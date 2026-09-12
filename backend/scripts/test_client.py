"""Interactive CLI client script for testing backend API & AI service."""

import sys
import uuid
import httpx

BASE_URL = "http://127.0.0.1:8000"


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

    target_url = prompt("Backend URL", BASE_URL)
    client = httpx.Client(base_url=target_url, timeout=60.0)

    # 1. Check ping
    try:
        ping = client.get("/ping")
        print("✅ Backend connected:", ping.json())
    except Exception as e:
        print(f"❌ Cannot connect to backend at {target_url}: {e}")
        sys.exit(1)

    # 2. Auth choice
    print("\n--- Authentication ---")
    login_choice = prompt("Choose auth mode (1: Register new user, 2: Login as 'user')", "1")
    if login_choice == "1":
        username = prompt("Enter login for new user", f"user_{uuid.uuid4().hex[:6]}")
        password = prompt("Enter password", "password123")
        display_name = prompt("Enter display name", "Демо Пользователь")
        resp = client.post(
            "/auth/register",
            json={"login": username, "password": password, "display_name": display_name},
        )
        if resp.status_code == 201:
            token = resp.json()["access_token"]
            print(f"✅ Registered as '{username}'!")
        else:
            print("⚠️ Registration failed:", resp.text)
            sys.exit(1)
    else:
        login = prompt("Login", "user")
        password = prompt("Password", "test-user-password")
        resp = client.post("/auth/login", json={"login": login, "password": password})
        resp.raise_for_status()
        token = resp.json()["access_token"]
        print(f"✅ Logged in as '{login}'!")

    headers = {"Authorization": f"Bearer {token}"}

    # 3. Create chat
    print("\n--- Creating Chat ---")
    chat_resp = client.post("/chats", headers=headers)
    chat_resp.raise_for_status()
    chat_id = chat_resp.json()["id"]
    print(f"✅ Chat ID: {chat_id}")

    # 4. Interactive Loop
    print("\n" + "=" * 60)
    print("💬 Chat Started! Type 'exit' or 'quit' to end session.")
    print("=" * 60)

    while True:
        question = prompt("\n❓ Your Question")
        if not question or question.lower() in ("exit", "quit", "q"):
            break

        client_msg_id = str(uuid.uuid4())
        print("⏳ Waiting for AI response...")

        try:
            send_resp = client.post(
                f"/chats/{chat_id}/messages",
                headers=headers,
                json={"text": question, "client_message_id": client_msg_id},
            )
            send_resp.raise_for_status()
            send_data = send_resp.json()

            ai_msg = next((m for m in send_data["messages"] if m["sender_type"] == "ai"), None)
            if ai_msg:
                print(f"\n🤖 AI:\n{ai_msg['text']}\n")

                # Prompt for rating
                do_rate = prompt("Rate this AI answer? (y/n)", "y").lower()
                if do_rate in ("y", "yes"):
                    stars_str = prompt("Stars (1-5)", "5")
                    try:
                        stars = int(stars_str)
                    except ValueError:
                        stars = 5
                    comment = prompt("Comment (optional)", "")
                    rate_resp = client.put(
                        f"/messages/{ai_msg['id']}/rating",
                        headers=headers,
                        json={"stars": stars, "comment": comment or None},
                    )
                    if rate_resp.status_code == 200:
                        print("⭐ Rating saved successfully!")
                    else:
                        print("❌ Rating failed:", rate_resp.text)
            else:
                print("⚠️ No AI message returned. Chat status:", send_data["chat"]["status"])

        except httpx.HTTPStatusError as exc:
            print("❌ Error:", exc.response.status_code, exc.response.text)
        except Exception as exc:
            print("❌ Unexpected error:", exc)

    # 5. Optional close
    close_it = prompt("\nClose chat session? (y/n)", "y").lower()
    if close_it in ("y", "yes"):
        client.post(f"/chats/{chat_id}/close", headers=headers, json={"reason": "resolved"})
        print("🔒 Chat closed.")

    print("\n👋 Goodbye!")


if __name__ == "__main__":
    main()
