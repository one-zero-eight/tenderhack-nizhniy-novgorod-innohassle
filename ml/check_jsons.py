#!/usr/bin/env python3
"""Проверка целостности jsons/ после process.py.

Что проверяем:
  - фронтматтер: есть name и slug, slug совпадает с именем файла;
  - все ссылки ![..](__IMG_PREFIX__/<slug>/image-N.png) резолвятся в файл;
  - в jsons/<slug>/ нет файлов, на которые никто не ссылается;
  - все ноды достижимы из разделов верхнего уровня, все children существуют;
  - нет дубликатов id (ключей вида "18#2"), пустых заголовков и расхождения
    глубины ключа с глубиной в дереве.

Usage: python3 check_jsons.py   (код возврата 1, если что-то не так)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JSONS_DIR = HERE / "jsons"
IMG_REF = re.compile(r"!\[[^\]]*\]\(__IMG_PREFIX__/([^/]+)/(image-\d+(?:-\d+)?\.\w+)\)")
META_KEY = "_meta"


def check(path: Path) -> list[str]:
    slug = path.stem
    raw: dict[str, dict] = json.loads(path.read_text(encoding="utf-8"))
    problems: list[str] = []

    meta = raw.pop(META_KEY, None)
    nodes = {k: v for k, v in raw.items() if k != META_KEY}
    if not meta:
        problems.append(f"{slug}: нет секции {META_KEY} с name/slug")
    else:
        for key in ("name", "slug"):
            if not str(meta.get(key) or "").strip():
                problems.append(f"{slug}: пустой {key} в {META_KEY}")
        if meta.get("slug") and meta["slug"] != slug:
            problems.append(f"{slug}: slug в {META_KEY} ('{meta['slug']}') не совпадает с именем файла")

    # дерево: достижимость, существование детей, глубина
    roots = [node_id for node_id in nodes if not any(node_id in (n.get("children") or []) for n in nodes.values())]
    if not roots:
        problems.append(f"{slug}: нет ни одного раздела верхнего уровня")
    depth = {node_id: 0 for node_id in roots}
    queue = list(roots)
    while queue:
        node_id = queue.pop()
        for child in nodes[node_id]["children"]:
            if child not in nodes:
                problems.append(f"{slug}: {node_id} ссылается на несуществующую ноду {child}")
                continue
            if child in depth:
                problems.append(f"{slug}: нода {child} встречается в children дважды")
                continue
            depth[child] = depth[node_id] + 1
            queue.append(child)
    unreachable = sorted(set(nodes) - set(depth))
    if unreachable:
        problems.append(f"{slug}: недостижимые ноды {unreachable[:5]}")

    # Глубина в дереве считается от верхнего раздела (у него 0), а не от номера
    # ключа: ключи начинаются с "2", но root-ноды больше нет.
    numeric_depth = {node_id: len(node_id.split("#")[0].split(".")) - 1 for node_id in nodes}
    for node_id, node in nodes.items():
        if depth.get(node_id) != numeric_depth[node_id]:
            problems.append(
                f"{slug}: ключ {node_id} на глубине {depth.get(node_id)} в дереве, "
                f"а по номеру ожидается {numeric_depth[node_id]}"
            )
        if not node["heading"].strip():
            problems.append(f"{slug}: у ноды {node_id} пустой heading")
        if "#" in node_id:
            problems.append(f"{slug}: дубликат id {node_id}")

    # картинки: ссылки <-> файлы
    referenced = {name for _, name in IMG_REF.findall(json.dumps(nodes, ensure_ascii=False))}
    img_dir = JSONS_DIR / slug
    present = {p.name for p in img_dir.iterdir()} if img_dir.is_dir() else set()
    for name in sorted(referenced):
        if not (img_dir / name).exists():
            problems.append(f"{slug}: ссылка на отсутствующий файл {name}")
    for name in sorted(present - referenced):
        problems.append(f"{slug}: файл {name} никем не используется")

    if not problems:
        print(f"  ok  {slug:26} разделов={len(nodes):4} картинок={len(present):4} верхних={len(roots)}")
    return problems


def main() -> int:
    paths = sorted(JSONS_DIR.glob("*.json"))
    if not paths:
        print(f"нет json в {JSONS_DIR} — сначала `just process`", file=sys.stderr)
        return 1

    problems = [p for path in paths for p in check(path)]
    if problems:
        print("\nпроблемы:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"\nвсего мануалов: {len(paths)} — всё чисто")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
