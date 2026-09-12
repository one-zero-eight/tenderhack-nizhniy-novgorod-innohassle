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
from src.db.models import SupportLine, User  # noqa: E402
from src.db.storage import SQLAlchemyStorage  # noqa: E402
from src.services.ai_client import AIClient  # noqa: E402
from src.services.auth import issue_token  # noqa: E402
from src.services.chats import ChatService  # noqa: E402
from src.services.moderation import ModerationUnavailable  # noqa: E402

PASSWORD = "test-user-password"


class FakeAI:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.answer_mode = "answered"
        self.hold: str | None = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.chats: dict[str, dict] = {}

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path
        body = json.loads(request.content) if request.content else {}
        self.calls.append((endpoint, body))
        if self.hold == endpoint:
            self.started.set()
            await self.release.wait()
        if endpoint == "/health":
            return httpx.Response(200, json={"status": "ready", "mode": "stub"})
        if request.method == "POST" and endpoint == "/ml-api/chat":
            chat_id = f"test-ml-chat-{len(self.chats) + 1}"
            self.chats[chat_id] = {
                "id": chat_id,
                "title": "Новый чат",
                "system_prompt": body.get("system_prompt") if body else None,
                "redirect_line": None,
                "redirect_reason": None,
                "topic": None,
                "subtopic": None,
                "closed_at": None,
                "created_at": "2026-09-12T00:00:00Z",
                "updated_at": "2026-09-12T00:00:00Z",
                "messages": [],
            }
            return httpx.Response(201, json={"id": chat_id, "title": "Новый чат", "topic": None, "subtopic": None})
        if "/ml-api/chat/" in endpoint and endpoint.endswith("/message"):
            if self.answer_mode == "error":
                return httpx.Response(503)
            if self.answer_mode == "timeout":
                raise httpx.ReadTimeout("Simulated timeout")
            parts = endpoint.split("/")
            chat_id = parts[3]
            turn_num = len(self.chats[chat_id]["messages"]) // 2 + 1 if chat_id in self.chats else 1
            msg_id = f"msg-{turn_num}"
            if chat_id in self.chats:
                self.chats[chat_id]["messages"].append({
                    "id": f"msg-user-{len(self.chats[chat_id]['messages']) + 1}",
                    "role": "user",
                    "content": body.get("message", ""),
                    "tools": [],
                })
                self.chats[chat_id]["messages"].append({
                    "id": msg_id,
                    "role": "assistant",
                    "content": "A supported answer",
                    "tools": [],
                })
            sse_text = (
                f"event: start\ndata: {{\"message_id\": \"{msg_id}\"}}\n\n"
                f"event: done\ndata: {{\"message_id\": \"{msg_id}\", \"content\": \"A supported answer\"}}\n\n"
            )
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=sse_text,
            )
        if request.method == "GET" and endpoint.startswith("/ml-api/chat/"):
            parts = endpoint.split("/")
            chat_id = parts[3]
            if chat_id in self.chats:
                return httpx.Response(200, json=self.chats[chat_id])
            return httpx.Response(404, json={"detail": "Not found"})
        if request.method == "DELETE" and endpoint.startswith("/ml-api/chat/"):
            parts = endpoint.split("/")
            chat_id = parts[3]
            self.chats.pop(chat_id, None)
            return httpx.Response(204)

        if endpoint == "/ml-api/knowledge-base":
            return httpx.Response(
                200,
                json=[
                    {
                        "slug": "instrukciya-po-sozdaniyu-oferty-i-ste",
                        "title": "Инструкция по созданию оферты и СТЕ",
                        "sections": 5,
                        "url": "/knowledge-base/instrukciya-po-sozdaniyu-oferty-i-ste",
                    }
                ],
            )
        if endpoint == "/ml-api/knowledge-base/instrukciya-po-sozdaniyu-oferty-i-ste":
            return httpx.Response(
                200,
                json={
                    "slug": "instrukciya-po-sozdaniyu-oferty-i-ste",
                    "title": "Инструкция по созданию оферты и СТЕ",
                    "sections": [{"id": "1", "title": "Section 1"}],
                },
            )
        if endpoint == "/ml-api/knowledge-base/instrukciya-po-sozdaniyu-oferty-i-ste/1":
            return httpx.Response(
                200,
                json={
                    "id": "1",
                    "title": "Section 1",
                    "content_md": "# Section 1",
                },
            )
        if endpoint.startswith("/ml-api/knowledge-base/not-found"):
            return httpx.Response(404, json={"detail": "Not found"})
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

    async def transfer_to_operator(self, chat_id: str, line_id: int = 1, *, login: str = "user"):
        user = self.users[login]
        service = ChatService(self.storage, self.ai, self.moderator)
        return await service.request_operator(chat_id, user, line_id)

    async def close_chat(self, chat_id: str, reason: str = "resolved", *, login: str = "user"):
        user = self.users[login]
        service = ChatService(self.storage, self.ai, self.moderator)
        return await service.close(chat_id, user, reason)


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
        monkeypatch.setattr("src.api.lifespan.RubertModerator", FakeModerator)
        monkeypatch.setattr(SQLAlchemyStorage, "from_url", lambda url: storage)
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            # Startup creates required support lines, but no accounts.
            async with storage.create_session() as session:
                assert list(await session.scalars(select(SupportLine.id).order_by(SupportLine.id))) == [1, 2, 3]
                assert await session.scalar(select(User.id)) is None
            async with httpx.AsyncClient(transport=httpx.MockTransport(fake), base_url="http://ai.test/") as ai_http:
                app.state.ai = AIClient(ai_http, settings)
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://backend.test"
                ) as client:
                    for login, role, line_id in [
                        ("user", "buyer", None),
                        ("user2", "seller", None),
                        ("operator1", "support", 1),
                        ("operator2", "support", 2),
                        ("operator3", "support", 3),
                        ("admin", "admin", None),
                    ]:
                        response = await client.post(
                            "/auth/register",
                            json={"login": login, "password": PASSWORD, "role": role, "support_line_id": line_id},
                        )
                        assert response.status_code == 201, response.text
                    async with storage.create_session() as session:
                        users = {user.login: user for user in await session.scalars(select(User))}
                    yield Case(client, storage, fake, app.state.moderator, settings, users)
    finally:
        fake.release.set()
        if app is not None and hasattr(app.state, "moderator"):
            app.state.moderator.release.set()
        await storage.close_connection()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin_engine.dispose()
