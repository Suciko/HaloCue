# -*- coding: utf-8 -*-
"""Materialize AA's installed official Spine bundles into a read-only cache.

The Addressables cache keeps the binary skeleton, atlas text and texture in
UnityFS bundles. This module resolves them through the installed catalog and
writes ordinary Spine files under HaloCue's own output directory. Source
bundles are never modified.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from official_catalog import CatalogBundleLocation, catalog_bundle_locations
from spine_face_web_renderer import detect_spine_version


_CHARACTER_MARKER = "/uis/03_scenario/02_character/"
_DATA_MARKER = _CHARACTER_MARKER + "data/"


@dataclass(frozen=True)
class OfficialSpineSource:
    outfit_key: str
    spine: str
    asset_stem: str
    skeleton: CatalogBundleLocation
    atlas: CatalogBundleLocation
    texture: CatalogBundleLocation

    @property
    def cached(self) -> bool:
        return all(
            item.data_path is not None
            for item in (self.skeleton, self.atlas, self.texture)
        )


def _asset_stem(internal_id: str, suffix: str) -> str:
    filename = str(internal_id).replace("\\", "/").rsplit("/", 1)[-1]
    if not filename.casefold().endswith(suffix.casefold()):
        return ""
    return filename[: -len(suffix)]


def _locations_by_stem(
    catalog_path: str | Path,
    cache_root: str | Path,
    suffix: str,
) -> dict[str, CatalogBundleLocation]:
    locations = catalog_bundle_locations(
        catalog_path,
        cache_root,
        internal_predicate=lambda value: (
            _DATA_MARKER in str(value).replace("\\", "/").casefold()
            and str(value).casefold().endswith(suffix.casefold())
        ),
    )
    result: dict[str, CatalogBundleLocation] = {}
    for location in locations:
        stem = _asset_stem(location.internal_id, suffix)
        if stem:
            result[stem.casefold()] = location
    return result


def discover_official_spine_sources(
    catalog_path: str | Path,
    cache_root: str | Path,
) -> tuple[tuple[OfficialSpineSource, ...], tuple[dict, ...]]:
    """Return every official skeleton set represented by the local catalog."""
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8-sig"))
    prefab_names = {}
    for value in catalog.get("m_InternalIds") or []:
        normalized = str(value).replace("\\", "/")
        lower = normalized.casefold()
        if (
            _CHARACTER_MARKER in lower
            and _DATA_MARKER not in lower
            and lower.endswith(".prefab")
        ):
            name = normalized.rsplit("/", 1)[-1][:-len(".prefab")]
            prefab_names[name.casefold()] = name

    skeletons = _locations_by_stem(catalog_path, cache_root, ".skel.bytes")
    atlases = _locations_by_stem(catalog_path, cache_root, ".atlas.txt")
    textures = _locations_by_stem(catalog_path, cache_root, ".png")
    sources: list[OfficialSpineSource] = []
    failures: list[dict] = []
    for normalized_stem in sorted(set(skeletons) | set(atlases) | set(textures)):
        skeleton = skeletons.get(normalized_stem)
        atlas = atlases.get(normalized_stem)
        texture = textures.get(normalized_stem)
        missing = [
            kind for kind, value in (
                ("skeleton", skeleton), ("atlas", atlas), ("texture", texture)
            ) if value is None
        ]
        stem_source = skeleton or atlas or texture
        stem = _asset_stem(
            stem_source.internal_id,
            ".skel.bytes" if skeleton else ".atlas.txt" if atlas else ".png",
        )
        expected_key = "CharacterSpine_" + (
            stem[:-4] if stem.casefold().endswith("_spr") else stem
        )
        outfit_key = prefab_names.get(expected_key.casefold())
        if missing or not outfit_key:
            failures.append({
                "asset_stem": stem,
                "expected_outfit_key": expected_key,
                "reason": "missing_catalog_component" if missing else "missing_prefab_identity",
                "missing": missing,
            })
            continue
        sources.append(OfficialSpineSource(
            outfit_key=outfit_key,
            spine=f"UIs/03_Scenario/02_Character/{outfit_key}",
            asset_stem=stem,
            skeleton=skeleton,
            atlas=atlas,
            texture=texture,
        ))
    return tuple(sources), tuple(failures)


def _text_asset_bytes(environment, expected_name: str) -> bytes:
    expected = expected_name.casefold()
    for obj in environment.objects:
        if obj.type.name != "TextAsset":
            continue
        asset = obj.read()
        if str(getattr(asset, "m_Name", "")).casefold() != expected:
            continue
        value = getattr(asset, "m_Script", b"")
        if isinstance(value, bytes):
            return value
        return str(value).encode("utf-8", errors="surrogateescape")
    raise LookupError(f"TextAsset not found: {expected_name}")


def _texture_image(environment, expected_name: str):
    expected = expected_name.casefold()
    fallback = []
    for obj in environment.objects:
        if obj.type.name != "Texture2D":
            continue
        asset = obj.read()
        image = getattr(asset, "image", None)
        if image is None:
            continue
        fallback.append(image)
        if str(getattr(asset, "m_Name", "")).casefold() == expected:
            return image
    if len(fallback) == 1:
        return fallback[0]
    raise LookupError(f"Texture2D not found: {expected_name}")


def _atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_bytes(value)
    os.replace(pending, path)


def _atomic_json(path: Path, value: dict) -> None:
    _atomic_bytes(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def _location_evidence(location: CatalogBundleLocation) -> dict:
    return {
        "internal_id": location.internal_id,
        "bundle_name": location.bundle_name,
        "content_hash": location.content_hash,
        "data_path": str(location.data_path) if location.data_path else "",
    }


def _source_fingerprint(source: OfficialSpineSource) -> str:
    digest = hashlib.sha256()
    for location in (source.skeleton, source.atlas, source.texture):
        digest.update(location.internal_id.encode("utf-8"))
        digest.update(location.bundle_name.encode("utf-8"))
        digest.update(location.content_hash.encode("utf-8"))
    return digest.hexdigest()


def materialize_official_spine_source(
    source: OfficialSpineSource,
    output_root: str | Path,
    *,
    unity_loader: Callable[[str], object] | None = None,
    force: bool = False,
) -> dict:
    """Export one official bundle set into HaloCue's local render cache."""
    if not source.cached:
        raise FileNotFoundError(f"official Spine bundle is not cached: {source.outfit_key}")
    bundle_dir = Path(output_root).resolve() / Path(source.spine) / source.outfit_key
    manifest_path = bundle_dir / "source.json"
    fingerprint = _source_fingerprint(source)
    if not force and manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        required = [
            bundle_dir / f"{source.asset_stem}.skel",
            bundle_dir / f"{source.asset_stem}.atlas",
            bundle_dir / f"{source.asset_stem}.png",
        ]
        if manifest.get("source_fingerprint") == fingerprint and all(
            path.is_file() for path in required
        ):
            return manifest

    if unity_loader is None:
        import UnityPy
        unity_loader = UnityPy.load
    loaded = {}

    def environment(location: CatalogBundleLocation):
        key = str(location.data_path.resolve())
        if key not in loaded:
            loaded[key] = unity_loader(key)
        return loaded[key]

    skeleton_bytes = _text_asset_bytes(
        environment(source.skeleton), f"{source.asset_stem}.skel"
    )
    atlas_bytes = _text_asset_bytes(
        environment(source.atlas), f"{source.asset_stem}.atlas"
    )
    texture = _texture_image(environment(source.texture), source.asset_stem)
    skeleton_path = bundle_dir / f"{source.asset_stem}.skel"
    atlas_path = bundle_dir / f"{source.asset_stem}.atlas"
    texture_path = bundle_dir / f"{source.asset_stem}.png"
    _atomic_bytes(skeleton_path, skeleton_bytes)
    _atomic_bytes(atlas_path, atlas_bytes)
    texture_path.parent.mkdir(parents=True, exist_ok=True)
    pending_texture = texture_path.with_suffix(".png.pending")
    texture.save(pending_texture, "PNG")
    os.replace(pending_texture, texture_path)
    signature = hashlib.sha256(skeleton_bytes).hexdigest()
    manifest = {
        "schema_version": 1,
        "status": "ready",
        "source_kind": "official_base",
        "outfit_key": source.outfit_key,
        "spine": source.spine,
        "asset_stem": source.asset_stem,
        "spine_signature": signature,
        "spine_version": detect_spine_version(skeleton_path),
        "source_fingerprint": fingerprint,
        "sources": {
            "skeleton": _location_evidence(source.skeleton),
            "atlas": _location_evidence(source.atlas),
            "texture": _location_evidence(source.texture),
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_json(manifest_path, manifest)
    return manifest


def materialize_official_spines(
    catalog_path: str | Path,
    cache_root: str | Path,
    output_root: str | Path,
    *,
    force: bool = False,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    sources, discovery_failures = discover_official_spine_sources(
        catalog_path, cache_root
    )
    records: list[dict] = []
    failures = list(discovery_failures)
    for index, source in enumerate(sources, 1):
        try:
            records.append(materialize_official_spine_source(
                source, output_root, force=force
            ))
        except Exception as exc:
            failures.append({
                "outfit_key": source.outfit_key,
                "asset_stem": source.asset_stem,
                "reason": "materialize_failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "source": {
                    "spine": source.spine,
                    "skeleton": _location_evidence(source.skeleton),
                    "atlas": _location_evidence(source.atlas),
                    "texture": _location_evidence(source.texture),
                },
            })
        if progress:
            progress(index, len(sources), source.outfit_key)
    return {
        "catalog_path": str(Path(catalog_path).resolve()),
        "cache_root": str(Path(cache_root).resolve()),
        "output_root": str(Path(output_root).resolve()),
        "source_count": len(sources),
        "ready_count": len(records),
        "failed_count": len(failures),
        "records": records,
        "failures": failures,
    }
