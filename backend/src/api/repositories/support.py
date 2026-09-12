from fastapi import APIRouter

from src.api.repositories.chats import Limit, Offset
from src.api.repositories.dependencies import Chats, CurrentUser
from src.db.models import ChatStatus
from src.schemas.chat import ChatOut, ChatPage

router = APIRouter(prefix="/operator/chats", tags=["operators"])


@router.get("", response_model=ChatPage)
async def operator_chats(
    user: CurrentUser,
    service: Chats,
    status: ChatStatus | None = None,
    topic: str | None = None,
    subtopic: str | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> ChatPage:
    return await service.list_chats(
        user, scope="operator", status=status, topic=topic, subtopic=subtopic, offset=offset, limit=limit
    )


@router.post("/{chat_id}/claim", response_model=ChatOut)
async def claim(chat_id: str, user: CurrentUser, service: Chats) -> ChatOut:
    return await service.claim(chat_id, user)

