from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

import src.api.logging_  # noqa: F401
from src.db import SQLAlchemyStorage
from src.services.ai_client import AIClient
from src.services.moderation import RubertModerator


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Application startup
    settings = app.state.settings
    storage = SQLAlchemyStorage.from_url(settings.db_url.get_secret_value())
    app.state.storage = storage
    headers = {}
    if settings.ai_service_token:
        headers["Authorization"] = f"Bearer {settings.ai_service_token.get_secret_value()}"
    http = httpx.AsyncClient(
        base_url=str(settings.ai_base_url).rstrip("/") + "/", headers=headers, follow_redirects=False, trust_env=False
    )
    app.state.ai = AIClient(http, settings)
    moderator = RubertModerator(settings)
    app.state.moderator = moderator
    try:
        # Fail startup if local model files are missing or incompatible.
        await moderator.start()
        yield
    finally:
        await moderator.close()
        await http.aclose()
        # Application shutdown
        await storage.close_connection()
