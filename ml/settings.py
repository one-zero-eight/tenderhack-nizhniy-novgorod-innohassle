"""Настройки приложения: LLM, эмбеддинги, БД, логирование.

Всё берётся из переменных окружения, а сам набор переменных задаётся env-файлом.
Какой файл загружать — выбирается переменной APP_ENV (имя файла без .env):

    APP_ENV=deepseek  ->  ml/deepseek.env   (облачный DeepSeek, прод на 8010)
    APP_ENV=local     ->  ml/local.env      (локальный qwen через LM Studio)
    не задана         ->  ml/.env           (старое поведение)

Пример запуска на локальной модели:

    APP_ENV=local uvicorn app:app --port 8011

Отдельный конфиг нужен в первую очередь для пары «LLM + база»: у облачного и
локального запусков разные модели и разные файлы SQLite, иначе они мешают друг другу.

Модуль импортируется первым в app.py/rag.py/handrules.py и грузит dotenv до того,
как остальной код прочитает os.getenv.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent

# ENV-файлы, которые знает приложение. Имя берётся из APP_ENV.
ENV_FILES = {
    "deepseek": HERE / "deepseek.env",
    "local": HERE / "local.env",
    # None — файл по умолчанию (.env), для обратной совместимости.
    "": HERE / ".env",
}

# Какое окружение активно. Строка пустая — грузится .env.
APP_ENV = os.getenv("APP_ENV", "").strip().lower()


def env_file() -> Path:
    """Путь к активному env-файлу.

    Неизвестное значение APP_ENV — ошибка, а не тихий откат на .env: иначе легко
    запустить прод на локальной модели, просто опечатавшись.
    """
    if APP_ENV not in ENV_FILES:
        known = ", ".join(k for k in ENV_FILES if k)
        raise SystemExit(
            f"APP_ENV='{APP_ENV}' неизвестен. Доступные значения: {known} "
            "(или пусто — тогда читается .env)."
        )
    return ENV_FILES[APP_ENV]


# override=False: уже заданные переменные окружения важнее файла. Так можно
# точечно переопределить любой параметр прямо в команде запуска.
load_dotenv(env_file(), override=False)


def get(name: str, default: str = "") -> str:
    """Значение настройки строкой."""
    return os.getenv(name, default)


def get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


# ------------------------------------------------------------------ LLM


def llm_model() -> str:
    return get("LLM_MODEL", "deepseek-flash")


def llm_base() -> str:
    return get("LLM_API_BASE", "https://api.deepseek.com/v1")


def llm_key() -> str:
    return get("LLM_API_KEY", "")


def llm_context_window() -> int:
    return get_int("LLM_CONTEXT_WINDOW", 128_000)


def llm_timeout() -> float:
    # Локальная модель на большом контексте отвечает медленно — таймаут щедрый.
    return get_float("LLM_TIMEOUT", 120.0)


def llm_temperature() -> float:
    return get_float("LLM_TEMPERATURE", 0.0)


def llm_extra_headers() -> dict[str, str]:
    """Дополнительные заголовки к запросам LLM: 'Ключ=Значение,Ключ2=Значение2'.

    Нужно для локальных шлюзов, которым требуется свой заголовок авторизации.
    """
    raw = get("LLM_EXTRA_HEADERS", "")
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        if "=" in pair:
            key, value = pair.split("=", 1)
            headers[key.strip()] = value.strip()
    return headers


# ------------------------------------------------------------------ БД


def db_path() -> Path:
    """Файл SQLite с чатами. У облачного и локального запусков он разный."""
    return Path(get("CHAT_DB_PATH") or (HERE / "chats.sqlite3"))
