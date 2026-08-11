from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def _read_manifest(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if payload.get("schema_version") != 1 or not isinstance(payload.get("records"), list):
        return None
    return payload


def seed_bundled_previews(seed_root: str | Path, destination: str | Path) -> int:
    source_root = Path(seed_root)
    target_root = Path(destination)
    bundled = _read_manifest(source_root / "manifest.json")
    if bundled is None:
        return 0

    existing = _read_manifest(target_root / "manifest.json") or {
        "schema_version": 1,
        "status": "ready",
        "fingerprint": "",
        "records": [],
        "failures": [],
    }
    bundled_identities = {
        (str(row.get("kind") or ""), str(row.get("normalized_key") or ""))
        for row in bundled["records"]
    }
    records = []
    known = set()
    for row in existing["records"]:
        identity = (str(row.get("kind") or ""), str(row.get("normalized_key") or ""))
        relative = Path(str(row.get("path") or ""))
        if not all(identity) or relative.is_absolute() or ".." in relative.parts:
            continue
        bundled_row = next(
            (
                candidate
                for candidate in bundled["records"]
                if (
                    str(candidate.get("kind") or ""),
                    str(candidate.get("normalized_key") or ""),
                ) == identity
            ),
            None,
        )
        if identity in bundled_identities and (
            not (target_root / relative).is_file()
            or str((bundled_row or {}).get("path") or "") != str(row.get("path") or "")
        ):
            continue
        records.append(row)
        known.add(identity)
    copied = 0
    for row in bundled["records"]:
        identity = (str(row.get("kind") or ""), str(row.get("normalized_key") or ""))
        if not all(identity) or identity in known:
            continue
        relative = Path(str(row.get("path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            continue
        source = source_root / relative
        target = target_root / relative
        if not source.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source, target)
        records.append(dict(row))
        known.add(identity)
        copied += 1

    if copied == 0 and (target_root / "manifest.json").is_file():
        return 0
    target_root.mkdir(parents=True, exist_ok=True)
    failures = list(existing.get("failures") or [])
    payload = {
        "schema_version": 1,
        "status": "partial" if failures else "ready",
        "fingerprint": str(existing.get("fingerprint") or "bundled-android-previews-v1"),
        "counts": {
            "backgrounds": sum(row.get("kind") == "background" for row in records),
            "avatars": sum(row.get("kind") == "avatar" for row in records),
            "failed": len(failures),
        },
        "records": records,
        "failures": failures,
    }
    temporary = target_root / "manifest.json.tmp"
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, target_root / "manifest.json")
    return copied
