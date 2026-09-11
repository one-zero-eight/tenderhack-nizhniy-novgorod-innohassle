"""Seed demo accounts without resetting existing passwords or replacing real line descriptions."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from sqlalchemy import select

from src.config_schema import Settings
from src.db.models import Role, SupportLine, User
from src.db.storage import AbstractSQLAlchemyStorage, SQLAlchemyStorage
from src.schemas.chat import SupportLineOut
from src.services.auth import hash_password

DEMO_ACCOUNTS = [
    ("user", "Пользователь", Role.USER, None),
    ("user2", "Второй пользователь", Role.USER, None),
    ("operator1", "Оператор 1", Role.OPERATOR, 1),
    ("operator2", "Оператор 2", Role.OPERATOR, 2),
    ("operator3", "Оператор 3", Role.OPERATOR, 3),
    ("admin", "Администратор", Role.ADMIN, None),
]


async def seed_demo(
    storage: AbstractSQLAlchemyStorage, password: str, lines: list[SupportLineOut] | None = None
) -> None:
    if len(password) < 8:
        raise ValueError("Demo password must contain at least 8 characters")
    if lines is not None and (len(lines) != 3 or {line.id for line in lines} != {1, 2, 3}):
        raise ValueError("Provide exactly the support lines with IDs 1, 2, 3")
    configured_lines = lines or [
        SupportLineOut(
            id=line_id,
            name=f"Линия {line_id}",
            description=f"Укажите реальные обязанности линии {line_id}.",
        )
        for line_id in (1, 2, 3)
    ]
    hashed = hash_password(password)
    async with storage.create_session() as session, session.begin():
        for description in configured_lines:
            existing = await session.get(SupportLine, description.id)
            if existing is None:
                session.add(SupportLine(**description.model_dump()))
            elif lines is not None:
                existing.name, existing.description = description.name, description.description
        await session.flush()
        for login, name, role, line_id in DEMO_ACCOUNTS:
            if await session.scalar(select(User.id).where(User.login == login)) is None:
                session.add(
                    User(login=login, display_name=name, role=role, support_line_id=line_id, password_hash=hashed)
                )


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lines-file", type=Path, help="JSON array of three {id, name, description} objects")
    args = parser.parse_args()
    password = os.environ.get("DEMO_PASSWORD")
    if not password:
        parser.error("Set DEMO_PASSWORD to the password for newly created demo accounts")
    lines = None
    if args.lines_file:
        lines = [SupportLineOut.model_validate(line) for line in json.loads(args.lines_file.read_text())]
    storage = SQLAlchemyStorage.from_url(Settings().api_settings.db_url.get_secret_value())
    try:
        await seed_demo(storage, password, lines)
        print("Seeded three support lines and demo accounts: user, user2, operator1, operator2, operator3, admin.")
        print("Existing account passwords were preserved.")
    finally:
        await storage.close_connection()


if __name__ == "__main__":
    asyncio.run(main())
