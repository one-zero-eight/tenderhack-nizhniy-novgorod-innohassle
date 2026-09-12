"""Загрузка размеченных мануалов из jsons/*.json (см. process.py).

Один мануал = один json: плоская мапа нод {"root" | "x.x.x": {heading, text, children}}.
Здесь она разворачивается в Section'ы со ссылками на предков, чтобы поиску и агенту
не приходилось каждый раз ходить по дереву.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

JSONS_DIR = Path(__file__).resolve().parent / "jsons"
ROOT = "root"

# Плейсхолдер из process.py для картинок и публичный префикс, куда их подставляет app.
IMG_PLACEHOLDER = "__IMG_PREFIX__"
IMG_PREFIX = "/ml-assets/image"


@dataclass(frozen=True)
class Section:
    manual: str  # slug мануала
    manual_title: str
    id: str  # "root" | "2.4.1"
    heading: str
    text: str
    children: tuple[str, ...]
    ancestors: tuple[str, ...]  # от корня вниз, без самого раздела и без "root"

    @property
    def title_line(self) -> str:
        return f"{self.id} {self.heading}".strip()


@dataclass(frozen=True)
class Manual:
    slug: str
    title: str
    sections: dict[str, Section]

    @property
    def ordered_ids(self) -> list[str]:
        return sorted(self.sections, key=_id_sort_key)


def _id_sort_key(section_id: str) -> tuple[int, ...]:
    if section_id == ROOT:
        return (-1,)
    return tuple(int(part) for part in section_id.split("."))


def load_manual(path: Path) -> Manual:
    raw: dict[str, dict] = json.loads(path.read_text(encoding="utf-8"))
    slug = path.stem
    title = (raw.get(ROOT) or {}).get("heading", "").strip() or slug

    ancestors: dict[str, tuple[str, ...]] = {ROOT: ()}
    queue = [ROOT]
    while queue:
        current = queue.pop()
        for child in raw.get(current, {}).get("children", []):
            if child in raw and child not in ancestors:
                ancestors[child] = (*ancestors[current], current)
                queue.append(child)

    sections = {
        node_id: Section(
            manual=slug,
            manual_title=title,
            id=node_id,
            heading=(node.get("heading") or "").strip(),
            text=(node.get("text") or "").strip(),
            children=tuple(node.get("children") or ()),
            ancestors=tuple(a for a in ancestors.get(node_id, ()) if a != ROOT),
        )
        for node_id, node in raw.items()
    }
    return Manual(slug=slug, title=title, sections=sections)


def load_manuals(jsons_dir: Path = JSONS_DIR) -> dict[str, Manual]:
    return {path.stem: load_manual(path) for path in sorted(jsons_dir.glob("*.json"))}


def manuals_overview(manuals: dict[str, Manual]) -> str:
    """Список мануалов для системного промпта: slug + название."""
    lines = []
    for manual in manuals.values():
        lines.append(f"- {manual.slug} — {manual.title}")
    return "\n".join(lines)


def resolve_manual(manuals: dict[str, Manual], value: str) -> Manual | None:
    """Принимает slug, кусок slug или название мануала."""
    key = " ".join((value or "").split()).strip().lower()
    if not key:
        return None
    if key in manuals:
        return manuals[key]
    loose = re.sub(r"[^a-z0-9а-яё]+", "-", key).strip("-")
    for slug, manual in manuals.items():
        if slug == loose or manual.title.lower() == key:
            return manual
    candidates = [m for slug, m in manuals.items() if key in slug or loose in slug or key in m.title.lower()]
    return candidates[0] if len(candidates) == 1 else None


def tree_rows(manual: Manual, ids: list[str]) -> list[tuple[int, Section, bool]]:
    """Строки дерева для найденных id: сами совпадения + все их предки, без дублей.

    Возвращает (отступ, раздел, это_совпадение) в порядке документа, а не в порядке
    релевантности — чтобы агенту было видно структуру, а не ранжирование.
    """
    hits = {node_id for node_id in ids if node_id in manual.sections}
    rows: dict[str, tuple[int, Section, bool]] = {}
    for node_id in sorted(hits, key=_id_sort_key):
        section = manual.sections[node_id]
        for ancestor in section.ancestors:
            rows.setdefault(ancestor, (len(manual.sections[ancestor].ancestors), manual.sections[ancestor], False))
        rows[node_id] = (len(section.ancestors), section, True)
    return [rows[node_id] for node_id in sorted(rows, key=_id_sort_key)]


def render_tree(manual: Manual, ids: list[str]) -> str:
    lines = []
    for depth, section, is_hit in tree_rows(manual, ids):
        marker = "  [найдено]" if is_hit else ""
        lines.append(f"{'  ' * depth}- {section.title_line}{marker}")
    return "\n".join(lines)


def section_body(section: Section) -> str:
    body = section.text or "(текст раздела пустой — он только группирует подразделы)"
    # Агенту и фронтенду нужны рабочие ссылки на картинки, а не плейсхолдер.
    return body.replace(IMG_PLACEHOLDER, IMG_PREFIX)


def render_section(manual: Manual, section: Section) -> str:
    """Ответ инструмента open: шапка + подразделы + текст."""
    path = " > ".join([manual.title, *(f"{a} {manual.sections[a].heading}".strip() for a in section.ancestors)])
    lines = [
        f"мануал: {manual.slug} — {manual.title}",
        f"раздел: {section.title_line}",
        f"путь: {path}",
    ]
    if section.children:
        lines.append(f"подразделы ({len(section.children)}):")
        lines += [f"- {manual.sections[c].title_line}" for c in section.children if c in manual.sections]
    else:
        lines.append("подразделы: нет")
    lines += ["", section_body(section)]
    return "\n".join(lines)
