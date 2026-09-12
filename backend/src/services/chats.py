import hashlib
import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Chat, ChatStatus, CloseReason, Message, Rating, Role, SenderType, SupportLine, User, utcnow
from src.db.repositories.chats import (
    append_message,
    chat_view,
    check_owner,
    check_read_access,
    check_writer,
    load_chat,
    message_views,
    submission_messages,
)
from src.db.storage import AbstractSQLAlchemyStorage
from src.schemas.chat import (
    ChatOut,
    ChatPage,
    MessageIn,
    MessagePage,
    RatingIn,
    RatingOut,
    SendResult,
)
from src.services.ai_client import AIClient, AIUnavailable
from src.services.errors import fail
from src.services.moderation import ModerationUnavailable, Moderator

logger = logging.getLogger(__name__)

BOT_STATES = (ChatStatus.AI,)


def invalidate_pending(chat: Chat) -> None:
    chat.updated_at = utcnow()


def close_chat(session: AsyncSession, chat: Chat, reason: CloseReason, *, reply_to: UUID | None = None) -> None:
    invalidate_pending(chat)
    chat.status = ChatStatus.CLOSED
    chat.close_reason = reason
    chat.closed_at = utcnow()
    if reason == CloseReason.MODERATION:
        chat.moderation_reason = "profanity"
        text = "Обращение завершено из-за нецензурной лексики. Пожалуйста, соблюдайте правила общения."
    else:
        text = "Обращение закрыто. Вы можете оценить полученные ответы."
    append_message(session, chat, text, reply_to=reply_to)


class ChatService:
    def __init__(self, storage: AbstractSQLAlchemyStorage, ai: AIClient, moderator: Moderator):
        self.storage = storage
        self.ai = ai
        self.moderator = moderator

    async def create(self, user: User) -> ChatOut:
        if user.role != Role.USER:
            fail(403, "USER_REQUIRED", "Only users can open chats")
        async with self.storage.create_session() as session, session.begin():
            chat = Chat(user_id=user.id)
            session.add(chat)
            await session.flush()
            return await chat_view(session, chat)

    async def get(self, chat_id: UUID, user: User) -> ChatOut:
        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_read_access(chat, user)
            return await chat_view(session, chat)

    async def list_chats(
        self,
        user: User,
        *,
        scope: str = "owner",
        offset: int = 0,
        limit: int = 50,
        status: ChatStatus | None = None,
        line_id: int | None = None,
        operator_id: UUID | None = None,
        user_id: UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> ChatPage:
        filters = []
        if scope == "owner":
            filters.append(Chat.user_id == user.id)
        elif scope == "operator":
            if user.role != Role.OPERATOR:
                fail(403, "OPERATOR_REQUIRED", "Operator access required")
            filters.append(
                or_(
                    (Chat.status == ChatStatus.WAITING_OPERATOR) & (Chat.support_line_id == user.support_line_id),
                    Chat.operator_id == user.id,
                )
            )
        elif scope != "admin" or user.role != Role.ADMIN:
            fail(403, "ADMIN_REQUIRED", "Admin access required")
        if status is not None:
            filters.append(Chat.status == status)
        if line_id is not None:
            filters.append(Chat.support_line_id == line_id)
        if operator_id is not None:
            filters.append(Chat.operator_id == operator_id)
        if user_id is not None:
            filters.append(Chat.user_id == user_id)
        if since is not None:
            filters.append(Chat.created_at >= since)
        if until is not None:
            filters.append(Chat.created_at < until)
        order = (
            (Chat.handed_off_at.asc().nulls_last(), Chat.id)
            if scope == "operator"
            else (
                Chat.created_at.desc(),
                Chat.id.desc(),
            )
        )
        async with self.storage.create_session() as session, session.begin():
            total = await session.scalar(select(func.count()).select_from(Chat).where(*filters))
            rows = list(
                await session.scalars(select(Chat).where(*filters).order_by(*order).offset(offset).limit(limit))
            )
            return ChatPage(
                items=[await chat_view(session, row) for row in rows], total=total, offset=offset, limit=limit
            )

    async def messages(self, chat_id: UUID, user: User, after_sequence: int, limit: int) -> MessagePage:
        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_read_access(chat, user)
            rows = list(
                await session.scalars(
                    select(Message)
                    .where(
                        Message.chat_id == chat_id,
                        Message.sequence > after_sequence,
                    )
                    .order_by(Message.sequence)
                    .limit(limit + 1)
                )
            )
            selected = rows[:limit]
            return MessagePage(
                items=await message_views(session, selected),
                next_sequence=selected[-1].sequence if selected else after_sequence,
                has_more=len(rows) > limit,
            )

    async def _existing(
        self, session: AsyncSession, chat: Chat, user: User, payload: MessageIn, digest: str
    ) -> SendResult | None:
        existing = await session.scalar(
            select(Message).where(
                Message.chat_id == chat.id,
                Message.client_message_id == payload.client_message_id,
            )
        )
        if existing is None:
            return None
        if existing.sender_id != user.id or existing.input_hash != digest:
            fail(409, "MESSAGE_ID_REUSED", "This client_message_id was already used for a different message")
        return SendResult(chat=await chat_view(session, chat), messages=await submission_messages(session, existing))

    async def send(self, chat_id: UUID, user: User, payload: MessageIn) -> SendResult:
        digest = hashlib.sha256(payload.text.encode()).hexdigest()
        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_writer(chat, user)
            existing = await self._existing(session, chat, user, payload, digest)
            if existing:
                return existing
            if chat.status == ChatStatus.CLOSED:
                fail(409, "CHAT_CLOSED", "This chat is closed")

        blocked = False
        if user.role == Role.USER:
            try:
                blocked = await self.moderator.is_blocked(payload.text)
            except ModerationUnavailable:
                fail(503, "MODERATION_UNAVAILABLE", "Message not delivered. Please retry moderation later")

        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_writer(chat, user)
            existing = await self._existing(session, chat, user, payload, digest)
            if existing:
                return existing
            if chat.status == ChatStatus.CLOSED:
                fail(409, "CHAT_CLOSED", "This chat was closed while the message was being checked")
            message = append_message(
                session,
                chat,
                "[Сообщение удалено из-за нецензурной лексики]" if blocked else payload.text,
                sender_type=SenderType.USER if user.role == Role.USER else SenderType.OPERATOR,
                sender=user,
                client_message_id=payload.client_message_id,
                input_hash=digest,
                is_redacted=blocked,
            )
            if blocked:
                close_chat(session, chat, CloseReason.MODERATION, reply_to=message.id)
                return SendResult(
                    chat=await chat_view(session, chat), messages=await submission_messages(session, message)
                )

            if user.role != Role.USER or chat.status != ChatStatus.AI:
                return SendResult(
                    chat=await chat_view(session, chat), messages=await submission_messages(session, message)
                )

            message_id = message.id
            ml_chat_id = chat.ml_chat_id

        answer = None
        try:
            if not ml_chat_id:
                ml_chat_id = await self.ai.create_chat()
            answer = await self.ai.send_message(ml_chat_id, payload.text)
        except AIUnavailable as exc:
            logger.warning(
                "AI service unavailable for chat %s (user %s): %s. Falling back to system message.",
                chat_id,
                user.id,
                exc,
            )
            answer = None

        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            if ml_chat_id and chat.ml_chat_id is None:
                chat.ml_chat_id = ml_chat_id

            if chat.status == ChatStatus.AI:
                if answer is not None:
                    if answer.redirect_line:
                        line = await session.get(SupportLine, answer.redirect_line)
                        if line is None:
                            line = await session.get(SupportLine, 1)
                        chat.status = ChatStatus.WAITING_OPERATOR
                        chat.support_line_id = line.id if line else 1
                        chat.handed_off_at = utcnow()
                        chat.updated_at = utcnow()
                        if answer.content.strip():
                            append_message(
                                session,
                                chat,
                                answer.content,
                                sender_type=SenderType.AI,
                                reply_to=message_id,
                                citations=answer.citations,
                                tool_calls=answer.tool_calls,
                            )
                        reason_str = f"причина: {answer.redirect_reason}" if answer.redirect_reason else "по рекомендации ИИ"
                        line_name = line.name if line else f"Линия {answer.redirect_line}"
                        append_message(
                            session,
                            chat,
                            f"Обращение автоматически перенаправлено в «{line_name}» ({reason_str}). Ожидайте подключения оператора.",
                            sender_type=SenderType.SYSTEM,
                        )
                    else:
                        append_message(
                            session,
                            chat,
                            answer.content,
                            sender_type=SenderType.AI,
                            reply_to=message_id,
                            citations=answer.citations,
                            tool_calls=answer.tool_calls,
                        )
                else:
                    append_message(
                        session,
                        chat,
                        "ИИ-помощник временно недоступен. Вы можете перенаправить запрос оператору.",
                        sender_type=SenderType.SYSTEM,
                        reply_to=message_id,
                    )
            message = await session.get(Message, message_id)
            return SendResult(chat=await chat_view(session, chat), messages=await submission_messages(session, message))

    async def request_operator(self, chat_id: UUID, user: User, line_id: int) -> ChatOut:
        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_read_access(chat, user)
            check_owner(chat, user)
            if chat.status == ChatStatus.WAITING_OPERATOR and line_id == chat.support_line_id:
                return await chat_view(session, chat)
            if chat.status not in (ChatStatus.AI, ChatStatus.WAITING_OPERATOR):
                fail(409, "HANDOFF_NOT_AVAILABLE", "The chat is already claimed by an operator or closed")
            line = await session.get(SupportLine, line_id)
            if line is None:
                fail(422, "INVALID_SUPPORT_LINE", "Unknown support line")
            chat.status = ChatStatus.WAITING_OPERATOR
            chat.support_line_id = line_id
            chat.handed_off_at = utcnow()
            chat.updated_at = utcnow()
            append_message(session, chat, f"Обращение передано в «{line.name}». Ожидайте подключения оператора.")
            return await chat_view(session, chat)

    async def claim(self, chat_id: UUID, user: User) -> ChatOut:
        if user.role != Role.OPERATOR:
            fail(403, "OPERATOR_REQUIRED", "Operator access required")
        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            if chat.support_line_id != user.support_line_id:
                fail(403, "WRONG_SUPPORT_LINE", "This chat belongs to another support line")
            if chat.status == ChatStatus.OPERATOR and chat.operator_id == user.id:
                return await chat_view(session, chat)
            if chat.status != ChatStatus.WAITING_OPERATOR:
                fail(409, "CHAT_NOT_WAITING", "This chat has already been claimed or closed")
            invalidate_pending(chat)
            chat.status = ChatStatus.OPERATOR
            chat.operator_id = user.id
            chat.assigned_at = utcnow()
            append_message(session, chat, f"К диалогу подключился оператор {user.display_name}.")
            return await chat_view(session, chat)

    async def close(self, chat_id: UUID, user: User, reason: str) -> ChatOut:
        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_writer(chat, user)
            if user.role == Role.OPERATOR and reason != "resolved":
                fail(403, "INVALID_CLOSE_REASON", "Operators can close a chat as resolved")
            if chat.status != ChatStatus.CLOSED:
                close_chat(session, chat, CloseReason(reason))
            return await chat_view(session, chat)

    async def rate(self, message_id: UUID, user: User, payload: RatingIn) -> RatingOut:
        async with self.storage.create_session() as session, session.begin():
            message = await session.get(Message, message_id)
            if message is None:
                fail(404, "MESSAGE_NOT_FOUND", "Message not found")
            chat = await load_chat(session, message.chat_id, lock=True)
            check_read_access(chat, user)
            check_owner(chat, user)
            if message.sender_type not in (SenderType.AI, SenderType.OPERATOR) or message.is_redacted:
                fail(422, "MESSAGE_NOT_RATEABLE", "Only delivered AI or operator replies can be rated")
            rating = await session.scalar(
                select(Rating).where(Rating.message_id == message_id, Rating.user_id == user.id)
            )
            if rating is None:
                rating = Rating(message_id=message_id, user_id=user.id, **payload.model_dump())
                session.add(rating)
            else:
                rating.stars, rating.comment, rating.updated_at = payload.stars, payload.comment, utcnow()
            await session.flush()
            return RatingOut.model_validate(rating)
