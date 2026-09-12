import asyncio
import logging
from datetime import timedelta
from uuid import uuid4

import jwt
from sqlalchemy import select

from src.api.app import create_app
from src.db.models import SupportLine, User, utcnow


async def test_auth_and_permissions(case):
    assert (await case.client.get("/chats")).status_code == 401
    bad = await case.client.post("/auth/login", json={"login": "user", "password": "wrong"})
    assert bad.status_code == 401
    valid = await case.client.post("/auth/login", json={"login": "user", "password": "test-user-password"})
    assert valid.status_code == 200
    token = valid.json()["access_token"]
    me = await case.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["role"] == "buyer"
    assert "password_hash" not in me.json()

    # Public registration (default role is buyer)
    reg = await case.client.post(
        "/auth/register",
        json={"login": "newuser", "password": "newpassword123", "display_name": "Новый Пользователь"},
    )
    assert reg.status_code == 201
    new_token = reg.json()["access_token"]
    new_me = await case.client.get("/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert new_me.json()["login"] == "newuser"
    assert new_me.json()["display_name"] == "Новый Пользователь"
    assert new_me.json()["role"] == "buyer"

    # Register as seller
    reg_seller = await case.client.post(
        "/auth/register",
        json={"login": "newseller", "password": "password123", "role": "seller"},
    )
    assert reg_seller.status_code == 201
    seller_me = (await case.client.get("/auth/me", headers={"Authorization": f"Bearer {reg_seller.json()['access_token']}"})).json()
    assert seller_me["role"] == "seller"

    # Register as support
    bad_support = await case.client.post(
        "/auth/register",
        json={"login": "badsupport", "password": "password123", "role": "support"},
    )
    assert bad_support.status_code == 400

    reg_support = await case.client.post(
        "/auth/register",
        json={"login": "newsupport", "password": "password123", "role": "support", "support_line_id": 2},
    )
    assert reg_support.status_code == 201
    support_me = (await case.client.get("/auth/me", headers={"Authorization": f"Bearer {reg_support.json()['access_token']}"})).json()
    assert support_me["role"] == "support"
    assert support_me["support_line_id"] == 2

    # Verify /support/chats works
    support_chats = await case.client.get("/support/chats", headers={"Authorization": f"Bearer {reg_support.json()['access_token']}"})
    assert support_chats.status_code == 200

    # Duplicate registration conflict
    dup = await case.client.post("/auth/register", json={"login": "newuser", "password": "newpassword123"})
    assert dup.status_code == 409
    assert (await case.request("GET", "/admin/stats")).status_code == 403
    assert (await case.request("GET", "/support/chats")).status_code == 403
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
    ]:
        assert (await case.request(method, f"/chats/{chat}{suffix}", login="user2", **kwargs)).status_code == 404
    assert (await case.request("GET", f"/chats/{chat}", login="admin")).status_code == 200


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
    reply = messages[1]["id"]
    assert (await case.request("PUT", f"/chats/{chat}/rating", login="user2", json={"stars": 5})).status_code == 404
    for stars in [0, 6, True, "5"]:
        assert (await case.request("PUT", f"/chats/{chat}/rating", json={"stars": stars})).status_code == 422
    await case.close_chat(chat, reason="resolved")
    first = await case.request("PUT", f"/chats/{chat}/rating", json={"stars": 5, "comment": "Good"})
    assert first.status_code == 200
    assert first.json()["chat_id"] == chat
    updated = await case.request("PUT", f"/chats/{chat}/rating", json={"stars": 2, "comment": "Needs detail"})
    assert first.json()["id"] == updated.json()["id"]
    assert updated.json()["stars"] == 2

    # Check chat detail and list include rating
    chat_detail = (await case.request("GET", f"/chats/{chat}")).json()
    assert chat_detail["rating"]["stars"] == 2
    assert chat_detail["rating"]["comment"] == "Needs detail"
    assert chat_detail["rating"]["chat_id"] == chat

    chats_list = (await case.request("GET", "/chats")).json()
    assert chats_list["items"][0]["rating"]["stars"] == 2

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
    assert [c for c in case.ai.calls if "/message" in c[0]] == []
    repeated = await case.send(chat, "[block] forbidden text", client_id=client_id)
    assert repeated.json()["messages"] == result["messages"]
    assert [c for c in case.ai.calls if "/message" in c[0]] == []
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
        await case.close_chat(chat, reason="user_cancelled")
    finally:
        case.moderator.release.set()
    assert (await pending).status_code == 409
    assert [c for c in case.ai.calls if "/message" in c[0]] == []
    transcript = (await case.request("GET", f"/chats/{chat}/messages")).json()["items"]
    assert all(message["sender_type"] == "system" for message in transcript)


async def test_waiting_chat_uses_only_local_moderation(case):
    chat = await case.chat()
    await case.transfer_to_operator(chat, 1)
    assert (await case.send(chat)).status_code == 200
    assert len(case.moderator.calls) == 1
    assert [c for c in case.ai.calls if "/message" in c[0]] == []
    blocked = await case.send(chat, "[block]")
    assert blocked.json()["chat"]["close_reason"] == "moderation"
    assert [c for c in case.ai.calls if "/message" in c[0]] == []


async def test_operator_handoff_moderation_and_identity(case):
    chat = await case.chat()
    await case.send(chat)
    await case.transfer_to_operator(chat, 2)
    assert (await case.request("GET", f"/chats/{chat}/messages", login="operator2")).status_code == 404
    assert (await case.request("GET", "/support/chats", login="operator1")).json()["total"] == 0
    assert (await case.request("GET", "/support/chats", login="operator2")).json()["total"] == 1
    assert (await case.request("POST", f"/support/chats/{chat}/claim", login="operator1")).status_code == 403
    claimed = await case.request("POST", f"/support/chats/{chat}/claim", login="operator2")
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
    await case.transfer_to_operator(chat, 2)
    responses = await asyncio.gather(
        *[case.request("POST", f"/support/chats/{chat}/claim", login=login) for login in ("operator2", "operator3")]
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = responses[0].json() if responses[0].status_code == 200 else responses[1].json()
    state = (await case.request("GET", f"/chats/{chat}")).json()
    assert state["operator"]["id"] == winner["operator"]["id"]


async def test_startup_preserves_support_lines_and_accounts(case):
    async with case.storage.create_session() as session, session.begin():
        line = await session.get(SupportLine, 1)
        line.name = "Custom support"
        line.description = "Configured responsibilities"
    await asyncio.gather(case.storage.create_all(), case.storage.create_all())
    lines = await case.request("GET", "/support-lines")
    assert len(lines.json()) == 3
    assert lines.json()[0] == {"id": 1, "name": "Custom support", "description": "Configured responsibilities"}
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


async def test_admin_get_all_chats(case):
    res1 = await case.request("POST", "/chats", login="user")
    assert res1.status_code == 201
    chat1 = res1.json()["id"]

    res2 = await case.request("POST", "/chats", login="user2")
    assert res2.status_code == 201
    chat2 = res2.json()["id"]

    # Regular user/operator should be denied access to admin endpoint
    assert (await case.request("GET", "/admin/chats", login="user")).status_code == 403
    assert (await case.request("GET", "/admin/chats", login="operator1")).status_code == 403

    # Admin gets all chats
    res = await case.request("GET", "/admin/chats", login="admin")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 2
    chat_ids = [c["id"] for c in data["items"]]
    assert chat1 in chat_ids
    assert chat2 in chat_ids

    # Verify user display_name returned in GET /admin/chats
    chat1_data = next(c for c in data["items"] if c["id"] == chat1)
    chat2_data = next(c for c in data["items"] if c["id"] == chat2)
    assert chat1_data["user_display_name"] == case.users["user"].display_name
    assert chat1_data["display_name"] == case.users["user"].display_name
    assert chat1_data["user"]["id"] == str(case.users["user"].id)
    assert chat1_data["user"]["display_name"] == case.users["user"].display_name

    assert chat2_data["user_display_name"] == case.users["user2"].display_name
    assert chat2_data["display_name"] == case.users["user2"].display_name
    assert chat2_data["user"]["id"] == str(case.users["user2"].id)
    assert chat2_data["user"]["display_name"] == case.users["user2"].display_name

    # Admin filters by user_id
    user1_id = str(case.users["user"].id)
    res_user1 = await case.request("GET", f"/admin/chats?user_id={user1_id}", login="admin")
    assert res_user1.status_code == 200
    user1_chats = res_user1.json()
    assert all(c["user_id"] == user1_id for c in user1_chats["items"])
    assert all(c["user_display_name"] == case.users["user"].display_name for c in user1_chats["items"])
    assert chat1 in [c["id"] for c in user1_chats["items"]]
    assert chat2 not in [c["id"] for c in user1_chats["items"]]



async def test_concurrent_duplicate_submission_creates_one_answer(case):
    chat, client_id = await case.chat(), str(uuid4())
    replies = await asyncio.gather(case.send(chat, client_id=client_id), case.send(chat, client_id=client_id))
    assert all(reply.status_code == 200 for reply in replies)
    transcript = (await case.request("GET", f"/chats/{chat}/messages")).json()["items"]
    assert [message["sender_type"] for message in transcript] == ["user", "ai"]
    assert [message["sequence"] for message in transcript] == [1, 2]
    assert len([call for call in case.ai.calls if "/message" in call[0]]) == 1


async def test_routing_outage_and_human_rating_attribution(case, caplog):
    caplog.set_level(logging.WARNING)
    logging.getLogger("src").addHandler(caplog.handler)
    case.ai.answer_mode = "error"
    chat = await case.chat()
    result = await case.send(chat)
    assert result.status_code == 200
    assert "AI service unavailable for chat" in caplog.text
    await case.transfer_to_operator(chat, 2)
    await case.request("POST", f"/support/chats/{chat}/claim", login="operator2")
    await case.send(chat, "Human reply", login="operator2")
    await case.close_chat(chat, reason="resolved", login="operator2")
    ratings = await asyncio.gather(
        *[case.request("PUT", f"/chats/{chat}/rating", json={"stars": score}) for score in (4, 5)]
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


async def test_admin_exact_star_filter(case):
    for stars in (1, 2, 5):
        chat = await case.chat()
        await case.send(chat)
        await case.request("PUT", f"/chats/{chat}/rating", json={"stars": stars})
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


async def test_knowledge_base_proxy_endpoints(case):
    res = await case.client.get("/ml-api/knowledge-base")
    assert res.status_code == 200, res.text
    manuals = res.json()
    assert isinstance(manuals, list)
    assert len(manuals) >= 1
    assert manuals[0]["slug"] == "instrukciya-po-sozdaniyu-oferty-i-ste"

    # Verify alias is removed
    assert (await case.client.get("/knowledge-base")).status_code == 404

    res = await case.client.get("/ml-api/knowledge-base/instrukciya-po-sozdaniyu-oferty-i-ste")
    assert res.status_code == 200, res.text
    structure = res.json()
    assert structure["slug"] == "instrukciya-po-sozdaniyu-oferty-i-ste"
    assert len(structure["sections"]) >= 1

    res = await case.client.get("/ml-api/knowledge-base/instrukciya-po-sozdaniyu-oferty-i-ste/1")
    assert res.status_code == 200, res.text
    section = res.json()
    assert section["id"] == "1"
    assert "content_md" in section

    res_404 = await case.client.get("/ml-api/knowledge-base/not-found")
    assert res_404.status_code == 404


async def test_chat_rating_returned_in_all_endpoints(case):
    chat = await case.chat()
    # 1. New chat has no rating
    detail = (await case.request("GET", f"/chats/{chat}")).json()
    assert detail["rating"] is None

    # 2. Rate chat
    rate_res = await case.request("PUT", f"/chats/{chat}/rating", json={"stars": 5, "comment": "Отличный ответ"})
    assert rate_res.status_code == 200
    assert rate_res.json()["stars"] == 5
    assert rate_res.json()["sender_type"] == "ai"

    # 3. GET /chats/{chat_id} returns rating
    detail = (await case.request("GET", f"/chats/{chat}")).json()
    assert detail["rating"]["stars"] == 5
    assert detail["rating"]["comment"] == "Отличный ответ"
    assert detail["rating"]["sender_type"] == "ai"

    # 4. GET /chats returns rating
    chats_list = (await case.request("GET", "/chats")).json()
    assert chats_list["items"][0]["rating"]["stars"] == 5

    # 5. transfer to operator
    await case.transfer_to_operator(chat, 1)
    req_op = (await case.request("GET", f"/chats/{chat}")).json()
    assert req_op["status"] == "waiting_operator"
    assert req_op["rating"]["stars"] == 5

    # 6. GET /support/chats returns rating
    op_chats = (await case.request("GET", "/support/chats", login="operator1")).json()
    assert op_chats["items"][0]["rating"]["stars"] == 5

    # 7. POST /support/chats/{chat_id}/claim returns rating
    claimed = (await case.request("POST", f"/support/chats/{chat}/claim", login="operator1")).json()
    assert claimed["status"] == "operator"
    assert claimed["rating"]["stars"] == 5

    # Re-rate chat with operator attribution
    re_rate = await case.request("PUT", f"/chats/{chat}/rating", json={"stars": 4, "comment": "Оператор помог"})
    assert re_rate.status_code == 200
    assert re_rate.json()["stars"] == 4
    assert re_rate.json()["sender_type"] == "operator"

    # 8. close chat returns rating
    await case.close_chat(chat, reason="resolved", login="operator1")
    closed = (await case.request("GET", f"/chats/{chat}")).json()
    assert closed["status"] == "closed"
    assert closed["rating"]["stars"] == 4
    assert closed["rating"]["comment"] == "Оператор помог"
    assert closed["rating"]["sender_type"] == "operator"

    # 9. GET /admin/chats returns rating
    admin_chats = (await case.request("GET", "/admin/chats", login="admin")).json()
    assert admin_chats["items"][0]["rating"]["stars"] == 4


async def test_chat_topic_and_subtopic_sync_and_filtering(case):
    chat = await case.chat()
    # 1. Initial chat has None for topic and subtopic
    detail = (await case.request("GET", f"/chats/{chat}")).json()
    assert detail["topic"] is None
    assert detail["subtopic"] is None

    # 2. Simulate ML classifier assigning topic and subtopic
    case.ai.chats[chat]["topic"] = "Закупки и котировочные сессии"
    case.ai.chats[chat]["subtopic"] = "Создание оферты"

    # 3. GET /chats/{chat} syncs and returns topic and subtopic
    synced = (await case.request("GET", f"/chats/{chat}")).json()
    assert synced["topic"] == "Закупки и котировочные сессии"
    assert synced["subtopic"] == "Создание оферты"

    # 4. GET /chats returns topic and subtopic
    chat_list = (await case.request("GET", "/chats")).json()
    assert chat_list["items"][0]["topic"] == "Закупки и котировочные сессии"
    assert chat_list["items"][0]["subtopic"] == "Создание оферты"

    # 5. Filter GET /chats by topic and subtopic
    matched = (await case.request("GET", "/chats?topic=Закупки и котировочные сессии")).json()
    assert matched["total"] == 1
    unmatched = (await case.request("GET", "/chats?topic=Другое")).json()
    assert unmatched["total"] == 0

    sub_matched = (await case.request("GET", "/chats?subtopic=Создание оферты")).json()
    assert sub_matched["total"] == 1
    sub_unmatched = (await case.request("GET", "/chats?subtopic=Прочее")).json()
    assert sub_unmatched["total"] == 0

    # 6. Filter GET /admin/chats by topic
    admin_matched = (await case.request("GET", "/admin/chats?topic=Закупки и котировочные сессии", login="admin")).json()
    assert admin_matched["total"] == 1
    admin_unmatched = (await case.request("GET", "/admin/chats?topic=Другое", login="admin")).json()
    assert admin_unmatched["total"] == 0
