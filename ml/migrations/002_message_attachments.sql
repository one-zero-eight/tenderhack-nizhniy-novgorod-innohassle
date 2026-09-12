-- Вложения, отправленные вместе с сообщением пользователя.
--
-- В `messages.attachments` лежит JSON-массив описаний вида
-- [{"id": "<file_id>", "filename": "...", "kind": "image|document", ...}].
-- Сами файлы — в папке attachments/<id> (см. attachments.py), поэтому картинки
-- и документы остаются доступными в истории чата и после отправки в модель:
-- таблица chat_files для этого не годится, она чистится на отправке.
ALTER TABLE messages ADD COLUMN attachments TEXT;
