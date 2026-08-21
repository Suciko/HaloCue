# -*- coding: utf-8 -*-
"""Conservative, deterministic guards for balanced character direction."""

import re

from director_policy import normalize_direction_plan


DIRECTION_FIELDS = frozenset({"face", "emo", "act", "fx"})
STRONG_ACTIONS = frozenset({"jump", "shake", "hophop"})
# Shake is a visible reaction state, not a resource to throttle globally.
UNTHROTTLED_ACTIONS = frozenset({"shake"})
COMEDY_EMOTICON_ESCALATIONS = frozenset(
    {
        ("疑问", "惊叹"),
        ("惊叹", "冒烟"),
        ("冒烟", "怒筋"),
        ("冷汗", "冒烟"),
        ("沉默", "惊叹"),
    }
)


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
        if field in explicit:
            continue
        item[field] = value
        applied[field] = value
        item.setdefault("_direction_origins", {})[field] = "model"
    return applied


def _remove_automatic_field(item, field, reason="density_cooldown"):
    value = item.pop(field, None)
    origins = item.get("_direction_origins")
    if isinstance(origins, dict):
        origins.pop(field, None)
    if value is not None:
        item.setdefault("_direction_drops", []).append({
            "field": field, "value": value, "reason": reason,
        })


def _director_value(item, field, default=""):
    director = item.get("_director")
    return director.get(field, default) if isinstance(director, dict) else default


def _continuity_command(item, layer):
    continuity = _director_value(item, "continuity", {})
    return continuity.get(layer, "none") if isinstance(continuity, dict) else "none"


def _allows_transient_repeat(item, layer, previous_target):
    if _continuity_command(item, layer) == "escalate":
        return True
    reason = _director_value(item, "reason", "none")
    if reason in {
        "new_stimulus", "listener_reaction", "group_sync",
        "comedy_escalation", "action_impact", "emotional_shift",
    }:
        return True
    target = str(_director_value(item, "reaction_target", "") or "")
    return bool(target and target != previous_target)


def normalize_emoticon_density(items):
    """Apply balanced emoticon cooldowns while preserving authored fields."""
    dialogue_no = -1
    previous_had_emoticon = False
    previous_emoticon = None
    previous_target = ""
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
            escalating_steam = (
                emoticon == "冒烟"
                and item.get("act") == "hophop"
                and previous_had_emoticon
            )
            semantic_escalation = (previous_emoticon, emoticon) in COMEDY_EMOTICON_ESCALATIONS
            directed_repeat = _allows_transient_repeat(item, "emo", previous_target)
            if (
                "emo" not in explicit
                and (previous_had_emoticon or too_soon)
                and not semantic_escalation
                and not escalating_steam
                and not directed_repeat
            ):
                _remove_automatic_field(item, "emo", "unsupported_transient_repeat")
                previous_had_emoticon = False
                previous_emoticon = None
            else:
                last_emoticon[emoticon] = dialogue_no
                previous_had_emoticon = True
                previous_emoticon = emoticon
                previous_target = str(_director_value(item, "reaction_target", "") or "")
        else:
            previous_had_emoticon = False
            previous_emoticon = None


def normalize_action_density(items):
    """Apply balanced action cooldowns while preserving authored fields."""
    previous_had_strong_action = False
    speaker_turns = {}
    last_speaker_action = {}
    previous_target = ""
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
        if action in UNTHROTTLED_ACTIONS:
            last_speaker_action[(who, action)] = speaker_turn
            previous_had_strong_action = action in STRONG_ACTIONS
            previous_target = str(_director_value(item, "reaction_target", "") or "")
            continue
        last_turn = last_speaker_action.get((who, action), -10_000)
        repeated_too_soon = speaker_turn - last_turn <= 3
        adjacent_strong = action in STRONG_ACTIONS and previous_had_strong_action
        directed_repeat = _allows_transient_repeat(item, "act", previous_target)
        if (
            "act" not in explicit
            and (repeated_too_soon or adjacent_strong)
            and not directed_repeat
        ):
            _remove_automatic_field(item, "act", "unsupported_transient_repeat")
            previous_had_strong_action = False
            continue
        last_speaker_action[(who, action)] = speaker_turn
        previous_had_strong_action = action in STRONG_ACTIONS
        previous_target = str(_director_value(item, "reaction_target", "") or "")


def normalize_direction_density(items):
    """Apply the stateful scene policy, with the legacy fallback kept for old callers."""
    if any(isinstance(item.get("_director_intent"), dict) for item in items):
        normalize_direction_plan(items)
        return
    normalize_emoticon_density(items)
    normalize_action_density(items)


def _direction_candidates(text, previous_text=""):
    previous_text = re.sub(r"\s+", "", str(previous_text or ""))
    value = re.sub(r"\s+", "", str(text or ""))
    eager_help = (
        any(token in value for token in ("也可以帮忙", "我也可以帮忙", "我也来帮忙"))
        and any(token in value for token in ("一起", "更快", "帮忙", "检查", "确认"))
    )
    clear_celebration = (
        value.startswith(("太好了！", "太好了!"))
        and any(token in value for token in ("继续", "成功", "通过", "完成", "没问题"))
    )
    formal_result_report = (
        bool(re.search(r"(?:报告|汇报|检查结果)[：:]", value))
        and any(
            token in value
            for token in (
                "没有发现", "未发现", "未检测到", "确认", "正常", "异常",
                "安全", "完毕", "结束", "已完成", "以上",
            )
        )
    )
    if formal_result_report:
        return {"emo": ("反应", "formal_result_report_response")}
    if eager_help or clear_celebration:
        return {
            "emo": ("闪亮", "eager_positive_participation"),
            "act": ("hophop", "eager_positive_participation"),
        }
    if re.search(r"[！？!?]$", value) and ("！？" in value or "?!" in value or "!?" in value):
        return {"emo": ("惊叹", "mixed_surprise_question")}
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
    listed_setback = (
        "淘汰" in value
        and ("……" in value or "..." in value)
        and ("、" in value or "路线" in value or "营业时间" in value)
    )
    sustained_complaint = (
        any(token in value for token in ("没辙", "没办法", "全都", "不会等人"))
        and ("……" in value or "..." in value or "路线" in value or "营业时间" in value)
        and any(token in value for token in ("算了", "真的是", "结果", "只能"))
    )
    if listed_setback or sustained_complaint:
        return {"emo": ("冒烟", "sustained_complaint")}
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
    if (
        len(value) <= 40
        and re.search(r"[！!。.]", value)
        and any(token in value for token in ("当然吃", "浪费", "只是", "总、总之", "总总之"))
        and ("！" in value or "!" in value)
    ):
        return {"act": ("jump", "defensive_comedy_reaction")}
    return {}


def infer_direction_cues(text, previous_text=""):
    """Return only high-confidence missing direction fields for one line."""
    return {
        field: value
        for field, (value, _rule) in _direction_candidates(text, previous_text).items()
    }


def supplement_directions(items, cast, *, rule_allowlist=None):
    """Fill empty portrait fields and report each deterministic supplement."""
    changes = []
    allowed_rules = set(rule_allowlist) if rule_allowlist is not None else None
    previous_text = ""
    for index, item in enumerate(items):
        if item.get("kind") != "line":
            continue
        character = cast.get(item.get("who"), {})
        if character.get("portrait") and not character.get("narrator"):
            for field, (value, rule) in _direction_candidates(
                item.get("text", ""), previous_text
            ).items():
                if allowed_rules is not None and rule not in allowed_rules:
                    continue
                before = item.get(field)
                explicit = set(item.get("_explicit_direction_fields") or ())
                repair_eager_cue = (
                    rule == "eager_positive_participation"
                    and field in {"emo", "act"}
                    and field not in explicit
                )
                if before == value or (before and not repair_eager_cue):
                    continue
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
