# TenderHack Support Backend

FastAPI backend for the TenderHack support-chat application. PostgreSQL stores chats, messages, support assignments, and ratings. A neighboring ML service handles retrieval-augmented QA, LLM tool execution, and support line routing over Server-Sent Events (SSE). The backend performs local RuBERT profanity checks.

---

## 1. Quick Start & Setup

**Requirements:** Python 3.12+, `uv`, and Docker.

```bash
uv sync
uv run python -m scripts.download_moderation_model
cp settings.example.yaml settings.yaml
uv run python -c 'import secrets; print(secrets.token_hex(32))'
```

1. Paste the generated key into `api_settings.jwt_secret` in `settings.yaml`.
2. Configure `ai_base_url` to point to your ML service (default: `http://100.64.0.5:8010`).
3. Launch PostgreSQL and run the application:

```bash
docker compose up -d --wait db
export DEMO_PASSWORD='choose-your-demo-password'
uv run -m src.seed
uv run -m src.api --host 127.0.0.1 --port 8000
```

Seeding creates default test accounts: `user`, `user2`, `operator1` (Line 1), `operator2` (Line 2), `operator3` (Line 3), and `admin`.

---

## 2. Architecture & ML Service Integration

The backend proxies user requests to the ML service and handles state management, local profanity checks, and operator handoffs.

```
[ Frontend ] ---> [ Backend FastAPI ] ---> [ Local RuBERT Moderation ]
                        |
                        +---> [ PostgreSQL DB ]
                        |
                        +---> [ ML Service (SSE Streaming) ]
                                 ├── search()
                                 ├── open() -> Citations
                                 ├── support_manual()
                                 └── transfer_to_support() -> Redirect SSE event
```

### ML SSE Stream Events Handled by Backend:
- `tool_call`: Captures internal tool executions (`search`, `open`, `support_manual`, `transfer_to_support`). Saved in `Message.tool_calls`.
- `tool_result`: Tool execution results.
- `redirect`: Emitted when the AI decides to transfer the user to human support. The backend parses `line` and `reason`, and **automatically transitions** the chat to `WAITING_OPERATOR` assigned to that support line.
- `done`: Final assistant text response.
- `error`: Stream failure error message.

### Image Proxying:
The ML service embeds static images in markdown responses as `![caption](/ml-assets/image/<slug>/<filename>)`.
The backend provides an **unauthenticated proxy endpoint** `GET /ml-assets/image/{slug}/{filename}` so frontend clients can load static images directly without auth tokens.

---

## 3. End-to-End Usage Flow

Here is the sequential order of endpoint calls to execute a complete support conversation:

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Backend
    participant ML as ML Service
    actor Operator

    User->>Backend: POST /auth/login (obtain JWT token)
    User->>Backend: POST /chats (create new chat)
    Backend-->>User: Chat created (status: "ai")

    User->>Backend: POST /chats/{id}/messages {"text": "How to register?", "client_message_id": "..."}
    Backend->>Backend: RuBERT Profanity Check
    Backend->>ML: POST /ml-api/chat/{ml_chat_id}/message (SSE)
    ML-->>Backend: tool_call (open section 1.2), done event
    Backend-->>User: AI response with citations & tool_calls

    Note over User, ML: Automatic Handoff Example
    User->>Backend: POST /chats/{id}/messages {"text": "I want human operator", "client_message_id": "..."}
    Backend->>ML: POST /ml-api/chat/{ml_chat_id}/message (SSE)
    ML-->>Backend: redirect event {line: "L2", reason: "User requested human"}
    Backend-->>User: Updated Chat (status: "waiting_operator", line: 2)

    Note over Operator, Backend: Operator Handling
    Operator->>Backend: GET /operator/chats (view queue for line 2)
    Operator->>Backend: POST /operator/chats/{id}/claim
    Backend-->>Operator: Chat assigned (status: "operator")
    Operator->>Backend: POST /chats/{id}/messages {"text": "Hello, how can I help?"}

    User->>Backend: POST /chats/{id}/close {"reason": "resolved"}
    User->>Backend: PUT /messages/{id}/rating {"stars": 5, "comment": "Great support!"}
```

---

## 4. Complete API Endpoint Reference

### Authentication (`/auth`)
- `POST /auth/login` — Authenticate with `{"login": "...", "password": "..."}`. Returns JWT access token.
- `POST /auth/register` — Register a new account (`{"login": "...", "password": "...", "display_name": "..."}`).
- `GET /auth/me` — Get current user information and role.

### Support Lines, Knowledge Base & Image Proxy
- `GET /support-lines` — List available support lines (Lines 1-3: Technical support, Procurement support, General inquiries).
- `GET /ml-assets/image/{slug}/{filename}` — **Unauthenticated** image proxy forwarding to the ML service's static assets.
- `GET /ml-api/knowledge-base` (or `/knowledge-base`) — List all knowledge base manuals (slug, title, section count, URL).
- `GET /ml-api/knowledge-base/{slug}` (or `/knowledge-base/{slug}`) — Get manual structure and section tree hierarchy.
- `GET /ml-api/knowledge-base/{slug}/{section_id}` (or `/knowledge-base/{slug}/{section_id}`) — Get section content (Markdown text, navigation, breadcrumbs).

### Client Chat Flow (`/chats`)
- `POST /chats` — Create a new user chat session (Status initialized to `ai`).
- `GET /chats` — List user's chats with pagination (`status`, `offset`, `limit`).
- `GET /chats/{chat_id}` — Get single chat details and status.
- `GET /chats/{chat_id}/messages` — Get message history with pagination (`after_sequence`, `limit`).
- `POST /chats/{chat_id}/messages` — Send user message `{"text": "...", "client_message_id": "<uuid>"}`.
  - Moderated via RuBERT.
  - Sends to ML service via SSE if status is `ai`.
  - Automatically transitions to `waiting_operator` if ML service triggers a `redirect` event.
  - Returns `SendResult` containing updated `chat` state and new `messages`.
- `POST /chats/{chat_id}/request-operator` — Request manual handoff to human support (`{"support_line_id": 2}`). Status becomes `waiting_operator`.
- `POST /chats/{chat_id}/close` — Close chat (`{"reason": "resolved"}` or `{"reason": "user_cancelled"}`).
- `PUT /messages/{message_id}/rating` — Rate a delivered AI or operator reply (`{"stars": 5, "comment": "..."}`).

### Operator Workspace (`/operator`)
- `GET /operator/chats` — List waiting and assigned chats for operator's support line.
- `POST /operator/chats/{chat_id}/claim` — Claim a waiting chat from operator's support line.

### Admin Dashboard (`/admin`)
- `GET /admin/chats` — Query all chats with parameters (`from`, `to`, `status`, `line_id`, `operator_id`, `user_id`, `offset`, `limit`).
- `GET /admin/ratings` — Review customer ratings and feedback comments.
- `GET /admin/stats` — View aggregated analytics (chat counts, close reasons, average rating, rating histograms).
- `GET /admin/ai-health` — Check ML service health status.

### Health Check
- `GET /ping` — Application and database health check.

---

## 5. Running Tests

To run the complete test suite against an isolated PostgreSQL instance:

```bash
TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/postgres" uv run pytest -v
```
