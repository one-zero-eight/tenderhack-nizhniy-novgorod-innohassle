"""Фоновая классификация обращения: тема + подтема.

Запускается один раз на чат — после первого ответа агента. Спрашивает у LLM тему и
подтему по паре «вопрос пользователя + ответ агента» и складывает результат в БД
(chats.topic / chats.subtopic).

Здесь намеренно НЕТ маппинга секций на темы: классификатор работает по тексту диалога,
поэтому подтемы размечаются так же, как темы, — просто как второй уровень выбора.

Задача фоновая и необязательная: любая ошибка глушится, чат без темы — валидное состояние.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx

import settings

HERE = Path(__file__).resolve().parent
TOPICS_FILE = HERE / "topics.json"

# Фолбэк, когда подходящей темы нет. Должен совпадать с topics.json.
FALLBACK = "Прочее"

# Локальные модели (и deepseek-flash) — reasoning: бюджет уходит на reasoning_content,
# поэтому max_tokens с запасом, а читаем только content.
MAX_TOKENS = 3000
RETRIES = 3
TIMEOUT = 120

# Сколько символов ответа отдавать модели. Хвост ответа не нужен, а лишний
# контекст только замедляет разбор.
ANSWER_LIMIT = 4000

SYSTEM = (
    "Ты классифицируешь обращения в поддержку Портала поставщиков (zakupki.mos.ru).\n"
    "Тебе дают вопрос пользователя и ответ консультанта. Определи ТЕМУ и ПОДТЕМУ обращения.\n"
    "\n"
    "Правила:\n"
    "- Подтема обязана быть из списка подтем выбранной темы — не придумывай свои.\n"
    "- Если ни одна тема не подходит, верни тему \"Прочее\" и подтему \"Прочее\".\n"
    "- Если тема подходит, а точной подтемы нет — бери наиболее близкую из этой темы.\n"
    "- Ориентируйся на суть вопроса, а не на отдельные слова.\n"
    "\n"
    "Ответ — строго JSON без markdown и пояснений:\n"
    '{"topic": "<тема>", "subtopic": "<подтема>"}'
)


def _topics() -> list[dict]:
    """Классификатор из topics.json. Отсутствие файла не должно ронять импорт."""
    if not TOPICS_FILE.exists():
        return []
    payload = json.loads(TOPICS_FILE.read_text(encoding="utf-8"))
    return payload.get("topics", [])


TOPICS: list[dict] = _topics()

# topic -> {подтемы в нижнем регистре: каноничное название}
_SUBTOPICS: dict[str, dict[str, str]] = {
    entry["topic"]: {sub["title"].strip().lower(): sub["title"] for sub in entry["subtopics"]}
    for entry in TOPICS
}
_TOPIC_NAMES: dict[str, str] = {entry["topic"].strip().lower(): entry["topic"] for entry in TOPICS}


def topics_block() -> str:
    """Список тем с подтемами — то, что видит модель."""
    return "\n".join(
        f'- {entry["topic"]}: ' + "; ".join(sub["title"] for sub in entry["subtopics"])
        for entry in TOPICS
    )


def normalize(topic: str | None, subtopic: str | None) -> tuple[str, str]:
    """Приводит ответ модели к паре из классификатора.

    Модель может вернуть верную подтему, но приписать её не той теме, или назвать
    подтему из другой темы. Тогда подтема ищется по всем темам — это лучше, чем
    потерять её и отдать «Прочее».
    """
    topic_raw = (topic or "").strip()
    sub_raw = (subtopic or "").strip()

    resolved_topic = _TOPIC_NAMES.get(topic_raw.lower())
    resolved_sub: str | None = None

    if resolved_topic is not None:
        resolved_sub = _SUBTOPICS.get(resolved_topic, {}).get(sub_raw.lower())

    if resolved_sub is None and sub_raw:
        # Подтема названа верно, но тема подобрана неверно — доверяем подтеме.
        for name, subs in _SUBTOPICS.items():
            found = subs.get(sub_raw.lower())
            if found is not None:
                resolved_topic = name
                resolved_sub = found
                break

    if resolved_topic is None:
        return FALLBACK, FALLBACK
    if resolved_sub is None:
        # Тема есть, подтема не распознана: «Прочее» на уровне подтемы честнее выдумки.
        return resolved_topic, FALLBACK
    return resolved_topic, resolved_sub


def parse(raw: str) -> dict:
    """Достаёт JSON из ответа модели (может быть в ``` или с текстом вокруг)."""
    text = (raw or "").strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1].removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _ask_llm(question: str, answer: str) -> str:
    """Один запрос к DeepSeek. Пустая строка, если не удалось."""
    base = settings.llm_base()
    key = settings.llm_key()
    model = settings.llm_model()
    if not key:
        # Раньше здесь был молчаливый return "", из-за чего недостижимый API
        # выглядел как «все обращения попадают в Прочее».
        print("Классификация: не задан LLM_API_KEY — тема не определена")
        return ""

    user = (
        f"Темы и подтемы:\n{topics_block()}\n\n"
        f"Вопрос пользователя:\n{question}\n\n"
        f"Ответ консультанта:\n{answer[:ANSWER_LIMIT]}\n\n"
        'Верни JSON {"topic": "...", "subtopic": "..."}'
    )

    last = ""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for attempt in range(RETRIES):
            try:
                response = await client.post(
                    base.rstrip("/") + "/chat/completions",
                    headers={"Authorization": "Bearer " + key},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": SYSTEM},
                            {"role": "user", "content": user},
                        ],
                        "max_tokens": MAX_TOKENS,
                        "temperature": 0,
                        "response_format": {"type": "json_object"},
                    },
                )
                if response.status_code != 200:
                    last = f"HTTP {response.status_code}"
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                choice = response.json()["choices"][0]
                content = choice["message"].get("content") or ""
                # Обрыв по длине — повтор, иначе рискуем получить неполный JSON.
                if choice.get("finish_reason") == "length" or not content.strip():
                    last = f"обрезанный ответ (finish_reason={choice.get('finish_reason')})"
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                return content
            except Exception as exc:  # noqa: BLE001 — классификация не критична
                last = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(2 * (attempt + 1))

    print(f"Классификация: запрос не удался ({last})")
    return ""


async def classify(question: str, answer: str) -> tuple[str, str]:
    """Возвращает пару (тема, подтема). При неудаче — («Прочее», «Прочее»)."""
    if not TOPICS:
        return FALLBACK, FALLBACK
    question = " ".join((question or "").split())
    answer = " ".join((answer or "").split())
    if not question:
        return FALLBACK, FALLBACK

    raw = await _ask_llm(question, answer)
    picked = parse(raw)
    return normalize(picked.get("topic"), picked.get("subtopic"))


async def classify_and_save(
    chat_id: str,
    question: str,
    answer: str,
    *,
    storage=None,
) -> tuple[str, str] | None:
    """Фоновая точка входа: классифицирует и пишет тему с подтемой в БД.

    Никогда не бросает исключений — вызывается из asyncio-задачи без ожидания.
    """
    from storage import get_storage

    store = storage or get_storage()
    try:
        topic, subtopic = await classify(question, answer)
    except Exception as exc:  # noqa: BLE001 — фон не должен падать
        print(f"Классификация {chat_id[:8]}: ошибка {type(exc).__name__}: {exc}")
        return None
    try:
        store.set_chat_topic(chat_id, topic, subtopic)
    except Exception as exc:  # noqa: BLE001
        print(f"Классификация {chat_id[:8]}: не удалось записать тему: {exc}")
        return None
    print(f"Классификация {chat_id[:8]}: {topic} / {subtopic}")
    return topic, subtopic


def start_background(chat_id: str, question: str, answer: str, *, storage=None) -> asyncio.Task | None:
    """Запускает классификацию отдельной задачей и сразу возвращает управление.

    Ссылку на задачу держим в множестве: иначе сборщик мусора может её прибрать,
    пока она ещё выполняется.
    """
    if not TOPICS:
        return None
    task = asyncio.create_task(classify_and_save(chat_id, question, answer, storage=storage))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return task


_TASKS: set[asyncio.Task] = set()


__all__ = [
    "FALLBACK",
    "TOPICS",
    "classify",
    "classify_and_save",
    "normalize",
    "parse",
    "start_background",
    "topics_block",
]
