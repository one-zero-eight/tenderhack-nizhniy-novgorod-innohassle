"""Загрузка размеченных мануалов из jsons/*.json (см. process.py).

Один мануал = один json: служебная секция "_meta" с name/slug и плоская мапа
нод {"x.x.x": {heading, text, children}}. Отдельного корня нет: верхнеуровневые
разделы ("2", "2.1") — такие же ноды, как и остальные.
Здесь мапа разворачивается в Section'ы со ссылками на предков.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

JSONS_DIR = Path(__file__).resolve().parent / "jsons"
META_KEY = "_meta"

# Плейсхолдер из process.py для картинок и публичный префикс, куда его подставляет app.
IMG_PLACEHOLDER = "__IMG_PREFIX__"
IMG_PREFIX = "/ml-assets/image"


@dataclass(frozen=True)
class Section:
    manual: str  # slug мануала
    manual_title: str
    id: str  # "2", "2.4.1"
    heading: str
    text: str
    children: tuple[str, ...]
    ancestors: tuple[str, ...]  # от верхнего раздела вниз, без самого раздела

    @property
    def title_line(self) -> str:
        return f"{self.id} {self.heading}".strip()


@dataclass(frozen=True)
class Manual:
    slug: str
    title: str
    name: str
    sections: dict[str, Section]

    @property
    def ordered_ids(self) -> list[str]:
        return sorted(self.sections, key=_id_sort_key)


def _id_sort_key(section_id: str) -> tuple[int, ...]:
    return tuple(int(part) for part in section_id.split("#")[0].split("."))


def load_manual(path: Path) -> Manual:
    raw: dict[str, dict] = json.loads(path.read_text(encoding="utf-8"))
    meta = raw.pop(META_KEY, {}) or {}
    slug = str(meta.get("slug") or path.stem)
    name = str(meta.get("name") or slug)

    # Предки считаем обходом от верхнеуровневых разделов (у них нет родителя).
    roots = [
        node_id
        for node_id, node in raw.items()
        if not any(node_id in (other.get("children") or []) for other in raw.values())
    ]
    ancestors: dict[str, tuple[str, ...]] = {node_id: () for node_id in roots}
    queue = list(roots)
    while queue:
        current = queue.pop()
        for child in raw.get(current, {}).get("children", []):
            if child in raw and child not in ancestors:
                ancestors[child] = (*ancestors[current], current)
                queue.append(child)

    sections = {
        node_id: Section(
            manual=slug,
            manual_title=name,
            id=node_id,
            heading=(node.get("heading") or "").strip(),
            text=(node.get("text") or "").strip(),
            children=tuple(node.get("children") or ()),
            ancestors=ancestors.get(node_id, ()),
        )
        for node_id, node in raw.items()
    }
    return Manual(slug=slug, title=name, name=name, sections=sections)


def load_manuals(jsons_dir: Path = JSONS_DIR) -> dict[str, Manual]:
    return {path.stem: load_manual(path) for path in sorted(jsons_dir.glob("*.json"))}


def manuals_overview(manuals: dict[str, Manual]) -> str:
    """Список мануалов для контекста агента: короткий slug + человеческое name."""
    return "\n".join(f"- {m.slug} — {m.name}" for m in manuals.values())


def resolve_manual(manuals: dict[str, Manual], value: str) -> Manual | None:
    """Принимает slug, кусок slug или название мануала."""
    key = " ".join((value or "").split()).strip().lower()
    if not key:
        return None
    if key in manuals:
        return manuals[key]
    loose = re.sub(r"[^a-z0-9а-яё]+", "-", key).strip("-")
    for slug, manual in manuals.items():
        if slug == loose or manual.name.lower() == key:
            return manual
    candidates = [m for slug, m in manuals.items() if key in slug or loose in slug or key in m.name.lower()]
    return candidates[0] if len(candidates) == 1 else None


# tree_rows/render_tree были нужны только выдаче search (RAG отключён).
# def tree_rows(manual: Manual, ids: list[str]) -> list[tuple[int, Section, bool]]:
#     """Строки дерева для найденных id: сами совпадения + все их предки, без дублей."""
#     hits = {node_id for node_id in ids if node_id in manual.sections}
#     rows: dict[str, tuple[int, Section, bool]] = {}
#     for node_id in sorted(hits, key=_id_sort_key):
#         section = manual.sections[node_id]
#         for ancestor in section.ancestors:
#             rows.setdefault(
#                 ancestor, (len(manual.sections[ancestor].ancestors), manual.sections[ancestor], False)
#             )
#         rows[node_id] = (len(section.ancestors), section, True)
#     return [rows[node_id] for node_id in sorted(rows, key=_id_sort_key)]
#
#
# def render_tree(manual: Manual, ids: list[str]) -> str:
#     lines = []
#     for depth, section, is_hit in tree_rows(manual, ids):
#         marker = "  [найдено]" if is_hit else ""
#         lines.append(f"{'  ' * depth}- {section.title_line}{marker}")
#     return "\n".join(lines)


def section_body(section: Section) -> str:
    body = section.text or "(текст раздела пустой — он только группирует подразделы)"
    # Агенту и фронтенду нужны рабочие ссылки на картинки, а не плейсхолдер.
    return body.replace(IMG_PLACEHOLDER, IMG_PREFIX)


def render_section(manual: Manual, section: Section) -> str:
    """Ответ инструмента read: шапка + подразделы + текст."""
    path = " > ".join([manual.name, *(f"{a} {manual.sections[a].heading}".strip() for a in section.ancestors)])
    lines = [
        f"мануал: {manual.slug} — {manual.name}",
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
