"""Conservative local prefills; mappings remain editable and cards stay unreviewed."""

import re

from .background_search import normalize
from .scene_backgrounds import assess_background, scene_context


def character_match(speaker: str, characters: list[dict]) -> dict | None:
    needle = speaker.strip().casefold()
    matches = [
        row
        for row in characters
        if row.get("identifier")
        and row.get("spine")
        and needle
        in {
            str(name).strip().casefold()
            for name in [row.get("name"), row.get("source_name"), *row.get("aliases", [])]
        }
    ]
    if len(matches) == 1:
        return matches[0]
    # Explicit ordinary outfit, only when there is exactly one such AA resource.
    ordinary = [
        row
        for row in matches
        if re.fullmatch(
            r"CharacterSpine_[a-z]+(?:_noweapon)?", str(row.get("spine")).split("/")[-1]
        )
    ]
    return ordinary[0] if len(ordinary) == 1 else None


def background_match(cards: list[dict], scene: dict, backgrounds: list[dict]) -> dict | None:
    context = scene_context(cards, scene["card_id"], {})
    if context["current_background"] or context["notes"]:
        return None
    title = normalize(context["title"])
    candidates = []
    for row in backgrounds:
        if row.get("key", "").startswith("BG_CS_"):
            continue
        assessment = assess_background(row, context)
        if assessment["conflicts"]:
            continue
        exact = any(title == normalize(row.get(key) or "") for key in ("name", "place"))
        if exact or (context["requirements"].get("place") and assessment["status"] == "match"):
            candidates.append((2 if exact else 1, row))
    if not candidates:
        return None
    score = max(item[0] for item in candidates)
    winners = [row for value, row in candidates if value == score]
    identities = {
        row.get("_aa_hash") or row.get("aa_hash") or row["key"].casefold() for row in winners
    }
    return winners[0] if len(identities) == 1 else None
