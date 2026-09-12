import json

import httpx
import pytest
from fastapi import FastAPI

from src.api.app import create_app
from src.config import api_settings


class MockAI:
    def __init__(self, transport):
        self.http = httpx.AsyncClient(base_url="http://ai-service/", transport=transport)


@pytest.fixture
def mock_ai_app():
    rules: dict[str, dict] = {}
    should_fail = False

    async def handle_request(request: httpx.Request) -> httpx.Response:
        nonlocal should_fail
        if should_fail:
            raise httpx.ConnectError("Connection refused")

        path = request.url.path
        if request.method == "GET" and path == "/ml-api/handrules":
            limit = int(request.url.params.get("limit", 100))
            items = list(rules.values())
            items.reverse()
            return httpx.Response(200, json=items[:limit])

        if request.method == "POST" and path == "/ml-api/handrules":
            body = request.read().decode()
            data = json.loads(body)
            rule_id = f"rule-{len(rules) + 1}"
            record = {
                "id": rule_id,
                "user_message": data["user_message"],
                "instructions": data["instructions"],
                "created_at": "2026-09-12T00:00:00Z",
                "updated_at": "2026-09-12T00:00:00Z",
            }
            rules[rule_id] = record
            return httpx.Response(201, json=record)

        if request.method == "GET" and path == "/ml-api/handrules/search":
            q = request.url.params.get("q", "").lower()
            k = int(request.url.params.get("k", 3))
            matches = [
                r for r in rules.values()
                if any(w in r["user_message"].lower() for w in q.split())
            ]
            if not matches:
                matches = list(rules.values())
            return httpx.Response(200, json=matches[:k])

        if request.method == "GET" and path.startswith("/ml-api/handrules/"):
            rule_id = path.split("/")[-1]
            if rule_id in rules:
                return httpx.Response(200, json=rules[rule_id])
            return httpx.Response(404, json={"detail": "Правило не найдено"})

        if request.method == "PATCH" and path.startswith("/ml-api/handrules/"):
            rule_id = path.split("/")[-1]
            if rule_id not in rules:
                return httpx.Response(404, json={"detail": "Правило не найдено"})
            data = json.loads(request.read().decode())
            rule = rules[rule_id]
            if "user_message" in data:
                rule["user_message"] = data["user_message"]
            if "instructions" in data:
                rule["instructions"] = data["instructions"]
            rule["updated_at"] = "2026-09-12T00:00:01Z"
            return httpx.Response(200, json=rule)

        if request.method == "DELETE" and path.startswith("/ml-api/handrules/"):
            rule_id = path.split("/")[-1]
            if rule_id not in rules:
                return httpx.Response(404, json={"detail": "Правило не найдено"})
            rules.pop(rule_id)
            return httpx.Response(204)

        return httpx.Response(404)

    app: FastAPI = create_app(api_settings)
    mock_ai = MockAI(httpx.MockTransport(handle_request))
    app.state.ai = mock_ai

    def set_fail(val: bool):
        nonlocal should_fail
        should_fail = val

    return app, set_fail


@pytest.mark.asyncio
async def test_handrules_crud_and_search(mock_ai_app):
    app, _ = mock_ai_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Initially empty
        res = await client.get("/ml-api/handrules")
        assert res.status_code == 200
        assert res.json() == []

        # 2. Create rule 1
        create_payload = {
            "user_message": "Не могу войти в личный кабинет",
            "instructions": "Попроси очистить кэш браузера или использовать режим инкогнито",
        }
        res = await client.post("/ml-api/handrules", json=create_payload)
        assert res.status_code == 201
        created_rule = res.json()
        assert created_rule["id"] == "rule-1"
        assert created_rule["user_message"] == create_payload["user_message"]
        assert created_rule["instructions"] == create_payload["instructions"]
        assert "created_at" in created_rule

        # 3. Create rule 2
        res2 = await client.post(
            "/ml-api/handrules",
            json={
                "user_message": "Ошибка 500 на портале закупок",
                "instructions": "Сообщи, что ведутся технические работы",
            },
        )
        assert res2.status_code == 201
        rule2_id = res2.json()["id"]

        # 4. List rules
        res_list = await client.get("/ml-api/handrules")
        assert res_list.status_code == 200
        items = res_list.json()
        assert len(items) == 2
        # Fresh first
        assert items[0]["id"] == rule2_id

        # 5. List with limit
        res_limit = await client.get("/ml-api/handrules?limit=1")
        assert res_limit.status_code == 200
        assert len(res_limit.json()) == 1

        # 6. Search rules
        res_search = await client.get("/ml-api/handrules/search?q=ошибка+портала&k=1")
        assert res_search.status_code == 200
        search_items = res_search.json()
        assert len(search_items) == 1
        assert search_items[0]["id"] == rule2_id

        # 7. Get single rule
        res_single = await client.get("/ml-api/handrules/rule-1")
        assert res_single.status_code == 200
        assert res_single.json()["id"] == "rule-1"

        # 8. Get non-existent rule
        res_404 = await client.get("/ml-api/handrules/not-found")
        assert res_404.status_code == 404

        # 9. Patch rule
        res_patch = await client.patch(
            "/ml-api/handrules/rule-1",
            json={"instructions": "Обновленная инструкция для входа"},
        )
        assert res_patch.status_code == 200
        patched = res_patch.json()
        assert patched["instructions"] == "Обновленная инструкция для входа"
        assert patched["user_message"] == create_payload["user_message"]

        # 10. Delete rule
        res_del = await client.delete("/ml-api/handrules/rule-1")
        assert res_del.status_code == 204

        # 11. Verify deleted rule is 404
        assert (await client.get("/ml-api/handrules/rule-1")).status_code == 404


@pytest.mark.asyncio
async def test_handrules_validation_errors(mock_ai_app):
    app, _ = mock_ai_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Limit validation (min 1, max 500)
        assert (await client.get("/ml-api/handrules?limit=0")).status_code == 422
        assert (await client.get("/ml-api/handrules?limit=501")).status_code == 422

        # Create validation: missing fields
        assert (await client.post("/ml-api/handrules", json={"user_message": "test"})).status_code == 422
        assert (await client.post("/ml-api/handrules", json={"instructions": "test"})).status_code == 422
        # Create validation: empty strings
        assert (await client.post("/ml-api/handrules", json={"user_message": "", "instructions": "test"})).status_code == 422

        # Search validation: q is required
        assert (await client.get("/ml-api/handrules/search")).status_code == 422
        assert (await client.get("/ml-api/handrules/search?q=")).status_code == 422
        assert (await client.get("/ml-api/handrules/search?q=test&k=25")).status_code == 422

        # Patch validation: empty string rejected
        assert (await client.patch("/ml-api/handrules/rule-1", json={"user_message": ""})).status_code == 422


@pytest.mark.asyncio
async def test_handrules_upstream_unavailable(mock_ai_app):
    app, set_fail = mock_ai_app
    set_fail(True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/ml-api/handrules")
        assert res.status_code == 503
        assert res.json()["detail"]["code"] == "AI_UNAVAILABLE"
