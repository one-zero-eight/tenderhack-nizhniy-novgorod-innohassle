import asyncio
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.config_schema import Settings

BASE_DIR = Path(__file__).resolve().parents[1]
PRE_COMMIT_CONFIG = BASE_DIR / ".pre-commit-config.yaml"
DEFAULT_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"


def get_settings() -> Settings:
    """
    Load and return the settings from `settings.yaml` and/or environment variables.

    The `settings.yaml` file is optional: all values can be provided via environment
    variables instead (e.g. `API_SETTINGS__DB_URL`).
    """
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as e:
        raise RuntimeError(
            "❌ No `settings.yaml` found and no environment variables provided. "
            "Please provide settings via `settings.yaml` or environment variables "
            "(e.g. `API_SETTINGS__DB_URL`)."
        ) from e


def check_database_access():
    """
    Ensure the database is accessible using `db_url` from settings.
    """
    settings = get_settings()
    db_url = settings.api_settings.db_url.get_secret_value()

    async def test_connection():
        try:
            engine = create_async_engine(db_url)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                print("✅ Successfully connected to the database.")
        except Exception:
            print(f"❌ Failed to connect to the database at `{db_url}`")

    asyncio.run(test_connection())


def prepare():
    """
    Prepare the project for the run.
    """
    print("⚙️ Running prepare script...")
    check_database_access()
    print("✅ All setup steps completed.")
