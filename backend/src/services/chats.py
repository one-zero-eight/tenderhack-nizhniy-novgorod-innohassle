import asyncio
import hashlib
import json
import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Chat, ChatStatus, CloseReason, Message, Rating, SenderType, SupportLine, User, utcnow
from src.db.repositories.chats import (
    append_message,
    chat_view,
    chat_views,
    check_owner,
    check_read_access,
    check_writer,
    load_chat,
    submission_messages,
)
from src.db.storage import AbstractSQLAlchemyStorage
from src.schemas.chat import (
    ChatFileOut,
    ChatOut,
    ChatPage,
    MessageIn,
    MessageOut,
    MessagePage,
    RatingIn,
    RatingOut,
    SendResult,
)
from src.services.ai_client import AIClient, AIUnavailable
from src.services.errors import fail
from src.services.moderation import ModerationUnavailable, Moderator

logger = logging.getLogger(__name__)


def invalidate_pending(chat: Chat) -> None:
    chat.updated_at = utcnow()


def close_chat(session: AsyncSession, chat: Chat, reason: CloseReason, *, reply_to: str | None = None) -> None:
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


def _extract_citations(tools: list[dict]) -> list[dict]:
    citations = []
    for tool in tools:
        if tool.get("name") == "open":
            args = tool.get("kwargs") or tool.get("arguments") or {}
            if isinstance(args, dict):
                manual = args.get("manual")
                section_id = args.get("section_id")
                if manual and section_id:
                    citations.append({"manual": str(manual), "section_id": str(section_id)})
    return citations


def _sync_ml_metadata(chat: Chat, ml_data: dict) -> None:
    new_title = ml_data.get("title")
    if chat.title == "Новый чат" and new_title and new_title != "Новый чат":
        chat.title = new_title
    if ml_data.get("topic") is not None:
        chat.topic = ml_data.get("topic")
    if ml_data.get("subtopic") is not None:
        chat.subtopic = ml_data.get("subtopic")
    if ml_data.get("avg_turn_seconds") is not None:
        chat.avg_turn_seconds = ml_data.get("avg_turn_seconds")
    elif "messages" in ml_data:
        durations = [
            m["duration_ms"]
            for m in ml_data["messages"]
            if m.get("role") == "assistant" and m.get("duration_ms") is not None
        ]
        if durations:
            chat.avg_turn_seconds = round(sum(durations) / (len(durations) * 1000), 2)


class ChatService:
    # Client submission cache for idempotency: (chat_id, client_message_id) -> SendResult
    _submissions: dict[tuple[str, UUID], SendResult] = {}
    _client_digests: dict[tuple[str, UUID], str] = {}
    _submission_locks: dict[tuple[str, UUID], asyncio.Lock] = {}

    def __init__(self, storage: AbstractSQLAlchemyStorage, ai: AIClient, moderator: Moderator):
        self.storage = storage
        self.ai = ai
        self.moderator = moderator

    @classmethod
    def _get_submission_lock(cls, key: tuple[str, UUID]) -> asyncio.Lock:
        lock = cls._submission_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            cls._submission_locks[key] = lock
        return lock

    async def create(self, user: User) -> ChatOut:
        if not user.is_customer:
            fail(403, "USER_REQUIRED", "Only users can open chats")
        ml_chat_id, title = await self.ai.create_chat()
        async with self.storage.create_session() as session, session.begin():
            chat = Chat(id=ml_chat_id, title=title, user_id=user.id)
            session.add(chat)
            await session.flush()
            return await chat_view(session, chat, user=user)

    async def get(self, chat_id: str, user: User) -> ChatOut:
        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_read_access(chat, user)
            # Sync title from ML service if it was updated from default
            if (
                chat.title == "Новый чат"
                or chat.topic is None
                or chat.subtopic is None
                or chat.avg_turn_seconds is None
            ):
                try:
                    ml_data = await self.ai.get_chat(chat_id)
                    _sync_ml_metadata(chat, ml_data)
                except Exception:
                    pass
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
        topic: str | None = None,
        subtopic: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> ChatPage:
        filters = []
        if scope == "owner":
            filters.append(Chat.user_id == user.id)
        elif scope in ("operator", "support"):
            if not user.is_support:
                fail(403, "OPERATOR_REQUIRED", "Operator access required")
            filters.append(
                or_(
                    (Chat.status == ChatStatus.WAITING_OPERATOR) & (Chat.support_line_id == user.support_line_id),
                    Chat.operator_id == user.id,
                )
            )
        elif scope != "admin" or not user.is_admin:
            fail(403, "ADMIN_REQUIRED", "Admin access required")
        if status is not None:
            filters.append(Chat.status == status)
        if line_id is not None:
            filters.append(Chat.support_line_id == line_id)
        if operator_id is not None:
            filters.append(Chat.operator_id == operator_id)
        if user_id is not None:
            filters.append(Chat.user_id == user_id)
        if topic is not None:
            filters.append(Chat.topic == topic)
        if subtopic is not None:
            filters.append(Chat.subtopic == subtopic)
        if since is not None:
            filters.append(Chat.created_at >= since)
        if until is not None:
            filters.append(Chat.created_at < until)
        order = (
            (Chat.handed_off_at.asc().nulls_last(), Chat.id)
            if scope in ("operator", "support")
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
            return ChatPage(items=await chat_views(session, rows), total=total, offset=offset, limit=limit)

    async def messages(self, chat_id: str, user: User, after_sequence: int = 0, limit: int = 50) -> MessagePage:
        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_read_access(chat, user)

            # 1. Load AI messages from ML service
            ai_messages: list[MessageOut] = []
            try:
                ml_data = await self.ai.get_chat(chat_id)
                _sync_ml_metadata(chat, ml_data)
                for idx, m in enumerate(ml_data.get("messages", [])):
                    role = m.get("role", "user")
                    tools = m.get("tools", [])
                    sender_type = SenderType.USER if role == "user" else SenderType.AI
                    name = user.display_name if sender_type == SenderType.USER else "ИИ-помощник"
                    sender_id = user.id if sender_type == SenderType.USER else None
                    raw_att = m.get("attachments", [])
                    attachments = [ChatFileOut.model_validate(a) for a in raw_att] if isinstance(raw_att, list) else []
                    ai_messages.append(
                        MessageOut(
                            id=m["id"],
                            chat_id=chat_id,
                            sequence=idx + 1,
                            sender_type=sender_type,
                            sender_id=sender_id,
                            sender_name=name,
                            text=m.get("content", ""),
                            citations=_extract_citations(tools),
                            tool_calls=tools,
                            attachments=attachments,
                            duration_ms=m.get("duration_ms"),
                            is_redacted=False,
                            created_at=chat.created_at,
                        )
                    )
            except Exception:
                pass

            # 2. Load operator / system messages from Postgres
            pg_messages = list(
                await session.scalars(select(Message).where(Message.chat_id == chat_id).order_by(Message.sequence))
            )

            # Assign sequences to PG messages so they cleanly follow AI messages
            offset_seq = len(ai_messages)
            pg_views = []
            for pm in pg_messages:
                view = MessageOut.model_validate(pm)
                view.sequence = offset_seq + pm.sequence
                pg_views.append(view)

            all_messages = ai_messages + pg_views

            # 3. Filter by after_sequence and paginate
            filtered = [m for m in all_messages if m.sequence > after_sequence]
            selected = filtered[:limit]
            return MessagePage(
                items=selected,
                next_sequence=selected[-1].sequence if selected else after_sequence,
                has_more=len(filtered) > limit,
            )

    async def send_stream(self, chat_id: str, user: User, payload: MessageIn):
        """Streams SSE events directly to client from ML service, updating backend state as needed."""
        digest = hashlib.sha256(payload.text.encode()).hexdigest()
        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_writer(chat, user)
            if chat.status == ChatStatus.CLOSED:
                fail(409, "CHAT_CLOSED", "This chat is closed")

        blocked = False
        if user.is_customer:
            try:
                blocked = await self.moderator.is_blocked(payload.text)
            except ModerationUnavailable:
                fail(503, "MODERATION_UNAVAILABLE", "Message not delivered. Please retry moderation later")

        if blocked:
            async with self.storage.create_session() as session, session.begin():
                chat = await load_chat(session, chat_id, lock=True)
                msg = append_message(
                    session,
                    chat,
                    "[Сообщение удалено из-за нецензурной лексики]",
                    sender_type=SenderType.USER,
                    sender=user,
                    client_message_id=payload.client_message_id,
                    input_hash=digest,
                    is_redacted=True,
                )
                close_chat(session, chat, CloseReason.MODERATION, reply_to=msg.id)
            err_data = json.dumps({"message": "Message blocked by moderation"}, ensure_ascii=False)
            yield f"event: error\ndata: {err_data}\n\n"
            done_data = json.dumps(
                {"message_id": "blocked", "content": "[Сообщение удалено из-за нецензурной лексики]"},
                ensure_ascii=False,
            )
            yield f"event: done\ndata: {done_data}\n\n"
            return

        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            if chat.status == ChatStatus.CLOSED:
                fail(409, "CHAT_CLOSED", "This chat is closed")
            if chat.status != ChatStatus.AI:
                # Operator chat mode
                msg = append_message(
                    session,
                    chat,
                    payload.text,
                    sender_type=SenderType.USER if user.is_customer else SenderType.OPERATOR,
                    sender=user,
                    client_message_id=payload.client_message_id,
                    input_hash=digest,
                )
                start_data = json.dumps({"message_id": msg.id})
                yield f"event: start\ndata: {start_data}\n\n"
                done_data = json.dumps({"message_id": msg.id, "content": msg.text})
                yield f"event: done\ndata: {done_data}\n\n"
                return

        # AI mode: stream from ML service
        async for event, data in self.ai.stream_message(chat_id, payload.text):
            if event == "redirect":
                raw_line = str(data.get("line", "1")).upper().lstrip("L")
                try:
                    line_id = int(raw_line)
                except ValueError:
                    line_id = 1
                reason = data.get("reason")
                async with self.storage.create_session() as session, session.begin():
                    chat = await load_chat(session, chat_id, lock=True)
                    line = await session.get(SupportLine, line_id) or await session.get(SupportLine, 1)
                    chat.status = ChatStatus.WAITING_OPERATOR
                    chat.support_line_id = line.id if line else 1
                    chat.handed_off_at = utcnow()
                    chat.updated_at = utcnow()
                    reason_str = f"причина: {reason}" if reason else "по рекомендации ИИ"
                    line_name = line.name if line else f"Линия {line_id}"
                    append_message(
                        session,
                        chat,
                        f"Обращение автоматически перенаправлено в «{line_name}» ({reason_str}). Ожидайте подключения оператора.",
                        sender_type=SenderType.SYSTEM,
                    )
            elif event == "done":
                async with self.storage.create_session() as session, session.begin():
                    chat = await load_chat(session, chat_id, lock=True)
                    chat.ai_messages_count += 1
                    chat.updated_at = utcnow()
                    try:
                        ml_data = await self.ai.get_chat(chat_id)
                        _sync_ml_metadata(chat, ml_data)
                    except Exception:
                        pass
            raw_data = json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else str(data)
            yield f"event: {event}\ndata: {raw_data}\n\n"

    async def send(self, chat_id: str, user: User, payload: MessageIn) -> SendResult:
        """JSON fallback for non-SSE requests."""
        cache_key = (chat_id, payload.client_message_id)
        digest = hashlib.sha256(payload.text.encode()).hexdigest()

        lock = self._get_submission_lock(cache_key)
        async with lock:
            if cache_key in self._submissions:
                if self._client_digests.get(cache_key) != digest:
                    fail(409, "MESSAGE_ID_REUSED", "This client_message_id was already used for a different message")
                return self._submissions[cache_key]

            async with self.storage.create_session() as session, session.begin():
                chat = await load_chat(session, chat_id, lock=True)
                check_writer(chat, user)
                if chat.status == ChatStatus.CLOSED:
                    fail(409, "CHAT_CLOSED", "This chat is closed")

            blocked = False
            if user.is_customer:
                try:
                    blocked = await self.moderator.is_blocked(payload.text)
                except ModerationUnavailable:
                    fail(503, "MODERATION_UNAVAILABLE", "Message not delivered. Please retry moderation later")

            if blocked:
                async with self.storage.create_session() as session, session.begin():
                    chat = await load_chat(session, chat_id, lock=True)
                    msg = append_message(
                        session,
                        chat,
                        "[Сообщение удалено из-за нецензурной лексики]",
                        sender_type=SenderType.USER,
                        sender=user,
                        client_message_id=payload.client_message_id,
                        input_hash=digest,
                        is_redacted=True,
                    )
                    close_chat(session, chat, CloseReason.MODERATION, reply_to=msg.id)
                    res = SendResult(
                        chat=await chat_view(session, chat),
                        messages=await submission_messages(session, msg),
                    )
                    self._submissions[cache_key] = res
                    self._client_digests[cache_key] = digest
                    return res

            async with self.storage.create_session() as session, session.begin():
                chat = await load_chat(session, chat_id, lock=True)
                if chat.status == ChatStatus.CLOSED:
                    fail(409, "CHAT_CLOSED", "This chat is closed")
                if chat.status != ChatStatus.AI:
                    # Operator mode
                    msg = append_message(
                        session,
                        chat,
                        payload.text,
                        sender_type=SenderType.USER if user.is_customer else SenderType.OPERATOR,
                        sender=user,
                        client_message_id=payload.client_message_id,
                        input_hash=digest,
                    )
                    res = SendResult(
                        chat=await chat_view(session, chat),
                        messages=await submission_messages(session, msg),
                    )
                    self._submissions[cache_key] = res
                    self._client_digests[cache_key] = digest
                    return res

            # AI Mode
            answer = None
            try:
                answer = await self.ai.send_message(chat_id, payload.text)
            except AIUnavailable as exc:
                logger.warning("AI service unavailable for chat %s (user %s): %s", chat_id, user.id, exc)
                answer = None

            async with self.storage.create_session() as session, session.begin():
                chat = await load_chat(session, chat_id, lock=True)
                if chat.status == ChatStatus.CLOSED:
                    fail(409, "CHAT_CLOSED", "This chat is closed")
                if answer is not None:
                    chat.ai_messages_count += 1
                    chat.updated_at = utcnow()
                    user_msg_id = f"user-{payload.client_message_id.hex[:12]}"
                    try:
                        ml_data = await self.ai.get_chat(chat_id)
                        _sync_ml_metadata(chat, ml_data)
                        msgs = ml_data.get("messages", [])
                        if len(msgs) >= 2:
                            user_msg_id = msgs[-2]["id"]
                    except Exception:
                        pass

                    user_att_raw = msgs[-2].get("attachments", []) if len(msgs) >= 2 else []
                    user_attachments = (
                        [ChatFileOut.model_validate(a) for a in user_att_raw] if isinstance(user_att_raw, list) else []
                    )
                    user_msg = MessageOut(
                        id=user_msg_id,
                        chat_id=chat_id,
                        sequence=1,
                        sender_type=SenderType.USER,
                        sender_id=user.id,
                        sender_name=user.display_name,
                        text=payload.text,
                        attachments=user_attachments,
                        is_redacted=False,
                        created_at=utcnow(),
                    )

                    if answer.redirect_line:
                        line = await session.get(SupportLine, answer.redirect_line) or await session.get(SupportLine, 1)
                        chat.status = ChatStatus.WAITING_OPERATOR
                        chat.support_line_id = line.id if line else 1
                        chat.handed_off_at = utcnow()
                        chat.updated_at = utcnow()
                        sys_msg = append_message(
                            session,
                            chat,
                            f"Обращение автоматически перенаправлено в «{line.name if line else f'Линия {answer.redirect_line}'}» "
                            f"({f'причина: {answer.redirect_reason}' if answer.redirect_reason else 'по рекомендации ИИ'}). Ожидайте подключения оператора.",
                            sender_type=SenderType.SYSTEM,
                        )
                        sys_view = MessageOut.model_validate(sys_msg)
                        ai_msg = MessageOut(
                            id=answer.message_id,
                            chat_id=chat_id,
                            sequence=2,
                            sender_type=SenderType.AI,
                            sender_id=None,
                            sender_name="ИИ-помощник",
                            text=answer.content,
                            citations=answer.citations,
                            tool_calls=answer.tool_calls,
                            duration_ms=answer.duration_ms,
                            is_redacted=False,
                            created_at=utcnow(),
                        )
                        messages = [user_msg, ai_msg, sys_view] if answer.content.strip() else [user_msg, sys_view]
                    else:
                        ai_msg = MessageOut(
                            id=answer.message_id,
                            chat_id=chat_id,
                            sequence=2,
                            sender_type=SenderType.AI,
                            sender_id=None,
                            sender_name="ИИ-помощник",
                            text=answer.content,
                            citations=answer.citations,
                            tool_calls=answer.tool_calls,
                            duration_ms=answer.duration_ms,
                            is_redacted=False,
                            created_at=utcnow(),
                        )
                        messages = [user_msg, ai_msg]
                else:
                    # Outage: append fallback system notice to Postgres
                    sys_msg = append_message(
                        session,
                        chat,
                        "ИИ-помощник временно недоступен. Вы можете перенаправить запрос оператору.",
                        sender_type=SenderType.SYSTEM,
                    )
                    user_msg = MessageOut(
                        id=f"user-{payload.client_message_id.hex[:12]}",
                        chat_id=chat_id,
                        sequence=1,
                        sender_type=SenderType.USER,
                        sender_id=user.id,
                        sender_name=user.display_name,
                        text=payload.text,
                        is_redacted=False,
                        created_at=utcnow(),
                    )
                    sys_view = MessageOut.model_validate(sys_msg)
                    messages = [user_msg, sys_view]

                res = SendResult(chat=await chat_view(session, chat), messages=messages)
                self._submissions[cache_key] = res
                self._client_digests[cache_key] = digest
                return res

    async def request_operator(self, chat_id: str, user: User, line_id: int) -> ChatOut:
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

    async def claim(self, chat_id: str, user: User) -> ChatOut:
        if not user.is_support:
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

    async def close(self, chat_id: str, user: User, reason: str) -> ChatOut:
        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_writer(chat, user)
            if user.is_support and reason != "resolved":
                fail(403, "INVALID_CLOSE_REASON", "Operators can close a chat as resolved")
            if chat.status != ChatStatus.CLOSED:
                close_chat(session, chat, CloseReason(reason))
            return await chat_view(session, chat)

    async def rate(self, chat_id: str, user: User, payload: RatingIn) -> RatingOut:
        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_read_access(chat, user)
            check_owner(chat, user)

            if chat.operator_id is not None:
                operator = await session.get(User, chat.operator_id)
                sender_type = SenderType.OPERATOR
                sender_id = chat.operator_id
                sender_name = operator.display_name if operator else "Оператор"
                support_line_id = chat.support_line_id
            else:
                sender_type = SenderType.AI
                sender_id = None
                sender_name = "ИИ-помощник"
                support_line_id = chat.support_line_id

            rating = await session.scalar(select(Rating).where(Rating.chat_id == chat.id))
            if rating is None:
                rating = Rating(
                    chat_id=chat.id,
                    user_id=user.id,
                    stars=payload.stars,
                    comment=payload.comment,
                    sender_type=sender_type,
                    sender_id=sender_id,
                    sender_name=sender_name,
                    support_line_id=support_line_id,
                    chat_title=chat.title,
                )
                session.add(rating)
            else:
                rating.stars = payload.stars
                rating.comment = payload.comment
                rating.sender_type = sender_type
                rating.sender_id = sender_id
                rating.sender_name = sender_name
                rating.support_line_id = support_line_id
                rating.chat_title = chat.title
                rating.updated_at = utcnow()
            await session.flush()
            return RatingOut.model_validate(rating)

    async def upload_file(
        self, chat_id: str, user: User, filename: str, content: bytes, content_type: str | None = None
    ) -> ChatFileOut:
        if not content:
            fail(400, "INVALID_FILE", "File cannot be empty")
        if len(content) > 10 * 1024 * 1024:
            fail(400, "FILE_TOO_LARGE", "File size exceeds 10 MB limit")

        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_writer(chat, user)
            if chat.status == ChatStatus.CLOSED:
                fail(409, "CHAT_CLOSED", "This chat is closed")

        try:
            file_data = await self.ai.upload_file(chat_id, filename, content, content_type)
            return ChatFileOut.model_validate(file_data)
        except KeyError:
            fail(404, "CHAT_NOT_FOUND", "Chat not found")
        except ValueError as exc:
            fail(400, "INVALID_FILE", str(exc))
        except AIUnavailable:
            fail(503, "AI_UNAVAILABLE", "AI service is unavailable")

    async def list_files(self, chat_id: str, user: User) -> list[ChatFileOut]:
        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_read_access(chat, user)

        try:
            files_data = await self.ai.list_files(chat_id)
            return [ChatFileOut.model_validate(f) for f in files_data]
        except KeyError:
            fail(404, "CHAT_NOT_FOUND", "Chat not found")
        except AIUnavailable:
            fail(503, "AI_UNAVAILABLE", "AI service is unavailable")

    async def get_file(self, chat_id: str, file_id: str, user: User) -> ChatFileOut:
        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_read_access(chat, user)

        try:
            file_data = await self.ai.get_file(chat_id, file_id)
            return ChatFileOut.model_validate(file_data)
        except KeyError:
            fail(404, "FILE_NOT_FOUND", "File not found")
        except AIUnavailable:
            fail(503, "AI_UNAVAILABLE", "AI service is unavailable")

    async def delete_file(self, chat_id: str, file_id: str, user: User) -> None:
        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_writer(chat, user)
            if chat.status == ChatStatus.CLOSED:
                fail(409, "CHAT_CLOSED", "This chat is closed")

        try:
            await self.ai.delete_file(chat_id, file_id)
        except KeyError:
            fail(404, "FILE_NOT_FOUND", "File not found")
        except AIUnavailable:
            fail(503, "AI_UNAVAILABLE", "AI service is unavailable")

    async def get_file_content(self, chat_id: str, file_id: str, user: User) -> tuple[bytes, str, str | None]:
        async with self.storage.create_session() as session, session.begin():
            chat = await load_chat(session, chat_id, lock=True)
            check_read_access(chat, user)

        try:
            return await self.ai.get_file_content(chat_id, file_id)
        except KeyError:
            fail(404, "FILE_NOT_FOUND", "File not found")
        except AIUnavailable:
            fail(503, "AI_UNAVAILABLE", "AI service is unavailable")
