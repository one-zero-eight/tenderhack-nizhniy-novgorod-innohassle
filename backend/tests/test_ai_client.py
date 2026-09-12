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
            'event: start\ndata: {"message_id": "m1"}\n\n'
            'event: token\ndata: {"delta": "Hi", "content": "Hi"}\n\n'
            'event: done\ndata: {"message_id": "m1", "content": "Hi there!"}\n\n'
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


async def test_ai_client_upload_file_success():
    async def respond(request: httpx.Request):
        assert request.url.path == "/ml-api/chat/chat-1/upload"
        return httpx.Response(
            201,
            json={
                "id": "file-123",
                "chat_id": "chat-1",
                "filename": "document.pdf",
                "content_type": "application/pdf",
                "kind": "document",
                "size": 1024,
                "is_image": False,
                "created_at": "2026-09-12T00:00:00Z",
                "url": "/attachments/file-123",
            },
        )

    async with httpx.AsyncClient(base_url="http://ai/", transport=httpx.MockTransport(respond)) as http:
        client = AIClient(http, settings())
        file_info = await client.upload_file("chat-1", "document.pdf", b"hello world", "application/pdf")
        assert file_info["id"] == "file-123"
        assert file_info["kind"] == "document"
        assert file_info["is_image"] is False


async def test_ai_client_upload_file_errors():
    async def respond(request: httpx.Request):
        if "chat-404" in request.url.path:
            return httpx.Response(404, json={"detail": "Чат не найден"})
        if "chat-409" in request.url.path:
            return httpx.Response(409, json={"detail": "Чат закрыт"})
        return httpx.Response(400, json={"detail": "Файл пуст"})

    async with httpx.AsyncClient(base_url="http://ai/", transport=httpx.MockTransport(respond)) as http:
        client = AIClient(http, settings())
        with pytest.raises(KeyError):
            await client.upload_file("chat-404", "doc.pdf", b"data")
        with pytest.raises(ValueError, match="Чат закрыт"):
            await client.upload_file("chat-409", "doc.pdf", b"data")
        with pytest.raises(ValueError, match="Файл пуст"):
            await client.upload_file("chat-1", "doc.pdf", b"")


async def test_ai_client_list_get_delete_files_and_attachments():
    async def respond(request: httpx.Request):
        path = request.url.path
        if request.method == "GET" and path == "/ml-api/chat/chat-1/files":
            return httpx.Response(200, json=[{"id": "file-1", "chat_id": "chat-1"}])
        if request.method == "GET" and path == "/ml-api/chat/chat-1/files/file-1":
            return httpx.Response(200, json={"id": "file-1", "chat_id": "chat-1"})
        if request.method == "DELETE" and path == "/ml-api/chat/chat-1/files/file-1":
            return httpx.Response(204)
        if request.method == "GET" and path == "/ml-api/chat/chat-1/files/file-1/content":
            return httpx.Response(200, content=b"content-bytes", headers={"content-type": "image/png"})
        if request.method == "GET" and path == "/attachments/file-1":
            return httpx.Response(200, content=b"attachment-bytes", headers={"content-type": "image/png"})
        return httpx.Response(404, json={"detail": "Not found"})

    async with httpx.AsyncClient(base_url="http://ai/", transport=httpx.MockTransport(respond)) as http:
        client = AIClient(http, settings())
        files = await client.list_files("chat-1")
        assert len(files) == 1
        assert files[0]["id"] == "file-1"

        file_meta = await client.get_file("chat-1", "file-1")
        assert file_meta["id"] == "file-1"

        await client.delete_file("chat-1", "file-1")

        content, ctype, disp = await client.get_file_content("chat-1", "file-1")
        assert content == b"content-bytes"
        assert ctype == "image/png"

        att_content, att_type, _ = await client.get_attachment("file-1")
        assert att_content == b"attachment-bytes"
        assert att_type == "image/png"


async def test_development_stub_file_operations(monkeypatch):
    monkeypatch.delenv("API_SETTINGS__AI_SERVICE_TOKEN", raising=False)
    async with httpx.AsyncClient(base_url="http://stub/", transport=httpx.ASGITransport(stub_app)) as http:
        client = AIClient(http, settings())
        chat_id, _ = await client.create_chat()

        # Upload file
        uploaded = await client.upload_file(chat_id, "photo.jpg", b"image-binary-data", "image/jpeg")
        assert uploaded["filename"] == "photo.jpg"
        assert uploaded["is_image"] is True
        file_id = uploaded["id"]

        # List files
        files = await client.list_files(chat_id)
        assert len(files) == 1
        assert files[0]["id"] == file_id

        # Get file metadata
        single = await client.get_file(chat_id, file_id)
        assert single["id"] == file_id

        # Get file content
        content, ctype, _ = await client.get_file_content(chat_id, file_id)
        assert content == b"image-binary-data"
        assert ctype == "image/jpeg"

        # Permanent attachment content
        att_bytes, att_type, _ = await client.get_attachment(file_id)
        assert att_bytes == b"image-binary-data"
        assert att_type == "image/jpeg"

        # Send message consumes attachments into message history
        answer = await client.send_message(chat_id, "Here is my photo")
        assert answer.message_id.startswith("msg-")

        # Files list should now be empty
        assert await client.list_files(chat_id) == []

        # Chat history now has attachments
        chat_history = await client.get_chat(chat_id)
        user_msg = chat_history["messages"][0]
        assert len(user_msg["attachments"]) == 1
        assert user_msg["attachments"][0]["id"] == file_id
