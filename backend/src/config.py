from pydantic import ValidationError

from src.config_schema import ApiSettings, Settings

try:
    settings: Settings = Settings()  # type: ignore[call-arg]
except ValidationError as e:  # pragma: no cover
    raise RuntimeError(
        f"❌ Invalid settings ({e}). Provide them via `settings.yaml` or environment variables (e.g. `API_SETTINGS__JWT_SECRET`, `API_SETTINGS__DB_URL`)."
    ) from e

api_settings: ApiSettings = settings.api_settings
