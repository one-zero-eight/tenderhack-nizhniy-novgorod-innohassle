"""Статистика обращений: агрегация чатов по темам и подтемам.

Считает то, что поддержке важно видеть на экране: сколько обращений в каждой теме,
сколько в среднем занимает ответ агента и как распределились исходы — от зелёного
(«спасибо за ответ») до красного (ответ не подошёл и перевели в поддержку),
см. badge_kinds. Пустые чаты (без сообщений) в статистику не попадают — это брошенные
«Новый чат», они только портят средние.

Здесь только данные, без разметки: страницы `/stats1` и `/stats2` рисуют из одного
и того же дерева, отличаются они лишь подачей — отдельные страницы тем против
единой таблицы с вложенными подтемами.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from storage import ChatRecord, get_storage
from topic_classifier import FALLBACK, TOPICS

# Заголовок группы для чатов, которые классификатор ещё не разобрал.
UNCLASSIFIED_TOPIC = "Без темы"
# Подтема-заглушка у чатов без темы: показывать там нечего, но группировать надо.
UNCLASSIFIED_SUBTOPIC = "—"

# Метки в статистике. Зелёная — благодарность пользователя, она ортогональна
# проблемным: чат может быть одновременно зелёным и жёлтым (поблагодарил,
# но обращение всё равно перевели). Две проблемные взаимоисключающие:
#   redirect — просто перевод в поддержку (оценки нет);
#   dislike — пользователю не понравился ответ (был перевод или нет — всё равно он).
# Порядок, подписи и веса живут здесь, чтобы шаблоны и сортировка не разъезжались.
BADGE_POSITIVE = "positive"
BADGE_REDIRECT = "redirect"
BADGE_DISLIKE = "dislike"

BADGE_ORDER = (BADGE_POSITIVE, BADGE_REDIRECT, BADGE_DISLIKE)

BADGE_TITLES = {
    BADGE_POSITIVE: "Пользователь поблагодарил за ответ",
    BADGE_REDIRECT: "Переведён на линию поддержки",
    BADGE_DISLIKE: "Пользователю не понравился ответ",
}

# Короткие подписи для легенды под таблицей.
BADGE_LABELS = {
    BADGE_POSITIVE: "спасибо за ответ",
    BADGE_REDIRECT: "перевод в поддержку",
    BADGE_DISLIKE: "ответ не подошёл",
}

# Вклад метки в сортировку по проблемности: оранжевая = 2, жёлтая = 1.
# Зелёная — не проблема, поэтому весит 0 и на сортировку не влияет.
BADGE_WEIGHT = {
    BADGE_POSITIVE: 0,
    BADGE_REDIRECT: 1,
    BADGE_DISLIKE: 2,
}

# Ключи сортировки, которые понимают страницы статистики.
SORT_COUNT = "count"
SORT_AVG = "avg"
SORT_BADGES = "badges"
SORT_KEYS = (SORT_COUNT, SORT_AVG, SORT_BADGES)


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
    # Сколько чатов строки в каждой метке (см. badge_kind). Пусто — проблем нет.
    badges: dict[str, int] = field(default_factory=dict)


def badge_kind(chat: ChatRecord) -> str | None:
    """Проблемная метка чата: недовольство ответом или перевод в поддержку.

    Метки взаимоисключающие. Приоритет у оценки пользователя: чат с отрицательной
    оценкой — оранжевый, даже если его потом перевели в поддержку (просто перевод
    без оценки — жёлтый). Зелёная благодарность сюда не входит — она ортогональна
    и добавляется отдельно (см. badge_kinds).
    """
    if chat.rating == "negative":
        return BADGE_DISLIKE
    if chat.is_closed:
        return BADGE_REDIRECT
    return None


def badge_kinds(chat: ChatRecord) -> list[str]:
    """Все метки чата: зелёная (поблагодарил) плюс проблемная, если она есть."""
    kinds: list[str] = []
    if chat.rating == "positive":
        kinds.append(BADGE_POSITIVE)
    problem = badge_kind(chat)
    if problem is not None:
        kinds.append(problem)
    return kinds


def badge_counts(chats: list[ChatRecord]) -> dict[str, int]:
    """Сколько раз каждая метка встретилась в наборе (чаты без метки не считаются)."""
    counts: dict[str, int] = {}
    for chat in chats:
        for kind in badge_kinds(chat):
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def badge_score(counts: dict[str, int]) -> int:
    """Проблемность набора: сумма метк по весам (красная 3, оранжевая 2, жёлтая 1)."""
    return sum(BADGE_WEIGHT[kind] * number for kind, number in counts.items())


def filter_chats(chats: list[ChatRecord], kinds: Collection[str]) -> list[ChatRecord]:
    """Оставляет чаты, у которых есть хотя бы одна из выбранных метк.

    Пустой набор — фильтр выключен, возвращаются все чаты: так выглядит дефолт
    на страницах статистики (показываем всё, пока не нажали ни на один бейдж).
    """
    if not kinds:
        return chats
    wanted = set(kinds)
    return [chat for chat in chats if wanted.intersection(badge_kinds(chat))]


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
                    badges=badge_counts(chats),
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
                badges=badge_counts(topic_chats),
            )
        )
    return topics


def find_topic(tree: list[StatsNode], topic: str) -> StatsNode | None:
    """Тема по имени (точное совпадение)."""
    for node in tree:
        if node.name == topic:
            return node
    return None


def chats_of(node: StatsNode) -> list[ChatRecord]:
    """Все чаты строки: у подтемы — свои, у темы — собранные из подтем."""
    if node.chats:
        return node.chats
    return [chat for sub in node.subtopics for chat in sub.chats]


def sort_nodes(nodes: list[StatsNode], key: str, *, descending: bool = True) -> list[StatsNode]:
    """Сортирует строки по количеству обращений, среднему времени ответа или меткам.

    Строки без измеренного времени всегда в конце — независимо от направления:
    «нет данных» не должно оказываться наверху при сортировке по времени.
    Метки сортируются по сумме весов (красная 3, оранжевая 2, жёлтая 1).
    """
    if key == SORT_AVG:
        measured = [node for node in nodes if node.avg_seconds is not None]
        missing = [node for node in nodes if node.avg_seconds is None]
        measured.sort(key=lambda node: node.avg_seconds or 0.0, reverse=descending)
        return measured + missing
    if key == SORT_BADGES:
        return sorted(nodes, key=lambda node: badge_score(node.badges), reverse=descending)
    return sorted(nodes, key=lambda node: node.count, reverse=descending)


def sort_chats(chats: list[ChatRecord], key: str, *, descending: bool = True) -> list[ChatRecord]:
    """Сортировка списка чатов подтемы — те же ключи, что и у таблиц."""
    if key == SORT_AVG:
        measured = [chat for chat in chats if chat.avg_turn_seconds is not None]
        missing = [chat for chat in chats if chat.avg_turn_seconds is None]
        measured.sort(key=lambda chat: chat.avg_turn_seconds or 0.0, reverse=descending)
        return measured + missing
    if key == SORT_BADGES:
        # Чат без метки — вес 0: при убывании проблемные сверху.
        return sorted(
            chats, key=lambda chat: BADGE_WEIGHT.get(badge_kind(chat) or "", 0), reverse=descending
        )
    # У чата «количество обращений» — это число его сообщений пользователя.
    return sorted(chats, key=lambda chat: chat.message_count, reverse=descending)


__all__ = [
    "BADGE_DISLIKE",
    "BADGE_LABELS",
    "BADGE_ORDER",
    "BADGE_POSITIVE",
    "BADGE_REDIRECT",
    "BADGE_TITLES",
    "BADGE_WEIGHT",
    "SORT_AVG",
    "SORT_BADGES",
    "SORT_COUNT",
    "SORT_KEYS",
    "UNCLASSIFIED_SUBTOPIC",
    "UNCLASSIFIED_TOPIC",
    "StatsNode",
    "badge_counts",
    "badge_kind",
    "badge_kinds",
    "badge_score",
    "build_tree",
    "chats_of",
    "filter_chats",
    "find_topic",
    "non_empty_chats",
    "sort_chats",
    "sort_nodes",
]
