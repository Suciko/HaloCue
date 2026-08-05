# -*- coding: utf-8 -*-
"""Conservative, deterministic guards for balanced character direction."""

import re


DIRECTION_FIELDS = frozenset({"face", "emo", "act", "fx"})
STRONG_ACTIONS = frozenset({"jump", "shake", "hophop"})


def mark_explicit_directions(item):
    """Record authored inline direction fields before model annotation."""
    item["_explicit_direction_fields"] = tuple(
        field for field in DIRECTION_FIELDS if item.get(field)
    )
    return item


def apply_model_directions(item, clean):
    """Apply legal model fields without replacing authored direction."""
    explicit = set(item.get("_explicit_direction_fields", ()))
    applied = {}
    for field, value in clean.items():
        if field in DIRECTION_FIELDS and field in explicit:
            continue
        item[field] = value
        applied[field] = value
        if field in DIRECTION_FIELDS:
            item.setdefault("_direction_origins", {})[field] = "model"
    return applied


def _remove_automatic_field(item, field):
    item.pop(field, None)
    origins = item.get("_direction_origins")
    if isinstance(origins, dict):
        origins.pop(field, None)


def normalize_emoticon_density(items):
    """Apply balanced emoticon cooldowns while preserving authored fields."""
    dialogue_no = -1
    previous_had_emoticon = False
    last_emoticon = {}
    for item in items:
        if item.get("kind") != "line":
            continue
        dialogue_no += 1
        explicit = set(item.get("_explicit_direction_fields", ()))
        emoticon = item.get("emo")
        if emoticon:
            cooldown = 8 if emoticon == "脸红" else 4
            too_soon = dialogue_no - last_emoticon.get(emoticon, -10_000) <= cooldown
            if "emo" not in explicit and (previous_had_emoticon or too_soon):
                _remove_automatic_field(item, "emo")
                previous_had_emoticon = False
            else:
                last_emoticon[emoticon] = dialogue_no
                previous_had_emoticon = True
        else:
            previous_had_emoticon = False


def normalize_action_density(items):
    """Apply balanced action cooldowns while preserving authored fields."""
    previous_had_strong_action = False
    speaker_turns = {}
    last_speaker_action = {}
    for item in items:
        if item.get("kind") != "line":
            continue
        who = item.get("who") or ""
        speaker_turns[who] = speaker_turns.get(who, 0) + 1
        speaker_turn = speaker_turns[who]
        explicit = set(item.get("_explicit_direction_fields", ()))
        action = item.get("act")
        if not action:
            previous_had_strong_action = False
            continue
        last_turn = last_speaker_action.get((who, action), -10_000)
        repeated_too_soon = speaker_turn - last_turn <= 3
        adjacent_strong = action in STRONG_ACTIONS and previous_had_strong_action
        if "act" not in explicit and (repeated_too_soon or adjacent_strong):
            _remove_automatic_field(item, "act")
            previous_had_strong_action = False
            continue
        last_speaker_action[(who, action)] = speaker_turn
        previous_had_strong_action = action in STRONG_ACTIONS


def normalize_direction_density(items):
    """Apply all balanced cooldowns while preserving authored direction."""
    normalize_emoticon_density(items)
    normalize_action_density(items)


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
