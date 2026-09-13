"""Перевод обращения на линию поддержки.

Мануал по линиям (`support-redirect-manual.md`) целиком кладётся в системный промпт
(см. rag.load_lines_manual) — отдельного инструмента support_manual() больше нет.
L3 из мануала убрана (её обрабатывает техническое подразделение вне Портала),
переводить можно только на L1 и L2.

Сам перевод выполняет `transfer_to_support(line)` — это заглушка: чат закрывается,
дальше писать нельзя. Реального интерфейса оператора нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANUAL_PATH = HERE / "support-redirect-manual.md"

LINES = ("L1", "L2")

LINE_NAMES = {
    "L1": "информационно-консультационная",
    "L2": "экспертно-методологическая",
}


@dataclass(frozen=True)
class Redirect:
    line: str
    reason: str = ""

    @property
    def title(self) -> str:
        # Линия без человеческого названия (старые чаты с L3) — только код,
        # иначе получается висячее тире «L3 — ».
        name = LINE_NAMES.get(self.line)
        return f"{self.line} — {name}" if name else self.line


def load_lines_manual() -> str:
    """Мануал по линиям поддержки — подставляется в системный промпт."""
    if not MANUAL_PATH.exists():
        return ""
    return MANUAL_PATH.read_text(encoding="utf-8").strip()


def normalize_line(line: str) -> str | None:
    """Принимает 'l1', 'L1', '1', 'линия 1' и приводит к 'L1'.

    L3 в справочнике больше нет (её обрабатывает техническое подразделение вне
    Портала), поэтому '3' не принимается: иначе чат закрывался бы на линию,
    которой нет ни в списке линий, ни в названиях.
    """
    raw = "".join((line or "").split()).upper().removeprefix("ЛИНИЯ").removeprefix("LINE").removeprefix("L")
    return f"L{raw}" if raw in ("1", "2") else None


def transfer_to_support(line: str, reason: str = "") -> str:
    """Перевести обращение на линию поддержки и завершить чат.

    Вызывай, когда в базе знаний ответа нет, а мануал по линиям подтверждает,
    что вопрос переводится (он целиком есть в системном промпте).
    Если вопрос вообще не относится к Порталу поставщиков — не вызывай,
    а вежливо скажи, что вопрос не по теме.

    line — одна из линий: L1 или L2.
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

        Вызывай, когда в базе знаний ответа нет, а мануал по линиям подтверждает,
        что вопрос переводится (он целиком есть в системном промпте).
        Если вопрос вообще не относится к Порталу поставщиков — не вызывай,
        а вежливо скажи, что вопрос не по теме.

        line — одна из линий: L1 или L2.
        reason — короткое пояснение для оператора, что случилось (1 предложение).
        """
        normalized = normalize_line(line)
        if normalized is None:
            return f"Неизвестная линия '{line}'. Доступны только: {', '.join(LINES)}."
        self.redirect = Redirect(line=normalized, reason=" ".join((reason or "").split())[:300])
        return f"Перевод на линию {normalized} принят, чат завершён."


def _transfer(line: str, reason: str) -> str:
    """Безсессионный вариант (CLI, тесты) — без сохранения состояния чата."""
    normalized = normalize_line(line)
    if normalized is None:
        return f"Неизвестная линия '{line}'. Доступны только: {', '.join(LINES)}."
    return f"Перевод на линию {normalized} принят, чат завершён."
