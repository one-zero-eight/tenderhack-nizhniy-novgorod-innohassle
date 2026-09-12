import asyncio
import json
import logging

import httpx
from httpx_sse import aconnect_sse
from pydantic import BaseModel, ConfigDict, ValidationError

from src.config_schema import ApiSettings

logger = logging.getLogger(__name__)


class AIUnavailable(Exception):
    """An unavailable endpoint or a response that violates the agreed AI contract."""


class MLAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message_id: str
    content: str


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

                    async for sse in event_source.aiter_sse():
                        if sse.event == "error":
                            err_data = json.loads(sse.data) if sse.data else {}
                            msg = err_data.get("message", "SSE stream error")
                            raise ValueError(f"ML service error: {msg}")
                        elif sse.event == "done":
                            done_data = json.loads(sse.data) if sse.data else {}
                            final_message_id = done_data.get("message_id")
                            final_content = done_data.get("content")

                    if final_content is None or final_message_id is None:
                        raise ValueError("SSE stream closed without 'done' event")

                    return MLAnswer(message_id=final_message_id, content=final_content)
        except (httpx.HTTPError, TimeoutError, ValidationError, ValueError, json.JSONDecodeError) as exc:
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
            raise AIUnavailable("health") from exc
