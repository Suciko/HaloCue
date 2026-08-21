"""Canonical state and validation helpers for annotation direction metadata."""

from collections.abc import Mapping
from typing import Any


SCENE_TYPES = ("main", "event", "bond", "other")
SCENE_FUNCTIONS = (
    "establishing",
    "entrance",
    "exposition",
    "dialogue",
    "comedy_escalation",
    "conflict",
    "emotional_turn",
    "action",
    "closing",
)
FOCUS_KINDS = ("speaker", "listener", "group", "offscreen_space")
RELATION_DISTANCES = ("distant", "normal", "approaching", "intimate", "remote")
SHOT_TRANSITIONS = ("cut", "reframe")
# Semantic camera operation chosen before the renderer maps it to cut/reframe.
# These are intentionally relationship- and character-independent.
SHOT_OPERATIONS = (
    "continue_group",
    "expand_group",
    "shrink_group",
    "replace_center_subject",
    "switch_group",
    "impact_insert",
)
CONTINUITY_STATES = ("start", "hold", "escalate", "end", "none")
DIRECTION_REASONS = (
    "new_stimulus",
    "relation_shift",
    "emotional_shift",
    "listener_reaction",
    "group_sync",
    "comedy_escalation",
    "action_impact",
    "scene_transition",
    "continuity_hold",
    "none",
)
BEAT_REASONS = (
    "await_response",
    "relationship_turn",
    "listener_reaction",
    "comedy_hold",
    "decision_pause",
    "physical_reaction",
    "offscreen_cue",
    "entrance_reveal",
    "group_reaction",
    "object_operation",
    "montage",
    "exit_aftershock",
)

_CONTINUITY_LAYERS = ("face", "emo", "act", "fx", "bgfx")
_TEXT_FIELDS = ("emotion_phase", "subtext")


def default_director(scene_type: str = "other") -> dict[str, Any]:
    """Return an independent canonical director state."""
    return {
        "scene_type": scene_type if scene_type in SCENE_TYPES else "other",
        "scene_function": "dialogue",
        "emotion_phase": "",
        "subtext": "",
        "relation_distance": "normal",
        "shot_operation": "",
        "shot_transition": "",
        "focus_kind": "speaker",
        "focus_character": "",
        "reaction_target": "",
        "visible_characters": [],
        "positions": {},
        "continuity": {layer: "none" for layer in _CONTINUITY_LAYERS},
        "reason": "none",
    }


def normalize_director(
    value: Any,
    *,
    cast_names: set[str],
    displayable_names: set[str],
    default_scene_type: str = "other",
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Normalize untrusted direction metadata and report discarded values."""
    invalid_root_value = value is not None and not isinstance(value, Mapping)
    source = value if isinstance(value, Mapping) else {}
    state = default_director(default_scene_type)
    diagnostics: list[dict[str, str]] = []

    def diagnostic(code: str, field: str, message: str) -> None:
        diagnostics.append({"code": code, "level": "warning", "field": field, "message": message})

    if invalid_root_value:
        diagnostic("director_invalid_value", "value", "Director metadata must be an object")

    def enum(field: str, allowed: tuple[str, ...]) -> None:
        candidate = source.get(field)
        if candidate in allowed:
            state[field] = candidate
        elif candidate not in (None, ""):
            diagnostic("director_invalid_value", field, f"Unsupported {field}: {candidate}")

    enum("scene_type", SCENE_TYPES)
    enum("scene_function", SCENE_FUNCTIONS)
    enum("relation_distance", RELATION_DISTANCES)
    enum("shot_operation", SHOT_OPERATIONS)
    enum("shot_transition", SHOT_TRANSITIONS)
    enum("focus_kind", FOCUS_KINDS)
    enum("reason", DIRECTION_REASONS)

    for field in _TEXT_FIELDS:
        candidate = source.get(field, "")
        if isinstance(candidate, str):
            state[field] = candidate[:160]
            if len(candidate) > 160:
                diagnostic("director_text_truncated", field, f"{field} was limited to 160 characters")
        elif candidate is not None:
            diagnostic("director_invalid_value", field, f"{field} must be text")

    for field in ("focus_character",):
        candidate = source.get(field, "")
        if isinstance(candidate, str) and candidate:
            if candidate not in cast_names:
                diagnostic("director_unknown_character", field, f"Unknown character: {candidate}")
            elif candidate not in displayable_names:
                diagnostic(
                    "director_non_displayable_character", field,
                    f"Character cannot be displayed: {candidate}",
                )
            else:
                state[field] = candidate
        elif candidate not in (None, ""):
            diagnostic("director_invalid_value", field, f"{field} must be a character name")

    reaction_target = source.get("reaction_target", "")
    if isinstance(reaction_target, str) and reaction_target:
        if reaction_target not in cast_names:
            diagnostic(
                "director_unknown_character", "reaction_target",
                f"Unknown character: {reaction_target}",
            )
        else:
            state["reaction_target"] = reaction_target
    elif reaction_target not in (None, ""):
        diagnostic("director_invalid_value", "reaction_target", "reaction_target must be a character name")

    visible = source.get("visible_characters", [])
    if isinstance(visible, (list, tuple)):
        for candidate in visible[:3]:
            if not isinstance(candidate, str):
                diagnostic("director_invalid_value", "visible_characters", "Visible characters must be names")
            elif candidate not in cast_names:
                diagnostic("director_unknown_character", "visible_characters", f"Unknown character: {candidate}")
            elif candidate not in displayable_names:
                diagnostic("director_non_displayable_character", "visible_characters", f"Character cannot be displayed: {candidate}")
            elif candidate not in state["visible_characters"]:
                state["visible_characters"].append(candidate)
        if len(visible) > 3:
            diagnostic(
                "director_visible_characters_limited", "visible_characters",
                "At most three characters can be visible in an AA shot",
            )
    elif visible is not None:
        diagnostic("director_invalid_value", "visible_characters", "Visible characters must be a list")

    positions = source.get("positions", {})
    if isinstance(positions, Mapping):
        used_slots: set[int] = set()
        for candidate, slot in positions.items():
            if candidate not in displayable_names:
                diagnostic("director_unknown_character", "positions", f"Unknown or hidden character: {candidate}")
            elif isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= 5:
                diagnostic("director_invalid_value", "positions", f"Invalid AA slot for {candidate}: {slot}")
            elif slot in used_slots:
                diagnostic("director_duplicate_slot", "positions", f"AA slot is used twice: {slot}")
            else:
                state["positions"][candidate] = slot
                used_slots.add(slot)
        if len(positions) > 3:
            diagnostic("director_positions_limited", "positions", "At most three positions are allowed")
    elif positions is not None:
        diagnostic("director_invalid_value", "positions", "Positions must be an object")

    continuity = source.get("continuity", {})
    if isinstance(continuity, Mapping):
        for layer in _CONTINUITY_LAYERS:
            command = continuity.get(layer)
            if command in CONTINUITY_STATES:
                state["continuity"][layer] = command
            elif command not in (None, ""):
                diagnostic("director_invalid_value", f"continuity.{layer}", f"Unsupported continuity state: {command}")
        for layer in continuity:
            if layer not in _CONTINUITY_LAYERS:
                diagnostic("director_unknown_continuity_layer", f"continuity.{layer}", f"Unknown continuity layer: {layer}")
    elif continuity is not None:
        diagnostic("director_invalid_value", "continuity", "Continuity must be an object")

    return state, diagnostics


def apply_continuity(
    previous: Mapping[str, str],
    values: Mapping[str, str],
    commands: Mapping[str, str],
) -> dict[str, str]:
    """Apply start/hold/escalate/end lifecycle commands to named layers."""
    result: dict[str, str] = {}
    for layer in set(previous) | set(values) | set(commands):
        command = commands.get(layer, "none")
        if command in ("start", "escalate"):
            result[layer] = values.get(layer, "")
        elif command == "hold":
            result[layer] = previous.get(layer, "")
        elif command == "end":
            result[layer] = ""
    return result
