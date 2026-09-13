from typing import Annotated

from fastapi import APIRouter, File, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from src.api.repositories.dependencies import Chats, CurrentUser, Storage
from src.db.models import ChatStatus
from src.db.repositories.chats import support_lines
from src.schemas.chat import (
    ChatFileOut,
    ChatOut,
    ChatPage,
    MessageIn,
    MessagePage,
    RatingIn,
    RatingOut,
    SendResult,
    SupportLineOut,
)

router = APIRouter(tags=["chats"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
RatingQuery = Annotated[int | None, Query(ge=1, le=5)]

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
    user: CurrentUser,
    service: Chats,
    status: ChatStatus | None = None,
    topic: str | None = None,
    subtopic: str | None = None,
    rating_lte: RatingQuery = None,
    rating_gte: RatingQuery = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> ChatPage:
    return await service.list_chats(
        user,
        status=status,
        topic=topic,
        subtopic=subtopic,
        rating_lte=rating_lte,
        rating_gte=rating_gte,
        offset=offset,
        limit=limit,
    )


@router.get("/chats/{chat_id}", response_model=ChatOut)
async def get_chat(chat_id: str, user: CurrentUser, service: Chats) -> ChatOut:
    return await service.get(chat_id, user)


@router.get("/chats/{chat_id}/messages", response_model=MessagePage)
async def get_messages(
    chat_id: str, user: CurrentUser, service: Chats, after_sequence: Annotated[int, Query(ge=0)] = 0, limit: Limit = 50
) -> MessagePage:
    return await service.messages(chat_id, user, after_sequence, limit)


@router.post("/chats/{chat_id}/messages", response_model=SendResult)
async def send_message(chat_id: str, payload: MessageIn, user: CurrentUser, service: Chats, request: Request):
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        return StreamingResponse(
            service.send_stream(chat_id, user, payload),
            media_type=SSE_MEDIA_TYPE,
            headers=SSE_HEADERS,
        )
    return await service.send(chat_id, user, payload)


@router.post("/chats/{chat_id}/stream")
async def stream_message(chat_id: str, payload: MessageIn, user: CurrentUser, service: Chats) -> StreamingResponse:
    return StreamingResponse(
        service.send_stream(chat_id, user, payload),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )


@router.post("/chats/{chat_id}/upload", response_model=ChatFileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    chat_id: str,
    file: Annotated[UploadFile, File(...)],
    user: CurrentUser,
    service: Chats,
) -> ChatFileOut:
    data = await file.read(10 * 1024 * 1024 + 1)
    return await service.upload_file(chat_id, user, file.filename or "file", data, file.content_type)


@router.get("/chats/{chat_id}/files", response_model=list[ChatFileOut])
async def list_files(
    chat_id: str,
    user: CurrentUser,
    service: Chats,
) -> list[ChatFileOut]:
    return await service.list_files(chat_id, user)


@router.get("/chats/{chat_id}/files/{file_id}", response_model=ChatFileOut)
async def get_file(
    chat_id: str,
    file_id: str,
    user: CurrentUser,
    service: Chats,
) -> ChatFileOut:
    return await service.get_file(chat_id, file_id, user)


@router.delete("/chats/{chat_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    chat_id: str,
    file_id: str,
    user: CurrentUser,
    service: Chats,
) -> None:
    await service.delete_file(chat_id, file_id, user)


@router.get("/chats/{chat_id}/files/{file_id}/content")
async def get_file_content(
    chat_id: str,
    file_id: str,
    user: CurrentUser,
    service: Chats,
) -> Response:
    content, content_type, disposition = await service.get_file_content(chat_id, file_id, user)
    headers = {}
    if disposition:
        headers["Content-Disposition"] = disposition
    return Response(content=content, media_type=content_type, headers=headers)


@router.put("/chats/{chat_id}/rating", response_model=RatingOut, tags=["ratings"])
async def rate_chat(chat_id: str, payload: RatingIn, user: CurrentUser, service: Chats) -> RatingOut:
    return await service.rate(chat_id, user, payload)
