"""FastAPI + HTMX UI для агента по мануалам Портала поставщиков."""

from __future__ import annotations

import contextlib
import html
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, unquote, urlencode

import mistune
from fastapi import APIRouter, FastAPI, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

import attachments as attachment_service
import chat as chat_service
import feedback
import handrules
import stats
from api import router as api_router
from assets import router as assets_router
from manuals import Manual, Section, section_body
from rag import langfuse, state
from storage import ChatRecord, MessageRecord, UserRecord, clean_username, get_storage
from support import LINE_NAMES
from topic_classifier import FALLBACK, TOPICS
from turns import TURNS

# Лимит вложения живёт в attachments: шаблоны показывают его в подсказке у формы.
MAX_UPLOAD_MB = attachment_service.MAX_FILE_SIZE // (1024 * 1024)

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


def _format_datetime(value: object) -> str:
    """Дата для интерфейса: «12.09.2026 22:33». Пустое значение — пустая строка."""
    if value is None:
        return ""
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            value = datetime.fromisoformat(value)
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    return str(value)


templates.env.filters["datetime"] = _format_datetime


def _tool_label(tool: object) -> Markup:
    """Подпись выполненного инструмента для админки.

    У read это ссылка на прочитанный документ вида «<name> <section_id>»,
    у остальных — просто имя инструмента.
    """
    name = str(getattr(tool, "name", "") or "")
    kwargs = getattr(tool, "kwargs", None) or {}
    if name == "read":
        slug = str(kwargs.get("manual", "")).strip()
        section_id = str(kwargs.get("section_id", "")).strip()
        manual = _manual(slug)
        title = manual.name if manual is not None else slug
        text = f"{title} {section_id}".strip()
        if slug and section_id:
            # База знаний живёт только в публичной части — ссылаемся на неё.
            href = f"/knowledge-base/{html.escape(slug)}/{html.escape(section_id)}"
            return Markup(f'<a class="tool-doc" href="{href}">{html.escape(text)}</a>')
        return Markup(html.escape(text or name))
    return Markup(html.escape(name))


templates.env.globals["tool_label"] = _tool_label


def _format_seconds(seconds: float) -> str:
    """Секунды по-человечески: «1,2 с» / «12 с» / «1 мин 05 с»."""
    if seconds < 10:
        return f"{seconds:.1f}".replace(".", ",") + " с"
    if seconds < 60:
        return f"{round(seconds)} с"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes} мин {rest:02d} с"


def _duration_label(ms: int | None) -> str:
    """Время генерации по-человечески: «1,2 с» / «12 с» / «1 мин 05 с».

    Пустая строка, пока ход не завершён: у незакрытого сообщения duration_ms = None.
    """
    if ms is None:
        return ""
    return _format_seconds(max(0, ms) / 1000)


def _avg_turn_label(seconds: float | None) -> str:
    """Время ответа для сайдбара админки. Нет данных — прочерк, а не пусто:
    иначе строка «название — счётчик» съезжала бы влево."""
    if seconds is None:
        return "—"
    return _format_seconds(seconds)


templates.env.globals["duration_label"] = _duration_label
templates.env.globals["avg_turn_label"] = _avg_turn_label

# Кнопки оценки ответа: тексты берём из feedback.py, чтобы шаблон и подсказки
# для LLM не разъезжались. ChatView.feedback_context решает, какие именно кнопки рисовать.
templates.env.globals["feedback_positive_label"] = feedback.POSITIVE_LABEL
templates.env.globals["feedback_negative_label"] = feedback.NEGATIVE_LABEL
templates.env.globals["feedback_operator_label"] = feedback.OPERATOR_LABEL
templates.env.globals["feedback_reasons"] = feedback.REASONS


# UI-состояние: какой чат открыт. Ключ — либо 'admin', либо username с /.
_ACTIVE_KEY = "admin"
_active_chats: dict[str, str] = {}


def _user_active_key(username: str) -> str:
    return f"user:{username}"


class ChatView(ChatRecord):
    """ChatRecord + флаг для шаблонов (стримится ли последний ответ)."""

    def __init__(self, record: ChatRecord, streaming_id: str | None = None) -> None:
        super().__init__(
            id=record.id,
            title=record.title,
            system_prompt=record.system_prompt,
            redirect_line=record.redirect_line,
            redirect_reason=record.redirect_reason,
            topic=record.topic,
            subtopic=record.subtopic,
            rating=record.rating,
            rating_reason=record.rating_reason,
            rated_at=record.rated_at,
            owner=record.owner,
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
        # Без человеческого названия (например, старая запись с L3) показываем
        # только код линии: «L3 — » с висячим тире выглядит как обрыв текста.
        name = LINE_NAMES.get(self.redirect_line)
        return f"{self.redirect_line} — {name}" if name else self.redirect_line

    def message_is_streaming(self, message: MessageRecord) -> bool:
        return message.id == self.streaming_id

    def is_feedback_target(self, message: MessageRecord) -> bool:
        """Можно ли вообще ставить кнопки оценки под этим сообщением.

        Кнопки живут только под последним сообщением, и только если это ответ
        ассистента: у чата одна оценка, и оценивать промежуточные ответы незачем.
        """
        return (
            message.role == "assistant"
            and bool(self.messages)
            and self.messages[-1].id == message.id
            and not self.is_closed
        )

    def feedback_visible(self, message: MessageRecord) -> bool:
        """Показывать ли кнопки оценки под этим ответом.

        Кнопки живут под последним ответом ассистента всегда, пока чат не закрыт
        и ответ не стримится: оценку можно поменять, новая перетирает прежнюю
        (оценка всё равно одна на чат). Исключение — служебная благодарность
        на кнопку «Спасибо за помощь»: это не ответ на вопрос, оценивать нечего.
        """
        if not self.is_feedback_target(message) or self.message_is_streaming(message):
            return False
        return not feedback.is_service_reply(message.content)

    def feedback_reasons_visible(self, message: MessageRecord) -> bool:
        """Нужен ли под ответом список причин и «Позови оператора».

        Причины появляются только в состоянии «ответ не подходит, но почему ещё
        не выбрано». Как только причина выбрана (или оценка стала positive),
        остаются только две кнопки оценки.
        """
        return self.feedback_visible(message) and self.rating == "negative" and not self.rating_reason

    def feedback_context(self, message: MessageRecord) -> dict[str, bool]:
        """Состояние блока оценки для шаблона: show rate-кнопок и show причин."""
        return {
            "rate": self.feedback_visible(message),
            "reasons": self.feedback_reasons_visible(message),
        }

    @property
    def questions(self) -> dict[str, str]:
        """id сообщения ассистента -> текст вопроса, на который оно отвечает.

        Нужно кнопке «Ассистент не должен так отвечать» в админке: она открывает
        /handrules/new с этим вопросом. Соответствие берём по порядку: вопрос —
        ближайшее user-сообщение выше ответа (ровно то же, что и в диалоге).
        """
        mapping: dict[str, str] = {}
        last_question = ""
        for message in self.messages:
            if message.role == "user":
                last_question = message.content or ""
            elif message.role == "assistant":
                mapping[message.id] = last_question
        return mapping


def _manuals() -> list[dict[str, str | int]]:
    """Список мануалов для базы знаний: slug, название, число разделов."""
    manuals, _ = state()
    return [{"slug": m.slug, "title": m.name, "sections": len(m.sections)} for m in manuals.values()]


def _manual(slug: str) -> Manual | None:
    manuals, _ = state()
    return manuals.get(slug)


def _section_view(manual: Manual, section: Section, depth: int = 0) -> dict[str, object]:
    """Раздел мануала в виде, удобном шаблону: заголовок, текст и вложенное поддерево."""
    return {
        "id": section.id,
        "heading": section.heading,
        "title_line": section.title_line,
        "body": render_markdown(section_body(section, manual)),
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
    """id текущего раздела плюс id всех его предков — для подсветки ветки в дереве."""
    if current is None:
        return frozenset()
    return frozenset({current.id, *current.ancestors})


def _manual_toc(manual: Manual, current: Section | None = None) -> list[dict[str, object]]:
    """Оглавление мануала: разделы верхнего уровня (без служебного корня)."""
    root_ids = [s.id for s in manual.sections.values() if not s.ancestors]
    ids = sorted(root_ids, key=lambda i: manual.ordered_ids.index(i))
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


def _active_id(key: str | None = None) -> str | None:
    """Id открытого чата для данного ключа ('admin' или 'user:<name>')."""
    k = key or _ACTIVE_KEY
    chat_id = _active_chats.get(k)
    if chat_id and get_storage().get_chat(chat_id) is None:
        _active_chats.pop(k, None)
        return None
    return chat_id


def _set_active(chat_id: str | None, key: str | None = None) -> None:
    k = key or _ACTIVE_KEY
    if chat_id is None:
        _active_chats.pop(k, None)
    else:
        _active_chats[k] = chat_id


def _render(request: Request, name: str, **ctx: object) -> HTMLResponse:
    """Рендер страницы.

    chats/active_id/tab берутся из ctx, если переданы явно; иначе — общие для /admin.
    """
    return templates.TemplateResponse(
        request,
        name,
        {
            "chats": ctx.pop("chats", chat_service.list_chats()),
            "active_id": ctx.pop("active_id", _active_id()),
            "tab": ctx.pop("tab", "support"),
            "max_upload_mb": MAX_UPLOAD_MB,
            **ctx,
        },
    )


def _panel_chat(chat_id: str | None = None) -> ChatView | None:
    """Открытый чат для панели. chat_id — конкретный чат, иначе активный для /admin."""
    if chat_id is None:
        chat_id = _active_id()
    if chat_id is None:
        return None
    record = chat_service.get_chat(chat_id)
    if record is None:
        _set_active(None)
        return None
    return ChatView(record, streaming_id=_streaming_message_id(chat_id))


def _chat_files(chat_id: str | None) -> list[dict[str, object]]:
    """Вложения чата для шаблона: уже загруженные, но ещё не отправленные."""
    if chat_id is None:
        return []
    return [item.to_dict() for item in attachment_service.list_files(chat_id)]


# Вложения нужны только панели чата, поэтому шаблон запрашивает их сам:
# так их не приходится протаскивать через каждый вызов _render.
templates.env.globals["chat_files"] = _chat_files


async def _read_upload(upload: UploadFile) -> bytes:
    """Читает файл с запасом в байт: так лимит проверяется до загрузки всего в память."""
    return await upload.read(attachment_service.MAX_FILE_SIZE + 1)


async def _store_upload(chat_id: str, upload: UploadFile) -> attachment_service.ChatFile:
    """Сохраняет вложение в БД. Бросает 400, если файл пуст, велик или не поддержан."""
    chat = chat_service.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    if chat.is_closed:
        raise HTTPException(status_code=409, detail="Чат закрыт: вложения больше не принимаются")

    data = await _read_upload(upload)
    try:
        return attachment_service.save_file(
            chat_id,
            upload.filename or "file",
            upload.content_type,
            data,
        )
    except attachment_service.AttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _file_content_response(chat_id: str, file_id: str) -> Response:
    """Оригинал вложения из своего чата — для превью в списке над композером.

    Читаем с диска (attachments/<id>), а не из BLOB: так работает и для документов,
    у которых в таблице лежит только markdown.
    """
    found = attachment_service.read_original(file_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Вложение не найдено")
    data, content_type, _filename = found
    return Response(content=data, media_type=content_type)


def _upload_failed(message: str) -> HTMLResponse:
    """Ответ на неудачную загрузку: только текст ошибки.

    Отдаём 200, чтобы htmx переписал им блок `#upload-error`, а не оставил страницу без
    объяснений: браузер прислал multipart-форму, а не JSON, поэтому стандартный
    обработчик ошибок FastAPI здесь не поможет.
    """
    safe = html.escape(message)
    return HTMLResponse(
        f'<div class="upload-error">{safe}</div>',
        status_code=200,
        headers={"HX-Retarget": "#upload-error", "HX-Reswap": "innerHTML"},
    )


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
# ui-роутер регистрируется в конце файла: он объявлен рядом со своими роутами.
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


def _turn_event_to_sse(event: str, payload: str, *, show_tools: bool = True) -> str | None:
    """Превращает событие из chat.stream_answer в SSE-фрейм для htmx.

    Возвращает None, если событие показывать не нужно (вызов инструмента).
    Вызывается фоновым ходом (turns.py) — здесь же живёт HTML, потому что шаблоны
    и фильтры доступны только в app.py.

    show_tools=True только для админки: на публичной странице вызовы инструментов
    пользователю не показываем — он видит только ответ.
    """
    if event == "tool_call":
        # Вызов инструмента не показываем — ждём результата.
        return None
    if event == "tool_result":
        if not show_tools:
            return None
        data = json.loads(payload)
        return chat_service.sse(
            "tool",
            _tool_result_html(
                data.get("name") or "", data.get("kwargs") or {}, bool(data.get("error"))
            ),
        )
    if event == "token":
        data = json.loads(payload)
        return chat_service.sse("token", render_markdown(data.get("content", "")))
    if event == "error":
        data = json.loads(payload)
        return chat_service.sse("token", render_markdown(f"\n\n[ошибка] {data['message']}"))
    if event == "redirect":
        # О переводе сообщаем событием, но перерисовкой занимается не оно: низ чата
        # обновляется на sse:done запросом к /chats/<id>/footer (см. _chat_footer).
        data = json.loads(payload)
        return chat_service.sse("redirect", data.get("line") or "")
    if event == "done":
        # Пустой ответ (например, страница уже отрисована) — просто закрываем стрим.
        # Иначе отдаём подпись времени генерации: она садится в span.who-time.
        try:
            data = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            data = {}
        duration = data.get("duration_ms")
        label = _duration_label(duration) if isinstance(duration, int) else ""
        return chat_service.sse("done", label)
    return chat_service.sse(event, payload)


def _chat_footer(request: Request, chat: ChatRecord, *, base: str, readonly: bool, hide_readonly_note: bool) -> HTMLResponse:
    """Низ панели чата: форма отправки или плашка перевода.

    Отдаётся отдельным запросом, потому что содержимое зависит от состояния чата,
    а узнать о переводе можно только после генерации: стрим о переводе не сообщает.
    Панель дёргает этот URL на sse:done (см. chat_panel.html) и подменяет себя —
    так плашка появляется сразу, без перезагрузки страницы.
    """
    view = chat if isinstance(chat, ChatView) else ChatView(chat)
    return templates.TemplateResponse(
        request,
        "chat_footer.html",
        {
            "chat": view,
            "base": base,
            "readonly": readonly,
            "hide_readonly_note": hide_readonly_note,
            "max_upload_mb": MAX_UPLOAD_MB,
        },
    )


def _chat_feedback(request: Request, chat: ChatRecord, *, base: str, readonly: bool) -> HTMLResponse:
    """Кнопки оценки под последним ответом ассистента — обновляемый фрагмент.

    Отдельным запросом, потому что оценка меняется в момент завершения ответа:
    base.html на sse:done перезапрашивает узлы с data-refresh-on-done (см. base.html).
    Пустой ответ — кнопок нет: ответ ещё стримится, чат закрыт или это админка
    (readonly).
    """
    if readonly:
        return HTMLResponse("")
    view = chat if isinstance(chat, ChatView) else ChatView(chat)
    state = view.feedback_context(view.messages[-1]) if view.messages else {"rate": False, "reasons": False}
    if not state["rate"]:
        return HTMLResponse("")
    return templates.TemplateResponse(
        request,
        "chat_feedback.html",
        {"chat": view, "base": base, "feedback": state},
    )


# --------------------------------------------------------------------- routes

# ------------------------------------------------------------------ публичная часть
#
# / — панель конкретного пользователя. Идентификация без пароля: имя лежит в куке.
# Если куки нет — показываем страницу ввода имени. Роль ('supplier'/'customer'/None)
# выбирается в /profile и уходит в вопрос к агенту, а не в системный промпт.
#
# /admin ниже работает независимо: там видны все чаты и авторизация не нужна.

USERNAME_COOKIE = "username"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # год: имя — это не сессия, пусть живёт долго


def _clean_username(raw: str | None) -> str:
    """Имя из формы/куки: схлопываем пробелы и режем длину. Паролей нет — это ярлык.

    Пустое имя нормализуется в '', потому что в форме ввода нам нужен явный «нет имени»,
    а не None.
    """
    return clean_username(raw) or ""


def _encode_username(name: str) -> str:
    """Кука — только latin-1, поэтому имена в кириллице кодируем в URL-escaped вид."""
    return quote(name, safe="")


def _decode_username(raw: str | None) -> str:
    """Обратная операция: терпимо к старым кукам, записанным без кодирования."""
    if not raw:
        return ""
    with contextlib.suppress(UnicodeDecodeError, ValueError):
        return unquote(raw)
    return raw


def _current_username(request: Request) -> str | None:
    """Имя из куки, если такой пользователь есть в БД. Иначе None (нужен /login)."""
    name = _clean_username(_decode_username(request.cookies.get(USERNAME_COOKIE)))
    if not name:
        return None
    return name if get_storage().get_user(name) is not None else None


def _current_user(request: Request) -> UserRecord | None:
    name = _current_username(request)
    return None if name is None else get_storage().get_user(name)


def _require_user(request: Request) -> str:
    """Имя текущего пользователя или редирект-исключение на /login."""
    name = _current_username(request)
    if name is None:
        raise _NeedLogin()
    return name


class _NeedLogin(Exception):
    """Внутренний сигнал: нет валидной куки — надо показать страницу идентификации."""


def _login_response(request: Request, *, error: str | None = None, username: str = "") -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "user_login.html",
        {"error": error, "username": username},
    )


def _user_page(
    request: Request,
    username: str,
    *,
    chat: ChatView | None = None,
    push_url: str | None = None,
    template: str = "user_index.html",
) -> HTMLResponse:
    """Страница пользователя: только его чаты (для /admin — все)."""
    key = _user_active_key(username)
    chats = chat_service.list_chats(owner=username)
    response = _render(
        request,
        template,
        chat=chat,
        chats=chats,
        active_id=_active_id(key),
        tab="support",
    )
    if push_url is not None:
        response.headers["HX-Push-Url"] = push_url
    return response


def _user_chat(username: str, chat_id: str) -> ChatRecord:
    """Чат пользователя или 404: чужой чат читать нельзя."""
    chat = chat_service.get_chat(chat_id)
    if chat is None or chat.owner != username:
        raise HTTPException(status_code=404, detail="Чат не найден")
    return chat


# ------------------------------------------------------------------ знания (общие)


def _knowledge_list(request: Request, *, base: str, template: str, username: str | None = None) -> HTMLResponse:
    chats = chat_service.list_chats(owner=username) if username else chat_service.list_chats()
    return _render(
        request,
        template,
        manuals=_manuals(),
        chats=chats,
        tab="knowledge",
        base=base,
    )


def _knowledge_manual_page(
    request: Request,
    slug: str,
    *,
    base: str,
    template: str,
    section_id: str | None = None,
    username: str | None = None,
) -> HTMLResponse:
    manual = _manual(slug)
    if manual is None:
        raise HTTPException(status_code=404, detail="Мануал не найден")

    if section_id is None:
        first = next(iter(manual.ordered_ids), None)
        section = None if first is None else manual.sections[first]
    else:
        section = manual.sections.get(section_id)
        if section is None:
            raise HTTPException(status_code=404, detail="Раздел не найден")

    chats = chat_service.list_chats(owner=username) if username else chat_service.list_chats()
    return _render(
        request,
        template,
        manual=manual,
        toc=_manual_toc(manual, section),
        current=section,
        active_section=None if section is None else _section_view(manual, section),
        chats=chats,
        tab="knowledge",
        base=base,
    )


# ------------------------------------------------------------------ /admin (чаты, без входа)
#
# Админка не требует идентификации и показывает все чаты. Базы знаний здесь нет —
# она осталась только в публичной части (см. ниже).

ui = APIRouter(prefix="/admin")

# Заголовок группы для чатов, которые классификатор ещё не разобрал.
# Берём из stats, чтобы сайдбар админки и статистика не разошлись в названии группы.
UNCLASSIFIED_TOPIC = stats.UNCLASSIFIED_TOPIC


def _avg_turn(chats: list[ChatRecord]) -> float | None:
    """Среднее время ответа по группе чатов.

    У чата это время его первого ответа (см. ChatStorage.average_turn_seconds),
    а у темы/подтемы — среднее по её чатам. Чаты без измеренных ответов
    (avg_turn_seconds is None) в расчёт не идут — иначе «нет данных» разбавляло бы
    среднее нулями.
    """
    values = [chat.avg_turn_seconds for chat in chats if chat.avg_turn_seconds is not None]
    return sum(values) / len(values) if values else None


def _topic_tree(records: list[ChatRecord]) -> list[dict[str, object]]:
    """Группирует чаты в дерево тем → подтем по порядку из topics.json.

    Чаты без темы попадают в отдельную группу в конце. Внутри подтемы — по времени
    последнего изменения (как их отдаёт list_chats). Пустые ветки не показываем.
    Каждому узлу и чату считаем время ответа — сайдбар показывает его справа.
    """
    by_topic: dict[str, dict[str, list[ChatRecord]]] = {}
    for record in records:
        topic = (record.topic or "").strip() or UNCLASSIFIED_TOPIC
        if topic == UNCLASSIFIED_TOPIC:
            subtopic = stats.UNCLASSIFIED_SUBTOPIC
        else:
            subtopic = (record.subtopic or "").strip() or FALLBACK
        by_topic.setdefault(topic, {}).setdefault(subtopic, []).append(record)

    # Порядок тем и подтем — как в классификаторе; незнакомые идут в конец по алфавиту.
    known_topics = [entry["topic"] for entry in TOPICS]
    ordered_topics = [t for t in known_topics if t in by_topic]
    ordered_topics += sorted(t for t in by_topic if t not in known_topics and t != UNCLASSIFIED_TOPIC)
    if UNCLASSIFIED_TOPIC in by_topic:
        ordered_topics.append(UNCLASSIFIED_TOPIC)

    tree: list[dict[str, object]] = []
    for topic in ordered_topics:
        subtopics = by_topic[topic]
        known_subtopics = _subtopic_order(topic)
        ordered_subs = [s for s in known_subtopics if s in subtopics]
        ordered_subs += sorted(s for s in subtopics if s not in known_subtopics)
        topic_chats = [chat for sub in ordered_subs for chat in subtopics[sub]]
        tree.append(
            {
                "topic": topic,
                "count": len(topic_chats),
                "avg_turn_seconds": _avg_turn(topic_chats),
                "subtopics": [
                    {
                        "subtopic": sub,
                        "count": len(subtopics[sub]),
                        "avg_turn_seconds": _avg_turn(subtopics[sub]),
                        "chats": subtopics[sub],
                    }
                    for sub in ordered_subs
                ],
            }
        )
    return tree


def _subtopic_order(topic: str) -> list[str]:
    """Порядок подтем как в topics.json. Для неизвестной темы — пусто."""
    for entry in TOPICS:
        if entry["topic"] == topic:
            return [sub["title"] for sub in entry.get("subtopics", [])]
    return []


@ui.get("/", response_class=HTMLResponse, **_ui())
async def admin_index(request: Request) -> HTMLResponse:
    """Поддержка: чаты слева (по темам и подтемам), переписка справа."""
    return _admin_page(request)


def _admin_page(request: Request, *, push_url: str | None = None) -> HTMLResponse:
    """Полная страница админки: сайдбар + панель.

    Любое действие с чатом возвращает всю страницу целиком — так не нужно
    синхронизировать отдельные фрагменты и подсветка активного чата всегда
    приходит с бэкенда. Чаты сгруппированы по темам и подтемам; ветка с открытым
    чатом разворачивается автоматически.
    """
    chat = _panel_chat()
    active_topic = active_subtopic = None
    if chat is not None:
        active_topic = (chat.topic or "").strip() or UNCLASSIFIED_TOPIC
        active_subtopic = (
            stats.UNCLASSIFIED_SUBTOPIC
            if active_topic == UNCLASSIFIED_TOPIC
            else ((chat.subtopic or "").strip() or FALLBACK)
        )

    response = _render(
        request,
        "admin.html",
        chat=chat,
        active_id=_active_id(),
        base="/admin",
        # Просмотр чатов — продолжение статистики (ссылки на чаты ведут сюда),
        # поэтому в шапке подсвечиваем таба «Статистика».
        tab="stats",
        topic_tree=_topic_tree(chat_service.list_chats()),
        active_topic=active_topic,
        active_subtopic=active_subtopic,
    )
    if push_url is not None:
        response.headers["HX-Push-Url"] = push_url
    return response


@ui.get("/chats/{chat_id}", response_class=HTMLResponse, include_in_schema=False)
async def admin_get_chat(request: Request, chat_id: str) -> HTMLResponse:
    """Переключение чата — отдаём страницу целиком. Здесь доступны любые чаты."""
    chat = chat_service.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    _set_active(chat.id)
    return _admin_page(request, push_url=f"/admin/chats/{chat.id}")


@ui.post("/chats", response_class=HTMLResponse, include_in_schema=False)
async def admin_create_chat(request: Request) -> HTMLResponse:
    """Новый чат без владельца: в /admin чаты ни к кому не привязаны."""
    chat = chat_service.create_chat()
    _set_active(chat.id)
    return _admin_page(request, push_url=f"/admin/chats/{chat.id}")


# Удаление чата из админки отключено намеренно: админка только смотрит.
# @ui.delete("/chats/{chat_id}", ...)
# async def admin_delete_chat(...): ...
#
# Отправка сообщений из админки тоже отключена — форма не рендерится (readonly).
# @ui.post("/chats/{chat_id}/messages", ...)
# async def admin_send_message(...): ...


@ui.get("/chats/{chat_id}/messages/{message_id}/stream", include_in_schema=False)
async def admin_stream_message(request: Request, chat_id: str, message_id: str) -> StreamingResponse:
    return _stream(chat_id, message_id)


@ui.get("/chats/{chat_id}/footer", response_class=HTMLResponse, include_in_schema=False)
async def admin_chat_footer(request: Request, chat_id: str) -> HTMLResponse:
    """Низ панели чата для админки: форма отправки или плашка перевода."""
    return _chat_footer(request, _require_chat(chat_id), base="/admin", readonly=True, hide_readonly_note=False)


@ui.post("/chats/{chat_id}/upload", response_class=HTMLResponse, include_in_schema=False)
async def admin_upload_file(request: Request, chat_id: str, file: UploadFile) -> HTMLResponse:
    """Загрузка вложения в любой чат из админки (то же, что в REST API)."""
    try:
        await _store_upload(chat_id, file)
    except HTTPException as exc:
        return _upload_failed(str(exc.detail))
    _set_active(chat_id)
    return _admin_page(request)


@ui.delete("/chats/{chat_id}/files/{file_id}", response_class=HTMLResponse, include_in_schema=False)
async def admin_delete_file(request: Request, chat_id: str, file_id: str) -> HTMLResponse:
    """Удаление вложения из любого чата."""
    _require_chat(chat_id)
    attachment_service.delete_file(chat_id, file_id)
    _set_active(chat_id)
    return _admin_page(request)


@ui.get("/chats/{chat_id}/files/{file_id}/content", include_in_schema=False)
async def admin_file_content(chat_id: str, file_id: str) -> Response:
    """Исходные байты картинки — для превью в админке."""
    _require_chat(chat_id)
    return _file_content_response(chat_id, file_id)


app.include_router(ui)


# ------------------------------------------------- handrules (правила агента)
#
# Публичные страницы для правил-подсказок (см. handrules.py). Не под /admin:
# правило заводят из админки по кнопке на ответе агента, но сами страницы —
# обычные, без входа. Тот же CRUD доступен по REST — /ml-api/handrules.


def _rule_page(request: Request, template: str, **ctx: object) -> HTMLResponse:
    """Общий рендер страниц правил. Список чатов в сайдбаре здесь не нужен."""
    return _render(request, template, chats=[], tab="handrules", **ctx)


def _require_handrule(rule_id: str) -> handrules.HandRuleRecord:
    rule = handrules.get(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Правило не найдено")
    return rule


@app.get("/handrules", response_class=HTMLResponse, include_in_schema=False)
async def handrules_list(request: Request) -> HTMLResponse:
    """Список всех правил."""
    return _rule_page(request, "handrules_list.html", rules=handrules.list_all())


# /handrules/new объявлен раньше /handrules/{rule_id}: иначе «new» попал бы в id.
@app.get("/handrules/new", response_class=HTMLResponse, include_in_schema=False)
async def handrules_new(request: Request, query: str = "") -> HTMLResponse:
    """Форма создания правила.

    `query` — вопрос, на который агент ответил не так: приходит из админки
    с кнопки «Ассистент не должен так отвечать» и подставляется в поле
    «На какие сообщения реагировать?».
    """
    return _rule_page(request, "handrules_new.html", query=query, instructions="")


@app.post("/handrules", response_class=HTMLResponse, include_in_schema=False)
async def handrules_create(
    request: Request,
    user_message: str = Form(""),
    instructions: str = Form(""),
) -> Response:
    """Создание правила из формы. Невалидное — возвращаем форму с текстом обратно."""
    try:
        rule = handrules.create(user_message, instructions)
    except handrules.HandRuleError as exc:
        return _rule_page(
            request,
            "handrules_new.html",
            query=user_message,
            instructions=instructions,
            error=str(exc),
        )
    return RedirectResponse(f"/handrules/{rule.id}", status_code=303)


@app.get("/handrules/{rule_id}", response_class=HTMLResponse, include_in_schema=False)
async def handrules_detail(request: Request, rule_id: str) -> HTMLResponse:
    """Одно правило: правка и удаление."""
    return _rule_page(request, "handrules_detail.html", rule=_require_handrule(rule_id))


@app.post("/handrules/{rule_id}", response_class=HTMLResponse, include_in_schema=False)
async def handrules_update(
    request: Request,
    rule_id: str,
    user_message: str = Form(""),
    instructions: str = Form(""),
) -> Response:
    """Сохранение правок со страницы правила."""
    _require_handrule(rule_id)
    try:
        handrules.update(rule_id, user_message, instructions)
    except handrules.HandRuleError as exc:
        rule = _require_handrule(rule_id)
        rule.user_message = user_message
        rule.instructions = instructions
        return _rule_page(request, "handrules_detail.html", rule=rule, error=str(exc))
    return RedirectResponse(f"/handrules/{rule_id}", status_code=303)


@app.delete("/handrules/{rule_id}", response_class=HTMLResponse, include_in_schema=False)
async def handrules_delete(rule_id: str) -> Response:
    """Удаление правила. Возвращаем на список — карточки, которую рисовали, больше нет."""
    handrules.delete(rule_id)
    return RedirectResponse("/handrules", status_code=303)


# ------------------------------------------------- статистика обращений (stats)
#
# Агрегация чатов по темам и подтемам (см. stats.py).
#
#   /stats             — таблица тем: обращений и среднее время ответа
#   /stats/<topic>     — таблица подтем; каждая разворачивается в список чатов
#
# Сортировка — query-параметры sort (count | avg) и desc (true | false).
# В /stats/<topic> сортировка независима на двух уровнях: подтемы между собой,
# чаты — внутри своей подтемы.


def _sort_args(sort: str | None, desc: bool | None) -> tuple[str, bool]:
    """Нормализует сортировку из query-строки. Незнакомый ключ — по умолчанию count."""
    key = sort if sort in stats.SORT_KEYS else stats.SORT_COUNT
    return key, True if desc is None else desc


def _stats_page(request: Request, template: str, **ctx: object) -> HTMLResponse:
    """Рендер страницы статистики. Сайдбар с чатами здесь не нужен."""
    return _render(request, template, chats=[], active_id=None, tab="stats", **ctx)


def _open_args(open: list[str] | None) -> list[str]:
    """Раскрытые подтемы из query. Пустые значения отбрасываем, дубли убираем.

    Имён подтем достаточно: они стабильны и не зависят от порядка сортировки,
    в отличие от индексов строк."""
    seen: list[str] = []
    for name in open or []:
        clean = (name or "").strip()
        if clean and clean not in seen:
            seen.append(clean)
    return seen


def _query_url(base: str, **params: object) -> str:
    """URL с query-параметрами. Списки разворачиваются в повторяющиеся ключи.

    Пустые значения не попадают в строку, чтобы URL оставался читаемым.
    """
    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        values = value if isinstance(value, (list, tuple)) else [value]
        for item in values:
            if item is None or item == "":
                continue
            pairs.append((key, str(item)))
    query = urlencode(pairs)
    return f"{base}?{query}" if query else base


@app.get("/stats", response_class=HTMLResponse, include_in_schema=False)
async def stats_topics(request: Request, sort: str | None = None, desc: bool | None = None) -> HTMLResponse:
    """Темы: количество обращений и среднее время ответа. Строка ведёт на /stats/<topic>."""
    key, descending = _sort_args(sort, desc)
    tree = stats.build_tree(stats.non_empty_chats())
    rows = [
        {
            "name": node.name,
            "count": node.count,
            "avg_seconds": node.avg_seconds,
            "href": f"/stats/{quote(node.name)}",
        }
        for node in stats.sort_nodes(tree, key, descending=descending)
    ]
    return _stats_page(
        request, "stats_topics.html", rows=rows, sort=key, desc=descending, sort_base="/stats"
    )


@app.get("/stats/{topic}", response_class=HTMLResponse, include_in_schema=False)
async def stats_subtopics(
    request: Request,
    topic: str,
    sort: str | None = None,
    desc: bool | None = None,
    open: list[str] | None = Query(default=None),
) -> HTMLResponse:
    """Подтемы темы; каждая разворачивается в список своих чатов.

    Чаты сортируются внутри своей подтемы — независимо от порядка подтем.
    Раскрытые подтемы приходят в `open` (по имени), поэтому смена сортировки
    их не сбрасывает: ссылки сортировки и тогглы пересобираются с тем же open.
    """
    key, descending = _sort_args(sort, desc)
    tree = stats.build_tree(stats.non_empty_chats())
    topic_node = stats.find_topic(tree, topic)
    if topic_node is None:
        raise HTTPException(status_code=404, detail="Тема не найдена")

    open_names = _open_args(open)
    base = f"/stats/{quote(topic_node.name)}"

    def sort_href(next_key: str, next_desc: bool) -> str:
        """Ссылка сортировки: меняет sort/desc, но сохраняет раскрытые подтемы."""
        return _query_url(base, sort=next_key, desc=str(next_desc).lower(), open=open_names)

    def toggle_query(name: str) -> str:
        """Ссылка для клика по подтеме: её имя добавляется или убирается из open.

        sort/desc тоже переносим — клик по подтеме не должен сбрасывать сортировку.
        """
        toggled = [n for n in open_names if n != name]
        if name not in open_names:
            toggled.append(name)
        return _query_url(base, sort=key, desc=str(descending).lower(), open=toggled)

    groups = [
        {
            "name": node.name,
            "count": node.count,
            "avg_seconds": node.avg_seconds,
            "chats": stats.sort_chats(node.chats, key, descending=descending),
        }
        for node in stats.sort_nodes(topic_node.subtopics, key, descending=descending)
    ]
    return _stats_page(
        request,
        "stats_subtopics.html",
        topic=topic_node,
        groups=groups,
        sort=key,
        desc=descending,
        sort_base=base,
        open_names=set(open_names),
        sort_link=sort_href,
        toggle_query=toggle_query,
    )


@app.get("/stats/{topic}/{chat_id}", response_class=HTMLResponse, include_in_schema=False)
async def stats_chat(request: Request, topic: str, chat_id: str) -> HTMLResponse:
    """Переписка одного чата темы, без сайдбара.

    `topic` в URL нужен только для хлебных крошек и проверки, что чат относится
    к открытой теме; сам чат ищется по id. Переписка только для чтения: форма
    отправки не рендерится (readonly), но кнопка «Ассистент не должен так отвечать»
    остаётся — правило заводится прямо со страницы ответа.
    """
    chat = chat_service.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    # Тема в URL должна совпадать с темой чата: иначе ссылка ведёт не туда.
    chat_topic = (chat.topic or "").strip() or stats.UNCLASSIFIED_TOPIC
    if chat_topic != topic:
        raise HTTPException(status_code=404, detail="Чат не относится к этой теме")

    return _render(
        request,
        "stats_chat.html",
        chats=[],
        active_id=None,
        tab="stats",
        topic_name=topic,
        chat=ChatView(chat, streaming_id=_streaming_message_id(chat.id)),
    )


# ------------------------------------------------------------------ / (публичная часть)


def _require_chat(chat_id: str) -> ChatRecord:
    chat = chat_service.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    return chat


async def _start_turn(
    request: Request,
    chat_id: str,
    message: str,
    *,
    base: str,
    role: str | None,
    template: str,
    username: str | None = None,
    turn_hint: str | None = None,
) -> HTMLResponse:
    """Общий запуск хода для / и /admin.

    Роль передаётся в turns → chat.stream_answer и дописывается к вопросу.
    Никаких изменений системного промпта — он остаётся кешируемым.
    turn_hint — служебная подсказка модели для этого хода (оценка ответа,
    запрос оператора): дописывается к вопросу только для модели.
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

    if username is None:
        _set_active(chat_id)
    else:
        _set_active(chat_id, key=_user_active_key(username))

    _user_msg, assistant_msg, _updated = await chat_service.prepare_turn(chat_id, text)

    # Вложения уходят в контекст этого хода. Привязываем их к сообщению и чистим таблицу
    # прямо здесь, до рендера страницы: иначе фоновая генерация успевала бы не всегда,
    # и файлы висели бы над композером до перезагрузки.
    files = attachment_service.list_files(chat_id, with_blobs=True)
    chat_service.bind_attachments(chat_id, _user_msg.id, files)

    TURNS.start(
        chat_id,
        assistant_msg,
        # Вызовы инструментов показываем только в админке (username is None).
        on_event=lambda event, payload: _turn_event_to_sse(
            event, payload, show_tools=username is None
        ),
        user_role=role,
        # Снимок сделан до очистки таблицы — фоновый ход строит по нему контекст модели.
        files=files,
        turn_hint=turn_hint,
    )

    if username is None:
        return _admin_page(request, push_url=f"{base}/chats/{chat_id}")
    return _user_page(
        request,
        username,
        chat=ChatView(_require_chat(chat_id), streaming_id=assistant_msg.id),
        push_url=f"{base}/chats/{chat_id}",
        template=template,
    )


async def _scripted_turn(
    request: Request,
    chat_id: str,
    username: str,
    user_text: str,
    reply: str,
    *,
    rating: str,
    reason: str | None = None,
    base: str = "",
) -> HTMLResponse:
    """Ход без LLM: пишет пару сообщений и стримит захардкоженный ответ.

    Так обрабатываются кнопки оценки: от пользователя уходит текст кнопки,
    система отвечает заранее известным текстом (chat.stream_scripted) и сразу
    сохраняет оценку чата. Кнопки под ответом обновятся сами на sse:done
    (см. _chat_feedback).
    """
    chat = _require_chat(chat_id)
    if chat.is_closed:
        raise HTTPException(
            status_code=409,
            detail=f"Чат закрыт: обращение переведено на линию поддержки {chat.redirect_line}",
        )
    # Оценку пишем до первого await: к моменту запуска хода состояние чата уже
    # актуально (перерисовка фрагмента происходит после done). Двойной клик по кнопке
    # гасит hx-disabled-elt на самой кнопке, пока идёт запрос.
    get_storage().set_chat_rating(chat_id, rating, reason)
    _user_msg, assistant_msg, _updated = await chat_service.prepare_turn(chat_id, user_text)
    _set_active(chat_id, key=_user_active_key(username))
    TURNS.start(
        chat_id,
        assistant_msg,
        on_event=lambda event, payload: _turn_event_to_sse(event, payload, show_tools=False),
        producer=lambda: chat_service.stream_scripted(chat_id, assistant_msg, reply),
    )
    return _user_page(
        request,
        username,
        chat=ChatView(_require_chat(chat_id), streaming_id=assistant_msg.id),
        push_url=f"{base}/chats/{chat_id}",
    )


def _stream(chat_id: str, message_id: str) -> StreamingResponse:
    """SSE-подписка на фоновый ход — общая для / и /admin.

    Подключиться можно в любой момент и сколько угодно раз: генерация живёт
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


def _tool_result_html(name: str, kwargs: dict, is_error: bool) -> str:
    """HTML одного результата инструмента для SSE.

    Совпадает с тем, что рисует шаблон message_assistant.html: без статуса «готово»,
    у read — ссылка на прочитанный документ.
    """
    label = _tool_label(SimpleNamespace(name=name, kwargs=kwargs))
    return f'<div class="tool{" error" if is_error else ""}">{label}</div>'


@app.exception_handler(_NeedLogin)
async def _need_login_handler(request: Request, _exc: _NeedLogin) -> Response:
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request) -> Response:
    """Страница идентификации. Если имя уже есть — уводим на /."""
    if _current_username(request) is not None:
        return RedirectResponse("/", status_code=303)
    return _login_response(request)


@app.post("/login", include_in_schema=False)
async def login_submit(request: Request, username: str = Form("")) -> Response:
    """Сохраняем имя в куке. Пароля нет: имя — просто ярлык для чатов."""
    name = _clean_username(username)
    if not name:
        return _login_response(request, error="Введите имя, чтобы продолжить.", username="")

    get_storage().upsert_user(name)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        USERNAME_COOKIE,
        _encode_username(name),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/logout", include_in_schema=False)
async def logout() -> Response:
    """Забываем имя: чаты при этом не удаляются."""
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(USERNAME_COOKIE)
    return response


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def user_index(request: Request) -> HTMLResponse:
    """Свои чаты: список — только чаты этого пользователя."""
    username = _require_user(request)
    key = _user_active_key(username)
    chat = _panel_chat(_active_id(key))
    return _user_page(request, username, chat=chat)


@app.get("/profile", response_class=HTMLResponse, include_in_schema=False)
async def profile_page(request: Request) -> HTMLResponse:
    """Профиль: имя и выбор роли (по умолчанию «не указано»)."""
    user = _current_user(request)
    if user is None:
        raise _NeedLogin()
    return _render(
        request,
        "user_profile.html",
        username=user.username,
        role=user.role,
        chats=chat_service.list_chats(owner=user.username),
        tab="profile",
    )


@app.post("/profile", include_in_schema=False)
async def profile_save(request: Request, role: str = Form("none")) -> Response:
    """Сохраняем роль. 'none' — сброс в NULL («не указано»)."""
    username = _require_user(request)
    chosen = role if role in ("supplier", "customer") else None
    get_storage().set_user_role(username, chosen)
    return RedirectResponse("/profile", status_code=303)


@app.get("/knowledge-base", response_class=HTMLResponse, include_in_schema=False)
async def user_knowledge_base(request: Request) -> HTMLResponse:
    username = _require_user(request)
    return _knowledge_list(request, base="", template="knowledge_base.html", username=username)


@app.get("/knowledge-base/{slug}", response_class=HTMLResponse, include_in_schema=False)
async def user_knowledge_manual(request: Request, slug: str) -> HTMLResponse:
    username = _require_user(request)
    return _knowledge_manual_page(
        request, slug, base="", template="knowledge_manual.html", username=username
    )


@app.get("/knowledge-base/{slug}/{section_id}", response_class=HTMLResponse, include_in_schema=False)
async def user_knowledge_section(request: Request, slug: str, section_id: str) -> HTMLResponse:
    username = _require_user(request)
    return _knowledge_manual_page(
        request,
        slug,
        base="",
        template="knowledge_manual.html",
        section_id=section_id,
        username=username,
    )


@app.get("/chats/{chat_id}", response_class=HTMLResponse, include_in_schema=False)
async def user_get_chat(request: Request, chat_id: str) -> HTMLResponse:
    """Переключение чата — только своего."""
    username = _require_user(request)
    chat = _user_chat(username, chat_id)
    _set_active(chat.id, key=_user_active_key(username))
    return _user_page(
        request,
        username,
        chat=ChatView(chat, streaming_id=_streaming_message_id(chat.id)),
        push_url=f"/chats/{chat.id}",
    )


@app.post("/chats", response_class=HTMLResponse, include_in_schema=False)
async def user_create_chat(request: Request) -> HTMLResponse:
    """Новый чат с владельцем из куки."""
    username = _require_user(request)
    chat = chat_service.create_chat(owner=username)
    _set_active(chat.id, key=_user_active_key(username))
    return _user_page(request, username, chat=ChatView(chat), push_url=f"/chats/{chat.id}")


@app.delete("/chats/{chat_id}", response_class=HTMLResponse, include_in_schema=False)
async def user_delete_chat(request: Request, chat_id: str) -> HTMLResponse:
    username = _require_user(request)
    _user_chat(username, chat_id)
    chat_service.delete_chat(chat_id)
    key = _user_active_key(username)
    if _active_id(key) == chat_id:
        remaining = chat_service.list_chats(owner=username)
        _set_active(remaining[0].id if remaining else None, key=key)
    return _user_page(request, username, push_url="/")


@app.post("/chats/{chat_id}/messages", response_class=HTMLResponse, include_in_schema=False)
async def user_send_message(request: Request, chat_id: str, message: str = Form(...)) -> HTMLResponse:
    """Отправка сообщения: роль пользователя дописывается к вопросу."""
    username = _require_user(request)
    _user_chat(username, chat_id)
    user = get_storage().get_user(username)
    return await _start_turn(
        request,
        chat_id,
        message,
        base="",
        role=None if user is None else user.role,
        template="user_index.html",
        username=username,
    )


@app.get("/chats/{chat_id}/messages/{message_id}/stream", include_in_schema=False)
async def user_stream_message(request: Request, chat_id: str, message_id: str) -> StreamingResponse:
    username = _require_user(request)
    _user_chat(username, chat_id)
    return _stream(chat_id, message_id)


@app.get("/chats/{chat_id}/footer", response_class=HTMLResponse, include_in_schema=False)
async def user_chat_footer(request: Request, chat_id: str) -> HTMLResponse:
    """Низ панели чата для публичной части: форма отправки или плашка перевода."""
    username = _require_user(request)
    return _chat_footer(request, _user_chat(username, chat_id), base="", readonly=False, hide_readonly_note=False)


@app.get("/chats/{chat_id}/feedback", response_class=HTMLResponse, include_in_schema=False)
async def user_chat_feedback(request: Request, chat_id: str) -> HTMLResponse:
    """Кнопки оценки под последним ответом — фрагмент, который обновляется на sse:done."""
    username = _require_user(request)
    return _chat_feedback(request, _user_chat(username, chat_id), base="", readonly=False)


@app.post("/chats/{chat_id}/feedback", response_class=HTMLResponse, include_in_schema=False)
async def user_feedback(request: Request, chat_id: str, value: str = Form(...)) -> HTMLResponse:
    """Кнопка оценки: «Спасибо за помощь» или «Ответ мне не подходит».

    Обе кнопки — ход без LLM: от пользователя уходит текст кнопки, система
    отвечает захардкоженным текстом, а в чат пишется оценка. Кнопки остаются
    под ответом и после выбора: повторный клик перетирает прежнюю оценку
    (оценка всё равно одна на чат). После negative появляются причины
    и «Позови оператора» (см. ChatView.feedback_context).
    """
    username = _require_user(request)
    _user_chat(username, chat_id)
    if value == "positive":
        return await _scripted_turn(
            request,
            chat_id,
            username,
            feedback.POSITIVE_LABEL,
            feedback.POSITIVE_REPLY,
            rating="positive",
        )
    if value == "negative":
        return await _scripted_turn(
            request,
            chat_id,
            username,
            feedback.NEGATIVE_LABEL,
            feedback.NEGATIVE_REPLY,
            rating="negative",
        )
    raise HTTPException(status_code=400, detail="Неизвестная оценка ответа")


@app.post("/chats/{chat_id}/feedback/reason", response_class=HTMLResponse, include_in_schema=False)
async def user_feedback_reason(request: Request, chat_id: str, reason: str = Form(...)) -> HTMLResponse:
    """Выбранная причина: обычный ход с LLM, которая перегенерирует ответ с замечанием.

    Показывается только в состоянии «negative без причины», но повторный запрос
    не блокируем: он просто перетирает причину и запускает новый ход.
    """
    username = _require_user(request)
    _user_chat(username, chat_id)
    chosen = " ".join(reason.split())
    if not feedback.is_reason(chosen):
        raise HTTPException(status_code=400, detail="Неизвестная причина")
    get_storage().set_chat_rating(chat_id, "negative", chosen)
    user = get_storage().get_user(username)
    return await _start_turn(
        request,
        chat_id,
        chosen,
        base="",
        role=None if user is None else user.role,
        template="user_index.html",
        username=username,
        turn_hint=feedback.reason_hint(chosen),
    )


@app.post("/chats/{chat_id}/feedback/operator", response_class=HTMLResponse, include_in_schema=False)
async def user_feedback_operator(request: Request, chat_id: str) -> HTMLResponse:
    """«Позови оператора»: обычный ход с LLM, которая решает вопрос перевода на линию."""
    username = _require_user(request)
    _user_chat(username, chat_id)
    get_storage().set_chat_rating(chat_id, "negative", feedback.OPERATOR_LABEL)
    user = get_storage().get_user(username)
    return await _start_turn(
        request,
        chat_id,
        feedback.OPERATOR_LABEL,
        base="",
        role=None if user is None else user.role,
        template="user_index.html",
        username=username,
        turn_hint=feedback.operator_hint(),
    )


@app.post("/chats/{chat_id}/upload", response_class=HTMLResponse, include_in_schema=False)
async def user_upload_file(request: Request, chat_id: str, file: UploadFile) -> HTMLResponse:
    """Загрузка одного вложения в свой чат: картинка или документ до 10 МБ.

    Документ прогоняется через docling без OCR, картинка сохраняется как есть.
    В ответ отдаём всю страницу — список вложений над композером обновится сам.
    """
    username = _require_user(request)
    _user_chat(username, chat_id)
    try:
        await _store_upload(chat_id, file)
    except HTTPException as exc:
        return _upload_failed(str(exc.detail))
    return _user_page(
        request,
        username,
        chat=ChatView(_require_chat(chat_id), streaming_id=_streaming_message_id(chat_id)),
    )


@app.delete("/chats/{chat_id}/files/{file_id}", response_class=HTMLResponse, include_in_schema=False)
async def user_delete_file(request: Request, chat_id: str, file_id: str) -> HTMLResponse:
    """Удаление вложения: файл не уйдёт в контекст модели."""
    username = _require_user(request)
    _user_chat(username, chat_id)
    attachment_service.delete_file(chat_id, file_id)
    return _user_page(
        request,
        username,
        chat=ChatView(_require_chat(chat_id), streaming_id=_streaming_message_id(chat_id)),
    )


@app.get("/chats/{chat_id}/files/{file_id}/content", include_in_schema=False)
async def user_file_content(request: Request, chat_id: str, file_id: str) -> Response:
    """Исходные байты картинки из своего чата — для превью в списке вложений."""
    username = _require_user(request)
    _user_chat(username, chat_id)
    return _file_content_response(chat_id, file_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8010)
