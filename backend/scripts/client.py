"""Interactive CLI client script for testing backend API & AI service."""

import sys
import uuid

import httpx

BASE_URL = "http://127.0.0.1:8000"
# JSON responses arrive after moderation, the AI's 300-second deadline, and chat retrieval.
REQUEST_TIMEOUT = httpx.Timeout(30.0, read=330.0)


def prompt(text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{text}{suffix}: ").strip()
        return val if val else default
    except (EOFError, KeyboardInterrupt):
        print("\nExiting...")
        sys.exit(0)


def main():
    print("=" * 60)
    print("🤖 Backend Interactive AI Chat & Rating Test Client")
    print("=" * 60)

    target_url = prompt("Backend URL (use http://127.0.0.1:8080/api for Docker Compose)", BASE_URL)
    try:
        with httpx.Client(base_url=target_url, timeout=REQUEST_TIMEOUT) as client:
            run_session(client)
    except httpx.HTTPStatusError as exc:
        print("❌ Error:", exc.response.status_code, exc.response.text)
        sys.exit(1)
    except httpx.RequestError as exc:
        print(f"❌ Request to {target_url} failed: {exc}")
        sys.exit(1)


def run_session(client: httpx.Client):
    # 1. Check ping
    ping = client.get("/ping")
    ping.raise_for_status()
    print("✅ Backend connected:", ping.json())

    # 2. Auth choice
    print("\n--- Authentication ---")
    login_choice = prompt("Choose auth mode (1: Register new user, 2: Login to existing account)", "1")
    if login_choice == "1":
        username = prompt("Enter login for new user", f"user_{uuid.uuid4().hex[:6]}")
        password = prompt("Enter password", "password123")
        display_name = prompt("Enter display name", "Демо Пользователь")
        resp = client.post(
            "/auth/register",
            json={"login": username, "password": password, "display_name": display_name},
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
        print(f"✅ Registered as '{username}'!")
    else:
        login = prompt("Login")
        password = prompt("Password")
        resp = client.post("/auth/login", json={"login": login, "password": password})
        resp.raise_for_status()
        token = resp.json()["access_token"]
        print(f"✅ Logged in as '{login}'!")

    headers = {"Authorization": f"Bearer {token}"}

    # 3. Create chat
    print("\n--- Creating Chat ---")
    chat_resp = client.post("/chats", headers=headers)
    chat_resp.raise_for_status()
    chat = chat_resp.json()
    chat_id = chat["id"]
    print(f"✅ Chat ID: {chat_id}")

    # 4. Interactive Loop
    print("\n" + "=" * 60)
    print("💬 Chat Started! Type 'exit' or 'quit' to end session.")
    print("=" * 60)

    while chat["status"] != "closed":
        question = prompt("\n❓ Your Question")
        if not question or question.lower() in ("exit", "quit", "q"):
            break

        client_msg_id = str(uuid.uuid4())
        print("⏳ Sending message and waiting for backend response...")

        try:
            send_resp = client.post(
                f"/chats/{chat_id}/messages",
                headers=headers,
                json={"text": question, "client_message_id": client_msg_id},
            )
            send_resp.raise_for_status()
            send_data = send_resp.json()
            chat = send_data["chat"]

            for message in send_data["messages"]:
                if message["sender_type"] != "user" or message.get("is_redacted"):
                    print(f"\n{message['sender_name']} ({message['sender_type']}):\n{message['text']}\n")

            print(f"Chat status: {chat['status']}. Recipient: {chat['recipient']['display_name']}")
            if chat["status"] == "closed":
                print(f"🔒 Chat closed: {chat['close_reason']}")
                break

            for message in send_data["messages"]:
                if message["sender_type"] not in ("ai", "operator") or message.get("is_redacted"):
                    continue
                # Prompt for rating
                do_rate = prompt("Rate this answer? (y/n)", "y").lower()
                if do_rate in ("y", "yes"):
                    while True:
                        stars_str = prompt("Stars (1-5)", "5")
                        try:
                            stars = int(stars_str)
                        except ValueError:
                            stars = 0
                        if 1 <= stars <= 5:
                            break
                        print("Enter a whole number from 1 to 5.")
                    comment = prompt("Comment (optional)", "")
                    rate_resp = client.put(
                        f"/messages/{message['id']}/rating",
                        headers=headers,
                        json={"stars": stars, "comment": comment or None},
                    )
                    if rate_resp.status_code == 200:
                        print("⭐ Rating saved successfully!")
                    else:
                        print("❌ Rating failed:", rate_resp.text)
        except httpx.HTTPStatusError as exc:
            print("❌ Error:", exc.response.status_code, exc.response.text)
            if exc.response.status_code == 409 and exc.response.json().get("detail", {}).get("code") == "CHAT_CLOSED":
                chat["status"] = "closed"
                break
        except httpx.RequestError as exc:
            print("❌ Request failed:", exc)

    # 5. Optional close
    if chat["status"] != "closed":
        close_it = prompt("\nClose chat session? (y/n)", "y").lower()
        if close_it in ("y", "yes"):
            close_resp = client.post(f"/chats/{chat_id}/close", headers=headers, json={"reason": "resolved"})
            close_resp.raise_for_status()
            print("🔒 Chat closed.")

    print("\n👋 Goodbye!")


if __name__ == "__main__":
    main()
