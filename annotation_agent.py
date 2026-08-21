"""Transactional orchestration for scene-aware screenplay annotation."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections import deque
from contextlib import contextmanager
from typing import Any, Callable, Collection, Dict, List, Mapping, Optional, Sequence

from director_state import SCENE_FUNCTIONS, SCENE_TYPES, apply_continuity

from annotation_chunks import (
    RunChunkController, assign_annotation_ids, build_chunks, build_scene_map,
    estimate_initial_chunk_limits, subdivide_chunk,
)
from annotation_memory import (
    AnnotationCheckpointStore,
    apply_state_delta,
    assemble_chunk_context,
    build_story_plan,
    complete_scene,
    initial_memory,
    merge_memory_events,
    retrieve_events,
)
from annotation_protocol import (
    ChunkProtocolError, build_chunk_schema, build_compact_chunk_schema,
    expand_compact_chunk_response, validate_chunk_response,
    validate_review_patches,
)
from annotation_safety import project_effective_annotation_row
from annotation_telemetry import (
    ReasoningTelemetryWriter, RequestTelemetryWriter, build_request_prompt_hashes,
)
from annotation_scene_planner import plan_scene_events, sanitize_scene_event_plan_for_cast
from direction_quality import (
    classify_quality_issue,
    is_automatic_repairable_quality_issue,
    sanitize_execution_beats,
    validate_execution_quality,
    validate_plan_quality,
)
from face_selection import silent_reaction_shortlists, target_face_shortlists
from prompt import build_repair_rules, select_repair_resources
from llm import EmptyModelResponseError, OutputCapacityError, RequestDeadlineError, StructuredOutputError


_CAPACITY_PROTOCOL_CODES = {"missing_target"}


# A semantic G2 repair may reconsider the local directing choice, but it must
# not make the already validated timeline structurally less valid.  Keep this
# list limited to deterministic camera/presence/geometry contradictions: the
# transaction guard rejects the candidate and preserves the original
# ``needs_review`` result; it never invents a reveal, cut, move, or cast member.
_G2_REPAIR_TRANSACTION_GUARD_CODES = frozenset({
    "reveal_person_not_present",
    "enter_person_already_present",
    "enter_without_arrival_evidence",
    "conceal_person_not_visible",
    "visible_over_three",
    "unsafe_spacing",
    "unmotivated_single_occupant_swap",
    "reframe_adds_character_without_reveal",
    "reframe_removes_character_without_conceal",
    "closeup_requires_hard_cut",
    "closeup_with_multiple_characters",
    "beat_performer_not_visible",
})


def _introduced_g2_repair_regressions(
    before: Mapping[str, Any], after: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Return deterministic structural findings introduced by a repair.

    A code at the same timeline anchor is treated as the same unresolved
    finding.  This lets a repair improve a different issue without pretending
    that every pre-existing review item was solved, while still catching a
    new failure at a later anchor after the repaired camera state propagates.
    """
    def identity(issue: Mapping[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(issue.get("code") or ""),
            str(issue.get("anchor_id") or issue.get("source_id") or ""),
            str(issue.get("position") or ""),
            str(issue.get("beat_id") or ""),
        )

    existing = {
        identity(issue)
        for issue in before.get("issues") or ()
        if isinstance(issue, Mapping)
        and str(issue.get("code") or "") in _G2_REPAIR_TRANSACTION_GUARD_CODES
    }
    return [
        copy.deepcopy(dict(issue))
        for issue in after.get("issues") or ()
        if isinstance(issue, Mapping)
        and str(issue.get("code") or "") in _G2_REPAIR_TRANSACTION_GUARD_CODES
        and identity(issue) not in existing
    ]


def _classify_chunk_error(exc: Exception) -> str:
    if isinstance(exc, OutputCapacityError):
        return "capacity"
    if isinstance(exc, ChunkProtocolError) and exc.code in _CAPACITY_PROTOCOL_CODES:
        return "capacity"
    if isinstance(exc, (ChunkProtocolError, StructuredOutputError, EmptyModelResponseError)):
        return "protocol"
    return "fatal"


def _is_request_deadline(exc: Exception) -> bool:
    return isinstance(exc, RequestDeadlineError)


def _chunk_error_code(exc: Exception) -> str:
    return str(getattr(exc, "code", "structured_output") or "structured_output")


def _chunk_error_detail(exc: Exception) -> str:
    return str(getattr(exc, "detail", "") or str(exc))


@contextmanager
def _temporary_reasoning_mode(provider: Any, mode: Optional[str]):
    if not mode:
        yield
        return
    override = getattr(provider, "temporary_reasoning_mode", None)
    if callable(override):
        with override(mode):
            yield
        return
    config = getattr(provider, "cfg", None)
    if not isinstance(config, dict):
        yield
        return
    previous = config.get("reasoning_mode")
    config["reasoning_mode"] = mode
    try:
        yield
    finally:
        if previous is None:
            config.pop("reasoning_mode", None)
        else:
            config["reasoning_mode"] = previous


def estimate_chunk_output_budget(
    target_lines: int, *, compact: bool, reasoning_mode: Optional[str], maximum: Optional[int],
) -> int:
    """Use the configured model output maximum without a smaller local cap."""
    if maximum not in (None, ""):
        return max(1, int(maximum))
    mode = str(reasoning_mode or "balanced").strip().lower()
    per_line = 75 if compact else 200
    visible_allowance = 1500 + max(1, int(target_lines)) * per_line
    reasoning_reserve = {
        "speed": 0,
        "minimal": 8_000,
        "low": 16_000,
        "balanced": 64_000,
        "medium": 64_000,
        "deep": 96_000,
        "high": 96_000,
        "xhigh": 128_000,
        "max": 128_000,
    }.get(mode, 64_000)
    estimate = visible_allowance + reasoning_reserve
    return max(1, max(1200, estimate))


def grow_chunk_output_budget(current: int, maximum: Optional[int]) -> Optional[int]:
    """Double a capacity-bound request without exceeding its configured ceiling."""
    current = max(1, int(current))
    cap = max(1, int(maximum or current))
    if current >= cap:
        return None
    return min(cap, max(current + 1, current * 2))


@contextmanager
def _temporary_output_budget(provider: Any, maximum: int):
    override = getattr(provider, "temporary_output_budget", None)
    if callable(override):
        with override(maximum):
            yield
        return
    yield


class AnnotationAgentError(RuntimeError):
    def __init__(
        self, stage: str, scene_id: str, chunk_id: str, detail: str,
        *, partial_result: Optional[Mapping[str, Any]] = None,
    ):
        super().__init__(f"{stage} {scene_id}/{chunk_id}: {detail}")
        self.stage = stage
        self.scene_id = scene_id
        self.chunk_id = chunk_id
        self.detail = detail
        self.partial_result = copy.deepcopy(dict(partial_result or {})) or None


def _emit(progress: Optional[Callable[..., None]], phase: str, current: int, total: int, detail: str) -> None:
    if progress:
        progress(phase, current, total, detail)


def _run_key(fingerprint: Mapping[str, Any]) -> str:
    value = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _checkpoint(
    memory: Mapping[str, Any], fingerprint: Mapping[str, Any], plan: Mapping[str, Any],
    rows: Mapping[str, Any], beats: Sequence[Mapping[str, Any]], *,
    director_plan: Mapping[str, Any],
    chunk_outputs: Mapping[str, Mapping[str, Any]] = {},
    chunk_order: Sequence[str] = (),
    resume_hints: Mapping[str, Any] = {},
) -> Dict[str, Any]:
    return {
        "schema_version": 3, "fingerprint": dict(fingerprint), "story_plan": dict(plan),
        "director_plan": copy.deepcopy(dict(director_plan)),
        "memory": copy.deepcopy(dict(memory)), "rows_by_id": copy.deepcopy(dict(rows)),
        "beats": copy.deepcopy(list(beats)),
        "chunk_outputs": copy.deepcopy(dict(chunk_outputs)),
        "chunk_order": list(chunk_order),
        "resume_hints": copy.deepcopy(dict(resume_hints)),
    }


def _base_input_hash(
    static_system: str, volatile: str, user: str,
    schema: Mapping[str, Any], target_count: int,
) -> str:
    identity = build_request_prompt_hashes(
        static_system, volatile, user, schema, target_count,
    )
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _attempt_response_provenance(
    provider: Any, previous_records: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Capture persisted-response identity without coupling to one provider."""
    current = list(getattr(provider, "request_records", []) or [])
    record = current[-1] if len(current) > len(previous_records) else None
    if not isinstance(record, Mapping):
        return {}
    keys = (
        "request_fingerprint", "response_sha256", "response_path",
        "raw_path", "raw_attempt",
    )
    return {key: copy.deepcopy(record[key]) for key in keys if record.get(key) is not None}


def _merge_director_rows(
    memory: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
    speakers_by_id: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    updated = copy.deepcopy(dict(memory))
    state = updated.setdefault("direction", {})
    continuity = dict(state.get("continuity") or {})
    for row in rows:
        director = row.get("direction") if isinstance(row, Mapping) else None
        intent = row.get("direction_intent") if isinstance(row, Mapping) else None
        source_id = str(row.get("source_id") or "")
        speaker = str(row.get("_speaker") or (speakers_by_id or {}).get(source_id) or "")
        presence = state.setdefault("scene_presence", {})
        if speaker and row.get("face"):
            state.setdefault("last_faces", {})[speaker] = str(row["face"])[:32]
        for field, state_field in (
            ("emo", "recent_emoticons"),
            ("act", "recent_actions"),
            ("se", "recent_sounds"),
        ):
            value = str(row.get(field) or "")
            if value:
                recent = list(state.get(state_field) or [])
                state[state_field] = (recent + [value[:160]])[-12:]
        for field in ("background", "place", "bgfx"):
            row_field = "bg" if field == "background" else field
            value = str(row.get(row_field) or "")
            if value:
                state[field] = value[:160]
        for name in row.get("_reveal") or []:
            if name:
                presence[name] = "present"
        for name in row.get("_enter") or []:
            if name:
                presence[name] = "present"
        for name in row.get("_exit") or []:
            if name:
                presence[name] = "absent"
        reactions = [
            value for value in row.get("_reactions") or []
            if isinstance(value, Mapping)
        ]
        for reaction in reactions:
            who = str(reaction.get("who") or "")
            face = str(reaction.get("face") or "")
            if who and face:
                state.setdefault("last_faces", {})[who] = face[:32]
            for field, state_field in (("emo", "recent_emoticons"), ("act", "recent_actions")):
                value = str(reaction.get(field) or "")
                if value:
                    recent = list(state.get(state_field) or [])
                    state[state_field] = (recent + [value[:160]])[-12:]

        has_direction_intent = (
            isinstance(director, Mapping) and isinstance(intent, Mapping) and bool(intent)
        )
        if has_direction_intent:
            focus = dict(state.get("focus") or {})
            if "focus_kind" in intent:
                focus["kind"] = str(director.get("focus_kind") or "speaker")[:32]
            if "focus_character" in intent:
                focus["character"] = str(director.get("focus_character") or "")[:160]
            state["focus"] = focus
            if "relation_distance" in intent:
                state["relation_distance"] = str(director.get("relation_distance") or "normal")[:32]
            if "emotion_phase" in intent:
                state["emotion_phase"] = str(director.get("emotion_phase") or "")[:160]
            if "scene_type" in intent:
                scene_type = str(director.get("scene_type") or "other")[:32]
                if scene_type != "other":
                    updated.setdefault("scene", {})["scene_type"] = scene_type
            if "scene_function" in intent:
                updated.setdefault("scene", {})["scene_function"] = str(
                    director.get("scene_function") or "dialogue"
                )[:32]
            if "subtext" in intent:
                state["subtext"] = str(director.get("subtext") or "")[:160]
            if "reaction_target" in intent:
                state["reaction_target"] = str(director.get("reaction_target") or "")[:160]
            if "visible_characters" in intent:
                state["shot_visible_characters"] = list(
                    director.get("visible_characters") or []
                )[:3]
            if "positions" in intent:
                state["positions"] = dict(director.get("positions") or {})
            if "shot_transition" in intent:
                state["shot_transition"] = str(director.get("shot_transition") or "")[:32]
            if "shot_operation" in intent:
                operation = str(director.get("shot_operation") or "")[:32]
                state["shot_operation"] = operation
                group = dict(state.get("shot_group") or {})
                if operation in {"switch_group", "impact_insert", "replace_center_subject"}:
                    group["group_id"] = source_id[:80]
                    group["status"] = "active"
                    group["spatial_mode"] = "insert" if operation == "impact_insert" else "stable"
                elif operation in {"continue_group", "expand_group", "shrink_group"}:
                    group.setdefault("group_id", source_id[:80])
                    group["status"] = "active"
                    group["spatial_mode"] = "reframe" if operation != "continue_group" else "stable"
                state["shot_group"] = group
            if "visible_characters" in intent:
                visible = [
                    str(name) for name in director.get("visible_characters") or []
                    if str(name)
                ][:3]
                group = dict(state.get("shot_group") or {})
                group["members"] = visible
                group["status"] = "active" if visible else "closed"
                focus_owner = str(
                    director.get("focus_character")
                    or (speaker if speaker in visible else "")
                    or group.get("focus_owner")
                    or ""
                )[:80]
                group["focus_owner"] = focus_owner if focus_owner in visible else ""
                state["shot_group"] = group

        visibility_is_explicit = has_direction_intent and "visible_characters" in intent
        positions_are_explicit = has_direction_intent and "positions" in intent
        line_reveal = [speaker] if speaker and row.get("reveal") else []
        revealed = list(row.get("_reveal") or []) + line_reveal
        entered = list(row.get("_enter") or [])
        concealed = {
            str(name) for name in row.get("_conceal") or [] if str(name)
        }
        for name in revealed + entered:
            if name:
                presence[name] = "present"
        for name in concealed:
            # conceal only removes a portrait from this shot; it explicitly
            # preserves the character's physical presence in the scene.
            presence[name] = "present"
        if (revealed or entered) and not visibility_is_explicit:
            visible = list(state.get("shot_visible_characters") or [])
            for name in revealed + entered:
                if name not in visible:
                    visible.append(name)
            state["shot_visible_characters"] = visible[:3]
        if row.get("_exit") and not visibility_is_explicit:
            exited = set(row["_exit"])
            state["shot_visible_characters"] = [
                name for name in state.get("shot_visible_characters") or []
                if name not in exited
            ][:3]
        if concealed:
            state["shot_visible_characters"] = [
                name for name in state.get("shot_visible_characters") or []
                if name not in concealed
            ][:3]
            group = dict(state.get("shot_group") or {})
            group["members"] = [
                name for name in group.get("members") or [] if name not in concealed
            ][:3]
            if group.get("focus_owner") in concealed:
                group["focus_owner"] = ""
            group["status"] = "active" if group["members"] else "closed"
            state["shot_group"] = group
        if not positions_are_explicit:
            positions = dict(state.get("positions") or {})
            for name, slot in dict(row.get("_position_updates") or {}).items():
                if name and isinstance(slot, int) and not isinstance(slot, bool) and 1 <= slot <= 5:
                    positions[str(name)] = slot
            move = row.get("move")
            if speaker and isinstance(move, int) and not isinstance(move, bool) and 1 <= move <= 5:
                positions[speaker] = move
            for name in row.get("_exit") or []:
                positions.pop(str(name), None)
            state["positions"] = positions
        if concealed:
            positions = dict(state.get("positions") or {})
            for name in concealed:
                positions.pop(name, None)
            state["positions"] = positions
        if has_direction_intent and "visible_characters" in intent:
            for name in director.get("visible_characters") or []:
                if name:
                    presence[name] = "present"
        commands = dict(intent.get("continuity") or {}) if has_direction_intent else {}
        values = {name: str(row.get(name) or "")[:160] for name in commands}
        changes = apply_continuity(continuity, values, commands)
        for name, command in commands.items():
            if command != "none" and name in changes:
                continuity[name] = changes[name]

        # Keep the latest executable node, including silent beats, available
        # to the next chunk. This runs after direction/state updates so the
        # summary reflects the actual resulting camera and phase.
        direction_for_node = dict(director) if isinstance(director, Mapping) else {}
        state["last_performance_node"] = {
            "source_id": source_id[:120],
            "speaker": speaker[:80],
            "silent": bool(row.get("_silent", False)),
            "face": str(
                row.get("face")
                or (state.get("last_faces") or {}).get(speaker)
                or ""
            )[:32],
            "emo": str(row.get("emo") or "")[:80],
            "act": str(row.get("act") or "")[:80],
            "fx": str(row.get("fx") or "")[:80],
            "visible_characters": [
                str(name)[:80] for name in (
                    direction_for_node.get("visible_characters")
                    or state.get("shot_visible_characters") or []
                ) if str(name)
            ][:3],
            "focus_character": str(
                direction_for_node.get("focus_character")
                or (state.get("focus") or {}).get("character") or ""
            )[:80],
            "emotion_phase": str(
                direction_for_node.get("emotion_phase")
                or state.get("emotion_phase") or ""
            )[:160],
            "reactions": [
                {
                    "who": str(reaction.get("who") or "")[:80],
                    "face": str(reaction.get("face") or "")[:32],
                    "emo": str(reaction.get("emo") or "")[:80],
                    "act": str(reaction.get("act") or "")[:80],
                }
                for reaction in reactions
                if str(reaction.get("who") or "")
            ][:3],
        }
    state["continuity"] = continuity
    return updated


def _effective_director_rows(
    rows_by_id: Mapping[str, Mapping[str, Any]],
    targets: Sequence[Mapping[str, Any]],
    cast: Mapping[str, Any],
    constraints: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Project model rows to the values that can actually reach the script."""
    effective_rows = []
    for item in targets:
        source_id = str(item.get("annotation_id") or "")
        row = rows_by_id.get(source_id)
        if not isinstance(row, Mapping):
            continue
        character = cast.get(item.get("who")) if isinstance(cast, Mapping) else None
        if not isinstance(character, Mapping):
            continue
        effective, _clean, _dropped, _details = project_effective_annotation_row(
            row, item, character, constraints,
        )
        effective["_reactions"] = copy.deepcopy(list(effective.get("reactions") or ()))
        effective_rows.append(effective)
    return effective_rows


def _interleaved_director_events(
    rows_by_id: Mapping[str, Mapping[str, Any]],
    targets: Sequence[Mapping[str, Any]],
    beats: Sequence[Mapping[str, Any]],
    cast: Mapping[str, Any],
    constraints: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Return before-beat, dialogue, after-beat events in their real timeline order."""
    effective = {
        str(row.get("source_id") or ""): row
        for row in _effective_director_rows(rows_by_id, targets, cast, constraints)
    }
    grouped: Dict[tuple[str, str], List[Mapping[str, Any]]] = {}
    for beat in beats:
        key = (str(beat.get("anchor_id") or ""), str(beat.get("position") or "after"))
        grouped.setdefault(key, []).append(beat)

    def beat_event(beat: Mapping[str, Any], ordinal: int) -> Dict[str, Any]:
        direction = {
            field: copy.deepcopy(beat[field])
            for field in ("visible_characters", "positions", "shot_transition", "shot_operation")
            if field in beat
        }
        entries = list(beat.get("reveal") or []) + list(beat.get("enter") or [])
        return {
            "source_id": str(beat.get("beat_id") or f"{beat.get('anchor_id')}:beat:{ordinal}"),
            "direction": direction,
            "direction_intent": copy.deepcopy(direction),
            "face": str(beat.get("face") or ""),
            "emo": str(beat.get("emo") or ""),
            "act": str(beat.get("act") or ""),
            "se": str(beat.get("se") or ""),
            "bg": str(beat.get("bg") or ""),
            "place": str(beat.get("place") or ""),
            "bgfx": str(beat.get("bgfx") or ""),
            "_speaker": str(beat.get("who") or ""),
            "_silent": True,
            "_reveal": [str(entry.get("who") or "") for entry in beat.get("reveal") or []],
            "_conceal": [str(entry.get("who") or "") for entry in beat.get("conceal") or []],
            "_enter": [str(entry.get("who") or "") for entry in beat.get("enter") or []],
            "_exit": [str(entry.get("who") or "") for entry in beat.get("exit") or []],
            "_position_updates": {
                str(entry.get("who") or ""): int(entry.get("slot") or 0)
                for entry in entries
                if isinstance(entry, Mapping)
                and str(entry.get("who") or "")
                and isinstance(entry.get("slot"), int)
                and not isinstance(entry.get("slot"), bool)
                and 1 <= int(entry.get("slot")) <= 5
            },
            "_reactions": copy.deepcopy(list(beat.get("reactions") or [])),
        }

    timeline: List[Dict[str, Any]] = []
    ordinal = 0
    for item in targets:
        source_id = str(item.get("annotation_id") or "")
        for beat in grouped.get((source_id, "before"), []):
            timeline.append(beat_event(beat, ordinal))
            ordinal += 1
        if source_id in effective:
            timeline.append(dict(effective[source_id]))
        for beat in grouped.get((source_id, "after"), []):
            timeline.append(beat_event(beat, ordinal))
            ordinal += 1
    return timeline


def _resolve_response_face_tokens(
    response: Any,
    *, face_tokens_by_target: Mapping[str, Mapping[str, str]],
    silent_tokens_by_beat: Mapping[tuple[str, str, str], Mapping[str, str]],
    face_tokens_by_character: Mapping[str, Mapping[str, str]] = {},
) -> None:
    """Resolve public semantic face tokens to private clip ids in place."""
    if isinstance(response, Mapping) and isinstance(response.get("lines"), list):
        for response_row in response["lines"]:
            if not isinstance(response_row, dict):
                continue
            source_id = str(response_row.get("source_id") or "")
            face_value = str(response_row.get("face") or "")
            token_map = face_tokens_by_target.get(source_id) or {}
            if token_map and face_value:
                resolved_face = token_map.get(face_value)
                if not resolved_face:
                    raise ChunkProtocolError(
                        "face_outside_shortlist",
                        f"{source_id} 的 face 必须原样使用当前 [Emo:语义] 候选；"
                        f"收到：{face_value!r}；可用："
                        f"{','.join(f'{token!r}->{face_id!r}' for token, face_id in token_map.items()) or '留空'}",
                    )
                response_row["face"] = resolved_face
            for reaction in response_row.get("reactions") or ():
                if not isinstance(reaction, dict):
                    continue
                reaction_who = str(reaction.get("who") or "")
                reaction_face = str(reaction.get("face") or "")
                reaction_tokens = face_tokens_by_character.get(reaction_who) or {}
                if not reaction_tokens or not reaction_face:
                    continue
                resolved_face = reaction_tokens.get(reaction_face)
                if not resolved_face:
                    raise ChunkProtocolError(
                        "face_outside_shortlist",
                        f"{source_id}/{reaction_who} 的 reactions.face 必须使用该角色的已提供候选；"
                        f"收到：{reaction_face!r}；可用："
                        f"{','.join(f'{token!r}->{face_id!r}' for token, face_id in reaction_tokens.items()) or '留空'}",
                    )
                reaction["face"] = resolved_face
    if not (isinstance(response, Mapping) and isinstance(response.get("beats"), list)):
        return
    for response_beat in response["beats"]:
        if not isinstance(response_beat, dict):
            continue
        anchor_id = str(response_beat.get("anchor_id") or "")
        position = str(response_beat.get("position") or "after")
        who = str(response_beat.get("who") or "")
        token_map = silent_tokens_by_beat.get((anchor_id, position, who)) or {}
        # G2 may add a causally justified silent beat that G1 did not
        # enumerate.  Such a beat has no planner-specific shortlist, but its
        # actor can still have an unambiguous semantic face token in the
        # current chunk's character shortlist.  Resolve through that
        # character-level map instead of dropping the authored face or
        # rejecting an otherwise legal resource at protocol validation.
        if not token_map:
            token_map = face_tokens_by_character.get(who) or {}
        face_value = str(response_beat.get("face") or "")
        if token_map and face_value:
            resolved_face = token_map.get(face_value)
            if not resolved_face:
                raise ChunkProtocolError(
                    "face_outside_shortlist",
                    f"无对话框节点 {anchor_id}/{who} 的 face 必须使用对应 [Emo:语义] 候选；"
                    f"收到：{face_value!r}；可用："
                    f"{','.join(f'{token!r}->{face_id!r}' for token, face_id in token_map.items()) or '留空'}",
                )
            response_beat["face"] = resolved_face
        for reaction in response_beat.get("reactions") or ():
            if not isinstance(reaction, dict):
                continue
            reaction_who = str(reaction.get("who") or "")
            reaction_tokens = silent_tokens_by_beat.get(
                (anchor_id, position, reaction_who), {},
            )
            if not reaction_tokens:
                reaction_tokens = face_tokens_by_character.get(reaction_who) or {}
            reaction_face = str(reaction.get("face") or "")
            if reaction_tokens and reaction_face:
                resolved_face = reaction_tokens.get(reaction_face)
                if not resolved_face:
                    raise ChunkProtocolError(
                        "face_outside_shortlist",
                        f"无对话框节点 {anchor_id}/{reaction_who} 的 face 必须使用对应 [Emo:语义] 候选；"
                        f"收到：{reaction_face!r}；可用："
                        f"{','.join(f'{token!r}->{face_id!r}' for token, face_id in reaction_tokens.items()) or '留空'}",
                    )
                reaction["face"] = resolved_face


def _strip_nonportrait_line_resources(
    response: Mapping[str, Any],
    targets: Sequence[Mapping[str, Any]],
    cast: Mapping[str, Any],
) -> List[Dict[str, str]]:
    """Remove impossible line carriers while preserving an explicit audit.

    A model can occasionally attach a face/emo/act/fx to a named voice
    character (teacher, narrator, clerk) even though that character has no
    portrait.  This is a hard protocol violation, but retrying the whole
    chunk is wasteful and can repeatedly reproduce the same mistake.  Clear
    only those impossible fields before validation; the returned records are
    attached to the attempt diagnostics so the authored decision is never
    silently lost.
    """
    if not isinstance(response, Mapping) or not isinstance(response.get("lines"), list):
        return []
    targets_by_id = {
        str(item.get("annotation_id") or ""): item for item in targets
    }
    repairs: List[Dict[str, str]] = []
    for row in response["lines"]:
        if not isinstance(row, dict):
            continue
        target = targets_by_id.get(str(row.get("source_id") or ""))
        speaker = str((target or {}).get("who") or "")
        character = cast.get(speaker) if isinstance(cast, Mapping) else None
        if not isinstance(character, Mapping):
            continue
        if character.get("portrait") and not character.get("narrator"):
            continue
        for field in ("face", "emo", "act", "fx"):
            value = row.get(field)
            if value in (None, ""):
                continue
            row[field] = ""
            repairs.append({
                "source_id": str(row.get("source_id") or ""),
                "speaker": speaker,
                "field": field,
                "value": str(value),
                "reason": "non_portrait_speaker_resource",
            })
    return repairs


def _strip_nonportrait_validated_rows(
    rows_by_id: Mapping[str, Any],
    targets: Sequence[Mapping[str, Any]],
    cast: Mapping[str, Any],
) -> tuple[Dict[str, Any], List[Dict[str, str]]]:
    """Re-apply the hard line-resource boundary to checkpoint rows.

    Checkpoints contain post-validation ``lines_by_id`` rather than the wire
    ``lines`` array.  Older checkpoints can therefore outlive a protocol fix
    and otherwise bypass the fresh execution/repair sanitizer on replay.
    Return a copied row map plus the same auditable repair records used for a
    live model response; never mutate the checkpoint object in place.
    """
    cleaned = copy.deepcopy(dict(rows_by_id or {}))
    targets_by_id = {
        str(item.get("annotation_id") or ""): item for item in targets
    }
    repairs: List[Dict[str, str]] = []
    for key, row in cleaned.items():
        if not isinstance(row, dict):
            continue
        source_id = str(row.get("source_id") or key or "")
        target = targets_by_id.get(source_id)
        speaker = str((target or {}).get("who") or "")
        character = cast.get(speaker) if isinstance(cast, Mapping) else None
        if not isinstance(character, Mapping):
            continue
        if character.get("portrait") and not character.get("narrator"):
            continue
        for field in ("face", "emo", "act", "fx"):
            value = row.get(field)
            if value in (None, ""):
                continue
            row[field] = ""
            repairs.append({
                "source_id": source_id,
                "speaker": speaker,
                "field": field,
                "value": str(value),
                "reason": "non_portrait_speaker_resource",
            })
    return cleaned, repairs


def _merge_g2_repair(
    original: Mapping[str, Any], repaired: Mapping[str, Any],
    repaired_ids: set[str],
) -> Dict[str, Any]:
    """Replace only failed anchors while retaining persistent beat identities."""
    merged = copy.deepcopy(dict(original))
    lines = copy.deepcopy(dict(original.get("lines_by_id") or {}))
    for source_id, repaired_row in (repaired.get("lines_by_id") or {}).items():
        if source_id not in repaired_ids:
            continue
        explicit_fields = repaired_row.get("annotation_intent_fields")
        if not isinstance(explicit_fields, Sequence) or isinstance(explicit_fields, (str, bytes)):
            lines[source_id] = copy.deepcopy(repaired_row)
            continue
        previous_row = copy.deepcopy(dict(lines.get(source_id) or {}))
        for identity_field in ("source_id", "text_fingerprint"):
            if identity_field in repaired_row:
                previous_row[identity_field] = copy.deepcopy(repaired_row[identity_field])
        for field in explicit_fields:
            if field in repaired_row:
                previous_row[str(field)] = copy.deepcopy(repaired_row[field])

        repaired_intent = repaired_row.get("direction_intent")
        if isinstance(repaired_intent, Mapping):
            previous_direction = copy.deepcopy(dict(previous_row.get("direction") or {}))
            previous_intent = copy.deepcopy(dict(previous_row.get("direction_intent") or {}))
            repaired_direction = repaired_row.get("direction") or {}
            for field in repaired_intent:
                if field == "continuity":
                    direction_continuity = dict(previous_direction.get("continuity") or {})
                    intent_continuity = dict(previous_intent.get("continuity") or {})
                    for layer in repaired_intent.get("continuity") or {}:
                        direction_continuity[layer] = copy.deepcopy(
                            (repaired_direction.get("continuity") or {}).get(layer)
                        )
                        intent_continuity[layer] = copy.deepcopy(
                            repaired_intent["continuity"].get(layer)
                        )
                    previous_direction["continuity"] = direction_continuity
                    previous_intent["continuity"] = intent_continuity
                else:
                    previous_direction[field] = copy.deepcopy(repaired_direction.get(field))
                    previous_intent[field] = copy.deepcopy(repaired_intent.get(field))
            previous_row["direction"] = previous_direction
            previous_row["direction_intent"] = previous_intent
        previous_row["annotation_intent_fields"] = sorted(set(
            previous_row.get("annotation_intent_fields") or ()
        ) | {str(field) for field in explicit_fields})
        lines[source_id] = previous_row
    previous_beats = copy.deepcopy(list(original.get("beats") or []))
    logical_ids: Dict[tuple[str, str, str, str], List[str]] = {}
    for beat in previous_beats:
        if str(beat.get("anchor_id") or "") not in repaired_ids:
            continue
        key = (
            str(beat.get("anchor_id") or ""), str(beat.get("position") or ""),
            str(beat.get("who") or ""), str(beat.get("reason") or ""),
        )
        logical_ids.setdefault(key, []).append(str(beat.get("beat_id") or ""))
    beat_positions = {
        str(beat.get("beat_id") or ""): index
        for index, beat in enumerate(previous_beats)
        if str(beat.get("beat_id") or "")
    }
    for beat in repaired.get("beats") or []:
        row = copy.deepcopy(dict(beat))
        supplied_id = str(row.get("beat_id") or "")
        key = (
            str(row.get("anchor_id") or ""), str(row.get("position") or ""),
            str(row.get("who") or ""), str(row.get("reason") or ""),
        )
        candidates = [value for value in logical_ids.get(key, []) if value]
        matched_id = supplied_id if supplied_id in beat_positions else ""
        if not matched_id and len(candidates) == 1:
            matched_id = candidates[0]
        if matched_id:
            row["beat_id"] = matched_id
            previous_beats[beat_positions[matched_id]] = row
        else:
            previous_beats.append(row)
            if supplied_id:
                beat_positions[supplied_id] = len(previous_beats) - 1
    merged["lines_by_id"] = lines
    merged["beats"] = previous_beats
    merged["state_delta"] = {
        **dict(original.get("state_delta") or {}),
        **dict(repaired.get("state_delta") or {}),
    }
    repaired_events = copy.deepcopy(list(repaired.get("memory_events") or []))
    if repaired_events:
        merged["memory_events"] = [
            copy.deepcopy(event) for event in original.get("memory_events") or []
            if not repaired_ids & {str(value) for value in event.get("source_ids") or []}
        ] + repaired_events
    else:
        # The repair schema requires memory_events even for a camera-only patch.
        # An empty array therefore means "no memory patch", not "delete every
        # event touching this anchor".
        merged["memory_events"] = copy.deepcopy(list(original.get("memory_events") or []))
    merged["diagnostics"] = list(original.get("diagnostics") or []) + list(
        repaired.get("diagnostics") or []
    )
    return merged


def _g2_face_change_token_options(
    targets: Sequence[Mapping[str, Any]],
    validated: Mapping[str, Any],
    report: Mapping[str, Any],
    face_tokens_by_target: Mapping[str, Mapping[str, str]],
    memory: Mapping[str, Any] | None = None,
) -> Dict[str, Dict[str, str]]:
    """Keep a face-change repair distinct from adjacent physical faces."""
    rows = validated.get("lines_by_id") or {}
    ordered_ids = [str(target.get("annotation_id") or "") for target in targets]
    speakers = {
        str(target.get("annotation_id") or ""): str(target.get("who") or "")
        for target in targets
    }
    positions = {source_id: index for index, source_id in enumerate(ordered_ids)}
    result: Dict[str, Dict[str, str]] = {
        str(source_id): dict(tokens)
        for source_id, tokens in face_tokens_by_target.items()
    }
    for issue in report.get("issues") or ():
        if "face_change" not in {str(value) for value in issue.get("missing") or ()}:
            continue
        source_id = str(issue.get("anchor_id") or "")
        if source_id not in positions or source_id not in result:
            continue
        who = speakers.get(source_id, "")
        disallowed = {str((rows.get(source_id) or {}).get("face") or "")}
        start_faces = ((memory or {}).get("direction") or {}).get("last_faces") or {}
        disallowed.add(str(start_faces.get(who) or ""))
        origin = positions[source_id]
        for step in (-1, 1):
            cursor = origin + step
            while 0 <= cursor < len(ordered_ids):
                neighbor_id = ordered_ids[cursor]
                if speakers.get(neighbor_id) == who:
                    face = str((rows.get(neighbor_id) or {}).get("face") or "")
                    if face:
                        disallowed.add(face)
                        break
                cursor += step
        disallowed.discard("")
        filtered = {
            token: face_id
            for token, face_id in result[source_id].items()
            if str(face_id) not in disallowed
        }
        if filtered:
            result[source_id] = filtered
    return result


def _compact_g2_repair_issues(
    issues: Sequence[Mapping[str, Any]],
    *,
    anchor_ids: Optional[Collection[str]] = None,
) -> List[Dict[str, Any]]:
    """Collapse repeated span failures scoped to the current repair TARGET."""
    allowed = {str(value) for value in anchor_ids or () if str(value)}
    high = [
        issue for issue in issues
        if str(issue.get("severity") or "high") in {"critical", "high"}
    ]
    result: List[Dict[str, Any]] = []
    seen_spans = set()
    keys = (
        "code", "message", "anchor_id", "beat_id", "event_id",
        "subject", "subjects", "missing", "visible", "previous", "current",
        "expected", "observed", "require_all", "span_start", "hold_until_id",
    )
    for issue in high:
        code = str(issue.get("code") or "")
        anchor_id = str(issue.get("anchor_id") or "")
        if allowed and anchor_id not in allowed:
            continue
        if code == "planned_shot_span_unfulfilled":
            signature = (
                str(issue.get("event_id") or ""),
                tuple(str(value) for value in issue.get("expected") or ()),
                str(issue.get("span_start") or anchor_id),
                str(issue.get("hold_until_id") or ""),
            )
            if signature in seen_spans:
                continue
            seen_spans.add(signature)
        row = {
            key: issue.get(key)
            for key in keys
            if issue.get(key) not in (None, "", [])
        }
        if code == "planned_shot_span_unfulfilled":
            row["anchor_id"] = str(issue.get("span_start") or anchor_id)
        result.append(row)
    return result


def _compact_g2_previous_lines(
    lines_by_id: Mapping[str, Mapping[str, Any]], source_ids: Sequence[str],
) -> Dict[str, Dict[str, Any]]:
    """Project previous execution to fields that can actually be repaired."""
    scalar_fields = (
        "source_id", "face", "emo", "act", "fx", "se", "bg", "bg_request",
        "place", "shake", "bgfx", "trans", "move", "shot", "reveal", "reactions",
    )
    direction_fields = (
        "scene_type", "scene_function", "emotion_phase", "subtext",
        "relation_distance", "shot_transition", "shot_operation", "focus_kind",
        "focus_character", "reaction_target", "visible_characters", "positions",
        "continuity", "reason",
    )
    result: Dict[str, Dict[str, Any]] = {}
    for source_id in source_ids:
        source = lines_by_id.get(source_id) or {}
        row = {
            key: copy.deepcopy(source.get(key))
            for key in scalar_fields
            if source.get(key) not in (None, "", [], {}, False, 0)
        }
        direction = source.get("direction") or {}
        direction_intent = source.get("direction_intent")
        recognized_intent = {
            key for key in direction_fields
            if isinstance(direction_intent, Mapping) and key in direction_intent
        }
        compact_direction = (
            {
                key: copy.deepcopy(direction.get(key))
                for key in direction_fields if key in recognized_intent
            }
            if recognized_intent else {
                key: copy.deepcopy(direction.get(key))
                for key in direction_fields
                if direction.get(key) not in (None, "", [], {}, False, 0, "none")
            }
        )
        if compact_direction:
            row["direction"] = compact_direction
        result[source_id] = row
    return result


def _g2_issue_diagnostics(
    report: Mapping[str, Any], *, scene_id: str, chunk_id: str,
) -> List[Dict[str, Any]]:
    result = []
    for raw_issue in report.get("issues") or ():
        issue = classify_quality_issue(raw_issue)
        severity = str(issue.get("severity") or "high")
        resolution = str(issue.get("resolution") or "ai_repair")
        result.append({
            **dict(issue), "level": severity,
            "scene_id": scene_id, "chunk_id": chunk_id, "stage": "G2",
            "needs_review": (
                resolution == "block"
                or is_automatic_repairable_quality_issue(issue)
            ),
        })
    return result


def _visible_items(items: Sequence[Mapping[str, Any]], chunk: Mapping[str, Any], before: int, after: int) -> List[Mapping[str, Any]]:
    dialogue = [i for i, item in enumerate(items) if item.get("kind") == "line"]
    targets = list(chunk.get("target_indices") or [])
    if not targets:
        return []
    positions = {index: pos for pos, index in enumerate(dialogue)}
    first = positions[targets[0]]
    last = positions[targets[-1]]
    indices = dialogue[max(0, first - before):last + 1 + after]
    return [items[index] for index in indices]


def _next_subdivision_limit(size: int) -> Optional[int]:
    for limit in (50, 30, 20, 10, 5):
        if size > limit:
            return limit
    return None


def annotation_mode_limits(mode: str) -> tuple[int, int, int]:
    mode = str(mode or "balanced").strip().lower()
    if mode == "speed":
        return 50, 60, 72
    if mode in {"deep", "high"}:
        return 16, 20, 24
    return 20, 24, 30


def run_annotation_agent(
    items: List[Dict[str, Any]], *, provider: Any, static_system: str,
    cast: Mapping[str, Any], constraints: Mapping[str, Any],
    usage_chain: Sequence[Mapping[str, Any]], checkpoint_store: AnnotationCheckpointStore,
    run_fingerprint: Mapping[str, Any], progress: Optional[Callable[..., None]] = None,
    model_activity: Optional[Callable[[Mapping[str, Any]], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None, target: Optional[int] = None,
    soft_limit: Optional[int] = None, hard_limit: Optional[int] = None,
    before: int = 15, after: int = 10,
    reasoning_mode: Optional[str] = None, annotation_max_tokens: Optional[int] = None,
    context_window_tokens: Optional[int] = None,
    story_type: str = "auto",
    scene_event_planning: bool = False,
) -> Dict[str, Any]:
    started_at = time.perf_counter()
    stats_before = dict(getattr(provider, "stats", {}) or {})
    request_count = 0
    retries = 0
    subdivisions = 0
    assign_annotation_ids(items)
    _emit(progress, "planning", 0, 1, "正在分析场景")
    scenes = build_scene_map(items, usage_chain)
    story_plan = build_story_plan(items, scenes, usage_chain)
    normalized_story_type = str(story_type or "auto").strip().lower()
    if normalized_story_type not in {"auto", "main", "event", "bond"}:
        normalized_story_type = "auto"

    def planned_scene_type(scene):
        value = str(scene.get("scene_type") or "").strip().lower()
        if value in SCENE_TYPES and value != "other":
            return value
        return normalized_story_type if normalized_story_type != "auto" else "other"

    def planned_scene_function(scene):
        value = str(scene.get("scene_function") or "").strip().lower()
        return value if value in SCENE_FUNCTIONS else "dialogue"

    def planned_active_modes(scene):
        modes = []
        for value in scene.get("active_modes") or []:
            mode = str(value or "").strip().lower()
            if mode in SCENE_TYPES and mode != "other" and mode not in modes:
                modes.append(mode)
        primary = planned_scene_type(scene)
        if primary in SCENE_TYPES and primary != "other" and primary not in modes:
            modes.insert(0, primary)
        return modes

    def planned_mode_source(scene):
        preflight_type = str(scene.get("scene_type") or "").strip().lower()
        if preflight_type in SCENE_TYPES and preflight_type != "other":
            return "preflight"
        return "user" if normalized_story_type != "auto" else "inferred"

    director_plan = {
        "story_type": normalized_story_type,
        "director_version": str(run_fingerprint.get("director_version") or ""),
        "scenes": [{
            "scene_id": str(scene.get("scene_id") or "")[:160],
            "scene_type": planned_scene_type(scene),
            "active_modes": planned_active_modes(scene),
            "scene_function": planned_scene_function(scene),
            "mode_source": planned_mode_source(scene),
        } for scene in story_plan["scenes"][:200]],
    }
    dialogue_items = [item for item in items if item.get("kind") == "line"]
    task_profile = {
        "target_lines": len(dialogue_items),
        "speaker_count": len({str(item.get("who") or "") for item in dialogue_items if item.get("who")}),
        "resource_complexity": min(
            10,
            len(cast or {}) + len(constraints.get("ok_bg") or set()) // 4 + len(usage_chain or []),
        ),
        "context_window_tokens": context_window_tokens,
        "annotation_max_tokens": annotation_max_tokens,
        "estimated_prompt_tokens": max(
            1_000,
            sum(len(str(item.get("who") or "")) + len(str(item.get("text") or "")) for item in items) // 3
            + len(json.dumps(story_plan, ensure_ascii=False)) // 3,
        ),
    }
    estimated_limits = estimate_initial_chunk_limits(task_profile)
    if target is not None or soft_limit is not None or hard_limit is not None:
        estimated_limits = type(estimated_limits)(
            int(target if target is not None else estimated_limits.target),
            int(soft_limit if soft_limit is not None else estimated_limits.soft_limit),
            int(hard_limit if hard_limit is not None else estimated_limits.hard_limit),
        )
    controller = RunChunkController(
        target=estimated_limits.target,
        soft_limit=estimated_limits.soft_limit,
        hard_limit=estimated_limits.hard_limit,
    )
    chunks = build_chunks(
        items, scenes, target=estimated_limits.target,
        soft_limit=estimated_limits.soft_limit, hard_limit=estimated_limits.hard_limit,
    )
    run_key = _run_key(run_fingerprint)
    telemetry_root = (
        checkpoint_store.root.parent / "annotation-telemetry"
        if checkpoint_store.root.name == "annotation-checkpoints"
        else checkpoint_store.root / "annotation-telemetry"
    )
    reasoning_writer = ReasoningTelemetryWriter(telemetry_root, run_key)
    request_writer = RequestTelemetryWriter(telemetry_root, run_key)
    saved = checkpoint_store.load(run_key)
    saved_schema_version = saved.get("schema_version") if isinstance(saved, Mapping) else None
    valid_saved = bool(
        saved and isinstance(saved_schema_version, int) and not isinstance(saved_schema_version, bool)
        and saved_schema_version >= 2
        and saved.get("fingerprint") == dict(run_fingerprint)
    )
    saved_chunk_outputs: Dict[str, Dict[str, Any]] = {}
    replay_enabled = False
    # Some providers persist a request first and receive the response later.
    # Their response file may legitimately change between attempts while the
    # request fingerprint stays the same.  Replaying the old chunk output in
    # that case would silently hide the new response from validation/policy.
    replayable_provider = bool(getattr(provider, "replay_checkpoint_outputs", True))
    if valid_saved and int(saved_schema_version) >= 3:
        memory = initial_memory(story_plan["summary"], normalized_story_type)
        rows_by_id = {}
        beats = []
        completed = set()
        resumed_chunks = 0
        saved_chunk_outputs = {
            str(chunk_id): copy.deepcopy(dict(record))
            for chunk_id, record in dict(saved.get("chunk_outputs") or {}).items()
            if isinstance(record, Mapping)
        }
        replay_enabled = replayable_provider
    elif valid_saved:
        memory = copy.deepcopy(saved.get("memory") or initial_memory(story_plan["summary"], normalized_story_type))
        rows_by_id = copy.deepcopy(saved.get("rows_by_id") or {})
        beats = copy.deepcopy(saved.get("beats") or [])
        completed = set((memory.get("progress") or {}).get("completed_chunks") or [])
        resumed_chunks = len(completed)
    else:
        memory = initial_memory(story_plan["summary"], normalized_story_type)
        rows_by_id = {}
        beats = []
        completed = set()
        resumed_chunks = 0

    chunk_outputs: Dict[str, Dict[str, Any]] = {}
    chunk_order: List[str] = []

    completed_target_ids = set(
        str(value)
        for value in (memory.get("progress") or {}).get("completed_target_ids") or []
    )
    request_telemetry: List[Dict[str, Any]] = []
    base_chunk_targets = [
        {str(items[index].get("annotation_id") or "") for index in chunk["target_indices"]}
        for chunk in chunks
    ]
    all_target_ids = {
        target_id for target_ids in base_chunk_targets for target_id in target_ids
    }

    def completion_status() -> Dict[str, Any]:
        pending_items = [
            item for item in items
            if str(item.get("annotation_id") or "") in all_target_ids
            and str(item.get("annotation_id") or "") not in completed_target_ids
        ]
        total_targets = len(all_target_ids)
        completed_targets = total_targets - len(pending_items)
        return {
            "total_targets": total_targets,
            "completed_targets": completed_targets,
            "pending_targets": len(pending_items),
            "pending_start_line": (
                pending_items[0].get("line_no") if pending_items else None
            ),
            "pending_end_line": (
                pending_items[-1].get("line_no") if pending_items else None
            ),
        }

    def partial_result_for_failure(
        stage: str, scene_id: str, chunk_id: str, detail: str,
    ) -> Dict[str, Any]:
        """Snapshot only accepted work so a caller can offer explicit recovery."""
        status = completion_status()
        failure = {
            "stage": str(stage), "scene_id": str(scene_id),
            "chunk_id": str(chunk_id), "detail": str(detail),
        }
        return {
            "items": copy.deepcopy(items),
            "rows_by_id": copy.deepcopy(rows_by_id),
            "memory": copy.deepcopy(memory),
            "beats": copy.deepcopy(beats),
            "director_plan": copy.deepcopy(director_plan),
            "chunk_outputs": copy.deepcopy(chunk_outputs),
            "metrics": build_metrics(),
            "diagnostics": copy.deepcopy(diagnostics) + [{
                "code": "annotation_generation_failed", "level": "error",
                "stage": str(stage), "scene_id": str(scene_id),
                "chunk_id": str(chunk_id), "detail": str(detail),
                "needs_review": True,
            }],
            "completed_chunks": len(completed),
            "resumed_chunks": resumed_chunks,
            "cancelled": False, "timed_out": False,
            "partial_failure": failure,
            **status,
        }

    def user_progress(include_current: bool = True) -> tuple[int, int]:
        total = len(base_chunk_targets)
        finished = sum(1 for target_ids in base_chunk_targets if target_ids <= completed_target_ids)
        current = min(total, finished + (1 if include_current and finished < total else 0))
        return current, total

    if resumed_chunks:
        current, total = user_progress(include_current=False)
        _emit(progress, "resumed", current, total, "已从检查点继续")

    queue = deque(chunks)
    completed_this_run = 0
    diagnostics: List[Dict[str, Any]] = [{
        "code": "chunk_initial_limits", "level": "info",
        "target": estimated_limits.target, "soft_limit": estimated_limits.soft_limit,
        "hard_limit": estimated_limits.hard_limit, "task_profile": task_profile,
    }]
    scene_event_plans: Dict[str, Dict[str, Any]] = {}
    saved_director_plan = (
        saved.get("director_plan") if isinstance(saved, Mapping) else None
    )
    saved_scene_plans = {
        str(scene.get("scene_id") or ""): dict(scene.get("event_plan") or {})
        for scene in (saved_director_plan or {}).get("scenes") or []
        if isinstance(scene, Mapping) and scene.get("event_plan")
    }
    if scene_event_planning:
        _emit(progress, "planning", 0, len(story_plan["scenes"]), "正在建立场景事件链")
        for scene_index, scene in enumerate(story_plan["scenes"], 1):
            scene_id = str(scene.get("scene_id") or "")
            def planning_activity(payload, *, _scene_id=scene_id, _scene_index=scene_index):
                if not model_activity:
                    return
                event = dict(payload or {})
                event.update({
                    "stage": "G1",
                    "scene_id": _scene_id,
                    "chunk_id": f"{_scene_id}:g1",
                    "chunk_current": _scene_index,
                    "chunk_total": len(story_plan["scenes"]),
                    "request_index": request_count,
                    "reasoning_summary": "正在梳理场景因果、人物关系和镜头意图",
                })
                model_activity(event)
            scene_plan_targets = [
                items[int(index)] for index in scene.get("target_indices") or []
                if 0 <= int(index) < len(items)
                and items[int(index)].get("kind") == "line"
            ]
            plan_quality: Dict[str, Any] = {"result": "not_run", "issues": []}
            if scene_id in saved_scene_plans:
                plan = sanitize_scene_event_plan_for_cast(saved_scene_plans[scene_id], cast)
                source = "checkpoint"
                plan_quality = validate_plan_quality(plan, targets=scene_plan_targets, cast=cast)
            else:
                try:
                    request_count += 1
                    plan = plan_scene_events(
                        provider, items, scene, cast=cast,
                        on_activity=planning_activity,
                    )
                    source = "model"
                    plan_quality = validate_plan_quality(plan, targets=scene_plan_targets, cast=cast)
                    if plan_quality.get("result") == "fail":
                        initial_plan_issues = [
                            dict(issue) for issue in plan_quality.get("issues") or ()
                            if isinstance(issue, Mapping)
                        ]
                        diagnostics.extend({
                            **dict(issue),
                            "level": str(issue.get("severity") or "high"),
                            "scene_id": scene_id,
                            "stage": "G1",
                        } for issue in plan_quality.get("issues") or [])
                        request_count += 1
                        repaired = plan_scene_events(
                            provider, items, scene,
                            previous_plan=plan,
                            quality_issues=plan_quality.get("issues") or [],
                            cast=cast,
                            on_activity=planning_activity,
                        )
                        repaired_quality = validate_plan_quality(
                            repaired, targets=scene_plan_targets, cast=cast,
                        )
                        plan = repaired
                        plan_quality = repaired_quality
                        if repaired_quality.get("result") == "pass":
                            # Keep the first G1 finding for provenance, but do
                            # not let a repaired hypothesis explain a later
                            # field loss or remain an active quality failure.
                            initial_codes = {
                                str(issue.get("code") or "")
                                for issue in initial_plan_issues
                            }
                            for diagnostic in diagnostics:
                                if (
                                    diagnostic.get("scene_id") == scene_id
                                    and diagnostic.get("stage") == "G1"
                                    and diagnostic.get("code") in initial_codes
                                ):
                                    diagnostic["evidence_status"] = "superseded_by_g1_repair"
                                    diagnostic["needs_review"] = False
                                    diagnostic["resolution"] = "advisory"
                        source = (
                            "model_repaired"
                            if repaired_quality.get("result") == "pass"
                            else "model_needs_review"
                        )
                except Exception as exc:
                    plan = {"scene_id": scene_id, "events": []}
                    source = "fallback"
                    diagnostics.append({
                        "code": "scene_event_plan_failed", "level": "warning",
                        "scene_id": scene_id, "detail": str(exc),
                    })
            scene_event_plans[scene_id] = plan
            if plan_quality.get("result") == "fail":
                diagnostics.extend({
                    **dict(issue),
                    "level": str(issue.get("severity") or "high"),
                    "scene_id": scene_id,
                    "stage": "G1",
                    "needs_review": (
                        str(issue.get("resolution") or "ai_repair") == "block"
                        or is_automatic_repairable_quality_issue(issue)
                    ),
                } for issue in plan_quality.get("issues") or [])
            for director_scene in director_plan["scenes"]:
                if str(director_scene.get("scene_id") or "") == scene_id:
                    director_scene["event_plan"] = copy.deepcopy(plan)
                    director_scene["event_plan_source"] = source
                    director_scene["event_plan_quality"] = copy.deepcopy(plan_quality)
                    break
            diagnostics.append({
                "code": "scene_event_plan_ready", "level": "info",
                "scene_id": scene_id, "source": source,
                "event_count": len(plan.get("events") or []),
            })
            _emit(
                progress, "planning", scene_index, len(story_plan["scenes"]),
                f"已规划场景事件链 {scene_index}/{len(story_plan['scenes'])}",
            )
    chunk_adaptations: List[Dict[str, Any]] = []
    saved_resume_limit = (
        (saved.get("resume_hints") or {}).get("resume_target_limit")
        if valid_saved and int(saved_schema_version) >= 3
        else (memory.get("progress") or {}).get("resume_target_limit")
    )
    if not saved_resume_limit and saved_chunk_outputs:
        saved_sizes = [
            len(record.get("target_ids") or [])
            for record in saved_chunk_outputs.values()
            if record.get("target_ids")
        ]
        saved_resume_limit = max(saved_sizes) if saved_sizes else None
    safe_target_limit: Optional[int] = (
        int(saved_resume_limit)
        if isinstance(saved_resume_limit, int) and not isinstance(saved_resume_limit, bool)
        and saved_resume_limit > 0
        else None
    )
    prepared_scenes: set[str] = set()

    def emit_model_activity(
        payload: Mapping[str, Any], *, scene_id: str, chunk_id: str,
        current: int, total: int,
        request_index: int, retry_count: int, subdivision_count: int,
    ) -> None:
        if not model_activity:
            return
        event = dict(payload)
        event.update({
            "scene_id": scene_id,
            "chunk_id": chunk_id,
            "chunk_current": current,
            "chunk_total": total,
            "request_index": request_index,
            "retry_count": retry_count,
            "subdivision_count": subdivision_count,
        })
        model_activity(event)

    def complete_chunk(
        call_user: str, schema: Mapping[str, Any], *, scene_id: str, chunk_id: str,
        current: int, total: int, retry_count: int, subdivision_count: int,
        call_volatile: Optional[str] = None,
        call_static_system: Optional[str] = None,
    ) -> Mapping[str, Any]:
        request_index = request_count
        active_static_system = static_system if call_static_system is None else call_static_system

        def activity_callback(payload: Mapping[str, Any]) -> None:
            emit_model_activity(
                payload,
                scene_id=scene_id,
                chunk_id=chunk_id,
                current=current,
                total=total,
                request_index=request_index,
                retry_count=retry_count,
                subdivision_count=subdivision_count,
            )

        stream_method = getattr(provider, "complete_json_stream", None)
        if callable(stream_method):
            return stream_method(
                active_static_system,
                volatile if call_volatile is None else call_volatile,
                call_user,
                schema,
                on_activity=activity_callback,
            )
        started_ms = int(time.time() * 1000)
        emit_model_activity(
            {
                "state": "waiting",
                "model": str(getattr(provider, "model", "") or ""),
                "request_started_at_ms": started_ms,
                "elapsed_ms": 0,
                "first_delta_ms": None,
                "received_chars": 0,
                "finish_reason": "",
            },
            scene_id=scene_id,
            chunk_id=chunk_id,
            current=current,
            total=total,
            request_index=request_index,
            retry_count=retry_count,
            subdivision_count=subdivision_count,
        )
        response = provider.complete_json(
            active_static_system, volatile if call_volatile is None else call_volatile,
            call_user, schema,
        )
        emit_model_activity(
            {
                "state": "completed",
                "model": str(getattr(provider, "model", "") or ""),
                "request_started_at_ms": started_ms,
                "elapsed_ms": max(0, int(time.time() * 1000) - started_ms),
                "first_delta_ms": None,
                "received_chars": 0,
                "finish_reason": str(getattr(provider, "_last_finish_reason", "unknown") or "unknown"),
            },
            scene_id=scene_id,
            chunk_id=chunk_id,
            current=current,
            total=total,
            request_index=request_index,
            retry_count=retry_count,
            subdivision_count=subdivision_count,
        )
        return response

    def is_reasoning_only_empty(exc: Exception) -> bool:
        return bool(
            isinstance(exc, EmptyModelResponseError)
            and int(getattr(exc, "reasoning_chars", 0) or 0) > 0
            and int(getattr(exc, "content_chars", 0) or 0) == 0
        )

    def is_reasoning_only_capacity(exc: Exception) -> bool:
        if not isinstance(exc, OutputCapacityError):
            return False
        records = list(getattr(provider, "request_records", []) or [])
        record = records[-1] if records else {}
        reasoning_used = int(
            record.get("reasoning_tokens") or record.get("reasoning_chars") or 0
        )
        content_chars = int(record.get("content_chars") or 0)
        if reasoning_used <= 0:
            return False
        if content_chars == 0:
            return True
        # Some OpenAI-compatible gateways stream an incomplete JSON prefix
        # after the reasoning channel. A length stop is definitive evidence
        # that this prefix is not complete, regardless of its character count.
        return str(record.get("finish_reason") or "").lower() == "length"

    def build_metrics() -> Dict[str, Any]:
        stats = getattr(provider, "stats", {}) or {}

        def token_delta(key):
            if key not in stats:
                return None
            return max(0, int(stats.get(key) or 0) - int(stats_before.get(key) or 0))

        cache_reports = token_delta("cache_reports")
        cache_read = token_delta("cache_read")
        cache_miss = token_delta("cache_miss")
        cache_reported = bool(cache_reports)
        cache_total = (cache_read or 0) + (cache_miss or 0)
        records = [dict(record) for record in request_telemetry[-50:]]

        def record_sum(key):
            values = [record.get(key) for record in records]
            if not any(value is not None for value in values):
                return None
            return sum(int(value or 0) for value in values)

        return {
            "requests": request_count,
            "retries": retries,
            "subdivisions": subdivisions,
            "input_tokens": token_delta("in"),
            "output_tokens": token_delta("out"),
            "cache_read_tokens": cache_read if cache_reported else None,
            "uncached_input_tokens": cache_miss if cache_reported else None,
            "cache_hit_rate": (
                cache_read / cache_total
                if cache_reported and cache_total
                else (0.0 if cache_reported else None)
            ),
            "cache_reported": cache_reported,
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000),
            "actual_model": str(getattr(provider, "model", "") or ""),
            "request_records": records,
            "reasoning_tokens": record_sum("reasoning_tokens"),
            "reasoning_chars": record_sum("reasoning_chars"),
            "content_chars": record_sum("content_chars"),
            "initial_chunk_limits": {
                "target": estimated_limits.target,
                "soft_limit": estimated_limits.soft_limit,
                "hard_limit": estimated_limits.hard_limit,
            },
            "chunk_adaptations": list(chunk_adaptations),
        }

    def capture_request_records(
        previous_records: Sequence[Mapping[str, Any]],
        previous_reasoning_records: Sequence[Mapping[str, Any]], *, scene_id: str, chunk_id: str,
        current_retry_count: int, current_subdivision_count: int, agent_request_index: int,
        prompt_hashes: Mapping[str, Any],
    ) -> None:
        records = list(getattr(provider, "request_records", []) or [])
        reasoning_records = list(getattr(provider, "reasoning_records", []) or [])
        def new_since(previous, current):
            previous_indices = {
                int(record["request_index"])
                for record in previous
                if isinstance(record, Mapping) and record.get("request_index") is not None
            }
            indexed = [
                record for record in current
                if isinstance(record, Mapping) and record.get("request_index") is not None
            ]
            if indexed:
                return [record for record in indexed if int(record["request_index"]) not in previous_indices]
            offset = len(previous)
            return current[offset:] if len(current) >= offset else current

        new_records = new_since(previous_records, records)
        if not new_records:
            new_records = [{"request_index": agent_request_index, "telemetry_source": "agent"}]
        for record in new_records:
            safe = dict(record)
            safe.update({
                "scene_id": scene_id,
                "chunk_id": chunk_id,
                "agent_request_index": agent_request_index,
                "retry_count": current_retry_count,
                "subdivision_count": current_subdivision_count,
                **dict(prompt_hashes),
                "adaptation_reason": controller.last_reason,
            })
            request_telemetry.append(safe)
            request_writer.write(safe)
        if len(request_telemetry) > 50:
            del request_telemetry[:-50]
        for record in new_since(previous_reasoning_records, reasoning_records):
            reasoning_writer.write({
                **dict(record),
                "scene_id": scene_id,
                "chunk_id": chunk_id,
                "agent_request_index": agent_request_index,
                "retry_count": current_retry_count,
                "subdivision_count": current_subdivision_count,
            })

    def observe_chunk(result: Dict[str, Any], *, scene_id: str, chunk_id: str) -> None:
        before_limits = controller.next_limits()
        after_limits = controller.observe(result)
        if after_limits == before_limits:
            return
        adaptation = {
            "scene_id": scene_id, "chunk_id": chunk_id,
            "reason": controller.last_reason,
            "previous": {
                "target": before_limits.target, "soft_limit": before_limits.soft_limit,
                "hard_limit": before_limits.hard_limit,
            },
            "next": {
                "target": after_limits.target, "soft_limit": after_limits.soft_limit,
                "hard_limit": after_limits.hard_limit,
            },
        }
        chunk_adaptations.append(adaptation)
        diagnostics.append({"code": "chunk_adapted", "level": "info", **adaptation})

    def success_ratio() -> Optional[float]:
        record = (getattr(provider, "request_records", []) or [])[-1:]
        if not record:
            return None
        current = record[0]
        reasoning = current.get("reasoning_chars")
        content = current.get("effective_content_chars")
        if content is None:
            content = current.get("content_chars")
        if reasoning is None or content is None:
            return None
        return float(reasoning or 0) / max(1, float(content or 0))

    while queue:
        chunk = queue.popleft()
        scene_id = str(chunk.get("scene_id") or "")
        if scene_id not in prepared_scenes:
            same_scene = [chunk]
            while queue and str(queue[0].get("scene_id") or "") == scene_id:
                same_scene.append(queue.popleft())
            scene = next((entry for entry in scenes if str(entry.get("scene_id")) == scene_id), None)
            if scene and controller.next_limits() != estimated_limits:
                remaining_indices = [
                    index for part in same_scene for index in part.get("target_indices") or []
                    if str(items[index].get("annotation_id") or "") not in completed_target_ids
                ]
                if remaining_indices:
                    rebuilt_scene = dict(scene)
                    rebuilt_scene["target_indices"] = remaining_indices
                    limits = controller.next_limits()
                    same_scene = build_chunks(
                        items, [rebuilt_scene], target=limits.target,
                        soft_limit=limits.soft_limit, hard_limit=limits.hard_limit,
                    )
            for part in reversed(same_scene):
                queue.appendleft(part)
            prepared_scenes.add(scene_id)
            chunk = queue.popleft()
        chunk_id = str(chunk["chunk_id"])
        if chunk_id in completed and all(
            str(items[index].get("annotation_id") or "") in completed_target_ids
            for index in chunk.get("target_indices") or []
        ):
            continue
        pending_indices = [
            index for index in chunk["target_indices"]
            if str(items[index].get("annotation_id") or "") not in completed_target_ids
        ]
        if not pending_indices:
            completed.add(chunk_id)
            continue
        if len(pending_indices) != len(chunk["target_indices"]):
            chunk = dict(chunk)
            chunk["target_indices"] = pending_indices
            chunk["target_ids"] = [items[index].get("annotation_id") for index in pending_indices]
            chunk["start_line"] = items[pending_indices[0]].get("line_no")
            chunk["end_line"] = items[pending_indices[-1]].get("line_no")
        if cancelled and cancelled():
            current, total = user_progress(include_current=False)
            _emit(progress, "cancelled", current, total, "标注已暂停，可继续")
            return {
                "items": items, "rows_by_id": rows_by_id, "memory": memory,
                "beats": beats,
                "metrics": build_metrics(),
                "diagnostics": diagnostics, "completed_chunks": len(completed),
                "resumed_chunks": resumed_chunks, "cancelled": True,
            }
        if safe_target_limit and len(pending_indices) > safe_target_limit:
            parts = subdivide_chunk(chunk, safe_target_limit)
            for part in reversed(parts):
                queue.appendleft(part)
            subdivisions += 1
            _emit(progress, "recovery", 0, len(base_chunk_targets),
                  f"已学习安全上限，先切分到 {safe_target_limit} 行再请求")
            if model_activity:
                emit_model_activity(
                    {
                        "state": "subdividing",
                        "reason": "learned_safe_limit",
                        "next_chunk_lines": safe_target_limit,
                    },
                    scene_id=str(chunk["scene_id"]),
                    chunk_id=chunk_id,
                    current=current,
                    total=total,
                    request_index=request_count,
                    retry_count=retries,
                    subdivision_count=subdivisions,
                )
            continue
        targets = [items[index] for index in chunk["target_indices"]]
        current_scene = next(
            (entry for entry in story_plan["scenes"] if str(entry.get("scene_id") or "") == scene_id),
            None,
        )
        if current_scene and str((memory.get("scene") or {}).get("id") or "") != scene_id:
            scene_context = dict(current_scene)
            scene_context["scene_type"] = planned_scene_type(current_scene)
            scene_context["active_modes"] = planned_active_modes(current_scene)
            scene_context["scene_function"] = planned_scene_function(current_scene)
            scene_context["characters"] = list(dict.fromkeys(
                str(items[index].get("who") or "")
                for index in current_scene.get("target_indices") or []
                if str(items[index].get("who") or "") in cast
            ))
            memory = complete_scene(
                memory, scene_context,
                str(current_scene.get("evidence") or current_scene.get("opening_text") or ""),
                cast_names=scene_context["characters"],
            )
        relevant_events = retrieve_events(memory.get("events") or [], targets, chunk["scene_id"], limit=8)
        face_shortlists = target_face_shortlists(
            items,
            chunk["target_indices"],
            cast=cast,
            constraints=constraints,
            last_faces=(memory.get("direction") or {}).get("last_faces") or {},
            scene_event_plan=scene_event_plans.get(scene_id),
            include_all=True,
        )
        face_allowlist_by_target = {
            str(targets[int(entry["i"]) - 1].get("annotation_id") or ""): {
                str(candidate.get("id") or "")
                for candidate in entry.get("candidates") or []
                if str(candidate.get("id") or "")
            }
            for entry in face_shortlists
            if isinstance(entry.get("i"), int) and 1 <= int(entry["i"]) <= len(targets)
        }
        face_tokens_by_target = {}
        face_tokens_by_character = {}
        ambiguous_character_tokens = {}
        for entry in face_shortlists:
            if not isinstance(entry.get("i"), int) or not 1 <= int(entry["i"]) <= len(targets):
                continue
            source_id = str(targets[int(entry["i"]) - 1].get("annotation_id") or "")
            token_map = face_tokens_by_target.setdefault(source_id, {})
            who = str(entry.get("who") or "")
            character_map = face_tokens_by_character.setdefault(who, {})
            ambiguous = ambiguous_character_tokens.setdefault(who, set())
            for candidate in entry.get("candidates") or []:
                token = str(candidate.get("token") or "")
                face_id = str(candidate.get("id") or "")
                if token and face_id:
                    token_map.setdefault(token, face_id)
                    existing = character_map.get(token)
                    if existing and existing != face_id:
                        ambiguous.add(token)
                    elif token not in ambiguous:
                        character_map[token] = face_id
        # A model may repeat a valid semantic label it saw for the same
        # character on another TARGET.  Merge only unambiguous aliases; a
        # collision stays target-local so it cannot silently resolve to the
        # wrong physical face.
        for entry in face_shortlists:
            if not isinstance(entry.get("i"), int) or not 1 <= int(entry["i"]) <= len(targets):
                continue
            source_id = str(targets[int(entry["i"]) - 1].get("annotation_id") or "")
            who = str(entry.get("who") or "")
            token_map = face_tokens_by_target.setdefault(source_id, {})
            for token, face_id in (face_tokens_by_character.get(who) or {}).items():
                if token not in (ambiguous_character_tokens.get(who) or set()):
                    token_map.setdefault(token, face_id)
        silent_shortlists = silent_reaction_shortlists(
            items,
            chunk["target_indices"],
            cast=cast,
            constraints=constraints,
            scene_event_plan=scene_event_plans.get(scene_id),
            last_faces=(memory.get("direction") or {}).get("last_faces") or {},
            include_all=True,
        )
        silent_tokens_by_beat = {}
        silent_tokens_by_character = {}
        ambiguous_silent_tokens = {}
        for entry in silent_shortlists:
            anchor_id = str(entry.get("anchor_id") or "")
            position = str(entry.get("position") or "after")
            for who, candidates in (entry.get("faces") or {}).items():
                token_map = silent_tokens_by_beat.setdefault(
                    (anchor_id, position, str(who)), {},
                )
                character_map = silent_tokens_by_character.setdefault(str(who), {})
                ambiguous = ambiguous_silent_tokens.setdefault(str(who), set())
                for candidate in candidates or ():
                    token = str(candidate.get("token") or "")
                    face_id = str(candidate.get("id") or "")
                    if token and face_id:
                        token_map.setdefault(token, face_id)
                        existing = character_map.get(token)
                        if existing and existing != face_id:
                            ambiguous.add(token)
                        elif token not in ambiguous:
                            character_map[token] = face_id
        for key, token_map in silent_tokens_by_beat.items():
            who = str(key[2] or "")
            for token, face_id in (silent_tokens_by_character.get(who) or {}).items():
                if token not in (ambiguous_silent_tokens.get(who) or set()):
                    token_map.setdefault(token, face_id)
        volatile, user = assemble_chunk_context(
            items, chunk, memory, relevant_events, usage_chain,
            before=before, after=after, max_events=8,
            compact=bool(getattr(provider, "supports_compact_annotation", False)),
            story_type=normalized_story_type,
            scene_event_plan=scene_event_plans.get(scene_id),
            cast=cast,
            constraints=constraints,
        )
        compact_protocol = bool(getattr(provider, "supports_compact_annotation", False))
        schema = (
            build_compact_chunk_schema(len(targets))
            if compact_protocol
            else build_chunk_schema([str(item["annotation_id"]) for item in targets])
        )
        target_ids = [str(item["annotation_id"]) for item in targets]
        base_input_hash = _base_input_hash(
            static_system, volatile, user, schema, len(targets),
        )
        checkpoint_execution: Optional[Dict[str, Any]] = None
        checkpoint_attempts: List[Dict[str, Any]] = []
        if replay_enabled:
            saved_output = saved_chunk_outputs.get(chunk_id)
            saved_target_ids = [
                str(value) for value in (saved_output or {}).get("target_ids") or []
            ]
            reusable = bool(
                saved_output
                and saved_target_ids == target_ids
                and str(saved_output.get("base_input_hash") or "") == base_input_hash
            )
            replay_mode = "reuse"
            replay_mode_for = getattr(provider, "checkpoint_replay_mode", None)
            if reusable and callable(replay_mode_for):
                replay_mode = str(replay_mode_for(saved_output) or "reuse")
            if reusable and replay_mode == "g2_repair":
                checkpoint_attempts = [
                    copy.deepcopy(dict(attempt))
                    for attempt in saved_output.get("model_attempts") or []
                    if isinstance(attempt, Mapping)
                ]
                execution_attempt = next((
                    attempt for attempt in reversed(checkpoint_attempts)
                    if attempt.get("phase") == "execution"
                    and attempt.get("outcome") == "accepted"
                    and isinstance(attempt.get("validated_response"), Mapping)
                ), None)
                if execution_attempt:
                    checkpoint_execution = copy.deepcopy(dict(
                        execution_attempt["validated_response"]
                    ))
                    cleaned_rows, checkpoint_repairs = _strip_nonportrait_validated_rows(
                        checkpoint_execution.get("lines_by_id") or {}, targets, cast,
                    )
                    checkpoint_execution["lines_by_id"] = cleaned_rows
                    execution_attempt["validated_response"] = copy.deepcopy(
                        execution_attempt.get("validated_response") or {}
                    )
                    execution_attempt["validated_response"]["lines_by_id"] = copy.deepcopy(
                        cleaned_rows
                    )
                    if checkpoint_repairs:
                        execution_attempt.setdefault("protocol_repairs", []).extend(
                            copy.deepcopy(checkpoint_repairs)
                        )
                        diagnostics.extend({
                            "code": "non_portrait_speaker_resource_cleared",
                            "level": "warning",
                            "stage": "checkpoint_g2_repair_refresh",
                            **repair,
                        } for repair in checkpoint_repairs)
                    diagnostics.append({
                        "code": "checkpoint_g2_repair_refresh", "level": "info",
                        "scene_id": scene_id, "chunk_id": chunk_id,
                    })
                else:
                    replay_mode = "refresh"
            if reusable and replay_mode == "reuse":
                fact_lines, checkpoint_repairs = _strip_nonportrait_validated_rows(
                    saved_output.get("lines_by_id") or {}, targets, cast,
                )
                replayed_output = copy.deepcopy(dict(saved_output))
                replayed_output["lines_by_id"] = copy.deepcopy(fact_lines)
                if checkpoint_repairs:
                    replayed_output["checkpoint_protocol_repairs"] = copy.deepcopy(
                        checkpoint_repairs
                    )
                    accepted_attempt = next((
                        attempt for attempt in reversed(
                            replayed_output.get("model_attempts") or []
                        )
                        if isinstance(attempt, Mapping)
                        and attempt.get("outcome") == "accepted"
                    ), None)
                    if isinstance(accepted_attempt, dict):
                        accepted_attempt.setdefault("protocol_repairs", []).extend(
                            copy.deepcopy(checkpoint_repairs)
                        )
                        validated_attempt = accepted_attempt.get("validated_response")
                        if isinstance(validated_attempt, dict):
                            validated_attempt["lines_by_id"] = copy.deepcopy(fact_lines)
                    diagnostics.extend({
                        "code": "non_portrait_speaker_resource_cleared",
                        "level": "warning",
                        "stage": "checkpoint_reuse",
                        **repair,
                    } for repair in checkpoint_repairs)
                raw_beats = saved_output.get("beats_by_id") or {}
                fact_beats = (
                    [copy.deepcopy(dict(value)) for value in raw_beats.values() if isinstance(value, Mapping)]
                    if isinstance(raw_beats, Mapping)
                    else [copy.deepcopy(dict(value)) for value in raw_beats if isinstance(value, Mapping)]
                )
                fact_state = copy.deepcopy(dict(saved_output.get("state_delta") or {}))
                fact_events = copy.deepcopy(list(saved_output.get("memory_events") or []))
                source_event_ids: Dict[str, List[str]] = {}
                for event in (scene_event_plans.get(scene_id) or {}).get("events") or []:
                    if not isinstance(event, Mapping):
                        continue
                    event_id = str(event.get("event_id") or "")
                    for source_id in event.get("source_ids") or []:
                        if event_id:
                            source_event_ids.setdefault(str(source_id), []).append(event_id)
                for item in targets:
                    source_id = str(item.get("annotation_id") or "")
                    item["_annotation_scene_id"] = scene_id
                    item["_annotation_chunk_id"] = chunk_id
                    item["_plan_event_ids"] = list(dict.fromkeys(source_event_ids.get(source_id, [])))
                rows_by_id.update(fact_lines)
                beats.extend(fact_beats)
                memory = apply_state_delta(
                    memory, fact_state, cast=cast, constraints=constraints,
                )
                memory = _merge_director_rows(
                    memory,
                    _interleaved_director_events(
                        fact_lines, targets, fact_beats, cast, constraints,
                    ),
                    {
                        str(item.get("annotation_id") or ""): str(item.get("who") or "")
                        for item in targets
                    },
                )
                visible = _visible_items(items, chunk, before, after)
                memory["events"] = merge_memory_events(
                    memory.get("events") or [], fact_events, visible,
                )
                progress_state = memory.setdefault("progress", {})
                progress_state.setdefault("completed_chunks", []).append(chunk_id)
                progress_state["completed_target_ids"] = list(dict.fromkeys(
                    list(progress_state.get("completed_target_ids") or []) + target_ids
                ))
                completed.add(chunk_id)
                completed_target_ids.update(target_ids)
                resumed_chunks += 1
                chunk_outputs[chunk_id] = replayed_output
                chunk_order.append(chunk_id)
                quality = saved_output.get("execution_quality")
                if isinstance(quality, Mapping):
                    diagnostics.extend(_g2_issue_diagnostics(
                        quality, scene_id=scene_id, chunk_id=chunk_id,
                    ))
                    for director_scene in director_plan.get("scenes") or []:
                        if str(director_scene.get("scene_id") or "") == scene_id:
                            director_scene.setdefault("execution_quality", []).append({
                                "chunk_id": chunk_id, **copy.deepcopy(dict(quality)),
                            })
                            break
                current, total = user_progress(include_current=False)
                _emit(progress, "resumed", current, total, f"已重放检查点 {chunk_id}")
                continue
            if checkpoint_execution is None:
                diagnostics.append({
                    "code": "checkpoint_replay_stopped", "level": "info",
                    "scene_id": scene_id, "chunk_id": chunk_id,
                    "reason": (
                        "missing_chunk" if not saved_output
                        else "base_input_hash_mismatch" if not reusable
                        else "provider_refresh"
                    ),
                })
        current, total = user_progress()
        _emit(progress, "annotating", current, total,
              f"正在标注第 {current}/{total} 个场景块")
        validated = checkpoint_execution
        last_error = None
        protocol_attempts = 0
        previous_invalid_response: Optional[Mapping[str, Any]] = None
        empty_retry_attempted = False
        reasoning_retry_mode = None
        output_budget = estimate_chunk_output_budget(
            len(targets), compact=compact_protocol,
            reasoning_mode=reasoning_mode,
            maximum=annotation_max_tokens,
        )
        reasoning_capacity_retries = 0
        model_attempts: List[Dict[str, Any]] = checkpoint_attempts
        while validated is None:
            call_user = user
            if protocol_attempts:
                call_user += (
                    f"\n\n上次响应无效：{_chunk_error_code(last_error)} - {_chunk_error_detail(last_error)}。"
                    "请修正内容，保持相同 TARGET，并且只返回 TARGET。"
                )
                if previous_invalid_response is not None:
                    call_user += (
                        "\n\nG2_EXECUTION_REPAIR\n"
                        "这是同一次生成的硬协议返修，不是重新导演。返回完整 JSON；"
                        "只修改直接导致上述错误的字段，其他行、表演字段、镜头选择、"
                        "state_delta、memory_events 和 beats 必须保持原值。\n"
                        "PREVIOUS_RESPONSE\n"
                        + json.dumps(
                            previous_invalid_response,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    )
            if empty_retry_attempted:
                call_user += "\n\n上一次模型只输出了思考而没有正文。请完成当前分析并提交最终 JSON，不要复述规则。"
            if reasoning_capacity_retries:
                call_user += "\n\n上一次推理占满了输出预算。预算已增加，请完成当前分析并返回最终 JSON。"
            previous_records = list(getattr(provider, "request_records", []) or [])
            previous_reasoning_records = list(getattr(provider, "reasoning_records", []) or [])
            prompt_hashes = build_request_prompt_hashes(
                static_system, volatile, call_user, schema, len(targets),
            )
            try:
                request_count += 1
                with _temporary_reasoning_mode(provider, reasoning_retry_mode):
                    with _temporary_output_budget(provider, output_budget):
                        response = complete_chunk(
                            call_user,
                            schema,
                            scene_id=str(chunk["scene_id"]),
                            chunk_id=chunk_id,
                            current=current,
                            total=total,
                            retry_count=retries,
                            subdivision_count=subdivisions,
                        )
                attempt_record = {
                    "phase": "execution",
                    "request_index": request_count,
                    "response": copy.deepcopy(response),
                    "outcome": "pending",
                    **_attempt_response_provenance(provider, previous_records),
                }
                model_attempts.append(attempt_record)
                visible = _visible_items(items, chunk, before, after)
                if compact_protocol:
                    response = expand_compact_chunk_response(response, targets)
                attempt_record["expanded_response"] = copy.deepcopy(dict(response))
                _resolve_response_face_tokens(
                    response,
                    face_tokens_by_target=face_tokens_by_target,
                    silent_tokens_by_beat=silent_tokens_by_beat,
                    face_tokens_by_character=face_tokens_by_character,
                )
                nonportrait_repairs = _strip_nonportrait_line_resources(
                    response, targets, cast,
                )
                if nonportrait_repairs:
                    attempt_record["protocol_repairs"] = copy.deepcopy(
                        nonportrait_repairs
                    )
                    diagnostics.extend({
                        "code": "non_portrait_speaker_resource_cleared",
                        "level": "warning",
                        "stage": "validate",
                        **repair,
                    } for repair in nonportrait_repairs)
                validated = validate_chunk_response(
                    response, targets,
                    visible_ids=[item["annotation_id"] for item in visible],
                    cast=cast, constraints=constraints,
                )
                for source_id, validated_row in validated["lines_by_id"].items():
                    selected_face = str(validated_row.get("face") or "")
                    allowed_faces = face_allowlist_by_target.get(str(source_id))
                    if selected_face and allowed_faces is not None and selected_face not in allowed_faces:
                        raise ChunkProtocolError(
                            "face_outside_shortlist",
                            f"{source_id} 的 face 不在当前标注后端候选中；"
                            f"请使用：{','.join(face_tokens_by_target.get(str(source_id), {})) or '留空'}",
                        )
                if current_scene:
                    for validated_row in validated["lines_by_id"].values():
                        direction = validated_row.get("direction")
                        intent = validated_row.get("direction_intent")
                        if not isinstance(direction, dict) or not isinstance(intent, Mapping):
                            continue
                        if "scene_type" not in intent:
                            direction["scene_type"] = planned_scene_type(current_scene)
                        elif direction.get("scene_type") not in planned_active_modes(current_scene):
                            direction["scene_type"] = planned_scene_type(current_scene)
                        if "scene_function" not in intent:
                            direction["scene_function"] = planned_scene_function(current_scene)
                attempt_record["validated_response"] = copy.deepcopy(validated)
                attempt_record["outcome"] = "accepted"
                break
            except Exception as exc:
                if model_attempts and model_attempts[-1].get("outcome") == "pending":
                    model_attempts[-1]["outcome"] = "rejected"
                    model_attempts[-1]["error_code"] = _chunk_error_code(exc)
                    model_attempts[-1]["error_detail"] = _chunk_error_detail(exc)
                kind = _classify_chunk_error(exc)
                last_error = exc
                if _is_request_deadline(exc):
                    observe_chunk({"success": False, "reason": "deadline"}, scene_id=str(chunk["scene_id"]), chunk_id=chunk_id)
                    timeout_memory = copy.deepcopy(memory)
                    timeout_progress = timeout_memory.setdefault("progress", {})
                    smaller_limit = (
                        max(5, len(targets) // 2)
                        if len(targets) > 5
                        else max(1, len(targets) - 1)
                    )
                    previous_limit = timeout_progress.get("resume_target_limit")
                    if isinstance(previous_limit, int) and previous_limit > 0:
                        smaller_limit = min(previous_limit, smaller_limit)
                    timeout_progress["resume_target_limit"] = smaller_limit
                    checkpoint_store.commit(run_key, _checkpoint(
                        timeout_memory, run_fingerprint, story_plan, rows_by_id, beats,
                        director_plan=director_plan,
                        chunk_outputs=chunk_outputs, chunk_order=chunk_order,
                        resume_hints={"resume_target_limit": smaller_limit},
                    ))
                    memory = timeout_memory
                    diagnostics.append({
                        "code": "request_deadline", "level": "warning",
                        "scene_id": str(chunk["scene_id"]), "chunk_id": chunk_id,
                        "detail": str(exc), "completed_chunks": len(completed),
                    })
                    _emit(progress, "timed_out", current, total, "当前场景块达到时间上限，已保留之前完成的内容")
                    if model_activity:
                        emit_model_activity(
                            {"state": "timed_out", "reason": "request_deadline"},
                            scene_id=str(chunk["scene_id"]), chunk_id=chunk_id,
                            current=current, total=total, request_index=request_count,
                            retry_count=retries, subdivision_count=subdivisions,
                        )
                    return {
                        "items": items, "rows_by_id": rows_by_id, "memory": memory,
                        "beats": beats, "metrics": build_metrics(),
                        "diagnostics": diagnostics,
                        "completed_chunks": len(completed), "resumed_chunks": resumed_chunks,
                        "cancelled": False, "timed_out": True,
                        **completion_status(),
                    }
                if is_reasoning_only_capacity(exc) and reasoning_capacity_retries < 3:
                    larger_budget = grow_chunk_output_budget(output_budget, annotation_max_tokens)
                    if larger_budget is not None:
                        output_budget = larger_budget
                        reasoning_capacity_retries += 1
                        retries += 1
                        _emit(progress, "recovery", current, total, f"推理占满输出预算，已增加到 {output_budget:,} tokens 后重试")
                        if model_activity:
                            emit_model_activity(
                                {
                                    "state": "retrying", "reason": "reasoning_capacity",
                                    "next_output_budget": output_budget,
                                },
                                scene_id=str(chunk["scene_id"]), chunk_id=chunk_id,
                                current=current, total=total, request_index=request_count,
                                retry_count=retries, subdivision_count=subdivisions,
                            )
                        continue
                if kind == "capacity":
                    observe_chunk({"success": False, "reason": "capacity"}, scene_id=str(chunk["scene_id"]), chunk_id=chunk_id)
                    break
                if isinstance(exc, EmptyModelResponseError) and empty_retry_attempted:
                    error = AnnotationAgentError(
                        "model_call", str(chunk["scene_id"]), chunk_id, str(exc),
                        partial_result=partial_result_for_failure(
                            "model_call", str(chunk["scene_id"]), chunk_id, str(exc),
                        ),
                    )
                    raise error from exc
                if isinstance(exc, EmptyModelResponseError):
                    observe_chunk({"success": False, "reason": "empty_response"}, scene_id=str(chunk["scene_id"]), chunk_id=chunk_id)
                    if is_reasoning_only_empty(exc):
                        empty_retry_attempted = True
                        retries += 1
                        continue
                if kind == "protocol" and protocol_attempts == 0:
                    observe_chunk({"success": False, "reason": "protocol"}, scene_id=str(chunk["scene_id"]), chunk_id=chunk_id)
                    previous_response = model_attempts[-1].get("response") if model_attempts else None
                    previous_invalid_response = (
                        copy.deepcopy(dict(previous_response))
                        if isinstance(previous_response, Mapping)
                        else None
                    )
                    protocol_attempts += 1
                    retries += 1
                    if model_activity:
                        emit_model_activity(
                            {
                                "state": "retrying",
                                "reason": _chunk_error_code(exc),
                            },
                            scene_id=str(chunk["scene_id"]),
                            chunk_id=chunk_id,
                            current=current,
                            total=total,
                            request_index=request_count,
                            retry_count=retries,
                            subdivision_count=subdivisions,
                        )
                    continue
                if kind == "protocol":
                    detail = f"{_chunk_error_code(exc)}: {_chunk_error_detail(exc)}"
                    error = AnnotationAgentError(
                        "structured_output", str(chunk["scene_id"]), chunk_id, detail,
                        partial_result=partial_result_for_failure(
                            "structured_output", str(chunk["scene_id"]), chunk_id, detail,
                        ),
                    )
                    raise error from exc
                error = AnnotationAgentError(
                    "model_call", str(chunk["scene_id"]), chunk_id, str(exc),
                    partial_result=partial_result_for_failure(
                        "model_call", str(chunk["scene_id"]), chunk_id, str(exc),
                    ),
                )
                raise error from exc
            finally:
                capture_request_records(
                    previous_records,
                    previous_reasoning_records,
                    scene_id=str(chunk["scene_id"]),
                    chunk_id=chunk_id,
                    current_retry_count=retries,
                    current_subdivision_count=subdivisions,
                    agent_request_index=request_count,
                    prompt_hashes=prompt_hashes,
                )
        if validated is None:
            subdivision = _next_subdivision_limit(len(targets))
            if subdivision is not None:
                _emit(
                    progress,
                    "recovery",
                    current,
                    total,
                    f"当前场景块输出过长，正在自动缩小到 {subdivision} 行后重试",
                )
                parts = subdivide_chunk(chunk, subdivision)
                for part in parts:
                    part["_capacity_candidate"] = True
                for part in reversed(parts):
                    queue.appendleft(part)
                diagnostics.append({
                    "code": "chunk_subdivided", "level": "warning", "chunk_id": chunk_id,
                    "maximum": subdivision,
                    "reason": getattr(last_error, "code", "structured_output"),
                })
                subdivisions += 1
                if model_activity:
                    emit_model_activity(
                        {
                            "state": "subdividing",
                            "reason": _chunk_error_code(last_error),
                            "next_chunk_lines": subdivision,
                        },
                        scene_id=str(chunk["scene_id"]),
                        chunk_id=chunk_id,
                        current=current,
                        total=total,
                        request_index=request_count,
                        retry_count=retries,
                        subdivision_count=subdivisions,
                    )
                continue
            detail = str(last_error)
            raise AnnotationAgentError(
                "structured_output", str(chunk["scene_id"]), chunk_id, detail,
                partial_result=partial_result_for_failure(
                    "structured_output", str(chunk["scene_id"]), chunk_id, detail,
                ),
            )

        validated["beats"], placeholder_issues = sanitize_execution_beats(
            validated.get("beats") or [],
        )
        diagnostics.extend({
            **issue, "level": str(issue.get("severity") or "info"),
            "scene_id": scene_id, "chunk_id": chunk_id, "stage": "G2",
        } for issue in placeholder_issues)
        g2_report = validate_execution_quality(
            scene_event_plans.get(scene_id), targets,
            validated.get("lines_by_id") or {}, validated.get("beats") or [],
            memory=memory, cast=cast, constraints=constraints,
        )
        g2_repaired = False
        # Quality validation can classify actionable execution defects as
        # ``needs_review`` rather than a hard protocol failure.  Those high
        # and critical findings still need the same targeted AI repair pass;
        # otherwise the audit detects the defect but the model never sees it.
        repairable_quality = g2_report.get("result") in {"fail", "needs_review"} and any(
            is_automatic_repairable_quality_issue(issue)
            for issue in g2_report.get("issues") or ()
            if isinstance(issue, Mapping)
        )
        if repairable_quality:
            failed_ids = {
                str(issue.get("anchor_id") or "")
                for issue in g2_report.get("issues") or []
                if is_automatic_repairable_quality_issue(issue)
                and str(issue.get("anchor_id") or "")
            }
            valid_target_ids = {str(item.get("annotation_id") or "") for item in targets}
            failed_ids &= valid_target_ids
            if not failed_ids:
                failed_ids = set(valid_target_ids)
            repair_indices = [
                index for index in chunk.get("target_indices") or []
                if str(items[index].get("annotation_id") or "") in failed_ids
            ]
            if repair_indices:
                repair_chunk = dict(chunk)
                repair_chunk["target_indices"] = repair_indices
                repair_chunk["target_ids"] = [
                    str(items[index].get("annotation_id") or "") for index in repair_indices
                ]
                repair_chunk["start_line"] = items[repair_indices[0]].get("line_no")
                repair_chunk["end_line"] = items[repair_indices[-1]].get("line_no")
                repair_targets = [items[index] for index in repair_indices]
                repair_volatile, repair_user = assemble_chunk_context(
                    items, repair_chunk, memory, relevant_events, usage_chain,
                    before=min(before, 5), after=min(after, 5), max_events=8,
                    compact=compact_protocol, story_type=normalized_story_type,
                    scene_event_plan=scene_event_plans.get(scene_id),
                    cast=cast, constraints=constraints,
                )
                repair_issue_payload = _compact_g2_repair_issues(
                    g2_report.get("issues") or [],
                    anchor_ids=repair_chunk["target_ids"],
                )
                repair_issue_codes = [
                    str(issue.get("code") or "")
                    for issue in g2_report.get("issues") or []
                    if isinstance(issue, Mapping) and str(issue.get("code") or "")
                ]
                repair_static_system = build_repair_rules(
                    repair_issue_codes, layout_mode="pure_ai",
                )
                resource_marker = "========== 本章可用资源 =========="
                resource_start = static_system.find(resource_marker)
                if resource_start >= 0:
                    repair_static_system += "\n\n" + select_repair_resources(
                        static_system[resource_start:], repair_issue_codes,
                    )
                previous_slice = {
                    "lines_by_id": _compact_g2_previous_lines(
                        validated.get("lines_by_id") or {},
                        repair_chunk["target_ids"],
                    ),
                    "beats": [
                        beat for beat in validated.get("beats") or []
                        if str(beat.get("anchor_id") or "") in failed_ids
                    ],
                }
                repair_face_tokens = _g2_face_change_token_options(
                    targets, validated, g2_report, face_tokens_by_target, memory,
                )
                repair_face_options = {
                    source_id: [
                        {"choice": token, "face_id": face_id}
                        for token, face_id in (repair_face_tokens.get(source_id) or {}).items()
                    ]
                    for source_id in repair_chunk["target_ids"]
                    if repair_face_tokens.get(source_id)
                    != face_tokens_by_target.get(source_id)
                }
                repair_user += (
                    "\n\nG2_EXECUTION_REPAIR\n"
                    "只返修当前 TARGET 中列出的失败锚点。不要改写其他行；"
                    "已有 beat 的 beat_id 必须原样保留，删除旧 beat 时不要返回它。\nISSUES\n"
                    + json.dumps(repair_issue_payload, ensure_ascii=False, separators=(",", ":"))
                    + "\nPREVIOUS_EXECUTION\n"
                    + json.dumps(previous_slice, ensure_ascii=False, separators=(",", ":"))
                    + ("\n返修响应的 lines 必须使用 TARGET 中稳定的 source_id，不得使用局部 i。"
                       if compact_protocol else "")
                    + "\n协议位置：紧凑响应中导演状态只能放在行的 d 对象；face/emo/act/fx/bgfx/se/move/reveal/reactions/enter/exit/shake/bg/place/trans 只能放在行顶层。reactions 是当前镜头中其他有立绘角色的同步反应数组，每项写 who/face/emo/act；不要把反应挂到旁白或无立绘说话人。不要重复填写同一字段，也不要把表演字段只写进 direction。"
                )
                if any(
                    str(issue.get("code") or "") in {
                        "repeated_static_camera_pivot",
                        "speaker_chasing_camera_relay",
                    }
                    for issue in g2_report.get("issues") or []
                    if isinstance(issue, Mapping)
                ):
                    repair_user += (
                        "\nCAMERA_COMPOSITION_REPAIR\n"
                        "上面的 history 是已落地的连续硬切。不要只保留同一角色在同一槽位并替换另一侧人物，"
                        "也不要为了让当前说话者可见而逐句传递交叠双人组；"
                        "请依据当前台词重新选择单人正反打、听者单人反应，或完整的新关系组。"
                        "硬切本身合法，不要为了通过检查伪造 reveal/enter/move。\n"
                    )
                if repair_face_options:
                    repair_user += (
                        "\nG2_FACE_CHANGE_OPTIONS\n"
                        + json.dumps(
                            repair_face_options, ensure_ascii=False, separators=(",", ":"),
                        )
                        + "\n这些候选已排除该角色相邻表情阶段正在使用的真实差分；"
                        "需要修复 face_change 的锚点只能原样返回对应 candidate.choice。"
                    )
                repair_schema = (
                    build_compact_chunk_schema(
                        len(repair_targets), repair_chunk["target_ids"],
                    )
                    if compact_protocol else build_chunk_schema(repair_chunk["target_ids"])
                )
                previous_records = list(getattr(provider, "request_records", []) or [])
                previous_reasoning_records = list(getattr(provider, "reasoning_records", []) or [])
                prompt_hashes = build_request_prompt_hashes(
                    repair_static_system, repair_volatile, repair_user,
                    repair_schema, len(repair_targets),
                )
                try:
                    request_count += 1
                    retries += 1
                    with _temporary_reasoning_mode(provider, reasoning_mode):
                        with _temporary_output_budget(provider, output_budget):
                            repair_response = complete_chunk(
                                repair_user, repair_schema,
                                scene_id=scene_id, chunk_id=f"{chunk_id}:g2-repair",
                                current=current, total=total, retry_count=retries,
                                subdivision_count=subdivisions,
                                call_volatile=repair_volatile,
                                call_static_system=repair_static_system,
                            )
                    repair_attempt_record = {
                        "phase": "g2_repair",
                        "request_index": request_count,
                        "target_ids": list(repair_chunk["target_ids"]),
                        "response": copy.deepcopy(repair_response),
                        "outcome": "pending",
                        **_attempt_response_provenance(provider, previous_records),
                    }
                    model_attempts.append(repair_attempt_record)
                    if compact_protocol:
                        repair_response = expand_compact_chunk_response(
                            repair_response, repair_targets,
                        )
                    repair_attempt_record["expanded_response"] = copy.deepcopy(
                        dict(repair_response)
                    )
                    _resolve_response_face_tokens(
                        repair_response,
                        face_tokens_by_target=repair_face_tokens,
                        silent_tokens_by_beat=silent_tokens_by_beat,
                        face_tokens_by_character=face_tokens_by_character,
                    )
                    nonportrait_repairs = _strip_nonportrait_line_resources(
                        repair_response, repair_targets, cast,
                    )
                    if nonportrait_repairs:
                        repair_attempt_record["protocol_repairs"] = copy.deepcopy(
                            nonportrait_repairs
                        )
                        diagnostics.extend({
                            "code": "non_portrait_speaker_resource_cleared",
                            "level": "warning",
                            "stage": "g2_repair_validate",
                            **repair,
                        } for repair in nonportrait_repairs)
                    repaired = validate_chunk_response(
                        repair_response, repair_targets,
                        visible_ids=[item["annotation_id"] for item in _visible_items(
                            items, repair_chunk, min(before, 5), min(after, 5),
                        )],
                        cast=cast, constraints=constraints,
                    )
                    repaired["beats"], repair_placeholder_issues = sanitize_execution_beats(
                        repaired.get("beats") or [],
                    )
                    diagnostics.extend({
                        **issue, "level": str(issue.get("severity") or "info"),
                        "scene_id": scene_id, "chunk_id": chunk_id, "stage": "G2",
                    } for issue in repair_placeholder_issues)
                    repair_attempt_record["validated_response"] = copy.deepcopy(repaired)
                    repair_candidate = _merge_g2_repair(
                        validated, repaired, failed_ids,
                    )
                    repair_candidate_report = validate_execution_quality(
                        scene_event_plans.get(scene_id), targets,
                        repair_candidate.get("lines_by_id") or {},
                        repair_candidate.get("beats") or [],
                        memory=memory, cast=cast, constraints=constraints,
                    )
                    repair_regressions = _introduced_g2_repair_regressions(
                        g2_report, repair_candidate_report,
                    )
                    repair_attempt_record["candidate_execution_quality"] = copy.deepcopy(
                        repair_candidate_report
                    )
                    if repair_regressions:
                        repair_attempt_record["outcome"] = "rejected"
                        repair_attempt_record["error_code"] = (
                            "g2_repair_introduced_structural_regression"
                        )
                        repair_attempt_record["introduced_regressions"] = copy.deepcopy(
                            repair_regressions
                        )
                        diagnostics.append({
                            "code": "g2_repair_introduced_structural_regression",
                            "level": "warning",
                            "scene_id": scene_id,
                            "chunk_id": chunk_id,
                            "stage": "G2",
                            "detail": (
                                "返修候选新引入确定性的镜头生命周期或几何错误；"
                                "已拒绝候选并保留返修前结果供审查。"
                            ),
                            "issues": copy.deepcopy(repair_regressions),
                        })
                    else:
                        validated = repair_candidate
                        g2_report = repair_candidate_report
                        repair_attempt_record["outcome"] = "accepted"
                        g2_repaired = True
                except Exception as exc:
                    if model_attempts and model_attempts[-1].get("outcome") == "pending":
                        model_attempts[-1]["outcome"] = "rejected"
                        model_attempts[-1]["error_code"] = _chunk_error_code(exc)
                        model_attempts[-1]["error_detail"] = _chunk_error_detail(exc)
                    diagnostics.append({
                        "code": "g2_repair_failed", "level": "warning",
                        "scene_id": scene_id, "chunk_id": chunk_id,
                        "stage": "G2", "detail": str(exc),
                    })
                finally:
                    capture_request_records(
                        previous_records, previous_reasoning_records,
                        scene_id=scene_id, chunk_id=f"{chunk_id}:g2-repair",
                        current_retry_count=retries,
                        current_subdivision_count=subdivisions,
                        agent_request_index=request_count,
                        prompt_hashes=prompt_hashes,
                    )
        g2_report["repaired_once"] = g2_repaired
        validated["execution_quality"] = copy.deepcopy(g2_report)
        g2_diagnostics = _g2_issue_diagnostics(
            g2_report, scene_id=scene_id, chunk_id=chunk_id,
        )
        diagnostics.extend(g2_diagnostics)
        for director_scene in director_plan.get("scenes") or []:
            if str(director_scene.get("scene_id") or "") == scene_id:
                director_scene.setdefault("execution_quality", []).append({
                    "chunk_id": chunk_id,
                    **copy.deepcopy(g2_report),
                })
                break
        source_event_ids: Dict[str, List[str]] = {}
        for event in (scene_event_plans.get(scene_id) or {}).get("events") or []:
            if not isinstance(event, Mapping):
                continue
            event_id = str(event.get("event_id") or "")
            for source_id in event.get("source_ids") or []:
                if event_id:
                    source_event_ids.setdefault(str(source_id), []).append(event_id)
        for item in targets:
            source_id = str(item.get("annotation_id") or "")
            item["_annotation_scene_id"] = scene_id
            item["_annotation_chunk_id"] = chunk_id
            item["_plan_event_ids"] = list(dict.fromkeys(source_event_ids.get(source_id, [])))
        for beat in validated.get("beats") or []:
            anchor_id = str(beat.get("anchor_id") or "")
            beat["_scene_id"] = scene_id
            beat["_chunk_id"] = chunk_id
            beat["_plan_event_ids"] = list(dict.fromkeys(source_event_ids.get(anchor_id, [])))

        observe_chunk(
            {"success": True, "reasoning_content_ratio": success_ratio()},
            scene_id=str(chunk["scene_id"]), chunk_id=chunk_id,
        )

        next_rows = copy.deepcopy(rows_by_id)
        next_rows.update(validated["lines_by_id"])
        next_beats = copy.deepcopy(beats)
        next_beats.extend(validated["beats"])
        next_memory = apply_state_delta(memory, validated["state_delta"], cast=cast, constraints=constraints)
        next_memory = _merge_director_rows(
            next_memory,
            _interleaved_director_events(
                validated["lines_by_id"], targets, validated["beats"], cast, constraints,
            ),
            {
                str(item.get("annotation_id") or ""): str(item.get("who") or "")
                for item in targets
            },
        )
        diagnostics.extend(validated.get("diagnostics") or [])
        visible = _visible_items(items, chunk, before, after)
        next_memory["events"] = merge_memory_events(next_memory.get("events") or [], validated["memory_events"], visible)
        next_progress = next_memory.setdefault("progress", {})
        next_progress.setdefault("completed_chunks", []).append(chunk_id)
        target_ids = [str(item["annotation_id"]) for item in targets]
        next_progress["completed_target_ids"] = list(dict.fromkeys(
            list(next_progress.get("completed_target_ids") or []) + target_ids
        ))
        if all_target_ids <= set(next_progress["completed_target_ids"]):
            next_progress.pop("resume_target_limit", None)
        chunk_output = {
            "scene_id": scene_id,
            "target_ids": list(target_ids),
            "lines_by_id": copy.deepcopy(dict(validated.get("lines_by_id") or {})),
            "beats_by_id": {
                str(beat.get("beat_id") or ""): copy.deepcopy(dict(beat))
                for beat in validated.get("beats") or []
                if str(beat.get("beat_id") or "")
            },
            "state_delta": copy.deepcopy(dict(validated.get("state_delta") or {})),
            "memory_events": copy.deepcopy(list(validated.get("memory_events") or [])),
            "base_input_hash": base_input_hash,
            "execution_quality": copy.deepcopy(dict(
                validated.get("execution_quality") or {}
            )),
            "model_attempts": copy.deepcopy(model_attempts),
        }
        chunk_outputs[chunk_id] = chunk_output
        if chunk_id not in chunk_order:
            chunk_order.append(chunk_id)
        checkpoint_store.commit(run_key, _checkpoint(
            next_memory, run_fingerprint, story_plan, next_rows, next_beats,
            director_plan=director_plan,
            chunk_outputs=chunk_outputs, chunk_order=chunk_order,
        ))
        rows_by_id = next_rows
        beats = next_beats
        memory = next_memory
        completed.add(chunk_id)
        completed_target_ids.update(target_ids)
        completed_this_run += 1
        if chunk.get("_capacity_candidate"):
            safe_target_limit = len(targets)

    return {
        "items": items, "rows_by_id": rows_by_id, "memory": memory,
        "beats": beats,
        "director_plan": copy.deepcopy(director_plan),
        "chunk_outputs": copy.deepcopy(chunk_outputs),
        "metrics": build_metrics(),
        "diagnostics": diagnostics, "completed_chunks": len(completed),
        "resumed_chunks": resumed_chunks, "cancelled": False, "timed_out": False,
        **completion_status(),
    }


def build_review_windows(items: Sequence[Mapping[str, Any]], scenes: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]], chunk_size: int = 30) -> List[Dict[str, Any]]:
    windows = []
    for scene in scenes:
        indices = list(scene.get("target_indices") or [])
        for offset in range(chunk_size, len(indices), chunk_size):
            selected = indices[max(0, offset - 5):min(len(indices), offset + 5)]
            event_text = " ".join(str(event.get("summary") or "") for event in events if event.get("status") == "open")
            windows.append({
                "kind": "chunk_boundary", "scene_id": scene.get("scene_id"),
                "source_ids": [items[index].get("annotation_id") for index in selected],
                "context": event_text + "\n" + "\n".join(str(items[index].get("text") or "") for index in selected),
            })
    return windows


def apply_review_patches(items: List[Dict[str, Any]], patches: Sequence[Mapping[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    updated = copy.deepcopy(items)
    by_id = {str(item.get("annotation_id")): item for item in updated}
    diagnostics = []
    for patch in patches:
        item = by_id.get(str(patch.get("source_id")))
        field = str(patch.get("field") or "")
        if not item or field not in {"face", "emo", "act", "fx", "se", "bg", "bg_request", "place", "shake", "bgfx", "trans", "move", "shot"}:
            continue
        if item.get(field) != patch.get("before"):
            diagnostics.append({"code": "review_before_mismatch", "level": "warning", "source_id": patch.get("source_id"), "field": field})
            continue
        item[field] = patch.get("after")
    return updated, diagnostics
