from __future__ import annotations

import copy
import re
from typing import Any, Mapping, Sequence


_ASCII_TERM = re.compile(r"[a-z0-9][a-z0-9_-]{1,}", re.IGNORECASE)
_CJK_TERM = re.compile(r"[\u3400-\u9fff]{2,}")
_GENERIC_TERMS = {
    "bg", "se", "sound", "background", "01", "02", "03", "04",
    "背景", "音效", "场景", "剧情", "人物", "蔚蓝档案",
}


def _terms(value: str) -> set[str]:
    text = str(value or "").casefold()
    terms = {match.group(0) for match in _ASCII_TERM.finditer(text)}
    for match in _CJK_TERM.finditer(text):
        chunk = match.group(0)
        terms.add(chunk)
        terms.update(chunk[index:index + 2] for index in range(len(chunk) - 1))
    return {term for term in terms if term not in _GENERIC_TERMS}


def _label_text(labels: Mapping[str, Any], key: str) -> str:
    value = labels.get(key)
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(
            str(value.get(field) or "")
            for field in ("label", "place", "time", "mood", "tags")
        )
    return ""


def _usage_pins(usage_chain: Sequence[Mapping[str, Any]]) -> tuple[set[str], set[str]]:
    backgrounds: set[str] = set()
    sounds: set[str] = set()
    for entry in usage_chain:
        if not isinstance(entry, Mapping):
            continue
        for need in entry.get("needs") or []:
            if not isinstance(need, Mapping):
                continue
            key = str(need.get("aa_key") or "").strip()
            kind = str(need.get("kind") or "").strip().casefold()
            if not key:
                continue
            if kind in {"background", "bg"}:
                backgrounds.add(key)
            elif kind in {"sound", "se", "sfx"}:
                sounds.add(key)
    return backgrounds, sounds


def _ranked_candidates(
    keys: Sequence[str], labels: Mapping[str, Any], query: str, query_terms: set[str],
) -> list[tuple[float, str]]:
    query_folded = query.casefold()
    ranked: list[tuple[float, str]] = []
    for key in keys:
        label = _label_text(labels, key)
        descriptor = f"{key} {label}".strip()
        score = 0.0
        if key.casefold() in query_folded:
            score += 10_000
        label_folded = label.casefold().strip()
        if len(label_folded) >= 2 and label_folded in query_folded:
            score += 1_000 + len(label_folded)
        for term in _terms(descriptor) & query_terms:
            score += min(100, len(term) * len(term))
        ranked.append((score, key))
    return sorted(ranked, key=lambda item: (-item[0], item[1]))


def _select(
    keys: Sequence[str], labels: Mapping[str, Any], query: str, query_terms: set[str],
    *, pins: set[str], limit: int, fallback_order: Sequence[str],
) -> list[str]:
    available = set(keys)
    selected = {key for key in pins if key in available}
    ranked = _ranked_candidates(keys, labels, query, query_terms)
    for score, key in ranked:
        if score <= 0 or len(selected) >= limit:
            break
        selected.add(key)
    for key in fallback_order:
        if len(selected) >= limit:
            break
        if key in available:
            selected.add(key)
    return sorted(selected)


def rank_background_candidates(index: Mapping[str, Any], query: str) -> list[tuple[float, str]]:
    """Rank frozen keys using existing labels; scores are not probabilities."""
    return _ranked_candidates(
        list(index.get("bg") or {}), index.get("bg_label") or {}, query, _terms(query),
    )


def build_resource_candidate_index(
    index: Mapping[str, Any],
    source_text: str,
    *,
    cast_config: Mapping[str, Any] | None = None,
    usage_chain: Sequence[Mapping[str, Any]] | None = None,
    background_limit: int = 48,
    sound_limit: int = 96,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a bounded prompt catalogue while leaving the source index untouched."""
    backgrounds = [str(key) for key in (index.get("bg") or {})]
    sounds = [str(key) for key in (index.get("sounds") or [])]
    background_labels = index.get("bg_label") or {}
    sound_labels = index.get("sound_label") or {}
    usage_backgrounds, usage_sounds = _usage_pins(usage_chain or [])

    config = cast_config or {}
    config_backgrounds = {
        str(config.get("default_bg") or "").strip(),
        *(str(value or "").strip() for value in (config.get("scene_bg") or {}).values()),
    }
    exact_backgrounds = {
        key for key in backgrounds if key.casefold() in source_text.casefold()
    }
    exact_sounds = {key for key in sounds if key.casefold() in source_text.casefold()}
    background_pins = usage_backgrounds | config_backgrounds | exact_backgrounds | {"BG_Black"}
    sound_pins = usage_sounds | exact_sounds

    query = source_text + "\n" + "\n".join(
        str(entry) for entry in (usage_chain or [])
    )
    query_terms = _terms(query)
    background_counts = index.get("bg") or {}
    background_fallback = sorted(
        backgrounds,
        key=lambda key: (
            -int(background_counts.get(key) or 0)
            if str(background_counts.get(key) or "").lstrip("-").isdigit()
            else 0,
            key,
        ),
    )
    selected_backgrounds = _select(
        backgrounds,
        background_labels,
        query,
        query_terms,
        pins=background_pins,
        limit=max(1, int(background_limit)),
        fallback_order=background_fallback,
    )
    selected_sounds = _select(
        sounds,
        sound_labels,
        query,
        query_terms,
        pins=sound_pins,
        limit=max(1, int(sound_limit)),
        fallback_order=sorted(sounds),
    )

    candidate = copy.deepcopy(dict(index))
    candidate["bg"] = {
        key: (index.get("bg") or {})[key] for key in selected_backgrounds
    }
    candidate["sounds"] = selected_sounds
    candidate["bg_label"] = {
        key: background_labels[key]
        for key in selected_backgrounds if key in background_labels
    }
    candidate["sound_label"] = {
        key: sound_labels[key]
        for key in selected_sounds if key in sound_labels
    }
    manifest = {
        "version": 1,
        "backgrounds": selected_backgrounds,
        "sounds": selected_sounds,
        "background_count": len(selected_backgrounds),
        "sound_count": len(selected_sounds),
        "full_background_count": len(backgrounds),
        "full_sound_count": len(sounds),
        "pinned_backgrounds": sorted(background_pins & set(backgrounds)),
        "pinned_sounds": sorted(sound_pins & set(sounds)),
    }
    return candidate, manifest
