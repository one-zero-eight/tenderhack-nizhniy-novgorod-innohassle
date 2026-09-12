import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from sqlalchemy import select

from src.api.app import create_app
from src.db.models import Chat, User, utcnow
from src.seed import seed_demo


async def test_auth_and_permissions(case):
    assert (await case.client.get("/chats")).status_code == 401
    bad = await case.client.post("/auth/login", json={"login": "user", "password": "wrong"})
    assert bad.status_code == 401
    valid = await case.client.post("/auth/login", json={"login": "user", "password": "test-user-password"})
    assert valid.status_code == 200
    token = valid.json()["access_token"]
    me = await case.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["role"] == "user"
    assert "password_hash" not in me.json()

    # Public registration
    reg = await case.client.post(
        "/auth/register",
        json={"login": "newuser", "password": "newpassword123", "display_name": "Новый Пользователь"},
    )
    assert reg.status_code == 201
    new_token = reg.json()["access_token"]
    new_me = await case.client.get("/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert new_me.json()["login"] == "newuser"
    assert new_me.json()["display_name"] == "Новый Пользователь"
    assert new_me.json()["role"] == "user"

    # Duplicate registration conflict
    dup = await case.client.post("/auth/register", json={"login": "newuser", "password": "newpassword123"})
    assert dup.status_code == 409
    assert (await case.request("GET", "/admin/stats")).status_code == 403
    assert (await case.request("GET", "/operator/chats")).status_code == 403
    assert (await case.request("POST", "/chats", login="admin")).status_code == 403
    expired = jwt.encode(
        {
            "sub": str(case.users["admin"].id),
            "iat": utcnow() - timedelta(hours=2),
            "exp": utcnow() - timedelta(hours=1),
            "iss": "tenderhack-backend",
            "aud": "tenderhack-web",
        },
        case.settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    assert (await case.client.get("/admin/stats", headers={"Authorization": f"Bearer {expired}"})).status_code == 401
    chat = await case.chat()
    for method, suffix, kwargs in [
        ("GET", "", {}),
        ("GET", "/messages", {}),
        ("POST", "/handoff", {"json": {"support_line_id": 1}}),
    ]:
        assert (await case.request(method, f"/chats/{chat}{suffix}", login="user2", **kwargs)).status_code == 404
    assert (await case.request("GET", f"/chats/{chat}", login="admin")).status_code == 200
    assert (await case.request("GET", "/admin/ai-health", login="admin")).json()["status"] == "ready"


async def test_answer_idempotency_ratings_and_stats(case):
    chat = await case.chat()
    client_id = str(uuid4())
    sent = await case.send(chat, client_id=client_id)
    assert sent.status_code == 200, sent.text
    messages = sent.json()["messages"]
    assert [message["sender_type"] for message in messages] == ["user", "ai"]
    assert sent.json()["chat"]["recipient"]["kind"] == "ai"
    repeated = await case.send(chat, client_id=client_id)
    assert repeated.json()["messages"] == messages
    assert any("/ml-api/chat" in call[0] for call in case.ai.calls)
    assert (await case.send(chat, "Changed text", client_id=client_id)).status_code == 409
    assert (await case.request("PUT", f"/messages/{messages[0]['id']}/rating", json={"stars": 5})).status_code == 422
    reply = messages[1]["id"]
    assert (await case.request("PUT", f"/messages/{reply}/rating", login="user2", json={"stars": 5})).status_code == 404
    for stars in [0, 6, True, "5"]:
        assert (await case.request("PUT", f"/messages/{reply}/rating", json={"stars": stars})).status_code == 422
    assert (await case.request("POST", f"/chats/{chat}/close", json={"reason": "resolved"})).status_code == 200
    first = await case.request("PUT", f"/messages/{reply}/rating", json={"stars": 5, "comment": "Good"})
    updated = await case.request("PUT", f"/messages/{reply}/rating", json={"stars": 2, "comment": "Needs detail"})
    assert first.json()["id"] == updated.json()["id"]
    stats = (await case.request("GET", "/admin/stats", login="admin")).json()
    assert stats["chats"]["total"] == 1
    assert stats["chats"]["by_close_reason"] == {"resolved": 1}
    assert stats["activity"] == {"ai": 1, "operator": 0}
    assert stats["ratings"]["count"] == 1
    assert stats["ratings"]["average"] == 2
    assert stats["ratings"]["histogram"]["2"] == 1
    reviews = await case.request("GET", "/admin/ratings?stars_lte=2", login="admin")
    assert reviews.json()["items"][0]["chat_id"] == chat
    assert reviews.json()["items"][0]["comment"] == "Needs detail"
    first_page = (await case.request("GET", f"/chats/{chat}/messages?limit=1")).json()
    second_page = (
        await case.request("GET", f"/chats/{chat}/messages?after_sequence={first_page['next_sequence']}")
    ).json()
    assert first_page["has_more"] is True
    assert second_page["items"][0]["id"] == reply
    assert second_page["items"][0]["rating"]["stars"] == 2
    assert (await case.send(chat, "After closure")).status_code == 409


async def test_block_closes_and_redacts_before_answering(case):
    chat, client_id = await case.chat(), str(uuid4())
    response = await case.send(chat, "[block] forbidden text", client_id=client_id)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["chat"]["status"] == "closed"
    assert result["chat"]["close_reason"] == "moderation"
    assert result["messages"][0]["is_redacted"] is True
    assert "forbidden text" not in str(result)
    assert case.ai.calls == []
    repeated = await case.send(chat, "[block] forbidden text", client_id=client_id)
    assert repeated.json()["messages"] == result["messages"]
    assert case.ai.calls == []
    assert len(case.moderator.calls) == 1
    assert (await case.send(chat, "[block] different", client_id=client_id)).status_code == 409


async def test_moderation_outage_keeps_draft_and_allows_retry(case):
    chat, client_id = await case.chat(), str(uuid4())
    case.moderator.error = True
    response = await case.send(chat, client_id=client_id)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "MODERATION_UNAVAILABLE"
    assert (await case.request("GET", f"/chats/{chat}")).json()["status"] == "ai"
    assert (await case.request("GET", f"/chats/{chat}/messages")).json()["items"] == []
    case.moderator.error = False
    assert (await case.send(chat, client_id=client_id)).status_code == 200


async def test_closing_during_local_moderation_does_not_publish(case):
    chat = await case.chat()
    case.moderator.hold = True
    pending = asyncio.create_task(case.send(chat))
    try:
        await asyncio.wait_for(case.moderator.started.wait(), timeout=2)
        closed = await case.request("POST", f"/chats/{chat}/close", json={"reason": "user_cancelled"})
        assert closed.status_code == 200
    finally:
        case.moderator.release.set()
    assert (await pending).status_code == 409
    assert case.ai.calls == []
    transcript = (await case.request("GET", f"/chats/{chat}/messages")).json()["items"]
    assert all(message["sender_type"] == "system" for message in transcript)


async def test_waiting_chat_uses_only_local_moderation(case):
    chat = await case.chat()
    await case.request("POST", f"/chats/{chat}/handoff", json={"support_line_id": 1})
    assert (await case.send(chat)).status_code == 200
    assert len(case.moderator.calls) == 1
    assert case.ai.calls == []
    blocked = await case.send(chat, "[block]")
    assert blocked.json()["chat"]["close_reason"] == "moderation"
    assert case.ai.calls == []


@pytest.mark.parametrize(
    "mode,reason", [("error", "ai_unavailable"), ("timeout", "ai_unavailable")]
)
async def test_failure_offers_ai_selected_line(case, mode, reason):
    case.ai.answer_mode = mode
    chat = await case.chat()
    response = await case.send(chat)
    assert response.status_code == 200, response.text
    result = response.json()["chat"]
    assert result["status"] == "handoff_offered"
    assert result["suggested_line"] is None
    assert result["support_line"] is None
    assert result["handoff_reason"] == reason


@pytest.mark.parametrize("invalid_line", [0, 4, True, "2", None])
async def test_invalid_routing_requires_manual_choice(case, invalid_line):
    case.ai.answer_mode = "error"
    chat = await case.chat()
    assert (await case.send(chat)).json()["chat"]["suggested_line"] is None
    assert (await case.request("POST", f"/chats/{chat}/handoff", json={})).status_code == 422
    accepted = await case.request("POST", f"/chats/{chat}/handoff", json={"support_line_id": 3})
    assert accepted.json()["status"] == "waiting_operator"
    assert accepted.json()["recipient"]["support_line"]["id"] == 3


async def test_operator_handoff_moderation_and_identity(case):
    chat = await case.chat()
    await case.send(chat)
    offer = await case.request("POST", f"/chats/{chat}/handoff-offer")
    assert offer.json()["chat"]["suggested_line"] is None
    accepted = await case.request("POST", f"/chats/{chat}/handoff", json={"support_line_id": 2})
    assert accepted.json()["recipient"]["kind"] == "support_queue"
    assert (await case.request("GET", f"/chats/{chat}/messages", login="operator2")).status_code == 404
    assert (await case.request("GET", "/operator/chats", login="operator1")).json()["total"] == 0
    assert (await case.request("GET", "/operator/chats", login="operator2")).json()["total"] == 1
    assert (await case.request("POST", f"/operator/chats/{chat}/claim", login="operator1")).status_code == 403
    claimed = await case.request("POST", f"/operator/chats/{chat}/claim", login="operator2")
    assert claimed.json()["recipient"]["operator"]["id"] == str(case.users["operator2"].id)
    calls = len(case.ai.calls)
    human = await case.send(chat, "An operator's answer", login="operator2")
    assert human.status_code == 200, human.text
    assert len(case.ai.calls) == calls
    assert human.json()["messages"][0]["sender_type"] == "operator"
    assert human.json()["messages"][0]["support_line_id"] == 2
    assert (await case.send(chat, "Another question")).status_code == 200
    assert len(case.ai.calls) == calls
    assert case.moderator.calls[-1] == "Another question"
    case.moderator.error = True
    assert (await case.send(chat, "Keep this as a draft")).status_code == 503
    case.moderator.error = False
    blocked = await case.send(chat, "[block] during operator chat")
    assert blocked.json()["chat"]["close_reason"] == "moderation"
    transcript = (await case.request("GET", f"/chats/{chat}/messages")).json()["items"]
    assert any(message["sender_type"] == "ai" for message in transcript)
    assert not any(message["text"] == "Keep this as a draft" for message in transcript)
    assert (await case.send(chat, "Late operator reply", login="operator2")).status_code == 409


async def test_claim_is_atomic(case):
    async with case.storage.create_session() as session, session.begin():
        competitor = await session.get(User, case.users["operator3"].id)
        competitor.support_line_id = 2
    chat = await case.chat()
    await case.request("POST", f"/chats/{chat}/handoff", json={"support_line_id": 2})
    responses = await asyncio.gather(
        *[case.request("POST", f"/operator/chats/{chat}/claim", login=login) for login in ("operator2", "operator3")]
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = responses[0].json() if responses[0].status_code == 200 else responses[1].json()
    state = (await case.request("GET", f"/chats/{chat}")).json()
    assert state["operator"]["id"] == winner["operator"]["id"]


@pytest.mark.parametrize("interrupt", ["handoff", "block", "close", "expire"])
async def test_late_answer_cannot_change_interrupted_chat(case, interrupt):
    chat, client_id = await case.chat(), str(uuid4())
    case.ai.hold = "/ml-api/chat/test-ml-chat-1/message"
    task = asyncio.create_task(case.send(chat, client_id=client_id))
    try:
        await asyncio.wait_for(case.ai.started.wait(), timeout=2)
        repeated = await case.send(chat, client_id=client_id)
        assert repeated.json()["chat"]["ai_pending"] is True
        assert (await case.send(chat, "A second clean question")).status_code == 409
        if interrupt == "handoff":
            response = await case.request("POST", f"/chats/{chat}/handoff", json={"support_line_id": 1})
            expected = "waiting_operator"
        elif interrupt == "block":
            response = await case.send(chat, "[block]")
            expected = "closed"
        elif interrupt == "close":
            response = await case.request("POST", f"/chats/{chat}/close", json={"reason": "user_cancelled"})
            expected = "closed"
        else:
            async with case.storage.create_session() as session, session.begin():
                row = await session.get(Chat, UUID(chat))
                row.ai_deadline_at = utcnow() - timedelta(seconds=1)
            response = await case.request("GET", f"/chats/{chat}")
            expected = "handoff_offered"
        assert response.status_code == 200, response.text
        case.ai.release.set()
        finished = await task
        assert finished.json()["chat"]["status"] == expected
        assert finished.json()["chat"]["ai_pending"] is False
        transcript = (await case.request("GET", f"/chats/{chat}/messages")).json()["items"]
        assert not any(message["sender_type"] == "ai" for message in transcript)
        if interrupt == "expire":
            again = (await case.request("GET", f"/chats/{chat}/messages")).json()["items"]
            assert len(again) == len(transcript) == 2
    finally:
        case.ai.release.set()
        await task


async def test_direct_support_without_question_and_seed_idempotency(case):
    chat = await case.chat()
    offer = await case.request("POST", f"/chats/{chat}/handoff-offer")
    assert len(offer.json()["support_lines"]) == 3
    assert offer.json()["chat"]["suggested_line"] is None
    assert case.ai.calls == []
    await seed_demo(case.storage, "a-different-password")
    async with case.storage.create_session() as session:
        users = list(await session.scalars(select(User)))
    assert len(users) == 6
    assert (
        await case.client.post("/auth/login", json={"login": "user", "password": "test-user-password"})
    ).status_code == 200


async def test_admin_periods_and_history_exclude_notices(case):
    chat = await case.chat()
    response = await case.send(chat, "Try a question")
    assert response.json()["chat"]["status"] == "ai"
    assert response.json()["chat"]["suggested_line"] is None
    stats = await case.request("GET", "/admin/stats", login="admin", params={"from": "2100-01-01T00:00:00Z"})
    assert stats.json()["chats"]["total"] == 0
    assert stats.json()["ratings"]["average"] is None
    assert (
        await case.request(
            "GET",
            "/admin/stats",
            login="admin",
            params={
                "from": "2026-10-01T00:00:00Z",
                "to": "2026-01-01T00:00:00Z",
            },
        )
    ).status_code == 422
    assert (await case.request("GET", "/admin/stats?from=2026-01-01", login="admin")).status_code == 422


async def test_concurrent_duplicate_submission_creates_one_answer(case):
    chat, client_id = await case.chat(), str(uuid4())
    replies = await asyncio.gather(case.send(chat, client_id=client_id), case.send(chat, client_id=client_id))
    assert all(reply.status_code == 200 for reply in replies)
    transcript = (await case.request("GET", f"/chats/{chat}/messages")).json()["items"]
    assert [message["sender_type"] for message in transcript] == ["user", "ai"]
    assert [message["sequence"] for message in transcript] == [1, 2]
    assert len([call for call in case.ai.calls if "/message" in call[0]]) == 1


async def test_routing_outage_and_human_rating_attribution(case):
    case.ai.answer_mode = "error"
    chat = await case.chat()
    result = await case.send(chat)
    assert result.json()["chat"]["suggested_line"] is None
    await case.request("POST", f"/chats/{chat}/handoff", json={"support_line_id": 2})
    await case.request("POST", f"/operator/chats/{chat}/claim", login="operator2")
    response = await case.send(chat, "Human reply", login="operator2")
    message_id = response.json()["messages"][0]["id"]
    assert (
        await case.request("POST", f"/chats/{chat}/close", login="operator2", json={"reason": "user_cancelled"})
    ).status_code == 403
    assert (
        await case.request("POST", f"/chats/{chat}/close", login="operator2", json={"reason": "resolved"})
    ).status_code == 200
    ratings = await asyncio.gather(
        *[case.request("PUT", f"/messages/{message_id}/rating", json={"stars": score}) for score in (4, 5)]
    )
    assert all(rating.status_code == 200 for rating in ratings)
    assert ratings[0].json()["id"] == ratings[1].json()["id"]
    async with case.storage.create_session() as session, session.begin():
        operator = await session.get(User, case.users["operator2"].id)
        operator.support_line_id = 3
    stats = (await case.request("GET", "/admin/stats", login="admin")).json()
    assert stats["ratings"]["count"] == 1
    assert stats["ratings"]["by_support_line"][0]["key"] == "2"
    assert stats["ratings"]["by_operator"][0]["key"] == str(case.users["operator2"].id)
    assert stats["chats"]["total"] == 1
    assert stats["activity"] == {"ai": 0, "operator": 1}
    reviews = (await case.request("GET", "/admin/ratings?line_id=2&sender_type=operator", login="admin")).json()
    assert reviews["total"] == 1


async def test_chat_list_recovers_expired_answer_before_status_filter(case):
    chat = await case.chat()
    sent = await case.send(chat)
    question_id = UUID(sent.json()["messages"][0]["id"])
    async with case.storage.create_session() as session, session.begin():
        row = await session.get(Chat, UUID(chat))
        row.pending_ai_message_id = question_id
        row.ai_deadline_at = utcnow() - timedelta(seconds=1)
    page = await case.request("GET", "/chats?status=handoff_offered")
    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert page.json()["items"][0]["ai_pending"] is False
    transcript = (await case.request("GET", f"/chats/{chat}/messages")).json()["items"]
    await case.request("GET", "/admin/chats", login="admin")
    repeated = (await case.request("GET", f"/chats/{chat}/messages")).json()["items"]
    assert repeated == transcript
    assert transcript[-1]["sender_type"] == "system"


async def test_admin_exact_star_filter(case):
    chat = await case.chat()
    for stars in (1, 2, 5):
        response = await case.send(chat)
        reply = response.json()["messages"][1]["id"]
        await case.request("PUT", f"/messages/{reply}/rating", json={"stars": stars})
    exact = await case.request("GET", "/admin/ratings?stars=2", login="admin")
    assert exact.status_code == 200
    assert exact.json()["total"] == 1
    assert exact.json()["items"][0]["stars"] == 2
    low = await case.request("GET", "/admin/ratings?stars_lte=2", login="admin")
    assert low.json()["total"] == 2
    assert (await case.request("GET", "/admin/ratings?stars=6", login="admin")).status_code == 422


async def test_schema_initialization_preserves_existing_data(case):
    chat = await case.chat()
    restarted = create_app(case.settings)
    async with restarted.router.lifespan_context(restarted):
        assert (await case.request("GET", f"/chats/{chat}")).status_code == 200
    assert (await case.request("GET", "/support-lines")).json()[0]["id"] == 1
