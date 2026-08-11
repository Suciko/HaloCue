# -*- coding: utf-8 -*-
"""Shared direction policy for model prompting and deterministic restraint."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any, Dict, Mapping, MutableMapping, Sequence


WINDOW_LINES = 12
HEAVY_FIELDS = frozenset({"fx", "bgfx", "shake"})

# Caps are automatic annotations per 12 dialogue lines. Authored annotations are
# never removed, but still consume the budget so automation does not pile on top.
FUNCTION_BUDGETS: Dict[str, Dict[str, int]] = {
    "establishing": dict(face=2, emo=1, act=1, fx=1, se=2, bg=1, bg_request=1,
                         place=1, shake=0, bgfx=1, trans=1, move=1, shot=0,
                         camera=2, beat=0, heavy=1),
    "entrance": dict(face=3, emo=2, act=2, fx=1, se=2, bg=0, bg_request=0,
                     place=0, shake=0, bgfx=1, trans=0, move=2, shot=0,
                     camera=3, beat=1, heavy=1),
    "exposition": dict(face=3, emo=1, act=1, fx=1, se=1, bg=0, bg_request=0,
                       place=0, shake=0, bgfx=0, trans=0, move=1, shot=0,
                       camera=3, beat=1, heavy=1),
    "dialogue": dict(face=3, emo=1, act=1, fx=0, se=1, bg=0, bg_request=0,
                     place=0, shake=0, bgfx=0, trans=0, move=1, shot=0,
                     camera=2, beat=1, heavy=0),
    "comedy_escalation": dict(face=5, emo=4, act=3, fx=1, se=2, bg=0,
                              bg_request=0, place=0, shake=1, bgfx=1, trans=0,
                              move=1, shot=0, camera=4, beat=2, heavy=2),
    "conflict": dict(face=4, emo=3, act=2, fx=1, se=2, bg=0, bg_request=0,
                     place=0, shake=1, bgfx=1, trans=0, move=2, shot=0,
                     camera=4, beat=1, heavy=2),
    "emotional_turn": dict(face=4, emo=1, act=1, fx=1, se=1, bg=0,
                           bg_request=0, place=0, shake=0, bgfx=0, trans=0,
                           move=1, shot=0, camera=3, beat=1, heavy=1),
    "action": dict(face=4, emo=2, act=4, fx=2, se=4, bg=1, bg_request=1,
                   place=1, shake=2, bgfx=2, trans=1, move=3, shot=2,
                   camera=5, beat=1, heavy=3),
    "closing": dict(face=2, emo=1, act=1, fx=0, se=1, bg=1, bg_request=1,
                    place=1, shake=0, bgfx=0, trans=1, move=1, shot=0,
                    camera=2, beat=1, heavy=0),
}

STORY_MULTIPLIERS = {
    "main": {"se": 1.25, "bgfx": 1.25, "shake": 1.25, "shot": 1.25},
    "event": {"emo": 1.25, "act": 1.25, "beat": 1.25},
    "bond": {"face": 1.25, "camera": 1.25, "emo": 0.75, "act": 0.75,
             "heavy": 0.6, "bgfx": 0.5, "shake": 0.5},
}

FIELD_REASONS = {
    "emo": {"new_stimulus", "emotional_shift", "listener_reaction", "group_sync",
            "comedy_escalation", "action_impact"},
    "act": {"new_stimulus", "relation_shift", "emotional_shift", "group_sync",
            "comedy_escalation", "action_impact"},
    "fx": {"new_stimulus", "relation_shift", "emotional_shift", "action_impact",
           "scene_transition"},
    "bgfx": {"new_stimulus", "comedy_escalation", "action_impact", "scene_transition"},
    "shake": {"comedy_escalation", "action_impact"},
    "move": {"new_stimulus", "relation_shift", "action_impact", "scene_transition"},
    "shot": {"action_impact"},
    "bg": {"scene_transition", "new_stimulus"},
    "bg_request": {"scene_transition", "new_stimulus"},
    "place": {"scene_transition", "new_stimulus"},
    "trans": {"scene_transition"},
    "camera": {"new_stimulus", "relation_shift", "emotional_shift", "listener_reaction",
               "group_sync", "comedy_escalation", "action_impact", "scene_transition"},
}


def _normalized_story_type(value: Any) -> str:
    value = str(value or "other").strip().lower()
    return value if value in {"main", "event", "bond"} else "other"


def _normalized_function(value: Any) -> str:
    value = str(value or "dialogue").strip().lower()
    return value if value in FUNCTION_BUDGETS else "dialogue"


def direction_budget(scene_type: Any, scene_function: Any) -> Dict[str, int]:
    """Return the canonical automatic budget for one 12-line window."""
    function = _normalized_function(scene_function)
    result = dict(FUNCTION_BUDGETS[function])
    for field, multiplier in STORY_MULTIPLIERS.get(_normalized_story_type(scene_type), {}).items():
        result[field] = max(0, int(math.ceil(result.get(field, 0) * multiplier)))
    return result


def prompt_policy(story_type: Any = "auto") -> str:
    """Render the same policy data as a compact instruction for the model."""
    story = _normalized_story_type(story_type)
    rows = []
    for name in (
        "establishing", "entrance", "exposition", "dialogue",
        "comedy_escalation", "conflict", "emotional_turn", "action", "closing",
    ):
        budget = direction_budget(story, name)
        rows.append(
            f"- {name}: face变化<={budget['face']}, emo<={budget['emo']}, act<={budget['act']}, "
            f"heavy(fx/bgfx/shake)<={budget['heavy']}, camera<={budget['camera']}, "
            f"beat<={budget['beat']}"
        )
    return (
        "# 最小充分演出预算\n\n"
        f"以下是每 12 行对白的自动标注上限（当前剧情类型 {story}）；它是上限，不是配额，"
        "没有证据时应为 0。用户原文已有标注不计入模型任务。\n"
        + "\n".join(rows)
        + "\n普通 dialogue 默认安静：大多数行不加 emo/act/fx/bgfx/shake，不逐行换镜头或重复 face。"
          "瞬时层必须由 direction.reason 说明新刺激、关系/情绪变化、听者反应、喜剧升级或动作冲击；"
          "continuity=hold 表示保持状态，不能把同一素材再输出一次。"
    )


def _director(item: Mapping[str, Any]) -> Mapping[str, Any]:
    value = item.get("_director")
    return value if isinstance(value, Mapping) else {}


def _intent(item: Mapping[str, Any]) -> Mapping[str, Any]:
    value = item.get("_director_intent")
    return value if isinstance(value, Mapping) else {}


def _record_drop(item: MutableMapping[str, Any], field: str, value: Any, reason: str) -> None:
    item.setdefault("_direction_drops", []).append({
        "field": field, "value": value, "reason": reason,
    })


def _drop_field(item: MutableMapping[str, Any], field: str, reason: str) -> None:
    value = item.pop(field, None)
    origins = item.get("_direction_origins")
    if isinstance(origins, MutableMapping):
        origins.pop(field, None)
    if value not in (None, "", 0, False):
        _record_drop(item, field, value, reason)


def _has_evidence(item: Mapping[str, Any], field: str) -> bool:
    raw_intent = item.get("_director_intent")
    if not isinstance(raw_intent, Mapping):
        return True  # compatibility path for the older stateless annotator
    intent = raw_intent
    director = _director(item)
    function = _normalized_function(director.get("scene_function"))
    reason = str(director.get("reason") or "none")
    continuity = director.get("continuity")
    command = continuity.get(field, "none") if isinstance(continuity, Mapping) else "none"
    if command in {"start", "escalate", "end"}:
        return True
    if reason in FIELD_REASONS.get(field, set()):
        return True
    if field in {"bg", "bg_request", "place", "trans"} and function in {"establishing", "closing"}:
        return True
    return False


def _boundary(raw: Any) -> bool:
    value = str(raw or "").strip()
    return (
        value == "---"
        or bool(re.match(r"^#{1,6}\s+", value))
        or bool(re.match(r"^@(bg|place)\b", value, re.IGNORECASE))
    )


def normalize_direction_plan(
    items: Sequence[MutableMapping[str, Any]],
    beats: Sequence[Mapping[str, Any]] = (),
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Enforce evidence, continuity and budgets across the final direction plan."""
    counts: Dict[str, int] = defaultdict(int)
    last_face: Dict[str, str] = {}
    last_camera: tuple[str, ...] | None = None
    line_in_window = 0
    window_id = 0
    diagnostics: list[Dict[str, Any]] = []

    def reset_window(*, reset_state: bool = False) -> None:
        nonlocal counts, last_camera, line_in_window, window_id
        counts = defaultdict(int)
        line_in_window = 0
        window_id += 1
        if reset_state:
            last_face.clear()
            last_camera = None

    for item in items:
        if item.get("kind") != "line":
            if _boundary(item.get("raw")):
                reset_window(reset_state=True)
            continue
        director = _director(item)
        if line_in_window and str(director.get("reason") or "") == "scene_transition":
            reset_window(reset_state=True)
            item["_camera_reset"] = True
        if line_in_window >= WINDOW_LINES:
            reset_window()
        item["_direction_policy_window"] = window_id
        line_in_window += 1
        scene_type = director.get("scene_type") or "other"
        scene_function = _normalized_function(director.get("scene_function"))
        budget = direction_budget(scene_type, scene_function)
        explicit = set(item.get("_explicit_direction_fields", ()))
        explicit_directives = set(item.get("_explicit_directives", ()))
        for directive in set(item.get("_explicit_directive_starts", ())):
            field = "camera" if directive in {"camera", "camera_hold"} else directive
            if field in budget:
                counts[field] += 1
                if field in HEAVY_FIELDS:
                    counts["heavy"] += 1

        for field in (
            "face", "emo", "act", "fx", "se", "bg", "bg_request", "place",
            "shake", "bgfx", "trans", "move", "shot",
        ):
            value = item.get(field)
            if value in (None, "", 0, False):
                continue
            authored = field in explicit
            if field == "face":
                who = str(item.get("who") or "")
                changed = last_face.get(who) != str(value)
                if not authored and not changed:
                    _drop_field(item, field, "redundant_state_restatement")
                    continue
                if not authored and last_face.get(who) and not _has_evidence(item, field):
                    _drop_field(item, field, "missing_direction_evidence")
                    continue
                if not authored and counts["face"] >= budget[field]:
                    _drop_field(item, field, "scene_function_budget")
                    continue
                last_face[who] = str(value)
                if changed:
                    counts["face"] += 1
                continue

            if authored:
                counts[field] += 1
                if field in HEAVY_FIELDS:
                    counts["heavy"] += 1
                continue
            if field in FIELD_REASONS and not _has_evidence(item, field):
                _drop_field(item, field, "missing_direction_evidence")
                continue
            if counts[field] >= budget.get(field, 0):
                _drop_field(item, field, "scene_function_budget")
                continue
            if field in HEAVY_FIELDS and counts["heavy"] >= budget["heavy"]:
                _drop_field(item, field, "heavy_effect_budget")
                continue
            counts[field] += 1
            if field in HEAVY_FIELDS:
                counts["heavy"] += 1

        intent = item.get("_director_intent")
        if isinstance(intent, MutableMapping) and explicit_directives & {"camera", "camera_hold"}:
            intent.pop("visible_characters", None)
            last_camera = None
            if "camera" in explicit_directives:
                item["_camera_reset"] = True
            else:
                item.pop("_camera_reset", None)
        if isinstance(intent, MutableMapping) and "visible_characters" in intent:
            camera = tuple(str(name) for name in director.get("visible_characters", []) if str(name))
            if camera == last_camera:
                intent.pop("visible_characters", None)
                _record_drop(item, "camera", list(camera), "redundant_camera_restatement")
            elif not _has_evidence(item, "camera"):
                intent.pop("visible_characters", None)
                _record_drop(item, "camera", list(camera), "missing_direction_evidence")
            elif counts["camera"] >= budget["camera"]:
                intent.pop("visible_characters", None)
                _record_drop(item, "camera", list(camera), "scene_function_budget")
            else:
                counts["camera"] += 1
                last_camera = camera
                item.pop("_camera_reset", None)

    by_id = {
        str(item.get("annotation_id") or ""): item
        for item in items if item.get("kind") == "line"
    }
    beat_counts: Dict[tuple[int, str], int] = defaultdict(int)
    seen_anchors: set[tuple[str, str, str]] = set()
    kept_beats: list[Dict[str, Any]] = []
    for beat in beats or ():
        anchor_id = str(beat.get("anchor_id") or "")
        anchor = by_id.get(anchor_id)
        if not anchor:
            continue
        director = _director(anchor)
        budget = direction_budget(director.get("scene_type"), director.get("scene_function"))
        key = (int(anchor.get("_direction_policy_window") or 0), _normalized_function(director.get("scene_function")))
        signature = (anchor_id, str(beat.get("position") or ""), str(beat.get("who") or ""))
        if signature in seen_anchors or beat_counts[key] >= budget["beat"]:
            diagnostics.append({
                "code": "director_policy_drop", "level": "info", "field": "beat",
                "source_id": anchor_id, "reason": "scene_function_budget",
            })
            continue
        seen_anchors.add(signature)
        beat_counts[key] += 1
        kept_beats.append(dict(beat))

    for item in items:
        item.pop("_direction_policy_window", None)
        for drop in item.get("_direction_drops", []):
            diagnostics.append({
                "code": "director_policy_drop", "level": "info",
                "source_id": str(item.get("annotation_id") or ""),
                "field": str(drop.get("field") or ""),
                "reason": str(drop.get("reason") or ""),
            })
    return kept_beats, diagnostics
