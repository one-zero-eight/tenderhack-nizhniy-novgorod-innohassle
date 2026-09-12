"""REST API чатов: /ml-api/chat ...

Эндпоинты:
    POST /ml-api/chat                — создать чат, вернуть id
    GET  /ml-api/chat/<id>           — содержимое чата (сообщения + вызовы инструментов)
    POST /ml-api/chat/<id>/message   — SSE-стрим ответа агента и вызовов инструментов

Никакой аутентификации: все чаты общие, доступ по id.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Path, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

import chat as chat_service
from storage import ChatRecord, get_storage
router = APIRouter(prefix="/ml-api", tags=["ml-api"])

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
    kwargs: dict[str, object] = Field(
        default_factory=dict, description="Аргументы вызова, как их передал агент"
    )
    output: str | None = Field(
        default=None,
        description="Результат инструмента. `null`, пока вызов ещё выполняется",
    )
    error: bool = Field(default=False, description="`true`, если инструмент вернул ошибку")


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


class ChatSummary(BaseModel):
    """Чат без сообщений — то, что возвращается при создании и в списке."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Идентификатор чата, используется во всех дальнейших запросах")
    title: str = Field(description="Заголовок чата (первое сообщение пользователя либо «Новый чат»)")
    system_prompt: str | None = Field(
        default=None,
        description="Дополнительный системный промпт, заданный при создании чата (дописывается к базовому)",
    )
    redirect_line: str | None = Field(
        default=None,
        description="Линия поддержки, на которую переведён чат (`L1`/`L2`/`L3`). `null`, пока не переведён",
    )
    redirect_reason: str | None = Field(
        default=None, description="Пояснение от агента для оператора поддержки"
    )
    closed_at: str | None = Field(
        default=None,
        description="Время перевода на линию поддержки. Если не `null`, чат закрыт и писать в него нельзя",
    )
    created_at: str = Field(description="Время создания, ISO 8601")
    updated_at: str = Field(description="Время последнего изменения, ISO 8601")


class ChatOut(ChatSummary):
    """Полное содержимое чата: метаданные плюс вся переписка по порядку."""

    messages: list[MessageOut] = Field(
        default_factory=list, description="Сообщения в хронологическом порядке"
    )


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
        description=(
            "Агент перевёл обращение на линию поддержки; чат закрыт, дальнейшие сообщения "
            "отклоняются с 409"
        ),
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
        "к базовому системному промпту агента, не заменяя его."
    ),
    response_description="Созданный чат",
    responses={500: {"model": ErrorOut, "description": "Ошибка хранилища"}},
)
async def create_chat(payload: Annotated[ChatIn | None, Body()] = None) -> ChatSummary:
    return _summary(chat_service.create_chat(payload.system_prompt if payload else None))


@router.get(
    "/chat",
    response_model=list[ChatSummary],
    summary="Список чатов",
    description="Возвращает чаты, свежие сверху. Без сообщений.",
    response_description="Список чатов",
)
async def list_chats(
    limit: Annotated[
        int,
        Query(ge=1, le=200, description="Сколько чатов вернуть максимум", examples=[50]),
    ] = 50,
) -> list[ChatSummary]:
    return [_summary(record) for record in chat_service.list_chats()[:limit]]


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
    get_storage().delete_chat(chat_id)


@router.post(
    "/chat/{chat_id}/message",
    response_class=StreamingResponse,
    response_model=None,
    summary="Отправить сообщение агенту (SSE)",
    description=(
        "Записывает сообщение пользователя и стримит ответ агента в формате `text/event-stream`.\n\n"
        "**События стрима:**\n\n"
        + "\n".join(
            f"- `{event.event}` — {event.description}. payload: `{event.data}`"
            for event in STREAM_EVENTS
        )
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
            async for chunk in chat_service.run_turn(chat_id, text):
                yield chunk
        except KeyError:
            yield chat_service.sse("error", {"message": "Чат не найден"})
        except chat_service.ChatClosedError as exc:
            yield chat_service.sse("error", {"message": str(exc)})

    return StreamingResponse(events(), media_type=SSE_MEDIA_TYPE, headers=SSE_HEADERS)


__all__ = [
    "ChatIn",
    "ChatOut",
    "ChatSummary",
    "MessageIn",
    "MessageOut",
    "STREAM_EVENTS",
    "ToolCallOut",
    "router",
]
