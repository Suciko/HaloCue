"""Import compact official face-use contexts into ``aa_assets.db``.

The JSON index is a build artifact. Runtime consumers read the SQLite table,
so this command is the only boundary that turns the official corpus into
promptable evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assetdb


HERE = Path(__file__).resolve().parents[1]
DEFAULT_DB = HERE / "aa_assets.db"
DEFAULT_INDEX = HERE.parents[1] / "05-官方演出语料库" / "derived" / "face_text_examples.json"


def load_records(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    characters = payload.get("characters") if isinstance(payload, dict) else {}
    records = []
    for ident, faces in (characters or {}).items():
        if not isinstance(faces, dict):
            continue
        for face_id, examples in faces.items():
            for index, example in enumerate(examples or []):
                if not isinstance(example, dict):
                    continue
                uid = str(example.get("record_uid") or "").strip()
                if not uid:
                    continue
                records.append({
                    "ident": ident,
                    "face_id": face_id,
                    "record_uid": f"{uid}:{index}",
                    "text_cn": example.get("text") or "",
                    "silent": bool(example.get("silent")),
                    "emoticons": example.get("emoticons") or [],
                    "actions": example.get("actions") or [],
                    "closeup": bool(example.get("closeup")),
                })
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    args = parser.parse_args()
    records = load_records(args.index)
    con = assetdb.connect(args.db)
    try:
        count = assetdb.replace_face_official_usage(con, records)
        total = con.execute("SELECT COUNT(*) FROM face_official_usage").fetchone()[0]
    finally:
        con.close()
    print(f"导入官方表情语境 {count} 条；数据库现有 {total} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
