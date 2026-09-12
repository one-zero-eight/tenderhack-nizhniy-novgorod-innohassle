-- Вложения чата: файлы и картинки, загруженные до отправки сообщения.
--
-- Файл лежит в самой SQLite (BLOB в data), потому что внешнего хранилища у проекта нет,
-- а вложения живут ровно до следующего сообщения в чат.
--
-- kind = 'image'    -> data = исходные байты картинки, text = NULL.
-- kind = 'document' -> text = markdown из docling (без OCR и картинок), data = NULL.
--
-- Строки удаляются, когда вложения уходят в контекст модели на следующем сообщении.
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
