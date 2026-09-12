from pydantic import BaseModel, ConfigDict, Field


class HandRule(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Идентификатор правила, нужен для правки и удаления")
    user_message: str = Field(
        description="Пример вопроса пользователя, по которому правило ищется. Пишите его так, как пишут пользователи — поиск сравнивает формулировки",
        examples=["Не могу открыть страницу портала закупок, мне возвращают ошибку 500"],
    )
    instructions: str = Field(
        description="Что агенту делать в таком случае. Правило перебивает общие указания промпта",
        examples=["Не перенаправляй в поддержку: скажи, что мы уже работаем над проблемой, и попроси зайти позже"],
    )
    created_at: str | None = Field(default=None, description="Время создания, ISO 8601")
    updated_at: str | None = Field(default=None, description="Время последнего изменения, ISO 8601")


class HandRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_message: str = Field(
        min_length=1,
        max_length=4000,
        description="Пример вопроса пользователя",
        examples=["Не могу открыть страницу портала закупок, мне возвращают ошибку 500"],
    )
    instructions: str = Field(
        min_length=1,
        max_length=4000,
        description="Инструкция агенту на такой вопрос",
        examples=["Не перенаправляй в поддержку, скажи что мы уже работаем над проблемой"],
    )


class HandRulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_message: str | None = Field(
        default=None,
        min_length=1,
        max_length=4000,
        description="Пример вопроса пользователя",
    )
    instructions: str | None = Field(
        default=None,
        min_length=1,
        max_length=4000,
        description="Инструкция агенту на такой вопрос",
    )
