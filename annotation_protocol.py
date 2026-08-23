"""Strict, source-identity based protocol for stateful annotation calls."""

from __future__ import annotations

import copy
import re
import json
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Sequence

import tables
from annotation_safety import is_fx_allowed, normalize_emoticon

from director_state import (
    BEAT_REASONS,
    CONTINUITY_STATES,
    DIRECTION_REASONS,
    FOCUS_KINDS,
    RELATION_DISTANCES,
    SHOT_TRANSITIONS,
    SHOT_OPERATIONS,
    SCENE_FUNCTIONS,
    SCENE_TYPES,
    default_director,
    normalize_director,
)


ANNOTATION_FIELDS = (
    "face", "emo", "act", "fx", "se", "bg", "bg_request", "place",
    "shake", "bgfx", "trans", "move", "shot", "reveal",
)
OPTIONAL_LINE_FIELDS = {"reveal"}
LINE_REACTION_FIELDS = {"reactions"}
ANNOTATION_FIELD_TYPES = {
    name: bool if name == "shake" else int if name == "move" else str
    for name in ANNOTATION_FIELDS
}
LINE_REQUIRED_FIELDS = set(ANNOTATION_FIELDS) - OPTIONAL_LINE_FIELDS | {
    "source_id", "text_fingerprint",
}
LINE_FIELDS = LINE_REQUIRED_FIELDS | OPTIONAL_LINE_FIELDS | LINE_REACTION_FIELDS | {"direction"}
STATE_FIELDS = {
    "background", "place", "bgfx", "visible_characters", "positions",
    "last_faces", "recent_emoticons", "recent_actions", "recent_sounds",
    "open_threads", "shot_group", "reaction_chain", "scene_presence",
}
STATE_FIELD_TYPES = {
    "background": str,
    "place": str,
    "bgfx": str,
    "visible_characters": list,
    "positions": dict,
    "last_faces": dict,
    "recent_emoticons": list,
    "recent_actions": list,
    "recent_sounds": list,
    "open_threads": list,
    "shot_group": dict,
    "reaction_chain": dict,
    "scene_presence": dict,
}
EVENT_FIELDS = {
    "kind", "participants", "keywords", "summary", "source_ids",
    "evidence", "importance", "status",
}
BEAT_REQUIRED_FIELDS = {
    "anchor_id", "position", "who", "face", "emo", "act", "wait_ms", "reason",
}
BEAT_STAGE_FIELDS = {
    "beat_id",
    "visible_characters", "positions", "shot_transition", "shot_operation", "reveal", "conceal", "enter", "exit",
    "reactions", "fx", "se", "bg", "place", "trans", "bgfx", "shake",
}
BEAT_FIELDS = BEAT_REQUIRED_FIELDS | BEAT_STAGE_FIELDS
MAX_BEAT_WAIT_MS = 10_000
MAX_MEMORY_EVENTS_PER_CHUNK = 6
CONTINUITY_LAYERS = {"face", "emo", "act", "fx", "bgfx"}
DIRECTION_STRING_FIELDS = {
    "scene_type", "scene_function", "emotion_phase", "subtext",
    "relation_distance", "shot_transition", "focus_kind", "focus_character",
    "reaction_target", "reason", "shot_operation",
}
DIRECTION_FIELDS = DIRECTION_STRING_FIELDS | {
    "visible_characters", "positions", "continuity",
}


class ChunkProtocolError(ValueError):
    def __init__(self, code: str, detail: str, retryable: bool = True):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable


class _ExpandedChunkResponse(dict):
    def __init__(
        self, *args: Any, director_intents: Mapping[str, Any],
        annotation_intents: Mapping[str, Any], **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self.director_intents = dict(director_intents)
        self.annotation_intents = {
            str(source_id): set(fields)
            for source_id, fields in annotation_intents.items()
        }


def _field(name: str, description: str, field_type: str = "string") -> Dict[str, Any]:
    value: Dict[str, Any] = {"type": field_type, "description": description}
    if field_type == "integer":
        value["minimum"] = 0
    return value


def _reaction_schema(description: str) -> Dict[str, Any]:
    """Schema for an explicit visible listener reaction on a timed node."""
    return {
        "type": "object",
        "properties": {
            "who": _field("who", "同步反应的有立绘角色名"),
            "face": _field("face", "该角色的 [Emo:语义]；不改变时填空串"),
            "emo": _field("emo", "该角色的气泡中文名；不使用时填空串"),
            "act": _field("act", "该角色的原地动作英文名；不使用时填空串"),
        },
        "required": ["who", "face", "emo", "act"],
        "additionalProperties": False,
        "description": description,
    }


def _state_properties() -> Dict[str, Any]:
    """Bound state_delta to the same sizes used by the memory reducer."""
    bounded_string = {"type": "string", "maxLength": 160}
    shot_group = {
        "type": ["object", "null"], "additionalProperties": False,
        "properties": {
            "group_id": {"type": "string", "maxLength": 80},
            "members": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 80}},
            "anchor_stimulus": {"type": "string", "maxLength": 160},
            "interaction_topic": {"type": "string", "maxLength": 160},
            "focus_owner": {"type": "string", "maxLength": 80},
            "spatial_mode": {"type": "string", "enum": ["stable", "reframe", "insert"]},
            "status": {"type": "string", "enum": ["active", "suspended", "closed"]},
        },
    }
    reaction_chain = {
        "type": ["object", "null"], "additionalProperties": False,
        "properties": {
            "stimulus_id": {"type": "string", "maxLength": 80},
            "phase": {"type": "string", "enum": ["cue", "group_reaction", "focus_handoff", "action", "result", "aftershock", "resolved"]},
            "participants": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 80}},
            "primary_responder": {"type": "string", "maxLength": 80},
            "resolved": {"type": "boolean"},
        },
    }
    return {
        "background": {"type": ["string", "null"], "maxLength": 160},
        "place": {"type": ["string", "null"], "maxLength": 80},
        "bgfx": {"type": ["string", "null"], "maxLength": 80},
        "visible_characters": {
            "type": ["array", "null"], "maxItems": 3,
            "items": {"type": "string", "maxLength": 80},
        },
        "positions": {
            "type": ["object", "null"], "maxProperties": 3,
            "additionalProperties": {"type": "integer", "minimum": 1, "maximum": 5},
        },
        "last_faces": {
            "type": ["object", "null"], "maxProperties": 12,
            "additionalProperties": {"type": "string", "maxLength": 32},
        },
        "recent_emoticons": {
            "type": ["array", "null"], "maxItems": 12, "items": bounded_string,
        },
        "recent_actions": {
            "type": ["array", "null"], "maxItems": 12, "items": bounded_string,
        },
        "recent_sounds": {
            "type": ["array", "null"], "maxItems": 12, "items": bounded_string,
        },
        "open_threads": {
            "type": ["array", "null"], "maxItems": 20, "items": bounded_string,
        },
        "scene_presence": {
            "type": ["object", "null"],
            "additionalProperties": {
                "type": "string", "enum": ["unknown", "present", "absent"],
            },
        },
        "shot_group": shot_group,
        "reaction_chain": reaction_chain,
    }


def _direction_schema(*, annotation_aliases: bool = False) -> Dict[str, Any]:
    properties: Dict[str, Any] = {
        "scene_type": {"type": "string", "enum": list(SCENE_TYPES)},
        "scene_function": {"type": "string", "enum": list(SCENE_FUNCTIONS)},
        "emotion_phase": {"type": "string", "maxLength": 160},
        "subtext": {"type": "string", "maxLength": 160},
        "relation_distance": {"type": "string", "enum": list(RELATION_DISTANCES)},
        "shot_transition": {"type": "string", "enum": list(SHOT_TRANSITIONS)},
        "focus_kind": {"type": "string", "enum": list(FOCUS_KINDS)},
        "focus_character": {"type": "string"},
        "reaction_target": {"type": "string", "maxLength": 160},
        "visible_characters": {
            "type": "array", "maxItems": 3, "items": {"type": "string"},
        },
        "positions": {
            "type": "object", "maxProperties": 3,
            "additionalProperties": {"type": "integer", "minimum": 1, "maximum": 5},
        },
        "shot_transition": {
            "type": "string", "enum": list(SHOT_TRANSITIONS),
            "description": "cut=整镜硬切并重建完整构图；reframe=同镜重构；字段缺失=保持",
        },
        "shot_operation": {
            "type": "string", "enum": list(SHOT_OPERATIONS),
            "description": "先表达镜头语义操作；后端据此和正文证据映射 cut/reframe",
        },
        "continuity": {
            "type": "object",
            "properties": {
                layer: {"type": "string", "enum": list(CONTINUITY_STATES)}
                for layer in sorted(CONTINUITY_LAYERS)
            },
            "additionalProperties": False,
        },
        "reason": {"type": "string", "enum": list(DIRECTION_REASONS)},
    }
    if annotation_aliases:
        for name in ANNOTATION_FIELDS:
            field_type = "boolean" if name == "shake" else "integer" if name == "move" else "string"
            properties[name] = {"type": field_type}
    return {"type": "object", "properties": properties, "additionalProperties": False}


def _validate_direction_wire(
    value: Any, field: str, *, require_shot_positions: bool = False,
) -> Mapping[str, Any]:
    direction = _require_dict(value, "invalid_line", f"{field} must be an object")
    if not set(direction) <= DIRECTION_FIELDS:
        raise ChunkProtocolError("invalid_line", f"{field} contains unknown fields")
    for name in DIRECTION_STRING_FIELDS:
        if name in direction and not isinstance(direction[name], str):
            raise ChunkProtocolError("invalid_line", f"{field}.{name} must be a string")
    visible = direction.get("visible_characters", [])
    if (
        not isinstance(visible, list)
        or len(visible) > 3
        or any(not isinstance(name, str) for name in visible)
    ):
        raise ChunkProtocolError("invalid_line", f"{field}.visible_characters must be a string array")
    positions = direction.get("positions", {})
    if (
        not isinstance(positions, dict)
        or len(positions) > 3
        or any(not isinstance(name, str) for name in positions)
        or any(
            isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= 5
            for slot in positions.values()
        )
    ):
        raise ChunkProtocolError("invalid_line", f"{field}.positions must map names to slots 1-5")
    if len(set(positions.values())) != len(positions):
        raise ChunkProtocolError("invalid_line", f"{field}.positions cannot reuse an AA slot")
    if "visible_characters" in direction and not set(positions) <= set(visible):
        raise ChunkProtocolError(
            "invalid_line", f"{field}.positions can only contain visible characters",
        )
    shot_transition = str(direction.get("shot_transition") or "")
    if shot_transition in SHOT_TRANSITIONS:
        if "visible_characters" not in direction:
            raise ChunkProtocolError(
                "invalid_line", f"{field}.{shot_transition} requires a complete shot",
            )
        # Dialogue directions may omit numeric slots.  The stage engine owns
        # deterministic safe placement; requiring the model to hand-write
        # slots conflicted with the pure-AI contract and rejected otherwise
        # valid compositions.  Silent beats remain explicit spatial actions.
        if require_shot_positions and "positions" not in direction:
            raise ChunkProtocolError(
                "invalid_line", f"{field}.{shot_transition} requires explicit positions",
            )
        if "positions" in direction and set(positions) != set(visible):
            raise ChunkProtocolError(
                "invalid_line", f"{field}.{shot_transition} positions must cover the full shot",
            )
    continuity = direction.get("continuity", {})
    if not isinstance(continuity, dict) or not set(continuity) <= CONTINUITY_LAYERS:
        raise ChunkProtocolError("invalid_line", f"{field}.continuity has an invalid shape")
    if any(not isinstance(command, str) for command in continuity.values()):
        raise ChunkProtocolError("invalid_line", f"{field}.continuity values must be strings")
    return direction


def _normalized_direction_intent(
    raw: Mapping[str, Any], normalized: Mapping[str, Any],
) -> Dict[str, Any]:
    intent: Dict[str, Any] = {}
    for name in raw:
        if name == "visible_characters":
            intent[name] = list(normalized[name])
        elif name == "continuity":
            intent[name] = {
                layer: normalized[name][layer]
                for layer in raw[name]
                if layer in normalized[name]
            }
        else:
            intent[name] = normalized[name]
    return intent


def _beat_schema_properties(anchor: Mapping[str, Any]) -> Dict[str, Any]:
    reaction = _reaction_schema("同一无对话框节点中共同反应的角色")
    entrance = {
        "type": "object",
        "properties": {
            "who": _field("who", "入场角色名"),
            "slot": {"type": "integer", "minimum": 0, "maximum": 5},
            "side": {"type": "string", "enum": ["auto", "left", "right"]},
        },
        "required": ["who", "slot", "side"],
        "additionalProperties": False,
    }
    reveal_entry = {
        "type": "object",
        "properties": {
            "who": _field("who", "显现角色名"),
            "slot": {"type": "integer", "minimum": 0, "maximum": 5},
            "side": {"type": "string", "enum": ["fade", "left", "right"]},
        },
        "required": ["who", "slot", "side"],
        "additionalProperties": False,
    }
    departure = {
        "type": "object",
        "properties": {
            "who": _field("who", "退场角色名"),
            "side": {"type": "string", "enum": ["auto", "left", "right"]},
        },
        "required": ["who", "side"],
        "additionalProperties": False,
    }
    visual_departure = {
        "type": "object",
        "properties": {
            "who": _field("who", "离开当前镜头的角色名"),
            "side": {"type": "string", "enum": ["fade", "left", "right"]},
        },
        "required": ["who", "side"],
        "additionalProperties": False,
    }
    return {
        "beat_id": {
            "type": "string",
            "description": "后端持久节点 ID；首次生成时可省略，返修时必须原样保留",
        },
        "anchor_id": dict(anchor),
        "position": {"type": "string", "enum": ["before", "after"]},
        "who": _field("who", "执行无台词反应的主要角色名"),
        "face": _field("face", "有动态候选时填写该角色的 [Emo:语义]，不使用时填空串"),
        "emo": _field("emo", "气泡中文名，不使用时填空串"),
        "act": _field("act", "原地动作英文名，不使用时填空串"),
        "wait_ms": {
            "type": "integer", "minimum": 0, "maximum": MAX_BEAT_WAIT_MS,
            "description": "独立无台词反应的显式等待毫秒数",
        },
        "reason": {"type": "string", "enum": list(BEAT_REASONS)},
        "visible_characters": {
            "type": "array", "maxItems": 3, "items": {"type": "string"},
        },
        "positions": {
            "type": "object", "maxProperties": 3,
            "additionalProperties": {"type": "integer", "minimum": 1, "maximum": 5},
        },
        "shot_operation": {
            "type": "string", "enum": list(SHOT_OPERATIONS),
            "description": "该无台词拍的语义镜头操作；只在镜头组语义改变时填写",
        },
        "shot_transition": {
            "type": "string", "enum": list(SHOT_TRANSITIONS),
            "description": "cut=整镜硬切；reframe=同镜重构；保持当前镜头时省略",
        },
        "reactions": {
            "type": "array", "maxItems": 2, "items": reaction,
            "description": "与主要角色在同一个无对话框节点同步反应的其他角色；整拍总人数最多三人",
        },
        "reveal": {
            "type": "array", "items": reveal_entry,
            "description": "仍在当前空间中的角色加入连续镜头；无方向依据时 fade，明确横向运动时 left/right",
        },
        "conceal": {
            "type": "array", "items": visual_departure,
            "description": "角色淡出或横向离开当前连续镜头，但仍留在剧情空间；不表示真实退场",
        },
        "enter": {"type": "array", "items": entrance},
        "exit": {"type": "array", "items": departure},
        "fx": _field("fx", "主要角色立绘效果，不使用时省略"),
        "se": _field("se", "该演出事件的音效，不使用时省略"),
        "bg": _field("bg", "该无台词事件切换到的已验证背景，不使用时省略"),
        "place": _field("place", "真实新场景的地点卡，不使用时省略"),
        "trans": _field("trans", "与背景变化配套的过渡，不使用时省略"),
        "bgfx": _field("bgfx", "该演出事件的背景效果，不使用时省略"),
        "shake": {"type": "boolean"},
    }


def build_chunk_schema(target_ids: Sequence[str]) -> Dict[str, Any]:
    """Build a strict schema whose source_id enum is limited to this chunk."""
    row_properties: Dict[str, Any] = {
        "source_id": {"type": "string", "enum": list(target_ids)},
        "text_fingerprint": _field("text_fingerprint", "原文指纹，必须原样返回"),
    }
    row_required = ["source_id", "text_fingerprint"]
    for name in ANNOTATION_FIELDS:
        field_type = "boolean" if name == "shake" else "integer" if name == "move" else "string"
        if name == "reveal":
            row_properties[name] = {
                "type": "string", "enum": ["", "left", "right", "fade"],
                "description": "让本行说话者加入连续镜头；普通显现用 fade，明确横向运动才用 left/right，保持时留空",
            }
        else:
            description = (
                "有当前候选时只能原样填写 [Emo:语义]；无需换脸时填空串"
                if name == "face" else "不使用时填空值"
            )
            row_properties[name] = _field(name, description, field_type)
        if name not in OPTIONAL_LINE_FIELDS:
            row_required.append(name)
    row_properties["reactions"] = {
        "type": "array", "maxItems": 2,
        "items": _reaction_schema("对白或旁白节点上，当前镜头中其他有立绘角色的同步反应"),
        "description": (
            "只在本节点确实需要让非说话者先被看见时填写；普通对白无需填写，"
            "不把反应挂在旁白或无立绘说话人本身。"
        ),
    }
    row_properties["direction"] = _direction_schema()
    row_schema = {
        "type": "object", "properties": row_properties,
        "required": row_required, "additionalProperties": False,
    }
    state_properties = _state_properties()
    event_properties = {
        "kind": {"type": "string"}, "participants": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}}, "summary": {"type": "string"},
        "source_ids": {"type": "array", "items": {"type": "string"}}, "evidence": {"type": "string"},
        "importance": {"type": "number", "minimum": 0, "maximum": 1},
        "status": {"type": "string", "enum": ["open", "resolved", "reference"]},
    }
    beat_properties = _beat_schema_properties({
        "type": "string", "enum": list(target_ids),
    })
    return {
        "type": "object",
        "properties": {
            "lines": {"type": "array", "maxItems": len(target_ids), "items": row_schema},
            "state_delta": {"type": "object", "properties": state_properties, "additionalProperties": False},
            "memory_events": {"type": "array", "maxItems": MAX_MEMORY_EVENTS_PER_CHUNK, "items": {"type": "object", "properties": event_properties, "required": sorted(EVENT_FIELDS), "additionalProperties": False}},
            "beats": {"type": "array", "items": {
                "type": "object", "properties": beat_properties,
                "required": sorted(BEAT_REQUIRED_FIELDS), "additionalProperties": False,
            }},
        },
        "required": ["lines", "state_delta", "memory_events"],
        "additionalProperties": False,
    }


def build_compact_chunk_schema(target_count: int, target_ids: Sequence[str] = ()) -> Dict[str, Any]:
    """Build the low-overhead wire schema used by capable providers.

    The model returns a one-based target index and only non-empty annotation
    fields. Source identities and protocol defaults are restored locally.
    """
    if target_count < 1:
        raise ValueError("target_count must be positive")
    stable_ids = [str(value) for value in target_ids if str(value)]
    if stable_ids and len(stable_ids) != target_count:
        raise ValueError("target_ids must match target_count")
    stable_identity = bool(stable_ids)
    row_properties: Dict[str, Any] = (
        {"source_id": {"type": "string", "enum": stable_ids}}
        if stable_identity else
        {"i": {"type": "integer", "minimum": 1, "maximum": int(target_count)}}
    )
    for name in ANNOTATION_FIELDS:
        field_type = "boolean" if name == "shake" else "integer" if name == "move" else "string"
        row_properties[name] = {"type": field_type}
        if name == "face":
            row_properties[name]["description"] = "只能原样填写当前 FACE_SHORTLIST candidate.choice，或留空"
        elif name == "reveal":
            row_properties[name].update({
                "enum": ["", "left", "right", "fade"],
                "description": (
                    "本行说话者如何加入连续镜头；不是角色名；普通显现用 fade，"
                    "明确横向运动才用 left/right；不能与当前行的 shot_transition=cut 同时使用。"
                    "无需显现时省略或留空"
                ),
            })
    row_properties["reactions"] = {
        "type": "array", "maxItems": 2,
        "items": _reaction_schema("当前镜头中其他有立绘角色的同步反应；无新反应时省略"),
    }
    direction_properties = _direction_schema()["properties"]
    for name in DIRECTION_FIELDS:
        row_properties[name] = direction_properties[name]
    # Some schema-capable providers occasionally put the global state patch
    # beside the first compact line. Root state_delta is the canonical final
    # memory snapshot; the misplaced line copy only fills fields it omits.
    row_properties["state_delta"] = {
        "type": "object", "properties": _state_properties(),
        "additionalProperties": False,
    }
    # Some schema-capable models occasionally nest a valid line annotation in
    # compact `d`. Accept only known annotation names here; expansion below
    # restores their canonical row-level location before protocol validation.
    row_properties["d"] = _direction_schema(annotation_aliases=True)
    row_schema = {
        "type": "object", "properties": row_properties,
        "required": ["source_id" if stable_identity else "i"],
        "additionalProperties": False,
        "allOf": [
            {
                "not": {
                    "required": ["reveal", "d"],
                    "properties": {
                        "reveal": {"enum": ["left", "right", "fade"]},
                        "d": {
                            "required": ["shot_transition"],
                            "properties": {
                                "shot_transition": {"const": "cut"},
                            },
                        },
                    },
                },
            },
            {
                "not": {
                    "required": ["reveal", "shot_transition"],
                    "properties": {
                        "reveal": {"enum": ["left", "right", "fade"]},
                        "shot_transition": {"const": "cut"},
                    },
                },
            },
        ],
    }
    state_properties = _state_properties()
    event_properties = {
        "kind": {"type": "string"}, "participants": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}}, "summary": {"type": "string"},
        "source_ids": {"type": "array", "items": (
            {"type": "string", "enum": stable_ids}
            if stable_identity else
            {"type": "integer", "minimum": 1, "maximum": int(target_count)}
        )}, "evidence": {"type": "string"},
        "importance": {"type": "number", "minimum": 0, "maximum": 1},
        "status": {"type": "string", "enum": ["open", "resolved", "reference"]},
    }
    beat_properties = _beat_schema_properties(
        {"type": "string", "enum": stable_ids}
        if stable_identity else
        {"type": "integer", "minimum": 1, "maximum": int(target_count)}
    )
    return {
        "type": "object", "properties": {
            "lines": {"type": "array", "maxItems": int(target_count), "items": row_schema},
            "state_delta": {"type": "object", "properties": state_properties, "additionalProperties": False},
            "memory_events": {"type": "array", "maxItems": MAX_MEMORY_EVENTS_PER_CHUNK, "items": {"type": "object", "properties": event_properties, "required": sorted(EVENT_FIELDS), "additionalProperties": False}},
            "beats": {"type": "array", "items": {"type": "object", "properties": beat_properties, "required": sorted(BEAT_REQUIRED_FIELDS), "additionalProperties": False}},
        }, "required": ["lines", "state_delta", "memory_events"], "additionalProperties": False,
    }


def expand_compact_chunk_response(response: Any, targets: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Restore omitted no-op rows, identities and defaults before validation."""
    response = _require_dict(response, "invalid_response", "模型响应必须是对象")
    lines = response.get("lines")
    if not isinstance(lines, list):
        raise ChunkProtocolError("invalid_lines", "lines 必须是数组")
    root_state = dict(_require_dict(
        response.get("state_delta", {}), "invalid_state_delta", "state_delta 必须是对象",
    ))
    expanded_by_index: Dict[int, Dict[str, Any]] = {}
    seen = set()
    director_intents: Dict[str, Dict[str, Any]] = {}
    annotation_intents: Dict[str, set[str]] = {}
    index_by_source = {
        str(target.get("annotation_id") or ""): index
        for index, target in enumerate(targets, 1)
    }
    for compact in lines:
        compact = _require_dict(compact, "invalid_line", "compact line 必须是对象")
        compact = dict(compact)
        source_id = compact.pop("source_id", None)
        supplied_index = compact.pop("i", None)
        if source_id is not None:
            if not isinstance(source_id, str) or source_id not in index_by_source:
                raise ChunkProtocolError("unknown_target", f"compact line.source_id 超出目标范围: {source_id}")
            index = index_by_source[source_id]
            if supplied_index is not None and supplied_index != index:
                raise ChunkProtocolError("invalid_line", "compact line.i 与 source_id 指向不同目标")
        else:
            index = supplied_index
            if isinstance(index, bool) or not isinstance(index, int):
                raise ChunkProtocolError("invalid_line", "compact line 必须提供整数 i 或稳定 source_id")
            if not 1 <= index <= len(targets):
                raise ChunkProtocolError("unknown_target", f"compact line.i 超出目标范围: {index}")
        if index in seen:
            raise ChunkProtocolError("duplicate_target", f"目标行重复: {index}")
        seen.add(index)
        line_state = compact.pop("state_delta", None)
        if line_state is not None:
            line_state = _require_dict(
                line_state, "invalid_state_delta", "compact line.state_delta 必须是对象",
            )
            for name, value in line_state.items():
                if name not in root_state:
                    root_state[name] = value
        unknown = set(compact) - ({"d"} | set(ANNOTATION_FIELDS) | LINE_REACTION_FIELDS | DIRECTION_FIELDS)
        if unknown:
            raise ChunkProtocolError("invalid_line", f"compact line 包含未知字段: {sorted(unknown)}")
        raw_direction = _require_dict(
            compact.get("d", {}), "invalid_line", "compact line.d must be an object",
        )
        raw_direction = dict(raw_direction)
        for name in DIRECTION_FIELDS:
            if name not in compact:
                continue
            value = compact[name]
            if name in raw_direction and raw_direction[name] != value:
                raise ChunkProtocolError(
                    "invalid_line",
                    f"compact line.{name} 与 compact line.d.{name} 冲突",
                )
            raw_direction[name] = value
        direction_aliases = {
            name: raw_direction[name]
            for name in ANNOTATION_FIELDS
            if name in raw_direction
        }
        for name, value in direction_aliases.items():
            if name in compact and compact[name] != value:
                raise ChunkProtocolError(
                    "invalid_line",
                    f"compact line.{name} 与 compact line.d.{name} 冲突",
                )
            compact[name] = value
        direction_patch = _validate_direction_wire(
            {name: value for name, value in raw_direction.items() if name not in ANNOTATION_FIELDS},
            "compact line.d",
        )
        target = targets[index - 1]
        row = {
            "source_id": str(target.get("annotation_id") or ""),
            "text_fingerprint": str(target.get("text_fingerprint") or ""),
            **{
                name: (False if name == "shake" else 0 if name == "move" else "")
                for name in ANNOTATION_FIELDS if name not in OPTIONAL_LINE_FIELDS
            },
            "direction": default_director(),
        }
        continuity_patch = direction_patch.get("continuity", {})
        row["direction"].update({
            name: value for name, value in direction_patch.items()
            if name != "continuity"
        })
        row["direction"]["continuity"].update(continuity_patch)
        # Compact responses may put direction fields either in the nested
        # ``d`` object or directly beside ``i`` (both shapes are in the
        # schema).  In both cases they are explicit model intent.  Recording
        # only nested ``d`` made valid top-level camera plans look like
        # normalized defaults, so later state tracking silently ignored them.
        if direction_patch:
            director_intents[row["source_id"]] = dict(direction_patch)
        annotation_intents[row["source_id"]] = {
            name for name in (set(ANNOTATION_FIELDS) | LINE_REACTION_FIELDS)
            if name in compact
        }
        for name in ANNOTATION_FIELDS:
            if name in compact:
                row[name] = compact[name]
        if "reactions" in compact:
            row["reactions"] = compact["reactions"]
        if str(row.get("fx") or "").strip() == "无":
            existing_fx_command = row["direction"]["continuity"].get("fx")
            if existing_fx_command not in (None, "none", "end"):
                raise ChunkProtocolError(
                    "invalid_line",
                    "fx=无 与 continuity.fx 的开始/升级指令冲突",
                )
            row["direction"]["continuity"]["fx"] = "end"
            intent = director_intents.setdefault(row["source_id"], {})
            intent_continuity = dict(intent.get("continuity") or {})
            intent_continuity["fx"] = "end"
            intent["continuity"] = intent_continuity
        expanded_by_index[index] = row
    for index, target in enumerate(targets, 1):
        if index in expanded_by_index:
            continue
        expanded_by_index[index] = {
            "source_id": str(target.get("annotation_id") or ""),
            "text_fingerprint": str(target.get("text_fingerprint") or ""),
            **{
                name: (False if name == "shake" else 0 if name == "move" else "")
                for name in ANNOTATION_FIELDS if name not in OPTIONAL_LINE_FIELDS
            },
            "direction": default_director(),
        }
    expanded = [expanded_by_index[index] for index in range(1, len(targets) + 1)]
    expanded_beats = []
    for beat in response.get("beats", []):
        expanded_beat = dict(_require_dict(beat, "invalid_beat", "compact beat 必须是对象"))
        anchor = expanded_beat.get("anchor_id")
        if isinstance(anchor, str):
            if anchor not in index_by_source:
                raise ChunkProtocolError("unknown_beat_anchor", f"compact beat.anchor_id 超出目标范围: {anchor}")
        else:
            if isinstance(anchor, bool) or not isinstance(anchor, int):
                raise ChunkProtocolError("invalid_beat", "compact beat.anchor_id 必须是整数或稳定 source_id")
            if not 1 <= anchor <= len(targets):
                raise ChunkProtocolError("unknown_beat_anchor", f"compact beat.anchor_id 超出目标范围: {anchor}")
            anchor = str(targets[anchor - 1].get("annotation_id") or "")
        expanded_beat["anchor_id"] = anchor
        expanded_beats.append(expanded_beat)
    expanded_events = []
    for event in response.get("memory_events", []):
        expanded_event = dict(_require_dict(event, "invalid_memory_event", "compact memory_event 必须是对象"))
        source_ids = expanded_event.get("source_ids")
        if not isinstance(source_ids, list):
            raise ChunkProtocolError("invalid_memory_event", "compact memory_event.source_ids 必须是数组")
        mapped_ids = []
        for source in source_ids:
            if isinstance(source, str):
                if source not in index_by_source:
                    raise ChunkProtocolError("unknown_event_source", f"compact event source 超出目标范围: {source}")
                mapped_ids.append(source)
                continue
            if isinstance(source, bool) or not isinstance(source, int):
                raise ChunkProtocolError("invalid_memory_event", "compact memory_event.source_ids 必须使用整数索引或稳定 source_id")
            if not 1 <= source <= len(targets):
                raise ChunkProtocolError("unknown_event_source", f"compact event source 超出目标范围: {source}")
            mapped_ids.append(str(targets[source - 1].get("annotation_id") or ""))
        expanded_event["source_ids"] = mapped_ids
        expanded_events.append(expanded_event)
    return _ExpandedChunkResponse({
        "lines": expanded,
        "state_delta": root_state,
        "memory_events": expanded_events,
        **({"beats": expanded_beats} if "beats" in response else {}),
    }, director_intents=director_intents, annotation_intents=annotation_intents)


def merge_compact_retry_response(
    response: Any,
    previous_response: Mapping[str, Any] | None,
    targets: Sequence[Mapping[str, Any]],
    *,
    clear_fields: Iterable[str] = (),
) -> Dict[str, Any]:
    """Preserve authored fields when a compact protocol retry omits them.

    A protocol retry may return only fields changed to fix the reported
    error. Expanding that sparse response from blank defaults would silently
    erase valid face/emo/act/camera choices from the failed attempt. Merge at
    the wire level so explicit empty values still clear a field while omitted
    fields retain the previous response.
    """
    current = copy.deepcopy(dict(_require_dict(
        response, "invalid_response", "模型响应必须是对象",
    )))
    if not isinstance(previous_response, Mapping):
        return current
    previous = dict(previous_response)
    index_by_source = {
        str(target.get("annotation_id") or ""): index
        for index, target in enumerate(targets, 1)
    }

    def line_index(line):
        if not isinstance(line, Mapping):
            return None
        source_id = line.get("source_id")
        if isinstance(source_id, str) and source_id in index_by_source:
            return index_by_source[source_id]
        value = line.get("i")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    previous_lines = {
        index: dict(line)
        for line in previous.get("lines") or ()
        if (index := line_index(line)) is not None
    }
    current_lines = []
    seen = set()
    for line in current.get("lines") or ():
        if not isinstance(line, Mapping):
            current_lines.append(line)
            continue
        merged = dict(line)
        index = line_index(line)
        previous_line = previous_lines.get(index)
        if previous_line is not None:
            # Presence is the compact protocol's clear/keep signal. Explicit
            # empty strings/false/zero remain authored values.
            for field in set(ANNOTATION_FIELDS) | LINE_REACTION_FIELDS:
                if field not in merged and field in previous_line:
                    merged[field] = copy.deepcopy(previous_line[field])
            previous_direction = dict(previous_line.get("d") or {})
            for field in DIRECTION_FIELDS:
                if field in previous_line and field != "d":
                    previous_direction[field] = previous_line[field]
            current_direction = dict(merged.get("d") or {})
            for field in DIRECTION_FIELDS:
                if field in merged and field != "d":
                    current_direction[field] = merged[field]
            if previous_direction or current_direction:
                merged["d"] = {**previous_direction, **current_direction}
        current_lines.append(merged)
        if index is not None:
            seen.add(index)

    # Omitted rows are no-op rows in compact mode; carry their previous wire
    # entries into this retry so authored values survive expansion.
    for index, line in previous_lines.items():
        if index not in seen:
            current_lines.append(copy.deepcopy(line))
    for line in current_lines:
        if isinstance(line, dict):
            for field in clear_fields:
                line.pop(str(field), None)
    current["lines"] = current_lines

    if not current.get("state_delta") and previous.get("state_delta"):
        current["state_delta"] = copy.deepcopy(previous["state_delta"])
    for field in ("memory_events", "beats"):
        if not current.get(field) and previous.get(field):
            current[field] = copy.deepcopy(previous[field])
    return current


def _validate_beats(
    value: Any, expected_ids: Iterable[str], cast: Mapping[str, Any],
    constraints: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise ChunkProtocolError("invalid_beats", "beats 必须是数组")
    expected = set(expected_ids)
    result = []
    seen_events = set()
    displayable = {
        name for name, character in cast.items()
        if isinstance(character, Mapping) and character.get("portrait") and not character.get("narrator")
    } if isinstance(cast, Mapping) else set()

    def validate_people(values: Any, field: str) -> List[str]:
        if not isinstance(values, list) or len(values) > 3:
            raise ChunkProtocolError("invalid_beat", f"beat.{field} 必须是最多三人的数组")
        normalized = []
        for name in values:
            if not isinstance(name, str) or name not in displayable:
                raise ChunkProtocolError("invalid_beat_character", f"beat.{field} 角色不可显示: {name}")
            if name not in normalized:
                normalized.append(name)
        return normalized

    for beat in value:
        beat = _require_dict(beat, "invalid_beat", "beats 每项必须是对象")
        if not BEAT_REQUIRED_FIELDS <= set(beat) or not set(beat) <= BEAT_FIELDS:
            raise ChunkProtocolError("invalid_beat", "beat 字段不完整或包含未知字段")
        for name in ("anchor_id", "position", "who", "face", "emo", "act", "reason"):
            if not isinstance(beat.get(name), str):
                raise ChunkProtocolError("invalid_beat", f"beat.{name} 必须是字符串")
        anchor_id = beat["anchor_id"]
        if anchor_id not in expected:
            raise ChunkProtocolError("unknown_beat_anchor", f"beat 引用了未知目标行: {anchor_id}")
        if beat.get("position") not in {"before", "after"}:
            raise ChunkProtocolError("invalid_beat_position", "beat position 只能是 before 或 after")
        if beat["reason"] not in BEAT_REASONS:
            raise ChunkProtocolError("invalid_beat_reason", f"beat reason 无效: {beat['reason']}")
        who = beat["who"]
        character = cast.get(who) if isinstance(cast, Mapping) else None
        if not character or not character.get("portrait") or character.get("narrator"):
            raise ChunkProtocolError("invalid_beat_character", f"beat 角色不可显示: {who}")
        wait_ms = beat.get("wait_ms")
        if isinstance(wait_ms, bool) or not isinstance(wait_ms, int) or not 0 <= wait_ms <= MAX_BEAT_WAIT_MS:
            raise ChunkProtocolError("invalid_beat_wait", "beat wait_ms 必须在 0-10000 之间")
        face = beat["face"]
        allowed_faces = constraints.get("faces_by_id", {}).get(character.get("id"), set())
        if face and face not in allowed_faces and face.zfill(2) not in allowed_faces:
            raise ChunkProtocolError("illegal_beat_face", f"{who} 没有已验证表情 {face}")
        raw_emo = beat["emo"]
        emo = normalize_emoticon(raw_emo)
        if emo and emo not in constraints.get("ok_emo", set()):
            raise ChunkProtocolError("illegal_beat_emoticon", f"未知气泡 {raw_emo}")
        act = beat["act"]
        if act and act not in constraints.get("ok_act", set()):
            raise ChunkProtocolError("illegal_beat_action", f"未知动作 {act}")
        visible = validate_people(beat["visible_characters"], "visible_characters") if "visible_characters" in beat else None
        positions = beat.get("positions", {})
        if not isinstance(positions, dict) or len(positions) > 3:
            raise ChunkProtocolError("invalid_beat_positions", "beat.positions 必须是人物到槽位的对象")
        normalized_positions: Dict[str, int] = {}
        for name, slot in positions.items():
            if name not in displayable:
                raise ChunkProtocolError("invalid_beat_character", f"beat.positions 角色不可显示: {name}")
            if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= 5:
                raise ChunkProtocolError("invalid_beat_positions", f"beat.positions 槽位无效: {name}={slot}")
            normalized_positions[name] = slot
        if len(set(normalized_positions.values())) != len(normalized_positions):
            raise ChunkProtocolError("duplicate_beat_slot", "beat.positions 不能让两个人占同一槽位")
        if visible is not None and not set(normalized_positions) <= set(visible):
            raise ChunkProtocolError("invalid_beat_positions", "beat.positions 只能包含本镜可见人物")
        shot_transition = str(beat.get("shot_transition") or "")
        if shot_transition and shot_transition not in SHOT_TRANSITIONS:
            raise ChunkProtocolError(
                "invalid_beat", f"beat.shot_transition 无效: {shot_transition}",
            )
        if shot_transition:
            if visible is None or "positions" not in beat:
                raise ChunkProtocolError(
                    "invalid_beat", f"beat.{shot_transition} 必须携带完整镜头名单和站位",
                )
            if set(normalized_positions) != set(visible):
                raise ChunkProtocolError(
                    "invalid_beat_positions", "cut/reframe 的 positions 必须覆盖完整镜头",
                )
        shot_operation = str(beat.get("shot_operation") or "")
        if shot_operation and shot_operation not in SHOT_OPERATIONS:
            raise ChunkProtocolError(
                "invalid_beat", f"beat.shot_operation 无效: {shot_operation}",
            )

        reactions = beat.get("reactions", [])
        if not isinstance(reactions, list) or len(reactions) > 2:
            raise ChunkProtocolError("invalid_beat", "beat.reactions 最多包含两个共同反应角色")
        normalized_reactions = []
        reacted = {who}
        for reaction in reactions:
            reaction = _require_dict(
                reaction, "invalid_beat", "beat.reactions 每项必须是对象",
            )
            if set(reaction) != {"who", "face", "emo", "act"}:
                raise ChunkProtocolError("invalid_beat", "beat.reactions 字段无效")
            name = reaction.get("who")
            if name not in displayable or name in reacted:
                raise ChunkProtocolError(
                    "invalid_beat_character", f"beat.reactions 角色不可显示或重复: {name}",
                )
            reacted.add(name)
            reaction_character = cast[name]
            reaction_face = str(reaction.get("face") or "")
            allowed_reaction_faces = constraints.get("faces_by_id", {}).get(
                reaction_character.get("id"), set(),
            )
            if (
                reaction_face
                and reaction_face not in allowed_reaction_faces
                and reaction_face.zfill(2) not in allowed_reaction_faces
            ):
                raise ChunkProtocolError(
                    "illegal_beat_face", f"{name} 没有已验证表情 {reaction_face}",
                )
            raw_reaction_emo = str(reaction.get("emo") or "")
            reaction_emo = normalize_emoticon(raw_reaction_emo)
            if reaction_emo and reaction_emo not in constraints.get("ok_emo", set()):
                raise ChunkProtocolError("illegal_beat_emoticon", f"未知气泡 {raw_reaction_emo}")
            reaction_act = str(reaction.get("act") or "")
            if reaction_act and reaction_act not in constraints.get("ok_act", set()):
                raise ChunkProtocolError("illegal_beat_action", f"未知动作 {reaction_act}")
            if visible is not None and name not in visible:
                raise ChunkProtocolError(
                    "invalid_beat_character", f"共同反应角色不在本镜可见名单: {name}",
                )
            normalized_reactions.append({
                "who": name,
                "face": reaction_face.zfill(2) if reaction_face else "",
                "emo": constraints.get("sym2cn", {}).get(reaction_emo, reaction_emo),
                "act": reaction_act,
            })
        profiles = constraints.get("portrait_profiles_by_name") or {}
        positioned = list(normalized_positions)
        for index, first in enumerate(positioned):
            for second in positioned[index + 1:]:
                required = max(
                    int((profiles.get(first) or {}).get("min_slot_gap") or 1),
                    int((profiles.get(second) or {}).get("min_slot_gap") or 1),
                )
                if abs(normalized_positions[first] - normalized_positions[second]) < required:
                    raise ChunkProtocolError(
                        "unsafe_beat_spacing", f"{first} 与 {second} 的立绘槽位会重叠",
                    )

        entrances = beat.get("enter", [])
        if not isinstance(entrances, list):
            raise ChunkProtocolError("invalid_beat_enter", "beat.enter 必须是数组")
        normalized_enter = []
        entered = set()
        for entry in entrances:
            entry = _require_dict(entry, "invalid_beat_enter", "beat.enter 每项必须是对象")
            if set(entry) != {"who", "slot", "side"}:
                raise ChunkProtocolError("invalid_beat_enter", "beat.enter 字段无效")
            name, slot, side = entry["who"], entry["slot"], entry["side"]
            if name not in displayable or name in entered:
                raise ChunkProtocolError("invalid_beat_character", f"beat.enter 角色不可显示或重复: {name}")
            if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot <= 5:
                raise ChunkProtocolError("invalid_beat_enter", f"beat.enter 槽位无效: {slot}")
            if side not in {"auto", "left", "right"}:
                raise ChunkProtocolError("invalid_beat_enter", f"beat.enter 方向无效: {side}")
            if 1 <= slot <= 2:
                side = "left"
            elif 4 <= slot <= 5:
                side = "right"
            entered.add(name)
            normalized_enter.append({"who": name, "slot": slot, "side": side})

        reveals = beat.get("reveal", [])
        if not isinstance(reveals, list):
            raise ChunkProtocolError("invalid_beat_reveal", "beat.reveal 必须是数组")
        normalized_reveal = []
        revealed = set()
        for entry in reveals:
            entry = _require_dict(entry, "invalid_beat_reveal", "beat.reveal 每项必须是对象")
            if set(entry) != {"who", "slot", "side"}:
                raise ChunkProtocolError("invalid_beat_reveal", "beat.reveal 字段无效")
            name, slot, side = entry["who"], entry["slot"], entry["side"]
            if name not in displayable or name in revealed:
                raise ChunkProtocolError(
                    "invalid_beat_character", f"beat.reveal 角色不可显示或重复: {name}",
                )
            if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot <= 5:
                raise ChunkProtocolError("invalid_beat_reveal", f"beat.reveal 槽位无效: {slot}")
            if side not in {"fade", "left", "right"}:
                raise ChunkProtocolError("invalid_beat_reveal", f"beat.reveal 方向无效: {side}")
            if side != "fade" and 1 <= slot <= 2:
                side = "left"
            elif side != "fade" and 4 <= slot <= 5:
                side = "right"
            revealed.add(name)
            normalized_reveal.append({"who": name, "slot": slot, "side": side})

        if entered & revealed:
            raise ChunkProtocolError(
                "invalid_beat", "同一角色不能在一个 beat 中同时 reveal 和 enter",
            )

        conceals = beat.get("conceal", [])
        if not isinstance(conceals, list):
            raise ChunkProtocolError("invalid_beat_conceal", "beat.conceal 必须是数组")
        normalized_conceal = []
        concealed = set()
        for entry in conceals:
            entry = _require_dict(entry, "invalid_beat_conceal", "beat.conceal 每项必须是对象")
            if set(entry) != {"who", "side"}:
                raise ChunkProtocolError("invalid_beat_conceal", "beat.conceal 字段无效")
            name, side = entry["who"], entry["side"]
            if name not in displayable or name in concealed:
                raise ChunkProtocolError("invalid_beat_character", f"beat.conceal 角色不可显示或重复: {name}")
            if side not in {"fade", "left", "right"}:
                raise ChunkProtocolError("invalid_beat_conceal", f"beat.conceal 方向无效: {side}")
            concealed.add(name)
            normalized_conceal.append({"who": name, "side": side})

        departures = beat.get("exit", [])
        if not isinstance(departures, list):
            raise ChunkProtocolError("invalid_beat_exit", "beat.exit 必须是数组")
        normalized_exit = []
        exited = set()
        for entry in departures:
            entry = _require_dict(entry, "invalid_beat_exit", "beat.exit 每项必须是对象")
            if set(entry) != {"who", "side"}:
                raise ChunkProtocolError("invalid_beat_exit", "beat.exit 字段无效")
            name, side = entry["who"], entry["side"]
            if name not in displayable or name in exited:
                raise ChunkProtocolError("invalid_beat_character", f"beat.exit 角色不可显示或重复: {name}")
            if side not in {"auto", "left", "right"}:
                raise ChunkProtocolError("invalid_beat_exit", f"beat.exit 方向无效: {side}")
            exited.add(name)
            normalized_exit.append({"who": name, "side": side})

        lifecycle_overlap = concealed & (entered | revealed | exited)
        if lifecycle_overlap:
            raise ChunkProtocolError(
                "invalid_beat",
                f"同一角色不能在一个 beat 中同时显现/进入/淡出/退场: {sorted(lifecycle_overlap)}",
            )

        if shot_transition == "cut" and (
            normalized_reveal or normalized_conceal or normalized_enter or normalized_exit
        ):
            raise ChunkProtocolError(
                "invalid_beat", "整镜硬切不能与真实入场/退场或立绘显隐放在同一个 beat",
            )
        if visible is not None:
            empty_offscreen = (
                not visible
                and beat["reason"] in {"offscreen_cue", "montage"}
                and not any((face, emo, act, normalized_reactions))
            )
            if not empty_offscreen and who not in visible:
                raise ChunkProtocolError(
                    "invalid_beat_character", f"beat 主体不在本镜可见名单: {who}",
                )
            missing_enter = {entry["who"] for entry in normalized_enter} - set(visible)
            if missing_enter:
                raise ChunkProtocolError(
                    "invalid_beat_character", f"入场角色不在本镜可见名单: {sorted(missing_enter)}",
                )
            missing_reveal = {entry["who"] for entry in normalized_reveal} - set(visible)
            if missing_reveal:
                raise ChunkProtocolError(
                    "invalid_beat_character", f"显现角色不在本镜可见名单: {sorted(missing_reveal)}",
                )

        fx = str(beat.get("fx") or "")
        fx_parts = {
            part.strip()
            for part in re.split(r"[+＋、,，/]", fx)
            if part.strip()
        }
        allowed_fx = constraints.get("ok_fx", set())
        if fx and (
            not is_fx_allowed(fx)
            or (allowed_fx and not fx_parts <= set(allowed_fx))
        ):
            raise ChunkProtocolError("illegal_beat_fx", f"未知立绘效果 {fx}")
        se = str(beat.get("se") or "")
        if se and se not in constraints.get("ok_se", set()):
            raise ChunkProtocolError("illegal_beat_sound", f"未知音效 {se}")
        bg = str(beat.get("bg") or "")
        if bg and bg not in constraints.get("ok_bg", set()):
            raise ChunkProtocolError("illegal_beat_background", f"未知背景 {bg}")
        place = str(beat.get("place") or "")
        trans = str(beat.get("trans") or "")
        if trans:
            transition_value, transition_error = tables.resolve_transition(trans)
            if not transition_value or transition_error:
                raise ChunkProtocolError("illegal_beat_transition", transition_error or f"未知过渡 {trans}")
        bgfx = str(beat.get("bgfx") or "")
        if bgfx and bgfx not in constraints.get("ok_bgfx", set()):
            raise ChunkProtocolError("illegal_beat_bgfx", f"未知背景效果 {bgfx}")
        shake = beat.get("shake", False)
        if not isinstance(shake, bool):
            raise ChunkProtocolError("invalid_beat", "beat.shake 必须是布尔值")

        normalized = {
            "anchor_id": anchor_id, "position": beat["position"], "who": who,
            "face": face.zfill(2) if face else "",
            "emo": constraints.get("sym2cn", {}).get(emo, emo), "act": act,
            "wait_ms": wait_ms, "reason": beat["reason"],
        }
        for field, field_value in (
            ("visible_characters", visible), ("positions", normalized_positions),
            ("shot_transition", shot_transition),
            ("shot_operation", shot_operation),
            ("reveal", normalized_reveal),
            ("conceal", normalized_conceal),
            ("enter", normalized_enter), ("exit", normalized_exit),
            ("reactions", normalized_reactions),
            ("fx", fx), ("se", se), ("bg", bg), ("place", place),
            ("trans", trans), ("bgfx", bgfx), ("shake", shake),
        ):
            if field in beat:
                normalized[field] = field_value
        supplied_beat_id = beat.get("beat_id")
        if supplied_beat_id is not None and not isinstance(supplied_beat_id, str):
            raise ChunkProtocolError("invalid_beat", "beat.beat_id 必须是字符串")
        generated_beat_id = "beat-" + str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            "halocue-aa-beat-v1:" + json.dumps(
                normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ),
        ))
        normalized["beat_id"] = (
            supplied_beat_id.strip()[:96] if supplied_beat_id and supplied_beat_id.strip()
            else generated_beat_id
        )
        signature = repr(sorted(normalized.items(), key=lambda pair: pair[0]))
        if signature not in seen_events:
            seen_events.add(signature)
            result.append(normalized)
    return result


def _require_dict(value: Any, code: str, detail: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ChunkProtocolError(code, detail)
    return value


def _validate_state_delta(value: Any) -> Dict[str, Any]:
    state = _require_dict(value, "invalid_state_delta", "state_delta 必须是对象")
    unknown = set(state) - STATE_FIELDS
    if unknown:
        raise ChunkProtocolError("invalid_state_delta", f"state_delta 包含未知字段: {sorted(unknown)}")
    normalized = {}
    for name, field_value in state.items():
        if field_value is None:
            continue
        if not isinstance(field_value, STATE_FIELD_TYPES[name]):
            raise ChunkProtocolError("invalid_state_delta", f"state_delta.{name} has an invalid type")
        if name == "scene_presence":
            if any(
                not isinstance(character, str)
                or status not in {"unknown", "present", "absent"}
                for character, status in field_value.items()
            ):
                raise ChunkProtocolError(
                    "invalid_state_delta",
                    "state_delta.scene_presence 必须是角色名到 unknown/present/absent 的对象",
                )
        normalized[name] = field_value
    return normalized


def _validate_events(value: Any, visible_ids: Iterable[str]) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise ChunkProtocolError("invalid_memory_events", "memory_events 必须是数组")
    visible = set(visible_ids)
    result = []
    for event in value:
        if len(result) >= MAX_MEMORY_EVENTS_PER_CHUNK:
            raise ChunkProtocolError(
                "too_many_memory_events",
                f"每个场景块最多 {MAX_MEMORY_EVENTS_PER_CHUNK} 条长期记忆",
            )
        event = _require_dict(event, "invalid_memory_event", "memory_events 每项必须是对象")
        if set(event) != EVENT_FIELDS:
            raise ChunkProtocolError("invalid_memory_event", "memory event 字段不完整或包含未知字段")
        for name in ("kind", "summary", "evidence", "status"):
            if not isinstance(event.get(name), str):
                raise ChunkProtocolError("invalid_memory_event", f"memory event.{name} 必须是字符串")
        for name in ("participants", "keywords", "source_ids"):
            values = event.get(name)
            if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
                raise ChunkProtocolError("invalid_memory_event", f"memory event.{name} 必须是字符串数组")
        importance = event.get("importance")
        if (
            isinstance(importance, bool)
            or not isinstance(importance, (int, float))
            or not 0 <= importance <= 1
        ):
            raise ChunkProtocolError("invalid_memory_event", "memory event.importance 必须在 0 到 1 之间")
        if event["status"] not in {"open", "resolved", "reference"}:
            raise ChunkProtocolError("invalid_memory_event", "memory event.status 无效")
        source_ids = event.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids or not set(source_ids) <= visible:
            raise ChunkProtocolError("invalid_event_source", "memory event 必须引用当前可见原文行")
        if not isinstance(event.get("evidence"), str) or not event["evidence"].strip():
            raise ChunkProtocolError("invalid_memory_event", "memory event 缺少证据文本")
        result.append(dict(event))
    return result


def _validate_annotation_row(value: Any) -> Mapping[str, Any]:
    row = _require_dict(value, "invalid_line", "lines 每项必须是对象")
    if not LINE_REQUIRED_FIELDS <= set(row) or not set(row) <= LINE_FIELDS:
        raise ChunkProtocolError("invalid_line", "line 字段不完整或包含未知字段")
    if "direction" in row:
        _validate_direction_wire(row["direction"], "line.direction")
    if not isinstance(row.get("source_id"), str) or not isinstance(row.get("text_fingerprint"), str):
        raise ChunkProtocolError("invalid_line", "source_id 和 text_fingerprint 必须是字符串")
    for name, expected_type in ANNOTATION_FIELD_TYPES.items():
        if name in OPTIONAL_LINE_FIELDS and name not in row:
            continue
        field_value = row.get(name)
        if expected_type is int:
            valid = isinstance(field_value, int) and not isinstance(field_value, bool)
        else:
            valid = isinstance(field_value, expected_type)
        if not valid:
            raise ChunkProtocolError("invalid_line", f"line.{name} 类型不正确")
    if row.get("reveal", "") not in {"", "left", "right", "fade"}:
        raise ChunkProtocolError(
            "invalid_line", "line.reveal 只允许留空或使用 left/right/fade",
        )
    reactions = row.get("reactions", [])
    if not isinstance(reactions, list) or len(reactions) > 2:
        raise ChunkProtocolError("invalid_line", "line.reactions 最多包含两个同步反应角色")
    for reaction in reactions:
        reaction = _require_dict(
            reaction, "invalid_line", "line.reactions 每项必须是对象",
        )
        if set(reaction) != {"who", "face", "emo", "act"}:
            raise ChunkProtocolError("invalid_line", "line.reactions 字段无效")
        if not isinstance(reaction.get("who"), str):
            raise ChunkProtocolError("invalid_line", "line.reactions.who 必须是字符串")
        for name in ("face", "emo", "act"):
            if not isinstance(reaction.get(name), str):
                raise ChunkProtocolError(
                    "invalid_line", f"line.reactions.{name} 必须是字符串",
                )
    return row


def _normalize_reactions(
    value: Any, *, cast: Mapping[str, Any], constraints: Mapping[str, Any],
    visible: Sequence[str] | None = None, owner: str = "",
    field_name: str = "line.reactions",
) -> List[Dict[str, str]]:
    """Validate explicit same-node reactions without assigning them to a speaker."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 2:
        raise ChunkProtocolError("invalid_line", f"{field_name} 最多包含两个同步反应角色")
    displayable = {
        name for name, character in (cast or {}).items()
        if isinstance(character, Mapping)
        and character.get("portrait") and not character.get("narrator")
    }
    visible_set = set(visible) if visible is not None else None
    normalized: List[Dict[str, str]] = []
    reacted = {owner} if owner else set()
    for reaction in value:
        reaction = _require_dict(
            reaction, "invalid_line", f"{field_name} 每项必须是对象",
        )
        if set(reaction) != {"who", "face", "emo", "act"}:
            raise ChunkProtocolError("invalid_line", f"{field_name} 字段无效")
        name = str(reaction.get("who") or "")
        if name not in displayable or name in reacted:
            raise ChunkProtocolError(
                "invalid_line_character", f"{field_name} 角色不可显示或重复: {name}",
            )
        if visible_set is not None and name not in visible_set:
            raise ChunkProtocolError(
                "invalid_line_character", f"{field_name} 角色不在本镜可见名单: {name}",
            )
        reacted.add(name)
        reaction_character = cast[name]
        reaction_face = str(reaction.get("face") or "")
        allowed_faces = constraints.get("faces_by_id", {}).get(
            reaction_character.get("id"), set(),
        )
        if (
            reaction_face
            and reaction_face not in allowed_faces
            and reaction_face.zfill(2) not in allowed_faces
        ):
            raise ChunkProtocolError(
                "illegal_line_reaction_face", f"{name} 没有已验证表情 {reaction_face}",
            )
        reaction_emo = normalize_emoticon(reaction.get("emo"))
        if reaction_emo and reaction_emo not in constraints.get("ok_emo", set()):
            raise ChunkProtocolError("illegal_line_reaction_emoticon", f"未知气泡 {reaction.get('emo')}")
        reaction_act = str(reaction.get("act") or "")
        if reaction_act and reaction_act not in constraints.get("ok_act", set()):
            raise ChunkProtocolError("illegal_line_reaction_action", f"未知动作 {reaction_act}")
        normalized.append({
            "who": name,
            "face": reaction_face.zfill(2) if reaction_face else "",
            "emo": constraints.get("sym2cn", {}).get(reaction_emo, reaction_emo),
            "act": reaction_act,
        })
    return normalized


def _validate_line_resources(
    row: Mapping[str, Any], target: Mapping[str, Any],
    cast: Mapping[str, Any], constraints: Mapping[str, Any],
) -> Dict[str, Any]:
    """Validate and canonicalize top-level line resources before policy."""
    normalized = dict(row)
    if not constraints:
        return normalized

    speaker = str(target.get("who") or "")
    character = cast.get(speaker) if speaker and isinstance(cast, Mapping) else None
    portrait_known = bool(speaker and speaker in cast)
    portrait = bool(
        isinstance(character, Mapping)
        and character.get("portrait")
        and not character.get("narrator")
    )
    if portrait_known and not portrait:
        for field in ("face", "emo", "act", "fx"):
            if normalized.get(field):
                raise ChunkProtocolError(
                    "illegal_line_character_resource",
                    f"{speaker}无立绘，不能使用 {field}",
                )

    face = str(normalized.get("face") or "")
    if face and "faces_by_id" in constraints:
        character_id = str((character or {}).get("id") or "")
        allowed_faces = constraints.get("faces_by_id", {}).get(character_id, set())
        canonical_face = face if face in allowed_faces else face.zfill(2)
        if canonical_face not in allowed_faces:
            raise ChunkProtocolError(
                "illegal_line_face", f"{speaker or character_id} 没有已验证表情 {face}",
            )
        normalized["face"] = canonical_face

    emo = normalize_emoticon(normalized.get("emo"))
    if emo and "ok_emo" in constraints:
        if emo not in constraints.get("ok_emo", set()):
            raise ChunkProtocolError(
                "illegal_line_emoticon", f"未知气泡 {normalized.get('emo')}",
            )
        normalized["emo"] = constraints.get("sym2cn", {}).get(emo, emo)

    act = str(normalized.get("act") or "")
    if act and "ok_act" in constraints and act not in constraints.get("ok_act", set()):
        raise ChunkProtocolError("illegal_line_action", f"未知动作 {act}")

    fx = str(normalized.get("fx") or "")
    if fx and "ok_fx" in constraints and fx != "无" and not is_fx_allowed(fx):
        raise ChunkProtocolError("illegal_line_effect", f"未知效果 {fx}")

    for field, code, label in (
        ("se", "illegal_line_sound", "未知音效"),
        ("bg", "illegal_line_background", "未知背景"),
        ("bgfx", "illegal_line_background_effect", "未知背景效果"),
        ("shot", "illegal_line_shot_target", "射击目标不是可显示角色"),
    ):
        value = str(normalized.get(field) or "")
        allow_key = f"ok_{field}"
        if value and allow_key in constraints and value not in constraints.get(allow_key, set()):
            raise ChunkProtocolError(code, f"{label} {value}")
    return normalized


def validate_chunk_response(
    response: Any, targets: Sequence[Mapping[str, Any]], visible_ids: Iterable[str] = (),
    *, cast: Mapping[str, Any] = {}, constraints: Mapping[str, Any] = {},
    initial_visible_characters: Sequence[str] | None = None,
) -> Dict[str, Any]:
    expanded_compact = isinstance(response, _ExpandedChunkResponse)
    director_intents = getattr(response, "director_intents", {})
    annotation_intents = getattr(response, "annotation_intents", {})
    response = _require_dict(response, "invalid_response", "模型响应必须是对象")
    lines = response.get("lines")
    if not isinstance(lines, list):
        raise ChunkProtocolError("invalid_lines", "lines 必须是数组")
    expected = {str(item.get("annotation_id")): str(item.get("text_fingerprint") or "") for item in targets}
    targets_by_id = {str(item.get("annotation_id")): item for item in targets}
    target_ordinals = {
        str(item.get("annotation_id")): index
        for index, item in enumerate(targets, start=1)
    }
    seen = set()
    rows_by_id: Dict[str, Dict[str, Any]] = {}
    diagnostics: List[Dict[str, str]] = []
    unsafe_spacing_details: List[str] = []
    cast_names = set(cast) if isinstance(cast, Mapping) else set()
    displayable_names = {
        name for name, character in cast.items()
        if isinstance(character, Mapping) and character.get("portrait") and not character.get("narrator")
    } if isinstance(cast, Mapping) else set()
    # ``None`` preserves the protocol helper's historical standalone behavior.
    # Live annotation passes the previous shot explicitly so a reaction cannot
    # target an actor who merely exists in the cast but is still off camera.
    tracking_visibility = initial_visible_characters is not None
    active_visible = list(dict.fromkeys(
        str(name) for name in (initial_visible_characters or ())
        if str(name) in displayable_names
    ))[:3]
    for row in lines:
        row = _validate_annotation_row(row)
        source_id = row["source_id"]
        if source_id in seen:
            raise ChunkProtocolError("duplicate_target", f"目标行重复: {source_id}")
        if source_id not in expected:
            raise ChunkProtocolError("unknown_target", f"响应包含未知目标行: {source_id}")
        seen.add(source_id)
        if row["text_fingerprint"] != expected[source_id]:
            raise ChunkProtocolError("fingerprint_mismatch", f"原文指纹不匹配: {source_id}")
        direction_source = row.get("direction")
        if str(row.get("fx") or "").strip() == "无":
            direction_source = dict(direction_source or {})
            continuity = dict(direction_source.get("continuity") or {})
            existing_fx_command = continuity.get("fx")
            if existing_fx_command not in (None, "none", "end"):
                raise ChunkProtocolError(
                    "invalid_line",
                    "fx=无 与 continuity.fx 的开始/升级指令冲突",
                )
            continuity["fx"] = "end"
            direction_source["continuity"] = continuity
        direction, row_diagnostics = normalize_director(
            direction_source,
            cast_names=cast_names,
            displayable_names=displayable_names,
        )
        for diagnostic in row_diagnostics:
            diagnostic.setdefault("source_id", source_id)
        normalized_row = dict(row)
        normalized_row["direction"] = direction
        positions = direction.get("positions") or {}
        profiles = constraints.get("portrait_profiles_by_name") or {}
        positioned = list(positions)
        for index, first in enumerate(positioned):
            for second in positioned[index + 1:]:
                required = max(
                    int((profiles.get(first) or {}).get("min_slot_gap") or 1),
                    int((profiles.get(second) or {}).get("min_slot_gap") or 1),
                )
                if abs(positions[first] - positions[second]) < required:
                    unsafe_spacing_details.append(
                        f"TARGET i={target_ordinals[source_id]} ({source_id}): "
                        f"{first}@{positions[first]} 与 {second}@{positions[second]} "
                        f"至少间隔 {required}"
                    )
        for layer, command in list(direction.get("continuity", {}).items()):
            if command in {"start", "escalate"} and not normalized_row.get(layer):
                direction["continuity"][layer] = "none"
                row_diagnostics.append({
                    "code": "director_continuity_without_value", "level": "warning",
                    "field": f"continuity.{layer}",
                    "message": f"continuity.{layer}={command} requires a {layer} value",
                })
        raw_intent = (
            director_intents.get(source_id, {})
            if expanded_compact else row.get("direction", {})
        )
        target_item = targets_by_id.get(source_id, {})
        speaker_name = str(target_item.get("who") or "")
        speaker_character = cast.get(speaker_name) if isinstance(cast, Mapping) else None
        normalized_row = _validate_line_resources(
            normalized_row, target_item,
            cast if isinstance(cast, Mapping) else {}, constraints,
        )
        reaction_visible = None
        if isinstance(raw_intent, Mapping) and "visible_characters" in raw_intent:
            reaction_visible = direction.get("visible_characters") or []
            if tracking_visibility:
                active_visible = list(dict.fromkeys(
                    str(name) for name in reaction_visible
                    if str(name) in displayable_names
                ))[:3]
        elif tracking_visibility:
            reaction_visible = list(active_visible)
        normalized_row["reactions"] = _normalize_reactions(
            row.get("reactions", []),
            cast=cast if isinstance(cast, Mapping) else {},
            constraints=constraints,
            visible=reaction_visible,
            owner=speaker_name,
        )
        reveal = str(normalized_row.get("reveal") or "")
        if reveal:
            if not (
                isinstance(speaker_character, Mapping)
                and speaker_character.get("portrait")
                and not speaker_character.get("narrator")
            ):
                raise ChunkProtocolError(
                    "invalid_line", "line.reveal 只能用于本行有立绘的说话者",
                )
            if str(direction.get("shot_transition") or "") == "cut":
                raise ChunkProtocolError(
                    "invalid_line", "line.reveal 不能与整镜硬切同时使用",
                )
        if tracking_visibility:
            # Speaking does not prove that the portrait is on camera: an
            # authored listener shot may deliberately keep the voice outside
            # the frame. Only an explicit shot or reveal advances visibility.
            if normalized_row.get("reveal") and speaker_name not in active_visible:
                active_visible.append(speaker_name)
                active_visible = active_visible[:3]
        # An explicit listener shot can keep the speaker off screen.  That is
        # an authored shot/reverse-shot decision, not a protocol violation.
        normalized_row["direction_intent"] = _normalized_direction_intent(
            raw_intent if isinstance(raw_intent, Mapping) else {}, direction,
        )
        normalized_row["annotation_intent_fields"] = sorted(
            annotation_intents.get(source_id, ())
            if expanded_compact else (
                name for name in ANNOTATION_FIELDS if name in row
            )
        )
        rows_by_id[source_id] = normalized_row
        diagnostics.extend(row_diagnostics)
    missing = set(expected) - seen
    if missing:
        raise ChunkProtocolError("missing_target", f"响应缺少目标行: {sorted(missing)}")
    if unsafe_spacing_details:
        raise ChunkProtocolError(
            "unsafe_direction_spacing",
            "以下站位会造成立绘重叠，请在同一次返修中全部修正："
            + "; ".join(unsafe_spacing_details),
        )
    state = _validate_state_delta(response.get("state_delta", {}))
    events = _validate_events(response.get("memory_events", []), set(expected) | set(visible_ids))
    beats = _validate_beats(response.get("beats", []), expected, cast, constraints)
    return {
        "lines_by_id": rows_by_id, "state_delta": state,
        "memory_events": events, "beats": beats, "diagnostics": diagnostics,
    }


def validate_review_patches(response: Any, items: Sequence[Mapping[str, Any]], constraints: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Accept only annotation-field patches against existing source items."""
    if not isinstance(response, dict) or not isinstance(response.get("patches"), list):
        return []
    by_id = {str(item.get("annotation_id")): item for item in items if item.get("kind") == "line"}
    allowed = set(ANNOTATION_FIELDS)
    result = []
    for patch in response["patches"]:
        if not isinstance(patch, dict):
            continue
        source_id = str(patch.get("source_id") or "")
        field = str(patch.get("field") or "")
        if source_id not in by_id or field not in allowed:
            continue
        evidence_ids = patch.get("evidence_source_ids")
        if not isinstance(evidence_ids, list) or not evidence_ids or not set(evidence_ids) <= set(by_id):
            continue
        if "text" in field or field == "raw":
            continue
        result.append({
            "source_id": source_id, "field": field,
            "before": patch.get("before"), "after": patch.get("after"),
            "reason": str(patch.get("reason") or "")[:240],
            "evidence_source_ids": list(evidence_ids),
        })
    return result
