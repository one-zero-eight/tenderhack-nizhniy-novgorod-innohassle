from typing import Annotated

import httpx
from fastapi import APIRouter, Query, Request, Response, status

from src.schemas.handrule import HandRule, HandRuleIn, HandRulePatch
from src.services.errors import fail

router = APIRouter(prefix="/ml-api/handrules", tags=["handrules"])


async def _proxy_handrules(
    request: Request,
    method: str,
    path: str,
    params: dict | None = None,
    json_body: dict | None = None,
) -> Response:
    ai_http = request.app.state.ai.http
    try:
        res = await ai_http.request(method, path, params=params, json=json_body)
        headers = {}
        if res.status_code != 204:
            headers["Content-Type"] = res.headers.get("content-type", "application/json")
        return Response(
            content=res.content,
            status_code=res.status_code,
            headers=headers,
        )
    except (httpx.HTTPError, TimeoutError, ValueError):
        fail(503, "AI_UNAVAILABLE", "Handrules service is unavailable")


@router.get(
    "",
    response_model=list[HandRule],
    summary="Список правил",
    description=(
        "Возвращает все правила-подсказки, свежие сверху.\n\n"
        "Перед каждым ходом агента по вопросу пользователя ищутся до трёх ближайших правил "
        "(гибридный поиск: эмбеддинги + BM25), и их instructions уходят в системный промпт этого хода."
    ),
)
async def list_handrules(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=500, description="Сколько правил вернуть максимум")] = 100,
) -> Response:
    return await _proxy_handrules(request, "GET", "ml-api/handrules", params={"limit": limit})


@router.post(
    "",
    response_model=HandRule,
    status_code=status.HTTP_201_CREATED,
    summary="Создать правило",
    description=(
        "Создаёт правило вида {'user_message': ..., 'instructions': ...}.\n\n"
        "user_message — пример вопроса пользователя (по нему идёт поиск), "
        "instructions — что агенту делать в этом случае. "
        "После создания правило сразу участвует в поиске: индекс пересобирается лениво."
    ),
)
async def create_handrule(payload: HandRuleIn, request: Request) -> Response:
    return await _proxy_handrules(request, "POST", "ml-api/handrules", json_body=payload.model_dump())


@router.get(
    "/search",
    response_model=list[HandRule],
    summary="Проверить, какие правила подходят к вопросу",
    description=(
        "Сухой прогон поиска: возвращает правила, которые агент получил бы на такой вопрос, "
        "в порядке убывания релевантности. Нужен, чтобы проверить правило до того, "
        "как на него ответит живой агент.\n\n"
        "Объявлено перед /handrules/{rule_id} намеренно: иначе FastAPI принял бы search "
        "за идентификатор правила."
    ),
)
async def search_handrules(
    request: Request,
    q: Annotated[str, Query(min_length=1, description="Вопрос пользователя")],
    k: Annotated[int, Query(ge=1, le=20, description="Сколько правил вернуть")] = 3,
) -> Response:
    return await _proxy_handrules(request, "GET", "ml-api/handrules/search", params={"q": q, "k": k})


@router.get(
    "/{rule_id}",
    response_model=HandRule,
    summary="Одно правило",
    description="Возвращает правило по id.",
)
async def get_handrule(rule_id: str, request: Request) -> Response:
    return await _proxy_handrules(request, "GET", f"ml-api/handrules/{rule_id}")


@router.patch(
    "/{rule_id}",
    response_model=HandRule,
    summary="Изменить правило",
    description=(
        "Частично обновляет правило: переданные поля заменяются, остальные остаются как были. "
        "Пустая строка в любом из полей — ошибка."
    ),
)
async def update_handrule(rule_id: str, payload: HandRulePatch, request: Request) -> Response:
    body = payload.model_dump(exclude_unset=True)
    return await _proxy_handrules(request, "PATCH", f"ml-api/handrules/{rule_id}", json_body=body)


@router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить правило",
    description="Удаляет правило. После удаления оно больше не попадает в контекст агента.",
)
async def delete_handrule(rule_id: str, request: Request) -> Response:
    return await _proxy_handrules(request, "DELETE", f"ml-api/handrules/{rule_id}")
