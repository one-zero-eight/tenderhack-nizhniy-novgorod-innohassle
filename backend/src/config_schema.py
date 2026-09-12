import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[1] / "settings.yaml"


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_root_path: str = Field("/api")
    'Prefix for the API path (e.g. "/api/v0")'
    cors_allow_origin_regex: str = ".*"
    "Allowed origins for CORS: from which domains requests to the API are allowed."
    db_url: SecretStr = Field(
        ...,
        examples=[
            "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
            "postgresql+asyncpg://postgres:postgres@db:5432/postgres",
        ],
    )
    "PostgreSQL database connection URL"
    jwt_secret: SecretStr = Field(..., min_length=32)
    "Secret used to sign access tokens; use at least 32 random characters."
    access_token_minutes: int = Field(120, ge=1, le=1440)
    ai_base_url: AnyHttpUrl = Field(default="http://127.0.0.1:8010")
    ai_service_token: SecretStr | None = None
    moderation_model_path: Path = Path("models/rubert-tiny-toxicity")
    moderation_threshold: float = Field(0.8, gt=0, lt=1)
    moderation_block_labels: list[Literal["obscenity", "insult"]] = Field(default=["obscenity", "insult"], min_length=1)
    moderation_timeout: float = Field(5, gt=0, le=120)
    ai_answer_timeout: float = Field(300, gt=0, le=300, description="Total deadline in seconds for an ML answer stream.")
    ai_routing_timeout: float = Field(5, gt=0, le=120)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        json_schema_extra={"title": "Settings"},
        extra="ignore",
        env_nested_delimiter="__",
    )
    api_settings: ApiSettings

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings, dotenv_settings]
        yaml_path = Path(os.getenv("SETTINGS_PATH", DEFAULT_SETTINGS_PATH))
        if yaml_path.exists():
            sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=yaml_path))
        sources.append(file_secret_settings)
        return tuple(sources)

    @classmethod
    def save_schema(cls, path: Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            schema = {"$schema": "https://json-schema.org/draft-07/schema", **cls.model_json_schema()}
            yaml.dump(schema, f, sort_keys=False)
