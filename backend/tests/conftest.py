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
        self.chat_files: dict[str, list[dict]] = {}
        self.attachments: dict[str, dict] = {}
        self.handrules: dict[str, dict] = {}

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path
        try:
            body = json.loads(request.content) if request.content else {}
        except Exception:
            body = {}
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

        # File upload
        if request.method == "POST" and "/ml-api/chat/" in endpoint and endpoint.endswith("/upload"):
            parts = endpoint.split("/")
            chat_id = parts[3]
            if chat_id not in self.chats:
                return httpx.Response(404, json={"detail": "Чат не найден"})
            if self.chats[chat_id].get("closed_at") is not None:
                return httpx.Response(409, json={"detail": "Чат закрыт"})
            content = request.content
            if not content:
                return httpx.Response(400, json={"detail": "Файл пуст"})
            filename = "test-file.png"
            content_type = "image/png"
            if b'filename="' in content:
                try:
                    filename = content.split(b'filename="')[1].split(b'"')[0].decode()
                except Exception:
                    pass
            if b'Content-Type: ' in content:
                try:
                    content_type = content.split(b'Content-Type: ')[1].split(b'\r\n')[0].decode()
                except Exception:
                    pass

            file_data = content
            if b"\r\n\r\n" in content:
                file_data = content.split(b"\r\n\r\n", 1)[1]
                if b"\r\n--" in file_data:
                    file_data = file_data.rsplit(b"\r\n--", 1)[0]

            file_id = f"test-file-{len(self.attachments) + 1}"
            record = {
                "id": file_id,
                "chat_id": chat_id,
                "filename": filename,
                "content_type": content_type,
                "kind": "image" if content_type.startswith("image/") else "document",
                "size": len(file_data),
                "is_image": content_type.startswith("image/"),
                "created_at": "2026-09-12T00:00:00Z",
                "url": f"/attachments/{file_id}",
                "_data": file_data,
            }
            self.chat_files.setdefault(chat_id, []).append(record)
            self.attachments[file_id] = record
            return httpx.Response(201, json={k: v for k, v in record.items() if k != "_data"})

        # File content
        if request.method == "GET" and "/ml-api/chat/" in endpoint and "/files/" in endpoint and endpoint.endswith("/content"):
            parts = endpoint.split("/")
            chat_id = parts[3]
            file_id = parts[5]
            for f in self.chat_files.get(chat_id, []):
                if f["id"] == file_id:
                    return httpx.Response(200, content=f["_data"], headers={"content-type": f["content_type"]})
            return httpx.Response(404, json={"detail": "Файл не найден"})

        # Single file
        if request.method == "GET" and "/ml-api/chat/" in endpoint and "/files/" in endpoint:
            parts = endpoint.split("/")
            chat_id = parts[3]
            file_id = parts[5]
            for f in self.chat_files.get(chat_id, []):
                if f["id"] == file_id:
                    return httpx.Response(200, json={k: v for k, v in f.items() if k != "_data"})
            return httpx.Response(404, json={"detail": "Файл не найден"})

        # Delete file
        if request.method == "DELETE" and "/ml-api/chat/" in endpoint and "/files/" in endpoint:
            parts = endpoint.split("/")
            chat_id = parts[3]
            file_id = parts[5]
            files = self.chat_files.get(chat_id, [])
            for idx, f in enumerate(files):
                if f["id"] == file_id:
                    files.pop(idx)
                    return httpx.Response(204)
            return httpx.Response(404, json={"detail": "Файл не найден"})

        # List files
        if request.method == "GET" and "/ml-api/chat/" in endpoint and endpoint.endswith("/files"):
            parts = endpoint.split("/")
            chat_id = parts[3]
            if chat_id not in self.chats:
                return httpx.Response(404, json={"detail": "Чат не найден"})
            return httpx.Response(200, json=[{k: v for k, v in f.items() if k != "_data"} for f in self.chat_files.get(chat_id, [])])

        # Attachment download
        if request.method == "GET" and (endpoint.startswith("/attachments/") or endpoint.startswith("/ml-assets/attachments/")):
            file_id = endpoint.split("/")[-1]
            if file_id in self.attachments:
                rec = self.attachments[file_id]
                return httpx.Response(200, content=rec["_data"], headers={"content-type": rec["content_type"]})
            return httpx.Response(404, json={"detail": "Вложение не найдено"})

        if "/ml-api/chat/" in endpoint and endpoint.endswith("/message"):
            if self.answer_mode == "error":
                return httpx.Response(503)
            if self.answer_mode == "timeout":
                raise httpx.ReadTimeout("Simulated timeout")
            parts = endpoint.split("/")
            chat_id = parts[3]
            turn_num = len(self.chats[chat_id]["messages"]) // 2 + 1 if chat_id in self.chats else 1
            msg_id = f"msg-{turn_num}"

            pending = self.chat_files.pop(chat_id, [])
            user_att = [{k: v for k, v in f.items() if k != "_data"} for f in pending]

            if chat_id in self.chats:
                self.chats[chat_id]["messages"].append({
                    "id": f"msg-user-{len(self.chats[chat_id]['messages']) + 1}",
                    "role": "user",
                    "content": body.get("message", ""),
                    "tools": [],
                    "attachments": user_att,
                })
                self.chats[chat_id]["messages"].append({
                    "id": msg_id,
                    "role": "assistant",
                    "content": "A supported answer",
                    "tools": [],
                    "attachments": [],
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

        if request.method == "GET" and endpoint == "/ml-api/handrules":
            limit = int(request.url.params.get("limit", 100))
            rules = list(self.handrules.values())
            rules.reverse()
            return httpx.Response(200, json=rules[:limit])

        if request.method == "POST" and endpoint == "/ml-api/handrules":
            rule_id = f"rule-{len(self.handrules) + 1}"
            now = "2026-09-12T00:00:00Z"
            record = {
                "id": rule_id,
                "user_message": body.get("user_message", ""),
                "instructions": body.get("instructions", ""),
                "created_at": now,
                "updated_at": now,
            }
            self.handrules[rule_id] = record
            return httpx.Response(201, json=record)

        if request.method == "GET" and endpoint == "/ml-api/handrules/search":
            q = request.url.params.get("q", "").lower()
            k = int(request.url.params.get("k", 3))
            matches = [
                r for r in self.handrules.values()
                if any(w in r["user_message"].lower() for w in q.split())
            ]
            if not matches:
                matches = list(self.handrules.values())
            return httpx.Response(200, json=matches[:k])

        if request.method == "GET" and endpoint.startswith("/ml-api/handrules/"):
            rule_id = endpoint.split("/")[-1]
            if rule_id in self.handrules:
                return httpx.Response(200, json=self.handrules[rule_id])
            return httpx.Response(404, json={"detail": "Правило не найдено"})

        if request.method == "PATCH" and endpoint.startswith("/ml-api/handrules/"):
            rule_id = endpoint.split("/")[-1]
            if rule_id not in self.handrules:
                return httpx.Response(404, json={"detail": "Правило не найдено"})
            rule = self.handrules[rule_id]
            if "user_message" in body and body["user_message"] is not None:
                rule["user_message"] = body["user_message"]
            if "instructions" in body and body["instructions"] is not None:
                rule["instructions"] = body["instructions"]
            rule["updated_at"] = "2026-09-12T00:00:01Z"
            return httpx.Response(200, json=rule)

        if request.method == "DELETE" and endpoint.startswith("/ml-api/handrules/"):
            rule_id = endpoint.split("/")[-1]
            if rule_id not in self.handrules:
                return httpx.Response(404, json={"detail": "Правило не найдено"})
            self.handrules.pop(rule_id)
            return httpx.Response(204)

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
