FastAPI backend for the TenderHack support-chat MVP. PostgreSQL stores chats, messages, support assignments, and ratings. A neighboring AI service handles moderation, answering, and support-line classification. The [implementation plan](BACKEND_PLAN.md) describes the workflow and AI JSON contracts.

**Run locally from this `backend` directory.** Install Python 3.12+, uv, and Docker, then prepare dependencies and settings:

```bash
uv sync
cp settings.example.yaml settings.yaml
uv run python -c 'import secrets; print(secrets.token_hex(32))'
```

Paste the generated value into `api_settings.jwt_secret` in `settings.yaml`. Set `ai_base_url` to your AI service, or use the development stub below. The full settings schema is in [settings.schema.yaml](settings.schema.yaml); environment variables named `API_SETTINGS__...` override YAML values.

```bash
docker compose up -d --wait db
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

This stub exercises the contract and does not answer from a knowledge base or perform real moderation. Ordinary text returns a demo answer. Add these markers to a user message to exercise other paths:

| Marker | Simulated behavior |
| --- | --- |
| `[block]` | Moderation blocks the message and closes the chat. |
| `[moderation-error]` | Moderation is unavailable; the text stays undelivered for retry. |
| `[unknown] [line=2]` | No answer; routing recommends line 2. Use `1` or `3` for other lines. |
| `[answer-error]` | Answer generation fails; the backend offers support. |
| `[route-error]` | No answer and routing is unavailable; the user selects a line manually. |
| `[route-invalid]` | No answer and an invalid routing line; manual line selection is required. |
| `[moderation-slow]` / `[route-slow]` | Delays moderation or routing by 60 seconds to exercise its timeout. |
| `[slow]` | Answering takes 60 seconds, exercising the backend's configured timeout. |

The real AI service implements `POST /v1/moderate`, `POST /v1/answer`, `POST /v1/route`, and `GET /health`. Configure `ai_service_token` if it requires bearer authentication. For the stub, set the matching `API_SETTINGS__AI_SERVICE_TOKEN` environment variable in its terminal as well. The service must run on team-controlled infrastructure, as required by the case. The backend contains no profanity dictionary or classification rules.

**Run the complete demo with Docker Compose.** Set these variables in your shell or an ignored `.env` file:

```bash
export API_SETTINGS__JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
export DEMO_PASSWORD='choose-your-demo-password'
docker compose --profile demo up --build -d
docker compose exec -e DEMO_PASSWORD api uv run --no-sync python -m src.seed
```

Compose creates missing tables from the SQLAlchemy models before starting the API. Schema initialization is idempotent; it does not alter existing tables. The API listens on port 8000 and the stub on local port 8002. For a real neighboring AI service, set `API_SETTINGS__AI_BASE_URL` to its address reachable from the API container and run Compose without `--profile demo`. Retain the same signing secret across restarts. Demo accounts are created only by the explicit seed command.

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

Integration tests create the SQLAlchemy model tables in each test schema and use a controllable HTTP stub for the AI contract. They cover access control, handoff, moderation and routing failures, duplicate sends/ratings, concurrent claims, stale AI results, history, and reporting. Without `TEST_DATABASE_URL`, only the independent AI-client tests run; PostgreSQL integration tests are skipped.
