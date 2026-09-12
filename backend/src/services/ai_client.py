import asyncio
from typing import Literal, Self
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.config_schema import ApiSettings


class AIUnavailable(Exception):
    """An unavailable endpoint or a response that violates the agreed AI contract."""


class AIResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    section: str | None = Field(default=None, max_length=500)


class AnswerResult(AIResponse):
    outcome: Literal["answered", "no_answer"]
    answer: str | None = Field(max_length=16000)
    sources: list[Source] = Field(max_length=20)

    @model_validator(mode="after")
    def check_answer(self) -> Self:
        if self.outcome == "answered" and (not self.answer or not self.answer.strip()):
            raise ValueError("An answered result needs non-empty text")
        if self.outcome == "no_answer" and (self.answer is not None or self.sources):
            raise ValueError("A no-answer result cannot contain an answer or sources")
        return self


class RoutingResult(AIResponse):
    recommended_support_line_id: int = Field(strict=True, ge=1, le=3)


class AIClient:
    def __init__(self, http: httpx.AsyncClient, settings: ApiSettings):
        self.http = http
        self.settings = settings

    async def _post[T: AIResponse](self, endpoint: str, payload: dict, model: type[T], timeout: float) -> T:
        try:
            # An outer deadline also bounds slow chunked responses, not just socket inactivity.
            async with asyncio.timeout(timeout):
                response = await self.http.post(endpoint, json=payload, timeout=timeout)
                response.raise_for_status()
                result = model.model_validate(response.json())
                if str(result.request_id) != payload["request_id"]:
                    raise ValueError("Mismatched AI request ID")
                return result
        except (httpx.HTTPError, TimeoutError, ValidationError, ValueError) as exc:
            raise AIUnavailable(endpoint) from exc

    async def answer(self, request_id: UUID, message: str, history: list[dict]) -> AnswerResult:
        return await self._post(
            "v1/answer",
            {
                "request_id": str(request_id),
                "message": message,
                "history": history,
            },
            AnswerResult,
            self.settings.ai_answer_timeout,
        )

    async def route(self, request_id: UUID, message: str, history: list[dict], lines: list[dict]) -> int:
        result = await self._post(
            "v1/route",
            {
                "request_id": str(request_id),
                "message": message,
                "history": history,
                "support_lines": lines,
            },
            RoutingResult,
            self.settings.ai_routing_timeout,
        )
        if result.recommended_support_line_id not in {line["id"] for line in lines}:
            raise AIUnavailable("Unknown support line")
        return result.recommended_support_line_id

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
