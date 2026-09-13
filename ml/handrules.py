"""Handrules: правила-подсказки агенту, которые подмешиваются в системный промпт хода.

Зачем: агент иногда отвечает не так, как нужно поддержке (например, сразу переводит
обращение на линию, хотя проблему обещают починить). Такое поведение чинится правилом
«вопрос пользователя → что делать», а не правкой промпта.

    {"user_message": "Не могу открыть страницу портала закупок, мне возвращают ошибку 500",
     "instructions": "Не перенаправляй в поддержку: скажи, что мы уже работаем над проблемой, "
                     "и попроси зайти позже"}

Правила живут в таблице `handrules` (см. storage.py) и меняются CRUD'ом
(`/ml-api/handrules`, страница `/admin/handrules`).

Поиск — тот же fuse-подход, что был у RAG по мануалам: вектора (bge-m3) + BM25,
слияние относительных score. Корпус правил маленький и меняется редко, поэтому
индекс держится в памяти и пересобирается лениво — когда состав правил изменился
(см. `_corpus_hash`).

Перед каждым ходом `prompt_for(question)` достаёт до TOP_K близких правил
и рендерит их в блок системного промпта (`rag.build_agent(handrules_prompt=...)`).
Если правило подошло к нескольким вопросам подряд — ничего страшного: попадание
одних и тех же правил на каждый ход ожидаемо, это и есть их цель.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.core.schema import TextNode
from llama_index.core.vector_stores import MetadataFilters
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.vector_stores.chroma import ChromaVectorStore

import settings
from storage import HandRuleRecord, get_storage

HERE = Path(__file__).resolve().parent

# Индекс правил — отдельная chroma-коллекция, чтобы не путаться с мануалами (если
# RAG по мануалам когда-нибудь вернут — коллекции не пересекутся).
CHROMA_DIR = Path(settings.get("HANDRULES_CHROMA_DIR") or (HERE / "chroma_handrules"))
COLLECTION_NAME = "handrules"

# Сколько правил подмешивается в промпт одного хода.
TOP_K = 3
# Сколько кандидатов берёт каждый из ретриверов до слияния.
VECTOR_TOP_K = 8
BM25_TOP_K = 8

# Число запросов для QueryFusionRetriever. ДЕРЖАТЬ РАВНЫМ 1.
#
# При num_queries > 1 llama_index начнёт перефразировать запрос через LLM
# (`_get_queries` / `_aget_queries`) — лишний сетевой вызов DeepSeek на каждый ход.
# При 1 ретривер делает одно слияние: эмбеддинг запроса + BM25 + арифметика
# RELATIVE_SCORE, без обращения к модели. См. _build_index.
NUM_QUERIES = 1

# Ниже этой косинусной близости (bge-m3) правило считаем нерелевантным и не показываем.
# Нужно, чтобы на вопрос, которого нет среди правил, промпт не засорялся чужими
# инструкциями: пустой блок честнее случайного правила.
#
# Калибровка на живом корпусе: свои вопросы дали 0.48—0.62, посторонние
# («привет», «погода в африке», «борщ») — 0.26—0.34. 0.42 попадает в разрыв.
# Если правила станут длиннее и близость поедет, смотри /ml-api/handrules/search.
MIN_SCORE = 0.42


def _configure_embeddings() -> None:
    """Ставит модель эмбеддингов в глобальный Settings, если её там ещё нет.

    Загружается один раз на процесс (см. warmup): при `--reload` процесс
    пересоздаётся, и модель грузится заново — это ожидаемо, зато к моменту
    первого вопроса она уже готова.

    device=cpu по умолчанию: на macOS MPS падает в кернелах при повторном
    эмбеддинге (см. историю rag.py).

    Читаем `_embed_model` напрямую, а не через свойство `Settings.embed_model`:
    геттер при пустом значении пытается подсунуть OpenAI-модель и падает
    с ValueError, если нет OPENAI_API_KEY.
    """
    if getattr(Settings, "_embed_model", None) is not None:
        return
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    Settings.embed_model = HuggingFaceEmbedding(
        model_name=settings.get("EMBED_MODEL", "BAAI/bge-m3"),
        device=settings.get("EMBED_DEVICE", "cpu"),
    )


def _llm():
    """LLM, который QueryFusionRetriever требует в конструкторе.

    С `num_queries=1` он не вызывается (запросы не переписываются), и RELATIVE_SCORE
    тоже считает всё локально — модель нужна только чтобы llama_index не полез
    за дефолтной OpenAI-моделью и не падал без OPENAI_API_KEY.

    Берём уже настроенный в процессе Settings.llm (его ставит rag.py — агент и поиск
    ходят через одну модель). Если rag ещё не импортирован, поднимаем OpenAILike из тех
    же переменных окружения, чтобы не зависеть от порядка импортов.
    """
    if getattr(Settings, "_llm", None) is not None:
        return Settings.llm
    from llama_index.llms.openai_like import OpenAILike

    return OpenAILike(
        model=settings.llm_model(),
        api_base=settings.llm_base(),
        api_key=settings.llm_key(),
        is_chat_model=True,
        context_window=settings.llm_context_window(),
        is_function_calling_model=True,
        timeout=settings.llm_timeout(),
    )


def _node_text(rule: HandRuleRecord) -> str:
    """Что эмбеддится и индексируется BM25.

    `instructions` тоже в тексте: поиск идёт по вопросу, но если пользователь
    спрашивает «почему меня перевели в поддержку», правило про перевод всплывёт
    и по своей инструкции.
    """
    return f"{rule.user_message}\n{rule.instructions}"


def _nodes(rules: list[HandRuleRecord]) -> list[TextNode]:
    return [
        TextNode(
            id_=rule.id,
            text=_node_text(rule),
            metadata={"rule_id": rule.id, "user_message": rule.user_message},
        )
        for rule in rules
    ]


def _corpus_hash(rules: list[HandRuleRecord]) -> str:
    """Отпечаток состава правил: id + текст. Меняется — индекс пересобирается."""
    digest = hashlib.sha1()
    for rule in sorted(rules, key=lambda r: r.id):
        digest.update(rule.id.encode())
        digest.update(rule.user_message.encode())
        digest.update(rule.instructions.encode())
    return digest.hexdigest()


@dataclass
class _Index:
    """Индекс правил: fuse-ретривер для ранжирования + векторный для порога релевантности.

    Порог нужен отдельно, потому что RELATIVE_SCORE нормализует лучший результат
    к 1.0 всегда — даже когда ни одно правило не подходит («погода в африке» тоже
    получает 1.0). Абсолютную близость даёт только векторный поиск.
    """

    retriever: QueryFusionRetriever
    vector_retriever: object | None
    digest: str


_index: _Index | None = None


def _build_index(rules: list[HandRuleRecord], digest: str) -> _Index:
    """Пересобирает chroma-коллекцию целиком и собирает fuse-ретривер.

    Правил десятки, эмбеддинг дешёвый — пересборка «в лоб» проще и надёжнее,
    чем инкрементальные апдейты по одному правилу.
    """
    _configure_embeddings()
    import chromadb

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:  # noqa: BLE001 — коллекции ещё нет, это нормально
        pass
    collection = client.get_or_create_collection(COLLECTION_NAME)

    vector_store = ChromaVectorStore(chroma_collection=collection)
    nodes = _nodes(rules)
    if not nodes:
        # Правил нет: индексировать нечего, но валидный индекс нужен — на нём
        # держится проверка digest при следующем прогоне. BM25 на пустом списке падает.
        index = VectorStoreIndex.from_vector_store(
            vector_store, storage_context=StorageContext.from_defaults(vector_store=vector_store)
        )
        empty = index.as_retriever(similarity_top_k=1)
        return _Index(retriever=empty, vector_retriever=None, digest=digest)

    VectorStoreIndex(
        nodes,
        storage_context=StorageContext.from_defaults(vector_store=vector_store),
        show_progress=False,
    )
    index = VectorStoreIndex.from_vector_store(
        vector_store, storage_context=StorageContext.from_defaults(vector_store=vector_store)
    )
    top = min(VECTOR_TOP_K, len(nodes))
    vector_retriever = index.as_retriever(
        similarity_top_k=top,
        filters=MetadataFilters(filters=[]),
    )
    bm25 = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=min(BM25_TOP_K, len(nodes)))
    retriever = QueryFusionRetriever(
        retrievers=[vector_retriever, bm25],
        retriever_weights=[0.6, 0.4],
        similarity_top_k=min(TOP_K, len(nodes)),
        # 1 = без перефразировок через LLM, только слияние score. Менять осознанно:
        # при >1 каждый ход будет стоить лишний запрос к модели, а выигрыш на десятке
        # правил нулевой — формулировки и так покрыты парой «пример вопроса».
        num_queries=NUM_QUERIES,
        mode=FUSION_MODES.RELATIVE_SCORE,
        llm=_llm(),
        use_async=True,
    )
    return _Index(retriever=retriever, vector_retriever=vector_retriever, digest=digest)


def _ensure_index() -> tuple[_Index | None, list[HandRuleRecord]]:
    """Возвращает актуальный индекс (пересобирает при изменениях) и сами правила."""
    global _index
    rules = get_storage().list_handrules()
    if not rules:
        _index = None
        return None, []

    digest = _corpus_hash(rules)
    if _index is None or _index.digest != digest:
        _index = _build_index(rules, digest)
    return _index, rules


def invalidate() -> None:
    """Сбрасывает кеш индекса: следующий поиск пересоберёт его.

    Вызывается из CRUD — правила меняются редко, но после правки должны
    подхватываться сразу, а не после рестарта.
    """
    global _index
    _index = None


def warmup() -> bool:
    """Готовит эмбеддер и индекс заранее — на старте приложения.

    Без этого torch и веса bge-m3 грузятся лениво — прямо в первом ходе, и
    пользователь ждёт несколько секунд лишнего. Здесь мы платим это время при
    запуске, а не при первом вопросе. При `--reload` процесс пересоздаётся,
    поэтому прогрев повторяется — это нормально.

    Возвращает True, если модели/индекс готовы. Ошибку не пробрасываем: без
    правил приложение всё равно должно подняться (поиск просто вернёт пусто).
    """
    try:
        _configure_embeddings()
        _ensure_index()
    except Exception:  # noqa: BLE001 — прогрев не должен ломать старт
        return False
    return True


async def retrieve(question: str, k: int = TOP_K, min_score: float = MIN_SCORE) -> list[HandRuleRecord]:
    """Ищет до k правил, близких к вопросу пользователя (fuse: вектора + BM25).

    Порядок такой:
    1. векторный поиск даёт абсолютную близость (cosine) — по ней отсекаем всё,
       что ниже min_score. Это главный фильтр: без него на любой вопрос найдётся
       «лучшее» правило и промпт засорится мусором;
    2. если есть хотя бы один близкий кандидат — переранжируем через fuse
       (вектора + BM25): так точное совпадение слов в вопросе поднимает правило выше.

    Возвращает [] на пустой запрос, пустой корпус и когда ни одно правило
    не пробило порог близости.
    """
    query = " ".join((question or "").split()).strip()
    if not query:
        return []

    index, rules = _ensure_index()
    if index is None or not rules or index.vector_retriever is None:
        return []

    by_id = {rule.id: rule for rule in rules}
    try:
        vector_nodes = await index.vector_retriever.aretrieve(query)
    except Exception:  # noqa: BLE001 — поиск не должен ронять ход агента
        return []

    # Порог отсекает нерелевантное до слияния, чтобы fuse не «поднимал» шум.
    close = {
        str(node.metadata.get("rule_id") or node.node_id)
        for node in vector_nodes
        if node.score is not None and node.score >= min_score
    }
    if not close:
        return []

    try:
        fused = await index.retriever.aretrieve(query)
    except Exception:  # noqa: BLE001 — fuse — только улучшение порядка
        fused = []

    found: list[HandRuleRecord] = []
    seen: set[str] = set()
    # Сначала порядок fuse, затем — добор близкими кандидатами, которых fuse не вернул.
    for node in [*fused, *vector_nodes]:
        rule_id = str(node.metadata.get("rule_id") or node.node_id)
        rule = by_id.get(rule_id)
        if rule is None or rule.id in seen or rule.id not in close:
            continue
        seen.add(rule.id)
        found.append(rule)
        if len(found) >= k:
            break
    return found


def render_prompt(rules: list[HandRuleRecord]) -> str:
    """Блок системного промпта с найденными правилами. Пусто — пустая строка.

    Промпт намеренно строгий: правила — это то, что поддержка уже решила за агента,
    поэтому они перебивают общие указания промпта, но не факты из инструкций.
    """
    if not rules:
        return ""
    lines = [
        "# Правила ответа на этот вопрос",
        "",
        "Ниже — выдержки из правил поддержки, подобранные под текущий вопрос пользователя.",
        "Следуй им, даже если они расходятся с общими рекомендациями выше (кроме фактов"
        " из инструкций: не выдумывай того, чего в разделах нет).",
        "",
    ]
    for index, rule in enumerate(rules, start=1):
        lines.append(f"{index}. Если пользователь пишет что-то вроде: «{rule.user_message}»")
        lines.append(f"   → {rule.instructions}")
    return "\n".join(lines)


async def prompt_for(question: str, k: int = TOP_K) -> str:
    """Готовый блок промпта для вопроса пользователя (или пустая строка)."""
    return render_prompt(await retrieve(question, k=k))


# ------------------------------------------------------------------- CRUD-слой
#
# Тонкая обёртка над storage: описания и валидация полей в одном месте, чтобы
# REST API и админка не дублировали проверки.


class HandRuleError(ValueError):
    """Некорректное правило: пустой вопрос или пуста инструкция."""


def clean(value: str | None, *, limit: int = 4000) -> str:
    """Схлопывает пробелы и режет длину — одинаковая нормализация для API и UI."""
    return " ".join((value or "").split()).strip()[:limit]


def create(user_message: str, instructions: str) -> HandRuleRecord:
    message = clean(user_message)
    answer = clean(instructions)
    if not message or not answer:
        raise HandRuleError("Нужны оба поля: user_message и instructions")
    rule = get_storage().create_handrule(message, answer)
    invalidate()
    return rule


def get(rule_id: str) -> HandRuleRecord | None:
    return get_storage().get_handrule(rule_id)


def list_all(limit: int = 500) -> list[HandRuleRecord]:
    return get_storage().list_handrules(limit=limit)


def update(rule_id: str, user_message: str | None = None, instructions: str | None = None) -> HandRuleRecord | None:
    message = None if user_message is None else clean(user_message)
    answer = None if instructions is None else clean(instructions)
    if message == "" or answer == "":
        raise HandRuleError("Поля user_message и instructions не могут быть пустыми")
    rule = get_storage().update_handrule(rule_id, message, answer)
    if rule is not None:
        invalidate()
    return rule


def delete(rule_id: str) -> bool:
    removed = get_storage().delete_handrule(rule_id)
    if removed:
        invalidate()
    return removed


__all__ = [
    "MIN_SCORE",
    "NUM_QUERIES",
    "TOP_K",
    "HandRuleError",
    "clean",
    "create",
    "delete",
    "get",
    "invalidate",
    "list_all",
    "prompt_for",
    "render_prompt",
    "retrieve",
    "update",
]
