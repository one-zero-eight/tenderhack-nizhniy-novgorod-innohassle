import asyncio
from uuid import uuid4

import httpx
import pytest

from scripts.ai_stub import app as stub_app
from src.config_schema import ApiSettings
from src.services.ai_client import AIClient, AIUnavailable


def settings(**kwargs):
    return ApiSettings(
        db_url="postgresql+asyncpg://unused/unused", jwt_secret="unit-test-signing-secret-at-least-32", **kwargs
    )


@pytest.mark.parametrize(
    "body",
    [
        {"outcome": "answered", "answer": "", "sources": []},
        {"outcome": "answered", "answer": "   ", "sources": []},
        {"outcome": "answered", "answer": None, "sources": []},
        {"outcome": "no_answer", "answer": "An unsupported answer", "sources": []},
        {"outcome": "other", "answer": "An answer", "sources": []},
        {"outcome": "answered", "answer": "An answer", "sources": [{"title": "missing document id"}]},
    ],
)
async def test_invalid_answer_is_unavailable(body):
    request_id = uuid4()
    async with httpx.AsyncClient(
        base_url="http://ai/",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"request_id": str(request_id), **body}),
        ),
    ) as http:
        with pytest.raises(AIUnavailable):
            await AIClient(http, settings()).answer(request_id, "message", [])


@pytest.mark.parametrize("failure", ["invalid_json", "wrong_id", "http_error"])
async def test_invalid_transport_response_is_unavailable(failure):
    request_id = uuid4()

    def respond(request):
        if failure == "invalid_json":
            return httpx.Response(200, text="not json")
        if failure == "http_error":
            return httpx.Response(500, text="internal exception should not reach the user")
        return httpx.Response(
            200, json={"request_id": str(uuid4()), "outcome": "answered", "answer": "answer", "sources": []}
        )

    async with httpx.AsyncClient(base_url="http://ai/", transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(AIUnavailable):
            await AIClient(http, settings()).answer(request_id, "message", [])


async def test_total_deadline_bounds_http_call():
    async def slow(request):
        await asyncio.sleep(1)
        raise AssertionError("The client should cancel this request at its deadline")

    async with httpx.AsyncClient(base_url="http://ai/", transport=httpx.MockTransport(slow)) as http:
        client = AIClient(http, settings(ai_answer_timeout=0.01))
        with pytest.raises(AIUnavailable):
            await client.answer(uuid4(), "message", [])


async def test_routing_checks_supplied_catalog():
    request_id = uuid4()
    async with httpx.AsyncClient(
        base_url="http://ai/",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"request_id": str(request_id), "recommended_support_line_id": 2}),
        ),
    ) as http:
        with pytest.raises(AIUnavailable):
            await AIClient(http, settings()).route(request_id, "message", [], [{"id": 1}])


@pytest.mark.parametrize(
    "message,outcome,line",
    [
        ("ordinary message", "answered", None),
        ("[unknown] [line=3]", "no_answer", 3),
    ],
)
async def test_development_stub_matches_client_contract(monkeypatch, message, outcome, line):
    monkeypatch.delenv("API_SETTINGS__AI_SERVICE_TOKEN", raising=False)
    async with httpx.AsyncClient(base_url="http://stub/", transport=httpx.ASGITransport(stub_app)) as http:
        client = AIClient(http, settings())
        if outcome:
            assert (await client.answer(uuid4(), message, [])).outcome == outcome
        if line:
            assert await client.route(uuid4(), message, [], [{"id": n} for n in (1, 2, 3)]) == line
        assert (await client.health())["mode"] == "stub"


async def test_stub_requires_configured_internal_token(monkeypatch):
    monkeypatch.setenv("API_SETTINGS__AI_SERVICE_TOKEN", "stub-service-token")
    async with httpx.AsyncClient(base_url="http://stub/", transport=httpx.ASGITransport(stub_app)) as http:
        client = AIClient(http, settings())
        with pytest.raises(AIUnavailable):
            await client.answer(uuid4(), "message", [])
        http.headers["Authorization"] = "Bearer stub-service-token"
        assert (await client.answer(uuid4(), "message", [])).outcome == "answered"
