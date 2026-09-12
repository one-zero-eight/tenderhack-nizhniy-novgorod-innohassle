import asyncio

import httpx
import pytest

from scripts.ai_stub import app as stub_app
from src.config_schema import ApiSettings
from src.services.ai_client import AIClient, AIUnavailable


def settings(**kwargs):
    return ApiSettings(
        db_url="postgresql+asyncpg://unused/unused", jwt_secret="unit-test-signing-secret-at-least-32", **kwargs
    )


async def test_create_chat_success():
    async def respond(request: httpx.Request):
        assert request.url.path == "/ml-api/chat"
        return httpx.Response(201, json={"id": "ml-chat-123", "title": "Новый чат"})

    async with httpx.AsyncClient(base_url="http://ai/", transport=httpx.MockTransport(respond)) as http:
        client = AIClient(http, settings())
        chat_id = await client.create_chat()
        assert chat_id == "ml-chat-123"


async def test_send_message_sse_success():
    async def respond(request: httpx.Request):
        assert request.url.path == "/ml-api/chat/chat-1/message"
        sse_data = (
            "event: start\ndata: {\"message_id\": \"m1\"}\n\n"
            "event: token\ndata: {\"delta\": \"Hi\", \"content\": \"Hi\"}\n\n"
            "event: done\ndata: {\"message_id\": \"m1\", \"content\": \"Hi there!\"}\n\n"
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=sse_data)

    async with httpx.AsyncClient(base_url="http://ai/", transport=httpx.MockTransport(respond)) as http:
        client = AIClient(http, settings())
        answer = await client.send_message("chat-1", "Hello")
        assert answer.message_id == "m1"
        assert answer.content == "Hi there!"


async def test_send_message_sse_error_event():
    async def respond(request: httpx.Request):
        sse_data = "event: error\ndata: {\"message\": \"Model overloaded\"}\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=sse_data)

    async with httpx.AsyncClient(base_url="http://ai/", transport=httpx.MockTransport(respond)) as http:
        client = AIClient(http, settings())
        with pytest.raises(AIUnavailable):
            await client.send_message("chat-1", "Hello")


async def test_send_message_http_error():
    async def respond(request: httpx.Request):
        return httpx.Response(500, text="Internal server error")

    async with httpx.AsyncClient(base_url="http://ai/", transport=httpx.MockTransport(respond)) as http:
        client = AIClient(http, settings())
        with pytest.raises(AIUnavailable):
            await client.send_message("chat-1", "Hello")


async def test_total_deadline_bounds_http_call():
    async def slow(request: httpx.Request):
        await asyncio.sleep(1)
        raise AssertionError("The client should cancel this request at its deadline")

    async with httpx.AsyncClient(base_url="http://ai/", transport=httpx.MockTransport(slow)) as http:
        client = AIClient(http, settings(ai_answer_timeout=0.01))
        with pytest.raises(AIUnavailable):
            await client.send_message("chat-1", "message")


async def test_routing_stub_returns_none():
    async with httpx.AsyncClient(base_url="http://ai/") as http:
        client = AIClient(http, settings())
        assert await client.route("message") is None


async def test_development_stub_matches_client_contract(monkeypatch):
    monkeypatch.delenv("API_SETTINGS__AI_SERVICE_TOKEN", raising=False)
    async with httpx.AsyncClient(base_url="http://stub/", transport=httpx.ASGITransport(stub_app)) as http:
        client = AIClient(http, settings())
        chat_id = await client.create_chat()
        assert chat_id.startswith("stub-chat-")
        answer = await client.send_message(chat_id, "ordinary message")
        assert "Демонстрационный ответ" in answer.content
        assert (await client.health())["mode"] == "stub"


async def test_stub_requires_configured_internal_token(monkeypatch):
    monkeypatch.setenv("API_SETTINGS__AI_SERVICE_TOKEN", "stub-service-token")
    async with httpx.AsyncClient(base_url="http://stub/", transport=httpx.ASGITransport(stub_app)) as http:
        client = AIClient(http, settings())
        with pytest.raises(AIUnavailable):
            await client.create_chat()
        http.headers["Authorization"] = "Bearer stub-service-token"
        chat_id = await client.create_chat()
        assert chat_id.startswith("stub-chat-")
