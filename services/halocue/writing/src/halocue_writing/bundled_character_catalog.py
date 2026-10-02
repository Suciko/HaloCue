"""Read-only, maintainer-curated reference cards shipped with the application."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from services.halocue.runtime_layout import repository_root

from .errors import DomainError


class BundledCharacterCatalog:
    def __init__(self, root: Path | None = None):
        self.root = root or repository_root() / "data/reference-pack/characters"

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
