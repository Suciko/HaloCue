from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import ProductionError
from .name_baseline import CharacterNameBaseline
from .resource_previews import ResourcePreview, ResourcePreviewCatalog


RESOURCE_KINDS = {"characters", "backgrounds", "sounds", "cg"}
CG_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class ResourceCatalog:
    """Read the exported AA resource index without exposing local file paths."""

    def __init__(
        self,
        index_path: Path | None,
        aa_data: Path | None = None,
        legacy_root: Path | None = None,
        name_baseline: CharacterNameBaseline | None = None,
    ) -> None:
        self.index_path = index_path
        self.aa_data = aa_data
        self.previews = ResourcePreviewCatalog(legacy_root or Path(), aa_data)
        self.name_baseline = name_baseline or CharacterNameBaseline()

    def cg_keys(self) -> list[str]:
        """List registered popup names from the configured AA workspace only."""
        popup_dir = self.aa_data / "overrides" / "popups" if self.aa_data else None
        if not popup_dir or not popup_dir.is_dir():
            return []
        return sorted(
            {
                file.stem
                for file in popup_dir.iterdir()
                if file.is_file() and file.suffix.casefold() in CG_EXTENSIONS and file.stem
            },
            key=str.casefold,
        )

    def _load(self) -> dict[str, Any]:
        if not self.index_path or not self.index_path.is_file():
            raise ProductionError(
                "resource_index_not_configured",
                "资源索引尚未配置",
                status=409,
            )
        try:
            value = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProductionError(
                "resource_index_corrupted",
                "资源索引无法读取",
                status=500,
            ) from exc
        if not isinstance(value, dict):
            raise ProductionError(
                "resource_index_corrupted",
                "资源索引格式无效",
                status=500,
            )
        return value

    @staticmethod
    def _page(items: list[dict[str, Any]], offset: int, limit: int) -> dict[str, Any]:
        total = len(items)
        page = items[offset : offset + limit]
        return {
            "ok": True,
            "items": page,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(page) < total,
        }

    def list(
        self, kind: str, *, query: str = "", offset: int = 0, limit: int = 80
    ) -> dict[str, Any]:
        if kind not in RESOURCE_KINDS:
            raise ProductionError("resource_kind_not_found", "资源类型不存在", status=404)
        payload = self._load()
        needle = query.strip().casefold()
        offset = max(0, offset)
        limit = max(1, min(limit, 200))

        if kind == "cg":
            items = [
                {"key": key, "name": key, "source": "aa_popup_override"}
                for key in self.cg_keys()
                if not needle or needle in key.casefold()
            ]
        elif kind == "backgrounds":
            raw = payload.get("bg") if isinstance(payload.get("bg"), dict) else {}
            items = [
                {
                    "key": str(key),
                    "name": str(key),
                    "aa_hash": value,
                    "source": "resource_index",
                }
                for key, value in raw.items()
                if not needle or needle in str(key).casefold()
            ]
        elif kind == "sounds":
            raw = payload.get("sounds") if isinstance(payload.get("sounds"), list) else []
            items = [
                {"key": str(value), "name": str(value), "source": "resource_index"}
                for value in raw
                if isinstance(value, (str, int))
                and (not needle or needle in str(value).casefold())
            ]
        else:
            raw = (
                payload.get("characters")
                if isinstance(payload.get("characters"), list)
                else []
            )
            items = []
            for value in raw:
                if not isinstance(value, dict):
                    continue
                identifier = str(value.get("identifier") or "").strip()
                if not identifier:
                    continue
                presentation = self.name_baseline.resolve(value)
                name = str(presentation["name"] or identifier)
                club = str(value.get("club") or "")
                aliases = presentation["aliases"]
                if needle and not any(needle in field.casefold() for field in (identifier, name, club, *aliases)):
                    continue
                faces = value.get("faces") if isinstance(value.get("faces"), list) else []
                items.append(
                    {
                        "key": identifier,
                        "identifier": identifier,
                        "name": name,
                        "club": club,
                        "spine": str(value.get("spine") or ""),
                        "outfit_key": str(value.get("outfit_key") or ""),
                        "avatar_key": str(value.get("avatar") or ""),
                        "face_count": len(faces),
                        "name_source": presentation["name_source"],
                        "aliases": aliases,
                        "source": "resource_index",
                    }
                )

        items.sort(key=lambda item: (str(item.get("name") or "").casefold(), item["key"]))
        result = self._page(items, offset, limit)
        result["kind"] = kind
        result["query"] = query
        return result

    def contains(self, kind: str, key: str) -> bool:
        if kind == "cg":
            return key in set(self.cg_keys())
        if kind == "backgrounds":
            raw = self._load().get("bg")
            return isinstance(raw, dict) and key in raw
        if kind == "sounds":
            raw = self._load().get("sounds")
            return isinstance(raw, list) and key in {str(item) for item in raw}
        if kind == "characters":
            raw = self._load().get("characters")
            return isinstance(raw, list) and any(
                isinstance(item, dict) and str(item.get("identifier") or "") == key
                for item in raw
            )
        return False

    def preview(self, kind: str, key: str) -> ResourcePreview | None:
        if not self.contains(kind, key):
            return None
        if kind == "backgrounds":
            return self.previews.background(key)
        if kind == "cg":
            return self.previews.cg(key)
        if kind == "characters":
            raw = self._load().get("characters")
            item = next(
                (
                    value for value in raw if isinstance(raw, list) and isinstance(value, dict)
                    and str(value.get("identifier") or "") == key
                ),
                None,
            )
            if item:
                return self.previews.avatar(
                    avatar_key=str(item.get("avatar") or ""),
                    spine=str(item.get("spine") or ""),
                )
        return None

    def character_detail(self, identifier: str) -> dict[str, Any]:
        raw = self._load().get("characters")
        if not isinstance(raw, list):
            raw = []
        value = next(
            (
                item
                for item in raw
                if isinstance(item, dict)
                and str(item.get("identifier") or "") == identifier
            ),
            None,
        )
        if value is None:
            raise ProductionError("character_not_found", "角色不在资源索引中", status=404)
        faces = value.get("faces") if isinstance(value.get("faces"), list) else []
        presentation = self.name_baseline.resolve(value)
        safe_faces = []
        for face in faces:
            if not isinstance(face, dict):
                continue
            safe_faces.append(
                {
                    "id": str(face.get("id") or ""),
                    "raw": str(face.get("raw") or ""),
                    "label": str(face.get("label") or ""),
                }
            )
        return {
            "ok": True,
            "character": {
                "key": identifier,
                "identifier": identifier,
                "name": str(presentation["name"] or identifier),
                "name_zh_cn": str(presentation["name_zh_cn"]),
                "name_ja_fandom": str(presentation["name_ja_fandom"]),
                "aliases": presentation["aliases"],
                "source_name": str(presentation["source_name"]),
                "name_source": str(presentation["name_source"]),
                "club": str(value.get("club") or ""),
                "spine": str(value.get("spine") or ""),
                "outfit_key": str(value.get("outfit_key") or ""),
                "avatar_key": str(value.get("avatar") or ""),
                "faces": safe_faces,
                "source": "resource_index",
            },
        }
