"""Normalize stored visual semantic fields without changing manual edits."""

from __future__ import annotations

import argparse
from pathlib import Path

import assetdb
from face_semantics import migrate_semantic_storage


HERE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(HERE / "aa_assets.db"))
    parser.add_argument("--active-model", default="")
    args = parser.parse_args(argv)
    con = assetdb.connect(args.db)
    if args.active_model:
        assetdb.set_active_face_label_model(con, args.active_model)
    print(migrate_semantic_storage(con))
    print(f"active_face_label_model={assetdb.active_face_label_model(con)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
