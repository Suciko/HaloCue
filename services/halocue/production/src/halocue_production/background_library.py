from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath
from typing import Any

from .resource_previews import IMAGE_TYPES


OFFICIAL_SOURCES = {"official_base", "extra_pack", "official_resource_pack"}
PRIVATE_SOURCES = {"project_import", "task_import", "private", "custom", "history"}


class BackgroundLibraryScope:
    """Separate shared AA resources from images owned by individual stories."""

    def __init__(self, aa_data: Path | None, resource_index: Path | None) -> None:
        self.aa_data = aa_data
        self.resource_index = resource_index
        self._files: dict[Path, tuple[tuple[int, int], dict[str, Any]]] = {}
        self._scope_payload = None
        self._scope_signature = None
        self._scope_keys: set[str] = set()

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
            cached = self._files.get(path)
            if cached and cached[0] == stamp:
                return cached[1]
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            value = value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}
        self._files[path] = (stamp, value)
        return value

    def visible_keys(self, resources: dict[str, Any]) -> set[str]:
        backgrounds = resources.get("bg") or {}
        labels = resources.get("bg_label") or {}
        scene_labels = (resources.get("scene_labels") or {}).get("background") or {}
        paths = []
        if self.aa_data:
            paths.extend(
                [
                    self.aa_data / "overrides" / "manifest.json",
                    self.aa_data / "halocue-official-previews" / "manifest.json",
                ]
            )
        if self.resource_index:
            paths.append(self.resource_index.parent / "out" / "official-previews" / "manifest.json")
        signature = []
        for path in paths:
            try:
                stat = path.stat()
                signature.append((str(path), stat.st_mtime_ns, stat.st_size))
            except OSError:
                signature.append((str(path), None))
        classification = tuple(
            (
                key,
                (labels.get(key) or {}).get("source_kind")
                if isinstance(labels.get(key), dict)
                else None,
                (scene_labels.get(key) or {}).get("source_kind")
                if isinstance(scene_labels.get(key), dict)
                else None,
            )
            for key in backgrounds
        )
        signature = (tuple(signature), classification)
        if self._scope_payload is resources and self._scope_signature == signature:
            return set(self._scope_keys)
        allowed, private = set(), set()
        classified = False
        for key in backgrounds:
            metadata = {
                **(labels.get(key) if isinstance(labels.get(key), dict) else {}),
                **(scene_labels.get(key) if isinstance(scene_labels.get(key), dict) else {}),
            }
            source = str(metadata.get("source_kind") or "").casefold()
            classified = classified or bool(source)
            if source in OFFICIAL_SOURCES:
                allowed.add(str(key).casefold())
            elif source in PRIVATE_SOURCES:
                private.add(str(key).casefold())

        # Older standalone exports lack provenance. A bound AA workspace has
        # authoritative shared registries, so never treat its history as a pack.
        if self.aa_data is None and not classified:
            return set(backgrounds)

        roots = []
        if self.aa_data:
            roots.append(self.aa_data / "halocue-official-previews")
            shared_root = (self.aa_data / "overrides").resolve()
            manifest = self._read(shared_root / "manifest.json")
            for relative in manifest.get("BgOverrides", []):
                if not isinstance(relative, str):
                    continue
                path = PureWindowsPath(relative)
                if path.is_absolute() or any(part in {".", ".."} for part in path.parts):
                    continue
                candidate = shared_root.joinpath(*path.parts).resolve()
                if (
                    candidate.is_relative_to(shared_root)
                    and candidate.suffix.casefold() in IMAGE_TYPES
                ):
                    allowed.add(path.stem.casefold())
        if self.resource_index:
            roots.append(self.resource_index.parent / "out" / "official-previews")
        for root in roots:
            manifest = self._read(root / "manifest.json")
            # OfficialPreviewIndex records originate in Addressables bundles.
            # A generic thumbnail cache can also contain private task images.
            if manifest.get("schema_version") != 1:
                continue
            for row in manifest.get("records", []):
                if isinstance(row, dict) and row.get("kind") == "background":
                    allowed.add(str(row.get("key") or "").casefold())
        visible = {key for key in backgrounds if str(key).casefold() in allowed - private}
        self._scope_payload, self._scope_signature, self._scope_keys = resources, signature, visible
        return set(visible)
