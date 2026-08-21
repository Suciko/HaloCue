# -*- coding: utf-8 -*-
"""Convert the community Markdown portrait-position table into safe hints."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


DIRECTION = {"偏左": "left", "居中": "center", "偏右": "right"}
FRAMING = {"特写": "closeup", "半身": "half", "全身": "full"}


def parse(path: Path) -> dict:
    grouped = defaultdict(list)
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.startswith("|") or raw.startswith("|---") or raw.startswith("| 角色 "):
            continue
        parts = [part.strip() for part in raw.strip().strip("|").split("|")]
        if len(parts) != 6:
            continue
        name, skins, weapon, wings, face, framing = parts
        grouped[name].append({
            "skin_count": int(skins) if skins.isdigit() else None,
            "has_weapon": weapon == "有",
            "has_wings": wings == "有",
            "face_direction": DIRECTION.get(face),
            "framing": FRAMING.get(framing),
        })

    def consensus(rows, key):
        values = {row[key] for row in rows if row[key] is not None}
        return next(iter(values)) if len(values) == 1 else None

    characters = {}
    for name, rows in sorted(grouped.items()):
        characters[name] = {
            "hint_count": len(rows),
            "skin_count": max((row["skin_count"] or 0) for row in rows),
            "face_direction": consensus(rows, "face_direction"),
            "has_weapon": consensus(rows, "has_weapon"),
            "has_wings": consensus(rows, "has_wings"),
            "framing": consensus(rows, "framing"),
            "observed": rows,
        }
    return {
        "version": 1,
        "source": "community_face_pos_default_skin_export",
        "input_rows": sum(len(rows) for rows in grouped.values()),
        "characters": characters,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload = parse(args.source)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"rows={payload['input_rows']} characters={len(payload['characters'])} "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
