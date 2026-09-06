from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any


IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class ResourcePreview:
    path: Path
    media_type: str


class ResourcePreviewCatalog:
    """Resolve allowlisted local previews without exposing their paths to clients."""

    def __init__(self, legacy_root: Path, aa_data: Path | None) -> None:
        self.preview_root = legacy_root / "out" / "official-previews"
        self.aa_data = aa_data
        self._manifest_stamp: tuple[int, int] | None = None
        self._records: dict[tuple[str, str], Path] = {}

    @staticmethod
    def _normalized(value: str) -> str:
        return value.strip().casefold()

    def _official(self, kind: str, key: str) -> Path | None:
        manifest_path = self.preview_root / "manifest.json"
        try:
            stat = manifest_path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return None
        if stamp != self._manifest_stamp:
            records: dict[tuple[str, str], Path] = {}
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                for row in payload.get("records", []):
                    if not isinstance(row, dict):
                        continue
                    row_kind = str(row.get("kind") or "")
                    row_key = self._normalized(str(row.get("key") or ""))
                    relative = str(row.get("path") or "")
                    if row_kind not in {"background", "avatar"} or not row_key:
                        continue
                    candidate = (self.preview_root / relative).resolve()
                    if candidate.is_relative_to(self.preview_root.resolve()) and candidate.is_file():
                        records[(row_kind, row_key)] = candidate
            except (OSError, ValueError, TypeError):
                records = {}
            self._manifest_stamp = stamp
            self._records = records
        return self._records.get((kind, self._normalized(key)))

    def background(self, key: str) -> ResourcePreview | None:
        return self._as_preview(self._official("background", key))

    def avatar(self, *, avatar_key: str, spine: str) -> ResourcePreview | None:
        direct = Path(avatar_key.replace("\\", "/")).name
        path = self._official("avatar", direct) if direct else None
        if path is None:
            stem = Path(spine.replace("\\", "/")).name
            prefix = "characterspine_"
            if stem.casefold().startswith(prefix):
                path = self._official("avatar", f"Student_Portrait_{stem[len(prefix):]}")
        return self._as_preview(path)

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
        if path is None or path.suffix.casefold() not in IMAGE_TYPES:
            return None
        media_type = mimetypes.guess_type(path.name)[0]
        return ResourcePreview(path=path, media_type=media_type or "application/octet-stream")
