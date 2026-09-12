"""Offline smoke checks of the pinned weights; not an accuracy benchmark."""

import os

import pytest

from src.config_schema import ApiSettings
from src.services.moderation import RubertModerator


@pytest.mark.skipif(os.getenv("RUN_MODERATION_MODEL_TESTS") != "1", reason="Requires downloaded RuBERT model files")
async def test_pinned_model_support_messages_and_profanity():
    settings = ApiSettings(
        db_url="postgresql+asyncpg://unused/unused", jwt_secret="test-signing-secret-at-least-32-characters"
    )
    moderator = RubertModerator(settings)
    try:
        await moderator.start()
        for text in (
            "Здравствуйте, как изменить реквизиты поставщика?",
            "Ваша система опять не работает, исправьте ошибку!",
            "Нужно застраховать оборудование",
        ):
            assert not await moderator.is_blocked(text), text
        for text in (
            "нахуй",
            "Да пошёл ты нахуй",
            "Это полная хуйня",
            "Вы идиот",
            "Согласуйте поставку. " * 150 + " Это полная хуйня",
        ):
            assert await moderator.is_blocked(text), text
    finally:
        await moderator.close()
