from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(prefix="/manul", tags=["manul"])

_IMG_PATH = Path(__file__).parents[2] / "img" / "manul.jpg"


@router.get("", response_class=FileResponse)
async def get_manul() -> FileResponse:
    """Return the manul image."""
    return FileResponse(_IMG_PATH, media_type="image/jpeg")
