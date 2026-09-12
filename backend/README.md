# TenderHack Support Backend

FastAPI backend for the TenderHack support-chat platform. It orchestrates user authentication, role-based access control, local RuBERT profanity moderation, real-time Server-Sent Events (SSE) streaming, human operator escalations, ratings, and analytics.

The backend works in tandem with the neighboring ML service (`ml/`), which provides retrieval-augmented generation (RAG) over official Supplier Portal manuals, LLM tool execution, automatic chat titling, and AI conversation persistence.

---

## 1. Architecture & Design Principles

```
[ Frontend Client ]
       │
       │ (1) HTTP / SSE (/chats/{id}/messages)
       ▼
[ Backend Orchestrator (FastAPI) ] ─── (2) Local RuBERT Moderation (Toxicity / Profanity)
   ├── Auth & RBAC (Users, Operators, Admins, JWT)
   ├── Human Operator Queues & Claiming
   ├── Ratings & Customer Satisfaction Analytics
   │
   ├── [ PostgreSQL Database ]
   │     ├── chats (metadata, status, support_line_id, operator_id, title)
   │     ├── messages (human operator & system messages ONLY)
   │     ├── ratings (ratings with denormalized sender & line context)
   │     ├── users & support_lines
   │
   └── [ ML Service Proxy (Async HTTP / SSE) ]
         ├── 1:1 Eager Chat Lifecycle (POST /ml-api/chat)
         ├── Retrieval-Augmented QA & Agent Tools (search, open)
         ├── Automatic Chat Titling
         ├── Full Dialogue Persistence (SQLite messages & tool_calls)
         └── Real-time SSE Stream (start, token, tool_call, tool_result, redirect, done)
```

### Core Design Principles

1. **Zero Dual-Storage of AI Turns**:
   - AI assistant replies, citations, user prompts in AI mode, and tool execution logs are stored **exclusively in the ML service's SQLite database**.
   - PostgreSQL only stores human operator responses and system notices in the `messages` table.
   - When transcripts are retrieved via `GET /chats/{chat_id}/messages`, the backend dynamically merges ML service dialogue with operator messages from PostgreSQL into a unified sequential timeline.

2. **1:1 Chat ID Adoption**:
   - The backend adopts the ML service's 32-character string ID (`chat_id: str`) directly as the primary identifier across PostgreSQL and all APIs.
   - Chats are created eagerly in the ML service upon calling `POST /chats`, eliminating dual-ID mapping tables and lazy-creation latency.

3. **Dual-Mode Messaging (Real-Time SSE Streaming + JSON Fallback)**:
   - `POST /chats/{chat_id}/messages` automatically inspects the `Accept` header. If `text/event-stream` is requested, it directly streams SSE events from the AI agent to the frontend.
   - Explicit endpoints `POST /chats/{chat_id}/stream` and `POST /chats/{chat_id}/message` provide dedicated SSE streams.
   - Standard JSON clients continue to receive the complete `SendResult` payload synchronously.

4. **Decoupled Ratings & Performance**:
   - Customer feedback (`Rating`) stores denormalized sender and line metadata (`sender_type`, `sender_id`, `support_line_id`, `message_text`).
   - Reporting queries and administrative statistics run without expensive `JOIN` operations against message history.

---

## 2. Quick Start & Setup

### Prerequisites
- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) package manager
- Docker (for PostgreSQL)

### Setup Steps

```bash
# 1. Install dependencies
uv sync

# 2. Download the local RuBERT moderation model
uv run python -m scripts.download_moderation_model

# 3. Configure environment settings
cp settings.example.yaml settings.yaml
uv run python -c 'import secrets; print(secrets.token_hex(32))'
```

1. Insert the generated hex string into `api_settings.jwt_secret` in `settings.yaml`.
2. Configure `ai_base_url` to point to the ML service (default: `http://100.64.0.5:8010` or local `http://127.0.0.1:8010`).
3. Start the PostgreSQL container and seed demo accounts:

```bash
# Launch database
docker compose up -d --wait db

# Seed default test users and support lines
export DEMO_PASSWORD='your-demo-password'
uv run -m src.seed

# Run FastAPI server
uv run -m src.api --host 127.0.0.1 --port 8000
```

### Pre-seeded Demo Accounts
- `user` / `user2` — Customer accounts (Role: `user`)
- `operator1` — Line 1 Operator: Technical Support (Role: `operator`)
- `operator2` — Line 2 Operator: Procurement & Quotation Sessions (Role: `operator`)
- `operator3` — Line 3 Operator: Organization Accreditation & ERUZ (Role: `operator`)
- `admin` — System Administrator (Role: `admin`)

Password for all pre-seeded accounts is the value of `DEMO_PASSWORD` passed during seeding.

AI generation has a total deadline of 300 seconds, including pauses during model
generation and tool calls. Configure it with `API_SETTINGS__AI_ANSWER_TIMEOUT`
or `api_settings.ai_answer_timeout` in `settings.yaml` (maximum: 300 seconds).
Existing explicit values, such as 30 seconds, still override the new default.
The generation stream has no separate read timeout; connection, write, and pool
timeouts remain in effect. This applies to both SSE and JSON message endpoints.

---

## 3. End-to-End Application Flows

### Flow 1: AI Answering with Real-Time SSE Streaming (Primary Flow)

The primary interaction mode for users seeking automated support from the knowledge base:

```mermaid
sequenceDiagram
    autonumber
    actor User as Client / Frontend
    participant Backend as Backend FastAPI
    participant Moderator as RuBERT Moderator
    participant ML as ML Service (SQLite)

    User->>Backend: POST /chats (Bearer JWT)
    Backend->>ML: POST /ml-api/chat
    ML-->>Backend: 201 Created {id: "ml-chat-abc123", title: "Новый чат"}
    Backend-->>User: 201 Created {id: "ml-chat-abc123", status: "ai", title: "Новый чат"}

    User->>Backend: POST /chats/ml-chat-abc123/messages<br/>Header: Accept: text/event-stream<br/>{"text": "Как создать оферту?", "client_message_id": "uuid-1"}
    Backend->>Moderator: Check toxicity & profanity (payload.text)
    Moderator-->>Backend: OK (clean)
    Backend->>ML: POST /ml-api/chat/ml-chat-abc123/message (SSE)

    ML-->>Backend: event: start {message_id: "msg-ai-1"}
    Backend-->>User: event: start {message_id: "msg-ai-1"}

    ML-->>Backend: event: tool_call {id: "call-1", name: "search", kwargs: {...}}
    Backend-->>User: event: tool_call {id: "call-1", name: "search", ...}

    ML-->>Backend: event: tool_result {id: "call-1", name: "search", output: "..."}
    Backend-->>User: event: tool_result {id: "call-1", name: "search", ...}

    ML-->>Backend: event: token {delta: "Для создания ", content: "Для создания "}
    Backend-->>User: event: token {delta: "Для создания ", content: "Для создания "}

    ML-->>Backend: event: done {message_id: "msg-ai-1", content: "Для создания оферты перейдите..."}
    Backend-->>User: event: done {message_id: "msg-ai-1", content: "..."}
```

1. **Chat Creation**: `POST /chats` eagerly registers a new session in the ML service and returns a 32-character string ID.
2. **Streaming Submission**: Sending `Accept: text/event-stream` initiates an asynchronous generator yielding server-sent events directly to the frontend.
3. **Tool Visibility**: Tool events (`search`, `open`) allow the frontend to render live status indicators ("Searching manual...", "Reading section 5.2.1").
4. **Chat Titling**: On the initial user question, the ML service LLM generates a concise 3–7 word title, which the backend syncs automatically.

---

### Flow 2: Automated Support Line Escalation (`redirect` Event)

When the AI model determines an inquiry requires human expertise or portal intervention:

```mermaid
sequenceDiagram
    autonumber
    actor User as Client / Frontend
    participant Backend as Backend FastAPI
    participant ML as ML Service
    actor Operator as Human Operator

    User->>Backend: POST /chats/{id}/messages {"text": "Мне заблокировали личный кабинет", ...}
    Backend->>ML: POST /ml-api/chat/{id}/message (SSE)
    ML->>ML: Agent executes transfer_to_support(line="L1", reason="Account blocked")
    ML-->>Backend: event: redirect {line: "L1", reason: "Блокировка аккаунта"}
    ML-->>Backend: event: done {message_id: "...", content: "Перевожу вас на специалиста..."}

    Backend->>Backend: 1. Update Chat status to 'waiting_operator'<br/>2. Assign support_line_id = 1<br/>3. Append System Notice to PostgreSQL
    Backend-->>User: SSE stream closes (or JSON SendResult with updated recipient)

    Note over Operator, Backend: Operator takes over chat
    Operator->>Backend: GET /operator/chats (filter by line 1)
    Operator->>Backend: POST /operator/chats/{id}/claim
    Backend-->>Operator: Chat claimed (status: 'operator')
```

1. The agent triggers the internal `transfer_to_support` tool.
2. The ML service marks the chat as redirected and emits `event: redirect`.
3. The backend updates the PostgreSQL chat record:
   - `status = ChatStatus.WAITING_OPERATOR`
   - `support_line_id = 1`
   - `handed_off_at = now()`
   - Appends an automated system notice explaining the transfer reason to the user.

---

### Flow 3: Manual Operator Handoff & Human Conversation

A user can manually bypass the AI assistant at any time to request a human operator:

```mermaid
sequenceDiagram
    autonumber
    actor User as Client
    participant Backend as Backend FastAPI
    actor Operator as Operator (Line 2)

    User->>Backend: POST /chats/{id}/request-operator {"support_line_id": 2}
    Backend-->>User: 200 OK {status: "waiting_operator", recipient: {kind: "support_queue", ...}}

    Operator->>Backend: GET /operator/chats?status=waiting_operator
    Backend-->>Operator: 200 OK {items: [{id: "{id}", status: "waiting_operator", ...}]}

    Operator->>Backend: POST /operator/chats/{id}/claim
    Backend-->>Operator: 200 OK {status: "operator", operator: {id: "operator-uuid", display_name: "Оператор"}}

    Operator->>Backend: POST /chats/{id}/messages {"text": "Здравствуйте! Чем могу помочь?", "client_message_id": "uuid-2"}
    Backend->>Backend: RuBERT Check -> Append to PostgreSQL messages
    Backend-->>Operator: 200 OK (SendResult)

    User->>Backend: GET /chats/{id}/messages
    Backend->>Backend: Fetches ML dialogue + PostgreSQL operator messages
    Backend-->>User: 200 OK (Continuous sequence: 1: User, 2: AI, 3: Operator)
```

1. **Request Operator**: `POST /chats/{chat_id}/request-operator` transitions the chat from `ai` to `waiting_operator`.
2. **Claiming**: Only operators assigned to the matching `support_line_id` can claim the chat (`POST /operator/chats/{chat_id}/claim`).
3. **Transcript Merging**: The backend merges AI turns from SQLite with human messages from PostgreSQL so both participants see the full conversational context.

---

### Flow 4: Moderation & Profanity Filtering

Every inbound user and operator message is analyzed by a local RuBERT toxicity classification model:

```mermaid
sequenceDiagram
    autonumber
    actor User as Client
    participant Backend as Backend FastAPI
    participant Moderator as RuBERT Toxicity Model
    participant DB as PostgreSQL

    User->>Backend: POST /chats/{id}/messages {"text": "[forbidden/toxic content]", ...}
    Backend->>Moderator: is_blocked(text)
    Moderator-->>Backend: True (Violates acceptable use policy)

    Backend->>DB: 1. Append redacted message: "[Сообщение удалено из-за нецензурной лексики]"<br/>2. Close Chat: status='closed', close_reason='moderation', moderation_reason='profanity'<br/>3. Append System Notice: "Обращение завершено из-за нецензурной лексики..."
    Backend-->>User: 200 OK {chat: {status: "closed", close_reason: "moderation"}, messages: [...]}

    Note over User, Backend: Subsequent message attempts
    User->>Backend: POST /chats/{id}/messages {"text": "Hello?", ...}
    Backend-->>User: 409 Conflict {"code": "CHAT_CLOSED", "message": "This chat is closed"}
```

- If flagged, the AI model is **never contacted**, preventing token consumption and toxic prompt injection.
- The offensive message is permanently redacted in the database.
- The chat is closed with `close_reason = moderation`.

---

### Flow 5: Resolution, Rating & Feedback Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor User as Client
    participant Backend as Backend FastAPI
    participant DB as PostgreSQL

    User->>Backend: POST /chats/{id}/close {"reason": "resolved"}
    Backend-->>User: 200 OK {status: "closed", close_reason: "resolved"}

    User->>Backend: PUT /messages/{message_id}/rating {"stars": 5, "comment": "Очень помогло!"}
    Backend->>Backend: Verify message_id is an AI or Operator reply & user is chat owner
    Backend->>DB: Upsert Rating row with denormalized sender & line info
    Backend-->>User: 200 OK {id: "rating-uuid", stars: 5, comment: "..."}
```

- Users can rate any delivered AI reply or operator response.
- Rating attempts on user's own prompt messages are rejected with `422 Unprocessable Entity` (`MESSAGE_NOT_RATEABLE`).
- Ratings are idempotent; sending updated stars or comments overwrites the existing rating record.

---

## 4. Complete API Endpoint Reference

### Authentication (`/auth`)

| Method | Endpoint | Role Required | Request Body | Response Body | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `POST` | `/auth/register` | Public | `RegisterIn` | `TokenOut` | Register a new user or operator. Returns Bearer token. |
| `POST` | `/auth/login` | Public | `LoginIn` | `TokenOut` | Authenticate with login and password. |
| `GET` | `/auth/me` | Authenticated | None | `UserOut` | Retrieve profile and role of current user. |

#### Auth Schemas
```json
// POST /auth/register
{
  "login": "supplier_ivan",
  "password": "strongpassword123",
  "display_name": "Иван Петров",
  "role": "user",                  // "user" | "operator" | "admin"
  "support_line_id": null          // Required if role == "operator" (1, 2, or 3)
}

// POST /auth/login
{
  "login": "supplier_ivan",
  "password": "strongpassword123"
}

// Response (TokenOut)
{
  "access_token": "eyJhbGciOiJIUzI1Ni...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

---

### Support Lines (`/support-lines`)

| Method | Endpoint | Role Required | Request Body | Response Body | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET` | `/support-lines` | Authenticated | None | `list[SupportLineOut]` | List available support lines with IDs, names, and descriptions. |

---

### Customer Chats (`/chats`)

| Method | Endpoint | Role Required | Request Body | Response Body | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `POST` | `/chats` | `user` | None | `ChatOut` (201) | Create a new chat session. Eagerly registers in ML service. |
| `GET` | `/chats` | Authenticated | Query params | `ChatPage` | List chats belonging to the user (`status`, `offset`, `limit`). |
| `GET` | `/chats/{chat_id}` | Owner / Admin / Assigned Operator | None | `ChatOut` | Retrieve single chat state and current recipient metadata. |
| `GET` | `/chats/{chat_id}/messages` | Owner / Admin / Assigned Operator | Query params | `MessagePage` | Retrieve merged message history (`after_sequence`, `limit`). |
| `POST` | `/chats/{chat_id}/messages` | Owner / Assigned Operator | `MessageIn` | `SendResult` or SSE Stream | Send message. Emits SSE if `Accept: text/event-stream`, else JSON. |
| `POST` | `/chats/{chat_id}/stream` | Owner / Assigned Operator | `MessageIn` | SSE Stream | Explicit SSE streaming message submission endpoint. |
| `POST` | `/chats/{chat_id}/message` | Owner / Assigned Operator | `MessageIn` | SSE Stream | Alternate explicit SSE streaming message submission endpoint. |
| `POST` | `/chats/{chat_id}/request-operator` | Owner | `RequestOperatorIn` | `ChatOut` | Request transfer to a human support line (`1`, `2`, or `3`). |
| `POST` | `/chats/{chat_id}/close` | Owner / Assigned Operator | `CloseIn` | `ChatOut` | Close chat session (`"resolved"` or `"user_cancelled"`). |

#### Chat Request Payloads
```json
// POST /chats/{chat_id}/messages
{
  "text": "Как создать котировочную сессию?",
  "client_message_id": "c1f7b8d4-5e2a-4a67-9321-123456789abc"
}

// POST /chats/{chat_id}/request-operator
{
  "support_line_id": 2
}

// POST /chats/{chat_id}/close
{
  "reason": "resolved"   // "resolved" | "user_cancelled"
}
```

---

### Ratings & Feedback (`/messages`)

| Method | Endpoint | Role Required | Request Body | Response Body | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `PUT` | `/messages/{message_id}/rating` | Chat Owner | `RatingIn` | `RatingOut` | Submit or update star rating (1–5) and comment for an assistant/operator reply. |

#### Rating Payload
```json
// PUT /messages/{message_id}/rating
{
  "stars": 5,                     // 1 to 5
  "comment": "Отличный и быстрый ответ!" // optional, max 2000 chars
}
```

---

### Operator Desk (`/operator`)

| Method | Endpoint | Role Required | Request Body | Response Body | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET` | `/operator/chats` | `operator` | Query params | `ChatPage` | View active and waiting chats routed to operator's support line. |
| `POST` | `/operator/chats/{chat_id}/claim` | `operator` | None | `ChatOut` | Assign waiting chat to current operator (`status: operator`). |

---

### Admin Monitoring & Analytics (`/admin`)

| Method | Endpoint | Role Required | Request Body | Response Body | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET` | `/admin/chats` | `admin` | Query params | `ChatPage` | Filter all chats by date range, status, line, user, or operator. |
| `GET` | `/admin/ratings` | `admin` | Query params | `RatingPage` | Filter customer ratings (`stars`, `stars_lte`, line, operator). |
| `GET` | `/admin/stats` | `admin` | Query params | `dict` | Aggregated analytics: average ratings, volumes, close reasons. |
| `GET` | `/admin/ai-health` | `admin` | None | `dict` | Upstream AI service readiness and component status. |

---

### Knowledge Base & Asset Proxying

| Method | Endpoint | Role Required | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/ml-api/knowledge-base` | Public / App | List all uploaded portal manuals (slug, title, section count, URL). |
| `GET` | `/ml-api/knowledge-base/{slug}` | Public / App | Get complete hierarchy and section tree of a manual. |
| `GET` | `/ml-api/knowledge-base/{slug}/{section_id}` | Public / App | Fetch Markdown content and breadcrumbs for a specific section. |
| `GET` | `/ml-assets/image/{slug}/{filename}` | Public (**No Auth**) | Direct image proxy for manual illustrations referenced in markdown. |
| `GET` | `/ping` | Public | Healthcheck endpoint (`{"status": "pong"}`). |

---

## 5. SSE Event Specification

When consuming streaming message endpoints (`/stream`, `/message`, or `Accept: text/event-stream`), events arrive in the standard SSE format:

```
event: <event_name>
data: <json_payload>

```

| Event Name | Data Schema | Description |
| :--- | :--- | :--- |
| `start` | `{"message_id": "msg-..."}` | Emitted first. Contains the ID of the newly generated assistant message. |
| `token` | `{"delta": "...", "content": "..."}` | Emitted per chunk. `delta` is new text; `content` is total accumulated Markdown. |
| `tool_call` | `{"id": "...", "name": "search", "kwargs": {...}, "output": null}` | AI agent invoked an internal tool. |
| `tool_result` | `{"id": "...", "name": "search", "output": "...", "error": false}` | Tool finished execution. Matches previous `tool_call` ID. |
| `redirect` | `{"line": "L1", "reason": "..."}` | Agent triggered handoff to human support. Chat transitions to `waiting_operator`. |
| `error` | `{"message": "..."}` | Execution error occurred during agent run. |
| `done` | `{"message_id": "...", "content": "..."}` | Final event. Confirms full response saved to SQLite. |

---

## 6. Standard Error Codes

All errors return standard FastAPI error bodies: `{"detail": {"code": "<CODE>", "message": "<MESSAGE>"}}`.

| HTTP Status | Code | Description |
| :--- | :--- | :--- |
| `400` | `OPERATOR_LINE_REQUIRED` | An operator was registered without `support_line_id`. |
| `401` | `AUTH_REQUIRED` | Missing `Authorization: Bearer <token>` header. |
| `401` | `INVALID_TOKEN` | Token expired, invalid signature, or user deleted. |
| `401` | `INVALID_CREDENTIALS` | Incorrect username or password on `/auth/login`. |
| `403` | `USER_REQUIRED` | Action restricted to clients (role: `user`). |
| `403` | `OPERATOR_REQUIRED` | Action restricted to support operators (role: `operator`). |
| `403` | `ADMIN_REQUIRED` | Action restricted to administrators (role: `admin`). |
| `403` | `FORBIDDEN_CHAT_ACCESS` | Operator attempted to claim chat belonging to another support line. |
| `404` | `CHAT_NOT_FOUND` | Requested chat does not exist or caller lacks read access. |
| `404` | `MESSAGE_NOT_FOUND` | Target message ID not found. |
| `409` | `CHAT_CLOSED` | Attempted to send message or close an already closed chat. |
| `409` | `MESSAGE_ID_REUSED` | Reused `client_message_id` with a different message body. |
| `409` | `HANDOFF_NOT_AVAILABLE` | Chat is already closed or assigned to an operator. |
| `409` | `LOGIN_TAKEN` | Username already in use during registration. |
| `422` | `MESSAGE_NOT_RATEABLE` | Only delivered assistant or operator replies can be rated. |
| `422` | `INVALID_SUPPORT_LINE` | Selected line ID does not exist. |
| `422` | `INVALID_PERIOD` | Query parameter `from` timestamp is after `to`. |
| `503` | `MODERATION_UNAVAILABLE` | Local moderation service or model failed. Message was withheld. |
| `503` | `AI_UNAVAILABLE` | Upstream ML service unreachable or returned 5xx. |

---

## 7. Running Tests

The test suite runs against an isolated PostgreSQL schema without disturbing production or development data:

```bash
# Run all tests
TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/postgres" uv run pytest -v

# Run individual test suites
TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/postgres" uv run pytest tests/test_workflow.py -v
TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/postgres" uv run pytest tests/test_ai_client.py -v
TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/postgres" uv run pytest tests/test_moderation.py -v
```
