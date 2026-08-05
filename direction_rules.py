# -*- coding: utf-8 -*-
"""Conservative, deterministic guards for balanced character direction."""

import re


def _direction_candidates(text, previous_text=""):
    del previous_text  # Reserved for contextual rules that need the prior beat.
    value = re.sub(r"\s+", "", str(text or ""))
    if re.fullmatch(r"[…⋯.·]+[!！]+", value):
        return {"emo": ("惊叹", "punctuation_only_exclaim")}
    if (
        value.startswith(("……", "⋯⋯", "..."))
        and "!" not in value
        and "！" not in value
        and any(token in value for token in ("为什么", "怎么会", "怎么把"))
        and any(token in value for token in ("那么", "这么", "说得", "说成"))
    ):
        return {"emo": ("沉默", "paused_deadpan_response")}
    if (
        any(
            token in value
            for token in ("走了！", "走了!", "快点", "跟上", "闭嘴", "够了")
        )
        and any(
            token in value
            for token in ("再不", "还不", "才真的", "都给我", "偏离计划")
        )
        and ("！" in value or "!" in value)
    ):
        return {"emo": ("冒烟", "irritated_urgent_command")}
    if (
        len(value) <= 24
        and re.search(r"[!！]{2,}$", value)
        and any(
            token in value
            for token in (
                "更不行",
                "绝对不行",
                "才不是",
                "绝对不要",
                "怎么可能",
                "闭嘴",
                "住手",
            )
        )
    ):
        return {"act": ("jump", "forceful_short_rebuttal")}
    return {}


def infer_direction_cues(text, previous_text=""):
    """Return only high-confidence missing direction fields for one line."""
    return {
        field: value
        for field, (value, _rule) in _direction_candidates(text, previous_text).items()
    }


def supplement_directions(items, cast):
    """Fill empty portrait fields and report each deterministic supplement."""
    changes = []
    previous_text = ""
    for index, item in enumerate(items):
        if item.get("kind") != "line":
            continue
        character = cast.get(item.get("who"), {})
        if character.get("portrait") and not character.get("narrator"):
            for field, (value, rule) in _direction_candidates(
                item.get("text", ""), previous_text
            ).items():
                if item.get(field):
                    continue
                before = item.get(field)
                item[field] = value
                item.setdefault("_direction_origins", {})[field] = (
                    "deterministic_supplement"
                )
                changes.append(
                    {
                        "item_index": index,
                        "field": field,
                        "before": before,
                        "after": value,
                        "rule": rule,
                    }
                )
        previous_text = str(item.get("text") or "")
    return changes
