"""Strict, source-identity based protocol for stateful annotation calls."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence

from director_state import (
    BEAT_REASONS,
    CONTINUITY_STATES,
    DIRECTION_REASONS,
    FOCUS_KINDS,
    RELATION_DISTANCES,
    SCENE_FUNCTIONS,
    SCENE_TYPES,
    default_director,
    normalize_director,
)


ANNOTATION_FIELDS = (
    "face", "emo", "act", "fx", "se", "bg", "bg_request", "place",
    "shake", "bgfx", "trans", "move", "shot",
)
ANNOTATION_FIELD_TYPES = {
    name: bool if name == "shake" else int if name == "move" else str
    for name in ANNOTATION_FIELDS
}
LINE_REQUIRED_FIELDS = set(ANNOTATION_FIELDS) | {"source_id", "text_fingerprint"}
LINE_FIELDS = LINE_REQUIRED_FIELDS | {"direction"}
STATE_FIELDS = {
    "background", "place", "bgfx", "visible_characters", "positions",
    "last_faces", "recent_emoticons", "recent_actions", "recent_sounds",
    "open_threads",
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
}
STATE_SCHEMA_TYPES = {str: "string", list: "array", dict: "object"}
EVENT_FIELDS = {
    "kind", "participants", "keywords", "summary", "source_ids",
    "evidence", "importance", "status",
}
BEAT_FIELDS = {"anchor_id", "position", "who", "face", "emo", "act", "wait_ms", "reason"}
MAX_BEAT_WAIT_MS = 10_000
CONTINUITY_LAYERS = {"face", "emo", "act", "fx", "bgfx"}
DIRECTION_STRING_FIELDS = {
    "scene_type", "scene_function", "emotion_phase", "subtext",
    "relation_distance", "focus_kind", "focus_character",
    "reaction_target", "reason",
}
DIRECTION_FIELDS = DIRECTION_STRING_FIELDS | {"visible_characters", "continuity"}


class ChunkProtocolError(ValueError):
    def __init__(self, code: str, detail: str, retryable: bool = True):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable


class _ExpandedChunkResponse(dict):
    def __init__(self, *args: Any, director_intents: Mapping[str, Any], **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.director_intents = dict(director_intents)


def _field(name: str, description: str, field_type: str = "string") -> Dict[str, Any]:
    value: Dict[str, Any] = {"type": field_type, "description": description}
    if field_type == "integer":
        value["minimum"] = 0
    return value


def _direction_schema() -> Dict[str, Any]:
    properties: Dict[str, Any] = {
        "scene_type": {"type": "string", "enum": list(SCENE_TYPES)},
        "scene_function": {"type": "string", "enum": list(SCENE_FUNCTIONS)},
        "emotion_phase": {"type": "string", "maxLength": 160},
        "subtext": {"type": "string", "maxLength": 160},
        "relation_distance": {"type": "string", "enum": list(RELATION_DISTANCES)},
        "focus_kind": {"type": "string", "enum": list(FOCUS_KINDS)},
        "focus_character": {"type": "string"},
        "reaction_target": {"type": "string", "maxLength": 160},
        "visible_characters": {"type": "array", "items": {"type": "string"}},
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
    return {"type": "object", "properties": properties, "additionalProperties": False}


def _validate_direction_wire(value: Any, field: str) -> Mapping[str, Any]:
    direction = _require_dict(value, "invalid_line", f"{field} must be an object")
    if not set(direction) <= DIRECTION_FIELDS:
        raise ChunkProtocolError("invalid_line", f"{field} contains unknown fields")
    for name in DIRECTION_STRING_FIELDS:
        if name in direction and not isinstance(direction[name], str):
            raise ChunkProtocolError("invalid_line", f"{field}.{name} must be a string")
    visible = direction.get("visible_characters", [])
    if not isinstance(visible, list) or any(not isinstance(name, str) for name in visible):
        raise ChunkProtocolError("invalid_line", f"{field}.visible_characters must be a string array")
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


def build_chunk_schema(target_ids: Sequence[str]) -> Dict[str, Any]:
    """Build a strict schema whose source_id enum is limited to this chunk."""
    row_properties: Dict[str, Any] = {
        "source_id": {"type": "string", "enum": list(target_ids)},
        "text_fingerprint": _field("text_fingerprint", "原文指纹，必须原样返回"),
    }
    row_required = ["source_id", "text_fingerprint"]
    for name in ANNOTATION_FIELDS:
        field_type = "boolean" if name == "shake" else "integer" if name == "move" else "string"
        row_properties[name] = _field(name, "不使用时填空值", field_type)
        row_required.append(name)
    row_properties["direction"] = _direction_schema()
    row_schema = {
        "type": "object", "properties": row_properties,
        "required": row_required, "additionalProperties": False,
    }
    state_properties = {
        name: {"type": [STATE_SCHEMA_TYPES[field_type], "null"]}
        for name, field_type in STATE_FIELD_TYPES.items()
    }
    event_properties = {
        "kind": {"type": "string"}, "participants": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}}, "summary": {"type": "string"},
        "source_ids": {"type": "array", "items": {"type": "string"}}, "evidence": {"type": "string"},
        "importance": {"type": "number", "minimum": 0, "maximum": 1},
        "status": {"type": "string", "enum": ["open", "resolved", "reference"]},
    }
    beat_properties = {
        "anchor_id": {"type": "string", "enum": list(target_ids)},
        "position": {"type": "string", "enum": ["before", "after"]},
        "who": _field("who", "执行无台词反应的角色名"),
        "face": _field("face", "该角色资源表中的表情编号，不使用时填空串"),
        "emo": _field("emo", "气泡中文名，不使用时填空串"),
        "act": _field("act", "原地动作英文名，不使用时填空串"),
        "wait_ms": {
            "type": "integer", "minimum": 0, "maximum": MAX_BEAT_WAIT_MS,
            "description": "独立无台词反应的显式等待毫秒数",
        },
        "reason": {"type": "string", "enum": list(BEAT_REASONS)},
    }
    return {
        "type": "object",
        "properties": {
            "lines": {"type": "array", "items": row_schema},
            "state_delta": {"type": "object", "properties": state_properties, "additionalProperties": False},
            "memory_events": {"type": "array", "items": {"type": "object", "properties": event_properties, "required": sorted(EVENT_FIELDS), "additionalProperties": False}},
            "beats": {"type": "array", "items": {
                "type": "object", "properties": beat_properties,
                "required": sorted(BEAT_FIELDS), "additionalProperties": False,
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
    row_properties: Dict[str, Any] = {
        "i": {"type": "integer", "minimum": 1, "maximum": int(target_count)},
    }
    for name in ANNOTATION_FIELDS:
        field_type = "boolean" if name == "shake" else "integer" if name == "move" else "string"
        row_properties[name] = {"type": field_type}
    row_properties["d"] = _direction_schema()
    row_schema = {
        "type": "object", "properties": row_properties,
        "required": ["i"], "additionalProperties": False,
    }
    state_properties = {
        name: {"type": [STATE_SCHEMA_TYPES[field_type], "null"]}
        for name, field_type in STATE_FIELD_TYPES.items()
    }
    event_properties = {
        "kind": {"type": "string"}, "participants": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}}, "summary": {"type": "string"},
        "source_ids": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": int(target_count)}}, "evidence": {"type": "string"},
        "importance": {"type": "number", "minimum": 0, "maximum": 1},
        "status": {"type": "string", "enum": ["open", "resolved", "reference"]},
    }
    beat_properties = {
        "anchor_id": {"type": "integer", "minimum": 1, "maximum": int(target_count)},
        "position": {"type": "string", "enum": ["before", "after"]},
        "who": _field("who", "执行无台词反应的角色名"),
        "face": _field("face", "表情编号，不使用时省略"),
        "emo": _field("emo", "气泡中文名，不使用时省略"),
        "act": _field("act", "动作英文名，不使用时省略"),
        "wait_ms": {"type": "integer", "minimum": 0, "maximum": MAX_BEAT_WAIT_MS},
        "reason": {"type": "string", "enum": list(BEAT_REASONS)},
    }
    return {
        "type": "object", "properties": {
            "lines": {"type": "array", "items": row_schema},
            "state_delta": {"type": "object", "properties": state_properties, "additionalProperties": False},
            "memory_events": {"type": "array", "items": {"type": "object", "properties": event_properties, "required": sorted(EVENT_FIELDS), "additionalProperties": False}},
            "beats": {"type": "array", "items": {"type": "object", "properties": beat_properties, "required": sorted(BEAT_FIELDS), "additionalProperties": False}},
        }, "required": ["lines", "state_delta", "memory_events"], "additionalProperties": False,
    }


def expand_compact_chunk_response(response: Any, targets: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Restore complete line identities/defaults before normal validation."""
    response = _require_dict(response, "invalid_response", "模型响应必须是对象")
    lines = response.get("lines")
    if not isinstance(lines, list):
        raise ChunkProtocolError("invalid_lines", "lines 必须是数组")
    expanded = []
    seen = set()
    director_intents: Dict[str, Dict[str, Any]] = {}
    for compact in lines:
        compact = _require_dict(compact, "invalid_line", "compact line 必须是对象")
        index = compact.get("i")
        if isinstance(index, bool) or not isinstance(index, int):
            raise ChunkProtocolError("invalid_line", "compact line.i 必须是整数")
        if not 1 <= index <= len(targets):
            raise ChunkProtocolError("unknown_target", f"compact line.i 超出目标范围: {index}")
        if index in seen:
            raise ChunkProtocolError("duplicate_target", f"目标行重复: {index}")
        seen.add(index)
        unknown = set(compact) - ({"i", "d"} | set(ANNOTATION_FIELDS))
        if unknown:
            raise ChunkProtocolError("invalid_line", f"compact line 包含未知字段: {sorted(unknown)}")
        direction_patch = _validate_direction_wire(compact.get("d", {}), "compact line.d")
        target = targets[index - 1]
        row = {
            "source_id": str(target.get("annotation_id") or ""),
            "text_fingerprint": str(target.get("text_fingerprint") or ""),
            **{name: (False if name == "shake" else 0 if name == "move" else "") for name in ANNOTATION_FIELDS},
            "direction": default_director(),
        }
        continuity_patch = direction_patch.get("continuity", {})
        row["direction"].update({
            name: value for name, value in direction_patch.items()
            if name != "continuity"
        })
        row["direction"]["continuity"].update(continuity_patch)
        if "d" in compact:
            director_intents[row["source_id"]] = dict(direction_patch)
        for name in ANNOTATION_FIELDS:
            if name in compact:
                row[name] = compact[name]
        expanded.append(row)
    expected = set(range(1, len(targets) + 1))
    missing = expected - seen
    if missing:
        raise ChunkProtocolError("missing_target", f"响应缺少目标行: {sorted(missing)}")
    expanded_beats = []
    for beat in response.get("beats", []):
        expanded_beat = dict(_require_dict(beat, "invalid_beat", "compact beat 必须是对象"))
        anchor_index = expanded_beat.get("anchor_id")
        if isinstance(anchor_index, bool) or not isinstance(anchor_index, int):
            raise ChunkProtocolError("invalid_beat", "compact beat.anchor_id 必须是整数")
        if not 1 <= anchor_index <= len(targets):
            raise ChunkProtocolError("unknown_beat_anchor", f"compact beat.anchor_id 超出目标范围: {anchor_index}")
        expanded_beat["anchor_id"] = str(targets[anchor_index - 1].get("annotation_id") or "")
        expanded_beats.append(expanded_beat)
    expanded_events = []
    for event in response.get("memory_events", []):
        expanded_event = dict(_require_dict(event, "invalid_memory_event", "compact memory_event 必须是对象"))
        source_ids = expanded_event.get("source_ids")
        if not isinstance(source_ids, list):
            raise ChunkProtocolError("invalid_memory_event", "compact memory_event.source_ids 必须是数组")
        mapped_ids = []
        for source_index in source_ids:
            if isinstance(source_index, bool) or not isinstance(source_index, int):
                raise ChunkProtocolError("invalid_memory_event", "compact memory_event.source_ids 必须使用整数索引")
            if not 1 <= source_index <= len(targets):
                raise ChunkProtocolError("unknown_event_source", f"compact event source 超出目标范围: {source_index}")
            mapped_ids.append(str(targets[source_index - 1].get("annotation_id") or ""))
        expanded_event["source_ids"] = mapped_ids
        expanded_events.append(expanded_event)
    return _ExpandedChunkResponse({
        "lines": expanded,
        "state_delta": response.get("state_delta", {}),
        "memory_events": expanded_events,
        **({"beats": expanded_beats} if "beats" in response else {}),
    }, director_intents=director_intents)


def _validate_beats(
    value: Any, expected_ids: Iterable[str], cast: Mapping[str, Any],
    constraints: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise ChunkProtocolError("invalid_beats", "beats 必须是数组")
    expected = set(expected_ids)
    result = []
    for beat in value:
        beat = _require_dict(beat, "invalid_beat", "beats 每项必须是对象")
        if set(beat) != BEAT_FIELDS:
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
        emo = beat["emo"]
        if emo and emo not in constraints.get("ok_emo", set()):
            raise ChunkProtocolError("illegal_beat_emoticon", f"未知气泡 {emo}")
        act = beat["act"]
        if act and act not in constraints.get("ok_act", set()):
            raise ChunkProtocolError("illegal_beat_action", f"未知动作 {act}")
        result.append({
            "anchor_id": anchor_id, "position": beat["position"], "who": who,
            "face": face.zfill(2) if face else "",
            "emo": constraints.get("sym2cn", {}).get(emo, emo), "act": act,
            "wait_ms": wait_ms, "reason": beat["reason"],
        })
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
        normalized[name] = field_value
    return normalized


def _validate_events(value: Any, visible_ids: Iterable[str]) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise ChunkProtocolError("invalid_memory_events", "memory_events 必须是数组")
    visible = set(visible_ids)
    result = []
    for event in value:
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
        field_value = row.get(name)
        if expected_type is int:
            valid = isinstance(field_value, int) and not isinstance(field_value, bool)
        else:
            valid = isinstance(field_value, expected_type)
        if not valid:
            raise ChunkProtocolError("invalid_line", f"line.{name} 类型不正确")
    return row


def validate_chunk_response(
    response: Any, targets: Sequence[Mapping[str, Any]], visible_ids: Iterable[str] = (),
    *, cast: Mapping[str, Any] = {}, constraints: Mapping[str, Any] = {},
) -> Dict[str, Any]:
    expanded_compact = isinstance(response, _ExpandedChunkResponse)
    director_intents = getattr(response, "director_intents", {})
    response = _require_dict(response, "invalid_response", "模型响应必须是对象")
    lines = response.get("lines")
    if not isinstance(lines, list):
        raise ChunkProtocolError("invalid_lines", "lines 必须是数组")
    expected = {str(item.get("annotation_id")): str(item.get("text_fingerprint") or "") for item in targets}
    seen = set()
    rows_by_id: Dict[str, Dict[str, Any]] = {}
    diagnostics: List[Dict[str, str]] = []
    cast_names = set(cast) if isinstance(cast, Mapping) else set()
    displayable_names = {
        name for name, character in cast.items()
        if isinstance(character, Mapping) and character.get("portrait") and not character.get("narrator")
    } if isinstance(cast, Mapping) else set()
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
        direction, row_diagnostics = normalize_director(
            row.get("direction"),
            cast_names=cast_names,
            displayable_names=displayable_names,
        )
        normalized_row = dict(row)
        normalized_row["direction"] = direction
        raw_intent = (
            director_intents.get(source_id, {})
            if expanded_compact else row.get("direction", {})
        )
        normalized_row["direction_intent"] = _normalized_direction_intent(
            raw_intent if isinstance(raw_intent, Mapping) else {}, direction,
        )
        rows_by_id[source_id] = normalized_row
        diagnostics.extend(row_diagnostics)
    missing = set(expected) - seen
    if missing:
        raise ChunkProtocolError("missing_target", f"响应缺少目标行: {sorted(missing)}")
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
