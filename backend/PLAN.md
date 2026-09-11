**Build the MVP as one FastAPI backend with PostgreSQL and a separate, stateless AI service.** Keep the existing SQLAlchemy/asyncpg setup. Use ordinary HTTP requests and frontend polling; the proposed MVP needs no Redis, message broker, background worker, WebSockets, or token streaming.

This plan covers backend implementation only. It is based on [task.pdf](task.pdf), especially pages 2–5. The initial repository provided database/session scaffolding and `/ping`; the MVP now implements the models, authentication, business endpoints, and integration checks described here; real-service demo validation remains outstanding. See [README.md](README.md) for startup, configuration, and API usage. The AI service owns profanity detection, knowledge-base ingestion, retrieval, answer generation, and support-line classification. The backend stores conversations, applies moderation decisions, and executes confirmed handoffs and operator assignments.

The working assumption is that operators use a small interface backed by this service. Seed three configurable support lines named “Line 1”, “Line 2”, and “Line 3”; the presentation does not define their responsibilities. Use the actual names and descriptions when the team supplies them. A user may be routed directly to any of the three lines.

**Endpoints required from the AI service**

The AI team must provide these four endpoints at the configured `ai_base_url`. The backend calls them over HTTP, using `Authorization: Bearer <ai_service_token>` when configured. The detailed JSON contracts and failure handling appear below.

| Method | Path | Request | Required response |
| --- | --- | --- | --- |
| `POST` | `/v1/moderate` | `request_id`, original user `message`. | Echo `request_id`; return `decision: allow` with `reason: null`, or `decision: block` with `reason: profanity`. A block is HTTP `200`. |
| `POST` | `/v1/answer` | `request_id`, approved `message`, bounded approved `history`. | Echo `request_id`; return `outcome: answered`, non-empty `answer`, and `sources`; or `outcome: no_answer`, `answer: null`, and `sources: []`. Both outcomes are HTTP `200`. |
| `POST` | `/v1/route` | `request_id`, approved `message`, bounded approved `history`, and the three `support_lines` with IDs, names, and descriptions. | HTTP `200` with the same `request_id` and `recommended_support_line_id` belonging to the supplied catalog. The backend asks the user to confirm before assigning that line. |
| `GET` | `/health` | No body. | JSON describing readiness of moderation, answering, and routing, including model/index readiness. HTTP `200` when all capabilities are ready; `503` otherwise. |

Technical failures use non-2xx responses. Default backend timeouts are 5 seconds for moderation, 30 seconds for answering, and 5 seconds for routing. The service remains stateless with respect to conversations; the backend supplies context and persists results.

`POST /v1/feedback/analyze` is an optional future capability, not required for the MVP.

**Implementation audit — 2026-09-11**

| Plan area | Verified implementation / remaining work |
| --- | --- |
| 1. Foundation | Complete: five SQLAlchemy models and constraints, idempotent schema creation and seeding, hashed-password login, expiring tokens, database roles and ownership checks. Migrations were removed at the user's request; run `uv run -m src.db.init` instead. Existing tables are not altered by initialization. |
| 2. Chat and moderation | Complete: authenticated chat APIs, incremental history, author/recipient metadata, moderation before publication, redacted profanity closure, undelivered drafts on moderation failure, and permitted closure reasons. |
| 3. Answering and routing | Complete against the HTTP contract stub: bounded context, citations, no-answer/error offers, validated recommendations, separate timeouts, deduplication, pending deadlines and stale-result protection. Expired pending requests also recover when listing chats or rating a reply. |
| 4. Human support | Complete: three database waiting lists, confirmed handoff, exclusive claim, operator attribution and replies, continued user moderation, and closure. Claims use a chat-row lock followed by a state check/update; concurrent-claim tests verify one winner and one `409`. Support business logic lives in `src/services/chats.py`, with HTTP routes in `src/api/repositories/support.py`. |
| 5. Feedback and admin | Complete: rating upsert and validation, review/message traceability, date/status/line/operator filters, exact-star and low-star review filters, separate SQL aggregates, sample counts, and current queue snapshots. |
| 6. Demo preparation | Partial: startup/API documentation, configurable real-service URL/token, standalone stub (including delays and invalid routing), and automated checks are ready. Real-service acceptance checks and the presentation BPMN diagram remain outstanding. |

Validation: **46 tests passed**, including PostgreSQL integration tests in isolated schemas and AI-client tests; `ruff check .` passed. The test schema now uses the same SQLAlchemy table creation as the initialization command, with a regression check that repeat initialization preserves data.

Outstanding before the actual demo:

- Supply the real AI service address/token and agreed support-line responsibilities; replace the placeholder line descriptions using the seed command's `--lines-file` option.
- Verify known/unknown questions, classification accuracy, Russian profanity and innocent near-matches, and independent capability failures against that service. Stub tests establish backend behavior, not model quality or real-service readiness.
- Produce the presentation BPMN diagram of the implemented user/backend/AI/operator process.

Optional feedback analysis, waiting/resolution-time metrics, whole-chat ratings, transfers, exports, and other items explicitly deferred below are outside this MVP.

**Implement the conversation workflow before adding reporting.**

1. A user creates a chat and sends a message.
2. The backend calls the AI service's moderation endpoint before publishing the text or requesting an answer. On a `block` decision, close the chat, store a redacted message and a system notice, and tell the user why it was closed. The case explicitly requires termination, not just rejection of that message.
3. On an `allow` decision, save the message. In AI mode, call the answer endpoint with recent approved chat history.
4. If the service answers, save and return an AI message. If it reports no answer, times out, or fails, call the AI service's routing endpoint and offer its recommended support line. Use different notices for missing knowledge and temporary service failure. If routing also fails, offer the three lines for the user to choose from.
5. The user accepts the offer, optionally choosing another line. Only then does the backend put the chat in that line's waiting list. For a direct support request, first obtain a routing suggestion from the approved transcript, then ask the user to confirm it.
6. An operator from the selected line claims the chat, sees its existing transcript, and replies. Subsequent user messages still pass AI-service moderation before reaching the operator; they do not trigger answer generation or reclassification.
7. The user or assigned operator closes the chat. The user can rate individual AI/operator replies, including after closure.

Use these chat states and expose a computed `recipient` object in every chat response:

| State | What the user sees | How it changes |
| --- | --- | --- |
| `ai` | “AI assistant” | A clean question calls AI; accepting support moves to `waiting_operator`. |
| `handoff_offered` | “AI assistant — support available”, with suggested line | Accepting moves to `waiting_operator`; another question returns to `ai`. |
| `waiting_operator` | “Waiting for Line 2”, for example | An authorized operator claims the chat. |
| `operator` | “Anna · Line 2”, for example | User and assigned operator exchange messages until closure. |
| `closed` | Closed status and reason | Messages are read-only; delivered responses remain rateable. |

Any active state can become `closed`. Record `close_reason = resolved | user_cancelled | moderation`; cancellation and profanity must not inflate resolved-chat counts. Call AI-service moderation for every user chat message, including messages sent while waiting for or talking to an operator. Closing or handing off a chat prevents a late AI answer or routing result from changing the conversation.

The `recipient` identifies who receives the next message: AI, a support-line queue, or a named operator. Each message separately exposes its actual author (`user`, `ai`, `operator`, or `system`), public display name, and support line where applicable. System notices and historical AI replies must retain their own labels after an operator joins.

**Keep moderation and routing decisions in the AI service.** The backend consumes explicit `allow`/`block` decisions and support-line IDs; it contains no profanity dictionary, classification keywords, or model logic. A moderation block closes the chat and records the service's reason code. A routing recommendation becomes an actual line assignment only after user confirmation; the backend validates that the returned ID belongs to the three configured lines. The AI team can choose a lightweight implementation for each capability.

If moderation times out or returns an invalid result, return `503` with `MODERATION_UNAVAILABLE`, leave the chat open, and keep the text as a frontend draft for retry. Do not publish it, send it to answer generation, or expose it to operators. The user can still request support using the existing approved transcript. An outage is not a profanity finding. If routing is unavailable or returns an invalid line, keep the suggested line empty and let the user select one explicitly; the backend does not invent a classification.

**Start with five tables.** Use UUIDs for users, chats, messages, and ratings; fixed IDs `1`, `2`, `3` for support lines; and UTC timestamps throughout.

| Table | Main fields and constraints |
| --- | --- |
| `users` | `id`, `login`, `password_hash`, `display_name`, `role` (`user`, `operator`, `admin`), nullable `support_line_id`. For the MVP, each operator belongs to one line. |
| `support_lines` | `id`, `name`, `description`. Seed exactly three entries. |
| `chats` | `id`, `user_id`, `status`, `suggested_line_id`, `handoff_reason`, actual `support_line_id`, nullable `operator_id`, `pending_ai_message_id`, `ai_deadline_at`, `created_at`, `updated_at`, `handed_off_at`, `assigned_at`, `closed_at`, `close_reason`, nullable `moderation_reason`. Suggested routing and accepted routing are distinct. |
| `messages` | `id`, `chat_id`, per-chat `sequence`, `sender_type`, nullable `sender_id`, `sender_name`, nullable `support_line_id`, `text`, optional `citations` JSON, nullable `reply_to_message_id`, nullable `client_message_id` and `input_hash`, `is_redacted`, `created_at`. Store the operator's line at send time for correct attribution. |
| `ratings` | `id`, `message_id`, `user_id`, integer `stars` constrained to `1..5`, optional `comment`, `created_at`, `updated_at`. Unique `(message_id, user_id)` so updating a rating replaces the previous value. |

Add indexes for chat owner/date, chat status/line, message chat/sequence, and rating target. Make `(chat_id, sequence)` unique and allocate message sequences while locking the chat row. Make non-null `(chat_id, client_message_id)` unique to deduplicate frontend retries. Only the chat owner can rate its AI/operator messages; user messages, redacted messages, and system notices are not rateable. A response rating measures that reply; do not present its average as a separate whole-chat satisfaction score.

Create missing tables directly from SQLAlchemy metadata with `uv run -m src.db.init`, and provide an idempotent seed command for three lines, demo users, one operator per line, and an admin. Per the updated requirement, do not maintain migrations. Initialization does not alter existing tables.

**Use a small authenticated REST API.** Seed demo accounts and implement token-based login with hashed passwords and expiring signed tokens. Read roles and line membership from the database. Registration, password reset, and supplier-portal SSO can follow later.

Paths below are application routes. The existing `app_root_path=/api` describes deployment behind a proxy; it is not the router prefix. Agree the public base URL with the frontend so `/api` is applied once. [FastAPI proxy documentation](https://fastapi.tiangolo.com/advanced/behind-a-proxy/)

| Endpoint | Purpose and access |
| --- | --- |
| `POST /auth/login` | Exchange a seeded account's login/password for an expiring access token. |
| `GET /auth/me` | Return the current user's role, public name, and operator line if applicable. |
| `GET /support-lines` | Return the three line IDs, names, and descriptions. |
| `POST /chats` | Create the current user's chat in `ai` state. |
| `GET /chats` | Paginated list of the current user's chats. |
| `GET /chats/{chat_id}` | Chat status, current recipient, support offer, pending AI status, and closure reason. Owner, assigned operator, or admin. |
| `GET /chats/{chat_id}/messages?after_sequence=...&limit=...` | Ordered transcript and incremental updates, with author metadata and the owner's rating on each reply. Same access rules as chat details. |
| `POST /chats/{chat_id}/messages` | Submit `{text, client_message_id}`. The backend obtains an AI moderation decision, then publishes approved input according to chat state. Assigned operators send human replies through the same endpoint. Return saved message(s) and updated chat state. |
| `POST /chats/{chat_id}/handoff-offer` | Owner requests support directly. Use AI routing on the latest approved question and history, store the suggestion, and return it with the three line choices. If there is no approved question or routing fails, return the line choices without a recommendation. |
| `POST /chats/{chat_id}/handoff` | Owner confirms `{support_line_id}`; use the stored AI suggestion when omitted. If neither exists, require an explicit line selection. Set `waiting_operator` and add a visible system notice. A repeated request to the same waiting line returns the existing result. |
| `POST /chats/{chat_id}/close` | Owner or assigned operator closes the chat with a permitted reason. Only the backend can set a moderation closure, following an AI-service `block` decision. |
| `PUT /messages/{message_id}/rating` | Owner creates or updates `{stars: 1..5, comment?: string}` for a delivered AI/operator reply. |
| `GET /operator/chats?status=...` | An operator's line's waiting chats and chats currently assigned to that operator. Waiting entries show enough metadata to choose a chat; claiming grants transcript access. |
| `POST /operator/chats/{chat_id}/claim` | Claim a waiting chat from the operator's line. Set the operator and add a visible “operator joined” notice. |
| `GET /admin/chats` | Admin-only paginated list of all chats; filter by date, status, line, and operator. Reuse chat details/messages endpoints to inspect a selected chat. |
| `GET /admin/ratings` | Admin-only rating/comment list; filter by stars, AI/operator author, line, or operator, with links back to the relevant chat/message. |
| `GET /admin/stats?from=...&to=...` | Admin-only chat and rating aggregates for the selected period. |
| `GET /admin/ai-health` | Admin diagnostic proxy for the neighboring AI service's readiness endpoint. |
| `GET /ping` | Keep the existing backend/database health check. |

Enforce ownership and operator assignment on every read/write endpoint. Clients cannot choose their sender identity or role. Both handoff endpoints apply only in `ai` or `handoff_offered`, except for an idempotent repeat of an accepted handoff. Claim a chat with a conditional database update so two operators cannot acquire it: one succeeds, the other gets `409`. Closing an already closed chat is harmless. A new message in a closed chat gets `409`. Use shared validation limits, initially 4,000 characters for a message and 2,000 for a rating comment, plus bounded pagination.

While a chat is open, the frontend polls chat details and messages every roughly two seconds. The operator screen polls its waiting list similarly. The backend's “queue” is a database query for `waiting_operator` chats ordered by `handed_off_at`; it does not require a queue service.

**Require three capability endpoints and a health endpoint from the AI service.** Keep the AI service stateless with respect to conversations: the backend sends context and stores the result. The service decides whether text is allowed, whether it can answer, and which support line fits the request. The backend owns database writes, user confirmation, waiting lists, and individual operator assignment.

| AI endpoint | Description |
| --- | --- |
| `POST /v1/moderate` | Check one user message for profanity. Return `allow` or `block` and a reason code. Called before answer generation or delivery to an operator, including while the chat is waiting in a support line. |
| `POST /v1/answer` | Given an approved question and recent approved history, return a grounded answer with source metadata or an explicit `no_answer` result. |
| `POST /v1/route` | Given an approved question, history, and the three support-line descriptions, return the recommended line ID. Called after `no_answer`, after an answer-generation failure, or when the user requests support directly. |
| `GET /health` | Report readiness of moderation, answering, and routing, including the model/index. Return `200` when all required capabilities are ready and `503` otherwise, with component statuses for diagnosis. Use for startup/demo diagnostics, not as an extra call before every message. |

The normal AI path calls moderation, then answering. Routing is called only when a support offer is needed. In operator mode, user messages call moderation only. Separate endpoints allow moderation and routing to remain usable when answer generation fails, where the AI service's own implementation permits it.

Example request to `POST /v1/moderate` (generate a request UUID before storing a message):

```json
{
  "request_id": "uuid-for-this-submission",
  "message": "The user's original message"
}
```

A blocked response uses HTTP `200`:

```json
{
  "request_id": "uuid-for-this-submission",
  "decision": "block",
  "reason": "profanity"
}
```

An allowed response uses the same shape with `decision: "allow"` and `reason: null`. For the MVP, `profanity` is the only blocking reason. A valid `block` is a business decision; non-2xx responses, timeouts, malformed responses, or mismatched request IDs mean moderation is unavailable, not that the text is prohibited.

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

Technical failures use non-2xx responses. For answering, timeout, malformed JSON, mismatched request IDs, unknown outcomes, and an empty `answered` response trigger a support offer and a bounded routing attempt. Routing failure leaves the recommendation empty and presents the three line choices. Moderation failure leaves the message undelivered and the chat open. Agree separate configurable timeouts with the AI team: short budgets for moderation and routing, a longer budget for answering, and a frontend timeout exceeding the combined request budget. No automatic AI retries are necessary for the demo.

**Call the AI endpoints synchronously from the request handler, with short database transactions.** Authenticate, validate input, and check for an existing `client_message_id` before calling moderation. On its return, lock and recheck the chat: a block closes an active chat atomically with the redacted message and notice; an allowed message is saved and either delivered to human support or marked pending for an AI answer. A chat closed during moderation receives no new message. Never hold a database transaction open during an HTTP call.

For answering and any subsequent routing, commit the approved message and pending marker first, with a deadline covering both calls. Lock the chat briefly again to save the answer or support offer and clear the marker. While an answer is pending, reject another approved AI question with `409`; a moderation block still closes the chat. Continue to allow closing or requesting support. Before publishing an answer or routing result, check that the pending message still matches and the chat remains in AI mode.

A direct `/handoff-offer` request clears the pending answer, sets `handoff_offered`, and obtains a line recommendation from the approved transcript. Store a returned recommendation only if the chat is still awaiting that offer and the latest approved question has not changed. Accepting support or closing the chat invalidates outstanding answer/routing results. User messages in `waiting_operator` or `operator` mode are published only after moderation allows them.

A repeated `client_message_id` returns the existing saved result or pending status rather than creating another message. Reusing the ID for different text gets `409`; store an input hash alongside the ID so this comparison also works for redacted messages. If moderation was unavailable, nothing was saved and the same submission can be retried. If the API stops during answering/routing, the next chat read/write converts an expired pending marker into a technical-failure support offer without a recommended line. The user can select a line or request a fresh suggestion. This small recovery check avoids leaving a chat permanently “thinking” without introducing a worker. Save the offer state and notice together so polling/retries do not create duplicates.

Configure the AI base URL, internal service token, and moderation/answer/routing timeouts in `ApiSettings`, then regenerate the settings schema/example. Use one async HTTP client owned by the FastAPI lifespan, with `moderate`, `answer`, and `route` methods. The AI service must run on team-controlled infrastructure: the case prohibits external search/LLM APIs in the solution (PDF pages 6–7).

**Start admin reporting with direct SQL aggregates.**

| Metric | Definition |
| --- | --- |
| Chat volume | Total created chats, counts by current status, and closed counts split by closure reason. |
| Support workload | Chats handed to each line, currently waiting chats, and currently assigned chats per operator. |
| AI vs human activity | Counts of delivered AI and operator replies, excluding system notices and redacted messages. These are activity counts, not proof that the issue was resolved. |
| Response quality | Rating count, mean stars, and histogram for stars 1–5; group by AI/operator, individual operator, and the reply's support line. Always show sample size with the average. |
| Feedback to inspect | Low ratings (1–2 stars) with their comments and original messages. Treat 3 as neutral and 4–5 as positive for simple reporting. |

For chat metrics, apply `[from, to)` to `chats.created_at`; for reply activity, use `messages.created_at`; for rating metrics, apply it to `ratings.created_at` and use the current saved rating value. Return the reporting period and denominators. Queue counts are a current snapshot and should be labeled separately from period counts. Aggregate chats and ratings separately to avoid counting one chat multiple times after joining its messages. Attribute ratings to the message's original author and line. Use UTC storage and let the frontend display local time.

Average waiting time and resolution time are useful follow-ups once the core demo works. Whole-chat ratings, transfer history, multiple line memberships, full-text search, exports, and elaborate dashboards can also wait.

The full case additionally asks for substantive conclusions from positive/negative feedback (PDF pages 3 and 5; evaluation on page 9). Stars and basic statistics are the requested first step. An **optional later AI endpoint**, `POST /v1/feedback/analyze`, could accept a bounded set of `{feedback_id, stars, comment, response_text, support_line_id}` and return a summary plus recurring issues tied to feedback IDs. Add it only if that capability is included in the AI team's scope; it is not required for this MVP's chat flow. The backend can supply filtered reviews and display the returned report without implementing analysis itself.

**Implement in this order, finishing a demonstrable flow at each step.**

| Step | Backend work | Done when |
| --- | --- | --- |
| 1. Foundation | Five models, schema initialization, demo seed data, login, role/ownership dependencies, shared schemas. | Each demo role can authenticate; unauthorized chat/admin access is rejected. |
| 2. Chat and moderation integration | Create/list/read chats, message history, `/v1/moderate` client and stub, closure, author/recipient metadata. | Allowed input persists; a block closes the chat without calling answering/routing; a moderation outage leaves input undelivered and allows retry. |
| 3. Answering and routing integration | Agree `/v1/answer` and `/v1/route`, extend the HTTP adapter and stub, save answer/source metadata and routing suggestions, handle failures, implement pending marker and retry deduplication. | An answer, an AI-selected support line after no-answer, and manual line selection after a routing failure can all be demonstrated with the stub. |
| 4. Human support | Three waiting lists, consent-based handoff, atomic claim, operator replies, continued moderation of user messages, closure, polling responses. | The user sees the selected line, then a named operator; the transcript survives handoff and new user messages still pass moderation. |
| 5. Feedback and admin | Rating upsert, admin chat/review lists, filters, SQL statistics. | An admin can trace a low rating to its reply and compare AI/operator ratings without duplicate counts. |
| 6. Demo preparation | Replace the stub with the neighboring service, verify the main flows, document startup and API examples. | Known question, unknown question, correct line recommendation, service failures, profanity closure, handoff, and rating/reporting all work. |

Place business logic in a small `src/services/` package (`chats`, `ai_client`, `support`, `stats`). The `ai_client` wraps the three capability endpoints; chat logic applies their decisions. Keep HTTP handlers in the existing `src/api/repositories/` convention, database access in `src/db/repositories/`, models in `src/db/models/`, and request/response schemas in `src/schemas/`. Add schema initialization and seed/stub utilities without a larger architectural reorganization.

Before the demo, verify the failures that affect this workflow: a user cannot access another user's chat; an operator cannot claim another line's chat; two operators cannot claim one chat; a moderation block closes the chat and never reaches answering, routing, or an operator; unavailable moderation leaves the chat open and input undelivered; no-answer and answer timeouts trigger routing and a support offer; invalid or unavailable routing requires manual line selection; user messages continue through moderation after handoff; late answer/routing results cannot change a handed-off or closed chat; ratings validate their target and range; duplicate sends/ratings do not duplicate data. Use an AI stub with independent moderation allow/block/error, answer answered/no-answer/error, and routing line-1/2/3/invalid/error modes, plus delays, and a disposable PostgreSQL database for these checks. Check Russian profanity examples and innocent near-matches against the real moderation service with the AI team. The presentation also requires a BPMN process diagram; draw the implemented user/backend/AI/operator workflow for the team presentation after it is stable.
