"""Create missing database tables from the SQLAlchemy models."""

import asyncio

from src.config_schema import Settings
from src.db.storage import SQLAlchemyStorage


async def main() -> None:
    storage = SQLAlchemyStorage.from_url(Settings().api_settings.db_url.get_secret_value())
    try:
        await storage.create_all()
    finally:
        await storage.close_connection()


if __name__ == "__main__":
    asyncio.run(main())
