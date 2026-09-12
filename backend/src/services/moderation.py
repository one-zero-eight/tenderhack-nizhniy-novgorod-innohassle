import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from src.config_schema import ApiSettings

logger = logging.getLogger(__name__)


class ModerationUnavailable(Exception):
    """Local moderation could not complete; the message must remain unpublished."""


class Moderator(Protocol):
    async def is_blocked(self, text: str) -> bool: ...


class RubertModerator:
    def __init__(self, settings: ApiSettings):
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="moderation")
        self._slot = asyncio.Semaphore(1)
        self._tokenizer = None
        self._model = None

    async def start(self) -> None:
        # Imports, disk I/O and warmup all run outside the event loop.
        await asyncio.get_running_loop().run_in_executor(self._executor, self._load)

    def _load(self) -> None:
        import torch  # noqa: PLC0415 - keep ML imports out of API/CLI module initialization
        from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: PLC0415

        torch.set_num_threads(1)
        path = str(self.settings.moderation_model_path)
        self._tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, use_fast=True)
        self._model = (
            AutoModelForSequenceClassification.from_pretrained(path, local_files_only=True, use_safetensors=True)
            .to("cpu")
            .eval()
        )
        self._label_ids = [self._model.config.label2id[label] for label in self.settings.moderation_block_labels]
        self._max_length = min(512, self._model.config.max_position_embeddings, self._tokenizer.model_max_length)
        self._score("Здравствуйте")

    def _score(self, text: str) -> float:
        import torch  # noqa: PLC0415 - keep ML imports out of API/CLI module initialization

        if self._model is None or self._tokenizer is None:
            raise RuntimeError("Moderation model is not loaded")
        # Score sentences as well as the full text: a short profane sentence can
        # otherwise be diluted by a long, mostly neutral message. No word list is used.
        sentences = [part.strip() for part in re.split(r"(?<=[.!?;])\s+|[\r\n]+", text) if part.strip()]
        texts = list(dict.fromkeys([text, *sentences]))
        encoded = self._tokenizer(
            texts,
            truncation=True,
            max_length=self._max_length,
            stride=64,
            return_overflowing_tokens=True,
            padding=False,
        )
        # Overflow metadata is for the tokenizer, not a model input.
        inputs = {name: encoded[name] for name in self._tokenizer.model_input_names if name in encoded}
        highest = 0.0
        with torch.inference_mode():
            # Bound memory even when a 4,000-character message produces many chunks.
            for start in range(0, len(inputs["input_ids"]), 4):
                batch = {name: value[start : start + 4] for name, value in inputs.items()}
                batch = self._tokenizer.pad(batch, padding=True, return_tensors="pt")
                logits = self._model(**batch).logits[:, self._label_ids]
                if not torch.isfinite(logits).all():
                    raise ValueError("Non-finite moderation output")
                highest = max(highest, torch.sigmoid(logits).max().item())
        return highest

    async def is_blocked(self, text: str) -> bool:
        try:
            async with asyncio.timeout(self.settings.moderation_timeout):
                await self._slot.acquire()
                try:
                    future = asyncio.get_running_loop().run_in_executor(self._executor, self._score, text)
                except BaseException:
                    self._slot.release()
                    raise

                def finished(result: asyncio.Future) -> None:
                    self._slot.release()
                    # Retrieve late exceptions after a request timed out or disconnected.
                    if not result.cancelled():
                        result.exception()

                future.add_done_callback(finished)
                # A timeout cannot stop native inference. Keep the slot occupied until it
                # really finishes, preventing an unbounded executor queue on repeated retries.
                score = await asyncio.shield(future)
                return score >= self.settings.moderation_threshold
        except Exception as exc:
            # Do not log user text or exception details that could include it.
            logger.warning("Local moderation unavailable (%s)", type(exc).__name__)
            raise ModerationUnavailable from exc

    async def close(self) -> None:
        await asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=True)
