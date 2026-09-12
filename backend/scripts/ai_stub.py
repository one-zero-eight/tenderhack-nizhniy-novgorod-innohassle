"""Development-only AI contract stub simulating ML-service SSE endpoints."""

import asyncio
import json
import os
import secrets
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


async def authenticate(authorization: Annotated[str | None, Header()] = None):
    token = os.environ.get("API_SETTINGS__AI_SERVICE_TOKEN")
    if token and not secrets.compare_digest(authorization or "", f"Bearer {token}"):
        raise HTTPException(401, "Invalid internal service token")


app = FastAPI(title="Development AI stub", dependencies=[Depends(authenticate)])


class ChatIn(BaseModel):
    system_prompt: str | None = Field(default=None, max_length=8000)


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


@app.get("/health")
async def health():
    return {
        "status": "ready",
        "mode": "stub",
        "components": {
            "answering": "ready",
        },
    }


_CHATS: dict[str, dict] = {}


@app.post("/ml-api/chat", status_code=201)
async def create_chat(payload: ChatIn | None = None):
    chat_id = f"stub-chat-{uuid4().hex[:8]}"
    now = datetime.now(UTC).isoformat()
    record = {
        "id": chat_id,
        "title": "Новый чат",
        "system_prompt": payload.system_prompt if payload else None,
        "redirect_line": None,
        "redirect_reason": None,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }
    _CHATS[chat_id] = record
    return record


@app.get("/ml-api/chat/{chat_id}")
async def get_chat(chat_id: str):
    if chat_id not in _CHATS:
        raise HTTPException(404, "Чат не найден")
    return _CHATS[chat_id]


@app.post("/ml-api/chat/{chat_id}/message")
async def send_message(chat_id: str, payload: MessageIn):
    if "[slow]" in payload.message:
        await asyncio.sleep(60)

    if "[answer-error]" in payload.message:
        async def error_generator():
            err_data = json.dumps({"message": "Simulated answer outage"})
            yield f"event: error\ndata: {err_data}\n\n"
        return StreamingResponse(error_generator(), media_type="text/event-stream")

    msg_id = f"msg-{uuid4().hex[:8]}"
    content = "Демонстрационный ответ. Подключите AI-сервис для ответа по базе знаний."

    if chat_id in _CHATS:
        _CHATS[chat_id]["messages"].append({
            "id": f"msg-user-{len(_CHATS[chat_id]['messages']) + 1}",
            "role": "user",
            "content": payload.message,
            "tools": [],
        })
        _CHATS[chat_id]["messages"].append({
            "id": msg_id,
            "role": "assistant",
            "content": content,
            "tools": [],
        })

    async def sse_generator():
        start_data = json.dumps({"message_id": msg_id})
        yield f"event: start\ndata: {start_data}\n\n"

        token_data = json.dumps({"delta": content, "content": content})
        yield f"event: token\ndata: {token_data}\n\n"

        done_data = json.dumps({"message_id": msg_id, "content": content})
        yield f"event: done\ndata: {done_data}\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@app.delete("/ml-api/chat/{chat_id}", status_code=204)
async def delete_chat(chat_id: str):
    _CHATS.pop(chat_id, None)
    return None


@app.get("/ml-api/knowledge-base")
async def list_manuals():
    return [
        {
            "slug": "instrukciya-po-sozdaniyu-oferty-i-ste",
            "title": "Инструкция по созданию оферты и СТЕ",
            "sections": 5,
            "url": "/knowledge-base/instrukciya-po-sozdaniyu-oferty-i-ste",
        }
    ]


@app.get("/ml-api/knowledge-base/{slug}")
async def get_manual_structure(slug: str):
    if slug == "not-found":
        raise HTTPException(404, "Мануал не найден")
    return {
        "slug": slug,
        "title": "Инструкция по созданию оферты и СТЕ",
        "sections": [
            {
                "id": "root",
                "title": "Полный текст",
                "depth": 0,
                "ancestors": [],
                "children": ["1"],
            },
            {
                "id": "1",
                "title": "Общие положения",
                "depth": 1,
                "ancestors": ["root"],
                "children": [],
            },
        ],
    }


@app.get("/ml-api/knowledge-base/{slug}/{section_id}")
async def get_manual_section(slug: str, section_id: str):
    if slug == "not-found" or section_id == "not-found":
        raise HTTPException(404, "Раздел не найден")
    return {
        "id": section_id,
        "title": "Общие положения",
        "content_md": "# Общие положения\n\nТекст раздела инструкции...",
        "breadcrumbs": [{"id": "root", "title": "Инструкция"}, {"id": section_id, "title": "Общие положения"}],
        "prev": None,
        "next": None,
        "parent": "root",
        "manual": {"slug": slug, "title": "Инструкция по созданию оферты и СТЕ"},
    }
