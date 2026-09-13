from urllib.parse import quote

import httpx
from fastapi import APIRouter, Request, Response

from src.schemas.stats import TopicSummaryStatus
from src.services.errors import fail

router = APIRouter(tags=["stats"])


async def _proxy_stats(request: Request, path: str) -> Response:
    ai_http = request.app.state.ai.http
    try:
        res = await ai_http.get(path)
        headers = {}
        if res.status_code != 204:
            headers["Content-Type"] = res.headers.get("content-type", "application/json")
        return Response(
            content=res.content,
            status_code=res.status_code,
            headers=headers,
        )
    except (httpx.HTTPError, TimeoutError, ValueError):
        fail(503, "AI_UNAVAILABLE", "Stats summary service is unavailable")


@router.get(
    "/ml-api/stats/topics/{topic}/summary",
    response_model=TopicSummaryStatus,
    summary="AI-сводка темы статистики",
    description=(
        "Возвращает сохранённую AI-сводку по теме обращений и её статус.\n\n"
        "Сводки готовит фоновая задача — она следит за новыми отзывами. "
        "Если по теме появилась новая обратная связь, а сводка устарела или её ещё нет, "
        "этот запрос сам ставит генерацию в фон и сразу отвечает текущим состоянием: "
        "повторный запрос через несколько секунд вернёт уже обновлённый текст.\n\n"
        "Сводка отдаётся в markdown.\n\n"
        "**Статусы:** `ready` — актуальна; `outdated` — есть новая обратная связь, идёт пересчёт; "
        "`pending` — обратная связь есть, сводки ещё нет; `none` — обратной связи по теме нет."
    ),
)
@router.get(
    "/stats/topics/{topic}/summary",
    response_model=TopicSummaryStatus,
    include_in_schema=False,
)
@router.get(
    "/admin/topics/{topic}/summary",
    response_model=TopicSummaryStatus,
    include_in_schema=False,
)
async def get_topic_summary(topic: str, request: Request) -> Response:
    encoded_topic = quote(topic, safe="")
    return await _proxy_stats(request, f"ml-api/stats/topics/{encoded_topic}/summary")
