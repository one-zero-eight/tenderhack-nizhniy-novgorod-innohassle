#!/usr/bin/env python3
"""raw-md/*.md  ->  jsons/<slug>.json  +  jsons/<slug>/image-<id>.<ext>

One .md file -> one .json file: frontmatter (name/slug) + a flat map of nodes
keyed by "x.x.x", each node = {heading, text, children}. Верхнеуровневые разделы
("2", "2.1") — обычные ноды с номером, отдельного корня нет.

Figure captions ("Рисунок N - ...") are bound to the neighbouring image, the
image file is copied to jsons/<slug>/image-<N>.<ext> and the markdown reference
is rewritten to ![caption](__IMG_PREFIX__/<slug>/image-<N>.<ext>).

Usage: python3 process.py
"""

from __future__ import annotations

import json
import re
import shutil
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW_DIR = HERE / "raw-md"
OUT_DIR = HERE / "jsons"
IMG_PLACEHOLDER = "__IMG_PREFIX__"

# Служебные файлы raw-md: не мануалы, в jsons/ им не место.
# topics.md собирает build_topics.py, остальные — рабочие источники парсера обращений.
SKIP_FILES = {"topics.md", "Темы_подтемы_обращений.md", "support-redirect-manual.md"}

IMAGE_RE = re.compile(r"^!\[[^\]]*\]\((?P<src>[^)]+)\)\s*$")
CAPTION_RE = re.compile(r"^(?:##\s+|- |\*\s+)?Рисунок\s+(?P<id>\d+)\s*[-–—]\s*(?P<caption>.*?)\s*$")
SECTION_RE = re.compile(r"^##\s+(?P<id>\d+(?:\.\d+)*)\.?(?![\w)])\s*(?P<heading>.*?)\s*$")
TITLE_RE = re.compile(r"^#\s+(?P<heading>.+?)\s*$")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*(?:\n|\Z)", re.S)
# Старый вариант разметки: '# Заголовок' остался выше frontmatter в одном из файлов.
TITLE_BEFORE_FRONTMATTER_RE = re.compile(
    r"\A#\s*(?P<title>.+?)\s*\n\s*\n---\s*\n\s*\n(?P<body>.*?)\n---\s*(?:\n|\Z)", re.S
)

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e",
    "ю": "yu", "я": "ya",
}


def slugify(name: str) -> str:
    """'Инструкция по работе с МЧД' -> 'instrukciya-po-rabote-s-mchd'."""
    latin = "".join(TRANSLIT.get(ch, ch) for ch in name.lower())
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", latin)).strip("-")


def parse_frontmatter(text: str, fallback_name: str) -> tuple[dict[str, str], list[str], str]:
    """Возвращает (frontmatter, строки без него, найденный '# ' заголовок).

    Понимает оба формата: обычный frontmatter в начале файла и вариант, где
    выше frontmatter остался старый '# Заголовок'. Заголовок идёт в name,
    если в frontmatter его нет.
    """
    title = ""
    match = TITLE_BEFORE_FRONTMATTER_RE.match(text)
    if match:
        title = match.group("title").strip()
        text = match.group("body") + "\n" + text[match.end() :]
    else:
        match = FRONTMATTER_RE.match(text)
        if match:
            text = text[match.end() :]

    meta: dict[str, str] = {}
    for line in (match.group("body") if match else "").split("\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip().strip("'\"")
        if value:
            meta[key.strip().lower()] = value

    # '# Заголовок' мог остаться в теле файла — забираем его и выкидываем строку.
    lines = text.split("\n")
    if not title:
        for i, line in enumerate(lines):
            title_match = TITLE_RE.match(line)
            if title_match:
                title = title_match.group("heading").strip()
                lines.pop(i)
                break

    meta.setdefault("name", title or fallback_name)
    meta.setdefault("slug", slugify(fallback_name))
    return meta, lines, title


def bind_images(lines: list[str]) -> dict[int, tuple[str, str, str]]:
    """Map image line index -> (image name, caption, source path).

    A caption owns the image next to it (only blank lines in between),
    preferring the image above it, and is ignored if there is none.
    Caption-less images get ids continuing after the last figure number.
    """
    images = {i: IMAGE_RE.match(line).group("src") for i, line in enumerate(lines) if IMAGE_RE.match(line)}
    captions = {i: m for i, line in enumerate(lines) if i not in images and (m := CAPTION_RE.match(line))}

    owners: dict[int, tuple[int, str]] = {}
    for pos in sorted(captions):
        above, below = pos - 1, pos + 1
        while above >= 0 and not lines[above].strip():
            above -= 1
        while below < len(lines) and not lines[below].strip():
            below += 1
        target = next((i for i in (above, below) if i in images and i not in owners), None)
        if target is not None:
            m = captions[pos]
            owners[target] = (int(m.group("id")), m.group("caption") or f"Рисунок {m.group('id')}")

    next_free = max((fid for fid, _ in owners.values()), default=0) + 1
    for i in sorted(images):
        if i not in owners:
            owners[i] = (next_free, "")
            next_free += 1

    used: dict[int, int] = {}
    binding: dict[int, tuple[str, str, str]] = {}
    for i in sorted(owners):
        fig_id, caption = owners[i]
        used[fig_id] = used.get(fig_id, 0) + 1
        suffix = "" if used[fig_id] == 1 else f"-{used[fig_id]}"
        binding[i] = (f"image-{fig_id}{suffix}", caption, images[i])
    return binding


def image_reference(name: str, caption: str, src: str, slug: str) -> str:
    alt = caption.replace("[", r"\[").replace("]", r"\]")
    return f"![{alt}]({IMG_PLACEHOLDER}/{slug}/{name}{Path(src).suffix})"


def build_nodes(lines: list[str]) -> dict[str, dict]:
    """Flat map: one node per '## x.x.x' heading, no synthetic root.

    Depth comes from the id itself (1 -> 1.1 -> 1.1.1); anything after '## '
    that is not an id (tables, figure captions, ...) stays in the text.
    Верхнеуровневые разделы ('## 2') имеют parent=None в списке children родителя.
    """
    nodes: dict[str, dict] = {}
    seen: dict[str, int] = {}
    stack: list[tuple[int, str]] = []  # (depth, key)

    def new_key(node_id: str) -> str:
        seen[node_id] = seen.get(node_id, 0) + 1
        return node_id if seen[node_id] == 1 else f"{node_id}#{seen[node_id]}"

    children_of: dict[str | None, list[str]] = {None: []}
    bodies: dict[str | None, list[str]] = {None: []}
    body = bodies[None]

    for line in lines:
        section = SECTION_RE.match(line)
        if section:
            node_id = section.group("id")
            key = new_key(node_id)
            while stack and stack[-1][0] >= node_id.count(".") + 1:
                stack.pop()
            parent = stack[-1][1] if stack else None
            nodes[key] = {"heading": section.group("heading"), "text": [], "children": []}
            children_of.setdefault(parent, []).append(key)
            bodies[key] = nodes[key]["text"]
            stack.append((node_id.count(".") + 1, key))
            body = nodes[key]["text"]
        else:
            body.append(line)

    # Строки до первого '## ' (вступление) отдаём первому верхнеуровневому разделу,
    # чтобы текст не потерялся и раздела без номера не было.
    intro = [line for line in bodies[None] if line.strip()]
    top_level = children_of[None]
    if intro and top_level:
        nodes[top_level[0]]["text"] = [*intro, "", *nodes[top_level[0]]["text"]]
    elif intro:
        nodes["1"] = {"heading": "", "text": intro, "children": []}
        children_of[None].append("1")

    for key, node in nodes.items():
        node["children"] = children_of.get(key, [])
    return nodes


def process(md_path: Path) -> tuple[str, dict[str, dict], int, dict[str, str]]:
    raw_text = md_path.read_text(encoding="utf-8")
    meta, lines, _ = parse_frontmatter(raw_text, md_path.stem)
    # slug из frontmatter задаёт и имя json-файла, и папку с картинками.
    slug = meta["slug"]
    binding = bind_images(lines)

    img_dir = OUT_DIR / slug
    rewritten = []
    for i, line in enumerate(lines):
        if i not in binding:
            rewritten.append(line)
            continue
        name, caption, src = binding[i]
        dest = img_dir / f"{name}{Path(src).suffix}"
        img_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(RAW_DIR / urllib.parse.unquote(src), dest)
        rewritten.append(image_reference(name, caption, src, slug))

    nodes = build_nodes(rewritten)
    for node in nodes.values():
        node["text"] = "\n".join(node["text"]).strip()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # name — человеческое название (уходит в контекст агента), slug — короткий id.
    payload = {"_meta": {"name": meta["name"], "slug": slug}, **nodes}
    (OUT_DIR / f"{slug}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return slug, nodes, len(binding), meta


def main() -> None:
    for md_path in sorted(RAW_DIR.glob("*.md")):
        if md_path.name in SKIP_FILES:
            print(f"{md_path.name}\n  -- пропущен (служебный)")
            continue
        slug, nodes, images, meta = process(md_path)
        print(
            f"{md_path.name}\n  -> jsons/{slug}.json  nodes={len(nodes)} "
            f"images={images} name='{meta['name']}'"
        )


if __name__ == "__main__":
    main()
