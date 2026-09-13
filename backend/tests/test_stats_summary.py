from urllib.parse import unquote

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
    summaries: dict[str, dict] = {
        "Работа с контрактами": {
            "topic": "Работа с контрактами",
            "status": "ready",
            "summary": "По теме «Работа с контрактами» — частые вопросы по согласованию.",
            "feedback_chats": 5,
            "updated_at": "2026-09-13T10:00:00Z",
        },
        "general": {
            "topic": "general",
            "status": "pending",
            "summary": None,
            "feedback_chats": 1,
            "updated_at": None,
        },
    }
    should_fail = False

    async def handle_request(request: httpx.Request) -> httpx.Response:
        nonlocal should_fail
        if should_fail:
            raise httpx.ConnectError("Connection refused")

        path = request.url.path
        if path.startswith("/ml-api/stats/topics/") and path.endswith("/summary"):
            raw_topic = path[len("/ml-api/stats/topics/") : -len("/summary")]
            topic = unquote(raw_topic)
            if topic in summaries:
                return httpx.Response(200, json=summaries[topic])
            return httpx.Response(404, json={"detail": f"Тема '{topic}' не найдена"})

        return httpx.Response(404)

    app: FastAPI = create_app(api_settings)
    mock_ai = MockAI(httpx.MockTransport(handle_request))
    app.state.ai = mock_ai

    def set_fail(val: bool):
        nonlocal should_fail
        should_fail = val

    return app, set_fail


@pytest.mark.asyncio
async def test_get_topic_summary_success(mock_ai_app):
    app, _ = mock_ai_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/ml-api/stats/topics/Работа%20с%20контрактами/summary")
        assert res.status_code == 200
        data = res.json()
        assert data["topic"] == "Работа с контрактами"
        assert data["status"] == "ready"
        assert "Работа с контрактами" in data["summary"]
        assert data["feedback_chats"] == 5
        assert data["updated_at"] == "2026-09-13T10:00:00Z"


@pytest.mark.asyncio
async def test_get_topic_summary_pending(mock_ai_app):
    app, _ = mock_ai_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/ml-api/stats/topics/general/summary")
        assert res.status_code == 200
        data = res.json()
        assert data["topic"] == "general"
        assert data["status"] == "pending"
        assert data["summary"] is None
        assert data["feedback_chats"] == 1


@pytest.mark.asyncio
async def test_get_topic_summary_not_found(mock_ai_app):
    app, _ = mock_ai_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/ml-api/stats/topics/unknown-topic/summary")
        assert res.status_code == 404
        data = res.json()
        assert "не найдена" in data["detail"]


@pytest.mark.asyncio
async def test_get_topic_summary_ai_unavailable(mock_ai_app):
    app, set_fail = mock_ai_app
    set_fail(True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/ml-api/stats/topics/general/summary")
        assert res.status_code == 503
        data = res.json()
        assert data["detail"]["code"] == "AI_UNAVAILABLE"


@pytest.mark.asyncio
async def test_get_topic_summary_aliases(mock_ai_app):
    app, _ = mock_ai_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Check /stats/topics/...
        res1 = await client.get("/stats/topics/Работа%20с%20контрактами/summary")
        assert res1.status_code == 200
        assert res1.json()["topic"] == "Работа с контрактами"

        # Check /admin/topics/...
        res2 = await client.get("/admin/topics/Работа%20с%20контрактами/summary")
        assert res2.status_code == 200
        assert res2.json()["topic"] == "Работа с контрактами"


def test_openapi_schema(mock_ai_app):
    app, _ = mock_ai_app
    schema = app.openapi()
    assert "/ml-api/stats/topics/{topic}/summary" in schema["paths"]
    endpoint_spec = schema["paths"]["/ml-api/stats/topics/{topic}/summary"]["get"]
    assert endpoint_spec["summary"] == "AI-сводка темы статистики"
    assert "TopicSummaryStatus" in schema["components"]["schemas"]
