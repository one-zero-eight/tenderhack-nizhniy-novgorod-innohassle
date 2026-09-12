from fastapi import APIRouter
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from src.api.repositories.dependencies import CurrentUser, Settings, Storage
from src.db.models import Role, User
from src.schemas.chat import LoginIn, RegisterIn, TokenOut, UserOut
from src.services.auth import dummy_password_hash, hash_password, issue_token, verify_password
from src.services.errors import fail

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(payload: RegisterIn, storage: Storage, settings: Settings) -> TokenOut:
    async with storage.create_session() as session, session.begin():
        existing = await session.scalar(select(User.id).where(User.login == payload.login))
        if existing:
            fail(409, "LOGIN_TAKEN", "A user with this login already exists")
        role = payload.role
        if role == Role.SUPPORT and not payload.support_line_id:
            fail(400, "SUPPORT_LINE_REQUIRED", "Support staff must specify a support line ID")
        display_name = payload.display_name or payload.login
        hashed = await run_in_threadpool(hash_password, payload.password)
        user = User(
            login=payload.login,
            password_hash=hashed,
            display_name=display_name,
            role=role,
            support_line_id=payload.support_line_id if role == Role.SUPPORT else None,
        )
        session.add(user)
        await session.flush()
        user_id = user.id

    return TokenOut(access_token=issue_token(user_id, settings), expires_in=settings.access_token_minutes * 60)


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
