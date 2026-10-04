"""Read-only, maintainer-curated reference cards shipped with the application."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from services.halocue.runtime_layout import repository_root

from .errors import DomainError


class BundledCharacterCatalog:
    def __init__(self, root: Path | None = None):
        self.root = root or repository_root() / "data/reference-pack/characters"

    def descriptor(self) -> dict:
        return {
            "available": self.root.is_dir(),
            "character_cards": len(list(self.root.glob("*.json"))),
        }

    def search(self, query: str, limit: int = 18) -> dict:
        needle = str(query).strip().casefold()
        items = []
        for path in sorted(self.root.glob("*.json")):
            card = json.loads(path.read_text(encoding="utf-8"))
            names = [str(card.get("name", "")), *map(str, card.get("aliases", []))]
            if needle and not any(needle in name.casefold() for name in names):
                continue
            items.append(
                {
                    "id": path.stem,
                    "name": names[0],
                    "aliases": names[1:],
                    "summary": str(card.get("core", "")),
                    "source_kind": "maintainer_curated_reference",
                }
            )
            if len(items) >= limit:
                break
        return {"items": items, "available": self.root.is_dir()}

    def import_payload(self, card_id: str) -> dict:
        path = next((p for p in self.root.glob("*.json") if p.stem == card_id), None)
        if path is None:
            raise DomainError("reference_card_not_found", "找不到这份随包人物参考卡。", status=404)
        return {
            "filename": path.name,
            "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
            "source_label": "随包人物参考 · 维护者整理",
        }

    def resolve_mentions(self, text: str) -> dict:
        """Resolve complete names/aliases, preferring longer overlapping names."""
        source = str(text).casefold()
        result = {"available": self.root.is_dir(), "matches": [], "ambiguous": []}
        if re.search(r"(?:不要|别|禁止|关闭)自动.{0,8}(?:人物卡|人物资料)", source):
            return result
        aliases = {}
        entries = self.search("", limit=1000)["items"]
        result["available"] = result["available"] and bool(entries)
        for item in entries:
            for alias in {item["name"], *item["aliases"]}:
                name = alias.strip().casefold()
                if len(name) >= 2:
                    aliases.setdefault(name, {})[item["id"]] = item
        spans = []
        for alias, items in aliases.items():
            pattern = re.escape(alias)
            if alias.isascii():
                pattern = r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])"
            for match in re.finditer(pattern, source):
                spans.append((match.start(), match.end(), alias, list(items.values())))
        occupied, selected = [], set()
        for start, end, alias, items in sorted(
            spans, key=lambda entry: entry[1] - entry[0], reverse=True
        ):
            if any(start >= left and end <= right for left, right in occupied):
                continue
            occupied.append((start, end))
            clause_start = max(source.rfind(mark, 0, start) for mark in "。；;\n，,") + 1
            clause_end = min(
                [pos for mark in "。；;\n，," if (pos := source.find(mark, end)) >= 0]
                or [len(source)]
            )
            before, after = source[clause_start:start], source[end:clause_end]
            if re.search(
                r"(?:不(?:要|必|需)?|别|无需|不用|排除).{0,8}(?:写|加入|添加|导入|安排|出场|登场)?\s*$",
                before,
            ) or re.match(r".{0,4}(?:不出场|不登场|不加入|不导入)", after):
                continue
            if len(items) != 1:
                result["ambiguous"].append(
                    {
                        "alias": alias,
                        "candidates": [{"id": item["id"], "name": item["name"]} for item in items],
                    }
                )
            elif items[0]["id"] not in selected:
                selected.add(items[0]["id"])
                result["matches"].append(items[0])
        return result
