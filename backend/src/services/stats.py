from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select

from src.db.models import Chat, ChatStatus, Message, Rating, SenderType, utcnow
from src.db.storage import AbstractSQLAlchemyStorage
from src.schemas.chat import AdminRatingOut, RatingPage
from src.services.errors import fail


def period_filters(column, since: datetime | None, until: datetime | None) -> list:
    if since is not None and until is not None and since >= until:
        fail(422, "INVALID_PERIOD", "The 'from' date must be earlier than 'to'")
    return ([column >= since] if since is not None else []) + ([column < until] if until is not None else [])


class StatsService:
    def __init__(self, storage: AbstractSQLAlchemyStorage):
        self.storage = storage

    async def ratings(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        stars: int | None = None,
        stars_lte: int | None = None,
        sender_type: SenderType | None = None,
        line_id: int | None = None,
        operator_id: UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> RatingPage:
        filters = period_filters(Rating.created_at, since, until)
        if stars is not None:
            filters.append(Rating.stars == stars)
        if stars_lte is not None:
            filters.append(Rating.stars <= stars_lte)
        if sender_type is not None:
            filters.append(Message.sender_type == sender_type)
        if line_id is not None:
            filters.append(Message.support_line_id == line_id)
        if operator_id is not None:
            filters.extend([Message.sender_type == SenderType.OPERATOR, Message.sender_id == operator_id])
        async with self.storage.create_session() as session:
            total = await session.scalar(select(func.count()).select_from(Rating).join(Message).where(*filters))
            rows = await session.execute(
                select(Rating, Message)
                .join(Message)
                .where(*filters)
                .order_by(
                    Rating.created_at.desc(),
                    Rating.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
            items = [
                AdminRatingOut(
                    id=rating.id,
                    message_id=rating.message_id,
                    user_id=rating.user_id,
                    stars=rating.stars,
                    comment=rating.comment,
                    created_at=rating.created_at,
                    updated_at=rating.updated_at,
                    chat_id=message.chat_id,
                    sender_type=message.sender_type,
                    sender_id=message.sender_id,
                    sender_name=message.sender_name,
                    support_line_id=message.support_line_id,
                    message_text=message.text,
                )
                for rating, message in rows
            ]
            return RatingPage(items=items, total=total, offset=offset, limit=limit)

    async def summary(self, since: datetime | None, until: datetime | None) -> dict:
        chat_filters = period_filters(Chat.created_at, since, until)
        rating_filters = period_filters(Rating.created_at, since, until)
        activity_filters = period_filters(Message.created_at, since, until)
        async with self.storage.create_session() as session:
            statuses = dict(
                (
                    await session.execute(select(Chat.status, func.count()).where(*chat_filters).group_by(Chat.status))
                ).all()
            )
            closures = dict(
                (
                    await session.execute(
                        select(Chat.close_reason, func.count())
                        .where(
                            *chat_filters,
                            Chat.status == ChatStatus.CLOSED,
                        )
                        .group_by(Chat.close_reason)
                    )
                ).all()
            )
            handoffs = dict(
                (
                    await session.execute(
                        select(Chat.support_line_id, func.count())
                        .where(
                            *chat_filters,
                            Chat.handed_off_at.is_not(None),
                        )
                        .group_by(Chat.support_line_id)
                    )
                ).all()
            )
            activity = dict(
                (
                    await session.execute(
                        select(Message.sender_type, func.count())
                        .where(
                            *activity_filters,
                            Message.sender_type.in_([SenderType.AI, SenderType.OPERATOR]),
                            Message.is_redacted.is_(False),
                        )
                        .group_by(Message.sender_type)
                    )
                ).all()
            )
            count, average = (
                await session.execute(select(func.count(Rating.id), func.avg(Rating.stars)).where(*rating_filters))
            ).one()
            histogram = dict(
                (
                    await session.execute(
                        select(Rating.stars, func.count()).where(*rating_filters).group_by(Rating.stars)
                    )
                ).all()
            )
            groups = {}
            for label, column in [
                ("by_sender_type", Message.sender_type),
                ("by_operator", Message.sender_id),
                ("by_support_line", Message.support_line_id),
            ]:
                query = select(column, func.count(Rating.id), func.avg(Rating.stars)).select_from(Rating).join(Message)
                filters = list(rating_filters)
                if label == "by_operator":
                    filters.append(Message.sender_type == SenderType.OPERATOR)
                groups[label] = [
                    {"key": str(key) if key is not None else None, "count": n, "average": float(avg)}
                    for key, n, avg in (await session.execute(query.where(*filters).group_by(column))).all()
                ]
            waiting = dict(
                (
                    await session.execute(
                        select(Chat.support_line_id, func.count())
                        .where(
                            Chat.status == ChatStatus.WAITING_OPERATOR,
                        )
                        .group_by(Chat.support_line_id)
                    )
                ).all()
            )
            assigned = dict(
                (
                    await session.execute(
                        select(Chat.operator_id, func.count())
                        .where(
                            Chat.status == ChatStatus.OPERATOR,
                        )
                        .group_by(Chat.operator_id)
                    )
                ).all()
            )
        return {
            "period": {"from": since, "to": until},
            "chats": {
                "total": sum(statuses.values()),
                "by_status": {state.value: statuses.get(state, 0) for state in ChatStatus},
                "by_close_reason": closures,
                "handed_off_by_line": {str(line): handoffs.get(line, 0) for line in (1, 2, 3)},
            },
            "activity": {"ai": activity.get(SenderType.AI, 0), "operator": activity.get(SenderType.OPERATOR, 0)},
            "ratings": {
                "count": count,
                "average": float(average) if average is not None else None,
                "histogram": {str(stars): histogram.get(stars, 0) for stars in range(1, 6)},
                **groups,
            },
            "queue_snapshot": {
                "as_of": utcnow(),
                "waiting_by_line": {str(line): waiting.get(line, 0) for line in (1, 2, 3)},
                "assigned_by_operator": {str(key): n for key, n in assigned.items()},
            },
        }
