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

# Заголовок нового чата. Пока он такой, при первом сообщении его заменит
# сгенерированное моделью название (см. chat.prepare_turn).
DEFAULT_CHAT_TITLE = "Новый чат"

# Допустимые оценки чата (chats.rating). Одна оценка на чат, к сообщениям не привязана.
RATINGS = ("positive", "negative")

# Ограничение на длину имени пользователя (кука / параметр username в API).
USERNAME_MAX_LEN = 64


def clean_username(raw: str | None) -> str | None:
    """Имя пользователя: схлопываем пробелы, режем длину.

    Возвращает None для пустого/невалидного значения — так «username не указан»
    и «username пуст» обрабатываются одинаково (вернуть все чаты).
    """
    name = " ".join((raw or "").split()).strip()[:USERNAME_MAX_LEN]
    return name or None

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT 'Новый чат',
    system_prompt TEXT,
    redirect_line TEXT,
    redirect_reason TEXT,
    topic         TEXT,
    subtopic      TEXT,
    rating        TEXT,
    rating_reason TEXT,
    rated_at      TEXT,
    owner         TEXT,
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
    display_content TEXT,
    attachments TEXT,
    -- Сущности, о которых речь в сообщении (контракт, закупка и т.п.), JSON-массивом.
    -- Приходят из REST API и уходят агенту в контекст (см. entities_context).
    entities    TEXT,
    duration_ms INTEGER,
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

-- Вызовы инструментов выбора сущности (contract/procurement/offer): под сообщением
-- ассистента рисуются inline-кнопки. Строки живут в БД, чтобы кнопки переживали
-- перезагрузку страницы. entity_kind — 'contract' | 'procurement' | 'offer',
-- payload — JSON со списком вариантов (id, label, text).
CREATE TABLE IF NOT EXISTS entity_choices (
    id          TEXT PRIMARY KEY,
    message_id  TEXT NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    entity_kind TEXT NOT NULL,
    payload     TEXT NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entity_choices_message ON entity_choices (message_id, created_at);

-- Пользователи публичной части (страница /). Паролей нет: username из куки —
-- только для идентификации. Для компаний (см. companies.py) username — это ИНН,
-- а is_authorized=1; у гостей флаг 0. role заполняется только у компаний.
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    role          TEXT CHECK (role IN ('supplier', 'customer')),
    is_authorized INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Вложения чата: файлы и картинки, загруженные до отправки сообщения.
-- Дублирует migrations/001_chat_files.sql, чтобы новая база сразу была полной.
-- kind = 'image'    -> data = байты картинки, text = NULL.
-- kind = 'document' -> text = markdown из docling (без OCR и картинок), data = NULL.
CREATE TABLE IF NOT EXISTS chat_files (
    id           TEXT PRIMARY KEY,
    chat_id      TEXT NOT NULL REFERENCES chats (id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    kind         TEXT NOT NULL CHECK (kind IN ('image', 'document')),
    size         INTEGER NOT NULL,
    text         TEXT,
    data         BLOB,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_files_chat ON chat_files (chat_id, created_at);

-- Правила-подсказки для агента (handrules): пара «вопрос пользователя → как отвечать».
-- Перед каждым ходом по вопросу пользователя ищутся самые близкие правила (см. handrules.py)
-- и их instructions уезжают в системный промпт этого хода.
CREATE TABLE IF NOT EXISTS handrules (
    id            TEXT PRIMARY KEY,
    user_message  TEXT NOT NULL,
    instructions  TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_handrules_updated ON handrules (updated_at DESC);

-- AI-сводки по темам статистики (см. summaries.py). signature — отпечаток
-- отзывов темы: по нему фоновая задача понимает, что сводку пора пересчитать,
-- и не дёргает LLM на каждый проход.
CREATE TABLE IF NOT EXISTS topic_summaries (
    topic      TEXT PRIMARY KEY,
    summary    TEXT NOT NULL,
    signature  TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
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
class EntityChoiceRecord:
    """Выбор сущности под сообщением: inline-кнопки контракта/закупки/предложения.

    entity_kind: 'contract' | 'procurement' | 'offer'.
    options: список {id, label, text} — label для кнопки, text уйдёт в чат
    от имени пользователя, когда он нажмёт кнопку.
    """

    message_id: str
    entity_kind: str
    options: list[dict[str, str]] = field(default_factory=list)
    # True — пользователь уже выбрал вариант: кнопки больше не показываем.
    used: bool = False


@dataclass
class MessageRecord:
    id: str
    role: str
    content: str
    # Текст, который видит пользователь, если он отличается от content.
    # Для выбора сущности content — служебная строка для агента
    # («Пользователь выбрал контракт: <id>»), а display_content — подпись
    # с кнопки. None — показываем content как есть.
    display_content: str | None = None
    tools: list[ToolCallRecord] = field(default_factory=list)
    # Вложения, отправленные вместе с сообщением: оригиналы лежат в attachments/<id>.
    attachments: list[dict[str, Any]] = field(default_factory=list)
    # Сущности, о которых речь в сообщении (контракт, закупка, предложение).
    # Приходят из REST API и целиком идут агенту в контекст (см. entities_context),
    # в самом тексте сообщения остаётся только @alias. В UI не рендерятся.
    entities: list[dict[str, Any]] = field(default_factory=list)
    # Сколько агент генерировал этот ответ, в миллисекундах (только у assistant).
    # Считается от старта хода до последнего токена, включая вызовы инструментов.
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "display_content": self.display_content,
            "tools": [tool.to_dict() for tool in self.tools],
            "attachments": list(self.attachments),
            "entities": list(self.entities),
            "duration_ms": self.duration_ms,
        }


@dataclass
class UserRecord:
    """Пользователь публичной части: имя из куки плюс признак компании.

    is_authorized=False — гость: он назвал только имя, компания неизвестна.
    is_authorized=True — вход по компании: username равен её ИНН, role заполнен
    ('supplier' — поставщик, 'customer' — заказчик), а реквизиты берутся из
    companies.get_company(username).
    Сюда же пишется 'legacy' — владелец чатов, созданных до появления /.
    """

    username: str
    role: str | None = None
    is_authorized: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "role": self.role,
            "is_authorized": self.is_authorized,
        }


@dataclass
class HandRuleRecord:
    """Правило-подсказка агента: на какой вопрос как отвечать.

    user_message — пример вопроса пользователя (по нему идёт поиск),
    instructions — что агенту делать/не делать в таком случае.
    """

    id: str
    user_message: str
    instructions: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_message": self.user_message,
            "instructions": self.instructions,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class TopicSummaryRecord:
    """AI-сводка темы статистики: готовый текст плюс отпечаток отзывов.

    signature хранится рядом, чтобы фоновая задача (summaries.py) сравнивала
    текущее состояние отзывов с тем, по которому сводка была построена.
    """

    topic: str
    summary: str
    signature: str = ""
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "summary": self.summary,
            "signature": self.signature,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
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
    topic: str | None = None
    subtopic: str | None = None
    owner: str | None = None
    closed_at: datetime | None = None
    # Оценка чата пользователем: одна на чат, к сообщениям не привязана.
    # rating: None | 'positive' | 'negative'; rating_reason — выбранная причина
    # (или 'Позови оператора' для этого сценария), только при negative.
    rating: str | None = None
    rating_reason: str | None = None
    rated_at: datetime | None = None
    messages: list[MessageRecord] = field(default_factory=list)
    # Время ответа агента в секундах: для чата — по его первому ответу,
    # для темы/подтемы — среднее по чатам (см. ChatStorage.average_turn_seconds
    # и stats._average). Заполняется списками чатов; None — не было измеренных ответов.
    avg_turn_seconds: float | None = None
    # Сколько сообщений в чате (см. ChatStorage.message_counts). Заполняется списками
    # чатов; 0 — пустой чат (заготовка «Новый чат»), такие в статистику не идут.
    message_count: int = 0

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
            "topic": self.topic,
            "subtopic": self.subtopic,
            "rating": self.rating,
            "rating_reason": self.rating_reason,
            "rated_at": self.rated_at.isoformat() if self.rated_at else None,
            "owner": self.owner,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "avg_turn_seconds": self.avg_turn_seconds,
            "message_count": self.message_count,
        }
        if with_messages:
            payload["messages"] = [message.to_dict() for message in self.messages]
        return payload


def _now() -> str:
    return datetime.now().isoformat()


def _load_attachments(row: sqlite3.Row) -> list[dict[str, Any]]:
    """Вложения сообщения из JSON-колонки. Терпимо к старым строкам (колонки нет)."""
    return _load_json_list(row, "attachments")


def _load_json_list(row: sqlite3.Row, column: str) -> list[dict[str, Any]]:
    """JSON-массив из колонки. Нет колонки/пусто/битый JSON — пустой список."""
    if column not in row.keys():
        return []
    raw = row[column]
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return loaded if isinstance(loaded, list) else []


def _load_entities(row: sqlite3.Row) -> list[dict[str, Any]]:
    """Сущности сообщения (контракт/закупка/...), пришедшие из REST API."""
    return _load_json_list(row, "entities")


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
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Досыпает колонки, которых нет в базе, созданной до их появления.

        Миграции лежат в migrations/*.sql и применяются вручную; здесь только
        идемпотентная страховка, чтобы код не падал на старой базе.
        """
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(messages)")}
        if "attachments" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN attachments TEXT")
        if "duration_ms" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN duration_ms INTEGER")
        if "display_content" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN display_content TEXT")
        if "entities" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN entities TEXT")

        chat_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(chats)")}
        if "rating" not in chat_columns:
            self._conn.execute("ALTER TABLE chats ADD COLUMN rating TEXT")
        if "rating_reason" not in chat_columns:
            self._conn.execute("ALTER TABLE chats ADD COLUMN rating_reason TEXT")
        if "rated_at" not in chat_columns:
            self._conn.execute("ALTER TABLE chats ADD COLUMN rated_at TEXT")

        choice_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(entity_choices)")}
        if "used" not in choice_columns:
            self._conn.execute("ALTER TABLE entity_choices ADD COLUMN used INTEGER NOT NULL DEFAULT 0")

        user_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(users)")}
        if "is_authorized" not in user_columns:
            self._conn.execute(
                "ALTER TABLE users ADD COLUMN is_authorized INTEGER NOT NULL DEFAULT 0"
            )

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ chats

    def create_chat(
        self,
        title: str = DEFAULT_CHAT_TITLE,
        system_prompt: str | None = None,
        owner: str | None = None,
    ) -> ChatRecord:
        now = _now()
        chat_id = _new_id()
        self._conn.execute(
            "INSERT INTO chats (id, title, system_prompt, owner, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, title, system_prompt, owner, now, now),
        )
        self._conn.commit()
        return ChatRecord(
            id=chat_id,
            title=title,
            system_prompt=system_prompt,
            owner=owner,
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
            topic=row["topic"],
            subtopic=row["subtopic"],
            rating=row["rating"],
            rating_reason=row["rating_reason"],
            rated_at=datetime.fromisoformat(row["rated_at"]) if row["rated_at"] else None,
            owner=row["owner"],
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

    def list_chats(self, limit: int = 200, owner: str | None = None) -> list[ChatRecord]:
        """Чаты по убыванию активности. owner=None — все (для /admin).

        В каждый чат дописываются среднее время хода и число сообщений (два
        запроса на весь список, а не N). Потребители полагаются на них: сайдбар
        админки показывает время, статистика отсеивает пустые чаты.
        """
        if owner is None:
            rows = self._conn.execute(
                "SELECT * FROM chats ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM chats WHERE owner = ? ORDER BY updated_at DESC LIMIT ?",
                (owner, limit),
            ).fetchall()
        records = [self._row_to_chat(row, with_messages=False) for row in rows]
        averages = self.average_turn_seconds()
        counts = self.message_counts()
        for record in records:
            record.avg_turn_seconds = averages.get(record.id)
            record.message_count = counts.get(record.id, 0)
        return records

    def average_turn_seconds(self) -> dict[str, float]:
        """Время ответа агента по каждому чату, в секундах — только по первому ответу.

        Берём `duration_ms` самого раннего ответа ассистента (минимальная позиция
        среди измеренных). Именно первый ответ показывает, как быстро поддержка
        отреагировала на обращение; последующие ходы — это уже уточнения, и они
        только размывали бы метрику. Чаты без измеренных ответов в словарь не попадают.
        Один запрос на весь список — иначе сайдбар админки делал бы N запросов.
        """
        rows = self._conn.execute(
            """SELECT m.chat_id AS chat_id, m.duration_ms AS first_ms
               FROM messages m
               JOIN (
                   SELECT chat_id, MIN(position) AS first_pos
                   FROM messages
                   WHERE role = 'assistant' AND duration_ms IS NOT NULL
                   GROUP BY chat_id
               ) f ON f.chat_id = m.chat_id AND f.first_pos = m.position
               WHERE m.role = 'assistant' AND m.duration_ms IS NOT NULL"""
        ).fetchall()
        return {row["chat_id"]: float(row["first_ms"]) / 1000.0 for row in rows}

    def message_counts(self) -> dict[str, int]:
        """Сколько сообщений в каждом чате. Один запрос на весь список.

        Нужно статистике: чаты без сообщений (пустые заготовки) в неё не попадают.
        """
        rows = self._conn.execute(
            "SELECT chat_id, COUNT(*) AS total FROM messages GROUP BY chat_id"
        ).fetchall()
        return {row["chat_id"]: int(row["total"]) for row in rows}

    # ------------------------------------------------------------------ users

    def get_user(self, username: str) -> UserRecord | None:
        row = self._conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return None if row is None else self._row_to_user(row)

    def upsert_user(self, username: str, *, is_authorized: bool = False) -> UserRecord:
        """Создаёт пользователя при первом входе; роль остаётся нетронутой.

        is_authorized=True выставляет флаг компании (вход по ИНН). Для гостя флаг
        не трогаем на повторных входах, но при первом он остаётся нулевым.
        """
        now = _now()
        self._conn.execute(
            "INSERT INTO users (username, role, is_authorized, created_at, updated_at) "
            "VALUES (?, NULL, ?, ?, ?) ON CONFLICT (username) DO NOTHING",
            (username, int(is_authorized), now, now),
        )
        if is_authorized:
            self._conn.execute(
                "UPDATE users SET is_authorized = 1, updated_at = ? WHERE username = ?",
                (now, username),
            )
        self._conn.commit()
        user = self.get_user(username)
        assert user is not None
        return user

    def set_user_role(self, username: str, role: str | None) -> UserRecord:
        """Устанавливает роль ('supplier' | 'customer' | None) и возвращает запись.

        Роль есть только у компаний: раньше её выбирал гость вручную, но теперь
        она приходит из companies.py вместе с реквизитами (см. app.login_company).
        """
        self.upsert_user(username)
        self._conn.execute(
            "UPDATE users SET role = ?, updated_at = ? WHERE username = ?",
            (role, _now(), username),
        )
        self._conn.commit()
        user = self.get_user(username)
        assert user is not None
        return user

    def _row_to_user(self, row: sqlite3.Row) -> UserRecord:
        # is_authorized может отсутствовать в очень старой базе до _migrate.
        keys = row.keys()
        return UserRecord(
            username=row["username"],
            role=row["role"],
            is_authorized=bool(row["is_authorized"]) if "is_authorized" in keys else False,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def rename_chat(self, chat_id: str, title: str) -> None:
        self._conn.execute("UPDATE chats SET title = ?, updated_at = ? WHERE id = ?", (title, _now(), chat_id))
        self._conn.commit()

    def set_chat_topic(self, chat_id: str, topic: str | None, subtopic: str | None = None) -> None:
        """Проставляет тему и подтему обращения. updated_at не трогаем: это фоновая метка,
        а не активность в чате — иначе список чатов переупорядочится сам по себе."""
        self._conn.execute(
            "UPDATE chats SET topic = ?, subtopic = ? WHERE id = ?",
            (topic, subtopic, chat_id),
        )
        self._conn.commit()

    def touch_chat(self, chat_id: str) -> None:
        self._conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (_now(), chat_id))
        self._conn.commit()

    # -------------------------------------------------------- AI-сводки тем

    def get_topic_summary(self, topic: str) -> TopicSummaryRecord | None:
        row = self._conn.execute(
            "SELECT * FROM topic_summaries WHERE topic = ?", (topic,)
        ).fetchone()
        if row is None:
            return None
        return TopicSummaryRecord(
            topic=row["topic"],
            summary=row["summary"],
            signature=row["signature"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def upsert_topic_summary(self, topic: str, summary: str, signature: str = "") -> TopicSummaryRecord:
        """Записывает сводку темы (перезаписывает прежнюю)."""
        self._conn.execute(
            """INSERT INTO topic_summaries (topic, summary, signature, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (topic) DO UPDATE SET
                   summary = excluded.summary,
                   signature = excluded.signature,
                   updated_at = excluded.updated_at""",
            (topic, summary, signature, _now()),
        )
        self._conn.commit()
        record = self.get_topic_summary(topic)
        assert record is not None
        return record

    def set_chat_rating(self, chat_id: str, rating: str, reason: str | None = None) -> None:
        """Оценка чата целиком: одна на чат, к сообщениям не привязана.

        rating — 'positive' | 'negative'. reason сохраняется только при negative
        (выбранная причина или «Позови оператора»). updated_at не трогаем: оценка
        ставится вместе с сообщениями хода, а порядок чатов менять не должна.
        """
        if rating not in RATINGS:
            raise ValueError(f"Неизвестная оценка: {rating}")
        self._conn.execute(
            "UPDATE chats SET rating = ?, rating_reason = ?, rated_at = ? WHERE id = ?",
            (rating, reason, _now(), chat_id),
        )
        self._conn.commit()

    # -------------------------------------------------------------- handrules

    def _row_to_handrule(self, row: sqlite3.Row) -> HandRuleRecord:
        return HandRuleRecord(
            id=row["id"],
            user_message=row["user_message"],
            instructions=row["instructions"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def create_handrule(self, user_message: str, instructions: str) -> HandRuleRecord:
        now = _now()
        rule_id = _new_id()
        self._conn.execute(
            "INSERT INTO handrules (id, user_message, instructions, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (rule_id, user_message, instructions, now, now),
        )
        self._conn.commit()
        return HandRuleRecord(
            id=rule_id,
            user_message=user_message,
            instructions=instructions,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )

    def get_handrule(self, rule_id: str) -> HandRuleRecord | None:
        row = self._conn.execute("SELECT * FROM handrules WHERE id = ?", (rule_id,)).fetchone()
        return None if row is None else self._row_to_handrule(row)

    def list_handrules(self, limit: int = 500) -> list[HandRuleRecord]:
        """Правила по убыванию свежести: новые сверху."""
        rows = self._conn.execute(
            "SELECT * FROM handrules ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_handrule(row) for row in rows]

    def update_handrule(
        self, rule_id: str, user_message: str | None = None, instructions: str | None = None
    ) -> HandRuleRecord | None:
        """Частичное обновление: None у поля означает «не трогать».

        Возвращает None, если правила с таким id нет (или нечего менять).
        """
        current = self.get_handrule(rule_id)
        if current is None:
            return None
        message = current.user_message if user_message is None else user_message
        answer = current.instructions if instructions is None else instructions
        self._conn.execute(
            "UPDATE handrules SET user_message = ?, instructions = ?, updated_at = ? WHERE id = ?",
            (message, answer, _now(), rule_id),
        )
        self._conn.commit()
        return self.get_handrule(rule_id)

    def delete_handrule(self, rule_id: str) -> bool:
        """Удаляет правило. False — если такого id не было."""
        cursor = self._conn.execute("DELETE FROM handrules WHERE id = ?", (rule_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def delete_chat(self, chat_id: str) -> None:
        self._conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        self._conn.commit()

    # --------------------------------------------------------------- messages

    def list_messages(self, chat_id: str) -> list[MessageRecord]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY position ASC", (chat_id,)
        ).fetchall()
        messages = [
            MessageRecord(
                id=row["id"],
                role=row["role"],
                content=row["content"],
                display_content=row["display_content"],
                attachments=_load_attachments(row),
                entities=_load_entities(row),
                duration_ms=row["duration_ms"],
            )
            for row in rows
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

    def add_message(
        self,
        chat_id: str,
        role: str,
        content: str = "",
        display_content: str | None = None,
        entities: list[dict[str, Any]] | None = None,
    ) -> MessageRecord:
        """Пишет сообщение.

        display_content — то, что видит пользователь, если текст для модели
        отличается (выбор сущности: id агенту, подпись кнопки в UI).
        entities — сущности из REST API (контракт, закупка и т.п.); сохраняются,
        чтобы и в контексте агента, и в отдаче REST они были на месте.
        """
        message = MessageRecord(
            id=_new_id(),
            role=role,
            content=content,
            display_content=display_content,
            entities=list(entities or []),
        )
        self._conn.execute(
            "INSERT INTO messages "
            "(id, chat_id, role, content, display_content, entities, position, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message.id,
                chat_id,
                role,
                content,
                display_content,
                json.dumps(message.entities, ensure_ascii=False) if message.entities else None,
                self._next_position(chat_id),
                _now(),
            ),
        )
        self._conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (_now(), chat_id))
        self._conn.commit()
        return message

    def set_message_attachments(self, message_id: str, attachments: list[dict[str, Any]]) -> None:
        """Помечает сообщение пользователя отправленными вложениями (только метаданные).

        Сами файлы остаются в attachments/<id>, чтобы картинки и документы были
        доступны в истории чата и после того, как улеглись в контекст модели.
        """
        payload = json.dumps(attachments, ensure_ascii=False, default=str) if attachments else None
        self._conn.execute("UPDATE messages SET attachments = ? WHERE id = ?", (payload, message_id))
        self._conn.commit()

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

    def latest_user_message(self, chat_id: str, before_message_id: str) -> MessageRecord | None:
        """Последнее пользовательское сообщение перед указанным assistant-сообщением.

        Нужно, чтобы привязать отправленные вложения к именно этому вопросу.
        """
        row = self._conn.execute(
            """SELECT * FROM messages
               WHERE chat_id = ? AND role = 'user'
                 AND position < (SELECT position FROM messages WHERE id = ?)
               ORDER BY position DESC LIMIT 1""",
            (chat_id, before_message_id),
        ).fetchone()
        if row is None:
            return None
        return MessageRecord(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            attachments=_load_attachments(row),
            entities=_load_entities(row),
            duration_ms=row["duration_ms"],
        )

    def update_message(self, message_id: str, content: str) -> None:
        self._conn.execute("UPDATE messages SET content = ? WHERE id = ?", (content, message_id))
        self._conn.commit()

    def set_message_duration(self, message_id: str, duration_ms: int) -> None:
        """Время генерации ответа агента: весь ход, включая вызовы инструментов."""
        self._conn.execute(
            "UPDATE messages SET duration_ms = ? WHERE id = ?", (max(0, int(duration_ms)), message_id)
        )
        self._conn.commit()

    def get_message(self, message_id: str) -> MessageRecord | None:
        row = self._conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            return None
        message = MessageRecord(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            display_content=row["display_content"],
            attachments=_load_attachments(row),
            entities=_load_entities(row),
            duration_ms=row["duration_ms"],
        )
        message.tools = self._list_tools([message.id]).get(message.id, [])
        return message

    def clear_messages(self, chat_id: str) -> None:
        self._conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        self._conn.commit()

    # ----------------------------------------------------------- entity choices

    def add_entity_choice(
        self, message_id: str, entity_kind: str, options: list[dict[str, str]]
    ) -> None:
        """Сохраняет набор вариантов выбора. Повторный вызов по тому же виду
        перезаписывает прежний: агенту незачем показывать два списка контрактов."""
        self._conn.execute(
            "DELETE FROM entity_choices WHERE message_id = ? AND entity_kind = ?",
            (message_id, entity_kind),
        )
        self._conn.execute(
            "INSERT INTO entity_choices (id, message_id, entity_kind, payload, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                _new_id(),
                message_id,
                entity_kind,
                json.dumps(options, ensure_ascii=False),
                _now(),
            ),
        )
        self._conn.commit()

    def list_entity_choices(self, message_ids: list[str]) -> dict[str, list[EntityChoiceRecord]]:
        """Выборы по нескольким сообщениям сразу — для рендера страницы чата."""
        if not message_ids:
            return {}
        placeholders = ",".join("?" * len(message_ids))
        rows = self._conn.execute(
            f"SELECT * FROM entity_choices WHERE message_id IN ({placeholders}) "
            "ORDER BY created_at, rowid",
            message_ids,
        ).fetchall()
        grouped: dict[str, list[EntityChoiceRecord]] = {}
        for row in rows:
            try:
                options = json.loads(row["payload"])
            except json.JSONDecodeError:
                options = []
            grouped.setdefault(row["message_id"], []).append(
                EntityChoiceRecord(
                    message_id=row["message_id"],
                    entity_kind=row["entity_kind"],
                    options=options,
                    used=bool(row["used"]),
                )
            )
        return grouped

    def mark_entity_choices_used(self, message_id: str) -> None:
        """Помечает все выборы сообщения использованными: пользователь уже выбрал.

        Кнопки после этого не рисуются — выбор сделан, повторять его незачем.
        """
        self._conn.execute(
            "UPDATE entity_choices SET used = 1 WHERE message_id = ?", (message_id,)
        )
        self._conn.commit()

    # -------------------------------------------------------------- tool calls

    def _next_tool_position(self, message_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS pos FROM tool_calls WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        return int(row["pos"])

    def add_tool_call(self, message_id: str, tool_id: str, name: str, kwargs: dict[str, Any]) -> ToolCallRecord:
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
        import settings

        # Путь берём из активного окружения (см. settings.APP_ENV): у облачного
        # и локального запусков разные файлы SQLite.
        resolved = path or settings.db_path()
        _storage = ChatStorage(resolved)
    return _storage
