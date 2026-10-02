"""Connect imported background identities, local media and previews in one generation."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from PIL import Image, ImageOps
from tables import bg_id

from .resource_previews import IMAGE_TYPES
from .background_library import BackgroundLibraryScope


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def aa_registered_resources(aa_data: Path, previous_path: Path | None) -> dict:
    """Read explicit AA exports and prior imports bound to this workspace only."""
    previous = _read(previous_path) if previous_path else {}
    result = (
        previous
        if previous.get("_source") and Path(previous["_source"]).resolve() == aa_data.resolve()
        else {}
    )
    export = aa_data / "aa_resources.json"
    if export.is_file() and export.resolve().is_relative_to(aa_data.resolve()):
        exported = _read(export)
        if exported.get("_source") and Path(exported["_source"]).resolve() != aa_data.resolve():
            raise ValueError("AA 资源索引属于其他工作区，请先修正来源路径")
        result = {**result, **exported, "_source": str(aa_data.resolve())}
    return result


def prepare_background_import(
    index: dict, *, aa_data: Path, output: Path, previous_path: Path | None, legacy_root: Path
) -> dict:
    """Write only into the unpublished generation. Never modify AA or the old index."""
    previous = aa_registered_resources(aa_data, previous_path)
    same_workspace = (
        bool(previous.get("_source")) and Path(previous["_source"]).resolve() == aa_data.resolve()
    )
    previous_media = previous.get("background_media") or {} if same_workspace else {}
    backgrounds = {**(previous.get("bg") or {} if same_workspace else {}), **index["bg"]}
    conflicts = set(index.get("bg_conflict") or [])
    for key in conflicts:
        backgrounds.pop(key, None)
    database_ids = {}
    labels = dict(previous.get("bg_label") or {}) if same_workspace else {}
    scenes = (
        dict((previous.get("scene_labels") or {}).get("background") or {}) if same_workspace else {}
    )
    # Read existing annotations, not model-generated replacements. No DB migration.
    database = legacy_root / "aa_assets.db"
    warnings = []
    if database.is_file():
        try:
            with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as con:
                con.row_factory = sqlite3.Row
                tables = {
                    r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if "bg" in tables:
                    for row in con.execute("SELECT * FROM bg"):
                        value = dict(row)
                        if isinstance(value.get("hash"), int):
                            database_ids[value["name"]] = value["hash"]
                        labels.setdefault(
                            value["name"],
                            {k: value.get(k) for k in ("label", "place", "time", "mood", "tags")},
                        )
                if "scene_visual_label" in tables:
                    for row in con.execute(
                        "SELECT asset_key,label_json,manual_json FROM scene_visual_label WHERE resource_channel='background' AND status='ready' ORDER BY updated_at DESC"
                    ):
                        scenes.setdefault(
                            row["asset_key"],
                            {
                                **json.loads(row["label_json"] or "{}"),
                                **json.loads(row["manual_json"] or "{}"),
                            },
                        )
        except (sqlite3.Error, ValueError, TypeError) as exc:
            warnings.append(f"部分旧背景标注未读取：{type(exc).__name__}")
    source_root = (aa_data / "overrides" / "bgs").resolve()
    local = {}
    if source_root.is_dir():
        for file in sorted(source_root.rglob("*")):
            if (
                file.suffix.casefold() not in IMAGE_TYPES
                or not file.is_file()
                or not file.resolve().is_relative_to(source_root)
            ):
                continue
            local.setdefault(file.stem, []).append(file)
            if file.stem not in conflicts:
                # Only installed overrides use filename hashing. Never invent an official ID.
                backgrounds.setdefault(
                    file.stem, database_ids.get(file.stem, int(bg_id(file.stem)))
                )
    preview_root = output.parent / "out" / "official-previews"
    preview_root.mkdir(parents=True, exist_ok=True)
    records, media = [], {}
    workspace_cache = aa_data / "halocue-official-previews"
    cache_roots = [workspace_cache]
    if same_workspace and previous_path:
        cache_roots.append(previous_path.parent / "out" / "official-previews")
    cached = {}
    for root in cache_roots:
        manifest = _read(root / "manifest.json")
        for row in manifest.get("records", []):
            if row.get("kind") not in {"background", "avatar"}:
                continue
            rel = str(row.get("path") or "")
            file = (root / rel).resolve()
            if (
                Path(rel).is_absolute()
                or not file.is_relative_to(root.resolve())
                or not file.is_file()
                or file.suffix.casefold() not in IMAGE_TYPES
            ):
                continue
            cached.setdefault((row["kind"], str(row.get("key") or "").casefold()), (file, row))

    # Database IDs are authoritative, but only bring in entries whose image is
    # located in this selected workspace. Do not import another workspace's list.
    for key, identity in database_ids.items():
        if key not in conflicts and (key in local or ("background", key.casefold()) in cached):
            backgrounds.setdefault(key, identity)

    visible = BackgroundLibraryScope(aa_data, previous_path).visible_keys(
        {"bg": backgrounds, "bg_label": labels, "scene_labels": {"background": scenes}}
    )
    backgrounds = {key: value for key, value in backgrounds.items() if key in visible}

    def store_preview(kind, key, source, digest, *, thumbnail=False):
        relative = (
            f"{kind}s/{digest}.webp" if thumbnail else f"{kind}s/{digest}{source.suffix.lower()}"
        )
        target = preview_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            if thumbnail:
                with Image.open(source) as image:
                    image = ImageOps.exif_transpose(image).convert("RGB")
                    image.thumbnail((640, 450))
                    image.save(target, "WEBP", quality=85)
            else:
                with Image.open(source) as image:
                    image.verify()
                shutil.copyfile(source, target)
        records.append({"kind": kind, "key": key, "path": relative, "source_fingerprint": digest})

    for key in backgrounds:
        entry = {"source_kind": "unresolved", "status": "missing"}
        files = local.get(key, [])
        try:
            if len(files) > 1:
                entry = {"source_kind": "override", "status": "ambiguous"}
            elif files:
                source = files[0]
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                entry = {
                    "source_kind": "override",
                    "status": "unreadable",
                    "source_relative": source.relative_to(aa_data).as_posix(),
                    "sha256": digest,
                }
                old = previous_media.get(key) or {}
                old_preview = cached.get(("background", key.casefold()))
                if old.get("sha256") == digest and old.get("status") == "ready" and old_preview:
                    store_preview("background", key, old_preview[0], digest)
                else:
                    store_preview("background", key, source, digest, thumbnail=True)
                entry["status"] = "ready"
            elif (previous_media.get(key) or {}).get("source_kind") == "override":
                # Do not resurrect a removed/moved local file from an old thumbnail.
                entry["source_kind"] = "override"
            elif ("background", key.casefold()) in cached:
                source, _ = cached[("background", key.casefold())]
                entry["source_kind"] = "aa_preview_cache"
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                store_preview("background", key, source, digest)
                entry.update(status="ready", sha256=digest)
        except (OSError, ValueError, Image.DecompressionBombError):
            entry["status"] = "unreadable"
        media[key] = entry
    for (kind, _), (source, row) in cached.items():
        if kind != "avatar":
            continue
        try:
            store_preview(
                "avatar", row["key"], source, hashlib.sha256(source.read_bytes()).hexdigest()
            )
        except (OSError, ValueError):
            warnings.append("有角色头像缓存无法读取；未影响背景导入。")
    index.update(
        bg=backgrounds,
        bg_label={k: v for k, v in labels.items() if k in backgrounds},
        scene_labels={"background": {k: v for k, v in scenes.items() if k in backgrounds}},
        background_media=media,
    )
    counts = {
        status: sum(row["status"] == status for row in media.values())
        for status in ("ready", "missing", "unreadable", "ambiguous")
    }
    counts["total"] = len(media)
    (preview_root / "manifest.json").write_text(
        json.dumps({"records": records, "background_media": counts}, ensure_ascii=False),
        encoding="utf-8",
    )
    if counts["total"] != counts["ready"]:
        warnings.append(
            f"背景预览：{counts['ready']} 项就绪，{counts['missing']} 项来源待定位，{counts['unreadable']} 项图片不可读，{counts['ambiguous']} 项同名冲突。"
        )
    return {"counts": counts, "warnings": warnings}
