"""AI-сводка по теме статистики: что пишут пользователи и что с этим делать.

Фоновая задача периодически смотрит, появилась ли по теме новая обратная связь:
оценка пользователя (`positive`/`negative`) или перевод в поддержку. Если появилась —
просит LLM пересказать статистику темы и эти отзывы и предложить, что поправить:
уточнить базу знаний или добавить динамическое правило (handrules) на частый вопрос.
Готовый текст кладётся в `topic_summaries` и показывается на странице темы под таблицей.

LLM здесь ничего не решает и никуда не пишет — это витрина. Поэтому во вход
уходят только вопросы пользователей и их отзывы; ответы агента в подсказку
не попадают (и лишнего объёма не добавляют).

Отпечаток `signature` считается по обратной связи темы: пока он не изменился,
сводка не пересчитывается и LLM не дёргается.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
from collections.abc import Iterable
from typing import Any

import feedback
import stats
from llama_index.core import Settings
from llama_index.core.base.llms.types import ChatMessage, MessageRole
from storage import ChatRecord, ChatStorage, get_storage

# Как часто проверять новые отзывы и пауза после старта (чтобы не мешать запуску).
import settings

POLL_SECONDS = settings.get_float("SUMMARY_POLL_SECONDS", 60.0)
FIRST_CHECK_DELAY = settings.get_float("SUMMARY_FIRST_DELAY", 10.0)
# Пауза между генерациями внутри одного прохода — не долбим LLM подряд.
GENERATE_PAUSE = settings.get_float("SUMMARY_GENERATE_PAUSE", 1.0)

# Чтобы подсказка оставалась короткой: длину вопроса и число отзывов режем.
MAX_QUESTION_LEN = 160
MAX_ITEMS = 30

# Служебные реплики оценки: это не вопрос пользователя, а его отзыв.
_SERVICE_TEXTS = frozenset(
    {feedback.POSITIVE_LABEL, feedback.NEGATIVE_LABEL, feedback.OPERATOR_LABEL, *feedback.REASONS}
)

# Версия промпта: входит в отпечаток, поэтому правка текста промпта автоматически
# пересчитывает все сводки (иначе старые остались бы в прежнем формате).
PROMPT_VERSION = "2"

SYSTEM_PROMPT = """Ты аналитик поддержки Портала поставщиков.
Тебе дают статистику по одной теме обращений и отзывы пользователей.
Ответь коротко, по-русски, в markdown: сначала абзац на 2—3 предложения о том, что
происходит, затем маркированный список из 1—2 пунктов — что уточнить в базе знаний
или какое динамическое правило добавить на частый вопрос.
Опирайся только на данные из запроса, не выдумывай цифры и функции. Заголовки не нужны."""

_task: asyncio.Task[None] | None = None

# Темы, по которым генерация идёт прямо сейчас (чтобы не запускать её дважды),
# и живые фоновые задачи — без ссылки на них asyncio может собрать задачу.
_INFLIGHT: set[str] = set()
_TASKS: set[asyncio.Task[Any]] = set()


# --------------------------------------------------------------------- данные


def _has_feedback(chat: ChatRecord) -> bool:
    """Обратная связь по чату: пользователь оценил ответ или обращение перевели."""
    return chat.rating in ("positive", "negative") or chat.is_closed


def feedback_chats(tree: Iterable[stats.StatsNode]) -> dict[str, list[ChatRecord]]:
    """По каждой теме — её чаты с обратной связью (пустые темы не попадают)."""
    result: dict[str, list[ChatRecord]] = {}
    for node in tree:
        chats = [chat for chat in stats.chats_of(node) if _has_feedback(chat)]
        if chats:
            result[node.name] = chats
    return result


def signature(chats: Iterable[ChatRecord]) -> str:
    """Отпечаток обратной связи темы: меняется — сводку пора пересчитать.

    Берём только то, что попадает в сводку: у какого чата какая оценка, причина
    и был ли перевод. Плюс версия промпта — чтобы его правка тоже сдвигала отпечаток.
    Обычные новые сообщения отпечаток не сдвигают.
    """
    payload = [
        PROMPT_VERSION,
        [
            [chat.id, chat.rating or "", chat.rating_reason or "", int(chat.is_closed)]
            for chat in sorted(chats, key=lambda item: item.id)
        ],
    ]
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def _question(store: ChatStorage, chat_id: str) -> str:
    """Первый содержательный вопрос пользователя в чате (без служебных реплик)."""
    record = store.get_chat(chat_id)
    if record is None:
        return ""
    for message in record.messages:
        if message.role != "user":
            continue
        text = " ".join((message.content or "").split())
        if text and text not in _SERVICE_TEXTS:
            return text[:MAX_QUESTION_LEN]
    return ""


def _review_text(chat: ChatRecord) -> str:
    """Отзыв чата по-человечески: что нажал пользователь и чем это закончилось."""
    if chat.rating == "positive":
        text = "спасибо за ответ"
    elif chat.rating == "negative":
        reason = (chat.rating_reason or "").strip()
        if reason == feedback.OPERATOR_LABEL:
            text = "ответ не подошёл, позвал оператора"
        elif reason:
            text = f"ответ не подошёл ({reason})"
        else:
            text = "ответ не подошёл"
    else:
        text = "оценки нет"
    if chat.is_closed:
        text += ", обращение перевели в поддержку"
    return text


def _avg(seconds: float | None) -> str:
    return "нет данных" if seconds is None else f"{seconds:.1f} с"


def build_payload(topic: str, node: stats.StatsNode, feedback_items: list[ChatRecord], store: ChatStorage) -> str:
    """Собирает текстовую подсказку: статистика темы + вопросы и отзывы.

    Ответы агента не добавляем — в этом и смысл, что сводка строится по тому,
    что писали и как оценили пользователи.
    """
    counts = stats.badge_counts(stats.chats_of(node))
    lines = [
        f"Тема: {topic}",
        "",
        "Статистика по теме:",
        f"- всего обращений: {node.count}",
        f"- среднее время ответа: {_avg(node.avg_seconds)}",
        f"- сказали спасибо: {counts.get(stats.BADGE_POSITIVE, 0)}",
        f"- ответ не подошёл: {counts.get(stats.BADGE_DISLIKE, 0)}",
        f"- перевели в поддержку без оценки: {counts.get(stats.BADGE_REDIRECT, 0)}",
        "",
        f"Обращения с обратной связью (вопрос → что произошло), всего {len(feedback_items)}:",
    ]
    for chat in feedback_items[:MAX_ITEMS]:
        question = _question(store, chat.id) or "вопрос не распознан"
        lines.append(f"- «{question}» → {_review_text(chat)}")
    if len(feedback_items) > MAX_ITEMS:
        lines.append(f"- …и ещё {len(feedback_items) - MAX_ITEMS} обращений")
    return "\n".join(lines)


# --------------------------------------------------------------------- модель


async def _complete(system: str, user: str) -> str:
    """Один вызов LLM. Вынесено отдельно, чтобы подменять в тестах."""
    response = await Settings.llm.achat(
        [
            ChatMessage(role=MessageRole.SYSTEM, content=system),
            ChatMessage(role=MessageRole.USER, content=user),
        ]
    )
    return (response.message.content or "").strip()


async def generate(
    topic: str, node: stats.StatsNode, feedback_items: list[ChatRecord], store: ChatStorage
) -> str:
    """Генерирует сводку по теме через LLM."""
    payload = build_payload(topic, node, feedback_items, store)
    return await _complete(SYSTEM_PROMPT, payload)


def topic_state(topic: str) -> dict[str, Any] | None:
    """Текущая сводка темы и её статус. None — темы с таким именем нет.

    Статусы:
      ready    — сводка есть и построена по текущей обратной связи;
      outdated — сводка есть, но появилась новая обратная связь;
      pending  — обратная связь есть, а сводки ещё нет (генерация не прошла);
      none     — обратной связи по теме нет, сводка не нужна.
    """
    store = get_storage()
    tree = stats.build_tree(stats.non_empty_chats())
    node = stats.find_topic(tree, topic)
    if node is None:
        return None
    chats = [chat for chat in stats.chats_of(node) if _has_feedback(chat)]
    saved = store.get_topic_summary(topic)
    if not chats:
        status = "none"
    elif saved is None:
        status = "pending"
    elif saved.signature == signature(chats):
        status = "ready"
    else:
        status = "outdated"
    return {
        "topic": topic,
        "status": status,
        "summary": saved.summary if saved is not None else None,
        "feedback_chats": len(chats),
        "updated_at": saved.updated_at if saved is not None else None,
    }


# ---------------------------------------------------------------- фоновая часть


async def _update(
    topic: str,
    node: stats.StatsNode,
    feedback_items: list[ChatRecord],
    store: ChatStorage,
    *,
    force: bool,
) -> bool:
    """Генерирует и сохраняет сводку темы. False — свежая уже была или LLM не ответил."""
    if topic in _INFLIGHT:
        return False
    mark = signature(feedback_items)
    saved = store.get_topic_summary(topic)
    if not force and saved is not None and saved.signature == mark:
        return False
    _INFLIGHT.add(topic)
    try:
        text = await generate(topic, node, feedback_items, store)
    except Exception:  # noqa: BLE001 — LLM может быть недоступен, это не фатально
        return False
    finally:
        _INFLIGHT.discard(topic)
    if not text:
        return False
    store.upsert_topic_summary(topic, text, mark)
    return True


async def refresh(*, force: bool = False) -> list[str]:
    """Пересчитывает сводки там, где появилась новая обратная связь.

    Возвращает имена обновлённых тем. Ошибки отдельных тем не роняют проход:
    фоновая задача не должна умирать из-за одного таймаута LLM.
    """
    store = get_storage()
    tree = stats.build_tree(stats.non_empty_chats())
    nodes = {node.name: node for node in tree}
    updated: list[str] = []
    for topic, feedback_items in feedback_chats(tree).items():
        node = nodes.get(topic)
        if node is None:
            continue
        if await _update(topic, node, feedback_items, store, force=force):
            updated.append(topic)
            if GENERATE_PAUSE > 0:
                await asyncio.sleep(GENERATE_PAUSE)
    return updated


async def update_topic(topic: str, *, force: bool = False) -> bool:
    """Пересчитывает сводку одной темы, если она устарела. True — сводка обновлена."""
    store = get_storage()
    tree = stats.build_tree(stats.non_empty_chats())
    node = stats.find_topic(tree, topic)
    if node is None:
        return False
    feedback_items = [chat for chat in stats.chats_of(node) if _has_feedback(chat)]
    if not feedback_items:
        return False
    return await _update(topic, node, feedback_items, store, force=force)


def schedule(topic: str) -> None:
    """Ставит обновление сводки в фон, не блокируя запрос (для REST-ручки)."""
    if topic in _INFLIGHT:
        return
    task = asyncio.create_task(update_topic(topic))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def _loop() -> None:
    await asyncio.sleep(FIRST_CHECK_DELAY)
    while True:
        with contextlib.suppress(Exception):
            await refresh()
        await asyncio.sleep(POLL_SECONDS)


def start_background() -> asyncio.Task[None] | None:
    """Запускает периодическую проверку обратной связи. None — если она выключена."""
    global _task
    if settings.get("SUMMARY_DISABLED"):
        return None
    _task = asyncio.create_task(_loop())
    return _task


async def stop_background() -> None:
    global _task
    # Отдельные задачи, поставленные REST-ручкой, тоже гасим.
    for pending in list(_TASKS):
        pending.cancel()
    for pending in list(_TASKS):
        with contextlib.suppress(asyncio.CancelledError):
            await pending
    _TASKS.clear()
    if _task is None:
        return
    _task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _task
    _task = None


__all__ = [
    "POLL_SECONDS",
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "build_payload",
    "feedback_chats",
    "generate",
    "refresh",
    "schedule",
    "signature",
    "start_background",
    "stop_background",
    "topic_state",
    "update_topic",
]
