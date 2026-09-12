import asyncio
import json
import os
from dataclasses import dataclass
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

# Importing the application must not depend on a developer's private settings.
os.environ["API_SETTINGS__DB_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:unused@localhost/backend_test",
)
os.environ["API_SETTINGS__JWT_SECRET"] = "test-only-signing-secret-at-least-32-characters"

from src.api.app import create_app  # noqa: E402
from src.config_schema import ApiSettings  # noqa: E402
from src.db.models import User  # noqa: E402
from src.db.storage import SQLAlchemyStorage  # noqa: E402
from src.seed import seed_demo  # noqa: E402
from src.services.ai_client import AIClient  # noqa: E402
from src.services.auth import issue_token  # noqa: E402
from src.services.moderation import ModerationUnavailable  # noqa: E402

PASSWORD = "test-user-password"


class FakeAI:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.answer_mode = "answered"
        self.route_line = 2
        self.route_error = False
        self.hold: str | None = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path
        body = json.loads(request.content) if request.content else {}
        self.calls.append((endpoint, body))
        if self.hold == endpoint:
            self.started.set()
            await self.release.wait()
        request_id = body.get("request_id")
        if endpoint == "/health":
            return httpx.Response(200, json={"status": "ready", "mode": "stub"})
        if endpoint == "/v1/answer":
            if self.answer_mode == "error":
                return httpx.Response(503)
            if self.answer_mode == "timeout":
                raise httpx.ReadTimeout("Simulated timeout")
            answer = "A supported answer" if self.answer_mode == "answered" else None
            sources = [{"document_id": "guide", "title": "User guide", "section": "Profile"}] if answer else []
            return httpx.Response(
                200, json={"request_id": request_id, "outcome": self.answer_mode, "answer": answer, "sources": sources}
            )
        if endpoint == "/v1/route":
            if self.route_error:
                return httpx.Response(503)
            return httpx.Response(200, json={"request_id": request_id, "recommended_support_line_id": self.route_line})
        raise AssertionError(f"Unexpected AI endpoint {endpoint}")


class FakeModerator:
    def __init__(self, settings):
        self.calls = []
        self.error = False
        self.hold = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def start(self):
        pass

    async def close(self):
        pass

    async def is_blocked(self, text):
        self.calls.append(text)
        if self.hold:
            self.started.set()
            await self.release.wait()
        if self.error:
            raise ModerationUnavailable
        return "[block]" in text


@dataclass
class Case:
    client: httpx.AsyncClient
    storage: SQLAlchemyStorage
    ai: FakeAI
    moderator: FakeModerator
    settings: ApiSettings
    users: dict[str, User]

    def headers(self, login: str = "user") -> dict[str, str]:
        return {"Authorization": f"Bearer {issue_token(self.users[login].id, self.settings)}"}

    async def request(self, method: str, endpoint: str, *, login: str = "user", **kwargs) -> httpx.Response:
        return await self.client.request(method, endpoint, headers=self.headers(login), **kwargs)

    async def chat(self) -> str:
        response = await self.request("POST", "/chats")
        assert response.status_code == 201, response.text
        return response.json()["id"]

    async def send(
        self,
        chat_id: str,
        message: str = "How do I update my profile?",
        *,
        login: str = "user",
        client_id: str | None = None,
    ) -> httpx.Response:
        return await self.request(
            "POST",
            f"/chats/{chat_id}/messages",
            login=login,
            json={"text": message, "client_message_id": client_id or str(uuid4())},
        )


@pytest.fixture
async def case(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    settings = ApiSettings(
        db_url=url,
        jwt_secret=os.environ["API_SETTINGS__JWT_SECRET"],
        app_root_path="",
        ai_base_url="http://ai.test",
        ai_answer_timeout=5,
        ai_routing_timeout=5,
    )
    # Every test owns a fresh schema; existing data in the database is never truncated or dropped.
    schema = "test_" + uuid4().hex
    admin_engine = create_async_engine(url)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    storage = SQLAlchemyStorage(create_async_engine(url, connect_args={"server_settings": {"search_path": schema}}))
    fake = FakeAI()
    app = None
    try:
        await storage.create_all()
        await seed_demo(storage, PASSWORD)
        async with storage.create_session() as session:
            users = {user.login: user for user in await session.scalars(select(User))}
        monkeypatch.setattr("src.api.lifespan.RubertModerator", FakeModerator)
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            app.state.storage = storage
            async with httpx.AsyncClient(transport=httpx.MockTransport(fake), base_url="http://ai.test/") as ai_http:
                app.state.ai = AIClient(ai_http, settings)
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://backend.test"
                ) as client:
                    yield Case(client, storage, fake, app.state.moderator, settings, users)
    finally:
        fake.release.set()
        if app is not None and hasattr(app.state, "moderator"):
            app.state.moderator.release.set()
        await storage.close_connection()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin_engine.dispose()
