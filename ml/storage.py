"""SQLite-хранилище чатов: чаты, сообщения и вызовы инструментов.

Одна таблица на сущность, WAL + foreign keys. Все операции синхронные и дешёвые,
поэтому вызываются прямо из async-хендлеров (SQLite без сети — блокировка на микросекунды).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_DB_PATH = HERE / "chats.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT 'Новый чат',
    system_prompt TEXT,
    redirect_line TEXT,
    redirect_reason TEXT,
    closed_at     TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chats_updated ON chats (updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    chat_id     TEXT NOT NULL REFERENCES chats (id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages (chat_id, position);

CREATE TABLE IF NOT EXISTS tool_calls (
    id          TEXT PRIMARY KEY,
    message_id  TEXT NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    name        TEXT NOT NULL,
    kwargs      TEXT NOT NULL DEFAULT '{}',
    output      TEXT,
    error       INTEGER NOT NULL DEFAULT 0,
    started_at  TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_message ON tool_calls (message_id, position);
"""


@dataclass
class ToolCallRecord:
    id: str
    name: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    output: str | None = None
    error: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kwargs": self.kwargs,
            "output": self.output,
            "error": self.error,
        }


@dataclass
class MessageRecord:
    id: str
    role: str
    content: str
    tools: list[ToolCallRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "tools": [tool.to_dict() for tool in self.tools],
        }


@dataclass
class ChatRecord:
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    system_prompt: str | None = None
    redirect_line: str | None = None
    redirect_reason: str | None = None
    closed_at: datetime | None = None
    messages: list[MessageRecord] = field(default_factory=list)

    @property
    def is_closed(self) -> bool:
        return self.closed_at is not None

    def to_dict(self, *, with_messages: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "system_prompt": self.system_prompt,
            "redirect_line": self.redirect_line,
            "redirect_reason": self.redirect_reason,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
        if with_messages:
            payload["messages"] = [message.to_dict() for message in self.messages]
        return payload


def _now() -> str:
    return datetime.now().isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


class ChatStorage:
    """CRUD по чатам. Один экземпляр на процесс, соединение — только для этого потока."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ chats

    def create_chat(self, title: str = "Новый чат", system_prompt: str | None = None) -> ChatRecord:
        now = _now()
        chat_id = _new_id()
        self._conn.execute(
            "INSERT INTO chats (id, title, system_prompt, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (chat_id, title, system_prompt, now, now),
        )
        self._conn.commit()
        return ChatRecord(
            id=chat_id,
            title=title,
            system_prompt=system_prompt,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )

    def _row_to_chat(self, row: sqlite3.Row, *, with_messages: bool) -> ChatRecord:
        closed_at = row["closed_at"]
        return ChatRecord(
            id=row["id"],
            title=row["title"],
            system_prompt=row["system_prompt"],
            redirect_line=row["redirect_line"],
            redirect_reason=row["redirect_reason"],
            closed_at=datetime.fromisoformat(closed_at) if closed_at else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            messages=self.list_messages(row["id"]) if with_messages else [],
        )

    def redirect_chat(self, chat_id: str, line: str, reason: str | None = None) -> None:
        """Переводит чат на линию поддержки и завершает его."""
        now = _now()
        self._conn.execute(
            """UPDATE chats SET redirect_line = ?, redirect_reason = ?, closed_at = ?,
               updated_at = ? WHERE id = ?""",
            (line, reason, now, now, chat_id),
        )
        self._conn.commit()

    def get_chat(self, chat_id: str) -> ChatRecord | None:
        row = self._conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
        return None if row is None else self._row_to_chat(row, with_messages=True)

    def list_chats(self, limit: int = 200) -> list[ChatRecord]:
        rows = self._conn.execute(
            "SELECT * FROM chats ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_chat(row, with_messages=False) for row in rows]

    def rename_chat(self, chat_id: str, title: str) -> None:
        self._conn.execute(
            "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?", (title, _now(), chat_id)
        )
        self._conn.commit()

    def touch_chat(self, chat_id: str) -> None:
        self._conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (_now(), chat_id))
        self._conn.commit()

    def delete_chat(self, chat_id: str) -> None:
        self._conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        self._conn.commit()

    # --------------------------------------------------------------- messages

    def list_messages(self, chat_id: str) -> list[MessageRecord]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY position ASC", (chat_id,)
        ).fetchall()
        messages = [
            MessageRecord(id=row["id"], role=row["role"], content=row["content"]) for row in rows
        ]
        if not messages:
            return messages
        tools = self._list_tools([message.id for message in messages])
        for message in messages:
            message.tools = tools.get(message.id, [])
        return messages

    def _list_tools(self, message_ids: list[str]) -> dict[str, list[ToolCallRecord]]:
        placeholders = ",".join("?" for _ in message_ids)
        rows = self._conn.execute(
            f"SELECT * FROM tool_calls WHERE message_id IN ({placeholders}) ORDER BY position ASC",
            message_ids,
        ).fetchall()
        grouped: dict[str, list[ToolCallRecord]] = {}
        for row in rows:
            grouped.setdefault(row["message_id"], []).append(
                ToolCallRecord(
                    id=row["id"],
                    name=row["name"],
                    kwargs=json.loads(row["kwargs"] or "{}"),
                    output=row["output"],
                    error=bool(row["error"]),
                )
            )
        return grouped

    def _next_position(self, chat_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS pos FROM messages WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        return int(row["pos"])

    def add_message(self, chat_id: str, role: str, content: str = "") -> MessageRecord:
        message = MessageRecord(id=_new_id(), role=role, content=content)
        self._conn.execute(
            "INSERT INTO messages (id, chat_id, role, content, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (message.id, chat_id, role, content, self._next_position(chat_id), _now()),
        )
        self._conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (_now(), chat_id))
        self._conn.commit()
        return message

    def latest_user_text(self, chat_id: str, before_message_id: str) -> str:
        """Текст последнего пользовательского сообщения перед указанным assistant-сообщением."""
        row = self._conn.execute(
            """SELECT content FROM messages
               WHERE chat_id = ? AND role = 'user'
                 AND position < (SELECT position FROM messages WHERE id = ?)
               ORDER BY position DESC LIMIT 1""",
            (chat_id, before_message_id),
        ).fetchone()
        return row["content"] if row else ""

    def update_message(self, message_id: str, content: str) -> None:
        self._conn.execute("UPDATE messages SET content = ? WHERE id = ?", (content, message_id))
        self._conn.commit()

    def get_message(self, message_id: str) -> MessageRecord | None:
        row = self._conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            return None
        message = MessageRecord(id=row["id"], role=row["role"], content=row["content"])
        message.tools = self._list_tools([message.id]).get(message.id, [])
        return message

    def clear_messages(self, chat_id: str) -> None:
        self._conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        self._conn.commit()

    # -------------------------------------------------------------- tool calls

    def _next_tool_position(self, message_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS pos FROM tool_calls WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        return int(row["pos"])

    def add_tool_call(
        self, message_id: str, tool_id: str, name: str, kwargs: dict[str, Any]
    ) -> ToolCallRecord:
        record = ToolCallRecord(id=tool_id or _new_id(), name=name, kwargs=kwargs)
        self._conn.execute(
            """INSERT OR REPLACE INTO tool_calls
               (id, message_id, position, name, kwargs, output, error, started_at)
               VALUES (?, ?, ?, ?, ?, NULL, 0, ?)""",
            (
                record.id,
                message_id,
                self._next_tool_position(message_id),
                name,
                json.dumps(kwargs, ensure_ascii=False, default=str),
                _now(),
            ),
        )
        self._conn.commit()
        return record

    def finish_tool_call(self, message_id: str, tool_id: str, output: str, error: bool) -> None:
        self._conn.execute(
            """UPDATE tool_calls SET output = ?, error = ?, finished_at = ?
               WHERE message_id = ? AND id = ?""",
            (output, int(error), _now(), message_id, tool_id),
        )
        self._conn.commit()


_storage: ChatStorage | None = None


def get_storage(path: Path | str | None = None) -> ChatStorage:
    global _storage
    if _storage is None:
        import os

        resolved = path or os.getenv("CHAT_DB_PATH") or DEFAULT_DB_PATH
        _storage = ChatStorage(resolved)
    return _storage
