#!/usr/bin/env python3
"""One-off (idempotent) repairs of the numbering artefacts in raw-md/*.md.

The source PDFs occasionally reuse section numbers, emit headings without
numbers and put a section title after its first subsection. Fixes below make
every document a proper tree: unique ids, depth growing one step at a time.

Already-applied fixes are skipped, so it is safe to re-run.

Usage: python3 fix_raw_md.py
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW_DIR = HERE / "raw-md"

SUPPLIER = "Инструкция по работе с Порталом для поставщика.md"
CUSTOMER = "Инструкция по работе с Порталом для заказчика.md"
YML = "Инструкция по формированию YML.md"

# ("replace", old heading, new heading)
# ("merge", "<id>", "orphan title line", new heading)
# ("move", heading, "line it must precede")
FIXES: dict[str, list[tuple]] = {
    # 8.1.2.1 / 8.1.2.2 got "## 1", "## 2", "## 3", "## 3.1", "## 4", "## 4.1" subsections
    SUPPLIER: [
        ("replace", "## 1 Утвержденная заявка", "## 8.1.2.1.1 Утвержденная заявка"),
        ("replace", "## 2 Доработка заявки, повторная подача", "## 8.1.2.1.2 Доработка заявки, повторная подача"),
        ("replace", "## 1. Заявка ожидает подписания", "## 8.1.2.2.1. Заявка ожидает подписания"),
        ("replace", "## 2. Заявка на рассмотрении", "## 8.1.2.2.2. Заявка на рассмотрении"),
        ("replace", "## 3. Доступные действия с ответами от банков", "## 8.1.2.2.3. Доступные действия с ответами от банков"),
        ("replace", "## 3.1. Изменить заявку", "## 8.1.2.2.3.1. Изменить заявку"),
        ("replace", "## 4. Работа с ответами банков", "## 8.1.2.2.4. Работа с ответами банков"),
        ("replace", "## 4.1. Выбрать ответ с одобрением и внести правки в оферту",
                    "## 8.1.2.2.4.1. Выбрать ответ с одобрением и внести правки в оферту"),
        ("replace", "## 4.2. Выбрать ответ с замечаниями и отправить на повторное рассмотрение",
                    "## 8.1.2.2.4.2. Выбрать ответ с замечаниями и отправить на повторное рассмотрение"),
        ("replace", "## 4.3. Выбрать ответ с одобрением и подписать оферту",
                    "## 8.1.2.2.4.3. Выбрать ответ с одобрением и подписать оферту"),
        # step of a process diagram, not a section
        ("replace", "## 1. Заказчик формирует проект контракта и направляет поставщику",
                    "Заказчик формирует проект контракта и направляет поставщику"),
        # line of the "Способ размещения закупки" list, not a section
        ("replace", "## 18. Реализация входных билетов и абонементов",
                    "18. Реализация входных билетов и абонементов"),
        # heading without a number, title on the next line
        ("merge", "## 14.2.2", "## Просмотр жалобы о необоснованной блокировке",
                  "## 14.2.2 Просмотр жалобы о необоснованной блокировке"),
        # "## 22 Контракты" was printed after its own subsection "## 22.1"
        ("move", "## 22 Контракты", "## 22.1 Реестр контрактов"),
    ],
    # 10.1/10.2/10.3 were never renumbered when the section became 12
    CUSTOMER: [
        ("replace", "## 10.1. Поиск контрактов", "## 12.1. Поиск контрактов"),
        ("replace", "## 10.2. Список контрактов", "## 12.2. Список контрактов"),
        ("replace", "## 10.3. Страница контракта", "## 12.3. Страница контракта"),
    ],
    # headings without a number / title split across two lines
    YML: [
        ("merge", "## 1.5.1.2", "## Атрибут days - срок доставки",
                  "## 1.5.1.2 Атрибут days - срок доставки"),
        ("merge", "## 1.5.1.3", "## Атрибут order-before - время заказа",
                  "## 1.5.1.3 Атрибут order-before - время заказа"),
        ("merge", "## 1.5.1.4 в прайс-", "## Как использовать элемент листе",
                  "## 1.5.1.4 Как использовать элемент в прайс-листе"),
    ],
}


def locate(lines: list[str], text: str) -> int | None:
    hits = [i for i, line in enumerate(lines) if line == text]
    if len(hits) > 1:
        raise SystemExit(f"ambiguous line ({len(hits)} matches): {text!r}")
    return hits[0] if hits else None


def fix(path: Path, ops: list[tuple]) -> list[str]:
    lines = path.read_text(encoding="utf-8").split("\n")
    log = []
    for op in ops:
        kind = op[0]
        if kind == "replace":
            _, old, new = op
            i = locate(lines, old)
            if i is None:
                if locate(lines, new) is None:
                    raise SystemExit(f"{path.name}: cannot find {old!r}")
                continue
            lines[i] = new
            log.append(f"  стр.{i + 1}: {old}  ->  {new}")
        elif kind == "merge":
            _, id_line, title_line, new = op
            i = locate(lines, id_line)
            if i is None:
                if locate(lines, new) is None:
                    raise SystemExit(f"{path.name}: cannot find {id_line!r}")
                continue
            j = locate(lines, title_line)
            if j != i + 2 or lines[i + 1].strip():
                raise SystemExit(f"{path.name}: {id_line!r} is not followed by {title_line!r}")
            lines[i] = new
            del lines[i + 1 : i + 3]
            log.append(f"  стр.{i + 1}+{j + 1}: {id_line} + {title_line}  ->  {new}")
        elif kind == "move":
            _, heading, before = op
            i, j = locate(lines, heading), locate(lines, before)
            if i < j:
                continue
            if not (lines[i - 1].strip() == "" and lines[i + 1].strip() == ""):
                raise SystemExit(f"{path.name}: {heading!r} is not a standalone block")
            chunk = [lines[i], lines[i + 1]]
            del lines[i - 1 : i + 1]
            j = locate(lines, before)
            lines[j:j] = chunk
            log.append(f"  стр.{i + 1}: {heading}  ->  перед стр.{j + 1} ({before})")
        else:
            raise SystemExit(f"unknown op {kind!r}")
    if log:
        path.write_text("\n".join(lines), encoding="utf-8")
    return log


def main() -> None:
    for name, ops in FIXES.items():
        path = RAW_DIR / name
        if not path.exists():
            print(f"{name}: нет файла, пропуск")
            continue
        log = fix(path, ops)
        print(f"{name}: {'исправлено' if log else 'уже исправлено'}")
        print("\n".join(log))


if __name__ == "__main__":
    main()
