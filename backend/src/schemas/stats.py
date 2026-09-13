from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TopicSummaryStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    topic: str = Field(
        description="Имя темы, как в URL `/stats/<topic>`",
        examples=["Работа с контрактами"],
    )
    status: Literal["ready", "outdated", "pending", "none"] = Field(
        description=(
            "`ready` — сводка актуальна; "
            "`outdated` — есть новая обратная связь, идёт пересчёт; "
            "`pending` — обратная связь есть, сводки ещё нет; "
            "`none` — обратной связи по теме нет."
        ),
        examples=["ready"],
    )
    summary: str | None = Field(
        default=None,
        description="Markdown-текст сводки. `null`, если сводки ещё нет (`pending` или `none`)",
        examples=["По теме… — не подошёл ответ.\n\n- Уточнить в базе знаний…"],
    )
    feedback_chats: int = Field(
        description="Сколько чатов темы имеют обратную связь (оценка пользователя или перевод)",
        examples=[2],
    )
    updated_at: str | None = Field(
        default=None,
        description="Когда сводка была сгенерирована, ISO 8601. `null`, если сводки нет",
    )
