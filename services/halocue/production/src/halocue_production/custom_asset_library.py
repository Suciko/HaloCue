from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from .errors import ProductionError
from .models import new_id, utc_now


class CustomAssetLibrary:
    """Durable, reusable user assets kept outside any ProductionRun."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _public(record: dict[str, Any]) -> dict[str, Any]:
        public = {
            key: value
            for key, value in record.items()
            if key not in {"private_source", "source_relative"}
        }
        public.setdefault("metadata_version", 1)
        return public

    @staticmethod
    def _write_record(path: Path, record: dict[str, Any]) -> None:
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, path)

    def _record_path(self, asset_id: str) -> Path:
        if not asset_id.startswith("library-asset-") or len(asset_id) != 26:
            raise ProductionError("custom_asset_not_found", "自定义素材不存在", status=404)
        directory = (self.root / asset_id).resolve()
        try:
            directory.relative_to(self.root.resolve())
        except ValueError as exc:
            raise ProductionError("custom_asset_not_found", "自定义素材不存在", status=404) from exc
        return directory / "asset.json"

    def _load(self, asset_id: str) -> dict[str, Any]:
        path = self._record_path(asset_id)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProductionError("custom_asset_not_found", "自定义素材不存在或已损坏", status=404) from exc
        if not isinstance(record, dict) or record.get("asset_id") != asset_id:
            raise ProductionError("custom_asset_not_found", "自定义素材不存在或已损坏", status=404)
        return record

    def _records(self) -> list[dict[str, Any]]:
        records = []
        for path in self.root.glob("library-asset-*/asset.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and value.get("lifecycle_status") != "archived":
                records.append(value)
        return records

    def list(self, *, kind: str = "", query: str = "", offset: int = 0, limit: int = 80) -> dict[str, Any]:
        needle = query.strip().casefold()
        rows = []
        for record in self._records():
            if kind and record.get("kind") != kind:
                continue
            labels = record.get("labels") if isinstance(record.get("labels"), dict) else {}
            searchable = [
                record.get("name"), record.get("key"), record.get("filename"),
                record.get("nickname"), *(record.get("tags") or []), *labels.values(),
            ]
            if needle and not any(needle in str(value or "").casefold() for value in searchable):
                continue
            rows.append(self._public(record))
        rows.sort(key=lambda item: (str(item.get("updated_at") or ""), str(item.get("asset_id") or "")), reverse=True)
        start = max(0, int(offset))
        page_size = max(1, min(int(limit), 200))
        page = rows[start : start + page_size]
        return {
            "ok": True,
            "schema_version": "custom-asset-library/1.0",
            "items": page,
            "total": len(rows),
            "offset": start,
            "limit": page_size,
            "has_more": start + len(page) < len(rows),
            "kind": kind,
            "query": query,
        }

    def detail(self, asset_id: str) -> dict[str, Any]:
        return self._public(self._load(asset_id))

    def source_for(self, asset_id: str) -> Path:
        record = self._load(asset_id)
        source = (self.root / asset_id / str(record.get("source_relative") or "")).resolve()
        try:
            source.relative_to((self.root / asset_id).resolve())
        except ValueError as exc:
            raise ProductionError("custom_asset_source_invalid", "自定义素材来源越界", status=409) from exc
        if not source.exists():
            raise ProductionError("custom_asset_source_missing", "自定义素材来源缺失", status=409)
        return source

    def preview(self, asset_id: str) -> Path | None:
        record = self._load(asset_id)
        source = self.source_for(asset_id)
        if record.get("kind") in {"background", "cg"}:
            return source if source.is_file() else None
        if record.get("kind") == "character" and source.is_dir():
            candidates = sorted(source.rglob("*.png")) + sorted(source.rglob("*.jpg"))
            candidates.sort(key=lambda path: ("avatar" not in path.name.casefold() and "portrait" not in path.name.casefold(), len(path.parts), path.name.casefold()))
            return candidates[0] if candidates else None
        return None

    def register(
        self,
        *,
        source: Path,
        kind: str,
        validation: dict[str, Any],
        filename: str,
        identifier: str,
        display_name: str,
        nickname: str,
        labels: dict[str, Any],
        recognition: dict[str, Any] | None,
        recognition_accepted: bool,
    ) -> tuple[dict[str, Any], bool]:
        digest = str(validation.get("sha256") or "")
        with self._lock:
            existing = next(
                (record for record in self._records() if record.get("kind") == kind and record.get("sha256") == digest),
                None,
            )
            if existing:
                return self._public(existing), True
            asset_id = new_id("library-asset")
            directory = self.root / asset_id
            source_root = directory / "source"
            directory.mkdir(parents=True, exist_ok=False)
            try:
                if source.is_dir():
                    shutil.copytree(source, source_root)
                    relative = "source"
                else:
                    source_root.mkdir()
                    target = source_root / source.name
                    shutil.copy2(source, target)
                    relative = str(Path("source") / source.name)
                candidate = (recognition or {}).get("candidate") if recognition_accepted else {}
                candidate = candidate if isinstance(candidate, dict) else {}
                final_name = display_name.strip() or str(candidate.get("title") or "").strip()
                key = identifier.strip() if kind == "character" else str(validation.get("stem") or "").strip()
                if not final_name:
                    final_name = str(labels.get("label") or key or Path(filename).stem)
                tags = labels.get("tags") if isinstance(labels.get("tags"), list) else candidate.get("tags") if recognition_accepted else []
                tags = list(dict.fromkeys(str(item).strip() for item in (tags or []) if str(item).strip()))[:24]
                merged_labels = {key: value for key, value in labels.items() if key != "tags"}
                if recognition_accepted:
                    for field in ("summary", "scene_type", "time_of_day", "mood"):
                        if candidate.get(field) and not merged_labels.get(field):
                            merged_labels[field] = candidate[field]
                record = {
                    "schema_version": "custom-asset/1.0",
                    "asset_id": asset_id,
                    "kind": kind,
                    "key": key,
                    "name": final_name,
                    "nickname": nickname.strip(),
                    "filename": Path(filename).name,
                    "sha256": digest,
                    "metadata": validation.get("metadata") or {},
                    "labels": merged_labels,
                    "tags": tags,
                    "recognition": recognition if recognition else {"state": "not_requested"},
                    "recognition_accepted": bool(recognition and recognition_accepted),
                    "source_relative": relative,
                    "source": "custom_library",
                    "lifecycle_status": "active",
                    "metadata_version": 1,
                    "created_at": utc_now(),
                    "updated_at": utc_now(),
                }
                self._write_record(directory / "asset.json", record)
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                raise
        return self._public(record), False

    def update_metadata(
        self,
        asset_id: str,
        *,
        expected_metadata_version: int,
        name: str,
        nickname: str,
        tags: Any,
        labels: Any,
    ) -> dict[str, Any]:
        clean_name = str(name or "").strip()
        clean_nickname = str(nickname or "").strip()
        if not clean_name:
            raise ProductionError("custom_asset_name_required", "素材名称不能为空")
        if len(clean_name) > 160 or len(clean_nickname) > 120:
            raise ProductionError("custom_asset_metadata_invalid", "素材名称或备注过长")
        if not isinstance(tags, list) or not isinstance(labels, dict):
            raise ProductionError("custom_asset_metadata_invalid", "素材标签格式无效")
        clean_tags = list(
            dict.fromkeys(str(item).strip() for item in tags if str(item).strip())
        )
        if len(clean_tags) > 24 or any(len(item) > 80 for item in clean_tags):
            raise ProductionError(
                "custom_asset_metadata_invalid", "搜索标签最多 24 个，每个不超过 80 个字符"
            )
        clean_labels: dict[str, str] = {}
        for field, limit in {"place": 100, "time": 80, "mood": 80}.items():
            value = str(labels.get(field) or "").strip()
            if len(value) > limit:
                raise ProductionError("custom_asset_metadata_invalid", "素材场景标签过长")
            if value:
                clean_labels[field] = value

        with self._lock:
            record = self._load(asset_id)
            current_version = int(record.get("metadata_version") or 1)
            if expected_metadata_version != current_version:
                raise ProductionError(
                    "custom_asset_metadata_conflict",
                    "素材信息已在其他位置更新，请刷新后重试",
                    status=409,
                    details={
                        "expected_metadata_version": expected_metadata_version,
                        "current_metadata_version": current_version,
                    },
                )
            existing_labels = (
                dict(record.get("labels")) if isinstance(record.get("labels"), dict) else {}
            )
            for field in ("place", "time", "mood", "scene_type", "time_of_day"):
                existing_labels.pop(field, None)
            existing_labels.update(clean_labels)
            record.update(
                {
                    "name": clean_name,
                    "nickname": clean_nickname,
                    "tags": clean_tags,
                    "labels": existing_labels,
                    "metadata_version": current_version + 1,
                    "updated_at": utc_now(),
                }
            )
            self._write_record(self._record_path(asset_id), record)
        return self._public(record)

    @staticmethod
    def recognition_digest(candidate: dict[str, Any]) -> str:
        payload = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
