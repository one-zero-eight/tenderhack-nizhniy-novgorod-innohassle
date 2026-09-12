import httpx
from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter(tags=["assets"])


@router.get("/ml-assets/image/{slug}/{filename}", summary="Картинка мануала")
async def proxy_image(slug: str, filename: str, request: Request) -> Response:
    ai_http = request.app.state.ai.http
    target_path = f"ml-assets/image/{slug}/{filename}"
    res = await ai_http.get(target_path)
    return Response(
        content=res.content,
        status_code=res.status_code,
        headers={"Content-Type": res.headers.get("content-type", "image/png")},
    )


@router.get("/attachments/{file_id}", summary="Скачать загруженный файл")
@router.get("/ml-assets/attachments/{file_id}", include_in_schema=False)
async def get_attachment(file_id: str, request: Request) -> Response:
    ai_http = request.app.state.ai.http
    target_path = f"attachments/{file_id}"
    try:
        res = await ai_http.get(target_path)
        if res.status_code == 404:
            raise HTTPException(status_code=404, detail="Вложение не найдено")
        headers = {}
        if "content-disposition" in res.headers:
            headers["Content-Disposition"] = res.headers["content-disposition"]
        if "cache-control" in res.headers:
            headers["Cache-Control"] = res.headers["cache-control"]
        else:
            headers["Cache-Control"] = "public, max-age=86400"
        return Response(
            content=res.content,
            status_code=res.status_code,
            media_type=res.headers.get("content-type", "application/octet-stream"),
            headers=headers,
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="AI service unavailable")
