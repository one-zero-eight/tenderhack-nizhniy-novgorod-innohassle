"""Development-only AI contract stub. Markers simulate outcomes; this is not an AI implementation."""

import asyncio
import os
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


async def authenticate(authorization: Annotated[str | None, Header()] = None):
    token = os.environ.get("API_SETTINGS__AI_SERVICE_TOKEN")
    if token and not secrets.compare_digest(authorization or "", f"Bearer {token}"):
        raise HTTPException(401, "Invalid internal service token")


app = FastAPI(title="Development AI stub", dependencies=[Depends(authenticate)])


class Input(BaseModel):
    request_id: UUID
    message: str = Field(min_length=1, max_length=4000)
    history: list[dict] = Field(default_factory=list, max_length=20)
    support_lines: list[dict] = Field(default_factory=list, max_length=3)


@app.get("/health")
async def health():
    return {
        "status": "ready",
        "mode": "stub",
        "components": {
            "moderation": "ready",
            "answering": "ready",
            "routing": "ready",
        },
    }


@app.post("/v1/moderate")
async def moderate(payload: Input):
    if "[moderation-slow]" in payload.message:
        await asyncio.sleep(60)
    if "[moderation-error]" in payload.message:
        raise HTTPException(503, "Simulated moderation outage")
    blocked = "[block]" in payload.message
    return {
        "request_id": payload.request_id,
        "decision": "block" if blocked else "allow",
        "reason": "profanity" if blocked else None,
    }


@app.post("/v1/answer")
async def answer(payload: Input):
    if "[slow]" in payload.message:
        await asyncio.sleep(60)
    if "[answer-error]" in payload.message:
        raise HTTPException(503, "Simulated answer outage")
    unknown = any(
        marker in payload.message for marker in ("[unknown]", "[route-error]", "[route-invalid]", "[route-slow]")
    )
    return {
        "request_id": payload.request_id,
        "outcome": "no_answer" if unknown else "answered",
        "answer": None if unknown else "Демонстрационный ответ. Подключите AI-сервис для ответа по базе знаний.",
        "sources": [],
    }


@app.post("/v1/route")
async def route(payload: Input):
    if "[route-slow]" in payload.message:
        await asyncio.sleep(60)
    if "[route-error]" in payload.message:
        raise HTTPException(503, "Simulated routing outage")
    line_id = next((line for line in (1, 2, 3) if f"[line={line}]" in payload.message), 1)
    return {
        "request_id": payload.request_id,
        "recommended_support_line_id": 4 if "[route-invalid]" in payload.message else line_id,
    }
