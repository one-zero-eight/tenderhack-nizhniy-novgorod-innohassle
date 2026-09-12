import asyncio
import threading
from types import SimpleNamespace

import pytest
import torch
from transformers import BertTokenizerFast

from src.config_schema import ApiSettings
from src.services.moderation import ModerationUnavailable, RubertModerator


@pytest.fixture
async def moderator(tmp_path):
    # Real tokenization and tensor operations; predictable logits isolate policy
    # and chunk coverage from the pretrained model's statistical accuracy.
    vocab = tmp_path / "vocab.txt"
    vocab.write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nhello\ncurse\n", encoding="utf-8")
    settings = ApiSettings(
        db_url="postgresql+asyncpg://unused/unused", jwt_secret="test-signing-secret-at-least-32-characters"
    )
    service = RubertModerator(settings)
    service._tokenizer = BertTokenizerFast(vocab_file=str(vocab))
    service._max_length = 80
    service._label_ids = [2, 1]

    def model(input_ids, **kwargs):
        assert input_ids.shape[1] <= 80
        assert input_ids.shape[0] <= 4
        logits = torch.full((len(input_ids), 5), 10.0)
        logits[:, 1] = -10.0
        logits[:, 2] = torch.where((input_ids == 6).any(dim=1), 10.0, -10.0)
        return SimpleNamespace(logits=logits)

    service._model = model
    try:
        yield service
    finally:
        await service.close()


async def test_selected_categories_block(moderator):
    # Threat/danger scores do not independently close the chat.
    assert not await moderator.is_blocked("hello")
    assert await moderator.is_blocked("curse")


@pytest.mark.parametrize("position", [0, 77, 78, 79, 300, 599])
async def test_all_chunks_including_boundaries_and_tail_are_checked(moderator, position):
    words = ["hello"] * 600
    words[position] = "curse"
    assert await moderator.is_blocked(" ".join(words))
    assert not await moderator.is_blocked("hello " * 600)


async def test_threshold_is_configurable_and_inclusive(moderator):
    moderator._model = lambda **kwargs: SimpleNamespace(logits=torch.zeros((1, 5)))
    moderator.settings.moderation_threshold = 0.5
    assert await moderator.is_blocked("hello")
    moderator.settings.moderation_threshold = 0.6
    assert not await moderator.is_blocked("hello")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
async def test_invalid_model_output_fails_closed(moderator, value):
    moderator._model = lambda **kwargs: SimpleNamespace(logits=torch.full((1, 5), value))
    with pytest.raises(ModerationUnavailable):
        await moderator.is_blocked("hello")


async def test_inference_error_allows_retry(moderator):
    original = moderator._model

    def broken(**kwargs):
        raise RuntimeError("inference failed")

    moderator._model = broken
    with pytest.raises(ModerationUnavailable):
        await moderator.is_blocked("hello")
    moderator._model = original
    assert not await moderator.is_blocked("hello")


@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_or_cancellation_keeps_worker_bounded_and_loop_responsive(moderator, cancel):
    started = threading.Event()
    release = threading.Event()
    calls = []
    original = moderator._score

    def slow(text):
        calls.append(text)
        started.set()
        release.wait(timeout=3)
        return 0.0

    moderator._score = slow
    moderator.settings.moderation_timeout = 0.1
    task = asyncio.create_task(moderator.is_blocked("first"))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(ModerationUnavailable):
                await task
        # The old native call still runs; retries must not enter the executor queue.
        with pytest.raises(ModerationUnavailable):
            await moderator.is_blocked("second")
        assert calls == ["first"]
    finally:
        release.set()
    moderator.settings.moderation_timeout = 5
    moderator._score = original
    assert not await moderator.is_blocked("hello")


async def test_missing_model_files_fail_startup(tmp_path):
    settings = ApiSettings(
        db_url="postgresql+asyncpg://unused/unused",
        jwt_secret="test-signing-secret-at-least-32-characters",
        moderation_model_path=tmp_path,
    )
    service = RubertModerator(settings)
    try:
        with pytest.raises((OSError, ValueError)):
            await service.start()
    finally:
        await service.close()


async def test_insult_category_can_be_disabled(moderator):
    logits = torch.tensor([[-10.0, 10.0, -10.0, -10.0, -10.0]])
    moderator._model = lambda **kwargs: SimpleNamespace(logits=logits)
    assert await moderator.is_blocked("hello")
    moderator._label_ids = [2]
    assert not await moderator.is_blocked("hello")


async def test_sentence_scoring_prevents_dilution(moderator):
    def diluted(input_ids, attention_mask, **kwargs):
        # Only a short isolated sentence triggers this model double.
        bad = (input_ids == 6).any(dim=1) & (attention_mask.sum(dim=1) < 10)
        logits = torch.full((len(input_ids), 5), -10.0)
        logits[:, 2] = torch.where(bad, 10.0, -10.0)
        return SimpleNamespace(logits=logits)

    moderator._model = diluted
    assert await moderator.is_blocked("hello " * 200 + ". curse")
