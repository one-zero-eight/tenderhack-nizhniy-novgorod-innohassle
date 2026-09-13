"""Вложения чата: временный контекст в SQLite + постоянное хранилище оригиналов.

Два разных источника, и они не заменяют друг друга:

* **`attachments/<id>` на диске** (`storage_dir`) — оригиналы файлов и картинок,
  которые загрузил пользователь. Живут, пока жив чат, и отдаются по
  `GET /attachments/<id>`, поэтому в истории чата картинки и файлы остаются
  доступными и после отправки. Плюс рядом лежит `<id>.json` с метаданными.
* **таблица `chat_files` в SQLite** — только то, что ещё не улетело в модель:
  «ожидающий» контекст. При отправке сообщения строки удаляются (см. `clear_files`),
  а файл на диске остаётся.

Текст документа тоже хранится в БД (`text`), чтобы не парсить docling'ом заново,
и в `.json` рядом с оригиналом — чтобы история читалась без БД.

Разбор документов делает docling: OCR выключен, картинки из документа выбрасываются
и остаются плейсхолдерами `<!-- image -->`, поэтому в контекст уходит чистый markdown.
Картинки сохраняются как есть — модели qwen3.6-35b-a3b и deepseek-flash мультимодальные,
и им отдаётся настоящий `ImageBlock`.
"""

from __future__ import annotations

import io
import json
import mimetypes
import re
import sqlite3
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from llama_index.core.base.llms.types import ChatMessage, ImageBlock, TextBlock

from storage import get_storage

HERE = Path(__file__).resolve().parent

# Постоянное хранилище оригиналов. Путь можно переопределить переменной окружения.
DEFAULT_STORAGE_DIR = HERE / "attachments"

# Жёсткий лимит на одно вложение: 10 МБ. Больше в контекст всё равно не влезет.
MAX_FILE_SIZE = 10 * 1024 * 1024

# Расширения, которые считаем картинками. MIME может быть application/octet-stream,
# если браузер его не определил, поэтому опираемся ещё и на суффикс файла.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

# Docling понимает эти форматы (InputFormat), плюс текстовые файлы читаем сами.
DOCLING_SUFFIXES = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".odt", ".ods", ".odp",
    ".html", ".htm", ".md", ".csv", ".asciidoc", ".epub", ".xml", ".json", ".tex",
}
PLAIN_SUFFIXES = {".txt", ".log", ".yml", ".yaml", ".ini", ".cfg", ".toml"}

# Форматы по умолчанию, когда ни MIME, ни суффикс ничего не сказали.
DEFAULT_CONTENT_TYPE = "application/octet-stream"

# id вложения — hex от uuid4. Проверяем перед тем, как строить путь к файлу.
ID_RE = re.compile(r"\A[a-f0-9]{32}\Z")


class AttachmentError(ValueError):
    """Некорректное вложение: слишком большое, пустое или неподдерживаемое."""


@dataclass
class ChatFile:
    """Вложение чата. `data` и `text` грузятся только когда нужны."""

    id: str
    chat_id: str
    filename: str
    content_type: str
    kind: str
    size: int
    created_at: datetime
    text: str | None = None
    data: bytes | None = None

    @property
    def is_image(self) -> bool:
        return self.kind == "image"

    @property
    def url(self) -> str:
        """Постоянная ссылка на оригинал — работает и после отправки сообщения."""
        return f"/attachments/{self.id}"

    @property
    def pending_url(self) -> str:
        """Ссылка на байты из таблицы, пока вложение ещё не отправлено."""
        return f"/ml-api/chat/{self.chat_id}/files/{self.id}/content"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "filename": self.filename,
            "content_type": self.content_type,
            "kind": self.kind,
            "size": self.size,
            "is_image": self.is_image,
            "text": self.text,
            "created_at": self.created_at.isoformat(),
            "url": self.url,
        }


def _now() -> str:
    return datetime.now().isoformat()


def storage_dir() -> Path:
    """Каталог с оригиналами. Переопределяется переменной ATTACHMENTS_DIR."""
    import settings

    path = Path(settings.get("ATTACHMENTS_DIR") or DEFAULT_STORAGE_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    """Своё соединение к той же базе: модуль работает и вне ChatStorage (CLI, миграции).

    Путь берём у ChatStorage, а не у DEFAULT_DB_PATH: иначе CHAT_DB_PATH игнорировался бы
    и вложения уезжали бы в другую базу, чем чаты (и падал бы foreign key).
    """
    path = Path(get_storage().path)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema(conn: sqlite3.Connection | None = None) -> None:
    """Создаёт таблицу вложений, если её ещё нет.

    Основной путь — migrations/001_chat_files.sql; здесь та же DDL, чтобы модуль
    не падал на базе, к которой миграцию не применили.
    """
    ddl = (HERE / "migrations" / "001_chat_files.sql").read_text()
    owns = conn is None
    conn = conn or _connect()
    try:
        conn.executescript(ddl)
        conn.commit()
    finally:
        if owns:
            conn.close()


# ------------------------------------------------------------ постоянное хранилище


def original_path(file_id: str) -> Path | None:
    """Путь к оригиналу по id. None — если id невалиден (защита от `..`)."""
    if not ID_RE.match(file_id or ""):
        return None
    return storage_dir() / file_id


def meta_path(file_id: str) -> Path | None:
    path = original_path(file_id)
    return None if path is None else path.with_suffix(".json")


def store_original(file_id: str, filename: str, content_type: str, data: bytes) -> None:
    """Кладёт оригинал и метаданные на диск. Файлы переживут отправку в модель."""
    path = original_path(file_id)
    if path is None:
        raise AttachmentError("Некорректный идентификатор вложения")
    path.write_bytes(data)
    meta = meta_path(file_id)
    if meta is not None:
        meta.write_text(
            json.dumps(
                {"id": file_id, "filename": filename, "content_type": content_type, "size": len(data)},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def content_disposition(filename: str, *, disposition: str = "inline") -> str:
    """HTTP-заголовок Content-Disposition, безопасный для латиницы.

    Заголовки передаются в latin-1, а имена файлов у нас кириллические, поэтому
    в `filename` кладём ASCII-заглушку, а настоящее имя — в `filename*` по RFC 5987
    (браузеры его понимают и показывают корректное русское имя).
    """
    name = filename or "file"
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace('"', "")
    quoted = urllib.parse.quote(name, safe="")
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


def read_original(file_id: str) -> tuple[bytes, str, str] | None:
    """Оригинал с диска: (байты, content_type, имя файла). None — если его нет."""
    path = original_path(file_id)
    if path is None or not path.is_file():
        return None
    content_type = DEFAULT_CONTENT_TYPE
    filename = file_id
    meta = meta_path(file_id)
    if meta is not None and meta.is_file():
        with meta.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        content_type = payload.get("content_type") or content_type
        filename = payload.get("filename") or filename
    return path.read_bytes(), content_type, filename


def delete_original(file_id: str) -> None:
    """Удаляет оригинал и метаданные. Вызывается вместе с удалением чата."""
    for path in (original_path(file_id), meta_path(file_id)):
        if path is not None:
            path.unlink(missing_ok=True)


def save_meta(payload: dict[str, Any]) -> None:
    """Дописывает (или создаёт) `<id>.json` — метаданные вложения для истории чата."""
    file_id = str(payload.get("id") or "")
    meta = meta_path(file_id)
    if meta is None:
        return
    existing: dict[str, Any] = {}
    if meta.is_file():
        with meta.open(encoding="utf-8") as handle:
            existing = json.load(handle)
    existing.update({key: value for key, value in payload.items() if value is not None})
    meta.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")


def load_meta(file_id: str) -> dict[str, Any] | None:
    """Метаданные вложения из `<id>.json`. None — если файла нет."""
    meta = meta_path(file_id)
    if meta is None or not meta.is_file():
        return None
    with meta.open(encoding="utf-8") as handle:
        return json.load(handle)


# ------------------------------------------------------------------ определение типа


def guess_image(filename: str, content_type: str | None) -> bool:
    """Картинка или нет. MIME от браузера бывает пустым, поэтому смотрим и суффикс."""
    suffix = Path(filename or "").suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return True
    return bool(content_type) and content_type.startswith("image/")


def normalize_content_type(filename: str, content_type: str | None) -> str:
    """MIME для ответа: приоритет у явного значения, иначе угадываем по имени."""
    if content_type and content_type != DEFAULT_CONTENT_TYPE:
        return content_type
    guessed, _ = mimetypes.guess_type(filename or "")
    return guessed or DEFAULT_CONTENT_TYPE


def validate(filename: str, content_type: str | None, data: bytes) -> tuple[str, str]:
    """Проверяет вложение и возвращает (kind, content_type).

    Бросает AttachmentError, если файл пустой, больше лимита или такого типа
    docling не умеет, а сохранять его как картинку нельзя.
    """
    if not data:
        raise AttachmentError("Файл пустой")
    if len(data) > MAX_FILE_SIZE:
        limit_mb = MAX_FILE_SIZE // (1024 * 1024)
        raise AttachmentError(f"Файл больше {limit_mb} МБ")

    resolved_type = normalize_content_type(filename, content_type)
    if guess_image(filename, resolved_type):
        return "image", resolved_type

    suffix = Path(filename or "").suffix.lower()
    if suffix not in DOCLING_SUFFIXES and suffix not in PLAIN_SUFFIXES:
        raise AttachmentError(
            f"Формат «{suffix or filename}» не поддерживается. "
            "Можно загрузить картинку или документ (pdf, docx, xlsx, pptx, html, md, txt)."
        )
    return "document", resolved_type


# ---------------------------------------------------------------- конвертация docling


def convert_document(filename: str, content_type: str, data: bytes) -> str:
    """Документ -> markdown через docling: без OCR, картинки — плейсхолдерами.

    do_ocr=False — распознавание текста со сканов выключено (нам нужен только
    встроенный текстовый слой). export_to_markdown(image_mode=PLACEHOLDER) оставляет
    на месте картинок `<!-- image -->`, а не base64: в БД и в контекст модели
    уходит чистый текст.

    Бросает AttachmentError, если docling не смог разобрать файл, — вызывающий код
    превращает это в 400, а не в 500.
    """
    try:
        from docling.datamodel.base_models import DocumentStream, InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling_core.types.doc import ImageRefMode

        # Текстовые форматы разбирать конвертером незачем — читаем как есть.
        suffix = Path(filename or "").suffix.lower()
        if suffix in PLAIN_SUFFIXES:
            return data.decode("utf-8", errors="replace")

        options = PdfPipelineOptions()
        options.do_ocr = False
        # Картинки нам не нужны: ни вырезать их из страниц, ни описывать моделью.
        options.generate_page_images = False
        options.generate_picture_images = False
        options.do_picture_description = False
        options.do_picture_classification = False

        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )
        # docling принимает только путь или DocumentStream, а файл приходит в память.
        source = DocumentStream(name=filename or "document", stream=io.BytesIO(data))
        result = converter.convert(source)
        return result.document.export_to_markdown(
            image_mode=ImageRefMode.PLACEHOLDER,
            image_placeholder="<!-- image -->",
        ).strip()
    except AttachmentError:
        raise
    except Exception as exc:  # поломку docling показываем как 400, а не 500
        raise AttachmentError(f"Не удалось разобрать «{filename}»: {exc}") from exc


# ------------------------------------------------------------------------ CRUD


def save_file(
    chat_id: str,
    filename: str,
    content_type: str | None,
    data: bytes,
    *,
    convert: bool = True,
) -> ChatFile:
    """Сохраняет одно вложение: оригинал на диск, ожидающий контекст — в БД.

    Документ перед записью в БД прогоняется через docling, картинка сохраняется как есть.
    Оригинал при этом всегда лежит в `attachments/<id>`.
    """
    kind, resolved_type = validate(filename, content_type, data)
    text: str | None = None
    blob: bytes | None = data
    if kind == "document":
        text = convert_document(filename, resolved_type, data) if convert else ""
        blob = None

    record = ChatFile(
        id=uuid.uuid4().hex,
        chat_id=chat_id,
        filename=filename or "file",
        content_type=resolved_type,
        kind=kind,
        size=len(data),
        created_at=datetime.fromisoformat(_now()),
        text=text,
        data=blob,
    )
    # Оригинал кладём первым: если docling успел отработать, а запись в БД упала,
    # файл останется доступным по /attachments/<id>.
    store_original(record.id, record.filename, record.content_type, data)
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO chat_files
               (id, chat_id, filename, content_type, kind, size, text, data, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.id,
                record.chat_id,
                record.filename,
                record.content_type,
                record.kind,
                record.size,
                record.text,
                record.data,
                record.created_at.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    # Подробности для истории чата: где лежит файл и что в нём было.
    save_meta(
        {
            "id": record.id,
            "chat_id": record.chat_id,
            "filename": record.filename,
            "content_type": record.content_type,
            "kind": record.kind,
            "size": record.size,
            "created_at": record.created_at.isoformat(),
        }
    )
    return record


def list_files(chat_id: str, *, with_blobs: bool = False) -> list[ChatFile]:
    """Ожидающие вложения чата по порядку загрузки. Исходные байты по умолчанию не читаем."""
    columns = "*" if with_blobs else "id, chat_id, filename, content_type, kind, size, created_at, text"
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT {columns} FROM chat_files WHERE chat_id = ? ORDER BY created_at ASC, rowid ASC",
            (chat_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        # Таблицы ещё нет — считаем, что вложений нет.
        return []
    finally:
        conn.close()
    return [_row_to_file(row, with_blobs=with_blobs) for row in rows]


def get_file(chat_id: str, file_id: str, *, with_blob: bool = False) -> ChatFile | None:
    columns = "*" if with_blob else "id, chat_id, filename, content_type, kind, size, created_at, text"
    conn = _connect()
    try:
        row = conn.execute(
            f"SELECT {columns} FROM chat_files WHERE chat_id = ? AND id = ?",
            (chat_id, file_id),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    return None if row is None else _row_to_file(row, with_blobs=with_blob)


def get_blob(chat_id: str, file_id: str) -> tuple[bytes, str, str] | None:
    """Байты картинки из ожидающего контекста: (data, content_type, filename)."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT data, content_type, filename, kind FROM chat_files WHERE chat_id = ? AND id = ?",
            (chat_id, file_id),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    if row is None or row["kind"] != "image" or row["data"] is None:
        return None
    return bytes(row["data"]), row["content_type"], row["filename"]


def delete_file(chat_id: str, file_id: str) -> bool:
    """Убирает ожидающее вложение из БД и его оригинал с диска. True — если строка была."""
    conn = _connect()
    try:
        cursor = conn.execute(
            "DELETE FROM chat_files WHERE chat_id = ? AND id = ?", (chat_id, file_id)
        )
        conn.commit()
        removed = cursor.rowcount > 0
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()
    if removed:
        delete_original(file_id)
    return removed


def clear_files(chat_id: str) -> int:
    """Отправляет вложения в модель: строки ждут-контекста удаляются, оригиналы остаются.

    Именно поэтому оригиналы живут в `attachments/`, а не в БД: в истории чата
    картинки и файлы должны остаться доступными.
    """
    conn = _connect()
    try:
        cursor = conn.execute("DELETE FROM chat_files WHERE chat_id = ?", (chat_id,))
        conn.commit()
        return cursor.rowcount
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def drop_originals(chat_id: str) -> int:
    """Удаляет оригиналы всех вложений чата — вызывается при удалении самого чата."""
    metas = [load_meta(name.stem) for name in storage_dir().glob("*.json")]
    removed = 0
    for meta in metas:
        if not meta or meta.get("chat_id") != chat_id:
            continue
        delete_original(str(meta.get("id") or ""))
        removed += 1
    return removed


def _row_to_file(row: sqlite3.Row, *, with_blobs: bool) -> ChatFile:
    keys = row.keys()
    return ChatFile(
        id=row["id"],
        chat_id=row["chat_id"],
        filename=row["filename"],
        content_type=row["content_type"],
        kind=row["kind"],
        size=row["size"],
        created_at=datetime.fromisoformat(row["created_at"]),
        text=row["text"] if "text" in keys else None,
        data=bytes(row["data"]) if with_blobs and "data" in keys and row["data"] is not None else None,
    )


# ------------------------------------------------------------------ контекст модели


def describe(files: list[ChatFile]) -> str:
    """Текстовая шапка про приложенные файлы — идёт первым блоком сообщения."""
    if not files:
        return ""
    lines = [
        "Пользователь приложил к сообщению файлы "
        + f"({len(files)} шт.). Ниже их содержимое.",
        "",
    ]
    for attachment in files:
        note = "картинка" if attachment.is_image else "документ, сконвертирован в markdown"
        lines.append(f"- {attachment.filename} ({note})")
    return "\n".join(lines)


def build_user_message(text: str, files: list[ChatFile]) -> str | ChatMessage:
    """Собирает user_msg для агента: текст вопроса + приложенные файлы.

    Без вложений возвращается обычная строка (как раньше). С вложениями — ChatMessage
    с блоками: картинки идут как ImageBlock (модель мультимодальная), документы —
    как текст в markdown. Если вложений нет, ничего не меняется.
    """
    if not files:
        return text

    blocks: list[Any] = [TextBlock(text=f"{text}\n\n{describe(files)}")]
    for attachment in files:
        if attachment.is_image:
            data = attachment.data
            if data is None:
                loaded = get_file(attachment.chat_id, attachment.id, with_blob=True)
                data = loaded.data if loaded else None
            if data:
                blocks.append(TextBlock(text=f"\n[{attachment.filename}]:"))
                blocks.append(ImageBlock(image=data, image_mimetype=attachment.content_type))
        elif attachment.text:
            blocks.append(TextBlock(text=f"\n[{attachment.filename}]:\n{attachment.text}"))
    return ChatMessage(role="user", blocks=blocks)


__all__ = [
    "DEFAULT_CONTENT_TYPE",
    "MAX_FILE_SIZE",
    "AttachmentError",
    "ChatFile",
    "build_user_message",
    "clear_files",
    "content_disposition",
    "convert_document",
    "delete_file",
    "delete_original",
    "describe",
    "drop_originals",
    "ensure_schema",
    "get_blob",
    "get_file",
    "guess_image",
    "list_files",
    "load_meta",
    "original_path",
    "read_original",
    "save_file",
    "save_meta",
    "storage_dir",
    "store_original",
    "validate",
]
