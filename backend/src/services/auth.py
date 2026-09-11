from datetime import timedelta
from uuid import UUID

import jwt
from pwdlib import PasswordHash

from src.config_schema import ApiSettings
from src.db.models import utcnow

password_hasher = PasswordHash.recommended()
dummy_password_hash = password_hasher.hash("dummy-login-timing-value")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hasher.verify(password, hashed)


def issue_token(user_id: UUID, settings: ApiSettings) -> str:
    now = utcnow()
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_minutes),
            "iss": "tenderhack-backend",
            "aud": "tenderhack-web",
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


def decode_token(token: str, settings: ApiSettings) -> UUID:
    payload = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        issuer="tenderhack-backend",
        audience="tenderhack-web",
        options={"require": ["sub", "iat", "exp", "iss", "aud"]},
    )
    return UUID(payload["sub"])
