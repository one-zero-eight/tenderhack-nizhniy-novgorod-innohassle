#!/usr/bin/env python3
"""Проверка целостности jsons/ после process.py.

Что проверяем:
  - все ссылки ![..](__IMG_PREFIX__/<slug>/image-N.png) резолвятся в файл;
  - в jsons/<slug>/ нет файлов, на которые никто не ссылается;
  - все ноды достижимы из root, все children существуют;
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


def check(path: Path) -> list[str]:
    slug = path.stem
    nodes: dict[str, dict] = json.loads(path.read_text(encoding="utf-8"))
    problems: list[str] = []

    if "root" not in nodes:
        return [f"{slug}: нет ноды root"]
    if not nodes["root"]["heading"].strip():
        problems.append(f"{slug}: у root пустой heading")

    # дерево: достижимость, существование детей, глубина
    depth = {"root": 0}
    queue = ["root"]
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

    for node_id, node in nodes.items():
        if node_id != "root" and depth.get(node_id) != len(node_id.split(".")):
            problems.append(f"{slug}: ключ {node_id} на глубине {depth.get(node_id)} в дереве")
        if node_id != "root" and not node["heading"].strip():
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
        print(
            f"  ok  {slug:58} разделов={len(nodes) - 1:4} "
            f"картинок={len(present):4} корневых={len(nodes['root']['children'])}"
        )
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
