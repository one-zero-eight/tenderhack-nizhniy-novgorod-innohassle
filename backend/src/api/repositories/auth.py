from fastapi import APIRouter
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from src.api.repositories.dependencies import CurrentUser, Settings, Storage
from src.db.models import User
from src.schemas.chat import LoginIn, TokenOut, UserOut
from src.services.auth import dummy_password_hash, issue_token, verify_password
from src.services.errors import fail

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
async def login(payload: LoginIn, storage: Storage, settings: Settings) -> TokenOut:
    async with storage.create_session() as session:
        user = await session.scalar(select(User).where(User.login == payload.login))
    valid = await run_in_threadpool(
        verify_password, payload.password, user.password_hash if user else dummy_password_hash
    )
    if user is None or not valid:
        fail(401, "INVALID_CREDENTIALS", "Invalid login or password")
    return TokenOut(access_token=issue_token(user.id, settings), expires_in=settings.access_token_minutes * 60)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
