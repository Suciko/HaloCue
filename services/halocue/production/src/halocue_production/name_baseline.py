from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CharacterNameBaseline:
    """Resolve user-facing names without changing AA resource identities."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._by_key: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path or not self.path.is_file():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        rows = payload.get("characters") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            keys = {
                str(row.get("identifier") or "").strip(),
                str(row.get("outfit_key") or "").strip(),
                str(row.get("spine") or "").strip(),
            }
            if not any(keys):
                continue
            if not str(row.get("name_zh_cn") or "").strip():
                continue
            for key in keys:
                if key:
                    self._by_key[key] = row

    @staticmethod
    def _aliases(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))

    def resolve(self, character: dict[str, Any]) -> dict[str, Any]:
        """Return presentation metadata while retaining the original legacy name."""
        source_name = str(
            character.get("source_name")
            or character.get("legacy_name")
            or character.get("name")
            or character.get("identifier")
            or ""
        ).strip()
        entry = next(
            (
                self._by_key[key]
                for key in (
                    str(character.get("identifier") or "").strip(),
                    str(character.get("outfit_key") or "").strip(),
                    str(character.get("spine") or "").strip(),
                )
                if key in self._by_key
            ),
            None,
        )
        explicit_cn = str(character.get("name_zh_cn") or "").strip()
        baseline_cn = str(entry.get("name_zh_cn") or "").strip() if entry else ""
        fandom_name = str(
            (entry or {}).get("name_ja_fandom") or character.get("name_ja_fandom") or ""
        ).strip()
        aliases = self._aliases((entry or {}).get("aliases"))
        aliases.extend(self._aliases(character.get("aliases")))
        aliases.extend(name for name in (source_name, fandom_name) if name)
        display_name = explicit_cn or baseline_cn or source_name
        return {
            "name": display_name,
            "name_zh_cn": explicit_cn or baseline_cn,
            "name_ja_fandom": fandom_name,
            "aliases": list(dict.fromkeys(aliases)),
            "source_name": source_name,
            "name_source": (
                "zh_cn_official_or_curated"
                if explicit_cn or baseline_cn
                else "legacy_source_unreviewed"
            ),
        }

    def decorate(self, character: dict[str, Any]) -> dict[str, Any]:
        """Copy a character row and add display/search fields for the 1.0 UI."""
        result = dict(character)
        resolved = self.resolve(result)
        if resolved["source_name"] and "legacy_name" not in result:
            result["legacy_name"] = resolved["source_name"]
        result.update(resolved)
        return result

    def decorate_resource_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a task-local resource snapshot with the name policy applied."""
        result = dict(payload)
        rows = payload.get("characters")
        if isinstance(rows, list):
            result["characters"] = [
                self.decorate(row) if isinstance(row, dict) else row for row in rows
            ]
        return result
