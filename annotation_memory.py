"""Versioned memory, retrieval and checkpoints for the annotation Agent."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from annotation_chunks import context_indices


SCHEMA_VERSION = 3
STORY_TYPES = {"auto", "main", "event", "bond"}
TRANSIENT_BGFX = {"集中线", "闪白", "闪电", "传送", "BG_FocusLine", "BG_Flash", "BG_Flash_Sound", "BG_Teleport"}
SHOT_OPERATION_VALUES = {
    "continue_group", "expand_group", "shrink_group", "replace_center_subject",
    "switch_group", "impact_insert",
}
SHOT_GROUP_STATUSES = {"active", "suspended", "closed"}
REACTION_PHASES = {"cue", "group_reaction", "focus_handoff", "action", "result", "aftershock", "resolved"}


def _story_type(value: Any) -> str:
    normalized = str(value or "auto").strip().lower()
    return normalized if normalized in STORY_TYPES else "auto"


def initial_memory(story_summary: str = "", story_type: str = "auto") -> Dict[str, Any]:
    normalized_story_type = _story_type(story_type)
    return {
        "schema_version": SCHEMA_VERSION,
        "story": {
            "summary": str(story_summary or ""), "type": normalized_story_type,
            "relationships": {}, "open_threads": [],
        },
        "scene": {
            "id": "", "location": "", "time": "", "purpose": "", "mood": "", "summary": "",
            "scene_type": normalized_story_type if normalized_story_type != "auto" else "other",
            "active_modes": [normalized_story_type] if normalized_story_type != "auto" else [],
            "scene_function": "dialogue", "mode_source": "user" if normalized_story_type != "auto" else "unknown",
        },
        "direction": {
            "background": None, "place": None, "bgfx": None,
            "visible_characters": [], "shot_visible_characters": [],
            "scene_presence": {},
            "positions": {}, "last_faces": {},
            "shot_operation": "",
            "shot_transition": "",
            "shot_group": {
                "group_id": "", "members": [], "anchor_stimulus": "",
                "interaction_topic": "", "focus_owner": "", "spatial_mode": "stable", "status": "closed",
            },
            "reaction_chain": {
                "stimulus_id": "", "phase": "resolved", "participants": [],
                "primary_responder": "", "resolved": True,
            },
            "last_performance_node": {},
            "recent_emoticons": [], "recent_actions": [], "recent_sounds": [],
            "focus": {"kind": "speaker", "character": ""},
            "relation_distance": "normal", "emotion_phase": "", "subtext": "",
            "reaction_target": "", "continuity": {},
        },
        "events": [],
        "progress": {"completed_chunks": [], "completed_target_ids": [], "next_scene_id": ""},
    }


def _bounded_strings(values: Any, limit: int = 12) -> List[str]:
    if not isinstance(values, list):
        return []
    return [str(value)[:160] for value in values if str(value or "").strip()][-limit:]


def _allowed_recent(values: Any, allowed: Any, aliases: Mapping[str, str] = {}) -> List[str]:
    legal = set(allowed or [])
    return [
        aliases.get(value, value)
        for value in _bounded_strings(values, 12)
        if value in legal
    ][-12:]


def apply_state_delta(memory: Mapping[str, Any], delta: Mapping[str, Any], *, cast: Mapping[str, Any], constraints: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a validated copy with persistent direction updates applied."""
    updated = copy.deepcopy(dict(memory))
    direction = updated.setdefault("direction", {})
    delta = dict(delta or {})
    background = str(delta.get("background") or "").strip()
    if background and background in set(constraints.get("ok_bg") or []):
        direction["background"] = background
    place = str(delta.get("place") or "").strip()
    if place:
        direction["place"] = place[:80]
    bgfx = str(delta.get("bgfx") or "").strip()
    if bgfx and bgfx in set(constraints.get("ok_bgfx") or []):
        direction["bgfx"] = None if bgfx in TRANSIENT_BGFX else bgfx[:80]

    valid_people = set(cast)
    if "scene_presence" in delta and isinstance(delta.get("scene_presence"), Mapping):
        presence = dict(direction.get("scene_presence") or {})
        for name, status in delta["scene_presence"].items():
            if name in valid_people and status in {"unknown", "present", "absent"}:
                presence[name] = status
        direction["scene_presence"] = presence
    if "visible_characters" in delta:
        direction["shot_visible_characters"] = [
            name for name in _bounded_strings(delta.get("visible_characters"), 8)
            if name in valid_people
        ][:3]
        direction.pop("visible_characters", None)
    positions = delta.get("positions")
    if isinstance(positions, dict):
        direction["positions"] = {
            name: int(value) for name, value in positions.items()
            if name in valid_people and isinstance(value, int) and 1 <= value <= 5
        }
    faces = delta.get("last_faces")
    if isinstance(faces, dict):
        current = dict(direction.get("last_faces") or {})
        for name, face in faces.items():
            character = cast.get(name) if isinstance(cast, dict) else None
            ident = character.get("id") if isinstance(character, dict) else None
            allowed = (constraints.get("faces_by_id") or {}).get(ident, set())
            evidence_by_id = constraints.get("face_evidence_by_id")
            evidence = (
                (evidence_by_id.get(ident) or {}).get(str(face), "unknown")
                if isinstance(evidence_by_id, Mapping) else "visual_confirmed"
            )
            displayable = bool(
                isinstance(character, Mapping)
                and character.get("portrait")
                and not character.get("narrator")
            )
            if (
                name in valid_people and displayable
                and str(face) in set(allowed or [])
                and evidence in {"visual_confirmed", "asset_semantic"}
            ):
                current[name] = str(face)
        direction["last_faces"] = current
    if "recent_emoticons" in delta:
        direction["recent_emoticons"] = _allowed_recent(
            delta.get("recent_emoticons"), constraints.get("ok_emo"),
            constraints.get("sym2cn") or {},
        )
    if "recent_actions" in delta:
        direction["recent_actions"] = _allowed_recent(
            delta.get("recent_actions"), constraints.get("ok_act"),
        )
    if "recent_sounds" in delta:
        direction["recent_sounds"] = _allowed_recent(
            delta.get("recent_sounds"), constraints.get("ok_se"),
        )
    if "open_threads" in delta:
        updated.setdefault("story", {})["open_threads"] = _bounded_strings(delta.get("open_threads"), 20)
    if "shot_group" in delta and isinstance(delta.get("shot_group"), Mapping):
        raw_group = delta["shot_group"]
        members = [name for name in _bounded_strings(raw_group.get("members"), 3) if name in valid_people]
        status = str(raw_group.get("status") or "closed")
        spatial_mode = str(raw_group.get("spatial_mode") or "stable")
        if status not in SHOT_GROUP_STATUSES:
            status = "closed"
        if spatial_mode not in {"stable", "reframe", "insert"}:
            spatial_mode = "stable"
        focus_owner = str(raw_group.get("focus_owner") or "")[:80]
        if focus_owner not in members:
            focus_owner = ""
        direction["shot_group"] = {
            "group_id": str(raw_group.get("group_id") or "")[:80],
            "members": members,
            "anchor_stimulus": str(raw_group.get("anchor_stimulus") or "")[:160],
            "interaction_topic": str(raw_group.get("interaction_topic") or "")[:160],
            "focus_owner": focus_owner,
            "spatial_mode": spatial_mode,
            "status": status,
        }
    if "reaction_chain" in delta and isinstance(delta.get("reaction_chain"), Mapping):
        raw_chain = delta["reaction_chain"]
        participants = [name for name in _bounded_strings(raw_chain.get("participants"), 3) if name in valid_people]
        phase = str(raw_chain.get("phase") or "resolved")
        if phase not in REACTION_PHASES:
            phase = "resolved"
        primary = str(raw_chain.get("primary_responder") or "")[:80]
        if primary not in participants:
            primary = ""
        direction["reaction_chain"] = {
            "stimulus_id": str(raw_chain.get("stimulus_id") or "")[:80],
            "phase": phase,
            "participants": participants,
            "primary_responder": primary,
            "resolved": bool(raw_chain.get("resolved", phase == "resolved")),
        }
    return updated


def complete_scene(
    memory: Mapping[str, Any], scene: Mapping[str, Any], summary: str,
    *, cast_names: Iterable[str] = (),
) -> Dict[str, Any]:
    updated = copy.deepcopy(dict(memory))
    previous_scene_type = str((updated.get("scene") or {}).get("scene_type") or "other")
    updated["scene"] = {
        "id": str(scene.get("scene_id") or ""),
        "location": str(scene.get("location") or ""),
        "time": str(scene.get("time") or ""),
        "purpose": str(scene.get("purpose") or ""),
        "mood": str(scene.get("mood") or ""),
        "summary": str(summary or "")[:1200],
        "scene_type": str(scene.get("scene_type") or previous_scene_type)[:32],
        "active_modes": _bounded_strings(scene.get("active_modes"), 3),
        "scene_function": str(scene.get("scene_function") or "dialogue")[:32],
        "mode_source": str(scene.get("mode_source") or "inferred")[:32],
    }
    direction = updated.setdefault("direction", {})
    direction.update({
        "background": None, "place": None, "bgfx": None,
        "visible_characters": [], "shot_visible_characters": [],
        "positions": {}, "last_faces": {},
        "scene_presence": {
            str(name): "unknown" for name in cast_names if str(name)
        },
        "shot_operation": "", "shot_transition": "",
        "shot_group": {
            "group_id": "", "members": [], "anchor_stimulus": "",
            "interaction_topic": "", "focus_owner": "", "spatial_mode": "stable", "status": "closed",
        },
        "reaction_chain": {
            "stimulus_id": "", "phase": "resolved", "participants": [],
            "primary_responder": "", "resolved": True,
        },
        "last_performance_node": {},
        "recent_emoticons": [], "recent_actions": [], "recent_sounds": [],
        "focus": {"kind": "speaker", "character": ""},
        "relation_distance": "normal", "emotion_phase": "", "subtext": "",
        "reaction_target": "", "continuity": {},
    })
    return updated


def _line_record(label: str, item: Mapping[str, Any], index: int = 0, *, compact: bool = False) -> str:
    marker = str(index) if compact and index else str(item.get("annotation_id"))
    suffix = "" if compact else f" | fingerprint={item.get('text_fingerprint')}"
    authored = [str(field) for field in item.get("_explicit_direction_fields", ()) if str(field)]
    if authored:
        suffix += " | authored=" + ",".join(authored)
    return f"[{label} {marker}] {item.get('who')}: {item.get('text')}{suffix}"


def _annotation_scene_context(
    usage_chain: Sequence[Mapping[str, Any]], targets: Sequence[int],
    items: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Project the UI/preflight plan into a small annotation-only context."""
    if not usage_chain:
        return []
    line_numbers = [int(items[index].get("line_no") or 0) for index in targets]
    target_start = min(line_numbers) if line_numbers else 0
    target_end = max(line_numbers) if line_numbers else target_start

    def number(value: Any) -> Optional[int]:
        match = re.search(r"\d+", str(value or ""))
        return int(match.group()) if match else None

    rows = [entry for entry in usage_chain if isinstance(entry, Mapping)]
    current = []
    for index, entry in enumerate(rows):
        start = number(entry.get("start"))
        end = number(entry.get("end")) or start
        if start is not None and start <= target_end and max(start, end or start) >= target_start:
            current.append(index)
    selected_indices = set()
    for index in current:
        selected_indices.update((index - 1, index, index + 1))
    if not selected_indices:
        selected_indices.update(range(min(2, len(rows))))
    allowed = {
        "segment", "start", "end", "location", "time", "scene_type",
        "active_modes", "scene_function", "reason", "needs", "required", "background",
        "bg", "se", "bgm", "aa_key",
    }

    def project(entry: Mapping[str, Any]) -> Dict[str, Any]:
        result = {}
        for key, value in entry.items():
            if key not in allowed:
                continue
            if key == "needs" and isinstance(value, list):
                result[key] = [
                    {
                        need_key: need_value
                        for need_key, need_value in need.items()
                        if need_key in {"kind", "name", "status", "aa_key", "location", "required"}
                    }
                    for need in value[:12]
                    if isinstance(need, Mapping)
                ]
            elif isinstance(value, str):
                result[key] = value[:240]
            else:
                result[key] = value
        return result

    return [
        project(rows[index])
        for index in sorted(selected_indices)
        if 0 <= index < len(rows)
    ]


def assemble_chunk_context(
    items: Sequence[Mapping[str, Any]], chunk: Mapping[str, Any], memory: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]], usage_chain: Sequence[Mapping[str, Any]], *,
    before: int = 15, after: int = 10, max_events: int = 8, compact: bool = False,
    story_type: str = "auto", scene_event_plan: Mapping[str, Any] | None = None,
    cast: Mapping[str, Any] | None = None,
    constraints: Mapping[str, Any] | None = None,
) -> Tuple[str, str]:
    dialogue = [i for i, item in enumerate(items) if item.get("kind") == "line"]
    past, future = context_indices(dialogue, dict(chunk), before=before, after=after)
    targets = list(chunk.get("target_indices") or [])
    selected = list(events)[:max_events]
    direction = memory.get("direction") or {}
    scene = memory.get("scene") or {}
    focus = direction.get("focus") if isinstance(direction.get("focus"), Mapping) else {}
    continuity = direction.get("continuity") if isinstance(direction.get("continuity"), Mapping) else {}
    normalized_story_type = _story_type(story_type)
    director_context = {
        "story_type": normalized_story_type,
        "scene_type": str(scene.get("scene_type") or (
            normalized_story_type if normalized_story_type != "auto" else "other"
        ))[:32],
        "active_modes": _bounded_strings(scene.get("active_modes"), 3),
        "scene_function": str(scene.get("scene_function") or "dialogue")[:32],
        "mode_source": str(scene.get("mode_source") or "unknown")[:32],
        "focus": {
            "kind": str(focus.get("kind") or "speaker")[:32],
            "character": str(focus.get("character") or "")[:160],
        },
        "relation_distance": str(direction.get("relation_distance") or "normal")[:32],
        "shot_operation": str(direction.get("shot_operation") or "")[:32],
        "shot_transition": str(direction.get("shot_transition") or "")[:32],
        "emotion_phase": str(direction.get("emotion_phase") or "")[:160],
        "subtext": str(direction.get("subtext") or "")[:160],
        "reaction_target": str(direction.get("reaction_target") or "")[:160],
        "continuity": {
            name: str(continuity.get(name) or "")[:160]
            for name in ("face", "emo", "act", "fx", "bgfx")
            if name in continuity
        },
        "visible_characters": _bounded_strings(
            direction.get("shot_visible_characters", direction.get("visible_characters")), 8
        ),
        "shot_group": dict(direction.get("shot_group") or {}),
        "reaction_chain": dict(direction.get("reaction_chain") or {}),
    }
    positions = direction.get("positions") if isinstance(direction.get("positions"), Mapping) else {}
    direction_snapshot = {
        "background": str(direction.get("background") or "")[:160],
        "place": str(direction.get("place") or "")[:80],
        "bgfx": str(direction.get("bgfx") or "")[:80],
        "visible_characters": _bounded_strings(
            direction.get("shot_visible_characters", direction.get("visible_characters")), 8
        ),
        "scene_presence": {
            str(name)[:160]: str(status)
            for name, status in dict(direction.get("scene_presence") or {}).items()
            if status in {"unknown", "present", "absent"}
        },
        "positions": {
            str(name)[:160]: value for name, value in positions.items()
            if isinstance(value, int)
        },
        "last_faces": {
            str(name)[:160]: str(value)[:32]
            for name, value in dict(direction.get("last_faces") or {}).items()
        },
        "shot_operation": str(direction.get("shot_operation") or "")[:32],
        "shot_transition": str(direction.get("shot_transition") or "")[:32],
        "shot_group": dict(direction.get("shot_group") or {}),
        "reaction_chain": dict(direction.get("reaction_chain") or {}),
        "last_performance_node": dict(direction.get("last_performance_node") or {}),
        "recent_emoticons": _bounded_strings(direction.get("recent_emoticons"), 8),
        "recent_actions": _bounded_strings(direction.get("recent_actions"), 8),
        "recent_sounds": _bounded_strings(direction.get("recent_sounds"), 8),
    }
    # Put the current decision order before resource candidates. The complete
    # rules stay cacheable, while this short block keeps the model focused on
    # event causality and shot space before it starts choosing assets.
    volatile_parts = [
        "CURRENT_DIRECTING_TASK\n"
        "先按事件因果和当前拍摄小组决定画面，再选 face/emo/act/fx。"
        "逐 TARGET 比较最近一个实际演出节点；该节点可以是对白或无对白 beat。"
        "先判断阶段变化是否有因果价值；有价值时主动选择至少一个自然的可见承载，"
        "没有变化时保持状态并使用有语义依据的 hold。"
        "镜头变化必须给出完整构图；普通保持不重复声明。"
        "只有真实入退场才 enter/exit；连续镜头中的立绘显隐用 reveal/conceal，普通情况淡入淡出；move 必须先落地再 cut。"
        "对白镜头可给说话者、听者反应或关系构图；不能因为台词强制同框。单镜最多三人，Wait 只用于无对话框 beat。"
        "计划是软导演假设；所选 carrier 有准确资源时用它兑现。"
        "计划的 action 没有语义准确的动作资源时，改用准确的 face/emo/camera/sound，不能为兑现计划选错 act。"
        "没有选择表演意图时不要为了配额补齐，无法确定的审美选择交给 AI。",
        "CURRENT_STORY_MEMORY\n" + json.dumps(memory.get("story") or {}, ensure_ascii=False, separators=(",", ":")),
        "CURRENT_SCENE_MEMORY\n" + json.dumps(memory.get("scene") or {}, ensure_ascii=False, separators=(",", ":")),
        "CURRENT_DIRECTION_STATE\n" + json.dumps(direction_snapshot, ensure_ascii=False, separators=(",", ":")),
        "DIRECTOR_CONTEXT\n" + json.dumps(director_context, ensure_ascii=False, separators=(",", ":")),
    ]
    from prompt import scene_mode_policy
    volatile_parts.append(scene_mode_policy(
        director_context["scene_type"], director_context["active_modes"],
    ))
    scene_context = _annotation_scene_context(usage_chain, targets, items)
    if scene_context:
        volatile_parts.append(
            "CONFIRMED_SCENE_PLAN\n"
            + json.dumps(scene_context, ensure_ascii=False, separators=(",", ":"))
        )
    volatile_parts.append("RELEVANT_MEMORY_EVENTS\n" + json.dumps(selected, ensure_ascii=False, separators=(",", ":")))
    if scene_event_plan:
        from annotation_scene_planner import project_scene_event_plan

        target_ids = [str(items[index].get("annotation_id") or "") for index in targets]
        projected = project_scene_event_plan(scene_event_plan, target_ids)
        if projected.get("active_events"):
            volatile_parts.append(
                "SCENE_EVENT_PLAN\n"
                + json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
                + "\n先遵守事件因果和拍摄小组，再选择逐行资源；不要把计划退化成按说话者换镜。\n"
                "本块按同一顺序联合决策：①确认当前 event、互动轴和 shot_group 保持区间；"
                "②从 CURRENT_DIRECTION_STATE 推演 cut/reframe/reveal/conceal/enter/exit/move 后的完整空间；"
                "③逐角色比较 face_arc、上一张脸和当前候选；context_role=previous/next 只供连续性参考，"
                "若没有语义更合适的新脸则保持并用其他表演载体承载变化；"
                "④performance_intents 是软导演假设：优先用语义准确的 carrier 兑现；"
                "若 action 没有准确资源，用 face/emo/camera/sound 等准确载体表达，而不选错 act；"
                "只有 require_all=true 且每层都有准确资源时才全部兑现，再判断正文支持的额外动作或气泡；"
                "⑤只在计划的 silent_beat 上生成无对话框节点并按实际展示需要填写 wait_ms；"
                "⑥复核峰值释放、镜头意图明确、同镜不超过三人和立绘不重叠。"
                "这是决策顺序，不是镜头、动作、气泡或 Wait 的数量配额。"
            )
    if cast and constraints:
        from face_selection import silent_reaction_shortlists, target_face_shortlists

        face_shortlists = target_face_shortlists(
            items,
            targets,
            cast=cast,
            constraints=constraints,
            last_faces=direction.get("last_faces") or {},
            scene_event_plan=scene_event_plan,
            include_all=True,
        )
        if face_shortlists:
            public_shortlists = []
            for entry in face_shortlists:
                current_face = str(entry.get("previous_face") or "")
                public_shortlists.append({
                    key: value for key, value in entry.items() if key != "candidates"
                } | {
                    "candidates": [
                        {
                            "choice": str(candidate.get("token") or ""),
                            "face_id": str(candidate.get("id") or ""),
                            "semantic": str(candidate.get("semantic") or ""),
                            "is_current": bool(
                                current_face
                                and str(candidate.get("id") or "") == current_face
                            ),
                        }
                        for candidate in entry.get("candidates") or []
                        if str(candidate.get("token") or "")
                        and str(candidate.get("id") or "")
                    ],
                })
            volatile_parts.append(
                "FACE_SHORTLIST_BY_TARGET\n"
                + json.dumps(public_shortlists, ensure_ascii=False, separators=(",", ":"))
                + "\n这是表情标注后端按当前台词排序的完整安全候选。"
                "候选前部是相关性建议，但列表包含当前角色和装束下全部已验证语义表情；"
                "face 只能原样填写对应 candidate.choice；face_id 是真实物理表情，semantic 是完整含义，"
                "is_current 表示它与块开始时的当前表情相同。AI 负责结合潜台词最终择一，也可以在无需换脸时留空。"
                "当 plan.stage_change=true 时，还要按 TARGET 顺序比较 face_id 与同角色此前最近一次非空选择；"
                "要求真实换脸时不得选择相同 face_id。"
                "若对白或旁白节点使用行级 reactions，reaction.face 只能复用这里展示的该反应角色 candidate.choice；"
                "当前块没有该角色候选时，优先用 reaction.emo/act 或独立 beat，不猜 face 编号。"
            )
        silent_shortlists = silent_reaction_shortlists(
            items,
            targets,
            cast=cast,
            constraints=constraints,
            scene_event_plan=scene_event_plan,
            last_faces=direction.get("last_faces") or {},
            include_all=True,
        )
        if silent_shortlists:
            public_silent = []
            for entry in silent_shortlists:
                public_silent.append({
                    "anchor_i": entry["anchor_i"],
                    "position": entry["position"],
                    "phase": entry["phase"],
                    "purpose": entry["purpose"],
                    "faces": {
                        who: [
                            {
                                "choice": str(candidate.get("token") or ""),
                                "face_id": str(candidate.get("id") or ""),
                                "semantic": str(candidate.get("semantic") or ""),
                                "is_current": bool(
                                    str((direction.get("last_faces") or {}).get(who) or "")
                                    and str(candidate.get("id") or "")
                                    == str((direction.get("last_faces") or {}).get(who) or "")
                                ),
                            }
                            for candidate in candidates
                            if str(candidate.get("token") or "")
                            and str(candidate.get("id") or "")
                        ]
                        for who, candidates in entry.get("faces", {}).items()
                    },
                })
            volatile_parts.append(
                "SILENT_REACTION_SHORTLIST_BY_TARGET\n"
                + json.dumps(public_silent, ensure_ascii=False, separators=(",", ":"))
                + "\n这里只覆盖确实计划了可读情绪反应的无对话框节点。"
                "beat.face 与 reactions.face 只能填写对应 anchor、position 和角色下的 candidate.choice，"
                "也可以在不需要换脸时留空；未列出的无对话框节点不要猜表情。"
                "face_id 与 is_current 用于判断是否发生真实物理变化。"
            )
    body = [
        "Update continuity across lines from DIRECTOR_CONTEXT; do not reset direction state for each line.",
        "只为 TARGET 行输出标注；PAST_CONTEXT 和 FUTURE_CONTEXT 只用于理解，不得标注 FUTURE_CONTEXT。",
        ("响应协议：只返回一个 JSON 对象；lines 使用从 1 开始的 i 对应 TARGET 顺序，只填写有值的演出字段；"
         "没有任何标注或状态变化的 TARGET 行从 lines 中完全省略，由后端自动补为空操作；"
         "不要返回只有 i 的空行，也不要重复 DIRECTOR_CONTEXT 或 continuity=hold；"
         "不复述规则、哈希、原文或候选比较；每行只做一次决策，完成语义判断后立即返回 JSON。"
         if compact else
         "响应协议：只返回一个 JSON 对象，顶层必须有 lines、state_delta、memory_events；可选 beats 只表达独立无台词反应；lines 必须恰好覆盖每个 TARGET，"
         "每项必须复制对应 TARGET 的 source_id 和 text_fingerprint，并只填写演出字段；不要使用旧版 i/speaker/wait 格式。"),
    ]
    body.extend(_line_record("PAST_CONTEXT", items[index], compact=compact) for index in past)
    body.extend(_line_record("TARGET", items[index], position + 1, compact=compact) for position, index in enumerate(targets))
    body.extend(_line_record("FUTURE_CONTEXT", items[index], compact=compact) for index in future)
    return "\n\n".join(volatile_parts), "\n".join(body)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    text = value if isinstance(value, str) else _canonical(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_run_fingerprint(
    script_text: str, cast: Mapping[str, Any], resources: Mapping[str, Any],
    prompt_version: str, schema_version: int, chunk_version: str,
    model_config: Mapping[str, Any], scene_hashes: Optional[Sequence[str]] = None,
    *, story_type: str = "auto", director_version: str = "",
    run_mode: str = "balanced", source_id: str = "",
) -> Dict[str, Any]:
    safe_model = {
        "provider": str(model_config.get("provider") or ""),
        "model": str(model_config.get("model") or ""),
        "runtime_fingerprint_sha256": str(
            model_config.get("runtime_fingerprint_sha256") or ""
        ),
        "max_tokens": int(model_config.get("max_tokens") or 0),
        "annotation_max_tokens": int(model_config.get("annotation_max_tokens") or 0),
        "reasoning_mode": str(model_config.get("reasoning_mode") or ""),
        "reasoning_wire_protocol": str(model_config.get("reasoning_wire_protocol") or ""),
        "source_context_strategy": str(model_config.get("source_context_strategy") or "preserve"),
    }
    return {
        "script_sha256": _sha(script_text), "cast_sha256": _sha(cast),
        "resources_sha256": _sha(resources), "prompt_version": str(prompt_version),
        "schema_version": int(schema_version), "chunk_version": str(chunk_version),
        "story_type": _story_type(story_type), "director_version": str(director_version or ""),
        "run_mode": str(run_mode or "balanced").strip().lower(),
        "source_id": str(source_id or "").strip(),
        "model": safe_model, "scene_hashes": list(scene_hashes or []),
    }


class AnnotationCheckpointStore:
    def __init__(self, root: Any):
        self.root = Path(root)
        self.last_error = ""

    @staticmethod
    def run_key(fingerprint: Mapping[str, Any]) -> str:
        return _sha(fingerprint)[:24]

    def _path(self, run_key: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(run_key))[:80]
        return self.root / safe / "checkpoint.json"

    def load(self, run_key: str) -> Optional[Dict[str, Any]]:
        path = self._path(run_key)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            self.last_error = str(exc)
            return None
        return value if isinstance(value, dict) else None

    def commit(self, run_key: str, state: Mapping[str, Any]) -> Path:
        path = self._path(run_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
        return path

    def resume_plan(self, saved: Mapping[str, Any], current: Mapping[str, Any], scenes: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        saved_fp = saved.get("fingerprint", saved)
        current_fp = current.get("fingerprint", current)
        scene_ids = [str(scene.get("scene_id") or "") for scene in scenes]
        old_hashes = list(saved_fp.get("scene_hashes") or [])
        new_hashes = list(current_fp.get("scene_hashes") or [])
        first_changed = next((i for i, pair in enumerate(zip(old_hashes, new_hashes)) if pair[0] != pair[1]), min(len(old_hashes), len(new_hashes)))
        structural = all(saved_fp.get(key) == current_fp.get(key) for key in (
            "prompt_version", "schema_version", "chunk_version", "director_version",
            "story_type", "model",
        ))
        exact = saved_fp == current_fp
        restart = scene_ids[first_changed] if first_changed < len(scene_ids) else None
        return {
            "reuse_scene_ids": scene_ids[:first_changed], "restart_scene_id": restart,
            "reuse_after_restart": False, "reuse_scene_map": saved_fp.get("schema_version") == current_fp.get("schema_version"),
            "reuse_chunk_results": exact and structural,
        }


def build_story_plan(items: Sequence[Mapping[str, Any]], scenes: Sequence[Mapping[str, Any]], usage_chain: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    speakers = sorted({str(item.get("who") or "") for item in items if item.get("kind") == "line" and item.get("who")})
    planned = []
    chain = [entry for entry in usage_chain or [] if isinstance(entry, Mapping)]

    def line_number(value: Any) -> Optional[int]:
        match = re.search(r"\d+", str(value or ""))
        return int(match.group()) if match else None

    def matching_entry(scene: Mapping[str, Any]) -> Mapping[str, Any]:
        scene_start = int(scene.get("start_line") or 0)
        scene_end = int(scene.get("end_line") or scene_start)
        for entry in chain:
            start = line_number(entry.get("start"))
            end = line_number(entry.get("end")) or start
            if start is not None and start <= scene_end and max(start, end or start) >= scene_start:
                return entry
        return {}

    for index, scene in enumerate(scenes):
        entry = matching_entry(scene)
        planned.append({
            **dict(scene),
            "segment": str(entry.get("segment") or scene.get("segment") or f"场景 {index + 1}"),
            "location": str(entry.get("location") or scene.get("location") or ""),
            "evidence": str(entry.get("evidence") or scene.get("evidence") or scene.get("opening_text") or ""),
            "time": str(entry.get("time") or scene.get("time") or ""),
            "scene_type": str(entry.get("scene_type") or scene.get("scene_type") or "other"),
            "active_modes": list(entry.get("active_modes") or scene.get("active_modes") or []),
            "scene_function": str(entry.get("scene_function") or scene.get("scene_function") or "dialogue"),
            "mode_source": "preflight" if entry.get("scene_type") else "inferred",
            "purpose": str(entry.get("reason") or scene.get("purpose") or ""),
        })
    summary = f"共 {len(planned)} 个场景；出场：{'、'.join(speakers)}。"
    return {"summary": summary, "speakers": speakers, "scenes": planned}


def merge_memory_events(existing: Sequence[Mapping[str, Any]], candidates: Sequence[Mapping[str, Any]], visible_items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {str(item.get("annotation_id") or ""): str(item.get("text") or "") for item in visible_items}
    result = [dict(event) for event in existing]
    keys = {_event_key(event) for event in result}
    for candidate in candidates:
        source_ids = [str(value) for value in candidate.get("source_ids") or []]
        evidence = str(candidate.get("evidence") or "").strip()
        if not source_ids or any(source_id not in by_id for source_id in source_ids):
            continue
        source_text = " ".join(by_id[source_id] for source_id in source_ids)
        if evidence not in source_text and source_text not in evidence:
            continue
        event = dict(candidate)
        event.setdefault("id", f"event-{_sha(event)[:12]}")
        key = _event_key(event)
        if key not in keys:
            result.append(event)
            keys.add(key)
    return result


def _event_key(event: Mapping[str, Any]) -> str:
    return _sha({
        "kind": event.get("kind"), "participants": sorted(event.get("participants") or []),
        "keywords": sorted(event.get("keywords") or []), "source_ids": sorted(event.get("source_ids") or []),
    })


def retrieve_events(events: Sequence[Mapping[str, Any]], items: Sequence[Mapping[str, Any]], scene_id: str, limit: int = 8) -> List[Dict[str, Any]]:
    text = " ".join(str(item.get("text") or "") for item in items)
    speakers = {str(item.get("who") or "") for item in items}
    scored = []
    for event in events:
        keyword_hits = sum(1 for word in event.get("keywords") or [] if str(word) and str(word) in text)
        participant_hits = sum(1 for name in event.get("participants") or [] if str(name) in speakers)
        status_bonus = 3 if event.get("status") == "open" else 0
        scene_bonus = 1 if event.get("scene_id") == scene_id else 0
        score = keyword_hits * 5 + participant_hits * 2 + status_bonus + scene_bonus + float(event.get("importance") or 0)
        scored.append((score, str(event.get("id") or ""), dict(event)))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in scored[:max(0, limit)]]
