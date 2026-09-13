"""Общий слой работы с чатами: SQLite + живой Context агента + SSE-события.

Используется и HTMX-админкой (app.py), и REST API (api.py).
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import nullcontext
from time import monotonic
from typing import Any

from llama_index.core.agent.workflow import AgentStream, ToolCall, ToolCallResult
from llama_index.core.base.llms.types import ChatMessage as LIChatMessage
from llama_index.core.workflow import Context

# Нужны только для генерации названия через LLM (закомментирована в generate_title).
# from llama_index.core import Settings
# from llama_index.core.base.llms.types import MessageRole
import attachments as attachment_service
import handrules
from rag import build_agent, langfuse, propagate_attributes
from storage import DEFAULT_CHAT_TITLE, ChatRecord, ChatStorage, MessageRecord, get_storage
from support import SupportSession
from topic_classifier import start_background as start_topic_classification

_CHAT_LOCKS: dict[str, asyncio.Lock] = {}

# Роль пользователя из /profile → пометка в начале его сообщения.
# None (не указано) в словаре нет: тогда вопрос уходит как есть.
ROLE_LABELS = {
    "supplier": "я поставщик",
    "customer": "я заказчик",
}

# Как часто сохранять накопленный ответ (в символах), чтобы не писать в SQLite на каждый токен.
PERSIST_EVERY = 200

# Захардкоженные ответы (оценка чата) отдаются не сразу, а потоком: сначала пауза,
# потом слова с небольшой задержкой — так ответ выглядит живым, хотя LLM не вызывается.
SCRIPT_FIRST_DELAY = 1.0
SCRIPT_TOKEN_DELAY = 0.045

# Слово вместе с пробелами после него — единица «стриминга» захардкоженного ответа.
_SCRIPT_TOKEN_RE = re.compile(r"\S+\s*")


def get_lock(chat_id: str) -> asyncio.Lock:
    lock = _CHAT_LOCKS.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _CHAT_LOCKS[chat_id] = lock
    return lock


def _title_from(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:48] + ("…" if len(compact) > 48 else "")


# ---------------------------------------------------------------------- title

# Минимальный промпт: задача узкая, лишний контекст только мешает.
# Не используется, пока генерация названия через LLM закомментирована в generate_title.
TITLE_SYSTEM_PROMPT = (
    "Ты придумываешь короткое название для чата в поддержке Портала поставщиков.\n"
    "Ответь только названием, без кавычек, точек и пояснений.\n"
    "Требования: 3—7 слов, на русском, по сути вопроса. "
    "Не пиши «вопрос», «тема», «помощь» и подобное. Не отвечай на вопрос — только назови его."
)

# Ограничение на длину названия чата в списке и в интерфейсе.
TITLE_MAX_LEN = 64


def _clean_title(raw: str) -> str:
    """Приводит ответ модели к названию: без кавычек/точек/переносов и лишней длины."""
    title = " ".join((raw or "").split()).strip()
    # Снимаем обрамляющие кавычки, точки и тире, которые модель часто добавляет.
    title = re.sub(r"^[\"'«»„“”`.,;:!?\-—\s]+|[\"'«»„“”`.,;:!?\-—\s]+$", "", title)
    if len(title) > TITLE_MAX_LEN:
        title = title[:TITLE_MAX_LEN].rstrip(" ,;:—-")
    return title


async def generate_title(text: str) -> str:
    """Название чата из текста вопроса — просто обрезанный текст первого сообщения.

    Генерация через LLM закомментирована (на локальной модели лишний вызов
    заметно тормозит создание чата). Чтобы вернуть — раскомментируй блок ниже.
    """
    question = " ".join((text or "").split()).strip()
    if not question:
        return DEFAULT_CHAT_TITLE

    return _title_from(question)

    # --- Генерация названия через LLM (выключено) ---
    # fallback = _title_from(question)
    # try:
    #     # achat, а не acomplete: OpenAILike не принимает system_prompt в acomplete.
    #     response = await Settings.llm.achat(
    #         [
    #             LIChatMessage(role=MessageRole.SYSTEM, content=TITLE_SYSTEM_PROMPT),
    #             LIChatMessage(
    #                 role=MessageRole.USER,
    #                 content=f"Вопрос пользователя: {question}\n\nНазвание чата:",
    #             ),
    #         ]
    #     )
    #     raw = response.message.content or ""
    # except Exception:
    #     return fallback
    #
    # title = _clean_title(raw)
    # # Совсем короткий или пустой ответ считаем неудачей и берём вопрос.
    # if len(title) < 3:
    #     return fallback
    # return title


def _history(storage: ChatStorage, chat_id: str, exclude_message_id: str | None = None) -> list[LIChatMessage]:
    """Восстанавливает диалог из SQLite — нужен, если контекст потерян (рестарт процесса).

    Вложения прошлых ходов сюда не попадают: они удаляются из БД сразу после отправки,
    а `content` сообщения хранит только текст вопроса.
    """
    history: list[LIChatMessage] = []
    for message in storage.list_messages(chat_id):
        if message.id == exclude_message_id:
            break
        if message.role not in ("user", "assistant"):
            continue
        history.append(LIChatMessage(role=message.role, content=message.content or ""))
    return history


# --------------------------------------------------------------------- events


def sse(event: str, data: dict[str, Any] | str) -> str:
    """SSE-фрейм. dict сериализуется в JSON одной строкой, строка может быть многострочной."""
    if isinstance(data, str):
        payload = data
    else:
        payload = json.dumps(data, ensure_ascii=False, default=str)
    lines = payload.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return f"event: {event}\n" + "".join(f"data: {line}\n" for line in lines) + "\n"


def tool_event(storage: ChatStorage, message_id: str, record: Any, *, phase: str) -> dict[str, Any]:
    return {
        "type": "tool_call" if phase == "start" else "tool_result",
        "id": record.id,
        "name": record.name,
        "kwargs": record.kwargs,
        "output": record.output,
        "error": record.error,
    }


# ----------------------------------------------------------------------- chat


def create_chat(
    system_prompt: str | None = None,
    storage: ChatStorage | None = None,
    owner: str | None = None,
) -> ChatRecord:
    """Новый чат. owner — имя пользователя с /, у чатов /admin владельца нет."""
    prompt = (system_prompt or "").strip() or None
    return (storage or get_storage()).create_chat(system_prompt=prompt, owner=owner)


def get_chat(chat_id: str, storage: ChatStorage | None = None) -> ChatRecord | None:
    return (storage or get_storage()).get_chat(chat_id)


def delete_chat(chat_id: str, storage: ChatStorage | None = None) -> None:
    """Удаляет чат вместе с его вложениями.

    Строки `chat_files` уезжают каскадом, а оригиналы в `attachments/` надо убрать
    руками — иначе мусор останется навсегда (файлы ни на что не ссылаются).
    drop_originals сканирует <id>.json и сносит всё, что привязано к этому чату.
    """
    (storage or get_storage()).delete_chat(chat_id)
    attachment_service.drop_originals(chat_id)


def list_chats(storage: ChatStorage | None = None, owner: str | None = None) -> list[ChatRecord]:
    """Чаты. owner=None — все (для /admin), иначе — только чаты этого пользователя.

    Среднее время хода и число сообщений дописывает само хранилище
    (см. ChatStorage.list_chats) — сайдбар админки и статистика берут их оттуда.
    """
    return (storage or get_storage()).list_chats(owner=owner)


class ChatClosedError(RuntimeError):
    """Чат уже переведён на линию поддержки — писать в него больше нельзя."""

    def __init__(self, line: str | None = None) -> None:
        self.line = line
        super().__init__("Чат закрыт: обращение переведено на линию поддержки")


def _maybe_classify_topic(store: ChatStorage, chat_id: str, question: str, answer: str) -> None:
    """Запускает фоновую классификацию темы/подтемы, но только для первого ответа.

    Первый ответ — самый информативный для разбора обращения, а повторная
    классификация на каждом ходу стоила бы лишний запрос и перетирала метку.
    """
    if not answer.strip():
        return
    chat = store.get_chat(chat_id)
    if chat is None or chat.topic is not None:
        return
    # Больше одной пары user/assistant в чате — это не первый ход.
    answers = sum(1 for message in chat.messages if message.role == "assistant")
    if answers > 1:
        return
    start_topic_classification(chat_id, question, answer, storage=store)


async def prepare_turn(
    chat_id: str, text: str, storage: ChatStorage | None = None
) -> tuple[MessageRecord, MessageRecord, ChatRecord]:
    """Записывает пару user/assistant в БД, попутно задавая заголовок чата.

    Заголовок генерируется моделью из первого вопроса в чате — синхронно, до создания
    сообщений, чтобы название успело попасть в ответ и в список чатов.

    В `content` сообщения остаётся только текст вопроса: вложения описываются отдельно
    в `attachments` (см. stream_answer), а их файлы лежат в папке attachments/.
    """
    store = storage or get_storage()
    chat = store.get_chat(chat_id)
    if chat is None:
        raise KeyError(chat_id)
    if chat.is_closed:
        raise ChatClosedError(chat.redirect_line)
    # Первое сообщение в чате — самое время дать ему осмысленное название.
    if chat.title == DEFAULT_CHAT_TITLE and text:
        store.rename_chat(chat_id, await generate_title(text))
    user_message = store.add_message(chat_id, "user", text)
    assistant_message = store.add_message(chat_id, "assistant", "")
    updated = store.get_chat(chat_id)
    assert updated is not None
    return user_message, assistant_message, updated


def _with_role(text: str, role: str | None, *, first_turn: bool) -> str:
    """Дописывает роль пользователя к его сообщению — только на первом ходу чата.

    Роль идёт именно в user_msg, а не в системный промпт: системный промпт остаётся
    неизменным и кешируется провайдером, а роль может меняться в /profile между ходами.
    Повторять метку в каждом сообщении не нужно: она остаётся в истории первого
    вопроса, и модель видит её в контексте на всех последующих ходах. Это заодно
    сохраняет префикс запроса неизменным и не мешает prefix-кешу провайдера.
    При role=None ничего не добавляется и агент уточняет сам, как раньше.
    """
    if not first_turn:
        return text
    label = ROLE_LABELS.get(role or "")
    if not label:
        return text
    return f"[{label}] {text}"


def bind_attachments(
    chat_id: str,
    user_message_id: str,
    files: list[attachment_service.ChatFile] | None,
    *,
    storage: ChatStorage | None = None,
) -> None:
    """Переносит вложения из ожидающего контекста в историю сообщения.

    Оригиналы уже лежат в `attachments/<id>`, поэтому их достаточно описать в
    `messages.attachments` и вычистить строки из `chat_files` — в таблице остаётся
    только то, что ещё не улетело в модель.

    Вызывается синхронно до старта фоновой генерации: иначе страница успевает
    отрендериться раньше очистки, и файлы висят над композером до перезагрузки.
    """
    if not files:
        return
    store = storage or get_storage()
    store.set_message_attachments(user_message_id, [item.to_dict() for item in files])
    attachment_service.clear_files(chat_id)


async def stream_answer(
    chat_id: str,
    assistant_message: MessageRecord,
    *,
    storage: ChatStorage | None = None,
    extra_events: bool = True,
    user_role: str | None = None,
    files: list[attachment_service.ChatFile] | None = None,
    turn_hint: str | None = None,
) -> AsyncIterator[str]:
    """Стримит ответ агента SSE-событиями: start/token/tool_call/tool_result/done.

    В БД пишется сразу, поэтому повторный GET чата отдаёт уже сохранённый текст.
    Туда же ложится `duration_ms` — сколько заняла генерация ответа целиком
    (модель + вызовы инструментов), см. storage.set_message_duration.
    user_role ('supplier'/'customer'/None) дописывается к первому вопросу чата, см. _with_role.
    files — вложения, приложенные к этому ходу: картинки уходят как ImageBlock,
    документы — как markdown. Привязка к сообщению и очистка таблицы — в
    bind_attachments, вызывающем раньше (до рендера страницы).
    turn_hint — служебная подсказка модели (оценка ответа, запрос оператора):
    дописывается к вопросу только для этого хода и в истории чата не сохраняется.
    """
    store = storage or get_storage()
    lock = get_lock(chat_id)
    raw_user_text = store.latest_user_text(chat_id, assistant_message.id)
    chat = store.get_chat(chat_id)
    # Правила-подсказки под этот вопрос: топ-3 близких по fuse-поиску (см. handrules.py).
    # Могут повторяться ход за ходом — это ожидаемо и не мешает.
    rules_prompt = await handrules.prompt_for(raw_user_text)
    # Сессия поддержки ловит transfer_to_support: по ней потом закрываем чат.
    support_session = SupportSession()
    turn_agent = build_agent(
        chat.system_prompt if chat else None,
        support_session=support_session,
        handrules_prompt=rules_prompt,
    )

    async with lock:
        # chat_history — всё до текущего вопроса; сам вопрос идёт в user_msg.
        history = _history(store, chat_id)
        # Метка роли — только на первый ход чата: дальше она уже есть в истории
        # и в каждом сообщении не нужна (см. _with_role).
        user_text = _with_role(raw_user_text, user_role, first_turn=not history)
        # Служебная подсказка хода — только для модели: в истории чата её нет.
        if turn_hint:
            user_text = f"{user_text}\n\n{turn_hint}"
        user_msg = attachment_service.build_user_message(user_text, files or [])
        if history and history[-1].role == "user":
            history = history[:-1]
        ctx = Context(turn_agent)
        handler = turn_agent.run(user_msg=user_msg, chat_history=history, ctx=ctx)
        answer = ""
        persisted = ""
        # Время генерации ответа: от старта хода до последнего токена. Вызовы
        # инструментов входят в интервал — пауза на тулкол тоже время генерации.
        started_at = monotonic()
        duration_ms = 0
        try:
            async for event in handler.stream_events():
                if isinstance(event, ToolCall):
                    record = store.add_tool_call(
                        assistant_message.id, event.tool_id, event.tool_name, event.tool_kwargs or {}
                    )
                    if extra_events:
                        yield sse("tool_call", tool_event(store, assistant_message.id, record, phase="start"))
                elif isinstance(event, ToolCallResult):
                    output = event.tool_output.content if event.tool_output is not None else ""
                    is_error = bool(event.tool_output is not None and event.tool_output.is_error)
                    store.finish_tool_call(assistant_message.id, event.tool_id, output, is_error)
                    saved = store.get_message(assistant_message.id)
                    record = next((t for t in (saved.tools if saved else []) if t.id == event.tool_id), None)
                    if extra_events and record is not None:
                        yield sse("tool_result", tool_event(store, assistant_message.id, record, phase="end"))
                elif isinstance(event, AgentStream):
                    if event.tool_calls or not event.delta:
                        continue
                    answer += event.delta
                    # Пишем в БД инкрементально (не каждый токен), чтобы при обрыве
                    # соединения клиент всё равно получил уже сгенерированный текст.
                    if len(answer) - len(persisted) >= PERSIST_EVERY:
                        store.update_message(assistant_message.id, answer)
                        persisted = answer
                    if extra_events:
                        yield sse("token", {"delta": event.delta, "content": answer})
            await handler
        except asyncio.CancelledError:
            # Клиент отвалился (закрыл вкладку/таймаут) — сохраняем то, что успели.
            # Время генерации запишет finally ниже.
            store.update_message(assistant_message.id, answer)
            store.touch_chat(chat_id)
            raise
        except Exception as exc:  # noqa: BLE001 — ошибку показываем клиенту
            answer += f"\n\n[ошибка] {exc}"
            if extra_events:
                yield sse("error", {"message": str(exc)})
        finally:
            store.update_message(assistant_message.id, answer)
            # Момент фиксируем до классификации темы и редиректа: это служебные шаги,
            # в время генерации ответа они не входят.
            duration_ms = round((monotonic() - started_at) * 1000)
            store.set_message_duration(assistant_message.id, duration_ms)
            store.touch_chat(chat_id)

        # Тема и подтема обращения — один раз на чат, после первого ответа агента.
        # Задача фоновая: на стрим и на пользователя не влияет.
        _maybe_classify_topic(store, chat_id, user_text, answer)

        # Агент решил перевести обращение — закрываем чат, писать сюда больше нельзя.
        if support_session.redirect is not None:
            redirect = support_session.redirect
            store.redirect_chat(chat_id, redirect.line, redirect.reason or None)
            if extra_events:
                yield sse("redirect", {"line": redirect.line, "reason": redirect.reason})

        if extra_events:
            yield sse("done", {"message_id": assistant_message.id, "content": answer, "duration_ms": duration_ms})


def _script_tokens(text: str) -> list[str]:
    """Режет текст на «токены» для стриминга: слово вместе с пробелами после него."""
    tokens = _SCRIPT_TOKEN_RE.findall(text or "")
    return tokens or [text]


async def stream_scripted(
    chat_id: str,
    assistant_message: MessageRecord,
    text: str,
    *,
    storage: ChatStorage | None = None,
    extra_events: bool = True,
    first_delay: float = SCRIPT_FIRST_DELAY,
    token_delay: float = SCRIPT_TOKEN_DELAY,
) -> AsyncIterator[str]:
    """Стримит захардкоженный ответ без вызова LLM (реакция на оценку чата).

    Отдаёт те же SSE-события, что и stream_answer (token/done), поэтому клиент и
    интерфейс не отличают такой ответ от ответа модели. Пауза перед началом и
    задержка между словами делают отдачу похожей на генерацию.
    """
    store = storage or get_storage()
    async with get_lock(chat_id):
        started_at = monotonic()
        if first_delay > 0:
            await asyncio.sleep(first_delay)
        answer = ""
        try:
            for token in _script_tokens(text):
                answer += token
                store.update_message(assistant_message.id, answer)
                if extra_events:
                    yield sse("token", {"delta": token, "content": answer})
                if token_delay > 0:
                    await asyncio.sleep(token_delay)
        finally:
            # При обрыве сохраняем то, что успели отдать, вместе со временем отдачи.
            duration_ms = round((monotonic() - started_at) * 1000)
            store.update_message(assistant_message.id, answer)
            store.set_message_duration(assistant_message.id, duration_ms)
            store.touch_chat(chat_id)
        if extra_events:
            yield sse("done", {"message_id": assistant_message.id, "content": answer, "duration_ms": duration_ms})


async def run_turn(
    chat_id: str,
    user_text: str,
    *,
    storage: ChatStorage | None = None,
    files: list[attachment_service.ChatFile] | None = None,
) -> AsyncIterator[str]:
    """Полный ход: запись сообщений в БД + стрим ответа (для REST API).

    files — вложения, ожидающие отправки (см. attachments.list_files). Сразу после
    записи вопроса они переносятся в историю сообщения, а таблица ожидающего контекста чистится.
    """
    store = storage or get_storage()
    user_message, assistant_message, _chat = await prepare_turn(chat_id, user_text, store)
    bind_attachments(chat_id, user_message.id, files, storage=store)
    message_id = assistant_message.id
    yield sse("start", {"message_id": message_id})

    trace_cm = (
        langfuse.start_as_current_observation(as_type="agent", name="chat-response", input=user_text)
        if langfuse is not None
        else nullcontext()
    )
    attrs_cm = (
        propagate_attributes(trace_name="chat-response", session_id=chat_id) if langfuse is not None else nullcontext()
    )
    with trace_cm as root:
        with attrs_cm:
            async for chunk in stream_answer(
                chat_id, assistant_message, storage=store, files=files
            ):
                if chunk.startswith("event: done"):
                    break
                yield chunk
        if root is not None:
            saved = store.get_message(message_id)
            root.update(output=saved.content if saved else "")

    saved = store.get_message(message_id)
    yield sse(
        "done",
        {
            "message_id": message_id,
            "content": saved.content if saved else "",
            "duration_ms": saved.duration_ms if saved and saved.duration_ms is not None else 0,
        },
    )


__all__ = [
    "TITLE_MAX_LEN",
    "TITLE_SYSTEM_PROMPT",
    "attachment_service",
    "bind_attachments",
    "create_chat",
    "delete_chat",
    "generate_title",
    "get_chat",
    "get_lock",
    "get_storage",
    "list_chats",
    "prepare_turn",
    "run_turn",
    "sse",
    "stream_answer",
    "stream_scripted",
]
