"""Отдача картинок мануалов и загруженных вложений.

* `GET /ml-assets/image/<slug>/<filename>` — картинки из инструкций
  (лежат рядом с json мануала: jsons/<slug>/image-N.png, см. process.py).
  Путь собирается вручную и проверяется на выход за пределы jsons/.
* `GET /attachments/<id>` — оригиналы файлов, загруженных пользователем
  (см. attachments.py). Работает и после отправки вложения в модель: файл живёт
  в `attachments/`, пока жив чат.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, Response

import attachments as attachment_service
from manuals import JSONS_DIR

router = APIRouter(tags=["ml-assets"])

# Расширение -> media type. Набор фиксирован: process.py кладёт только картинки.
MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def resolve_image(slug: str, filename: str) -> Path:
    """Безопасно превращает slug + имя файла в путь внутри jsons/.

    Бросает 404, если файла нет, и 400, если имя пытается выйти за пределы каталога.
    """
    root = JSONS_DIR.resolve()
    candidate = (root / slug / filename).resolve()
    # Разрешаем только <jsons>/<slug>/<file>: никаких .. и вложенных подкаталогов.
    if candidate.parent.parent != root or candidate.parent.name != slug:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный путь")
    if candidate.suffix.lower() not in MEDIA_TYPES or not candidate.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Картинка не найдена")
    return candidate


@router.get(
    "/ml-assets/image/{slug}/{filename}",
    summary="Картинка мануала",
    description=(
        "Отдаёт картинку из инструкции. Такие ссылки агент отдаёт в тексте разделов "
        "(`![подпись](/ml-assets/image/<slug>/image-N.png)`) — их можно вставлять в `<img src>`."
    ),
    response_class=FileResponse,
    responses={
        200: {"description": "Файл изображения", "content": {"image/png": {}}},
        400: {"description": "Некорректный путь"},
        404: {"description": "Картинка не найдена"},
    },
)
async def get_image(
    slug: Annotated[
        str, PathParam(description="Slug мануала, например `instrukciya-po-sozdaniyu-oferty-i-ste`")
    ],
    filename: Annotated[str, PathParam(description="Имя файла, например `image-1.png`")],
) -> FileResponse:
    path = resolve_image(slug, filename)
    return FileResponse(
        path,
        media_type=MEDIA_TYPES[path.suffix.lower()],
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get(
    "/attachments/{file_id}",
    response_class=Response,
    response_model=None,
    summary="Скачать загруженный файл",
    description=(
        "Отдаёт оригинал файла, который пользователь загрузил в чат. Работает и после "
        "отправки сообщения: оригиналы лежат в папке `attachments/` до удаления чата, "
        "в отличие от таблицы `chat_files`, которая чистится при отправке.\n\n"
        "Эту ссылку агент/интерфейс использует для картинок в истории чата."
    ),
    responses={
        200: {"description": "Файл", "content": {"application/octet-stream": {}}},
        404: {"description": "Вложение не найдено"},
    },
)
async def get_attachment(
    file_id: Annotated[str, PathParam(description="Идентификатор вложения")],
) -> Response:
    found = attachment_service.read_original(file_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Вложение не найдено")
    data, content_type, filename = found
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": attachment_service.content_disposition(filename),
            "Cache-Control": "public, max-age=86400",
        },
    )
