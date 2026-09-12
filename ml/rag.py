"""Агент по инструкциям Портала поставщиков.

RAG отключён: инструмент search убран, полное оглавление всех мануалов лежит
в системном промпте (hierarchy.txt), а агент читает разделы только через open().
Эмбеддинги, chroma и BM25 для этого не нужны — индекс не собирается и не читается.
Чтобы вернуть поиск: раскомментируй импорты и блоки с пометкой RAG ОТКЛЮЧЁН
и верни search в тулы агента (см. build_agent).
"""

from __future__ import annotations

import asyncio

# import contextlib  # RAG ОТКЛЮЧЁН
# import hashlib     # RAG ОТКЛЮЧЁН
import json
import os
from pathlib import Path

# import chromadb  # RAG ОТКЛЮЧЁН
from dotenv import load_dotenv
from llama_index.core import Settings  # , StorageContext, VectorStoreIndex  # RAG ОТКЛЮЧЁН
from llama_index.core.agent.workflow import AgentWorkflow

# from llama_index.core.retrievers import QueryFusionRetriever  # RAG ОТКЛЮЧЁН
# from llama_index.core.retrievers.fusion_retriever import FUSION_MODES  # RAG ОТКЛЮЧЁН
# from llama_index.core.schema import TextNode  # RAG ОТКЛЮЧЁН
from llama_index.core.tools import BaseTool, FunctionTool

# from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters  # RAG ОТКЛЮЧЁН
# from llama_index.embeddings.huggingface import HuggingFaceEmbedding  # RAG ОТКЛЮЧЁН
from llama_index.llms.openai_like import OpenAILike

# from llama_index.retrievers.bm25 import BM25Retriever  # RAG ОТКЛЮЧЁН
# from llama_index.vector_stores.chroma import ChromaVectorStore  # RAG ОТКЛЮЧЁН
from manuals import (
    Manual,
    Section,
    load_manuals,
    manuals_overview,
    render_section,
    resolve_manual,
)

# render_tree и JSONS_DIR нужны были только для поиска и сборки индекса.
# from manuals import JSONS_DIR, render_tree  # RAG ОТКЛЮЧЁН
# from sitemap import sitemap  # ОТКЛЮЧЕНО: инструмент карты сайта временно выключен
from support import SupportSession, load_lines_manual

load_dotenv(Path(__file__).resolve().parent / ".env")

from langfuse import get_client, propagate_attributes
from openinference.instrumentation.llama_index import LlamaIndexInstrumentor

HERE = Path(__file__).resolve().parent
# RAG ОТКЛЮЧЁН: константы нужны были только для сборки chroma-индекса.
# CHROMA_DIR = HERE / "chroma_db"
# COLLECTION_NAME = "portal_manuals"
# CORPUS_HASH_FILE = CHROMA_DIR / "corpus.sha1"
# TOP_K = 6  # сколько разделов возвращает поиск
# VECTOR_TOP_K = 8
# BM25_TOP_K = 8

# RAG ОТКЛЮЧЁН: эмбеддинги нужны только для search.
# device=cpu по умолчанию: собранный на macOS torch падает в MPS-кернелах
# (copy_cast_kernel_mps, SIGSEGV) при повторном эмбеддинге.
# Settings.embed_model = HuggingFaceEmbedding(
#     model_name=os.getenv("EMBED_MODEL", "BAAI/bge-m3"),
#     device=os.getenv("EMBED_DEVICE", "cpu"),
# )
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

# RAG ОТКЛЮЧЁН: chroma-клиент нужен только для search.
# chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))


# RAG ОТКЛЮЧЁН: хеш корпуса триггерил пересборку индекса.
# def _corpus_hash() -> str:
#     digest = hashlib.sha1()
#     for path in sorted(JSONS_DIR.glob("*.json")):
#         digest.update(path.name.encode())
#         digest.update(path.read_bytes())
#     return digest.hexdigest()


# RAG ОТКЛЮЧЁН: ноды нужны были только для индекса и BM25.
# def _nodes(manual: Manual) -> list[TextNode]:
#     """Раздел -> нода. Текст берём как есть, без чанкинга."""
#     return [
#         TextNode(
#             id_=f"{section.manual}::{section.id}",
#             text=section.text or section.heading or section.id,
#             metadata={
#                 "manual": section.manual,
#                 "manual_title": section.manual_title,
#                 "id": section.id,
#                 "heading": section.heading,
#                 "children": json.dumps(list(section.children), ensure_ascii=False),
#             },
#         )
#         for section in manual.sections.values()
#     ]
#
#
# class Retriever:
#     """Fuse-поиск (вектора + BM25) по разделам всех мануалов сразу."""
#
#     def __init__(self, manuals: dict[str, Manual], vector_store: ChromaVectorStore) -> None:
#         self.manuals = manuals
#         self.index = VectorStoreIndex.from_vector_store(
#             vector_store, storage_context=StorageContext.from_defaults(vector_store=vector_store)
#         )
#         self.bm25 = {
#             slug: BM25Retriever.from_defaults(nodes=_nodes(manual), similarity_top_k=BM25_TOP_K)
#             for slug, manual in manuals.items()
#         }
#
#     def _fusion(self, slug: str) -> QueryFusionRetriever:
#         vector = self.index.as_retriever(
#             similarity_top_k=VECTOR_TOP_K,
#             filters=MetadataFilters(filters=[ExactMatchFilter(key="manual", value=slug)]),
#         )
#         return QueryFusionRetriever(
#             retrievers=[vector, self.bm25[slug]],
#             retriever_weights=[0.6, 0.4],
#             similarity_top_k=TOP_K,
#             num_queries=1,
#             mode=FUSION_MODES.RELATIVE_SCORE,
#             use_async=True,
#         )
#
#     async def find_ids(self, slug: str, query: str) -> list[str]:
#         nodes = await self._fusion(slug).aretrieve(query)
#         seen: list[str] = []
#         for node in nodes:
#             node_id = str(node.metadata.get("id", ""))
#             if node_id and node_id not in seen:
#                 seen.append(node_id)
#         return seen
#
#     async def find_across_manuals(self, query: str) -> dict[str, list[str]]:
#         """Ищет по всем мануалам сразу. Возвращает slug -> id найденных разделов."""
#         results: dict[str, list[str]] = {}
#         for slug in self.manuals:
#             ids = await self.find_ids(slug, query)
#             if ids:
#                 results[slug] = ids
#         return results
#
#
# def _fresh_collection():
#     with contextlib.suppress(Exception):  # коллекции ещё нет — это нормально
#         chroma_client.delete_collection(COLLECTION_NAME)
#     return chroma_client.get_or_create_collection(COLLECTION_NAME)
#
#
# def build_index(force: bool = False) -> Retriever:
#     """Пересобирает chroma, если jsons/ изменились (или force=True).
#
#     Эмбеддинги считаются долго (минуты), поэтому вызывать лучше в фоне —
#     см. app._reindex_job.
#     """
#     global retriever
#
#     manuals = load_manuals()
#     digest = _corpus_hash()
#     cached = CORPUS_HASH_FILE.read_text().strip() if CORPUS_HASH_FILE.exists() else ""
#     collection = chroma_client.get_or_create_collection(COLLECTION_NAME)
#
#     if force or cached != digest or collection.count() == 0:
#         if cached != digest or force:
#             collection = _fresh_collection()
#         vector_store = ChromaVectorStore(chroma_collection=collection)
#         nodes = [node for manual in manuals.values() for node in _nodes(manual)]
#         VectorStoreIndex(
#             nodes,
#             storage_context=StorageContext.from_defaults(vector_store=vector_store),
#             show_progress=True,
#         )
#         CHROMA_DIR.mkdir(parents=True, exist_ok=True)
#         CORPUS_HASH_FILE.write_text(digest)
#         print(f"Индекс собран: {len(manuals)} мануалов, {len(nodes)} разделов.")
#     else:
#         vector_store = ChromaVectorStore(chroma_collection=collection)
#
#     retriever = Retriever(manuals, vector_store)
#     return retriever


# RAG ОТКЛЮЧЁН: мануалы читаются прямо из jsons/, индекс больше не нужен.
manuals: dict[str, Manual] = load_manuals()


def state() -> tuple[dict[str, Manual], None]:
    """Мануалы для API и админки. Второй элемент — retriever, которого больше нет."""
    return manuals, None


def _manuals_hint(manuals: dict[str, Manual]) -> str:
    return "\n".join(f"- {m.slug} — {m.title}" for m in manuals.values())


# RAG ОТКЛЮЧЁН: инструмент search убран, вместо него оглавление в системном промпте.
# async def search(query: str) -> str:
#     """Найти разделы по всем инструкциям сразу (гибридный поиск: эмбеддинги + BM25).
#
#     Вызывай первым делом на ЛЮБОЙ вопрос, даже если кажется, что он не про Портал.
#     ОБЯЗАТЕЛЬНЫЙ первый шаг: без него нельзя сказать, что вопрос не по теме.
#     ЗАПРЕЩЕНО отвечать «вопрос не относится к Порталу поставщиков» или «не по теме»,
#     если search в этом ответе не вызывался хотя бы один раз.
#     Возвращает только структуру (без текста), сгруппированную по мануалам:
#     id и заголовки найденных разделов плюс их родители. Чтобы прочитать раздел,
#     вызови open(manual, section_id), где manual — slug мануала из заголовка группы.
#
#     query — запрос на русском, лучше словами из инструкции («котировочная сессия»,
#     «электронное исполнение», «заявка на банковскую гарантию»). Если вернулось пусто,
#     переформулируй и вызови search ещё раз — только после этого вопрос можно
#     считать нерелевантным.
#     """
#     manuals, retriever = state()
#     if not (query or "").strip():
#         return "Пустой запрос: сформулируй, что именно искать."
#
#     grouped = await retriever.find_across_manuals(query)
#     if not grouped:
#         return f"По запросу «{query}» ничего не найдено ни в одной инструкции. Попробуй другие ключевые слова."
#
#     blocks: list[str] = []
#     total = 0
#     for slug, ids in grouped.items():
#         manual = manuals[slug]
#         total += len(ids)
#         blocks.append(f"[{slug}] — {manual.title} ({len(ids)} разделов):\n{render_tree(manual, ids)}")
#     return (
#         f"Найдено {total} разделов в {len(grouped)} мануалах по запросу «{query}»:\n\n"
#         + "\n\n".join(blocks)
#         + "\n\nПрочитай нужный раздел: open('<slug из [скобок]>', '<id>')."
#     )


def _resolve_section(manual: Manual, section_id: str) -> Section | list[str]:
    key = " ".join((section_id or "").split()).strip().rstrip(".")
    if "::" in key:
        key = key.rsplit("::", 1)[1]
    key = key.removeprefix(f"{manual.slug}:").strip()
    if key in manual.sections:
        return manual.sections[key]
    wanted = key.lower()
    exact = [s for s in manual.sections.values() if s.heading.lower() == wanted]
    if len(exact) == 1:
        return exact[0]
    loose = [s for s in manual.sections.values() if wanted and wanted in s.heading.lower()]
    if len(loose) == 1:
        return loose[0]
    return [s.id for s in loose[:10]]


def read(manual: str, section_id: str) -> str:  # имя инструмента задано агенту
    """Прочитать раздел мануала по id: текст, заголовок и список подразделов.

    manual — slug мануала (см. оглавление в промпте), section_id — номер раздела.
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
            return f"В мануале «{found.name}» нет раздела '{section_id}'. Возьми id из оглавления в промпте."
        listed = "\n".join(f"- {found.sections[i].title_line}" for i in resolved)
        return f"Точного id '{section_id}' нет, похожие разделы:\n{listed}\n\nВызови read с нужным id."
    return render_section(found, resolved)


SYSTEM_PROMPT = """Ты — консультант по Порталу поставщиков (zakupki.mos.ru).
Отвечай на русском, только по содержимому инструкций. Не выдумывай функции и кнопки,
которых нет в прочитанных разделах.

{terms}

Ниже — полное оглавление всех инструкций. Это карта, по которой ты выбираешь раздел:
раздел читается инструментом read(manual, section_id), где manual — slug из скобок
в заголовке мануала, а section_id — номер слева от двоеточия.

{hierarchy}

Тебе доступен один инструмент:
read(manual, section_id) — читает раздел: заголовок, подразделы и полный текст.

Как работать:
1. Найди подходящий раздел в оглавлении выше. Оглавление полное, поиск по нему не нужен.
   Если с первого взгляда подходящего раздела нет — перечитай оглавление, названия
   в инструкциях бывают непривычные («электронное исполнение», «котировочная сессия»,
   «СТЕ», «оферта»).
2. Прочитай нужный раздел: read(manual, section_id).
3. Если раздел родительский или не тот — прочитай его подразделы из children
   или возьми соседний пункт из оглавления.
4. Отвечай по прочитанному тексту. Не показывай пользователю служебное: id, slug'и,
   имена инструментов, но можешь называть раздел по заголовку («раздел «Работа с ответами банков»»).
5. Если спрашивают, ГДЕ что-то найти на сайте («где посмотреть закупки», «где форум»,
   «дай ссылку на регламент»), вставляй в ответ подходящие ссылки, если знаешь их точно,
   иначе переведи обращение на линию поддержки (transfer_to_support).
6. Если в разделе есть картинки — вставляй их в ответ отдельной строкой в том виде,
   как они даны: ![подпись](/ml-assets/image/<slug>/image-N.png). Интерфейс умеет их показывать.
   Ставь картинку рядом с тем шагом, который она иллюстрирует.
7. В конце ответа дай ссылки на разделы, которыми пользовался, в виде markdown-ссылок
   на страницы базы знаний: [<номер> <заголовок>](/knowledge-base/<slug>/<номер>).
   Например: [5.2.1 Добавить код ЕРУЗ](/knowledge-base/supplier-portal-econtract/5.2.1),
   [Работа с ответами банков](/knowledge-base/supplier-portal/8.1.2).
   Ставь 1—3 самых релевантных раздела, только те, что реально читал (read).
   Не выдумывай номера, которых не видел в оглавлении или read.
   Если ни один раздел не помог (перевод на линию или отказ), ссылки не нужны.
8. Если пользователь спрашивает про заказчика — бери мануал заказчика, если про поставщика —
   мануал поставщика; если непонятно, уточни или посмотри в обоих.

{lines}

Перевод на линию:
1. Прежде чем утверждать, что ответа нет, проверь оглавление и открой 1—2 наиболее
   подходящих раздела. Не переводи «как сделать X» вопрос, не убедившись, что инструкции
   его не покрывают.
2. Если подходящая линия есть — вызови transfer_to_support(line, reason).
   Это завершит чат: напиши пользователю, что вопрос передан на линию, назови линию
   человеческими словами (например «вторая линия, экспертно-методологическая»)
   и скажи, что скоро ответит специалист. Не называй это «L2» в тексте ответа.
3. Если вопрос вообще не относится к Порталу поставщиков и ни одна линия не подходит —
   НЕ вызывай transfer_to_support. Вежливо скажи, что вопрос не по теме Портала
   поставщиков и ты можешь помочь только с работой на Портале.

Как отвечать:
- Отвечай кратко. По умолчанию — 2–5 предложений или небольшой список, без вступлений
  вроде «Отличный вопрос» и без пересказа всего раздела.
- Если вопрос обширный (несколько сценариев сразу, «расскажи всё про…», задача с ветвлениями),
  НЕ вываливай длинный ответ. Дай краткую суть (пара предложений) и задай уточняющий вопрос:
  что именно интересует, заказчик или поставщик, какой шаг застрял.
- Развёрнутый ответ давай только если пользователь явно об этом попросил («подробно»,
  «пошагово», «полный ответ», «ничего не сокращай») или если без деталей ответ будет неверным.
"""


# RAG ОТКЛЮЧЁН: индекс больше не собирается — мануалы читаются из jsons/ (см. state).
# retriever: Retriever = build_index()

# Всё, что кладётся в системный промпт одним куском, лежит в отдельных txt.
TERMS_FILE = HERE / "terms.txt"
HIERARCHY_FILE = HERE / "hierarchy.txt"


def _read_text(path: Path) -> str:
    """Читает txt-файл промпта; отсутствие файла не должно ломать старт."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


# Базовый системный промпт: термины + оглавление всех мануалов + мануал по линиям.
BASE_SYSTEM_PROMPT = SYSTEM_PROMPT.format(
    terms=_read_text(TERMS_FILE),
    hierarchy=_read_text(HIERARCHY_FILE),
    lines=load_lines_manual(),
)

agent = AgentWorkflow.from_tools_or_functions(
    [read],  # search и sitemap отключены: оглавление целиком есть в промпте
    llm=Settings.llm,
    system_prompt=BASE_SYSTEM_PROMPT,
)


def build_agent(
    extra_system_prompt: str | None = None,
    support_session: SupportSession | None = None,
) -> AgentWorkflow:
    """Собирает агента под конкретный чат.

    extra_system_prompt дописывается к базовому (не заменяет его).
    support_session добавляет инструмент transfer_to_support, причём перевод
    запоминается в сессии — по ней чат потом закрывается.
    """
    parts = [BASE_SYSTEM_PROMPT]
    extra = (extra_system_prompt or "").strip()
    if extra:
        parts.append(extra)

    if support_session is None and len(parts) == 1:
        return agent

    raw_tools: list = [read]
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
    "langfuse",
    "manuals",
    "manuals_overview",
    "propagate_attributes",
    "state",
]


def main() -> None:  # pragma: no cover
    """python3 rag.py — показать список мануалов (search отключён вместе с RAG)."""
    print(manuals_overview(manuals))


if __name__ == "__main__":
    main()
