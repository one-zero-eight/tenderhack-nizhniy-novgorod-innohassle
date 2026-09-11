from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import AwareDatetime

from src.api.repositories.chats import Limit, Offset
from src.api.repositories.dependencies import Admin, Chats, Storage
from src.db.models import ChatStatus, SenderType
from src.schemas.chat import ChatPage, RatingPage
from src.services.ai_client import AIUnavailable
from src.services.errors import fail
from src.services.stats import StatsService

router = APIRouter(prefix="/admin", tags=["admin"])
Since = Annotated[AwareDatetime | None, Query(alias="from")]
Until = Annotated[AwareDatetime | None, Query(alias="to")]
LineId = Annotated[int | None, Query(ge=1, le=3)]


@router.get("/chats", response_model=ChatPage)
async def chats(
    user: Admin,
    service: Chats,
    since: Since = None,
    until: Until = None,
    status: ChatStatus | None = None,
    line_id: LineId = None,
    operator_id: UUID | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> ChatPage:
    if since is not None and until is not None and since >= until:
        fail(422, "INVALID_PERIOD", "The 'from' date must be earlier than 'to'")
    return await service.list_chats(
        user,
        scope="admin",
        status=status,
        line_id=line_id,
        operator_id=operator_id,
        since=since,
        until=until,
        offset=offset,
        limit=limit,
    )


@router.get("/ratings", response_model=RatingPage)
async def ratings(
    user: Admin,
    storage: Storage,
    since: Since = None,
    until: Until = None,
    stars: Annotated[int | None, Query(ge=1, le=5)] = None,
    stars_lte: Annotated[int | None, Query(ge=1, le=5)] = None,
    sender_type: SenderType | None = None,
    line_id: LineId = None,
    operator_id: UUID | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> RatingPage:
    return await StatsService(storage).ratings(
        since=since,
        until=until,
        stars=stars,
        stars_lte=stars_lte,
        sender_type=sender_type,
        line_id=line_id,
        operator_id=operator_id,
        offset=offset,
        limit=limit,
    )


@router.get("/stats")
async def stats(user: Admin, storage: Storage, since: Since = None, until: Until = None) -> dict:
    return await StatsService(storage).summary(since, until)


@router.get("/ai-health")
async def ai_health(user: Admin, request: Request) -> dict:
    try:
        return await request.app.state.ai.health()
    except AIUnavailable:
        fail(503, "AI_UNAVAILABLE", "The AI service is not fully ready")
