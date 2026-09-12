#!/usr/bin/env python3
"""Ручная проверка вложений: REST API против запущенного сервера.

Запуск: uvicorn app:app --port 8099, затем python3 check_attachments.py [base_url]
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099") + "/ml-api"

PASS = "OK  "
FAIL = "FAIL"


def request(method: str, path: str, *, data: bytes | None = None, headers: dict | None = None):
    # Путь, начинающийся с //, идёт от корня (например, //attachments/<id>), иначе — под /ml-api.
    root = path.startswith("//")
    url = ("http://" + BASE.split("//", 1)[1].split("/", 1)[0] + path[1:]) if root else BASE + path
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            return response.status, response.read(), {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), {k.lower(): v for k, v in exc.headers.items()}


def multipart(filename: str, content: bytes, content_type: str = "application/octet-stream"):
    boundary = uuid.uuid4().hex
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    return body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def check(label: str, condition: bool, extra: object = "") -> None:
    detail = str(extra)[:200] if extra else ""
    print(f"{PASS if condition else FAIL} {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        raise SystemExit(1)


def main() -> None:
    status, body, _ = request("POST", "/chat", data=b"{}", headers={"Content-Type": "application/json"})
    check("create chat", status == 201, str(status))
    chat_id = json.loads(body)["id"]

    # --- картинка ---
    png = Path(__file__).parent / "jsons/customer-portal/image-1.png"
    if not png.exists():
        png = next((Path(__file__).parent / "jsons").glob("*/image-1.png"))
    data, headers = multipart("image-1.png", png.read_bytes(), "image/png")
    status, body, _ = request("POST", f"/chat/{chat_id}/upload", data=data, headers=headers)
    check("upload image", status == 201, str(status))
    image = json.loads(body)
    check("image kind", image["kind"] == "image")
    check("image url present", image["url"].startswith("/attachments/"), image["url"])

    status, body, headers = request("GET", f"/chat/{chat_id}/files/{image['id']}/content")
    check("image content", status == 200 and body == png.read_bytes(), str(status))
    check("image content-type", headers.get("content-type") == "image/png", str(headers.get("content-type")))

    # --- txt ---
    text = "Первый абзац вложения.\n\nВторой абзац.".encode()
    data, headers = multipart("note.txt", text, "text/plain")
    status, body, _ = request("POST", f"/chat/{chat_id}/upload", data=data, headers=headers)
    check("upload txt", status == 201, str(status))
    doc = json.loads(body)
    check("txt kind is document", doc["kind"] == "document")

    # --- docx через docling ---
    docx = Path("/tmp/test_attachment.docx")
    if docx.exists():
        data, headers = multipart(
            "test_attachment.docx",
            docx.read_bytes(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        status, body, _ = request("POST", f"/chat/{chat_id}/upload", data=data, headers=headers)
        check("upload docx via docling", status == 201, str(status))
        check("docx is document", json.loads(body)["kind"] == "document")

    # --- список ---
    status, body, _ = request("GET", f"/chat/{chat_id}/files")
    listed = json.loads(body)
    check("list files", status == 200 and len(listed) >= 2, f"{len(listed)}")

    # --- неудачные загрузки ---
    data, headers = multipart("big.bin", b"x" * (10 * 1024 * 1024 + 1))
    status, body, _ = request("POST", f"/chat/{chat_id}/upload", data=data, headers=headers)
    check("oversize rejected", status == 400, f"{status} {body[:80]}")

    data, headers = multipart("empty.txt", b"", "text/plain")
    status, body, _ = request("POST", f"/chat/{chat_id}/upload", data=data, headers=headers)
    check("empty rejected", status == 400, f"{status} {body[:80]}")

    data, headers = multipart("virus.exe", b"MZ\x00\x00", "application/octet-stream")
    status, body, _ = request("POST", f"/chat/{chat_id}/upload", data=data, headers=headers)
    check("unknown format rejected", status == 400, f"{status} {body[:80]}")

    # --- удаление ---
    status, _body, _ = request("DELETE", f"/chat/{chat_id}/files/{doc['id']}")
    check("delete file", status == 204, str(status))
    status, _body, _ = request("DELETE", f"/chat/{chat_id}/files/{doc['id']}")
    check("delete missing is 404", status == 404, str(status))

    status, body, _ = request("GET", f"/chat/{chat_id}/files")
    check("file gone after delete", all(f["id"] != doc["id"] for f in json.loads(body)))

    # --- отправка сообщения: вложения уходят в контекст и удаляются из таблицы ---
    status, body, _ = request(
        "POST",
        f"/chat/{chat_id}/message",
        data=json.dumps({"message": "Что на картинке? Ответь одним предложением."}).encode(),
        headers={"Content-Type": "application/json"},
    )
    check("send message with attachments", status == 200, str(status))
    events = body.decode("utf-8", "replace")
    check("stream has done", "event: done" in events, events[-200:])

    status, body, _ = request("GET", f"/chat/{chat_id}/files")
    check("pending attachments cleared after send", json.loads(body) == [], body[:200])

    # --- история сохраняет вложения: оригинал живёт в attachments/<id> ---
    status, body, _ = request("GET", f"/chat/{chat_id}")
    chat = json.loads(body)
    user_messages = [m for m in chat["messages"] if m["role"] == "user"]
    sent = [a for m in user_messages for a in m.get("attachments", [])]
    check("history keeps sent attachments", len(sent) >= 2, f"{len(sent)}")

    image_in_history = next((a for a in sent if a["kind"] == "image"), None)
    check("image attachment in history", image_in_history is not None)
    check("history url is /attachments/<id>", image_in_history["url"].startswith("/attachments/"), image_in_history["url"])

    # Постоянная ссылка из истории должна отдавать те же байты и после отправки.
    file_id = image_in_history["url"].rsplit("/", 1)[-1]
    status, body, headers = request("GET", f"/chat/{chat_id}/files/{file_id}/content")
    check("pending content gone after send", status == 200, str(status))
    status, body2, headers = request("GET", f"//attachments/{file_id}")
    check("persistent attachment content", status == 200 and body2 == png.read_bytes(), str(status))
    check("persistent content-type", headers.get("content-type") == "image/png", str(headers.get("content-type")))

    # --- 404 на чужой чат ---
    status, _body, _ = request("GET", "/chat/deadbeef/files")
    check("unknown chat is 404", status == 404, str(status))

    status, _body, _ = request("GET", "//attachments/00000000000000000000000000000000")
    check("unknown attachment is 404", status == 404, str(status))

    request("DELETE", f"/chat/{chat_id}")
    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
