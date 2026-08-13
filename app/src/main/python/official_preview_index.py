# -*- coding: utf-8 -*-
"""Build a local thumbnail index from the user's installed AA resources."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Literal

from PIL import Image, ImageOps

from official_catalog import (
    CatalogBundleLocation,
    catalog_bundle_locations,
)


IndexStatus = Literal[
    "not_built", "building", "ready", "partial", "stale"
]


@dataclass(frozen=True)
class PreviewIndexState:
    status: IndexStatus
    backgrounds: int
    avatars: int
    failed: int
    fingerprint: str
    current: int = 0
    total: int = 0


@dataclass(frozen=True)
class BundleImage:
    name: str
    image: Image.Image
    asset_type: str = "Texture2D"


def _normalized_key(value: str) -> str:
    return str(value).strip().casefold()


def _index_fingerprint(catalog_path: Path, cache_root: Path) -> str:
    digest = hashlib.sha256()
    catalog = catalog_path.resolve()
    cache = cache_root.resolve()
    stat = catalog.stat()
    digest.update(catalog.read_bytes())
    digest.update(str(cache).encode("utf-8", errors="surrogatepass"))
    digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
    return digest.hexdigest()


def _source_fingerprint(location: CatalogBundleLocation) -> str:
    digest = hashlib.sha256()
    digest.update(location.bundle_name.encode("utf-8"))
    digest.update(location.content_hash.encode("utf-8"))
    if location.data_path is None:
        digest.update(b"missing")
    else:
        path = location.data_path.resolve()
        stat = path.stat()
        digest.update(str(path).encode("utf-8", errors="surrogatepass"))
        digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
    return digest.hexdigest()


def _default_bundle_loader(data_path: Path) -> Iterable[BundleImage]:
    import UnityPy

    environment = UnityPy.load(str(data_path))
    for obj in environment.objects:
        if obj.type.name not in {"Texture2D", "Sprite"}:
            continue
        try:
            asset = obj.read()
            image = asset.image
        except Exception:
            continue
        name = str(getattr(asset, "m_Name", "") or "")
        if name and image is not None:
            yield BundleImage(name, image, obj.type.name)


class OfficialPreviewIndex:
    SCHEMA_VERSION = 1

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.manifest_path = self.root / "manifest.json"
        self._manifest_cache_stamp: tuple[int, int] | None = None
        self._manifest_cache: dict | None = None

    def _read_manifest(self) -> dict | None:
        try:
            stat = self.manifest_path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
            if self._manifest_cache_stamp == stamp:
                return self._manifest_cache
            manifest = json.loads(
                self.manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            self._manifest_cache_stamp = None
            self._manifest_cache = None
            return None
        if not isinstance(manifest, dict):
            return None
        if manifest.get("schema_version") != self.SCHEMA_VERSION:
            return None
        if not isinstance(manifest.get("records"), list):
            return None
        self._manifest_cache_stamp = stamp
        self._manifest_cache = manifest
        return manifest

    @staticmethod
    def _manifest_state(manifest: dict, status: IndexStatus) -> PreviewIndexState:
        records = manifest.get("records", [])
        return PreviewIndexState(
            status=status,
            backgrounds=sum(row.get("kind") == "background" for row in records),
            avatars=sum(row.get("kind") == "avatar" for row in records),
            failed=len(manifest.get("failures", [])),
            fingerprint=str(manifest.get("fingerprint", "")),
        )

    def state(
        self,
        catalog_path: str | Path,
        cache_root: str | Path,
    ) -> PreviewIndexState:
        manifest = self._read_manifest()
        if manifest is None:
            return PreviewIndexState("not_built", 0, 0, 0, "")
        try:
            fingerprint = _index_fingerprint(
                Path(catalog_path), Path(cache_root)
            )
        except OSError:
            return self._manifest_state(manifest, "stale")
        status: IndexStatus = (
            manifest.get("status", "partial")
            if manifest.get("fingerprint") == fingerprint
            else "stale"
        )
        if status not in {"building", "ready", "partial"}:
            status = "stale"
        return self._manifest_state(manifest, status)

    def _write_manifest(self, manifest: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / "manifest.json.tmp"
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.manifest_path)
        self._manifest_cache_stamp = None
        self._manifest_cache = None

    def _manifest_payload(
        self,
        status: IndexStatus,
        fingerprint: str,
        records: list[dict],
        failures: list[dict],
    ) -> dict:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "status": status,
            "fingerprint": fingerprint,
            "counts": {
                "backgrounds": sum(
                    row["kind"] == "background" for row in records
                ),
                "avatars": sum(
                    row["kind"] == "avatar" for row in records
                ),
                "failed": len(failures),
            },
            "records": records,
            "failures": failures,
        }

    def _output_path(self, kind: str, key: str, suffix: str) -> Path:
        token = hashlib.sha256(_normalized_key(key).encode("utf-8")).hexdigest()
        return self.root / ("backgrounds" if kind == "background" else "avatars") / f"{token}{suffix}"

    def _relative_output(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _record(
        self,
        kind: str,
        key: str,
        output: Path,
        source_fingerprint: str,
    ) -> dict:
        return {
            "kind": kind,
            "key": key,
            "normalized_key": _normalized_key(key),
            "path": self._relative_output(output),
            "source_fingerprint": source_fingerprint,
        }

    @staticmethod
    def _background_key(internal_id: str) -> str | None:
        lower = internal_id.casefold()
        marker = "/defaultlocalgroup_assets_uis/03_scenario/01_background/"
        if marker not in lower:
            return None
        filename = internal_id.rsplit("/", 1)[-1]
        for suffix in (".jpg.bundle", ".jpeg.bundle", ".png.bundle"):
            if filename.casefold().endswith(suffix):
                return filename[: -len(suffix)]
        return None

    @staticmethod
    def _fit_background(image: Image.Image) -> Image.Image:
        fitted = ImageOps.contain(
            ImageOps.exif_transpose(image).convert("RGB"),
            (320, 180),
            Image.Resampling.LANCZOS,
        )
        canvas = Image.new("RGB", (320, 180), "black")
        canvas.paste(
            fitted,
            ((320 - fitted.width) // 2, (180 - fitted.height) // 2),
        )
        return canvas

    @staticmethod
    def _fit_avatar(image: Image.Image) -> Image.Image:
        fitted = ImageOps.contain(
            ImageOps.exif_transpose(image).convert("RGBA"),
            (160, 160),
            Image.Resampling.LANCZOS,
        )
        canvas = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        canvas.alpha_composite(
            fitted,
            ((160 - fitted.width) // 2, (160 - fitted.height) // 2),
        )
        return canvas

    def _reusable_records(
        self,
        old_records: list[dict],
        source_fingerprint: str,
        kind: str,
    ) -> list[dict]:
        records = [
            row
            for row in old_records
            if row.get("kind") == kind
            and row.get("source_fingerprint") == source_fingerprint
        ]
        for row in records:
            try:
                path = (self.root / row["path"]).resolve()
                path.relative_to(self.root.resolve())
            except (KeyError, OSError, ValueError):
                return []
            if not path.is_file():
                return []
        return records

    def build(
        self,
        catalog_path: str | Path,
        cache_root: str | Path,
        *,
        progress: Callable[[PreviewIndexState], None] | None = None,
        bundle_loader: Callable[[Path], Iterable[BundleImage]] | None = None,
    ) -> PreviewIndexState:
        catalog = Path(catalog_path)
        cache = Path(cache_root)
        fingerprint = _index_fingerprint(catalog, cache)
        previous = self._read_manifest() or {}
        old_records = previous.get("records", [])
        records: list[dict] = []
        failures: list[dict] = []
        loader = bundle_loader or _default_bundle_loader

        backgrounds = catalog_bundle_locations(
            catalog,
            cache,
            internal_predicate=lambda value: (
                self._background_key(value) is not None
            ),
        )
        avatars = catalog_bundle_locations(
            catalog,
            cache,
            internal_predicate=lambda value: value.casefold().endswith(
                "/avatars_assets_all.bundle"
            ),
        )
        work = [("background", row) for row in backgrounds]
        work.extend(("avatar", row) for row in avatars)

        for index, (kind, location) in enumerate(work, 1):
            failure_count = len(failures)
            try:
                source = _source_fingerprint(location)
                reusable = self._reusable_records(
                    old_records, source, kind
                )
                if reusable:
                    records.extend(reusable)
                    continue
                if location.data_path is None:
                    raise FileNotFoundError("catalog bundle is not cached")
                images = list(loader(location.data_path))
                if kind == "background":
                    key = self._background_key(location.internal_id)
                    matches = [
                        row
                        for row in images
                        if _normalized_key(row.name) == _normalized_key(key or "")
                    ]
                    selected = matches[0] if matches else (
                        images[0] if len(images) == 1 else None
                    )
                    if selected is None or key is None:
                        raise LookupError("background image not found in bundle")
                    output = self._output_path(kind, key, ".webp")
                    output.parent.mkdir(parents=True, exist_ok=True)
                    self._fit_background(selected.image).save(
                        output, "WEBP", quality=78
                    )
                    records.append(self._record(kind, key, output, source))
                else:
                    selected = [
                        row
                        for row in images
                        if row.asset_type == "Texture2D"
                        and row.name.startswith(
                            ("Student_Portrait_", "NPC_Portrait_")
                        )
                    ]
                    if not selected:
                        raise LookupError("avatar images not found in bundle")
                    for row in selected:
                        output = self._output_path(kind, row.name, ".png")
                        output.parent.mkdir(parents=True, exist_ok=True)
                        self._fit_avatar(row.image).save(output, "PNG")
                        records.append(
                            self._record(kind, row.name, output, source)
                        )
            except Exception as exc:
                failures.append(
                    {
                        "bundle": location.bundle_name,
                        "kind": kind,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            if index == 1 or index % 25 == 0 or len(failures) > failure_count:
                self._write_manifest(
                    self._manifest_payload(
                        "building", fingerprint, records, failures
                    )
                )
            if progress is not None:
                progress(
                    PreviewIndexState(
                        "building",
                        sum(row["kind"] == "background" for row in records),
                        sum(row["kind"] == "avatar" for row in records),
                        len(failures),
                        fingerprint,
                        current=index,
                        total=len(work),
                    )
                )

        status: IndexStatus = "partial" if failures else "ready"
        manifest = self._manifest_payload(
            status, fingerprint, records, failures
        )
        self._write_manifest(manifest)
        result = self._manifest_state(manifest, status)
        return PreviewIndexState(
            **{
                **result.__dict__,
                "current": len(work),
                "total": len(work),
            }
        )

    def resolve(
        self,
        kind: Literal["background", "avatar"],
        key: str,
    ) -> Path | None:
        if kind not in {"background", "avatar"}:
            return None
        normalized = _normalized_key(key)
        if not normalized or "/" in normalized or "\\" in normalized:
            return None
        manifest = self._read_manifest()
        if manifest is None:
            return None
        row = next(
            (
                item
                for item in manifest["records"]
                if item.get("kind") == kind
                and item.get("normalized_key") == normalized
            ),
            None,
        )
        if row is None:
            return None
        try:
            root = self.root.resolve()
            path = (self.root / row["path"]).resolve()
            path.relative_to(root)
        except (KeyError, OSError, ValueError):
            return None
        return path if path.is_file() else None
