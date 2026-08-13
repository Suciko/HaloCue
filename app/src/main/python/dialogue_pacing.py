# -*- coding: utf-8 -*-
"""Conservative dialogue segmentation for AA's one-bubble-per-line display."""

import re


_STRONG_MARK = re.compile(r"——|[！!？?]{2,}")
_CUTS = re.compile(r"——|[。！？!?；;]+")


def _split_once(text, *, threshold=38, minimum=8):
    if len(text) <= threshold or not _STRONG_MARK.search(text):
        return None
    candidates = []
    for match in _CUTS.finditer(text):
        cut = match.end()
        if minimum <= cut <= len(text) - minimum:
            candidates.append(cut)
    if not candidates:
        return None
    em_dash = [m.end() for m in re.finditer("——", text)
               if minimum <= m.end() <= len(text) - minimum]
    pool = em_dash or candidates
    cut = min(pool, key=lambda value: abs(value - len(text) / 2))
    return text[:cut], text[cut:]


def split_strong_dialogue_items(items, cast, *, threshold=38):
    """Split only long, strongly punctuated spoken lines without changing text.

    Manual annotations are left untouched. Narration is also left untouched:
    this rule exists for AA dialogue bubbles, not prose formatting.
    Inherits source_id and updates split_index.
    """
    result = []
    for item in items:
        character = cast.get(item.get("who"), {})
        eligible = (
            item.get("kind") == "line"
            and not character.get("narrator")
            and not any(item.get(key) for key in ("face", "emo", "act", "fx"))
        )
        split = _split_once(item.get("text", ""), threshold=threshold) if eligible else None
        if not split:
            result.append(item)
            continue
        for idx, text in enumerate(split):
            clone = dict(item)
            clone["text"] = text
            clone["raw"] = f"{item['who']}: {text}"
            clone["split_index"] = idx
            result.append(clone)
    return result
