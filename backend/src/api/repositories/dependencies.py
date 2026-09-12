from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config_schema import ApiSettings
from src.db.models import User
from src.db.storage import AbstractSQLAlchemyStorage
from src.services.auth import decode_token
from src.services.chats import ChatService
from src.services.errors import fail


def get_storage(request: Request) -> AbstractSQLAlchemyStorage:
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise RuntimeError("Storage is not initialized. Check lifespan setup.")
    return storage


def get_settings(request: Request) -> ApiSettings:
    return request.app.state.settings


def get_chat_service(request: Request) -> ChatService:
    return ChatService(get_storage(request), request.app.state.ai, request.app.state.moderator)


bearer = HTTPBearer(auto_error=False)


async def get_user(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> User:
    if credentials is None:
        fail(401, "AUTH_REQUIRED", "A bearer token is required")
    try:
        user_id = decode_token(credentials.credentials, get_settings(request))
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        fail(401, "INVALID_TOKEN", "Invalid or expired access token")
    async with get_storage(request).create_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            fail(401, "INVALID_TOKEN", "User no longer exists")
        return user


CurrentUser = Annotated[User, Depends(get_user)]
Chats = Annotated[ChatService, Depends(get_chat_service)]
Storage = Annotated[AbstractSQLAlchemyStorage, Depends(get_storage)]
Settings = Annotated[ApiSettings, Depends(get_settings)]


async def get_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        fail(403, "ADMIN_REQUIRED", "Admin access required")
    return user


async def get_support(user: CurrentUser) -> User:
    if not user.is_support:
        fail(403, "SUPPORT_REQUIRED", "Support access required")
    return user


Admin = Annotated[User, Depends(get_admin)]
Support = Annotated[User, Depends(get_support)]
