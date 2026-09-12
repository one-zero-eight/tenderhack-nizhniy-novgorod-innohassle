"""FastAPI + HTMX UI для агента по мануалам Портала поставщиков."""

from __future__ import annotations

import html
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import mistune
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

import chat as chat_service
from api import router as api_router
from assets import router as assets_router
from manuals import ROOT as SECTION_ROOT
from manuals import Manual, Section, section_body
from rag import langfuse, state
from storage import ChatRecord, MessageRecord, get_storage
from support import LINE_NAMES
from turns import TURNS

ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))
_md = mistune.create_markdown(
    escape=True,
    hard_wrap=True,
    plugins=["strikethrough", "table", "url"],
)


def render_markdown(text: str) -> str:
    if not text:
        return ""
    return _md(text)


templates.env.filters["tojson"] = lambda value: json.dumps(value, ensure_ascii=False, default=str)
templates.env.filters["markdown"] = lambda text: Markup(render_markdown(text or ""))


# UI-состояние админки: какой чат открыт. Ключ — константа, т.к. чаты общие.
_ACTIVE_KEY = "ui"
_active_chats: dict[str, str] = {}


class ChatView(ChatRecord):
    """ChatRecord + флаг для шаблонов (стримится ли последний ответ)."""

    def __init__(self, record: ChatRecord, streaming_id: str | None = None) -> None:
        super().__init__(
            id=record.id,
            title=record.title,
            system_prompt=record.system_prompt,
            redirect_line=record.redirect_line,
            redirect_reason=record.redirect_reason,
            closed_at=record.closed_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
            messages=record.messages,
        )
        self.streaming_id = streaming_id

    @property
    def redirect_line_title(self) -> str:
        if not self.redirect_line:
            return ""
        return f"{self.redirect_line} — {LINE_NAMES.get(self.redirect_line, '')}"

    def message_is_streaming(self, message: MessageRecord) -> bool:
        return message.id == self.streaming_id


def _manuals() -> list[dict[str, str | int]]:
    """Список мануалов для базы знаний: slug, название, число разделов."""
    manuals, _ = state()
    return [{"slug": m.slug, "title": m.title, "sections": len(m.sections) - 1} for m in manuals.values()]


def _manual(slug: str) -> Manual | None:
    manuals, _ = state()
    return manuals.get(slug)


def _section_view(manual: Manual, section: Section, depth: int = 0) -> dict[str, object]:
    """Раздел мануала в виде, удобном шаблону: заголовок, текст и вложенное поддерево."""
    return {
        "id": section.id,
        "heading": section.heading,
        "title_line": section.title_line,
        "body": render_markdown(section_body(section)),
        "depth": depth,
        "subtree": _children_view(manual, section, depth + 1),
    }


def _children_view(
    manual: Manual, section: Section, depth: int, path: frozenset[str] = frozenset()
) -> list[dict[str, object]]:
    """Рекурсивно собирает поддерево раздела для оглавления (без текста — только заголовки).

    path — id текущего раздела и всех его предков: по нему в шаблоне подсвечивается ветка.
    """
    nodes: list[dict[str, object]] = []
    for child_id in section.children:
        child = manual.sections.get(child_id)
        if child is None:
            continue
        nodes.append(
            {
                "id": child.id,
                "title_line": child.title_line,
                "depth": depth,
                "on_path": child.id in path,
                "subtree": _children_view(manual, child, depth + 1, path),
            }
        )
    return nodes


def _current_path(manual: Manual, current: Section | None) -> frozenset[str]:
    """id текущего раздела плюс id всех его предков — для подсветки ветки в дереве.

    Корень не отмечаем: он идёт последним пунктом оглавления и подсветка там лишняя.
    """
    if current is None:
        return frozenset()
    return frozenset({current.id, *(a for a in current.ancestors if a != SECTION_ROOT)})


def _manual_toc(manual: Manual, current: Section | None = None) -> list[dict[str, object]]:
    """Оглавление мануала: прямые подразделы корня плюс сам корень в конце."""
    root = manual.sections.get(SECTION_ROOT)
    ids = [*((root.children if root else ()) or ()), SECTION_ROOT]
    path = _current_path(manual, current)
    return [
        {
            "id": manual.sections[i].id,
            "title_line": manual.sections[i].title_line,
            "depth": 0,
            "on_path": i in path,
            "subtree": _children_view(manual, manual.sections[i], 1, path),
        }
        for i in ids
        if i in manual.sections
    ]


def _active_id() -> str | None:
    chat_id = _active_chats.get(_ACTIVE_KEY)
    if chat_id and get_storage().get_chat(chat_id) is None:
        _active_chats.pop(_ACTIVE_KEY, None)
        return None
    return chat_id


def _set_active(chat_id: str | None) -> None:
    if chat_id is None:
        _active_chats.pop(_ACTIVE_KEY, None)
    else:
        _active_chats[_ACTIVE_KEY] = chat_id


def _render(request: Request, name: str, **ctx: object) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        name,
        {
            "chats": chat_service.list_chats(),
            "active_id": _active_id(),
            # Вкладки шапки: поддержка (чаты) и база знаний (мануалы).
            "tab": ctx.pop("tab", "support"),
            **ctx,
        },
    )


def _panel_chat() -> ChatView | None:
    chat_id = _active_id()
    if chat_id is None:
        return None
    record = chat_service.get_chat(chat_id)
    if record is None:
        _set_active(None)
        return None
    return ChatView(record, streaming_id=_streaming_message_id(chat_id))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    # Аккуратно гасим незавершённые ходы, чтобы не терять записи в SQLite.
    await TURNS.shutdown()
    if langfuse is not None:
        langfuse.flush()
    get_storage().close()


# HTMX-роуты UI прячем из Swagger: единственный тег, который исключается ниже.
HTMX_TAG = "htmx-ui"

# REST-роуты чатов (см. api.py) — тег ml-api.
ML_API_TAG = "ml-api"

# Картинки мануалов (см. assets.py).
ASSETS_TAG = "ml-assets"


class _DocsFilteredOpenAPI(FastAPI):
    """FastAPI, который выкидывает из схемы всё, помеченное тегом HTMX_TAG.

    Сами эндпоинты продолжают работать — они просто не попадают в /ml-api/docs
    и /ml-api/openapi.json, чтобы в документации был только REST API.
    """

    def openapi(self) -> dict:
        if not self.openapi_schema:
            schema = super().openapi()
            paths = {
                path: ops
                for path, ops in schema.get("paths", {}).items()
                if not any(HTMX_TAG in op.get("tags", []) for op in ops.values())
            }
            # Удаляем объявленные, но больше нигде не используемые теги.
            used = {tag for ops in paths.values() for op in ops.values() for tag in op.get("tags", [])}
            schema["paths"] = paths
            schema["tags"] = [tag for tag in schema.get("tags", []) if tag.get("name") in used]
            self.openapi_schema = schema
        return self.openapi_schema


app = _DocsFilteredOpenAPI(
    title="Портал поставщиков — мануалы",
    lifespan=lifespan,
    docs_url="/ml-api/docs",
    redoc_url="/ml-api/redoc",
    openapi_url="/ml-api/openapi.json",
    openapi_tags=[
        {
            "name": ML_API_TAG,
            "description": "REST API чатов с агентом по мануалам Портала поставщиков.",
        },
        {
            "name": ASSETS_TAG,
            "description": "Картинки из мануалов.",
        },
        {
            "name": HTMX_TAG,
            "description": "HTMX-админка (не входит в публичный REST API).",
        },
    ],
)
app.include_router(api_router)
app.include_router(assets_router)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


def _ui(*, hidden: bool = False) -> dict:
    """Общие настройки роутов админки: всё под тегом HTMX (и, опционально, скрыто из схемы)."""
    meta: dict = {"tags": [HTMX_TAG], "include_in_schema": not hidden}
    return meta


@app.middleware("http")
async def no_cache(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if not path.startswith(("/static", "/ml-assets")):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def _streaming_message_id(chat_id: str) -> str | None:
    """Id сообщения, которое прямо сейчас генерируется в фоне (если есть)."""
    turn = TURNS.for_chat(chat_id)
    if turn is not None:
        return turn.message_id
    # Ход мог завершиться, пока никто не смотрел — тогда смотрим по последнему сообщению.
    record = get_storage().get_chat(chat_id)
    if record is None:
        return None
    for message in reversed(record.messages):
        if TURNS.is_streaming(message.id):
            return message.id
    return None


# --------------------------------------------------------------------- events


def _turn_event_to_sse(event: str, payload: str) -> str:
    """Превращает событие из chat.stream_answer в SSE-фрейм для htmx.

    Вызывается фоновым ходом (turns.py) — здесь же живёт HTML, потому что шаблоны
    и фильтры доступны только в app.py.
    """
    if event == "tool_call":
        data = json.loads(payload)
        return chat_service.sse("tool", _tool_call_html(data["name"], data.get("kwargs") or {}))
    if event == "tool_result":
        data = json.loads(payload)
        return chat_service.sse(
            "tool",
            _tool_result_html(data["name"], data.get("output") or "", bool(data.get("error"))),
        )
    if event == "token":
        data = json.loads(payload)
        return chat_service.sse("token", render_markdown(data.get("content", "")))
    if event == "error":
        data = json.loads(payload)
        return chat_service.sse("token", render_markdown(f"\n\n[ошибка] {data['message']}"))
    if event == "redirect":
        # Чат закрывается и появляется плашка — перерисуем страницу целиком.
        data = json.loads(payload)
        line = data.get("line") or ""
        return chat_service.sse("redirect", line)
    if event == "done":
        return chat_service.sse("done", "")
    return chat_service.sse(event, payload)


# ------------------------------------------------------------------ rendering


def _render(request: Request, name: str, **ctx: object) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        name,
        {
            "chats": chat_service.list_chats(),
            "active_id": _active_id(),
            "tab": ctx.pop("tab", "support"),
            **ctx,
        },
    )


# --------------------------------------------------------------------- routes


@app.get("/", response_class=HTMLResponse, **_ui())
async def index(request: Request) -> HTMLResponse:
    """Поддержка: список чатов слева, переписка справа."""
    return _render(request, "index.html", chat=_panel_chat(), tab="support")


@app.get("/knowledge-base", response_class=HTMLResponse, **_ui())
async def knowledge_base(request: Request) -> HTMLResponse:
    """База знаний: список мануалов со ссылками на страницы мануалов."""
    return _render(request, "knowledge_base.html", manuals=_manuals(), tab="knowledge")


@app.get("/knowledge-base/{slug}", response_class=HTMLResponse, **_ui())
async def knowledge_base_manual(request: Request, slug: str) -> HTMLResponse:
    """Страница мануала: дерево разделов слева, выбранный раздел справа."""
    manual = _manual(slug)
    if manual is None:
        raise HTTPException(status_code=404, detail="Мануал не найден")
    root = manual.sections.get(SECTION_ROOT)
    first = next((c for c in (root.children if root else ()) if c in manual.sections), None)
    first_section = None if first is None else manual.sections[first]
    return _render(
        request,
        "knowledge_manual.html",
        manual=manual,
        toc=_manual_toc(manual, first_section),
        current=first_section,
        active_section=None if first_section is None else _section_view(manual, first_section),
        tab="knowledge",
    )


@app.get("/knowledge-base/{slug}/{section_id}", response_class=HTMLResponse, **_ui())
async def knowledge_base_page(request: Request, slug: str, section_id: str) -> HTMLResponse:
    """Страница раздела мануала. Каждый раздел — обычный URL, дерево — ссылки."""
    manual = _manual(slug)
    if manual is None:
        raise HTTPException(status_code=404, detail="Мануал не найден")
    section = manual.sections.get(section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Раздел не найден")
    return _render(
        request,
        "knowledge_manual.html",
        manual=manual,
        toc=_manual_toc(manual, section),
        current=section,
        active_section=_section_view(manual, section),
        tab="knowledge",
    )


def _page(request: Request, *, push_url: str | None = None) -> HTMLResponse:
    """Полная страница чатов: сайдбар + панель.

    Любое действие с чатом (переключение, создание, удаление, отправка сообщения)
    возвращает всю страницу целиком — так не нужно синхронизировать отдельные
    фрагменты и подсветка активного чата всегда приходит с бэкенда.
    """
    view = _panel_chat()
    response = _render(request, "index.html", chat=view, tab="support")
    if push_url is not None:
        response.headers["HX-Push-Url"] = push_url
    return response


@app.get("/chats/{chat_id}", response_class=HTMLResponse, include_in_schema=False)
async def get_chat(request: Request, chat_id: str) -> HTMLResponse:
    """Переключение чата — отдаём страницу целиком."""
    chat = chat_service.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    _set_active(chat.id)
    return _page(request, push_url=f"/chats/{chat.id}")


@app.post("/chats", response_class=HTMLResponse, include_in_schema=False)
async def create_chat(request: Request) -> HTMLResponse:
    """Новый чат с нулевым системным промптом — форма создания не нужна."""
    chat = chat_service.create_chat()
    _set_active(chat.id)
    return _page(request, push_url=f"/chats/{chat.id}")


@app.delete("/chats/{chat_id}", response_class=HTMLResponse, include_in_schema=False)
async def delete_chat(request: Request, chat_id: str) -> HTMLResponse:
    if chat_service.get_chat(chat_id) is not None:
        get_storage().delete_chat(chat_id)
    if _active_id() == chat_id:
        remaining = chat_service.list_chats()
        _set_active(remaining[0].id if remaining else None)
    return _page(request, push_url="/")


def _short_json(value: object, limit: int = 280) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _tool_call_html(name: str, kwargs: dict) -> str:
    return (
        '<details class="tool" open>'
        f"<summary><span class='tool-name'>{html.escape(name)}</span>"
        "<span class='tool-status'>вызов</span></summary>"
        f"<code>{html.escape(_short_json(kwargs))}</code>"
        "</details>"
    )


def _tool_result_html(name: str, output: str, is_error: bool) -> str:
    status = "ошибка" if is_error else "готово"
    klass = "tool error" if is_error else "tool"
    return (
        f'<details class="{klass}">'
        f"<summary><span class='tool-name'>{html.escape(name)}</span>"
        f"<span class='tool-status'>{status}</span></summary>"
        f"<pre>{html.escape(output[:800])}{'…' if len(output) > 800 else ''}</pre>"
        "</details>"
    )


@app.post("/chats/{chat_id}/messages", response_class=HTMLResponse, include_in_schema=False)
async def send_message(request: Request, chat_id: str, message: str = Form(...)) -> HTMLResponse:
    """Отправка сообщения.

    Генерация уходит в фоновую задачу (turns.py) и не зависит от того, смотрит ли
    пользователь на чат. В ответ кладём сообщение пользователя + заготовку ответа
    ассистента со ссылкой на SSE-стрим.
    """
    chat = chat_service.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    if chat.is_closed:
        raise HTTPException(
            status_code=409,
            detail=f"Чат закрыт: обращение переведено на линию поддержки {chat.redirect_line}",
        )
    text = message.strip()
    if not text:
        return HTMLResponse("", status_code=204)

    _set_active(chat_id)
    _user_msg, assistant_msg, _updated = await chat_service.prepare_turn(chat_id, text)

    def to_sse(event: str, payload: str) -> str:
        return _turn_event_to_sse(event, payload)

    TURNS.start(chat_id, assistant_msg, on_event=to_sse)

    # Возвращаем страницу целиком: сообщение пользователя и заготовка ответа
    # уже в БД, а панель ассистента сама подключится к SSE-стриму.
    return _page(request, push_url=f"/chats/{chat_id}")


@app.get("/chats/{chat_id}/messages/{message_id}/stream", include_in_schema=False)
async def stream_message(request: Request, chat_id: str, message_id: str) -> StreamingResponse:
    """SSE-подписка на фоновый ход.

    Подключиться можно в любой момент и столько раз, сколько нужно: генерация живёт
    в turns.py и не отменяется при отключении клиента (например, при смене чата).
    """
    chat = chat_service.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден")

    async def events() -> AsyncIterator[str]:
        turn = TURNS.get(message_id)
        if turn is None:
            # Ход уже завершился и был вычищен — отдаём сохранённый текст из БД.
            saved = get_storage().get_message(message_id)
            if saved and saved.content:
                yield chat_service.sse("token", render_markdown(saved.content))
            yield chat_service.sse("done", "")
            return
        async for frame in TURNS.subscribe(message_id):
            yield frame

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8010)
