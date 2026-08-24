# -*- coding: utf-8 -*-
"""Portrait-space metadata used by the deterministic AA stage planner."""

from __future__ import annotations

import copy
import json
import os
import re
from functools import lru_cache
from typing import Any, Mapping


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CATALOG = os.path.join(HERE, "portrait_layout_hints.json")
CATALOG_VERSION = 1


def _base_name(value: Any) -> str:
    text = str(value or "").strip()
    return re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", text).strip()


@lru_cache(maxsize=4)
def load_catalog(path: str = DEFAULT_CATALOG) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"version": CATALOG_VERSION, "characters": {}}
    if not isinstance(value, dict) or not isinstance(value.get("characters"), dict):
        return {"version": CATALOG_VERSION, "characters": {}}
    return value


def _hint_for(character: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any]:
    rows = catalog.get("characters")
    if not isinstance(rows, Mapping):
        return {}
    candidates = []
    for key in (character.get("name"), character.get("identifier")):
        text = str(key or "").strip()
        if text:
            candidates.extend((text, _base_name(text)))
    for alias in character.get("aliases") or ():
        text = str(alias or "").strip()
        if text:
            candidates.extend((text, _base_name(text)))
    for key in dict.fromkeys(candidates):
        value = rows.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def enrich_resource_index(index: Mapping[str, Any], *, catalog_path: str = DEFAULT_CATALOG) -> dict[str, Any]:
    """Freeze conservative layout hints into a resource-index copy.

    Exact per-variant metadata already present on a character always wins.
    Community hints are attached only as provenance-marked fallbacks.
    """
    enriched = copy.deepcopy(dict(index))
    catalog = load_catalog(catalog_path)
    characters = enriched.get("characters")
    if not isinstance(characters, list):
        characters = []
        enriched["characters"] = characters
    for character in characters:
        if not isinstance(character, dict) or isinstance(character.get("portrait_layout"), dict):
            continue
        hint = _hint_for(character, catalog)
        if not hint:
            continue
        useful = {
            name: hint[name]
            for name in (
                "face_direction", "has_weapon", "has_wings", "framing",
                "visual_width", "min_slot_gap",
            )
            if hint.get(name) is not None
        }
        if not useful:
            continue
        character["portrait_layout"] = {
            **useful,
            "source": str(catalog.get("source") or "community_position_reference"),
            "confidence": "coarse_name_consensus",
            "default_skin_only": True,
            "hint_count": int(hint.get("hint_count") or 1),
        }
    enriched["portrait_layout_catalog"] = {
        "version": int(catalog.get("version") or CATALOG_VERSION),
        "source": str(catalog.get("source") or "community_position_reference"),
    }
    return enriched


def profiles_for_cast(
    index: Mapping[str, Any],
    cast: Mapping[str, Any],
    *,
    catalog_fallback: bool = False,
    catalog_path: str = DEFAULT_CATALOG,
) -> dict[str, dict[str, Any]]:
    """Return exact ident -> frozen portrait-layout metadata for this cast."""
    rows = index.get("characters") if isinstance(index, Mapping) else None
    by_ident = {
        str(row.get("identifier") or ""): row
        for row in rows or ()
        if isinstance(row, Mapping) and str(row.get("identifier") or "")
    }
    profiles: dict[str, dict[str, Any]] = {}
    catalog = load_catalog(catalog_path) if catalog_fallback else {}
    for display_name, character in cast.items():
        if not isinstance(character, Mapping):
            continue
        ident = str(character.get("id") or "")
        if not ident or ident in profiles:
            continue
        own = character.get("portrait_layout")
        row = by_ident.get(ident, {})
        value = own if isinstance(own, Mapping) else row.get("portrait_layout")
        if not isinstance(value, Mapping) and catalog_fallback:
            lookup = dict(row)
            lookup.setdefault("name", display_name)
            hint = _hint_for(lookup, catalog)
            useful = {
                name: hint[name]
                for name in (
                    "face_direction", "has_weapon", "has_wings", "framing",
                    "visual_width", "min_slot_gap",
                )
                if hint.get(name) is not None
            }
            value = useful
        if isinstance(value, Mapping):
            profiles[ident] = dict(value)
    return profiles
