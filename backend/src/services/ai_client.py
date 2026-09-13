import asyncio
import json
import logging
from time import monotonic

import httpx
from httpx_sse import SSEError, aconnect_sse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.config_schema import ApiSettings

logger = logging.getLogger(__name__)


class AIUnavailable(Exception):
    """An unavailable endpoint or a response that violates the agreed AI contract."""


class MLAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message_id: str
    content: str
    tool_calls: list[dict] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)
    entities: list[dict] = Field(default_factory=list)
    redirect_line: int | None = None
    redirect_reason: str | None = None
    duration_ms: int | None = None


class AIClient:
    def __init__(self, http: httpx.AsyncClient, settings: ApiSettings):
        self.http = http
        self.settings = settings

    async def create_chat(
        self, system_prompt: str | None = None, username: str | None = None
    ) -> tuple[str, str]:
        """Create a chat session in the ML service (POST /ml-api/chat) and return (chat_id, title)."""
        try:
            async with asyncio.timeout(10.0):
                payload: dict[str, str] = {}
                if system_prompt:
                    payload["system_prompt"] = system_prompt
                if username:
                    payload["username"] = username
                response = await self.http.post("ml-api/chat", json=payload if payload else None, timeout=10.0)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or "id" not in data or not isinstance(data["id"], str):
                    raise ValueError("Invalid chat creation response")
                return data["id"], data.get("title", "Новый чат")
        except (httpx.HTTPError, TimeoutError, ValidationError, ValueError) as exc:
            logger.warning("AI service unavailable during create_chat: %s (%s)", exc, type(exc).__name__)
            raise AIUnavailable("ml-api/chat") from exc

    async def get_chat(self, ml_chat_id: str) -> dict:
        """Fetch chat metadata and messages from ML service (GET /ml-api/chat/{chat_id})."""
        endpoint = f"ml-api/chat/{ml_chat_id}"
        try:
            async with asyncio.timeout(10.0):
                response = await self.http.get(endpoint, timeout=10.0)
                if response.status_code == 404:
                    raise KeyError(ml_chat_id)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Invalid chat response format")
                return data
        except KeyError:
            raise
        except (httpx.HTTPError, TimeoutError, ValueError) as exc:
            logger.warning("AI service unavailable during get_chat (%s): %s", endpoint, exc)
            raise AIUnavailable(endpoint) from exc

    async def stream_message(self, ml_chat_id: str, message: str, entities: list[dict] | None = None):
        """Stream SSE events from ML service (POST /ml-api/chat/{chat_id}/message)."""
        endpoint = f"ml-api/chat/{ml_chat_id}/message"
        # Generation and tool calls may be silent for longer than HTTPX's read
        # timeout. Bound the whole answer below while keeping other I/O limits.
        timeout = httpx.Timeout(self.http.timeout)
        timeout.read = None
        started = monotonic()
        body: dict = {"message": message}
        if entities:
            body["entities"] = entities
        try:
            async with asyncio.timeout(self.settings.ai_answer_timeout):
                async with aconnect_sse(
                    self.http, "POST", endpoint, json=body, timeout=timeout
                ) as event_source:
                    async for sse in event_source.aiter_sse():
                        event_name = sse.event or "message"
                        try:
                            data = json.loads(sse.data) if sse.data else {}
                        except json.JSONDecodeError:
                            data = {"raw": sse.data}
                        yield event_name, data
        except (httpx.HTTPError, TimeoutError, SSEError) as exc:
            logger.warning(
                "AI service unavailable during send_message (%s) after %.1fs (answer deadline %.1fs): %s (%s)",
                endpoint,
                monotonic() - started,
                self.settings.ai_answer_timeout,
                exc,
                type(exc).__name__,
            )
            raise AIUnavailable(endpoint) from exc

    async def send_message(
        self, ml_chat_id: str, message: str, entities: list[dict] | None = None
    ) -> MLAnswer:
        """Send a message to ML service agent via SSE and consume response (JSON fallback)."""
        final_content = None
        final_message_id = None
        tool_calls = []
        citations = []
        redirect_line = None
        redirect_reason = None
        duration_ms = None

        try:
            async for event, data in self.stream_message(ml_chat_id, message, entities=entities):
                if event == "error":
                    msg = data.get("message", "SSE stream error")
                    raise ValueError(f"ML service error: {msg}")
                elif event == "tool_call":
                    name = data.get("name", "")
                    args = data.get("kwargs", data.get("arguments", {}))
                    tool_calls.append(data)
                    if name == "open" and isinstance(args, dict):
                        manual = args.get("manual")
                        section_id = args.get("section_id")
                        if manual and section_id:
                            citations.append({"manual": str(manual), "section_id": str(section_id)})
                elif event == "redirect":
                    raw_line = str(data.get("line", "1")).upper().lstrip("L")
                    try:
                        redirect_line = int(raw_line)
                    except ValueError:
                        redirect_line = 1
                    redirect_reason = data.get("reason")
                elif event == "done":
                    final_message_id = data.get("message_id")
                    final_content = data.get("content")
                    duration_ms = data.get("duration_ms")

            if final_content is None and redirect_line is None:
                raise ValueError("SSE stream closed without 'done' or 'redirect' event")

            return MLAnswer(
                message_id=final_message_id or "redirect",
                content=final_content or "",
                tool_calls=tool_calls,
                citations=citations,
                redirect_line=redirect_line,
                redirect_reason=redirect_reason,
                duration_ms=duration_ms,
            )
        except (ValueError, AIUnavailable) as exc:
            if not isinstance(exc, AIUnavailable):
                logger.warning(
                    "AI service unavailable during send_message (%s): %s (%s)",
                    f"ml-api/chat/{ml_chat_id}/message",
                    exc,
                    type(exc).__name__,
                )
                raise AIUnavailable(f"ml-api/chat/{ml_chat_id}/message") from exc
            raise

    async def delete_chat(self, ml_chat_id: str) -> None:
        """Delete chat in ML service (DELETE /ml-api/chat/{chat_id})."""
        try:
            async with asyncio.timeout(5.0):
                response = await self.http.delete(f"ml-api/chat/{ml_chat_id}", timeout=5.0)
                if response.status_code != 404:
                    response.raise_for_status()
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.warning("Failed to delete ML chat %s: %s", ml_chat_id, exc)

    async def upload_file(
        self, ml_chat_id: str, filename: str, content: bytes, content_type: str | None = None
    ) -> dict:
        """Upload a file or image to ML service (POST /ml-api/chat/{chat_id}/upload)."""
        endpoint = f"ml-api/chat/{ml_chat_id}/upload"
        try:
            async with asyncio.timeout(30.0):
                files = {"file": (filename, content, content_type or "application/octet-stream")}
                response = await self.http.post(endpoint, files=files, timeout=30.0)
                if response.status_code == 404:
                    raise KeyError(ml_chat_id)
                if response.status_code in (400, 409, 422):
                    try:
                        err_detail = response.json().get("detail", response.text)
                    except Exception:
                        err_detail = response.text
                    raise ValueError(err_detail)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Invalid upload response format")
                return data
        except (KeyError, ValueError):
            raise
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.warning("AI service unavailable during upload_file (%s): %s", endpoint, exc)
            raise AIUnavailable(endpoint) from exc

    async def list_files(self, ml_chat_id: str) -> list[dict]:
        """List pending files for a chat in ML service (GET /ml-api/chat/{chat_id}/files)."""
        endpoint = f"ml-api/chat/{ml_chat_id}/files"
        try:
            async with asyncio.timeout(10.0):
                response = await self.http.get(endpoint, timeout=10.0)
                if response.status_code == 404:
                    raise KeyError(ml_chat_id)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list):
                    raise ValueError("Invalid list_files response format")
                return data
        except KeyError:
            raise
        except (httpx.HTTPError, TimeoutError, ValueError) as exc:
            logger.warning("AI service unavailable during list_files (%s): %s", endpoint, exc)
            raise AIUnavailable(endpoint) from exc

    async def get_file(self, ml_chat_id: str, file_id: str) -> dict:
        """Get file metadata from ML service (GET /ml-api/chat/{chat_id}/files/{file_id})."""
        endpoint = f"ml-api/chat/{ml_chat_id}/files/{file_id}"
        try:
            async with asyncio.timeout(10.0):
                response = await self.http.get(endpoint, timeout=10.0)
                if response.status_code == 404:
                    raise KeyError(file_id)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Invalid get_file response format")
                return data
        except KeyError:
            raise
        except (httpx.HTTPError, TimeoutError, ValueError) as exc:
            logger.warning("AI service unavailable during get_file (%s): %s", endpoint, exc)
            raise AIUnavailable(endpoint) from exc

    async def delete_file(self, ml_chat_id: str, file_id: str) -> None:
        """Delete pending file in ML service (DELETE /ml-api/chat/{chat_id}/files/{file_id})."""
        endpoint = f"ml-api/chat/{ml_chat_id}/files/{file_id}"
        try:
            async with asyncio.timeout(10.0):
                response = await self.http.delete(endpoint, timeout=10.0)
                if response.status_code == 404:
                    raise KeyError(file_id)
                response.raise_for_status()
        except KeyError:
            raise
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.warning("AI service unavailable during delete_file (%s): %s", endpoint, exc)
            raise AIUnavailable(endpoint) from exc

    async def get_file_content(self, ml_chat_id: str, file_id: str) -> tuple[bytes, str, str | None]:
        """Get pending file content from ML service (GET /ml-api/chat/{chat_id}/files/{file_id}/content)."""
        endpoint = f"ml-api/chat/{ml_chat_id}/files/{file_id}/content"
        try:
            async with asyncio.timeout(20.0):
                response = await self.http.get(endpoint, timeout=20.0)
                if response.status_code == 404:
                    raise KeyError(file_id)
                response.raise_for_status()
                return (
                    response.content,
                    response.headers.get("content-type", "application/octet-stream"),
                    response.headers.get("content-disposition"),
                )
        except KeyError:
            raise
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.warning("AI service unavailable during get_file_content (%s): %s", endpoint, exc)
            raise AIUnavailable(endpoint) from exc

    async def get_attachment(self, file_id: str) -> tuple[bytes, str, str | None]:
        """Get permanent attachment content from ML service (GET /attachments/{file_id})."""
        endpoint = f"attachments/{file_id}"
        try:
            async with asyncio.timeout(20.0):
                response = await self.http.get(endpoint, timeout=20.0)
                if response.status_code == 404:
                    raise KeyError(file_id)
                response.raise_for_status()
                return (
                    response.content,
                    response.headers.get("content-type", "application/octet-stream"),
                    response.headers.get("content-disposition"),
                )
        except KeyError:
            raise
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.warning("AI service unavailable during get_attachment (%s): %s", endpoint, exc)
            raise AIUnavailable(endpoint) from exc

    async def route(self, *args, **kwargs) -> int | None:
        """Stub method for backward compatibility. Returns None until routing is implemented."""
        return None

    async def health(self) -> dict:
        try:
            async with asyncio.timeout(5):
                response = await self.http.get("health", timeout=5)
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError("Invalid health response")
                return result
        except (httpx.HTTPError, TimeoutError, ValueError) as exc:
            logger.warning("AI service health check failed: %s (%s)", exc, type(exc).__name__)
            raise AIUnavailable("health") from exc
