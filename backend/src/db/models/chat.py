from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Role(StrEnum):
    USER = "user"
    OPERATOR = "operator"
    ADMIN = "admin"


class ChatStatus(StrEnum):
    AI = "ai"
    WAITING_OPERATOR = "waiting_operator"
    OPERATOR = "operator"
    CLOSED = "closed"


class SenderType(StrEnum):
    USER = "user"
    AI = "ai"
    OPERATOR = "operator"
    SYSTEM = "system"


class CloseReason(StrEnum):
    RESOLVED = "resolved"
    USER_CANCELLED = "user_cancelled"
    MODERATION = "moderation"


def enum_type(enum_class: type[StrEnum]) -> Enum:
    return Enum(
        enum_class,
        values_callable=lambda members: [member.value for member in members],
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
    )


class SupportLine(Base):
    __tablename__ = "support_lines"
    __table_args__ = (CheckConstraint("id BETWEEN 1 AND 3", name="three_lines"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role != 'operator' OR support_line_id IS NOT NULL", name="operator_line_required"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    login: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[Role] = mapped_column(enum_type(Role))
    support_line_id: Mapped[int | None] = mapped_column(ForeignKey("support_lines.id"))


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (
        Index("ix_chats_owner_created", "user_id", "created_at"),
        Index("ix_chats_queue", "status", "support_line_id", "handed_off_at"),
        CheckConstraint(
            "(status = 'closed') = (close_reason IS NOT NULL AND closed_at IS NOT NULL)", name="closure_consistent"
        ),
        CheckConstraint(
            "status != 'operator' OR (operator_id IS NOT NULL AND support_line_id IS NOT NULL)",
            name="assigned_operator_required",
        ),
        CheckConstraint(
            "status != 'waiting_operator' OR (support_line_id IS NOT NULL AND operator_id IS NULL)",
            name="waiting_line_required",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(100), default="Новый чат")
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[ChatStatus] = mapped_column(enum_type(ChatStatus), default=ChatStatus.AI)
    support_line_id: Mapped[int | None] = mapped_column(ForeignKey("support_lines.id"))
    operator_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    next_sequence: Mapped[int] = mapped_column(default=0)
    ai_messages_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    handed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[CloseReason | None] = mapped_column(enum_type(CloseReason))
    moderation_reason: Mapped[str | None] = mapped_column(String(40))


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "sequence", name="uq_messages_chat_sequence"),
        UniqueConstraint("chat_id", "client_message_id", name="uq_messages_chat_client_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid4().hex)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"))
    sequence: Mapped[int]
    sender_type: Mapped[SenderType] = mapped_column(enum_type(SenderType))
    sender_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    sender_name: Mapped[str] = mapped_column(String(100))
    support_line_id: Mapped[int | None] = mapped_column(ForeignKey("support_lines.id"))
    text: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict]] = mapped_column(JSON, default=list)
    tool_calls: Mapped[list[dict]] = mapped_column(JSON, default=list)
    reply_to_message_id: Mapped[str | None] = mapped_column(String(64), index=True)
    client_message_id: Mapped[UUID | None]
    input_hash: Mapped[str | None] = mapped_column(String(64))
    is_redacted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint("chat_id", name="uq_ratings_chat"),
        CheckConstraint("stars BETWEEN 1 AND 5", name="stars_range"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), unique=True, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    stars: Mapped[int]
    comment: Mapped[str | None] = mapped_column(String(2000))
    sender_type: Mapped[SenderType] = mapped_column(enum_type(SenderType), default=SenderType.AI)
    sender_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    sender_name: Mapped[str] = mapped_column(String(100), default="ИИ-помощник")
    support_line_id: Mapped[int | None] = mapped_column(ForeignKey("support_lines.id"))
    chat_title: Mapped[str] = mapped_column(String(200), default="")
    message_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    message_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

