"""Verify every shipped reference against its compressed and original digest."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def verify(root: Path) -> dict:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    records = 0
    for relative, expected in manifest["files"].items():
        path = (root / relative).resolve()
        path.relative_to(root.resolve())
        data = path.read_bytes()
        if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
            raise ValueError(f"reference integrity mismatch: {relative}")
        if "uncompressed_sha256" not in expected:
            continue
        digest = hashlib.sha256()
        size = 0
        lines = 0
        with gzip.open(path, "rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
                lines += chunk.count(b"\n")
        if (
            size != expected["uncompressed_bytes"]
            or digest.hexdigest() != expected["uncompressed_sha256"]
        ):
            raise ValueError(f"uncompressed integrity mismatch: {relative}")
        if relative.startswith("official-staging/records/"):
            source_name = relative.removeprefix("official-staging/").removesuffix(".gz")
            original = manifest["corpus_source"]["files"][source_name]
            if size != original["bytes"] or digest.hexdigest() != original["sha256"]:
                raise ValueError(f"original extraction mismatch: {relative}")
            records += lines
    cards = len(list((root / "characters").glob("*.json")))
    if (
        cards != manifest["character_card_count"]
        or records != manifest["corpus_source"]["record_counts"]["total"]
    ):
        raise ValueError("reference count mismatch")
    return {
        "ok": True,
        "files": len(manifest["files"]),
        "character_cards": cards,
        "official_records": records,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1] / "data/reference-pack"
    )
    print(json.dumps(verify(parser.parse_args().root)))
