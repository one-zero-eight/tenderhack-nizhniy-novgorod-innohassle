"""Статистика обращений: агрегация чатов по темам и подтемам.

Считает то, что поддержке важно видеть на экране: сколько обращений в каждой теме
и сколько в среднем занимает ответ агента. Пустые чаты (без сообщений) в статистику
не попадают — это брошенные «Новый чат», они только портят средние.

Здесь только данные, без разметки: страницы `/stats1` и `/stats2` рисуют из одного
и того же дерева, отличаются они лишь подачей — отдельные страницы тем против
единой таблицы с вложенными подтемами.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from storage import ChatRecord, get_storage
from topic_classifier import FALLBACK, TOPICS

# Заголовок группы для чатов, которые классификатор ещё не разобрал.
UNCLASSIFIED_TOPIC = "Без темы"
# Подтема-заглушка у чатов без темы: показывать там нечего, но группировать надо.
UNCLASSIFIED_SUBTOPIC = "—"

# Ключи сортировки, которые понимают страницы статистики.
SORT_COUNT = "count"
SORT_AVG = "avg"
SORT_KEYS = (SORT_COUNT, SORT_AVG)


@dataclass
class StatsNode:
    """Строка статистики: тема или подтема.

    name — название как его видит пользователь, count — сколько обращений (чатов),
    avg_seconds — среднее время ответа агента в секундах (None — измерений не было),
    chats — чаты строки (у подтемы заполнено, у темы — нет: там они лежат в подтемах).
    """

    name: str
    count: int
    avg_seconds: float | None
    chats: list[ChatRecord] = field(default_factory=list)
    subtopics: list[StatsNode] = field(default_factory=list)


def _average(chats: list[ChatRecord]) -> float | None:
    """Среднее время ответа по группе чатов.

    У чата это время его первого ответа, так что среднее по теме/подтеме
    показывает, как быстро в среднем реагировали на обращения. Чаты без
    измерений не учитываем — «нет данных» не должно разбавлять среднее нулями.
    """
    values = [chat.avg_turn_seconds for chat in chats if chat.avg_turn_seconds is not None]
    return sum(values) / len(values) if values else None


def non_empty_chats() -> list[ChatRecord]:
    """Все чаты, в которых есть хотя бы одно сообщение.

    Чаты без сообщений — это пустые заготовки (их создаёт кнопка «Новый чат»),
    в статистике они бессмысленны.
    """
    return [chat for chat in get_storage().list_chats(limit=1000) if chat.message_count > 0]


def _subtopic_order(topic: str) -> list[str]:
    """Порядок подтем как в topics.json. Для неизвестной темы — пусто."""
    for entry in TOPICS:
        if entry["topic"] == topic:
            return [sub["title"] for sub in entry.get("subtopics", [])]
    return []


def _topic_order() -> list[str]:
    """Порядок тем как в topics.json; неизвестные уедут в конец по алфавиту."""
    return [entry["topic"] for entry in TOPICS]


def _bucket(records: list[ChatRecord]) -> dict[str, dict[str, list[ChatRecord]]]:
    """Раскладывает чаты по теме → подтеме, подставляя заглушки вместо пустых меток."""
    by_topic: dict[str, dict[str, list[ChatRecord]]] = {}
    for record in records:
        topic = (record.topic or "").strip() or UNCLASSIFIED_TOPIC
        if topic == UNCLASSIFIED_TOPIC:
            subtopic = UNCLASSIFIED_SUBTOPIC
        else:
            subtopic = (record.subtopic or "").strip() or FALLBACK
        by_topic.setdefault(topic, {}).setdefault(subtopic, []).append(record)
    return by_topic


def _ordered_names(known: list[str], present: dict[str, Any], *, last: str | None = None) -> list[str]:
    """Сначала порядок из справочника, потом незнакомые по алфавиту, потом `last`."""
    ordered = [name for name in known if name in present]
    ordered += sorted(name for name in present if name not in known and name != last)
    if last is not None and last in present:
        ordered.append(last)
    return ordered


def build_tree(records: list[ChatRecord]) -> list[StatsNode]:
    """Дерево тем → подтем в порядке справочника, без пустых строк.

    Внутри подтемы чаты идут как их отдаёт хранилище — свежие сверху.
    """
    by_topic = _bucket(records)
    topics: list[StatsNode] = []
    for topic in _ordered_names(_topic_order(), by_topic, last=UNCLASSIFIED_TOPIC):
        subtopics_raw = by_topic[topic]
        subs: list[StatsNode] = []
        for subtopic in _ordered_names(_subtopic_order(topic), subtopics_raw):
            chats = subtopics_raw[subtopic]
            subs.append(
                StatsNode(
                    name=subtopic,
                    count=len(chats),
                    avg_seconds=_average(chats),
                    chats=chats,
                )
            )
        if not subs:
            continue
        # Чаты темы собираем из подтем: у самой темы своих чатов нет.
        topic_chats = [chat for sub in subs for chat in sub.chats]
        topics.append(
            StatsNode(
                name=topic,
                count=len(topic_chats),
                avg_seconds=_average(topic_chats),
                subtopics=subs,
            )
        )
    return topics


def find_topic(tree: list[StatsNode], topic: str) -> StatsNode | None:
    """Тема по имени (точное совпадение)."""
    for node in tree:
        if node.name == topic:
            return node
    return None


def sort_nodes(nodes: list[StatsNode], key: str, *, descending: bool = True) -> list[StatsNode]:
    """Сортирует строки по количеству обращений или по среднему времени ответа.

    Строки без измеренного времени всегда в конце — независимо от направления:
    «нет данных» не должно оказываться наверху при сортировке по времени.
    """
    if key == SORT_AVG:
        measured = [node for node in nodes if node.avg_seconds is not None]
        missing = [node for node in nodes if node.avg_seconds is None]
        measured.sort(key=lambda node: node.avg_seconds or 0.0, reverse=descending)
        return measured + missing
    return sorted(nodes, key=lambda node: node.count, reverse=descending)


def sort_chats(chats: list[ChatRecord], key: str, *, descending: bool = True) -> list[ChatRecord]:
    """Сортировка списка чатов подтемы — те же два ключа, что и у таблиц."""
    if key == SORT_AVG:
        measured = [chat for chat in chats if chat.avg_turn_seconds is not None]
        missing = [chat for chat in chats if chat.avg_turn_seconds is None]
        measured.sort(key=lambda chat: chat.avg_turn_seconds or 0.0, reverse=descending)
        return measured + missing
    # У чата «количество обращений» — это число его сообщений пользователя.
    return sorted(chats, key=lambda chat: chat.message_count, reverse=descending)


__all__ = [
    "SORT_AVG",
    "SORT_COUNT",
    "SORT_KEYS",
    "UNCLASSIFIED_SUBTOPIC",
    "UNCLASSIFIED_TOPIC",
    "StatsNode",
    "build_tree",
    "find_topic",
    "non_empty_chats",
    "sort_chats",
    "sort_nodes",
]
