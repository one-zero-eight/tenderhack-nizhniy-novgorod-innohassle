"""Development-only AI contract stub simulating ML-service SSE endpoints."""

import asyncio
import json
import os
import secrets
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, Response, UploadFile
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
_CHAT_FILES: dict[str, list[dict]] = {}
_ATTACHMENTS: dict[str, dict] = {}


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
        "topic": None,
        "subtopic": None,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
        "avg_turn_seconds": None,
        "messages": [],
    }
    _CHATS[chat_id] = record
    return record


@app.get("/ml-api/chat/{chat_id}")
async def get_chat(chat_id: str):
    if chat_id not in _CHATS:
        raise HTTPException(404, "Чат не найден")
    return _CHATS[chat_id]


@app.post("/ml-api/chat/{chat_id}/upload", status_code=201)
async def upload_file(chat_id: str, file: Annotated[UploadFile, File(...)]):
    if chat_id not in _CHATS:
        raise HTTPException(404, "Чат не найден")
    chat = _CHATS[chat_id]
    if chat.get("closed_at") is not None:
        raise HTTPException(409, "Чат закрыт")
    data = await file.read(10 * 1024 * 1024 + 1)
    if not data:
        raise HTTPException(400, "Файл пуст")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "Файл слишком большой")

    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    is_img = ext in image_exts or (file.content_type and file.content_type.startswith("image/"))
    kind = "image" if is_img else "document"
    file_id = f"file-{uuid4().hex[:8]}"
    record = {
        "id": file_id,
        "chat_id": chat_id,
        "filename": file.filename or "file",
        "content_type": file.content_type or "application/octet-stream",
        "kind": kind,
        "size": len(data),
        "is_image": is_img,
        "created_at": datetime.now(UTC).isoformat(),
        "url": f"/attachments/{file_id}",
        "_data": data,
    }
    _CHAT_FILES.setdefault(chat_id, []).append(record)
    _ATTACHMENTS[file_id] = record
    return {k: v for k, v in record.items() if k != "_data"}


@app.get("/ml-api/chat/{chat_id}/files")
async def list_files(chat_id: str):
    if chat_id not in _CHATS:
        raise HTTPException(404, "Чат не найден")
    return [{k: v for k, v in f.items() if k != "_data"} for f in _CHAT_FILES.get(chat_id, [])]


@app.get("/ml-api/chat/{chat_id}/files/{file_id}")
async def get_file(chat_id: str, file_id: str):
    if chat_id not in _CHATS:
        raise HTTPException(404, "Чат не найден")
    files = _CHAT_FILES.get(chat_id, [])
    for f in files:
        if f["id"] == file_id:
            return {k: v for k, v in f.items() if k != "_data"}
    raise HTTPException(404, "Файл не найден")


@app.delete("/ml-api/chat/{chat_id}/files/{file_id}", status_code=204)
async def delete_file(chat_id: str, file_id: str):
    if chat_id not in _CHATS:
        raise HTTPException(404, "Чат не найден")
    files = _CHAT_FILES.get(chat_id, [])
    for i, f in enumerate(files):
        if f["id"] == file_id:
            files.pop(i)
            return None
    raise HTTPException(404, "Файл не найден")


@app.get("/ml-api/chat/{chat_id}/files/{file_id}/content")
async def get_file_content(chat_id: str, file_id: str):
    if chat_id not in _CHATS:
        raise HTTPException(404, "Чат не найден")
    for f in _CHAT_FILES.get(chat_id, []):
        if f["id"] == file_id:
            return Response(content=f["_data"], media_type=f["content_type"])
    raise HTTPException(404, "Файл не найден")


@app.get("/attachments/{file_id}")
async def get_attachment(file_id: str):
    if file_id not in _ATTACHMENTS:
        raise HTTPException(404, "Вложение не найдено")
    record = _ATTACHMENTS[file_id]
    return Response(
        content=record["_data"],
        media_type=record["content_type"],
        headers={"Content-Disposition": f'attachment; filename="{record["filename"]}"'},
    )


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

    # Pending attachments for this turn
    pending = _CHAT_FILES.pop(chat_id, [])
    user_attachments = [{k: v for k, v in f.items() if k != "_data"} for f in pending]

    if chat_id in _CHATS:
        _CHATS[chat_id]["messages"].append(
            {
                "id": f"msg-user-{len(_CHATS[chat_id]['messages']) + 1}",
                "role": "user",
                "content": payload.message,
                "tools": [],
                "attachments": user_attachments,
            }
        )
        _CHATS[chat_id]["messages"].append(
            {
                "id": msg_id,
                "role": "assistant",
                "content": content,
                "tools": [],
                "attachments": [],
                "duration_ms": 100,
            }
        )
        assistant_durations = [
            m["duration_ms"]
            for m in _CHATS[chat_id]["messages"]
            if m.get("role") == "assistant" and m.get("duration_ms") is not None
        ]
        if assistant_durations:
            _CHATS[chat_id]["avg_turn_seconds"] = round(sum(assistant_durations) / (len(assistant_durations) * 1000), 2)

    async def sse_generator():
        start_data = json.dumps({"message_id": msg_id})
        yield f"event: start\ndata: {start_data}\n\n"

        token_data = json.dumps({"delta": content, "content": content})
        yield f"event: token\ndata: {token_data}\n\n"

        done_data = json.dumps({"message_id": msg_id, "content": content, "duration_ms": 100})
        yield f"event: done\ndata: {done_data}\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@app.delete("/ml-api/chat/{chat_id}", status_code=204)
async def delete_chat(chat_id: str):
    _CHATS.pop(chat_id, None)
    files = _CHAT_FILES.pop(chat_id, [])
    for f in files:
        _ATTACHMENTS.pop(f["id"], None)
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


_HANDRULES: dict[str, dict] = {}


class HandRuleInPayload(BaseModel):
    user_message: str = Field(min_length=1, max_length=4000)
    instructions: str = Field(min_length=1, max_length=4000)


class HandRulePatchPayload(BaseModel):
    user_message: str | None = Field(default=None, min_length=1, max_length=4000)
    instructions: str | None = Field(default=None, min_length=1, max_length=4000)


@app.get("/ml-api/handrules")
async def list_handrules_stub(limit: int = 100):
    rules = list(_HANDRULES.values())
    rules.reverse()
    return rules[:limit]


@app.post("/ml-api/handrules", status_code=201)
async def create_handrule_stub(payload: HandRuleInPayload):
    rule_id = f"rule-{uuid4().hex[:8]}"
    now = datetime.now(UTC).isoformat()
    record = {
        "id": rule_id,
        "user_message": payload.user_message,
        "instructions": payload.instructions,
        "created_at": now,
        "updated_at": now,
    }
    _HANDRULES[rule_id] = record
    return record


@app.get("/ml-api/handrules/search")
async def search_handrules_stub(q: str, k: int = 3):
    matches = []
    q_lower = q.lower()
    for rule in _HANDRULES.values():
        if any(word in rule["user_message"].lower() for word in q_lower.split()):
            matches.append(rule)
    if not matches:
        matches = list(_HANDRULES.values())
    return matches[:k]


@app.get("/ml-api/handrules/{rule_id}")
async def get_handrule_stub(rule_id: str):
    if rule_id not in _HANDRULES:
        raise HTTPException(404, "Правило не найдено")
    return _HANDRULES[rule_id]


@app.patch("/ml-api/handrules/{rule_id}")
async def update_handrule_stub(rule_id: str, payload: HandRulePatchPayload):
    if rule_id not in _HANDRULES:
        raise HTTPException(404, "Правило не найдено")
    rule = _HANDRULES[rule_id]
    if payload.user_message is not None:
        rule["user_message"] = payload.user_message
    if payload.instructions is not None:
        rule["instructions"] = payload.instructions
    rule["updated_at"] = datetime.now(UTC).isoformat()
    return rule


@app.delete("/ml-api/handrules/{rule_id}", status_code=204)
async def delete_handrule_stub(rule_id: str):
    if rule_id not in _HANDRULES:
        raise HTTPException(404, "Правило не найдено")
    _HANDRULES.pop(rule_id)
    return Response(status_code=204)
