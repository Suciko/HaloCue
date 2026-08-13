# -*- coding: utf-8 -*-
"""Shared direction policy for model prompting and deterministic restraint."""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, MutableMapping, Sequence


def _normalized_story_type(value: Any) -> str:
    value = str(value or "other").strip().lower()
    return value if value in {"main", "event", "bond"} else "other"


def prompt_policy(story_type: Any = "auto") -> str:
    """Describe semantic density guidance without numeric directing quotas."""
    story = _normalized_story_type(story_type)
    return (
        "# 分层演出密度\n\n"
        f"当前剧情类型为 {story}。不要按固定次数、比例或每 N 行配额安排演出；"
        "根据整段反应链决定每个变化，并让安静段、推进段、爆点和余波形成强弱对比。"
        "用户原文已有标注优先，不要覆盖。\n"
        "face 是人物持续表演层，必须在每次立绘角色发言时重新判断；它不与 emo/act/fx 等瞬时强调共用稀疏原则。"
          "普通 dialogue 默认安静，是指大多数行不加 emo/act/fx/bgfx/shake，也不逐行换镜头；不是让人物长时间保持一张脸。"
          "同一 face 不重复输出；换 face 必须与语气、态度、潜台词或反应阶段相符。"
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
    """Enforce resource-independent evidence and continuity invariants."""
    last_face: Dict[str, str] = {}
    last_scene_state: Dict[str, str] = {}
    established_scene_fields: set[str] = set()
    last_camera: tuple[str, ...] | None = None
    diagnostics: list[Dict[str, Any]] = []

    def reset_scene() -> None:
        nonlocal last_camera
        last_face.clear()
        last_camera = None
        established_scene_fields.clear()

    for item in items:
        if item.get("kind") != "line":
            if _boundary(item.get("raw")):
                reset_scene()
            continue
        director = _director(item)
        if str(director.get("reason") or "") == "scene_transition":
            reset_scene()
            item["_camera_reset"] = True
        explicit = set(item.get("_explicit_direction_fields", ()))
        explicit_directives = set(item.get("_explicit_directives", ()))

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
                last_face[who] = str(value)
                continue

            if field in {"bg", "place"} and not authored:
                normalized_value = str(value)
                if last_scene_state.get(field) == normalized_value:
                    _drop_field(item, field, "redundant_state_restatement")
                    continue
                if field not in established_scene_fields:
                    # A scene boundary creates a fresh establishing slot. The
                    # first valid background/place is structural scene state,
                    # so it must not be discarded merely because the model's
                    # per-line reason was sparse or inherited.
                    established_scene_fields.add(field)
                    last_scene_state[field] = normalized_value
                    continue

            if authored:
                if field in {"bg", "place"}:
                    established_scene_fields.add(field)
                    last_scene_state[field] = str(value)
                continue
            if field in {"bg", "place"}:
                established_scene_fields.add(field)
                last_scene_state[field] = str(value)

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
            else:
                last_camera = camera
                item.pop("_camera_reset", None)
        if (
            last_camera is not None
            and item.get("_speaker_has_portrait")
            and str(item.get("who") or "") not in last_camera
        ):
            # Official portrait dialogue keeps the speaker visible. A listener
            # focus may use a two-shot, but it must not turn ordinary portrait
            # dialogue into an off-screen voice merely because the next row
            # omitted a new camera decision.
            if isinstance(intent, MutableMapping):
                intent.pop("visible_characters", None)
            item["_camera_reset"] = True
            last_camera = None

    by_id = {
        str(item.get("annotation_id") or ""): item
        for item in items if item.get("kind") == "line"
    }
    seen_anchors: set[tuple[str, str, str]] = set()
    kept_beats: list[Dict[str, Any]] = []
    for beat in beats or ():
        anchor_id = str(beat.get("anchor_id") or "")
        anchor = by_id.get(anchor_id)
        if not anchor:
            continue
        signature = (anchor_id, str(beat.get("position") or ""), str(beat.get("who") or ""))
        if signature in seen_anchors:
            diagnostics.append({
                "code": "director_policy_drop", "level": "info", "field": "beat",
                "source_id": anchor_id, "reason": "duplicate_reaction_beat",
            })
            continue
        seen_anchors.add(signature)
        kept_beats.append(dict(beat))

    for item in items:
        for drop in item.get("_direction_drops", []):
            diagnostics.append({
                "code": "director_policy_drop", "level": "info",
                "source_id": str(item.get("annotation_id") or ""),
                "field": str(drop.get("field") or ""),
                "reason": str(drop.get("reason") or ""),
            })
    return kept_beats, diagnostics
