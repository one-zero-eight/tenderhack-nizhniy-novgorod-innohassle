import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from uuid import UUID, uuid4

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
from src.services.profile_entities import build_user_system_prompt, extract_mentions, resolve_profile_entities

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
        system_prompt = build_user_system_prompt(user)
        uname = user.display_name[:64] if user.display_name else user.login[:64]
        ml_chat_id, title = await self.ai.create_chat(system_prompt=system_prompt, username=uname)
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
        rating_lte: int | None = None,
        rating_gte: int | None = None,
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
        rating_filters = []
        if rating_lte is not None:
            rating_filters.append(Rating.stars <= rating_lte)
        if rating_gte is not None:
            rating_filters.append(Rating.stars >= rating_gte)
        if rating_filters:
            filters.append(Chat.id.in_(select(Rating.chat_id).where(*rating_filters)))
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

            ml_data = None
            try:
                ml_data = await self.ai.get_chat(chat_id)
                _sync_ml_metadata(chat, ml_data)
            except Exception:
                pass

            # Load messages from Postgres
            db_messages = list(
                await session.scalars(select(Message).where(Message.chat_id == chat_id).order_by(Message.sequence))
            )

            # Fallback sync from ML service for any messages not present in Postgres
            if ml_data and isinstance(ml_data, dict):
                existing_ids = {m.id for m in db_messages}
                changed = False
                for m in ml_data.get("messages", []):
                    m_id = m.get("id")
                    if m_id and m_id not in existing_ids:
                        role = m.get("role", "user")
                        sender_type = SenderType.USER if role == "user" else SenderType.AI
                        raw_att = m.get("attachments", [])
                        created_at = None
                        if m.get("created_at"):
                            try:
                                created_at = datetime.fromisoformat(m["created_at"])
                            except Exception:
                                pass
                        raw_ent = m.get("entities", [])
                        new_msg = append_message(
                            session,
                            chat,
                            m.get("content", ""),
                            sender_type=sender_type,
                            sender=user if sender_type == SenderType.USER else None,
                            citations=_extract_citations(m.get("tools", [])),
                            tool_calls=m.get("tools", []),
                            attachments=raw_att if isinstance(raw_att, list) else [],
                            entities=raw_ent if isinstance(raw_ent, list) else [],
                            duration_ms=m.get("duration_ms"),
                            message_id=m_id,
                            created_at=created_at or chat.created_at,
                        )
                        db_messages.append(new_msg)
                        existing_ids.add(m_id)
                        changed = True
                if changed:
                    db_messages.sort(key=lambda x: x.sequence)

            all_views = [MessageOut.model_validate(m) for m in db_messages]
            filtered = [m for m in all_views if m.sequence > after_sequence]
            selected = filtered[:limit]
            return MessagePage(
                items=selected,
                next_sequence=selected[-1].sequence if selected else after_sequence,
                has_more=len(filtered) > limit,
            )

    async def send_stream(self, chat_id: str, user: User, payload: MessageIn):
        """Streams SSE events directly to client from ML service, updating backend state as needed."""
        submitted_at = utcnow()
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
                    created_at=submitted_at,
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
                    created_at=submitted_at,
                )
                start_data = json.dumps({"message_id": msg.id})
                yield f"event: start\ndata: {start_data}\n\n"
                done_data = json.dumps({"message_id": msg.id, "content": msg.text})
                yield f"event: done\ndata: {done_data}\n\n"
                return

        # AI mode: stream from ML service
        cleaned_text, mentions = extract_mentions(payload.text)
        resolved_entities = resolve_profile_entities(mentions, user)
        explicit_aliases = {e.alias for e in payload.entities}
        all_entities = list(payload.entities) + [
            e for e in resolved_entities if e.alias not in explicit_aliases
        ]
        entities_dicts = [e.model_dump() for e in all_entities]

        tool_calls: list[dict] = []
        citations: list[dict] = []
        user_persisted = False
        user_db_msg_id: str | None = None

        async for event, data in self.ai.stream_message(
            chat_id, cleaned_text, entities=entities_dicts if entities_dicts else None
        ):
            if event == "tool":
                tool_calls.append(data)
                name = data.get("name", "")
                args = data.get("kwargs") or data.get("arguments") or {}
                if name == "open" and isinstance(args, dict):
                    manual = args.get("manual")
                    section_id = args.get("section_id")
                    if manual and section_id:
                        citations.append({"manual": str(manual), "section_id": str(section_id)})
            elif event == "redirect":
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

                    if not user_persisted:
                        user_att_raw = []
                        user_msg_id = None
                        try:
                            ml_data = await self.ai.get_chat(chat_id)
                            _sync_ml_metadata(chat, ml_data)
                            msgs = ml_data.get("messages", [])
                            if len(msgs) >= 1:
                                user_msg_id = msgs[-1]["id"]
                                user_att_raw = msgs[-1].get("attachments", [])
                        except Exception:
                            pass
                        u_msg = append_message(
                            session,
                            chat,
                            cleaned_text,
                            sender_type=SenderType.USER,
                            sender=user,
                            client_message_id=payload.client_message_id,
                            input_hash=digest,
                            attachments=user_att_raw if isinstance(user_att_raw, list) else [],
                            entities=entities_dicts,
                            message_id=user_msg_id,
                            created_at=submitted_at,
                        )
                        user_persisted = True
                        user_db_msg_id = u_msg.id

                    reason_str = f"причина: {reason}" if reason else "по рекомендации ИИ"
                    line_name = line.name if line else f"Линия {line_id}"
                    append_message(
                        session,
                        chat,
                        f"Обращение автоматически перенаправлено в «{line_name}» ({reason_str}). Ожидайте подключения оператора.",
                        sender_type=SenderType.SYSTEM,
                        reply_to=user_db_msg_id,
                    )
            elif event == "done":
                ai_completed_at = utcnow()
                content = data.get("content") or ""
                ai_msg_id = data.get("message_id") or uuid4().hex
                duration_ms = data.get("duration_ms")

                user_created_at = submitted_at
                ai_created_at = ai_completed_at
                if duration_ms is not None:
                    calc_user_created_at = ai_completed_at - timedelta(milliseconds=duration_ms)
                    if calc_user_created_at < user_created_at or user_created_at >= ai_created_at:
                        user_created_at = calc_user_created_at
                elif user_created_at >= ai_created_at:
                    user_created_at = ai_created_at - timedelta(milliseconds=1)

                async with self.storage.create_session() as session, session.begin():
                    chat = await load_chat(session, chat_id, lock=True)
                    chat.ai_messages_count += 1
                    chat.updated_at = ai_completed_at

                    prev_msg = await session.scalar(
                        select(Message).where(Message.chat_id == chat_id).order_by(Message.sequence.desc()).limit(1)
                    )

                    user_att_raw = []
                    user_msg_id = None
                    try:
                        ml_data = await self.ai.get_chat(chat_id)
                        _sync_ml_metadata(chat, ml_data)
                        msgs = ml_data.get("messages", [])
                        if len(msgs) >= 2:
                            user_msg_id = msgs[-2]["id"]
                            user_att_raw = msgs[-2].get("attachments", [])
                            if msgs[-2].get("created_at"):
                                try:
                                    user_created_at = datetime.fromisoformat(msgs[-2]["created_at"])
                                except Exception:
                                    pass
                            if msgs[-1].get("created_at"):
                                try:
                                    ai_created_at = datetime.fromisoformat(msgs[-1]["created_at"])
                                except Exception:
                                    pass
                        elif len(msgs) == 1:
                            user_msg_id = msgs[-1]["id"]
                            user_att_raw = msgs[-1].get("attachments", [])
                    except Exception:
                        pass

                    if prev_msg and prev_msg.created_at and user_created_at <= prev_msg.created_at:
                        user_created_at = prev_msg.created_at + timedelta(milliseconds=1)
                    if ai_created_at <= user_created_at:
                        ai_created_at = user_created_at + timedelta(milliseconds=max(duration_ms or 1, 1))

                    if not user_persisted:
                        u_msg = append_message(
                            session,
                            chat,
                            cleaned_text,
                            sender_type=SenderType.USER,
                            sender=user,
                            client_message_id=payload.client_message_id,
                            input_hash=digest,
                            attachments=user_att_raw if isinstance(user_att_raw, list) else [],
                            entities=entities_dicts,
                            message_id=user_msg_id,
                            created_at=user_created_at,
                        )
                        user_persisted = True
                        user_db_msg_id = u_msg.id

                    append_message(
                        session,
                        chat,
                        content,
                        sender_type=SenderType.AI,
                        sender=None,
                        reply_to=user_db_msg_id,
                        citations=citations or _extract_citations(tool_calls),
                        tool_calls=tool_calls,
                        duration_ms=duration_ms,
                        message_id=ai_msg_id,
                        created_at=ai_created_at,
                    )

            raw_data = json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else str(data)
            yield f"event: {event}\ndata: {raw_data}\n\n"

    async def send(self, chat_id: str, user: User, payload: MessageIn) -> SendResult:
        """JSON fallback for non-SSE requests."""
        submitted_at = utcnow()
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

                # Check if this client_message_id was already processed in PostgreSQL
                existing_user_msg = await session.scalar(
                    select(Message).where(
                        Message.chat_id == chat_id,
                        Message.client_message_id == payload.client_message_id,
                    )
                )
                if existing_user_msg is not None:
                    if existing_user_msg.input_hash != digest:
                        fail(
                            409, "MESSAGE_ID_REUSED", "This client_message_id was already used for a different message"
                        )
                    res = SendResult(
                        chat=await chat_view(session, chat),
                        messages=await submission_messages(session, existing_user_msg),
                    )
                    self._submissions[cache_key] = res
                    self._client_digests[cache_key] = digest
                    return res

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
                        created_at=submitted_at,
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
                        created_at=submitted_at,
                    )
                    res = SendResult(
                        chat=await chat_view(session, chat),
                        messages=await submission_messages(session, msg),
                    )
                    self._submissions[cache_key] = res
                    self._client_digests[cache_key] = digest
                    return res

            # AI Mode
            cleaned_text, mentions = extract_mentions(payload.text)
            resolved_entities = resolve_profile_entities(mentions, user)
            explicit_aliases = {e.alias for e in payload.entities}
            all_entities = list(payload.entities) + [
                e for e in resolved_entities if e.alias not in explicit_aliases
            ]
            entities_dicts = [e.model_dump() for e in all_entities]

            answer = None
            try:
                answer = await self.ai.send_message(
                    chat_id, cleaned_text, entities=entities_dicts if entities_dicts else None
                )
            except AIUnavailable as exc:
                logger.warning("AI service unavailable for chat %s (user %s): %s", chat_id, user.id, exc)
                answer = None

            async with self.storage.create_session() as session, session.begin():
                chat = await load_chat(session, chat_id, lock=True)
                if chat.status == ChatStatus.CLOSED:
                    fail(409, "CHAT_CLOSED", "This chat is closed")

                if answer is not None:
                    chat.ai_messages_count += 1
                    ai_completed_at = utcnow()
                    chat.updated_at = ai_completed_at

                    user_created_at = submitted_at
                    ai_created_at = ai_completed_at
                    if answer.duration_ms is not None:
                        calc_user_created_at = ai_completed_at - timedelta(milliseconds=answer.duration_ms)
                        if calc_user_created_at < user_created_at or user_created_at >= ai_created_at:
                            user_created_at = calc_user_created_at
                    elif user_created_at >= ai_created_at:
                        user_created_at = ai_created_at - timedelta(milliseconds=1)

                    prev_msg = await session.scalar(
                        select(Message).where(Message.chat_id == chat_id).order_by(Message.sequence.desc()).limit(1)
                    )

                    user_att_raw = []
                    user_msg_id = None
                    try:
                        ml_data = await self.ai.get_chat(chat_id)
                        _sync_ml_metadata(chat, ml_data)
                        msgs = ml_data.get("messages", [])
                        if len(msgs) >= 2:
                            user_msg_id = msgs[-2]["id"]
                            user_att_raw = msgs[-2].get("attachments", [])
                            if msgs[-2].get("created_at"):
                                try:
                                    user_created_at = datetime.fromisoformat(msgs[-2]["created_at"])
                                except Exception:
                                    pass
                            if msgs[-1].get("created_at"):
                                try:
                                    ai_created_at = datetime.fromisoformat(msgs[-1]["created_at"])
                                except Exception:
                                    pass
                        elif len(msgs) == 1:
                            user_msg_id = msgs[-1]["id"]
                            user_att_raw = msgs[-1].get("attachments", [])
                    except Exception:
                        pass

                    if prev_msg and prev_msg.created_at and user_created_at <= prev_msg.created_at:
                        user_created_at = prev_msg.created_at + timedelta(milliseconds=1)
                    if ai_created_at <= user_created_at:
                        ai_created_at = user_created_at + timedelta(milliseconds=max(answer.duration_ms or 1, 1))

                    user_db_msg = append_message(
                        session,
                        chat,
                        cleaned_text,
                        sender_type=SenderType.USER,
                        sender=user,
                        client_message_id=payload.client_message_id,
                        input_hash=digest,
                        attachments=user_att_raw if isinstance(user_att_raw, list) else [],
                        entities=entities_dicts,
                        message_id=user_msg_id,
                        created_at=user_created_at,
                    )

                    if answer.redirect_line:
                        line = await session.get(SupportLine, answer.redirect_line) or await session.get(SupportLine, 1)
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
                                sender=None,
                                reply_to=user_db_msg.id,
                                citations=answer.citations,
                                tool_calls=answer.tool_calls,
                                duration_ms=answer.duration_ms,
                                message_id=answer.message_id,
                                created_at=ai_created_at,
                            )
                        append_message(
                            session,
                            chat,
                            f"Обращение автоматически перенаправлено в «{line.name if line else f'Линия {answer.redirect_line}'}» "
                            f"({f'причина: {answer.redirect_reason}' if answer.redirect_reason else 'по рекомендации ИИ'}). Ожидайте подключения оператора.",
                            sender_type=SenderType.SYSTEM,
                            reply_to=user_db_msg.id,
                            created_at=ai_created_at + timedelta(milliseconds=1),
                        )
                    else:
                        append_message(
                            session,
                            chat,
                            answer.content,
                            sender_type=SenderType.AI,
                            sender=None,
                            reply_to=user_db_msg.id,
                            citations=answer.citations,
                            tool_calls=answer.tool_calls,
                            duration_ms=answer.duration_ms,
                            message_id=answer.message_id,
                            created_at=ai_created_at,
                        )
                else:
                    # Outage: append fallback system notice to Postgres
                    user_db_msg = append_message(
                        session,
                        chat,
                        cleaned_text,
                        sender_type=SenderType.USER,
                        sender=user,
                        client_message_id=payload.client_message_id,
                        input_hash=digest,
                        entities=entities_dicts,
                        created_at=submitted_at,
                    )
                    append_message(
                        session,
                        chat,
                        "ИИ-помощник временно недоступен. Вы можете перенаправить запрос оператору.",
                        sender_type=SenderType.SYSTEM,
                        reply_to=user_db_msg.id,
                        created_at=submitted_at + timedelta(milliseconds=1),
                    )

                messages = await submission_messages(session, user_db_msg)
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
