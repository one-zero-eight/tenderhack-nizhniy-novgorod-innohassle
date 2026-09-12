"""Фоновые ходы агента: генерация живёт независимо от HTMX/SSE-соединения.

Проблема, которую это решает: раньше стрим запускался внутри SSE-хендлера, поэтому
при переключении чата HTMX рвал соединение и генерация отменялась (asyncio.CancelledError).

Теперь ход — это отдельная asyncio-задача на чат:
- стартует один раз и доживает до конца, что бы ни делал клиент;
- копит события в буфере, чтобы новый клиент получил уже сгенерированное;
- к любому моменту можно подключиться (`subscribe`) и отключиться (`unsubscribe`),
  не влияя на саму генерацию;
- по завершении хранит финальное состояние, чтобы опоздавший клиент получил ответ сразу.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

import attachments as attachment_service
import chat as chat_service
from storage import MessageRecord, get_storage


@dataclass
class Turn:
    """Один ход агента (ответ на одно сообщение пользователя)."""

    chat_id: str
    message_id: str
    events: list[tuple[str, str]] = field(default_factory=list)
    subscribers: set[asyncio.Queue[tuple[str, str] | None]] = field(default_factory=set)
    task: asyncio.Task[None] | None = None
    done: bool = False
    error: str | None = None

    def publish(self, event: str, data: str) -> None:
        """Кладёт событие в буфер и рассылает подписчикам (без блокировки генерации)."""
        self.events.append((event, data))
        for queue in list(self.subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait((event, data))

    def finish(self) -> None:
        self.done = True
        for queue in list(self.subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(None)


class TurnManager:
    """Реестр активных и завершённых ходов, ключ — id сообщения ассистента."""

    def __init__(self) -> None:
        self._turns: dict[str, Turn] = {}
        # Ход на чат: второй одновременный ответ в тот же чат не запускаем.
        self._by_chat: dict[str, str] = {}

    # ------------------------------------------------------------------ state

    def get(self, message_id: str) -> Turn | None:
        return self._turns.get(message_id)

    def for_chat(self, chat_id: str) -> Turn | None:
        message_id = self._by_chat.get(chat_id)
        if message_id is None:
            return None
        turn = self._turns.get(message_id)
        if turn is None or turn.done:
            return None
        return turn

    def is_streaming(self, message_id: str) -> bool:
        turn = self._turns.get(message_id)
        return turn is not None and not turn.done

    # ------------------------------------------------------------------ start

    def start(
        self,
        chat_id: str,
        assistant_message: MessageRecord,
        on_event: Callable[[str, str], str | None] | None = None,
        user_role: str | None = None,
        files: list[attachment_service.ChatFile] | None = None,
    ) -> Turn:
        """Запускает генерацию в фоне. Возвращает Turn, к которому можно подключаться.

        on_event превращает пару (event, payload) из chat.stream_answer в SSE-строку,
        которую увидят клиенты. Так HTML-рендеринг остаётся в app.py, а не в слое чатов.
        files — вложения, ожидающие отправки вместе с этим ходом.
        """
        turn = Turn(chat_id=chat_id, message_id=assistant_message.id)
        self._turns[assistant_message.id] = turn
        self._by_chat[chat_id] = assistant_message.id
        turn.task = asyncio.create_task(self._run(turn, assistant_message, on_event, user_role, files))
        return turn

    async def _run(
        self,
        turn: Turn,
        assistant_message: MessageRecord,
        on_event: Callable[[str, str], str | None] | None,
        user_role: str | None = None,
        files: list[attachment_service.ChatFile] | None = None,
    ) -> None:
        try:
            async for chunk in chat_service.stream_answer(
                turn.chat_id, assistant_message, user_role=user_role, files=files
            ):
                # chat.stream_answer отдаёт готовые SSE-фреймы; разбираем в (event, data).
                event, data = _split_sse(chunk)
                if on_event is not None:
                    data = on_event(event, data)
                    # None — событие решили не показывать (например, вызов инструмента).
                    if data is None:
                        continue
                turn.publish(event, data)
        except Exception as exc:  # noqa: BLE001 — ход не должен ронять фоновую задачу
            turn.error = str(exc)
        finally:
            turn.finish()

    # -------------------------------------------------------------- subscribe

    async def subscribe(self, message_id: str, replay: bool = True) -> AsyncIterator[str]:
        """Отдаёт SSE-строки: сначала буфер, потом живые события.

        Если ход уже завершён — отдаём накопленное и выходим, ничего не ожидая.
        """
        turn = self._turns.get(message_id)
        if turn is None:
            return

        queue: asyncio.Queue[tuple[str, str] | None] = asyncio.Queue(maxsize=512)
        # Подписываемся до отправки буфера, иначе можно потерять события между шагами.
        snapshot = list(turn.events)
        turn.subscribers.add(queue)
        try:
            if replay:
                for event, data in snapshot:
                    yield data
            if turn.done and not turn.subscribers - {queue}:
                # Завершённый ход: буфера достаточно.
                if not replay:
                    for _event, data in snapshot:
                        yield data
                return
            while True:
                item = await queue.get()
                if item is None:
                    return
                _event, data = item
                yield data
        finally:
            turn.subscribers.discard(queue)
            if turn.done:
                self._cleanup(message_id)

    def _cleanup(self, message_id: str) -> None:
        """Убирает завершённый ход, когда на него больше никто не смотрит."""
        turn = self._turns.get(message_id)
        if turn is None or not turn.done or turn.subscribers:
            return
        self._turns.pop(message_id, None)
        if self._by_chat.get(turn.chat_id) == message_id:
            self._by_chat.pop(turn.chat_id, None)

    async def shutdown(self) -> None:
        for turn in list(self._turns.values()):
            if turn.task is not None and not turn.task.done():
                turn.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await turn.task


def _split_sse(chunk: str) -> tuple[str, str]:
    """Разбирает SSE-фрейм вида 'event: x\\ndata: {...}\\n\\n' на (event, data-блок)."""
    event = "message"
    data_lines: list[str] = []
    for line in chunk.splitlines():
        if line.startswith("event: "):
            event = line[len("event: ") :]
        elif line.startswith("data: "):
            data_lines.append(line[len("data: ") :])
    return event, "\n".join(data_lines)


TURNS = TurnManager()
"""Глобальный менеджер ходов: один на процесс."""

__all__ = ["TURNS", "Turn", "TurnManager"]


# Хранилище импортируется ради типизации в вызывающем коде.
_ = get_storage
