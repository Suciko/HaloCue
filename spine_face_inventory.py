# -*- coding: utf-8 -*-
"""Inventory real face animations across official base and extra Spine packs."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from spine_face_web_renderer import (
    SpineWebRenderer,
    _bundle_files,
    detect_spine_version,
    web_bundle_signature,
)
from asset_validation import _atlas_page_path, _atlas_pages, _read_atlas_lines


_FACE_ID_RE = re.compile(r"^\d{2}$")


@dataclass(frozen=True)
class SpineInventoryCandidate:
    source_kind: str
    source_root: str
    source_dir: str
    outfit_key: str
    spine: str
    spine_signature: str
    spine_version: str
    evidence: dict


def _read_source_manifest(directory: Path) -> dict:
    path = directory / "source.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def discover_spine_inventory_candidates(
    roots: Iterable[tuple[str, str | Path]],
    *,
    isolation_root: str | Path | None = None,
) -> tuple[tuple[SpineInventoryCandidate, ...], tuple[dict, ...]]:
    records: list[SpineInventoryCandidate] = []
    failures: list[dict] = []
    seen: set[str] = set()
    isolated_root = Path(isolation_root).resolve() if isolation_root else None
    for source_kind, root_value in roots:
        root = Path(root_value).resolve()
        if not root.is_dir():
            failures.append({
                "source_kind": str(source_kind),
                "source_root": str(root),
                "reason": "missing_source_root",
            })
            continue
        for skeleton_path in sorted(root.rglob("*.skel")):
            directory = skeleton_path.parent.resolve()
            key = str(skeleton_path.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            try:
                skeletons = sorted(directory.glob("*.skel"))
                atlases = sorted(directory.glob("*.atlas"))
                bundle_dir = directory
                if len(skeletons) != 1 or len(atlases) != 1:
                    atlas = skeleton_path.with_suffix(".atlas")
                    if isolated_root is None or not atlas.is_file():
                        raise ValueError(
                            "A renderable Spine bundle must contain exactly one .skel and one .atlas"
                        )
                    token = hashlib.sha256(
                        (str(skeleton_path.resolve()) + str(skeleton_path.stat().st_mtime_ns))
                        .encode("utf-8", errors="surrogatepass")
                    ).hexdigest()
                    bundle_dir = isolated_root / token
                    bundle_dir.mkdir(parents=True, exist_ok=True)
                    source_files = [skeleton_path, atlas]
                    for page in _atlas_pages(_read_atlas_lines(atlas)):
                        texture = _atlas_page_path(directory, page)
                        if texture is None or not texture.is_file():
                            raise FileNotFoundError(f"Spine atlas texture not found: {page}")
                        source_files.append(texture)
                    for source_file in source_files:
                        destination = bundle_dir / source_file.name
                        if (
                            not destination.is_file()
                            or destination.stat().st_size != source_file.stat().st_size
                        ):
                            shutil.copy2(source_file, destination)
                skeleton, _, _ = _bundle_files(bundle_dir)
                version = detect_spine_version(skeleton)
                if not version.startswith(("3.8", "4.2")):
                    raise ValueError(f"unsupported Spine version {version or 'unknown'}")
                manifest = _read_source_manifest(directory)
                relative = skeleton_path.relative_to(root).with_suffix("").as_posix()
                outfit_key = str(
                    manifest.get("outfit_key") or skeleton.stem
                ).strip()
                records.append(SpineInventoryCandidate(
                    source_kind=str(manifest.get("source_kind") or source_kind),
                    source_root=str(root),
                    source_dir=str(bundle_dir),
                    outfit_key=outfit_key,
                    spine=str(manifest.get("spine") or relative),
                    spine_signature=str(
                        manifest.get("spine_signature")
                        or hashlib.sha256(skeleton.read_bytes()).hexdigest()
                    ).strip(),
                    spine_version=version,
                    evidence={
                        "source_manifest": manifest,
                        "skeleton_path": str(skeleton_path.resolve()),
                        "isolated_source_dir": (
                            str(bundle_dir) if bundle_dir != directory else ""
                        ),
                    },
                ))
            except Exception as exc:
                failures.append({
                    "source_kind": str(source_kind),
                    "source_root": str(root),
                    "source_dir": str(directory),
                    "reason": "invalid_spine_bundle",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                })
    return tuple(records), tuple(failures)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(pending, path)


def build_spine_animation_inventory(
    candidates: Iterable[SpineInventoryCandidate],
    output_path: str | Path,
    *,
    force: bool = False,
    restart_every: int = 25,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    rows = list(candidates)
    output = Path(output_path).resolve()
    previous = {}
    if not force and output.is_file():
        try:
            old = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = {}
        previous = {
            str(item.get("bundle_signature") or ""): item
            for item in old.get("records") or []
            if isinstance(item, dict) and item.get("status") == "ready"
        }

    records: list[dict] = []
    failures: list[dict] = []
    renderer = None
    renderer_family = ""
    session_count = 0
    try:
        for index, candidate in enumerate(rows, 1):
            try:
                signature = web_bundle_signature(candidate.source_dir)
                cached = previous.get(signature)
                if cached is not None:
                    record = {
                        **cached,
                        **asdict(candidate),
                        "bundle_signature": signature,
                        "inventory_cached": True,
                    }
                else:
                    family = candidate.spine_version[:3]
                    if (
                        renderer is None
                        or renderer_family != family
                        or session_count >= max(1, int(restart_every))
                    ):
                        if renderer is not None:
                            renderer.__exit__(None, None, None)
                        renderer = SpineWebRenderer(
                            spine_version=candidate.spine_version,
                            canvas_size=1024,
                        )
                        renderer.__enter__()
                        renderer_family = family
                        session_count = 0
                    animations = renderer.animation_names(candidate.source_dir)
                    session_count += 1
                    face_ids = sorted({
                        name for name in animations if _FACE_ID_RE.fullmatch(name)
                    })
                    record = {
                        **asdict(candidate),
                        "bundle_signature": signature,
                        "status": "ready",
                        "animation_names": list(animations),
                        "face_ids": face_ids,
                        "face_count": len(face_ids),
                        "inventory_cached": False,
                    }
                records.append(record)
            except Exception as exc:
                failures.append({
                    **asdict(candidate),
                    "status": "failed",
                    "reason": "animation_inventory_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                })
            if progress:
                progress(index, len(rows), candidate.outfit_key)
            if index == 1 or index % 10 == 0 or failures:
                _atomic_json(output, {
                    "schema_version": 1,
                    "status": "building",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "candidate_count": len(rows),
                    "records": records,
                    "failures": failures,
                })
    finally:
        if renderer is not None:
            renderer.__exit__(None, None, None)
    payload = {
        "schema_version": 1,
        "status": "partial" if failures else "ready",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(rows),
        "ready_count": len(records),
        "failed_count": len(failures),
        "records": records,
        "failures": failures,
    }
    _atomic_json(output, payload)
    return payload
