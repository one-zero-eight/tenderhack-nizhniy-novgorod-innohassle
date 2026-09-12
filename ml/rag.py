"""Индексация мануалов и агент по инструкциям Портала поставщиков.

- один TextNode на раздел (без чанкинга), метаданные: manual, manual_title, id, heading, children
- fuse-поиск (вектора + BM25) внутри выбранного мануала
- агент видит только список мануалов и ходит по ним инструментами search/open
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.core.agent.workflow import AgentWorkflow
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.core.schema import TextNode
from llama_index.core.tools import BaseTool, FunctionTool
from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.openai_like import OpenAILike
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.vector_stores.chroma import ChromaVectorStore

from manuals import (
    JSONS_DIR,
    Manual,
    Section,
    load_manuals,
    manuals_overview,
    render_section,
    render_tree,
    resolve_manual,
)
from support import SupportSession, support_manual

load_dotenv(Path(__file__).resolve().parent / ".env")

from langfuse import get_client, propagate_attributes
from openinference.instrumentation.llama_index import LlamaIndexInstrumentor

HERE = Path(__file__).resolve().parent
CHROMA_DIR = HERE / "chroma_db"
COLLECTION_NAME = "portal_manuals"
CORPUS_HASH_FILE = CHROMA_DIR / "corpus.sha1"

TOP_K = 6  # сколько разделов возвращает поиск
VECTOR_TOP_K = 8
BM25_TOP_K = 8

# device=cpu по умолчанию: собранный на macOS torch падает в MPS-кернелах
# (copy_cast_kernel_mps, SIGSEGV) при повторном эмбеддинге. На CPU — медленнее,
# но стабильно; можно вернуть MPS через EMBED_DEVICE=mps.
Settings.embed_model = HuggingFaceEmbedding(
    model_name=os.getenv("EMBED_MODEL", "BAAI/bge-m3"),
    device=os.getenv("EMBED_DEVICE", "cpu"),
)
Settings.llm = OpenAILike(
    model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
    api_base=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1"),
    api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    is_chat_model=True,
    context_window=128_000,
    is_function_calling_model=True,
)

langfuse = None
if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
    LlamaIndexInstrumentor().instrument()
    langfuse = get_client()
else:
    print("Langfuse: LANGFUSE_PUBLIC_KEY/SECRET_KEY не заданы — трейсинг выключен.")

chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))


def _corpus_hash() -> str:
    digest = hashlib.sha1()
    for path in sorted(JSONS_DIR.glob("*.json")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _nodes(manual: Manual) -> list[TextNode]:
    """Раздел -> нода. Текст берём как есть, без чанкинга."""
    return [
        TextNode(
            id_=f"{section.manual}::{section.id}",
            text=section.text or section.heading or section.id,
            metadata={
                "manual": section.manual,
                "manual_title": section.manual_title,
                "id": section.id,
                "heading": section.heading,
                "children": json.dumps(list(section.children), ensure_ascii=False),
            },
        )
        for section in manual.sections.values()
    ]


class Retriever:
    """Fuse-поиск (вектора + BM25) по разделам всех мануалов сразу."""

    def __init__(self, manuals: dict[str, Manual], vector_store: ChromaVectorStore) -> None:
        self.manuals = manuals
        self.index = VectorStoreIndex.from_vector_store(
            vector_store, storage_context=StorageContext.from_defaults(vector_store=vector_store)
        )
        self.bm25 = {
            slug: BM25Retriever.from_defaults(nodes=_nodes(manual), similarity_top_k=BM25_TOP_K)
            for slug, manual in manuals.items()
        }

    def _fusion(self, slug: str) -> QueryFusionRetriever:
        vector = self.index.as_retriever(
            similarity_top_k=VECTOR_TOP_K,
            filters=MetadataFilters(filters=[ExactMatchFilter(key="manual", value=slug)]),
        )
        return QueryFusionRetriever(
            retrievers=[vector, self.bm25[slug]],
            retriever_weights=[0.6, 0.4],
            similarity_top_k=TOP_K,
            num_queries=1,
            mode=FUSION_MODES.RELATIVE_SCORE,
            use_async=True,
        )

    async def find_ids(self, slug: str, query: str) -> list[str]:
        nodes = await self._fusion(slug).aretrieve(query)
        seen: list[str] = []
        for node in nodes:
            node_id = str(node.metadata.get("id", ""))
            if node_id and node_id not in seen:
                seen.append(node_id)
        return seen

    async def find_across_manuals(self, query: str) -> dict[str, list[str]]:
        """Ищет по всем мануалам сразу. Возвращает slug -> id найденных разделов."""
        results: dict[str, list[str]] = {}
        for slug in self.manuals:
            ids = await self.find_ids(slug, query)
            if ids:
                results[slug] = ids
        return results


def _fresh_collection():
    with contextlib.suppress(Exception):  # коллекции ещё нет — это нормально
        chroma_client.delete_collection(COLLECTION_NAME)
    return chroma_client.get_or_create_collection(COLLECTION_NAME)


def build_index(force: bool = False) -> Retriever:
    """Пересобирает chroma, если jsons/ изменились (или force=True).

    Эмбеддинги считаются долго (минуты), поэтому вызывать лучше в фоне —
    см. app._reindex_job.
    """
    global retriever

    manuals = load_manuals()
    digest = _corpus_hash()
    cached = CORPUS_HASH_FILE.read_text().strip() if CORPUS_HASH_FILE.exists() else ""
    collection = chroma_client.get_or_create_collection(COLLECTION_NAME)

    if force or cached != digest or collection.count() == 0:
        if cached != digest or force:
            collection = _fresh_collection()
        vector_store = ChromaVectorStore(chroma_collection=collection)
        nodes = [node for manual in manuals.values() for node in _nodes(manual)]
        VectorStoreIndex(
            nodes,
            storage_context=StorageContext.from_defaults(vector_store=vector_store),
            show_progress=True,
        )
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        CORPUS_HASH_FILE.write_text(digest)
        print(f"Индекс собран: {len(manuals)} мануалов, {len(nodes)} разделов.")
    else:
        vector_store = ChromaVectorStore(chroma_collection=collection)

    retriever = Retriever(manuals, vector_store)
    return retriever


def state() -> tuple[dict[str, Manual], Retriever]:
    return retriever.manuals, retriever


def _manuals_hint(manuals: dict[str, Manual]) -> str:
    return "\n".join(f"- {m.slug} — {m.title}" for m in manuals.values())


async def search(query: str) -> str:
    """Найти разделы по всем инструкциям сразу (гибридный поиск: эмбеддинги + BM25).

    Вызывай первым делом на ЛЮБОЙ вопрос, даже если кажется, что он не про Портал.
    Возвращает только структуру (без текста), сгруппированную по мануалам:
    id и заголовки найденных разделов плюс их родители. Чтобы прочитать раздел,
    вызови open(manual, section_id), где manual — slug мануала из заголовка группы.

    query — запрос на русском, лучше словами из инструкции («котировочная сессия»,
    «электронное исполнение», «заявка на банковскую гарантию»).
    """
    manuals, retriever = state()
    if not (query or "").strip():
        return "Пустой запрос: сформулируй, что именно искать."

    grouped = await retriever.find_across_manuals(query)
    if not grouped:
        return (
            f"По запросу «{query}» ничего не найдено ни в одной инструкции. "
            "Попробуй другие ключевые слова."
        )

    blocks: list[str] = []
    total = 0
    for slug, ids in grouped.items():
        manual = manuals[slug]
        total += len(ids)
        blocks.append(
            f"[{slug}] — {manual.title} ({len(ids)} разделов):\n{render_tree(manual, ids)}"
        )
    return (
        f"Найдено {total} разделов в {len(grouped)} мануалах по запросу «{query}»:\n\n"
        + "\n\n".join(blocks)
        + "\n\nПрочитай нужный раздел: open('<slug из [скобок]>', '<id>')."
    )


def _resolve_section(manual: Manual, section_id: str) -> Section | list[str]:
    key = " ".join((section_id or "").split()).strip().rstrip(".")
    if "::" in key:
        key = key.rsplit("::", 1)[1]
    key = key.removeprefix(f"{manual.slug}:").strip()
    if key in manual.sections:
        return manual.sections[key]
    if key.lower() == "root":
        return manual.sections["root"]
    wanted = key.lower()
    exact = [s for s in manual.sections.values() if s.heading.lower() == wanted]
    if len(exact) == 1:
        return exact[0]
    loose = [s for s in manual.sections.values() if wanted and wanted in s.heading.lower()]
    if len(loose) == 1:
        return loose[0]
    return [s.id for s in loose[:10]]


def open(manual: str, section_id: str) -> str:  # имя инструмента задано агенту
    """Прочитать раздел мануала по id: текст, заголовок и список подразделов.

    manual — slug мануала, section_id — id из search или 'root' для верхнего уровня.
    Возвращает текст раздела целиком (в нём могут быть markdown-таблицы и ссылки
    на картинки вида ![подпись](__IMG_PREFIX__/<slug>/image-N.png)).
    """
    manuals, _ = state()
    found = resolve_manual(manuals, manual)
    if found is None:
        return f"Мануал '{manual}' не найден. Доступные мануалы:\n{_manuals_hint(manuals)}"

    resolved = _resolve_section(found, section_id)
    if isinstance(resolved, list):
        if not resolved:
            return (
                f"В мануале «{found.title}» нет раздела '{section_id}'. "
                f"Возьми id из search(manual, query) или открой верхний уровень: open('{found.slug}', 'root')."
            )
        listed = "\n".join(f"- {found.sections[i].title_line}" for i in resolved)
        return f"Точного id '{section_id}' нет, похожие разделы:\n{listed}\n\nВызови open с нужным id."
    return render_section(found, resolved)


SYSTEM_PROMPT = """Ты — консультант по Порталу поставщиков (zakupki.mos.ru).
Отвечай на русском, только по содержимому инструкций. Не выдумывай функции и кнопки,
которых нет в прочитанных разделах.

Тебе доступны инструкции (список ниже) и четыре инструмента:

1. search(query) — ищет сразу по ВСЕМ инструкциям и группирует результат по ним.
   Возвращает только структуру (id и заголовки), без текста.
2. open(manual, section_id) — читает раздел: заголовок, подразделы и полный текст.
3. support_manual() — мануал по линиям поддержки: куда переводить какие вопросы.
4. transfer_to_support(line, reason) — перевод обращения на линию L1/L2/L3.

Как работать:
0. Ниже — список инструкций, они только для справки, искать по ним не нужно:
{manuals}
1. ВСЕГДА начинай с search(query) — даже если кажется, что вопрос не про Портал закупок.
   Формулируй query словами из инструкции («котировочная сессия», «электронное
   исполнение», «заявка на банковскую гарантию»). Если с первого раза пусто —
   переформулируй и попробуй ещё раз-два разными словами.
2. Открой нужный раздел: open(manual, section_id) — manual бери из [скобок] в выдаче search.
3. Если раздел родительский или не тот — открой его подразделы из children или уточни поиск.
4. Отвечай по прочитанному тексту. Не показывай пользователю служебное: id, slug'и,
   имена инструментов, но можешь называть раздел по заголовку («раздел «Работа с ответами банков»»).
5. Если в разделе есть картинки — вставляй их в ответ отдельной строкой в том виде,
   как они даны: ![подпись](/ml-assets/image/<slug>/image-N.png). Интерфейс умеет их показывать.
   Ставь картинку рядом с тем шагом, который она иллюстрирует.
6. Если пользователь спрашивает про заказчика — бери мануал заказчика, если про поставщика —
   мануал поставщика; если непонятно, уточни или посмотри в обоих.

Если ответа в базе знаний нет:
1. Вызови support_manual() и посмотри, есть ли там линия под такой вопрос.
   Мануал в контекст не подгружается заранее — достаёшь его только когда нужно.
2. Если подходящая линия есть — вызови transfer_to_support(line, reason).
   Это завершит чат: напиши пользователю, что вопрос передан на линию, назови линию
   человеческими словами (например «вторая линия, экспертно-методологическая»)
   и скажи, что скоро ответит специалист. Не называй это «L2» в тексте ответа.
3. Если вопрос вообще не относится к Порталу поставщиков и в мануале нет подходящей
   линии — НЕ вызывай transfer_to_support. Вежливо скажи, что вопрос не по теме Портала
   поставщиков и ты можешь помочь только с работой на Портале.
4. Не переводи вопрос на линию, если ответ есть в инструкциях. И не переводи
   однотипный «как сделать X» вопрос — сначала убедись, что инструкции не покрывают его.

Как отвечать:
- Отвечай кратко. По умолчанию — 2–5 предложений или небольшой список, без вступлений
  вроде «Отличный вопрос» и без пересказа всего раздела.
- Если вопрос обширный (несколько сценариев сразу, «расскажи всё про…», задача с ветвлениями),
  НЕ вываливай длинный ответ. Дай краткую суть (пара предложений) и задай уточняющий вопрос:
  что именно интересует, заказчик или поставщик, какой шаг застрял.
- Развёрнутый ответ давай только если пользователь явно об этом попросил («подробно»,
  «пошагово», «полный ответ», «ничего не сокращай») или если без деталей ответ будет неверным.
"""


retriever: Retriever = build_index()

# Базовый системный промпт уже с подставленными мануалами.
BASE_SYSTEM_PROMPT = SYSTEM_PROMPT.format(manuals=_manuals_hint(retriever.manuals))

agent = AgentWorkflow.from_tools_or_functions(
    [search, open],
    llm=Settings.llm,
    system_prompt=BASE_SYSTEM_PROMPT,
)


def build_agent(
    extra_system_prompt: str | None = None,
    support_session: SupportSession | None = None,
) -> AgentWorkflow:
    """Собирает агента под конкретный чат.

    extra_system_prompt дописывается к базовому (не заменяет его).
    support_session добавляет инструменты support_manual/transfer_to_support,
    причём перевод запоминается в сессии — по ней чат потом закрывается.
    """
    parts = [BASE_SYSTEM_PROMPT]
    extra = (extra_system_prompt or "").strip()
    if extra:
        parts.append(extra)

    if support_session is None and len(parts) == 1:
        return agent

    raw_tools: list = [search, open, support_manual]
    if support_session is not None:
        raw_tools.append(support_session.transfer_to_support)
    tools = [t if isinstance(t, BaseTool) else FunctionTool.from_defaults(fn=t) for t in raw_tools]

    original = agent.agents[agent.root_agent]
    clone = original.model_copy(
        update={"system_prompt": "\n\n".join(parts), "tools": tools},
        deep=False,
    )
    return AgentWorkflow(agents=[clone], root_agent=clone.name)


__all__ = [
    "BASE_SYSTEM_PROMPT",
    "agent",
    "build_agent",
    "build_index",
    "langfuse",
    "manuals_overview",
    "propagate_attributes",
    "retriever",
    "state",
]


def main() -> None:  # pragma: no cover
    """python3 rag.py <query> — посмотреть, что вернёт search."""
    import sys

    manuals = retriever.manuals
    print(manuals_overview(manuals))
    if len(sys.argv) < 2:
        return
    print("\n" + asyncio.run(search(" ".join(sys.argv[1:]))) )


if __name__ == "__main__":
    main()
