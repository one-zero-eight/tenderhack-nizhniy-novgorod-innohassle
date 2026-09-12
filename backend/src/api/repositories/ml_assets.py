from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter(prefix="/ml-assets", tags=["assets"])


@router.get("/image/{slug}/{filename}")
async def proxy_image(slug: str, filename: str, request: Request) -> Response:
    ai_http = request.app.state.ai.http
    target_path = f"ml-assets/image/{slug}/{filename}"
    res = await ai_http.get(target_path)
    return Response(
        content=res.content,
        status_code=res.status_code,
        headers={"Content-Type": res.headers.get("content-type", "image/png")},
    )
