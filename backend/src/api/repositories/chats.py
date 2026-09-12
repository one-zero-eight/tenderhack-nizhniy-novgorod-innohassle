from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from src.api.repositories.dependencies import Chats, CurrentUser, Storage
from src.db.models import ChatStatus
from src.db.repositories.chats import support_lines
from src.schemas.chat import (
    ChatOut,
    ChatPage,
    CloseIn,
    MessageIn,
    MessagePage,
    RatingIn,
    RatingOut,
    RequestOperatorIn,
    SendResult,
    SupportLineOut,
)

router = APIRouter(tags=["chats"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]

SSE_MEDIA_TYPE = "text/event-stream"
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.get("/support-lines", response_model=list[SupportLineOut])
async def list_support_lines(user: CurrentUser, storage: Storage) -> list[SupportLineOut]:
    async with storage.create_session() as session:
        return await support_lines(session)


@router.post("/chats", response_model=ChatOut, status_code=201)
async def create_chat(user: CurrentUser, service: Chats) -> ChatOut:
    return await service.create(user)


@router.get("/chats", response_model=ChatPage)
async def list_chats(
    user: CurrentUser, service: Chats, status: ChatStatus | None = None, offset: Offset = 0, limit: Limit = 50
) -> ChatPage:
    return await service.list_chats(user, status=status, offset=offset, limit=limit)


@router.get("/chats/{chat_id}", response_model=ChatOut)
async def get_chat(chat_id: str, user: CurrentUser, service: Chats) -> ChatOut:
    return await service.get(chat_id, user)


@router.get("/chats/{chat_id}/messages", response_model=MessagePage)
async def get_messages(
    chat_id: str, user: CurrentUser, service: Chats, after_sequence: Annotated[int, Query(ge=0)] = 0, limit: Limit = 50
) -> MessagePage:
    return await service.messages(chat_id, user, after_sequence, limit)


@router.post("/chats/{chat_id}/messages", response_model=SendResult)
async def send_message(
    chat_id: str, payload: MessageIn, user: CurrentUser, service: Chats, request: Request
):
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        return StreamingResponse(
            service.send_stream(chat_id, user, payload),
            media_type=SSE_MEDIA_TYPE,
            headers=SSE_HEADERS,
        )
    return await service.send(chat_id, user, payload)


@router.post("/chats/{chat_id}/message")
@router.post("/chats/{chat_id}/stream")
async def stream_message(
    chat_id: str, payload: MessageIn, user: CurrentUser, service: Chats
) -> StreamingResponse:
    return StreamingResponse(
        service.send_stream(chat_id, user, payload),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )


@router.post("/chats/{chat_id}/request-operator", response_model=ChatOut)
async def request_operator(
    chat_id: str, payload: RequestOperatorIn, user: CurrentUser, service: Chats
) -> ChatOut:
    return await service.request_operator(chat_id, user, payload.support_line_id)


@router.post("/chats/{chat_id}/close", response_model=ChatOut)
async def close(chat_id: str, payload: CloseIn, user: CurrentUser, service: Chats) -> ChatOut:
    return await service.close(chat_id, user, payload.reason)


@router.put("/chats/{chat_id}/rating", response_model=RatingOut, tags=["ratings"])
async def rate_chat(chat_id: str, payload: RatingIn, user: CurrentUser, service: Chats) -> RatingOut:
    return await service.rate(chat_id, user, payload)


@router.put("/messages/{message_id}/rating", response_model=RatingOut, tags=["ratings"])
async def rate(message_id: str, payload: RatingIn, user: CurrentUser, service: Chats) -> RatingOut:
    return await service.rate_message(message_id, user, payload)
