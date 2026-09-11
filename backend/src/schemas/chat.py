from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from src.db.models import ChatStatus, CloseReason, Role, SenderType


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class LoginIn(Schema):
    login: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    password: str = Field(min_length=1, max_length=1024)


class TokenOut(Schema):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserOut(Schema):
    id: UUID
    login: str
    display_name: str
    role: Role
    support_line_id: int | None


class SupportLineOut(Schema):
    id: int
    name: str
    description: str


class ActorOut(Schema):
    id: UUID
    display_name: str


class RecipientOut(Schema):
    kind: Literal["ai", "support_queue", "operator", "none"]
    display_name: str
    support_line: SupportLineOut | None = None
    operator: ActorOut | None = None


class ChatOut(Schema):
    id: UUID
    user_id: UUID
    status: ChatStatus
    recipient: RecipientOut
    suggested_line: SupportLineOut | None
    support_line: SupportLineOut | None
    operator: ActorOut | None
    handoff_reason: str | None
    ai_pending: bool
    created_at: datetime
    updated_at: datetime
    handed_off_at: datetime | None
    assigned_at: datetime | None
    closed_at: datetime | None
    close_reason: CloseReason | None
    moderation_reason: str | None


class ChatPage(Schema):
    items: list[ChatOut]
    total: int
    offset: int
    limit: int


class MessageIn(Schema):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    client_message_id: UUID


class RatingIn(Schema):
    stars: int = Field(strict=True, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class RatingOut(RatingIn):
    id: UUID
    message_id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime


class MessageOut(Schema):
    id: UUID
    chat_id: UUID
    sequence: int
    sender_type: SenderType
    sender_id: UUID | None
    sender_name: str
    support_line_id: int | None
    text: str
    citations: list[dict]
    reply_to_message_id: UUID | None
    is_redacted: bool
    created_at: datetime
    rating: RatingOut | None = None


class MessagePage(Schema):
    items: list[MessageOut]
    next_sequence: int
    has_more: bool


class SendResult(Schema):
    chat: ChatOut
    messages: list[MessageOut]


class HandoffIn(Schema):
    support_line_id: int | None = Field(default=None, strict=True, ge=1, le=3)


class HandoffOfferOut(Schema):
    chat: ChatOut
    support_lines: list[SupportLineOut]


class CloseIn(Schema):
    reason: Literal["resolved", "user_cancelled"] = "resolved"


class AdminRatingOut(RatingOut):
    chat_id: UUID
    sender_type: SenderType
    sender_id: UUID | None
    sender_name: str
    support_line_id: int | None
    message_text: str


class RatingPage(Schema):
    items: list[AdminRatingOut]
    total: int
    offset: int
    limit: int
