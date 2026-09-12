import httpx
from fastapi import APIRouter, Request, Response

from src.services.errors import fail

router = APIRouter(prefix="/ml-api/knowledge-base", tags=["knowledge-base"])
kb_alias_router = APIRouter(prefix="/knowledge-base", tags=["knowledge-base"])


async def _proxy_kb(request: Request, path: str) -> Response:
    ai_http = request.app.state.ai.http
    try:
        res = await ai_http.get(path)
        return Response(
            content=res.content,
            status_code=res.status_code,
            headers={"Content-Type": res.headers.get("content-type", "application/json")},
        )
    except (httpx.HTTPError, TimeoutError, ValueError):
        fail(503, "AI_UNAVAILABLE", "Knowledge base service is unavailable")


@router.get("", summary="Список мануалов")
@router.get("/", summary="Список мануалов", include_in_schema=False)
@kb_alias_router.get("", include_in_schema=False)
@kb_alias_router.get("/", include_in_schema=False)
async def list_manuals(request: Request) -> Response:
    return await _proxy_kb(request, "ml-api/knowledge-base")


@router.get("/{slug}", summary="Структура мануала")
@kb_alias_router.get("/{slug}", include_in_schema=False)
async def get_manual_structure(slug: str, request: Request) -> Response:
    return await _proxy_kb(request, f"ml-api/knowledge-base/{slug}")


@router.get("/{slug}/{section_id}", summary="Содержимое раздела мануала")
@kb_alias_router.get("/{slug}/{section_id}", include_in_schema=False)
async def get_manual_section(slug: str, section_id: str, request: Request) -> Response:
    return await _proxy_kb(request, f"ml-api/knowledge-base/{slug}/{section_id}")
