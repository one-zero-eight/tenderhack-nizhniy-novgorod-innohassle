FastAPI backend for the TenderHack support-chat MVP. PostgreSQL stores chats, messages, support assignments, and ratings. A neighboring AI service handles answering and support-line classification. The backend performs local RuBERT profanity checks.

The completed backend uses SQLAlchemy/asyncpg, ordinary HTTP requests, and frontend polling. The AI service is stateless with respect to conversations and owns knowledge-base ingestion, retrieval, answer generation, and support-line classification. The backend persists conversations and executes confirmed handoffs and operator assignments. The case requirements are in [task.pdf](task.pdf).

**Run locally from this `backend` directory.** Install Python 3.12+, uv, and Docker, then prepare dependencies and settings:

```bash
uv sync
uv run python -m scripts.download_moderation_model
cp settings.example.yaml settings.yaml
uv run python -c 'import secrets; print(secrets.token_hex(32))'
```

Paste the generated value into `api_settings.jwt_secret` in `settings.yaml`. Set `ai_base_url` to your AI service, or use the development stub below. The full settings schema is in [settings.schema.yaml](settings.schema.yaml); environment variables named `API_SETTINGS__...` override YAML values.

```bash
docker compose up -d --wait db
# Optional here: initialize before seeding; API startup also creates missing tables.
uv run -m src.db.init
export DEMO_PASSWORD='choose-your-demo-password'
uv run -m src.seed
uv run -m src.api --host 127.0.0.1 --port 8000
```

Seeding creates `user`, `user2`, `operator1`, `operator2`, `operator3`, and `admin`, all using the password you supplied. Re-running it preserves existing passwords. Operators initially belong to lines 1, 2, and 3 respectively. To provide real line descriptions, create a JSON array of three `{id, name, description}` objects and run `uv run -m src.seed --lines-file lines.json`. Those descriptions are sent to the AI routing endpoint; the defaults are placeholders.

The API is available at `http://127.0.0.1:8000`, with interactive documentation at `/docs` and its schema at `/openapi.json`. Use an empty `app_root_path` for direct access, as in the example settings. Set `/api` only when a reverse proxy strips that public prefix before forwarding requests.

**Use the development AI stub while the neighboring service is being built.** Run it in another terminal:

```bash
uv run uvicorn scripts.ai_stub:app --host 127.0.0.1 --port 8002
```

This stub exercises the answering/routing contract and does not answer from a knowledge base. Moderation runs in the backend using the real local model, including in demo mode. Ordinary text returns a demo answer. Add these markers to a user message to exercise other paths:

| Marker | Simulated behavior |
| --- | --- |
| `[unknown] [line=2]` | No answer; routing recommends line 2. Use `1` or `3` for other lines. |
| `[answer-error]` | Answer generation fails; the backend offers support. |
| `[route-error]` | No answer and routing is unavailable; the user selects a line manually. |
| `[route-invalid]` | No answer and an invalid routing line; manual line selection is required. |
| `[route-slow]` | Delays routing by 60 seconds to exercise its timeout. |
| `[slow]` | Answering takes 60 seconds, exercising the backend's configured timeout. |

The real AI service implements `POST /v1/answer`, `POST /v1/route`, and `GET /health`. Configure `ai_service_token` if it requires bearer authentication. For the stub, set the matching `API_SETTINGS__AI_SERVICE_TOKEN` environment variable in its terminal as well. The service must run on team-controlled infrastructure, as required by the case. The backend owns profanity classification; the AI service needs no moderation endpoint.

**Local profanity moderation.** The backend uses [cointegrated/rubert-tiny-toxicity](https://huggingface.co/cointegrated/rubert-tiny-toxicity), an MIT-licensed Russian multilabel classifier. The download script pins revision `5d37eff844868e243467e4c38898bad46c271af2` and includes the model card. The default rule blocks high sigmoid scores in either `obscenity` or `insult`. Real-model checks found that common explicit swear words score below 0.02 for `obscenity` but above 0.98 for `insult`, so obscenity alone misses them. This also blocks some insults without profanity; threats and the aggregate toxicity score do not independently close chats. Set `moderation_block_labels: [obscenity]` to restrict categories, accepting those misses. The existing public closure reason remains `profanity`.

Model files are loaded once per API process from `moderation_model_path` (default `models/rubert-tiny-toxicity`). Run the download command above before local startup; Docker downloads the files during its build. Startup fails if the files cannot be loaded or the warmup fails. Runtime loading uses local files only. Linux/Windows use CPU PyTorch wheels; each API worker holds its own model and uses one inference worker with one PyTorch CPU thread.

`moderation_threshold` defaults to **0.8**; a message is blocked when any selected category's score in any chunk is greater than or equal to the threshold. This is an initial operating threshold, not a calibrated accuracy guarantee. Evaluate representative support messages before rollout. Lower values catch more borderline cases but may close innocent chats; higher values can miss profanity. There is no dictionary fallback. Long messages are tokenized into overlapping windows of at most 512 tokens with 64-token overlap, and every window is checked. Sentences split at punctuation followed by whitespace or at line breaks are also scored separately to reduce dilution by surrounding neutral text. Model inference runs outside the async event loop with bounded batches.

`moderation_timeout` defaults to 5 seconds, including waiting for the inference worker. Errors, non-finite scores, and timeouts return `503 MODERATION_UNAVAILABLE` without publishing the text or closing the chat. Native inference cannot be forcibly cancelled; after timeout or client cancellation the worker remains occupied until the calculation finishes, so retries cannot accumulate queued model jobs. Closing a chat during moderation still prevents message publication.

Environment overrides are `API_SETTINGS__MODERATION_MODEL_PATH`, `API_SETTINGS__MODERATION_THRESHOLD`, `API_SETTINGS__MODERATION_BLOCK_LABELS` (a JSON array such as `["obscenity","insult"]`), and `API_SETTINGS__MODERATION_TIMEOUT`. The former field `ai_moderation_timeout` / `API_SETTINGS__AI_MODERATION_TIMEOUT` is removed; use `moderation_timeout` instead. The AI contract no longer includes `POST /v1/moderate`, and demo markers such as `[block]` no longer simulate moderation (they are used only in test doubles).

**Run the complete demo with Docker Compose.** Set these variables in your shell or an ignored `.env` file:

```bash
export API_SETTINGS__JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
export DEMO_PASSWORD='choose-your-demo-password'
docker compose --profile demo up --build -d
docker compose exec -e DEMO_PASSWORD api uv run --no-sync python -m src.seed
```

Docker builds download a pinned model revision into the image; runtime inference requires no internet access. The API creates missing tables from the SQLAlchemy models during startup, both locally and in Compose. Startup fails if database initialization fails. Initialization is idempotent and serialized across concurrent API workers; it preserves existing data and does not alter existing columns or constraints. No separate initialization container is needed. The API listens on port 8000 and the stub on local port 8002. For a real neighboring AI service, set `API_SETTINGS__AI_BASE_URL` to its address reachable from the API container and run Compose without `--profile demo`. Retain the same signing secret across restarts. Demo accounts are created only by the explicit seed command.

**Authenticate and exercise the chat API.** Login accepts JSON:

```http
POST /auth/login
Content-Type: application/json

{"login": "user", "password": "your-demo-password"}
```

Pass the returned token as `Authorization: Bearer <access_token>` on subsequent requests. Tokens expire after 120 minutes by default; log in again to obtain another. Authentication uses Argon2 password hashes and signed JWTs, following the [FastAPI authentication approach](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/).

| Method and path | Usage |
| --- | --- |
| `GET /auth/me` | Current user, role, and operator line. |
| `GET /support-lines` | The three configured support lines. |
| `POST /chats` | Create a user chat; no request body. |
| `GET /chats` | Current user's chats; supports `status`, `offset`, and `limit`. |
| `GET /chats/{id}` | Status, current recipient, suggested line, and `ai_pending`. |
| `POST /chats/{id}/messages` | Send `{"text": "...", "client_message_id": "<uuid>"}`. Returns the saved submission/replies and current chat state. |
| `GET /chats/{id}/messages` | Poll with `after_sequence=<last_seen>` and `limit`; advance to `next_sequence`. |
| `POST /chats/{id}/handoff-offer` | Request an AI line suggestion without waiting for answer failure; no body. |
| `POST /chats/{id}/handoff` | Confirm `{"support_line_id": 2}` or `{}` to accept the stored recommendation. |
| `GET /operator/chats` | Operator's waiting list and assigned chats. |
| `POST /operator/chats/{id}/claim` | Operator claims a waiting chat; then replies through the normal message endpoint. |
| `POST /chats/{id}/close` | Send `{"reason": "resolved"}` or, for the owner, `{"reason": "user_cancelled"}`. |
| `PUT /messages/{id}/rating` | Owner rates a delivered AI/operator reply: `{"stars": 5, "comment": "Helpful"}`. Repeating updates the same rating. |
| `GET /admin/chats` | All chats; filters `from`, `to`, `status`, `line_id`, `operator_id`; pagination `offset`, `limit`. |
| `GET /admin/ratings` | Reviews and original replies; filters `from`, `to`, `stars`, `stars_lte`, `sender_type`, `line_id`, `operator_id`; pagination. |
| `GET /admin/stats` | Counts and rating aggregates, optionally filtered by `from`/`to`. |
| `GET /admin/ai-health` | Admin diagnostic check of the neighboring service. |
| `GET /ping` | Backend/database health check. |

User messages are moderated even during operator chats. A block closes the chat with a redacted message and system notice; unavailable moderation returns `503` without publishing the text. A missing answer or failed answer request offers support, with AI routing where available. The user confirms before the chat enters a line's waiting list. Chat responses expose the current recipient, while each message retains its original author and support line.

Send requests wait for moderation and, in AI mode, the answer/routing calls. With default timeouts, allow at least 45 seconds for the frontend request. Poll chat state and messages about every two seconds. If `has_more` is true, fetch the next page immediately. Errors use `{"detail": {"code": "...", "message": "..."}}`; request validation uses FastAPI's standard `422` error list. `AI_BUSY` means a request is still pending; the owner can wait, close the chat, or request support.

Generate one `client_message_id` for each new submission and reuse it when retrying that same text. Retries return the existing result or pending state. New messages use a new ID; reusing an ID with different text returns `409`. If the API restarts during answering, the next chat read recovers an expired pending request as a support offer. Reading history and rating delivered replies remain available after closure.

For reporting, date filters are inclusive `from` and exclusive `to`, with explicit timezones such as `2026-09-11T00:00:00+03:00`. Chat counts use chat creation time, reply activity uses message creation time, and rating aggregates use rating creation time with the latest saved score. Queue counts are a separate current snapshot. Mean stars are response ratings, with sample counts and distributions, rather than a separate whole-chat score.

**Run checks against an isolated test database.** The test fixture creates and removes a unique schema per test, preserving existing tables. An example disposable PostgreSQL container is:

```bash
docker run --rm -d --name tenderhack-test-db \
  -e POSTGRES_PASSWORD=test-only -e POSTGRES_DB=backend_test \
  -p 127.0.0.1:55432:5432 postgres:17.1
export TEST_DATABASE_URL='postgresql+asyncpg://postgres:test-only@127.0.0.1:55432/backend_test'
uv run pytest -q
uv run ruff check .
docker stop tenderhack-test-db
```

Integration tests let API startup create the SQLAlchemy model tables in each empty test schema and use a controllable HTTP stub for the AI contract and an injected local moderator. Unit tests exercise real tokenization with controlled model logits, including chunk boundaries, thresholding, failures, and cancellation; they do not establish pretrained model accuracy. They cover access control, handoff, moderation and routing failures, duplicate sends/ratings, concurrent claims, stale AI results, history, and reporting. Without `TEST_DATABASE_URL`, the independent AI-client and local moderation tests run; PostgreSQL integration tests are skipped. After downloading the pinned model, run `HF_HUB_OFFLINE=1 RUN_MODERATION_MODEL_TESTS=1 uv run pytest -q` to include real-model smoke checks for ordinary Russian support messages, explicit profanity, insults, and a swear sentence at the end of a long message. These examples verify integration, not general accuracy or resistance to obfuscation.


**Conversation workflow and access rules.** A new chat starts with AI. Every user message passes moderation before publication. An approved question receives an AI answer or a support offer; missing knowledge and temporary service failures have distinct notices. The user confirms the recommended line or chooses another line before entering its waiting list. An operator from that line claims the chat and continues the existing transcript. User messages while waiting or talking to an operator use local moderation without AI-service calls. Operator replies retain their existing behavior and are not moderated.

Every chat response includes a computed `recipient`; each message independently retains its original author, display name, and support line.

| State | What the user sees | How it changes |
| --- | --- | --- |
| `ai` | “AI assistant” | A clean question calls AI; accepting support moves to `waiting_operator`. |
| `handoff_offered` | “AI assistant — support available”, with suggested line | Accepting moves to `waiting_operator`; another question returns to `ai`. |
| `waiting_operator` | “Waiting for Line 2”, for example | An authorized operator claims the chat. |
| `operator` | “Anna · Line 2”, for example | User and assigned operator exchange messages until closure. |
| `closed` | Closed status and reason | Messages are read-only; delivered responses remain rateable. |

Any active state can close with `resolved`, `user_cancelled`, or `moderation`. Only the backend can set a moderation closure. Closing an already closed chat is harmless; sending a new message to it returns `409`. Cancellation and moderation closures are counted separately from resolved chats.

Chat details and transcripts are accessible to the owner, assigned operator, or admin. Waiting-list entries expose selection metadata; an operator gains transcript access by claiming a chat from their own line. Roles, sender identity, and line membership come from the database. Claims lock the chat row and recheck its state, so concurrent claims have one winner and one `409`.

Handoff endpoints apply in `ai` or `handoff_offered`; repeating an accepted handoff to the same waiting line returns its existing state. A direct support request uses the latest approved question and history. Without an approved question or valid recommendation, the user selects a line manually. Waiting lists query `waiting_operator` chats ordered by `handed_off_at`.

Messages allow up to 4,000 characters; rating comments allow up to 2,000. Only the owner can rate delivered AI/operator replies, with integer stars from 1 to 5. User messages, system notices, and redacted content are not rateable.

**Database and code organization.** Five SQLAlchemy tables use UUIDs for users, chats, messages, and ratings, fixed support-line IDs `1`, `2`, and `3`, and UTC timestamps.

| Table | Main fields and constraints |
| --- | --- |
| `users` | `id`, `login`, `password_hash`, `display_name`, `role` (`user`, `operator`, `admin`), nullable `support_line_id`. For the MVP, each operator belongs to one line. |
| `support_lines` | `id`, `name`, `description`. Exactly three seeded entries. |
| `chats` | `id`, `user_id`, `status`, `suggested_line_id`, `handoff_reason`, actual `support_line_id`, nullable `operator_id`, `pending_ai_message_id`, `ai_deadline_at`, `created_at`, `updated_at`, `handed_off_at`, `assigned_at`, `closed_at`, `close_reason`, nullable `moderation_reason`. Suggested routing and accepted routing are distinct. |
| `messages` | `id`, `chat_id`, per-chat `sequence`, `sender_type`, nullable `sender_id`, `sender_name`, nullable `support_line_id`, `text`, optional `citations` JSON, nullable `reply_to_message_id`, nullable `client_message_id` and `input_hash`, `is_redacted`, `created_at`. The operator's line is stored at send time for correct attribution. |
| `ratings` | `id`, `message_id`, `user_id`, integer `stars` constrained to `1..5`, optional `comment`, `created_at`, `updated_at`. Unique `(message_id, user_id)` so updating a rating replaces the previous value. |

Chats also store `generation` and `next_sequence` to reject stale AI results and allocate ordered messages under a chat-row lock. Unique `(chat_id, sequence)` and `(chat_id, client_message_id)` constraints enforce ordering and submission deduplication. Indexes support owner/date lookups, support queues, reply targets, and rating dates. API startup creates missing tables directly from model metadata; there are no migrations. `python -m src.db.init` remains available for initializing tables before an explicit seed command.

Business logic lives in `src/services/`: `chats.py` handles conversations and human support, `ai_client.py` handles AI HTTP contracts, `moderation.py` handles local obscenity classification, `auth.py` handles authentication, and `stats.py` handles reporting. HTTP routes live in `src/api/repositories/`, database helpers in `src/db/repositories/`, models in `src/db/models/`, and request/response schemas in `src/schemas/`.

**AI service JSON contracts.** The backend uses one async HTTP client owned by the FastAPI lifespan. Requests go to the configured `ai_base_url`, with bearer authentication when `ai_service_token` is set. The two capability endpoints must echo the request UUID. The normal path performs local moderation, then calls answering; routing runs when support is offered.

The AI service must provide these three endpoints:

| Method and path | Request | Required response |
| --- | --- | --- |
| `POST /v1/answer` | `request_id`, approved `message`, bounded approved `history`. | Echo `request_id`; return `outcome: "answered"`, non-empty `answer`, and `sources`, or `outcome: "no_answer"`, `answer: null`, and `sources: []`. Both outcomes use HTTP `200`. |
| `POST /v1/route` | `request_id`, approved `message`, bounded approved `history`, and the three `support_lines` with IDs, names, and descriptions. | HTTP `200` with the same `request_id` and `recommended_support_line_id` belonging to the supplied catalog. Assignment requires user confirmation. |
| `GET /health` | No body. | JSON describing answering, routing, and model/index readiness. HTTP `200` when all required capabilities are ready, `503` otherwise. |

Health checks are used for diagnostics, not before each message. Technical failures from capability endpoints use non-2xx responses. Detailed JSON examples follow.

Example request to `POST /v1/answer`:

```json
{
  "request_id": "uuid-of-the-user-message",
  "message": "How do I change the details in my supplier profile?",
  "history": [
    {"author": "user", "text": "I need help with my profile."},
    {"author": "ai", "text": "What would you like to change?"}
  ]
}
```

`history` contains up to the last 20 approved user/AI/operator messages, subject to a shared size limit. Exclude the current question from history to avoid sending it twice, and exclude system notices and redacted content. `author` can be `user`, `ai`, or `operator`. The same context rules apply to routing; neither endpoint receives text that failed moderation.

An answered response uses HTTP `200`:

```json
{
  "request_id": "uuid-of-the-user-message",
  "outcome": "answered",
  "answer": "Open your supplier profile and ...",
  "sources": [
    {"document_id": "supplier-guide", "title": "Supplier guide", "section": "Profile details"}
  ]
}
```

A knowledge-base miss also uses HTTP `200`:

```json
{
  "request_id": "uuid-of-the-user-message",
  "outcome": "no_answer",
  "answer": null,
  "sources": []
}
```

`answered` requires non-empty answer text. `no_answer` explicitly means the service cannot provide a sufficiently supported answer; the backend must not infer this by searching generated prose for phrases such as “I don't know.” Source metadata is passed through for the frontend to display; document ingestion and retrieval remain AI-service concerns.

Example request to `POST /v1/route` (include available approved history using the same format as `/v1/answer`):

```json
{
  "request_id": "uuid-for-this-routing-request",
  "message": "How do I change the details in my supplier profile?",
  "history": [],
  "support_lines": [
    {"id": 1, "name": "Line 1", "description": "Agreed responsibility for line 1"},
    {"id": 2, "name": "Line 2", "description": "Agreed responsibility for line 2"},
    {"id": 3, "name": "Line 3", "description": "Agreed responsibility for line 3"}
  ]
}
```

Successful routing uses HTTP `200`:

```json
{
  "request_id": "uuid-for-this-routing-request",
  "recommended_support_line_id": 2
}
```

The returned line must belong to the supplied catalog. Replace the placeholder descriptions with the lines' actual responsibilities before testing classification. Routing does not select a named operator, move the chat into a queue, or close it; those are backend operations performed after user confirmation. If there is no approved question yet, offer manual line selection without calling routing.

Technical failures use non-2xx responses. For answering, timeout, malformed JSON, mismatched request IDs, unknown outcomes, and an empty `answered` response trigger a support offer and a bounded routing attempt. Routing failure leaves the recommendation empty and presents the three line choices. Moderation failure leaves the message undelivered and the chat open. Default configurable timeouts are 5 seconds for local moderation (including waiting for its worker), 30 seconds for answering, and 5 seconds for routing. The frontend timeout must exceed the combined request budget. The backend does not automatically retry AI calls.

**Transactions, retries, and pending AI work.** AI calls run synchronously in request handlers, outside database transactions. The backend checks authentication and duplicate submission IDs before moderation, then locks and rechecks the chat before saving anything. A chat closed during moderation receives no new message. A block saves the redacted message and closure notice atomically; moderation failure returns `503` with `MODERATION_UNAVAILABLE` and saves no submission.

Before answering and routing, the backend commits the approved message and a pending marker with a deadline covering both calls. It briefly locks the chat again to persist the result and clear the marker. Another approved AI question while one is pending returns `409`; moderation can still close the chat, and the owner can close it or request support.

A direct handoff offer clears the pending answer. Generation and state checks discard late answers or routing results after another question, handoff, or closure. Submission hashes detect reuse of an ID with different text even when the original message was redacted. Expired pending work recovers on subsequent chat operations, including listing chats and rating replies, as a technical-failure support offer without a recommended line. The offer and notice are saved together to avoid duplicates. Recovery uses database state and requires no background worker.

**Reporting definitions.** Admin reporting uses direct SQL aggregates, with chats and ratings aggregated separately to avoid duplicate chat counts from message joins.

| Metric | Definition |
| --- | --- |
| Chat volume | Total created chats, counts by current status, and closed counts split by closure reason. |
| Support workload | Chats handed to each line, currently waiting chats, and currently assigned chats per operator. |
| AI vs human activity | Counts of delivered AI and operator replies, excluding system notices and redacted messages. These are activity counts, not proof that the issue was resolved. |
| Response quality | Rating count, mean stars, and histogram for stars 1–5; group by AI/operator, individual operator, and the reply's support line. Always show sample size with the average. |
| Feedback to inspect | Low ratings (1–2 stars) with their comments and original messages. Treat 3 as neutral and 4–5 as positive for simple reporting. |

Ratings stay attributed to the reply's original author and support line. UTC timestamps are stored by the backend; the frontend can display local time.

**MVP scope and real-service validation.** The backend implements authentication, chat and moderation, AI answering and routing, human support, reply ratings, and admin reporting. Registration, password reset, supplier-portal SSO, waiting/resolution-time metrics, whole-chat ratings, transfers, multiple operator line memberships, full-text search, and exports are outside this MVP.

Feedback analysis is also outside the implemented API. A possible future `POST /v1/feedback/analyze` could accept bounded reviews containing `feedback_id`, `stars`, `comment`, `response_text`, and `support_line_id`, and return a summary with recurring issues tied to feedback IDs.

When integrating the real AI service, configure its URL/token and agreed line descriptions, then validate known and unknown questions, routing classification accuracy and independent capability failures. Separately validate local RuBERT moderation against Russian profanity, obfuscated text, and innocent near-matches. Stub checks verify backend behavior; model quality requires representative labeled messages. The case also calls for a BPMN diagram of the user/backend/AI/operator workflow for the presentation.
