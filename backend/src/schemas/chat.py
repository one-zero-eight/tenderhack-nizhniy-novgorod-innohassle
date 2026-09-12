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


class RegisterIn(Schema):
    login: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    password: str = Field(min_length=1, max_length=1024)
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    role: Role = Role.BUYER
    support_line_id: int | None = Field(default=None, ge=1, le=3)


class TokenOut(Schema):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserOut(Schema):
    id: UUID
    login: str
    display_name: str
    role: Role
    support_line_id: int | None = None


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


class RatingIn(Schema):
    stars: int = Field(strict=True, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class RatingOut(RatingIn):
    id: UUID
    chat_id: str
    user_id: UUID
    created_at: datetime
    updated_at: datetime
    sender_type: SenderType | None = None
    sender_id: UUID | None = None
    sender_name: str | None = None
    support_line_id: int | None = None


class ChatOut(Schema):
    id: str
    title: str = "Новый чат"
    user_id: UUID
    status: ChatStatus
    recipient: RecipientOut
    support_line: SupportLineOut | None
    operator: ActorOut | None
    created_at: datetime
    updated_at: datetime
    handed_off_at: datetime | None
    assigned_at: datetime | None
    closed_at: datetime | None
    close_reason: CloseReason | None
    moderation_reason: str | None
    topic: str | None = None
    subtopic: str | None = None
    rating: RatingOut | None = None


class ChatPage(Schema):
    items: list[ChatOut]
    total: int
    offset: int
    limit: int


class MessageIn(Schema):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    client_message_id: UUID


class ChatFileOut(Schema):
    id: str
    chat_id: str
    filename: str
    content_type: str
    kind: str = "image"
    size: int
    is_image: bool
    created_at: datetime | str
    url: str


class MessageOut(Schema):
    id: str
    chat_id: str
    sequence: int
    sender_type: SenderType
    sender_id: UUID | None = None
    sender_name: str
    support_line_id: int | None = None
    text: str
    citations: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    attachments: list[ChatFileOut] = Field(default_factory=list)
    reply_to_message_id: str | None = None
    is_redacted: bool = False
    created_at: datetime



class MessagePage(Schema):
    items: list[MessageOut]
    next_sequence: int
    has_more: bool


class SendResult(Schema):
    chat: ChatOut
    messages: list[MessageOut]


class RequestOperatorIn(Schema):
    support_line_id: int = Field(strict=True, ge=1, le=3)


class CloseIn(Schema):
    reason: Literal["resolved", "user_cancelled"] = "resolved"


class AdminRatingOut(RatingOut):
    sender_type: SenderType
    sender_id: UUID | None = None
    sender_name: str
    support_line_id: int | None = None
    chat_title: str = ""


class RatingPage(Schema):
    items: list[AdminRatingOut]
    total: int
    offset: int
    limit: int
