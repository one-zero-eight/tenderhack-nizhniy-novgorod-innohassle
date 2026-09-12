"""REST API: `/ml-api/chat` для чатов и `/ml-api/knowledge-base` для мануалов.

Эндпоинты чатов:
    POST   /ml-api/chat                        — создать чат, вернуть id
    GET    /ml-api/chat                        — список чатов
    GET    /ml-api/chat/<id>                   — содержимое чата (сообщения + вызовы инструментов)
    DELETE /ml-api/chat/<id>                   — удалить чат
    POST   /ml-api/chat/<id>/message           — SSE-стрим ответа агента и вызовов инструментов

Эндпоинты вложений чата:
    POST   /ml-api/chat/<id>/upload            — загрузить один файл или картинку (до 10 МБ)
    GET    /ml-api/chat/<id>/files             — список загруженных, но ещё не отправленных файлов
    GET    /ml-api/chat/<id>/files/<file_id>   — метаданные одного файла
    GET    /ml-api/chat/<id>/files/<file_id>/content — содержимое (для картинок)
    DELETE /ml-api/chat/<id>/files/<file_id>   — удалить файл из чата

Эндпоинты вложений (постоянные):
    GET    /attachments/<file_id>              — оригинал загруженного файла (см. assets.py)

Эндпоинты базы знаний:
    GET /ml-api/knowledge-base               — список мануалов
    GET /ml-api/knowledge-base/<slug>        — структура мануала (все разделы дерева)
    GET /ml-api/knowledge-base/<slug>/<id>   — markdown одного раздела

Вложения живут в двух местах: оригиналы — в папке `attachments/` (отдаются по
`GET /attachments/<id>` и видны в истории чата), а таблица `chat_files` хранит только
ожидающий контекст. При отправке сообщения файлы уходят в модель (картинки — как
изображения, документы — как markdown), а строки из таблицы удаляются.

Никакой аутентификации: все чаты общие, доступ по id.

Параметр `username` необязателен: он только фильтрует чаты по владельцу (когда задан)
или назначает владельца при создании. Если не задан — поведение как раньше, все чаты.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Body, File, HTTPException, Path, Query, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

import attachments as attachment_service
import chat as chat_service
from manuals import Manual, Section, section_body
from rag import state
from storage import ChatRecord, clean_username, get_storage

router = APIRouter(prefix="/ml-api", tags=["ml-api"])


def _manuals() -> dict[str, Manual]:
    """Загруженные мануалы: slug -> Manual."""
    manuals, _ = state()
    return manuals


SSE_MEDIA_TYPE = "text/event-stream"
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

# --------------------------------------------------------------- pydantic DTO


class ToolCallOut(BaseModel):
    """Один вызов инструмента агентом (search/open) внутри ответа ассистента."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Идентификатор вызова инструмента (tool_call_id из LLM)")
    name: str = Field(description="Имя инструмента, например `search` или `open`")
    kwargs: dict[str, object] = Field(default_factory=dict, description="Аргументы вызова, как их передал агент")
    output: str | None = Field(
        default=None,
        description="Результат инструмента. `null`, пока вызов ещё выполняется",
    )
    error: bool = Field(default=False, description="`true`, если инструмент вернул ошибку")


class ChatFileOut(BaseModel):
    """Загруженный в чат файл или картинка.

    В таблице `chat_files` живёт только до следующего сообщения, но оригинал остаётся
    в `attachments/<id>` — поэтому `url` работает и для уже отправленных вложений.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Идентификатор вложения, нужен для удаления и получения содержимого")
    chat_id: str = Field(description="Чат, к которому приложен файл")
    filename: str = Field(description="Исходное имя файла", examples=["dogovor.pdf"])
    content_type: str = Field(description="MIME-тип файла", examples=["application/pdf"])
    kind: str = Field(
        description="`image` — картинка хранится как есть; `document` — сконвертирована в markdown",
        examples=["document"],
    )
    size: int = Field(description="Размер исходного файла в байтах", examples=[102400])
    is_image: bool = Field(description="`true`, если это картинка (уйдёт модели как изображение)")
    created_at: str = Field(description="Время загрузки, ISO 8601")
    url: str = Field(
        description=(
            "Постоянная ссылка на оригинал файла (`/attachments/<id>`). Работает и после "
            "отправки сообщения — файл остаётся доступным из истории чата"
        ),
        examples=["/attachments/cd34ef56"],
    )


class MessageOut(BaseModel):
    """Сообщение чата: пользовательское или ответ ассистента с историей тулколов."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Идентификатор сообщения")
    role: str = Field(description="Роль автора: `user` или `assistant`")
    content: str = Field(default="", description="Текст сообщения (markdown для ассистента)")
    tools: list[ToolCallOut] = Field(
        default_factory=list,
        description="Вызовы инструментов. Непусто только у сообщений ассистента",
    )
    attachments: list[ChatFileOut] = Field(
        default_factory=list,
        description=(
            "Файлы, отправленные вместе с сообщением. Оригиналы остаются доступными по "
            "`url` и после отправки в модель"
        ),
    )


class ChatSummary(BaseModel):
    """Чат без сообщений — то, что возвращается при создании и в списке."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Идентификатор чата, используется во всех дальнейших запросах")
    title: str = Field(description="Заголовок чата (первое сообщение пользователя либо «Новый чат»)")
    owner: str | None = Field(
        default=None,
        description=(
            "Имя пользователя, которому принадлежит чат (публичная часть `/`). "
            "`null` — чат создан без владельца (например, из `/admin`). "
            "Чаты, созданные до появления публичной части, помечены `legacy`"
        ),
    )
    system_prompt: str | None = Field(
        default=None,
        description="Дополнительный системный промпт, заданный при создании чата (дописывается к базовому)",
    )
    redirect_line: str | None = Field(
        default=None,
        description="Линия поддержки, на которую переведён чат (`L1`/`L2`). `null`, пока не переведён",
    )
    redirect_reason: str | None = Field(default=None, description="Пояснение от агента для оператора поддержки")
    topic: str | None = Field(
        default=None,
        description=(
            "Тема обращения из классификатора. `null`, пока фоновая классификация "
            "не завершилась (запускается после первого ответа)"
        ),
    )
    subtopic: str | None = Field(
        default=None,
        description="Подтема обращения внутри темы. `Прочее`, если точного соответствия нет",
    )
    closed_at: str | None = Field(
        default=None,
        description="Время перевода на линию поддержки. Если не `null`, чат закрыт и писать в него нельзя",
    )
    created_at: str = Field(description="Время создания, ISO 8601")
    updated_at: str = Field(description="Время последнего изменения, ISO 8601")


class ChatOut(ChatSummary):
    """Полное содержимое чата: метаданные плюс вся переписка по порядку."""

    messages: list[MessageOut] = Field(default_factory=list, description="Сообщения в хронологическом порядке")


class ChatIn(BaseModel):
    """Тело запроса на создание чата."""

    system_prompt: str | None = Field(
        default=None,
        max_length=8000,
        description=(
            "Дополнительный системный промпт. **Не переопределяет** базовый промпт агента, "
            "а дописывается в его конец — удобно передать контекст пользователя "
            "(роль на портале, регион, название организации и т.п.)."
        ),
        examples=["Пользователь: ООО «Ромашка», поставщик, регион — Москва."],
    )
    username: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Владелец чата. Если задан, чат появится в списке этого пользователя "
            "в публичной части и будет доступен там только ему. "
            "Если не задан — чат создаётся без владельца и виден только в общем списке"
        ),
        examples=["Иван Петров"],
    )


class MessageIn(BaseModel):
    """Тело запроса для отправки сообщения агенту."""

    message: str = Field(
        min_length=1,
        max_length=8000,
        description="Текст вопроса пользователя на русском",
        examples=["Как создать котировочную сессию?"],
    )


class ErrorOut(BaseModel):
    """Стандартная ошибка FastAPI."""

    detail: str = Field(description="Человекочитаемое описание ошибки")


# --------------------------------------------------- база знаний (DTO)


class ManualSummary(BaseModel):
    """Мануал в списке: без разделов, только метаданные."""

    slug: str = Field(
        description="Идентификатор мануала в URL, например `instrukciya-po-sozdaniyu-oferty-i-ste`",
        examples=["instrukciya-po-sozdaniyu-oferty-i-ste"],
    )
    title: str = Field(
        description="Человеческое название мануала из заголовка документа",
        examples=["Инструкция по созданию оферты и СТЕ"],
    )
    sections: int = Field(
        description="Число разделов мануала",
        examples=[42],
    )
    url: str = Field(
        description="Путь до страницы мануала в веб-интерфейсе",
        examples=["/knowledge-base/customer-portal"],
    )


class ManualSectionNode(BaseModel):
    """Раздел мануала внутри структуры (дерева). Без текста."""

    id: str = Field(
        description="Иерархический id раздела: `5`, `5.2`, `5.2.1`",
        examples=["5.2.1"],
    )
    title: str = Field(
        description="Заголовок раздела без номера",
        examples=["Добавить код ЕРУЗ"],
    )
    title_line: str = Field(
        description="Номер и заголовок одной строкой — то, что видно в оглавлении",
        examples=["5.2.1 Добавить код ЕРУЗ"],
    )
    depth: int = Field(
        description="Уровень вложенности: 0 — раздел верхнего уровня",
        examples=[2],
    )
    ancestors: list[str] = Field(
        default_factory=list,
        description="Цепочка родительских id от верхнего раздела вниз, без самого раздела",
        examples=[["5", "5.2"]],
    )
    has_content: bool = Field(description="`true`, если у раздела есть собственный текст (а не только подразделы)")
    children: list[str] = Field(
        default_factory=list,
        description="id непосредственных подразделов в порядке документа",
        examples=[["5.2.1", "5.2.2"]],
    )
    url: str = Field(
        description="Путь до страницы раздела в веб-интерфейсе",
        examples=["/knowledge-base/customer-portal/8.2.1"],
    )


class ManualStructure(BaseModel):
    """Полная структура мануала: все разделы плоским списком в порядке документа."""

    slug: str = Field(description="Идентификатор мануала", examples=["instrukciya-po-sozdaniyu-oferty-i-ste"])
    title: str = Field(description="Название мануала", examples=["Инструкция по созданию оферты и СТЕ"])
    sections: list[ManualSectionNode] = Field(
        default_factory=list,
        description="Все разделы в порядке документа",
    )


class ManualSection(BaseModel):
    """Содержимое одного раздела: markdown-текст плюс навигация по дереву."""

    slug: str = Field(description="Идентификатор мануала", examples=["instrukciya-po-sozdaniyu-oferty-i-ste"])
    manual_title: str = Field(description="Название мануала", examples=["Инструкция по созданию оферты и СТЕ"])
    id: str = Field(description="id раздела внутри мануала", examples=["5.2.1"])
    title: str = Field(description="Заголовок раздела без номера", examples=["Добавить код ЕРУЗ"])
    title_line: str = Field(description="Номер и заголовок одной строкой", examples=["5.2.1 Добавить код ЕРУЗ"])
    ancestors: list[str] = Field(
        default_factory=list,
        description="id родителей от корня вниз — по ним строится путь в оглавлении",
        examples=[["5", "5.2"]],
    )
    breadcrumbs: list[str] = Field(
        default_factory=list,
        description="Читаемый путь по заголовкам, включая сам раздел",
        examples=[["Перед началом работы", "Для исполнения через ЕИС необходимо", "Добавить код ЕРУЗ"]],
    )
    children: list[str] = Field(
        default_factory=list,
        description="id непосредственных подразделов в порядке документа",
        examples=[["5.2.1", "5.2.2"]],
    )
    content: str = Field(
        description=(
            "Текст раздела в markdown. Ссылки на картинки уже абсолютные "
            "(`/ml-assets/image/<slug>/image-N.png`) — их можно подставлять в `<img src>`."
        )
    )
    url: str = Field(
        description="Путь до страницы раздела в веб-интерфейсе",
        examples=["/knowledge-base/customer-portal/8.2.1"],
    )


class StreamEventInfo(BaseModel):
    """Описание SSE-события, которое может прийти в стриме ответа."""

    event: str = Field(description="Имя SSE-события")
    data: str = Field(description="JSON-payload события")
    description: str = Field(description="Когда приходит и что означает")


STREAM_EVENTS: list[StreamEventInfo] = [
    StreamEventInfo(
        event="start",
        data='{"message_id": "..."}',
        description="Всегда первым. Возвращает id созданного сообщения ассистента",
    ),
    StreamEventInfo(
        event="token",
        data='{"delta": "...", "content": "..."}',
        description="Дельта текста ответа и накопленный текст целиком (для рендера markdown заново)",
    ),
    StreamEventInfo(
        event="tool_call",
        data='{"type": "tool_call", "id": "...", "name": "search", "kwargs": {}, "output": null}',
        description="Агент вызвал инструмент; `output` пока null",
    ),
    StreamEventInfo(
        event="tool_result",
        data='{"type": "tool_result", "id": "...", "name": "search", "output": "...", "error": false}',
        description="Инструмент завершился; id совпадает с tool_call",
    ),
    StreamEventInfo(
        event="error",
        data='{"message": "..."}',
        description="Ошибка выполнения агента. Стрим всё равно закрывается событием done",
    ),
    StreamEventInfo(
        event="redirect",
        data='{"line": "L2", "reason": "..."}',
        description=("Агент перевёл обращение на линию поддержки; чат закрыт, дальнейшие сообщения отклоняются с 409"),
    ),
    StreamEventInfo(
        event="done",
        data='{"message_id": "...", "content": "..."}',
        description="Последнее событие: финальный текст ответа, уже сохранённый в БД",
    ),
]


def _summary(record: ChatRecord) -> ChatSummary:
    return ChatSummary.model_validate(record.to_dict(with_messages=False))


def _full(record: ChatRecord) -> ChatOut:
    return ChatOut.model_validate(record.to_dict(with_messages=True))


# ------------------------------------------------------------------- helpers


def _require_chat(chat_id: str) -> ChatRecord:
    record = chat_service.get_chat(chat_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Чат не найден")
    return record


# --------------------------------------------------- база знаний (helpers)


def _manual_url(slug: str, section_id: str | None = None) -> str:
    """Путь до страницы мануала или раздела в веб-интерфейсе."""
    base = f"/knowledge-base/{slug}"
    return base if section_id is None else f"{base}/{section_id}"


def _require_manual(slug: str) -> Manual:
    manual = _manuals().get(slug)
    if manual is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мануал не найден")
    return manual


def _section_node(manual: Manual, section: Section) -> ManualSectionNode:
    return ManualSectionNode(
        id=section.id,
        title=section.heading,
        title_line=section.title_line,
        depth=len(section.ancestors),
        ancestors=list(section.ancestors),
        has_content=bool(section.text),
        children=[c for c in section.children if c in manual.sections],
        url=_manual_url(manual.slug, section.id),
    )


# ------------------------------------------------------------------ endpoints


@router.post(
    "/chat",
    response_model=ChatSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Создать чат",
    description=(
        "Создаёт пустой чат и возвращает его идентификатор. "
        "Дальше сообщения отправляются в `POST /ml-api/chat/{chat_id}/message`.\n\n"
        "Опциональным полем `system_prompt` можно передать контекст: он дописывается "
        "к базовому системному промпту агента, не заменяя его.\n\n"
        "Опциональное поле `username` назначает владельца: такой чат появится в публичной "
        "части `/` у этого пользователя. Без `username` чат ничей и виден только в общем списке."
    ),
    response_description="Созданный чат",
    responses={500: {"model": ErrorOut, "description": "Ошибка хранилища"}},
)
async def create_chat(payload: Annotated[ChatIn | None, Body()] = None) -> ChatSummary:
    return _summary(
        chat_service.create_chat(
            payload.system_prompt if payload else None,
            owner=clean_username(payload.username if payload else None),
        )
    )


@router.get(
    "/chat",
    response_model=list[ChatSummary],
    summary="Список чатов",
    description=(
        "Возвращает чаты, свежие сверху. Без сообщений.\n\n"
        "Параметр `username` фильтрует чаты по владельцу. Если он не задан или пуст — "
        "возвращаются **все** чаты, включая ничейные и `legacy`."
    ),
    response_description="Список чатов",
)
async def list_chats(
    limit: Annotated[
        int,
        Query(ge=1, le=200, description="Сколько чатов вернуть максимум", examples=[50]),
    ] = 50,
    username: Annotated[
        str | None,
        Query(
            description=(
                "Вернуть только чаты этого пользователя. Не указан или пуст — все чаты"
            ),
            examples=["Иван Петров"],
        ),
    ] = None,
) -> list[ChatSummary]:
    owner = clean_username(username)
    return [_summary(record) for record in chat_service.list_chats(owner=owner)[:limit]]


@router.get(
    "/chat/{chat_id}",
    response_model=ChatOut,
    summary="Содержимое чата",
    description=(
        "Возвращает чат целиком: метаданные, все сообщения по порядку и для каждого ответа "
        "ассистента — историю вызовов инструментов с их аргументами и результатами."
    ),
    response_description="Чат с сообщениями и тулколами",
    responses={404: {"model": ErrorOut, "description": "Чат не найден"}},
)
async def get_chat(
    chat_id: Annotated[str, Path(description="Идентификатор чата из `POST /ml-api/chat`")],
) -> ChatOut:
    return _full(_require_chat(chat_id))


@router.delete(
    "/chat/{chat_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить чат",
    description="Удаляет чат вместе со всеми сообщениями и вызовами инструментов.",
    responses={404: {"model": ErrorOut, "description": "Чат не найден"}},
)
async def delete_chat(
    chat_id: Annotated[str, Path(description="Идентификатор чата")],
) -> None:
    _require_chat(chat_id)
    chat_service.delete_chat(chat_id)


@router.post(
    "/chat/{chat_id}/upload",
    response_model=ChatFileOut,
    status_code=status.HTTP_201_CREATED,
    summary="Загрузить файл или картинку в чат",
    description=(
        "Загружает **один** файл за запрос (`multipart/form-data`, поле `file`) и возвращает "
        "его id. Максимум — **10 МБ**.\n\n"
        "Как обрабатывается файл:\n\n"
        "- **картинка** (`png`, `jpg`, `jpeg`, `gif`, `webp`, `bmp`) — сохраняется как есть "
        "и на следующем сообщении уйдёт модели как изображение;\n"
        "- **документ** (`pdf`, `docx`, `xlsx`, `pptx`, `html`, `md`, `csv`, `txt`, ...) — "
        "сначала прогоняется через docling с выключенным OCR: картинки из документа "
        "выбрасываются, на их месте остаются плейсхолдеры `<!-- image -->`, а в БД "
        "уходит чистый markdown.\n\n"
        "Файлы копятся в чате и видны в `GET /ml-api/chat/{chat_id}/files`. "
        "При отправке сообщения (`POST /ml-api/chat/{chat_id}/message`) они уходят "
        "в контекст модели и удаляются.\n\n"
        "**Пример:**\n\n"
        "```bash\n"
        "curl -X POST http://localhost:8010/ml-api/chat/$ID/upload \\\n"
        '  -F "file=@dogovor.pdf"\n'
        "```"
    ),
    response_description="Загруженный файл",
    responses={
        400: {"model": ErrorOut, "description": "Файл пуст, слишком большой или неподдерживаемого формата"},
        404: {"model": ErrorOut, "description": "Чат не найден"},
        409: {"model": ErrorOut, "description": "Чат закрыт"},
        422: {"model": ErrorOut, "description": "Файл не передан"},
    },
)
async def upload_file(
    chat_id: Annotated[str, Path(description="Идентификатор чата")],
    file: Annotated[UploadFile, File(description="Один файл или картинка, до 10 МБ")],
) -> ChatFileOut:
    chat = _require_chat(chat_id)
    if chat.is_closed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Чат закрыт: обращение переведено на линию поддержки {chat.redirect_line}",
        )

    # Читаем с запасом в один байт, чтобы отличить ровно 10 МБ от «больше 10 МБ»
    # и не тянуть в память гигабайтную загрузку целиком.
    data = await file.read(attachment_service.MAX_FILE_SIZE + 1)
    try:
        record = attachment_service.save_file(
            chat_id,
            file.filename or "file",
            file.content_type,
            data,
        )
    except attachment_service.AttachmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ChatFileOut.model_validate(record.to_dict())


@router.get(
    "/chat/{chat_id}/files",
    response_model=list[ChatFileOut],
    summary="Список файлов чата",
    description=(
        "Возвращает загруженные, но ещё не отправленные вложения чата в порядке загрузки. "
        "После `POST /ml-api/chat/{chat_id}/message` список пустеет: файлы уходят в контекст модели."
    ),
    response_description="Вложения чата",
    responses={404: {"model": ErrorOut, "description": "Чат не найден"}},
)
async def list_files(
    chat_id: Annotated[str, Path(description="Идентификатор чата")],
) -> list[ChatFileOut]:
    _require_chat(chat_id)
    return [ChatFileOut.model_validate(item.to_dict()) for item in attachment_service.list_files(chat_id)]


@router.get(
    "/chat/{chat_id}/files/{file_id}",
    response_model=ChatFileOut,
    summary="Метаданные файла",
    description="Одно вложение чата без содержимого.",
    responses={
        404: {"model": ErrorOut, "description": "Чат или файл не найден"},
    },
)
async def get_file(
    chat_id: Annotated[str, Path(description="Идентификатор чата")],
    file_id: Annotated[str, Path(description="Идентификатор файла из `POST .../upload`")],
) -> ChatFileOut:
    _require_chat(chat_id)
    record = attachment_service.get_file(chat_id, file_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    return ChatFileOut.model_validate(record.to_dict())


@router.get(
    "/chat/{chat_id}/files/{file_id}/content",
    response_class=Response,
    response_model=None,
    summary="Содержимое файла",
    description=(
        "Отдаёт оригинал вложения, ожидающего отправки. Для картинок это готовый `image/*`, "
        "который можно подставить в `<img src>`.\n\n"
        "После отправки сообщения вложение пропадает из этого списка — тогда используйте "
        "постоянную ссылку `GET /attachments/{file_id}` из поля `url`."
    ),
    responses={
        200: {"description": "Файл", "content": {"application/octet-stream": {}}},
        404: {"model": ErrorOut, "description": "Файл не найден"},
    },
)
async def get_file_content(
    chat_id: Annotated[str, Path(description="Идентификатор чата")],
    file_id: Annotated[str, Path(description="Идентификатор файла")],
) -> Response:
    _require_chat(chat_id)
    found = attachment_service.read_original(file_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    data, content_type, filename = found
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": attachment_service.content_disposition(filename),
        },
    )


@router.delete(
    "/chat/{chat_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить файл из чата",
    description="Убирает вложение, не отправляя его модели.",
    responses={404: {"model": ErrorOut, "description": "Чат или файл не найден"}},
)
async def delete_file(
    chat_id: Annotated[str, Path(description="Идентификатор чата")],
    file_id: Annotated[str, Path(description="Идентификатор файла")],
) -> None:
    _require_chat(chat_id)
    if not attachment_service.delete_file(chat_id, file_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")


@router.post(
    "/chat/{chat_id}/message",
    response_class=StreamingResponse,
    response_model=None,
    summary="Отправить сообщение агенту (SSE)",
    description=(
        "Записывает сообщение пользователя и стримит ответ агента в формате `text/event-stream`.\n\n"
        "**Вложения:** все файлы, загруженные через `POST /ml-api/chat/{chat_id}/upload` "
        "и ещё не удалённые, прикрепляются к этому сообщению: картинки уходят модели "
        "как изображения, документы — как markdown-текст. После отправки вложения "
        "удаляются из БД, поэтому список файлов чата снова пуст.\n\n"
        "**События стрима:**\n\n"
        + "\n".join(f"- `{event.event}` — {event.description}. payload: `{event.data}`" for event in STREAM_EVENTS)
        + "\n\nОтвет агента сохраняется в БД по мере генерации, поэтому `GET /ml-api/chat/{chat_id}` "
        "после обрыва соединения вернёт уже сгенерированный текст.\n\n"
        "**Пример:**\n\n"
        "```bash\n"
        "curl -N -X POST http://localhost:8010/ml-api/chat/$ID/message \\\n"
        "  -H 'Content-Type: application/json' \\\n"
        '  -d \'{"message": "Как создать котировочную сессию?"}\'\n'
        "```"
    ),
    responses={
        200: {
            "description": "Поток SSE-событий (см. описание выше)",
            "content": {
                SSE_MEDIA_TYPE: {
                    "schema": {"type": "string"},
                    "example": (
                        'event: start\ndata: {"message_id": "a1b2"}\n\n'
                        'event: tool_call\ndata: {"type": "tool_call", "id": "t1", '
                        '"name": "search", "kwargs": {"manual": "..."}, "output": null}\n\n'
                        'event: tool_result\ndata: {"type": "tool_result", "id": "t1", '
                        '"name": "search", "output": "...", "error": false}\n\n'
                        'event: token\ndata: {"delta": "Что", "content": "Что"}\n\n'
                        'event: done\ndata: {"message_id": "a1b2", "content": "Что ..."}\n\n'
                    ),
                }
            },
        },
        404: {"model": ErrorOut, "description": "Чат не найден"},
        409: {
            "model": ErrorOut,
            "description": "Чат закрыт: обращение уже переведено на линию поддержки",
        },
        422: {"model": ErrorOut, "description": "Пустое сообщение или невалидное тело"},
    },
)
async def send_message(
    chat_id: Annotated[str, Path(description="Идентификатор чата")],
    payload: Annotated[MessageIn, Body()],
) -> StreamingResponse:
    chat = _require_chat(chat_id)
    if chat.is_closed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Чат закрыт: обращение переведено на линию поддержки {chat.redirect_line}",
        )
    text = payload.message.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Пустое сообщение")

    async def events() -> AsyncIterator[str]:
        try:
            files = attachment_service.list_files(chat_id, with_blobs=True)
            async for chunk in chat_service.run_turn(chat_id, text, files=files):
                yield chunk
        except KeyError:
            yield chat_service.sse("error", {"message": "Чат не найден"})
        except chat_service.ChatClosedError as exc:
            yield chat_service.sse("error", {"message": str(exc)})

    return StreamingResponse(events(), media_type=SSE_MEDIA_TYPE, headers=SSE_HEADERS)


# ------------------------------------------ база знаний (endpoints)


@router.get(
    "/knowledge-base",
    response_model=list[ManualSummary],
    summary="Список мануалов",
    description=(
        "Возвращает все загруженные инструкции Портала поставщиков: slug, название, "
        "число разделов и ссылку на страницу в веб-интерфейсе.\n\n"
        "Из `slug` собираются остальные запросы к базе знаний."
    ),
    response_description="Список мануалов в алфавитном порядке slug",
)
async def list_manuals() -> list[ManualSummary]:
    return [
        ManualSummary(
            slug=manual.slug,
            title=manual.name,
            sections=len(manual.sections),
            url=_manual_url(manual.slug),
        )
        for manual in _manuals().values()
    ]


@router.get(
    "/knowledge-base/{slug}",
    response_model=ManualStructure,
    summary="Структура мануала",
    description=(
        "Возвращает все разделы мануала плоским списком в порядке документа.\n\n"
        "Иерархия задаётся полями `depth`, `ancestors` и `children`: "
        "`depth` — уровень вложенности (0 — раздел верхнего уровня), `ancestors` — цепочка "
        "родителей от верхнего раздела вниз, "
        "`children` — id непосредственных подразделов. Текста разделов здесь нет — "
        "за ним идите в `GET /ml-api/knowledge-base/{slug}/{section_id}`."
    ),
    response_description="Структура мануала",
    responses={404: {"model": ErrorOut, "description": "Мануал не найден"}},
)
async def get_manual_structure(
    slug: Annotated[
        str,
        Path(
            description="Slug мануала из `GET /ml-api/knowledge-base`",
            examples=["instrukciya-po-sozdaniyu-oferty-i-ste"],
        ),
    ],
) -> ManualStructure:
    manual = _require_manual(slug)
    ordered = manual.ordered_ids
    return ManualStructure(
        slug=manual.slug,
        title=manual.name,
        sections=[_section_node(manual, manual.sections[i]) for i in ordered],
    )


@router.get(
    "/knowledge-base/{slug}/{section_id}",
    response_model=ManualSection,
    summary="Содержимое раздела мануала",
    description=(
        "Возвращает один раздел инструкции: текст в markdown плюс навигацию по дереву.\n\n"
        "`section_id` — иерархический номер из структуры мануала (`5`, `5.2.1`). "
        "Ссылки на картинки в тексте уже абсолютные (`/ml-assets/image/<slug>/image-N.png`), "
        "их можно подставлять в `<img src>` как есть.\n\n"
        "Поле `breadcrumbs` даёт читаемый путь до раздела — его удобно показывать пользователю."
    ),
    response_description="Раздел мануала с markdown-текстом",
    responses={
        404: {"model": ErrorOut, "description": "Мануал или раздел не найден"},
    },
)
async def get_manual_section(
    slug: Annotated[
        str,
        Path(
            description="Slug мануала из `GET /ml-api/knowledge-base`",
            examples=["instrukciya-po-sozdaniyu-oferty-i-ste"],
        ),
    ],
    section_id: Annotated[
        str,
        Path(
            description="id раздела из `GET /ml-api/knowledge-base/{slug}`",
            examples=["5.2.1"],
        ),
    ],
) -> ManualSection:
    manual = _require_manual(slug)
    section = manual.sections.get(section_id)
    if section is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Раздел не найден")

    # Путь по заголовкам: предки от корня вниз плюс сам раздел.
    breadcrumbs = [
        *(manual.sections[a].heading for a in section.ancestors if a in manual.sections),
        section.heading,
    ]
    return ManualSection(
        slug=manual.slug,
        manual_title=manual.title,
        id=section.id,
        title=section.heading,
        title_line=section.title_line,
        ancestors=list(section.ancestors),
        breadcrumbs=breadcrumbs,
        children=[c for c in section.children if c in manual.sections],
        content=section_body(section),
        url=_manual_url(manual.slug, section.id),
    )


__all__ = [
    "STREAM_EVENTS",
    "ChatFileOut",
    "ChatIn",
    "ChatOut",
    "ChatSummary",
    "ErrorOut",
    "ManualSection",
    "ManualSectionNode",
    "ManualStructure",
    "ManualSummary",
    "MessageIn",
    "MessageOut",
    "ToolCallOut",
    "router",
]
