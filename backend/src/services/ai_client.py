import asyncio
import json
import logging

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
    redirect_line: int | None = None
    redirect_reason: str | None = None


class AIClient:
    def __init__(self, http: httpx.AsyncClient, settings: ApiSettings):
        self.http = http
        self.settings = settings

    async def create_chat(self, system_prompt: str | None = None) -> str:
        """Create a chat session in the ML service (POST /ml-api/chat) and return its string ID."""
        try:
            async with asyncio.timeout(10.0):
                payload = {"system_prompt": system_prompt} if system_prompt else None
                response = await self.http.post("ml-api/chat", json=payload, timeout=10.0)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or "id" not in data or not isinstance(data["id"], str):
                    raise ValueError("Invalid chat creation response")
                return data["id"]
        except (httpx.HTTPError, TimeoutError, ValidationError, ValueError) as exc:
            logger.warning("AI service unavailable during create_chat: %s (%s)", exc, type(exc).__name__)
            raise AIUnavailable("ml-api/chat") from exc

    async def send_message(self, ml_chat_id: str, message: str) -> MLAnswer:
        """Send a message to ML service agent (POST /ml-api/chat/{chat_id}/message) via SSE and consume response."""
        endpoint = f"ml-api/chat/{ml_chat_id}/message"
        try:
            async with asyncio.timeout(self.settings.ai_answer_timeout):
                async with aconnect_sse(
                    self.http, "POST", endpoint, json={"message": message}
                ) as event_source:
                    final_content = None
                    final_message_id = None
                    tool_calls = []
                    citations = []
                    redirect_line = None
                    redirect_reason = None

                    async for sse in event_source.aiter_sse():
                        if sse.event == "error":
                            err_data = json.loads(sse.data) if sse.data else {}
                            msg = err_data.get("message", "SSE stream error")
                            raise ValueError(f"ML service error: {msg}")
                        elif sse.event == "tool_call":
                            call_data = json.loads(sse.data) if sse.data else {}
                            name = call_data.get("name", "")
                            args = call_data.get("arguments", {})
                            tool_calls.append(call_data)
                            if name == "open" and isinstance(args, dict):
                                manual = args.get("manual")
                                section_id = args.get("section_id")
                                if manual and section_id:
                                    citations.append({"manual": str(manual), "section_id": str(section_id)})
                        elif sse.event == "redirect":
                            redir_data = json.loads(sse.data) if sse.data else {}
                            raw_line = str(redir_data.get("line", "1")).upper().lstrip("L")
                            try:
                                redirect_line = int(raw_line)
                            except ValueError:
                                redirect_line = 1
                            redirect_reason = redir_data.get("reason")
                        elif sse.event == "done":
                            done_data = json.loads(sse.data) if sse.data else {}
                            final_message_id = done_data.get("message_id")
                            final_content = done_data.get("content")

                    if final_content is None and redirect_line is None:
                        raise ValueError("SSE stream closed without 'done' or 'redirect' event")

                    return MLAnswer(
                        message_id=final_message_id or "redirect",
                        content=final_content or "",
                        tool_calls=tool_calls,
                        citations=citations,
                        redirect_line=redirect_line,
                        redirect_reason=redirect_reason,
                    )
        except (httpx.HTTPError, TimeoutError, ValidationError, ValueError, json.JSONDecodeError, SSEError) as exc:
            logger.warning("AI service unavailable during send_message (%s): %s (%s)", endpoint, exc, type(exc).__name__)
            raise AIUnavailable(endpoint) from exc

    async def delete_chat(self, ml_chat_id: str) -> None:
        """Delete chat in ML service (DELETE /ml-api/chat/{chat_id})."""
        try:
            async with asyncio.timeout(5.0):
                response = await self.http.delete(f"ml-api/chat/{ml_chat_id}", timeout=5.0)
                if response.status_code != 404:
                    response.raise_for_status()
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.warning("Failed to delete ML chat %s: %s", ml_chat_id, exc)

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
