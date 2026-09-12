"""Перевод обращения на линию поддержки.

Мануал по линиям (`support-redirect-manual.md`) в контекст агента сразу не кладётся —
он объёмный. Агент достаёт его инструментом `support_manual()`, когда в базе знаний
ответа нет, и только потом (если вопрос вообще не про Портал) решает, куда переводить.

Сам перевод выполняет `transfer_to_support(line)` — это заглушка: чат закрывается,
дальше писать нельзя. Реального интерфейса оператора нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANUAL_PATH = HERE / "support-redirect-manual.md"

LINES = ("L1", "L2", "L3")

LINE_NAMES = {
    "L1": "информационно-консультационная",
    "L2": "экспертно-методологическая",
    "L3": "техническая",
}


@dataclass(frozen=True)
class Redirect:
    line: str
    reason: str = ""

    @property
    def title(self) -> str:
        return f"{self.line} — {LINE_NAMES.get(self.line, '')}"


_manual_cache: str | None = None


def support_manual() -> str:
    """Мануал по линиям поддержки: куда переводить какие обращения.

    Вызывай, когда search не нашёл ответа в инструкциях по Порталу, чтобы понять,
    относится ли вопрос вообще к Порталу и на какую линию его переводить.
    """
    global _manual_cache
    if _manual_cache is None:
        _manual_cache = MANUAL_PATH.read_text(encoding="utf-8").strip()
    return _manual_cache


def normalize_line(line: str) -> str | None:
    """Принимает 'l2', 'L2', '2', 'линия 2' и приводит к 'L2'."""
    raw = "".join((line or "").split()).upper().removeprefix("ЛИНИЯ").removeprefix("LINE").removeprefix("L")
    if raw in ("1", "2", "3"):
        return f"L{raw}"
    return None


def transfer_to_support(line: str, reason: str = "") -> str:
    """Перевести обращение на линию поддержки и завершить чат.

    Вызывай ТОЛЬКО если в базе знаний ответа нет и мануал по линиям подтверждает,
    что такой вопрос переводится. Если вопрос вообще не относится к Порталу
    поставщиков и в мануале нет подходящей линии — не вызывай, а вежливо скажи,
    что вопрос не по теме.

    line — одна из трёх линий: L1, L2 или L3.
    reason — короткое пояснение для оператора, что случилось (1 предложение).
    """
    return _transfer(line, reason)


@dataclass
class SupportSession:
    """Привязывает перевод к конкретному чату: инструмент сообщает о переводе сюда,
    а слой чата читает результат и закрывает чат."""

    redirect: Redirect | None = None

    def transfer_to_support(self, line: str, reason: str = "") -> str:
        """Перевести обращение на линию поддержки и завершить чат.

        Вызывай ТОЛЬКО если в базе знаний ответа нет и мануал по линиям подтверждает,
        что такой вопрос переводится (см. support_manual()). Если вопрос вообще не
        относится к Порталу поставщиков и в мануале нет подходящей линии — не вызывай,
        а вежливо скажи, что вопрос не по теме.

        line — одна из трёх линий: L1, L2 или L3.
        reason — короткое пояснение для оператора, что случилось (1 предложение).
        """
        normalized = normalize_line(line)
        if normalized is None:
            return (
                f"Неизвестная линия '{line}'. Доступны только: {', '.join(LINES)}. "
                "Посмотри мануал: support_manual()."
            )
        self.redirect = Redirect(line=normalized, reason=" ".join((reason or "").split())[:300])
        return f"Перевод на линию {normalized} принят, чат завершён."


def _transfer(line: str, reason: str) -> str:
    """Безсессионный вариант (CLI, тесты) — без сохранения состояния чата."""
    normalized = normalize_line(line)
    if normalized is None:
        return (
            f"Неизвестная линия '{line}'. Доступны только: {', '.join(LINES)}. "
            "Посмотри мануал: support_manual()."
        )
    return f"Перевод на линию {normalized} принят, чат завершён."
