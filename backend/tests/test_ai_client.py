import asyncio
import logging

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
        chat_id, title = await client.create_chat()
        assert chat_id == "ml-chat-123"
        assert title == "Новый чат"



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


async def test_send_message_sse_error_event(caplog):
    caplog.set_level(logging.WARNING)
    logging.getLogger("src").addHandler(caplog.handler)
    async def respond(request: httpx.Request):
        sse_data = 'event: error\ndata: {"message": "Model overloaded"}\n\n'
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=sse_data)

    async with httpx.AsyncClient(base_url="http://ai/", transport=httpx.MockTransport(respond)) as http:
        client = AIClient(http, settings())
        with pytest.raises(AIUnavailable):
            await client.send_message("chat-1", "Hello")
        assert "AI service unavailable during send_message" in caplog.text


async def test_send_message_http_error(caplog):
    caplog.set_level(logging.WARNING)
    logging.getLogger("src").addHandler(caplog.handler)
    async def respond(request: httpx.Request):
        return httpx.Response(500, text="Internal server error")

    async with httpx.AsyncClient(base_url="http://ai/", transport=httpx.MockTransport(respond)) as http:
        client = AIClient(http, settings())
        with pytest.raises(AIUnavailable):
            await client.send_message("chat-1", "Hello")
        assert "AI service unavailable during send_message" in caplog.text


async def test_total_deadline_bounds_http_call():
    async def slow(request: httpx.Request):
        await asyncio.sleep(1)
        raise AssertionError("The client should cancel this request at its deadline")

    async with httpx.AsyncClient(base_url="http://ai/", transport=httpx.MockTransport(slow)) as http:
        client = AIClient(http, settings(ai_answer_timeout=0.01))
        with pytest.raises(AIUnavailable):
            await client.send_message("chat-1", "message")


async def test_generation_disables_only_the_request_read_timeout():
    client_timeout = httpx.Timeout(connect=1, read=0.01, write=2, pool=3)

    async def respond(request: httpx.Request):
        # MockTransport does not enforce HTTPX timeouts; inspect the settings
        # passed to the transport to guard against inheriting its short read limit.
        assert request.extensions["timeout"] == {"connect": 1, "read": None, "write": 2, "pool": 3}
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='event: done\ndata: {"message_id": "m1", "content": "Answer"}\n\n',
        )

    async with httpx.AsyncClient(
        base_url="http://ai/", transport=httpx.MockTransport(respond), timeout=client_timeout
    ) as http:
        client = AIClient(http, settings())
        answer = await client.send_message("chat-1", "message")
        assert answer.content == "Answer"
        assert http.timeout == client_timeout


@pytest.mark.parametrize("keep_sending", [False, True], ids=["silent-stream", "active-stream"])
async def test_total_deadline_bounds_stream_and_closes_response(keep_sending):
    class SlowStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b'event: start\ndata: {"message_id": "m1"}\n\n'
            while True:
                if keep_sending:
                    await asyncio.sleep(0)
                    yield b'event: token\ndata: {"delta": "a"}\n\n'
                else:
                    await asyncio.sleep(10)

        async def aclose(self):
            self.closed = True

    stream = SlowStream()

    async def respond(request: httpx.Request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    async with httpx.AsyncClient(base_url="http://ai/", transport=httpx.MockTransport(respond)) as http:
        client = AIClient(http, settings(ai_answer_timeout=0.02))
        with pytest.raises(AIUnavailable) as caught:
            await client.send_message("chat-1", "message")
        assert isinstance(caught.value.__cause__, TimeoutError)
        assert stream.closed


async def test_routing_stub_returns_none():
    async with httpx.AsyncClient(base_url="http://ai/") as http:
        client = AIClient(http, settings())
        assert await client.route("message") is None


async def test_development_stub_matches_client_contract(monkeypatch):
    monkeypatch.delenv("API_SETTINGS__AI_SERVICE_TOKEN", raising=False)
    async with httpx.AsyncClient(base_url="http://stub/", transport=httpx.ASGITransport(stub_app)) as http:
        client = AIClient(http, settings())
        chat_id, _ = await client.create_chat()
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
        chat_id, _ = await client.create_chat()
        assert chat_id.startswith("stub-chat-")



async def test_send_message_sse_tool_call_and_redirect():
    async def respond(request: httpx.Request):
        sse_data = (
            'event: tool_call\ndata: {"id": "call-1", "name": "open", "arguments": {"manual": "manual.json", "section_id": "1.2"}}\n\n'
            'event: redirect\ndata: {"line": "L2", "reason": "User requested operator"}\n\n'
            'event: done\ndata: {"message_id": "m2", "content": "Redirecting..."}\n\n'
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=sse_data)

    async with httpx.AsyncClient(base_url="http://ai/", transport=httpx.MockTransport(respond)) as http:
        client = AIClient(http, settings())
        answer = await client.send_message("chat-1", "Hello")
        assert answer.message_id == "m2"
        assert answer.content == "Redirecting..."
        assert len(answer.tool_calls) == 1
        assert answer.tool_calls[0]["name"] == "open"
        assert answer.citations == [{"manual": "manual.json", "section_id": "1.2"}]
        assert answer.redirect_line == 2
        assert answer.redirect_reason == "User requested operator"
