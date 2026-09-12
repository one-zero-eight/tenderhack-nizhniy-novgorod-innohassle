from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Chat, ChatStatus, Message, Rating, Role, SenderType, SupportLine, User, utcnow
from src.schemas.chat import ActorOut, ChatOut, MessageOut, RatingOut, RecipientOut, SupportLineOut
from src.services.errors import fail


async def load_chat(session: AsyncSession, chat_id: str, *, lock: bool = False) -> Chat:
    query = select(Chat).where(Chat.id == chat_id)
    if lock:
        query = query.with_for_update()
    chat = await session.scalar(query)
    if chat is None:
        fail(404, "CHAT_NOT_FOUND", "Chat not found")
    return chat


def check_read_access(chat: Chat, user: User) -> None:
    if user.role == Role.ADMIN or chat.user_id == user.id:
        return
    if user.role == Role.OPERATOR and chat.operator_id == user.id:
        return
    fail(404, "CHAT_NOT_FOUND", "Chat not found")


def check_owner(chat: Chat, user: User) -> None:
    if user.role != Role.USER or chat.user_id != user.id:
        fail(403, "OWNER_REQUIRED", "Only the chat owner can perform this action")


def check_writer(chat: Chat, user: User) -> None:
    check_read_access(chat, user)
    if user.role == Role.USER and chat.user_id == user.id:
        return
    if user.role == Role.OPERATOR and chat.operator_id == user.id:
        return
    fail(403, "CHAT_WRITE_FORBIDDEN", "Only the owner or assigned operator can write to this chat")


def append_message(
    session: AsyncSession,
    chat: Chat,
    text: str,
    *,
    sender_type: SenderType = SenderType.SYSTEM,
    sender: User | None = None,
    client_message_id: UUID | None = None,
    input_hash: str | None = None,
    reply_to: str | None = None,
    is_redacted: bool = False,
    citations: list[dict] | None = None,
    tool_calls: list[dict] | None = None,
) -> Message:
    """The caller holds the chat row lock, which also orders committed message sequences."""
    chat.next_sequence += 1
    chat.updated_at = utcnow()
    name = sender.display_name if sender else ("ИИ-помощник" if sender_type == SenderType.AI else "Система")
    message = Message(
        id=uuid4().hex,
        chat_id=chat.id,
        sequence=chat.next_sequence,
        text=text,
        sender_type=sender_type,
        sender_id=sender.id if sender else None,
        sender_name=name,
        support_line_id=chat.support_line_id if sender_type == SenderType.OPERATOR else None,
        client_message_id=client_message_id,
        input_hash=input_hash,
        reply_to_message_id=reply_to,
        is_redacted=is_redacted,
        citations=citations or [],
        tool_calls=tool_calls or [],
        created_at=utcnow(),
    )
    session.add(message)
    return message


async def support_lines(session: AsyncSession) -> list[SupportLineOut]:
    rows = await session.scalars(select(SupportLine).order_by(SupportLine.id))
    return [SupportLineOut.model_validate(row) for row in rows]


_UNSET = object()


async def chat_view(session: AsyncSession, chat: Chat, rating: Rating | None | object = _UNSET) -> ChatOut:
    line = await session.get(SupportLine, chat.support_line_id) if chat.support_line_id else None
    operator = await session.get(User, chat.operator_id) if chat.operator_id else None
    line_out = SupportLineOut.model_validate(line) if line else None
    operator_out = ActorOut.model_validate(operator) if operator else None
    if chat.status == ChatStatus.CLOSED:
        recipient = RecipientOut(kind="none", display_name="Обращение закрыто")
    elif chat.status == ChatStatus.WAITING_OPERATOR:
        recipient = RecipientOut(kind="support_queue", display_name=f"Ожидание: {line.name if line else ''}", support_line=line_out)
    elif chat.status == ChatStatus.OPERATOR:
        recipient = RecipientOut(
            kind="operator", display_name=operator.display_name if operator else "", support_line=line_out, operator=operator_out
        )
    else:
        recipient = RecipientOut(kind="ai", display_name="ИИ-помощник")

    if rating is _UNSET:
        rating_obj = await session.scalar(select(Rating).where(Rating.chat_id == chat.id))
    else:
        rating_obj = rating
    rating_out = RatingOut.model_validate(rating_obj) if rating_obj else None

    return ChatOut(
        id=chat.id,
        title=chat.title,
        user_id=chat.user_id,
        status=chat.status,
        recipient=recipient,
        support_line=line_out,
        operator=operator_out,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        handed_off_at=chat.handed_off_at,
        assigned_at=chat.assigned_at,
        closed_at=chat.closed_at,
        close_reason=chat.close_reason,
        moderation_reason=chat.moderation_reason,
        rating=rating_out,
    )


async def chat_views(session: AsyncSession, chats: list[Chat]) -> list[ChatOut]:
    if not chats:
        return []
    ratings = list(await session.scalars(select(Rating).where(Rating.chat_id.in_([c.id for c in chats]))))
    by_chat = {r.chat_id: r for r in ratings}
    return [await chat_view(session, c, rating=by_chat.get(c.id)) for c in chats]


async def message_views(session: AsyncSession, messages: list[Message]) -> list[MessageOut]:
    if not messages:
        return []
    return [MessageOut.model_validate(message) for message in messages]


async def submission_messages(session: AsyncSession, message: Message) -> list[MessageOut]:
    rows = await session.scalars(
        select(Message)
        .where(
            Message.chat_id == message.chat_id,
            or_(Message.id == message.id, Message.reply_to_message_id == message.id),
        )
        .order_by(Message.sequence)
    )
    return await message_views(session, list(rows))


async def latest_question(session: AsyncSession, chat_id: str) -> Message | None:
    return await session.scalar(
        select(Message)
        .where(
            Message.chat_id == chat_id,
            Message.sender_type == SenderType.USER,
            Message.is_redacted.is_(False),
        )
        .order_by(Message.sequence.desc())
        .limit(1)
    )

