from uuid import uuid4


async def test_chat_file_upload_lifecycle(case):
    chat = await case.chat()

    # 1. Upload a file
    file_bytes = b"fake-png-image-binary-data"
    files = {"file": ("screenshot.png", file_bytes, "image/png")}
    res = await case.request("POST", f"/chats/{chat}/upload", login="user", files=files)
    assert res.status_code == 201, res.text
    file_info = res.json()
    assert file_info["filename"] == "screenshot.png"
    assert file_info["is_image"] is True
    assert file_info["kind"] == "image"
    file_id = file_info["id"]
    assert file_info["url"] == f"/attachments/{file_id}"

    # 2. List pending files
    res = await case.request("GET", f"/chats/{chat}/files", login="user")
    assert res.status_code == 200
    files_list = res.json()
    assert len(files_list) == 1
    assert files_list[0]["id"] == file_id

    # 3. Get single file metadata
    res = await case.request("GET", f"/chats/{chat}/files/{file_id}", login="user")
    assert res.status_code == 200
    assert res.json()["id"] == file_id

    # 4. Get pending file content
    res = await case.request("GET", f"/chats/{chat}/files/{file_id}/content", login="user")
    assert res.status_code == 200
    assert res.content == file_bytes
    assert res.headers["content-type"] == "image/png"

    # 5. Permanent attachment download route
    res = await case.client.get(f"/attachments/{file_id}")
    assert res.status_code == 200
    assert res.content == file_bytes

    # 6. Delete file
    res = await case.request("DELETE", f"/chats/{chat}/files/{file_id}", login="user")
    assert res.status_code == 204

    # Verify list is empty
    res = await case.request("GET", f"/chats/{chat}/files", login="user")
    assert res.status_code == 200
    assert res.json() == []

    # 7. Upload again and send a message -> attachment moves to message history
    files = {"file": ("photo.jpg", b"jpeg-bytes", "image/jpeg")}
    res = await case.request("POST", f"/chats/{chat}/upload", login="user", files=files)
    assert res.status_code == 201
    new_file_id = res.json()["id"]

    # Send message
    send_res = await case.send(chat, "Look at this picture", client_id=str(uuid4()))
    assert send_res.status_code == 200
    messages = send_res.json()["messages"]
    # User message should have the attachment
    assert len(messages[0]["attachments"]) == 1
    assert messages[0]["attachments"][0]["id"] == new_file_id
    assert messages[0]["attachments"][0]["url"] == f"/attachments/{new_file_id}"

    # After message, pending files should be empty
    res = await case.request("GET", f"/chats/{chat}/files", login="user")
    assert res.status_code == 200
    assert res.json() == []

    # History from /messages should also show attachments
    res = await case.request("GET", f"/chats/{chat}/messages", login="user")
    assert res.status_code == 200
    page = res.json()
    assert len(page["items"][0]["attachments"]) == 1
    assert page["items"][0]["attachments"][0]["id"] == new_file_id


async def test_chat_file_upload_validation_and_permissions(case):
    chat = await case.chat()

    # Empty file
    files = {"file": ("empty.txt", b"", "text/plain")}
    res = await case.request("POST", f"/chats/{chat}/upload", login="user", files=files)
    assert res.status_code == 400
    assert "empty" in res.text.lower() or "INVALID_FILE" in res.text

    # File exceeding 10MB
    large_bytes = b"0" * (10 * 1024 * 1024 + 2)
    files = {"file": ("large.png", large_bytes, "image/png")}
    res = await case.request("POST", f"/chats/{chat}/upload", login="user", files=files)
    assert res.status_code == 400
    assert "limit" in res.text.lower() or "exceeds" in res.text.lower() or "FILE_TOO_LARGE" in res.text

    # Unauthorized (another user cannot upload, list, or delete files)
    files = {"file": ("test.png", b"test", "image/png")}
    res = await case.request("POST", f"/chats/{chat}/upload", login="user2", files=files)
    assert res.status_code == 404

    res = await case.request("GET", f"/chats/{chat}/files", login="user2")
    assert res.status_code == 404

    # Upload valid file
    res = await case.request("POST", f"/chats/{chat}/upload", login="user", files=files)
    assert res.status_code == 201
    file_id = res.json()["id"]

    res = await case.request("GET", f"/chats/{chat}/files/{file_id}", login="user2")
    assert res.status_code == 404

    res = await case.request("DELETE", f"/chats/{chat}/files/{file_id}", login="user2")
    assert res.status_code == 404

    # Close chat
    await case.close_chat(chat, reason="resolved", login="user")

    # Upload to closed chat should be rejected with 409
    res = await case.request("POST", f"/chats/{chat}/upload", login="user", files=files)
    assert res.status_code == 409
