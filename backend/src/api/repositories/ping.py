from fastapi import APIRouter, Depends
from sqlalchemy import text

from src.db.storage import AbstractSQLAlchemyStorage

from .dependencies import get_storage

router = APIRouter(prefix="/ping", tags=["ping"])


@router.get("")
async def ping(storage: AbstractSQLAlchemyStorage = Depends(get_storage)) -> dict[str, str]:
    """Return a simple `pong` response to check the service (and DB connection) is alive."""
    async with storage.create_session() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "pong"}
