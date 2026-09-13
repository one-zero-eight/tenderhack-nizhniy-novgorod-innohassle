from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class EntityIn(Schema):
    alias: str = Field(
        default="",
        max_length=64,
        description="Псевдоним сущности в тексте сообщения (без @).",
        examples=["contract-1", "doc-cntr-1"],
    )
    kind: str = Field(
        default="",
        max_length=64,
        description="Вид сущности: contract, procurement, offer, document или любой свой.",
        examples=["contract", "document"],
    )
    text: str = Field(
        default="",
        max_length=2000,
        description="Компактное человекочитаемое описание: что это за сущность и её ключевые поля.",
        examples=["Контракт №44-ФЗ, статус: подписан"],
    )
    link: str | None = Field(
        default=None,
        max_length=500,
        description="Ссылка на сущность в исходной системе (необязательно).",
    )
    extra: dict[str, Any] | None = Field(
        default=None,
        description="Произвольные дополнительные поля.",
    )


class EntityOut(Schema):
    alias: str = Field(default="", max_length=64)
    kind: str = Field(default="", max_length=64)
    text: str = Field(default="", max_length=2000)
    link: str | None = Field(default=None, max_length=500)
    extra: dict[str, Any] | None = None
