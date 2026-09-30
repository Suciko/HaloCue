from __future__ import annotations

import json
import mimetypes
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class ResourcePreview:
    path: Path
    media_type: str


class ResourcePreviewCatalog:
    """Resolve allowlisted local previews without exposing their paths to clients."""

    def __init__(
        self, legacy_root: Path, aa_data: Path | None, resource_index: Path | None = None
    ) -> None:
        self.preview_root = legacy_root / "out" / "official-previews"
        self.resource_preview_root = (
            resource_index.parent / "out" / "official-previews" if resource_index else None
        )
        self.aa_data = aa_data
        self.override_background_root = (
            (aa_data / "overrides" / "bgs").resolve() if aa_data else None
        )
        self.workspace_preview_root = aa_data / "halocue-official-previews" if aa_data else None
        self.resource_index = resource_index
        self._media_stamp = None
        self._media_status = {}
        self._manifest_stamps: dict[Path, tuple[str, int, int]] = {}
        self._records_by_root: dict[Path, dict[tuple[str, str], Path]] = {}
        self._background_cache: dict[str, tuple[tuple, ResourcePreview]] = {}
        self._preview_lock = threading.RLock()

    def _background_signature(self) -> tuple:
        paths = [self.resource_index, self.preview_root / "manifest.json"]
        if self.resource_preview_root:
            paths.append(self.resource_preview_root / "manifest.json")
        if self.workspace_preview_root:
            paths.append(self.workspace_preview_root / "manifest.json")
        if self.aa_data:
            paths.extend(
                [self.aa_data / "overrides" / "manifest.json", self.aa_data / "overrides" / "bgs"]
            )
        signature = []
        for path in paths:
            try:
                stat = path.stat() if path else None
                signature.append((str(path), stat.st_mtime_ns, stat.st_size) if stat else None)
            except OSError:
                signature.append((str(path), None))
        return tuple(signature)

    @staticmethod
    def _normalized(value: str) -> str:
        return value.strip().casefold()

    def _official(self, kind: str, key: str) -> Path | None:
        # The index-generation manifest wins. Missing entries may still have a
        # preview in the explicitly bound AA workspace cache; never cross over
        # to a different compatibility checkout when either configured source
        # owns a manifest.
        roots: list[Path]
        if self.resource_preview_root and (self.resource_preview_root / "manifest.json").is_file():
            roots = [self.resource_preview_root]
            if (
                self.workspace_preview_root
                and (self.workspace_preview_root / "manifest.json").is_file()
            ):
                roots.append(self.workspace_preview_root)
        elif (
            self.workspace_preview_root
            and (self.workspace_preview_root / "manifest.json").is_file()
        ):
            roots = [self.workspace_preview_root]
        else:
            roots = [self.preview_root]

        for root in roots:
            preview = self._official_from_root(root, kind, key)
            if preview is not None:
                return preview
        return None

    def _official_from_root(self, root: Path, kind: str, key: str) -> Path | None:
        # A gallery starts many simultaneous thumbnail requests. Only one may
        # parse and validate each manifest generation.
        with self._preview_lock:
            return self._read_official_from_root(root, kind, key)

    def _read_official_from_root(self, root: Path, kind: str, key: str) -> Path | None:
        manifest_path = root / "manifest.json"
        try:
            stat = manifest_path.stat()
            stamp = (str(manifest_path), stat.st_mtime_ns, stat.st_size)
        except OSError:
            return None
        if stamp != self._manifest_stamps.get(root):
            records: dict[tuple[str, str], Path] = {}
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                resolved_root = root.resolve()
                for row in payload.get("records", []):
                    if not isinstance(row, dict):
                        continue
                    row_kind = str(row.get("kind") or "")
                    row_key = self._normalized(str(row.get("key") or ""))
                    relative = str(row.get("path") or "")
                    if row_kind not in {"background", "avatar"} or not row_key:
                        continue
                    if Path(relative).is_absolute():
                        continue
                    candidate = (root / relative).resolve()
                    if candidate.is_relative_to(resolved_root) and candidate.is_file():
                        records[(row_kind, row_key)] = candidate
            except (OSError, ValueError, TypeError):
                records = {}
            self._manifest_stamps[root] = stamp
            self._records_by_root[root] = records
        return self._records_by_root.get(root, {}).get((kind, self._normalized(key)))

    def background(self, key: str) -> ResourcePreview | None:
        return self._background_with_signature(key, self._background_signature())

    def backgrounds_available(self, keys: Iterable[str]) -> dict[str, bool]:
        """One filesystem generation check for an entire search result set."""
        signature = self._background_signature()
        return {key: self._background_with_signature(key, signature) is not None for key in keys}

    def _background_with_signature(self, key: str, signature: tuple) -> ResourcePreview | None:
        # AA's installed override is the rendered asset; a cache alone is not
        # the complete background catalogue. Restrict lookup to this workspace.
        if not key or key in {".", ".."} or any(char in key for char in "/\\:\x00"):
            return None
        cached = self._background_cache.get(key)
        if cached and cached[0] == signature and cached[1].path.is_file():
            return cached[1]
        if self.resource_index:
            stamp = signature[0]
            with self._preview_lock:
                if stamp != self._media_stamp:
                    data = (
                        json.loads(self.resource_index.read_text(encoding="utf-8"))
                        if stamp and len(stamp) == 3
                        else {}
                    )
                    self._media_status = {
                        self._normalized(str(media_key)): value
                        for media_key, value in (data.get("background_media") or {}).items()
                        if isinstance(value, dict)
                    }
                    self._media_stamp = stamp
        media = self._media_status.get(self._normalized(key)) or {}
        media_status = str(media.get("status") or "")
        if self.aa_data:
            root = self.override_background_root
            if media_status not in {"unreadable", "ambiguous"}:
                for suffix in (".png", ".jpg", ".jpeg", ".webp"):
                    candidate = root / f"{key}{suffix}"
                    if not candidate.is_file():
                        continue
                    candidate = candidate.resolve()
                    if candidate.is_relative_to(root):
                        preview = self._as_preview(candidate)
                        if preview is not None:
                            self._background_cache[key] = (signature, preview)
                        return preview
        official = self._as_preview(self._official("background", key))
        if official is not None:
            self._background_cache[key] = (signature, official)
            return official
        return None

    def avatar(self, *, avatar_key: str, spine: str) -> ResourcePreview | None:
        local = self._workspace_avatar(spine)
        if local is not None:
            return local
        direct = Path(avatar_key.replace("\\", "/")).name
        path = self._official("avatar", direct) if direct else None
        if path is None:
            stem = Path(spine.replace("\\", "/")).name
            prefix = "characterspine_"
            if stem.casefold().startswith(prefix):
                path = self._official("avatar", f"Student_Portrait_{stem[len(prefix) :]}")
        return self._as_preview(path)

    def _workspace_avatar(self, spine: str) -> ResourcePreview | None:
        """Resolve the installed AA avatar override for an indexed character."""
        if not self.aa_data:
            return None
        relative = str(spine or "").strip().replace("\\", "/")
        parts = relative.split("/")
        if (
            not relative
            or relative.startswith("/")
            or any(
                not part or part in {".", ".."} or ":" in part or "\x00" in part for part in parts
            )
        ):
            return None
        root = (self.aa_data / "overrides").resolve()
        for suffix in (".png", ".webp", ".jpg", ".jpeg"):
            candidate = root.joinpath(*parts[:-1], f"{parts[-1]}-avatar{suffix}").resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                preview = self._as_preview(candidate)
                if preview is not None:
                    return preview
        return None

    def cg(self, key: str) -> ResourcePreview | None:
        if not self.aa_data:
            return None
        root = self.aa_data / "overrides" / "popups"
        if not root.is_dir() or not key or any(part in {"", ".", ".."} for part in Path(key).parts):
            return None
        for suffix in IMAGE_TYPES:
            candidate = root / f"{key}{suffix}"
            if candidate.is_file():
                return self._as_preview(candidate)
        return None

    @staticmethod
    def _as_preview(path: Path | None) -> ResourcePreview | None:
        if path is None or not path.is_file() or path.suffix.casefold() not in IMAGE_TYPES:
            return None
        media_type = mimetypes.guess_type(path.name)[0]
        return ResourcePreview(path=path, media_type=media_type or "application/octet-stream")
