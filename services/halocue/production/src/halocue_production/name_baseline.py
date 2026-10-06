from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from services.halocue.runtime_layout import repository_root


def character_query_priority(character: dict[str, Any], query: str) -> int:
    needle = query.strip().casefold()
    names = [character.get("name"), *character.get("aliases", [])]
    return int(bool(needle) and any(needle == str(name or "").strip().casefold() for name in names))


@lru_cache(maxsize=1)
def bundled_name_aliases() -> dict[str, list[str]]:
    """Share curated spellings with AA search without inventing resource IDs."""
    groups: dict[str, list[list[str]]] = {}
    for path in sorted((repository_root() / "data/reference-pack/characters").glob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        names = list(dict.fromkeys([str(card.get("name") or "").strip(),
            *CharacterNameBaseline._aliases(card.get("aliases"))]))
        for name in names:
            if name:
                groups.setdefault(name.casefold(), []).append(names)
    # A shared short alias must not join unrelated or alternative identities.
    return {name: list(dict.fromkeys(names[0])) for name, names in groups.items()
            if len({tuple(group) for group in names}) == 1}


class CharacterNameBaseline:
    """Resolve user-facing names without changing AA resource identities."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._by_key: dict[str, dict[str, Any]] = {}
        self._signature: tuple[int, int] | None = None
        self._load()

    def _load(self) -> None:
        try:
            stat = self.path.stat() if self.path else None
        except OSError:
            stat = None
        signature = (stat.st_mtime_ns, stat.st_size) if stat else None
        if signature == self._signature:
            return
        if signature is None:
            self._by_key = {}
            self._signature = signature
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._by_key = {}
            self._signature = signature
            return
        rows = payload.get("characters") if isinstance(payload, dict) else None
        entries: dict[str, dict[str, Any]] = {}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            keys = {
                str(row.get("identifier") or "").strip(),
                str(row.get("outfit_key") or "").strip(),
                str(row.get("spine") or "").strip(),
            }
            if not any(keys):
                continue
            if not any(str(row.get(field) or "").strip() for field in ("name_zh_cn", "name_ja_fandom")):
                continue
            for key in keys:
                if key:
                    entries[key] = row
        self._by_key = entries
        self._signature = signature

    @staticmethod
    def _aliases(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))

    def resolve(self, character: dict[str, Any]) -> dict[str, Any]:
        """Return presentation metadata while retaining the original legacy name."""
        self._load()
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
        aliases.extend(name for name in (source_name, fandom_name, explicit_cn, baseline_cn) if name)
        # Official AA skeletons keep the romanized first name even when the
        # manifest uses a regional spelling (e.g. 陽奈). Use a unique curated
        # alias group, never substring matching or a generated character ID.
        spine = str(character.get("spine") or "").replace("\\", "/")
        official = re.search(r"(?:^|/)CharacterSpine_([a-z]+)(?:_|$)", spine, re.I)
        if official and not character.get("user_custom") and character.get("source") not in {"custom", "task_import"}:
            aliases.extend(bundled_name_aliases().get(official[1].casefold(), []))
        for name in list(aliases):
            aliases.extend(bundled_name_aliases().get(name.casefold(), []))
        display_name = fandom_name or explicit_cn or baseline_cn or source_name
        return {
            "name": display_name,
            "name_zh_cn": explicit_cn or baseline_cn,
            "name_ja_fandom": fandom_name,
            "aliases": list(dict.fromkeys(aliases)),
            "source_name": source_name,
            "name_source": (
                "ja_fandom_curated" if fandom_name else "zh_cn_official_or_curated"
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
