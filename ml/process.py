#!/usr/bin/env python3
"""raw-md/*.md  ->  jsons/<slug>.json  +  jsons/<slug>/image-<id>.<ext>

One .md file -> one .json file: a flat map of nodes keyed by "root" / "x.x.x",
each node = {heading, text, children}.

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

IMAGE_RE = re.compile(r"^!\[[^\]]*\]\((?P<src>[^)]+)\)\s*$")
CAPTION_RE = re.compile(r"^(?:##\s+|- |\*\s+)?Рисунок\s+(?P<id>\d+)\s*[-–—]\s*(?P<caption>.*?)\s*$")
SECTION_RE = re.compile(r"^##\s+(?P<id>\d+(?:\.\d+)*)\.?(?![\w)])\s*(?P<heading>.*?)\s*$")
TITLE_RE = re.compile(r"^#\s+(?P<heading>.+?)\s*$")

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
    """Flat map: 'root' (the '# ' title) + one node per '## x.x.x' heading.

    Depth comes from the id itself (1 -> 1.1 -> 1.1.1); anything after '## '
    that is not an id (tables, figure captions, ...) stays in the text.
    """
    nodes: dict[str, dict] = {}
    seen: dict[str, int] = {}
    stack: list[tuple[int, str]] = []  # (depth, key)

    def new_key(node_id: str) -> str:
        seen[node_id] = seen.get(node_id, 0) + 1
        return node_id if seen[node_id] == 1 else f"{node_id}#{seen[node_id]}"

    root = {"heading": "", "text": [], "children": []}
    nodes["root"] = root
    body = root["text"]

    for line in lines:
        section = SECTION_RE.match(line)
        if section:
            node_id = section.group("id")
            key = new_key(node_id)
            while stack and stack[-1][0] >= node_id.count(".") + 1:
                stack.pop()
            parent = stack[-1][1] if stack else "root"
            nodes[key] = {"heading": section.group("heading"), "text": [], "children": []}
            nodes[parent]["children"].append(key)
            stack.append((node_id.count(".") + 1, key))
            body = nodes[key]["text"]
        elif not root["heading"] and TITLE_RE.match(line):
            root["heading"] = TITLE_RE.match(line).group("heading")
        else:
            body.append(line)
    return nodes


def process(md_path: Path) -> tuple[str, dict[str, dict], int]:
    slug = slugify(md_path.stem)
    lines = md_path.read_text(encoding="utf-8").split("\n")
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
    (OUT_DIR / f"{slug}.json").write_text(
        json.dumps(nodes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return slug, nodes, len(binding)


def main() -> None:
    for md_path in sorted(RAW_DIR.glob("*.md")):
        slug, nodes, images = process(md_path)
        empty = sum(1 for n in nodes.values() if not n["heading"])
        print(f"{md_path.name}\n  -> jsons/{slug}.json  nodes={len(nodes) - 1} images={images} empty_headings={empty}")


if __name__ == "__main__":
    main()
