"""Explicit, recoverable migration helpers for the 0.9.3 user directory."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


LEGACY_VERSION = "0.9.3"
MIGRATION_SCHEMA = "halocue-migration/1"
MIGRATABLE_FILES = (
    "aa_assets.db",
    "aa_config.json",
    "aa_resources.json",
    "llm.json",
    "llm_profiles.json",
)


def legacy_state_path(environ: Mapping[str, str] | None = None) -> Path | None:
    env = os.environ if environ is None else environ
    local = str(env.get("LOCALAPPDATA") or "").strip()
    if not local:
        return None
    return (Path(local) / "HaloCue").resolve()


def migration_report(legacy_root: Path | None, current_root: Path) -> dict:
    legacy = legacy_root.resolve() if legacy_root else None
    current = current_root.resolve()
    detected = bool(legacy and legacy != current and legacy.is_dir())
    files = []
    if detected and legacy:
        for name in MIGRATABLE_FILES:
            source = legacy / name
            target = current / name
            if source.is_file():
                files.append({
                    "name": name,
                    "size": source.stat().st_size,
                    "target_exists": target.exists(),
                })
    return {
        "schema_version": MIGRATION_SCHEMA,
        "legacy_version": LEGACY_VERSION,
        "detected": detected,
        "legacy_root": str(legacy) if detected else "",
        "current_root": str(current),
        "files": files,
        "requires_confirmation": detected and bool(files),
    }


def backup_legacy_state(legacy_root: Path, backup_parent: Path) -> Path:
    source = Path(legacy_root).resolve(strict=True)
    if not source.is_dir() or len(source.parts) < 3:
        raise ValueError("legacy state directory is invalid")
    parent = Path(backup_parent).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = parent / f"HaloCue-legacy-{stamp}"
    shutil.copytree(source, target)
    return target


def import_legacy_state(legacy_root: Path, current_root: Path) -> dict:
    """Copy only known files and never overwrite an existing 1.0 file."""
    source = Path(legacy_root).resolve(strict=True)
    target_root = Path(current_root).resolve()
    if source == target_root or not source.is_dir():
        raise ValueError("legacy state directory is invalid")
    target_root.mkdir(parents=True, exist_ok=True)
    imported: list[str] = []
    skipped: list[str] = []
    for name in MIGRATABLE_FILES:
        source_file = source / name
        target_file = target_root / name
        if not source_file.is_file() or target_file.exists():
            if source_file.is_file():
                skipped.append(name)
            continue
        temporary = target_file.with_suffix(target_file.suffix + ".migration")
        shutil.copy2(source_file, temporary)
        os.replace(temporary, target_file)
        imported.append(name)
    return {"schema_version": MIGRATION_SCHEMA, "imported": imported, "skipped": skipped}


def write_report(path: Path, report: dict) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
