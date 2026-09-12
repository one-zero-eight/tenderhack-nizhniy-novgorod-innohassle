"""Общий слой работы с чатами: SQLite + живой Context агента + SSE-события.

Используется и HTMX-админкой (app.py), и REST API (api.py).
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import nullcontext
from typing import Any

from llama_index.core import Settings
from llama_index.core.agent.workflow import AgentStream, ToolCall, ToolCallResult
from llama_index.core.base.llms.types import ChatMessage as LIChatMessage
from llama_index.core.base.llms.types import MessageRole
from llama_index.core.workflow import Context

from rag import build_agent, langfuse, propagate_attributes
from storage import DEFAULT_CHAT_TITLE, ChatRecord, ChatStorage, MessageRecord, get_storage
from support import SupportSession

_CHAT_LOCKS: dict[str, asyncio.Lock] = {}

# Как часто сохранять накопленный ответ (в символах), чтобы не писать в SQLite на каждый токен.
PERSIST_EVERY = 200


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
    """Генерирует название чата из текста вопроса. Без стриминга.

    При любой ошибке LLM возвращает обрезанный текст вопроса — название чата
    не должно ломать создание чата или отправку сообщения.
    """
    question = " ".join((text or "").split()).strip()
    if not question:
        return DEFAULT_CHAT_TITLE

    fallback = _title_from(question)
    try:
        # achat, а не acomplete: OpenAILike не принимает system_prompt в acomplete.
        response = await Settings.llm.achat(
            [
                LIChatMessage(role=MessageRole.SYSTEM, content=TITLE_SYSTEM_PROMPT),
                LIChatMessage(
                    role=MessageRole.USER,
                    content=f"Вопрос пользователя: {question}\n\nНазвание чата:",
                ),
            ]
        )
        raw = response.message.content or ""
    except Exception:  # noqa: BLE001 — название не критично, отдаём фолбэк
        return fallback

    title = _clean_title(raw)
    # Совсем короткий или пустой ответ считаем неудачей и берём вопрос.
    if len(title) < 3:
        return fallback
    return title


def _history(storage: ChatStorage, chat_id: str, exclude_message_id: str | None = None) -> list[LIChatMessage]:
    """Восстанавливает диалог из SQLite — нужен, если контекст потерян (рестарт процесса)."""
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


def create_chat(system_prompt: str | None = None, storage: ChatStorage | None = None) -> ChatRecord:
    prompt = (system_prompt or "").strip() or None
    return (storage or get_storage()).create_chat(system_prompt=prompt)


def get_chat(chat_id: str, storage: ChatStorage | None = None) -> ChatRecord | None:
    return (storage or get_storage()).get_chat(chat_id)


def list_chats(storage: ChatStorage | None = None) -> list[ChatRecord]:
    return (storage or get_storage()).list_chats()


class ChatClosedError(RuntimeError):
    """Чат уже переведён на линию поддержки — писать в него больше нельзя."""

    def __init__(self, line: str | None = None) -> None:
        self.line = line
        super().__init__("Чат закрыт: обращение переведено на линию поддержки")


async def prepare_turn(
    chat_id: str, text: str, storage: ChatStorage | None = None
) -> tuple[MessageRecord, MessageRecord, ChatRecord]:
    """Записывает пару user/assistant в БД, попутно задавая заголовок чата.

    Заголовок генерируется моделью из первого вопроса в чате — синхронно, до создания
    сообщений, чтобы название успело попасть в ответ и в список чатов.
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


async def stream_answer(
    chat_id: str,
    assistant_message: MessageRecord,
    *,
    storage: ChatStorage | None = None,
    extra_events: bool = True,
) -> AsyncIterator[str]:
    """Стримит ответ агента SSE-событиями: start/token/tool_call/tool_result/done.

    В БД пишется сразу, поэтому повторный GET чата отдаёт уже сохранённый текст.
    """
    store = storage or get_storage()
    lock = get_lock(chat_id)
    user_text = store.latest_user_text(chat_id, assistant_message.id)
    chat = store.get_chat(chat_id)
    # Сессия поддержки ловит transfer_to_support: по ней потом закрываем чат.
    support_session = SupportSession()
    turn_agent = build_agent(chat.system_prompt if chat else None, support_session=support_session)

    async with lock:
        # chat_history — всё до текущего вопроса; сам вопрос идёт в user_msg.
        history = _history(store, chat_id)
        if history and history[-1].role == "user":
            history = history[:-1]
        ctx = Context(turn_agent)
        handler = turn_agent.run(user_msg=user_text, chat_history=history, ctx=ctx)
        answer = ""
        persisted = ""
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
            store.update_message(assistant_message.id, answer)
            store.touch_chat(chat_id)
            raise
        except Exception as exc:  # noqa: BLE001 — ошибку показываем клиенту
            answer += f"\n\n[ошибка] {exc}"
            if extra_events:
                yield sse("error", {"message": str(exc)})
        finally:
            store.update_message(assistant_message.id, answer)
            store.touch_chat(chat_id)

        # Агент решил перевести обращение — закрываем чат, писать сюда больше нельзя.
        if support_session.redirect is not None:
            redirect = support_session.redirect
            store.redirect_chat(chat_id, redirect.line, redirect.reason or None)
            if extra_events:
                yield sse("redirect", {"line": redirect.line, "reason": redirect.reason})

        if extra_events:
            yield sse("done", {"message_id": assistant_message.id, "content": answer})


async def run_turn(chat_id: str, user_text: str, *, storage: ChatStorage | None = None) -> AsyncIterator[str]:
    """Полный ход: запись сообщений в БД + стрим ответа (для REST API)."""
    store = storage or get_storage()
    _user_message, assistant_message, _chat = await prepare_turn(chat_id, user_text, store)
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
            async for chunk in stream_answer(chat_id, assistant_message, storage=store):
                if chunk.startswith("event: done"):
                    break
                yield chunk
        if root is not None:
            saved = store.get_message(message_id)
            root.update(output=saved.content if saved else "")

    saved = store.get_message(message_id)
    yield sse("done", {"message_id": message_id, "content": saved.content if saved else ""})


__all__ = [
    "TITLE_MAX_LEN",
    "TITLE_SYSTEM_PROMPT",
    "create_chat",
    "generate_title",
    "get_chat",
    "get_lock",
    "get_storage",
    "list_chats",
    "prepare_turn",
    "run_turn",
    "sse",
    "stream_answer",
]
