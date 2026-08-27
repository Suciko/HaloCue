"""Compile and sample deterministic scene-performance operations.

The current contract normalizes authored effects and character transitions.
The module is renderer-independent: browser preview and offline capture consume
the same plan, while execution modes decide how transient motion is sampled.
"""

from __future__ import annotations

import math
from typing import Any, Literal


PERFORMANCE_SCHEMA_VERSION = "scene-performance/1.1"
PERFORMANCE_SAMPLE_SCHEMA_VERSION = "scene-performance-sample/1.0"
DEFAULT_SHAKE_INTENSITY = 0.35
SHAKE_FREQUENCY_HZ = 12
SHAKE_MAX_X_PX = 14
SHAKE_MAX_Y_PX = 8
CHARACTER_ENTER_OFFSET_Y_PX = 24
CHARACTER_EXIT_OFFSET_Y_PX = 12
CHARACTER_ENTER_SCALE = 0.97
CHARACTER_EXIT_SCALE = 0.985
ExecutionMode = Literal["play", "sample", "skip", "reduced-motion"]


def _quantize(value: float, digits: int) -> float | int:
    rounded = round(value, digits)
    return int(rounded) if rounded == int(rounded) else rounded


def _intensity(value: Any) -> float:
    number = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if number is None or not math.isfinite(number):
        number = DEFAULT_SHAKE_INTENSITY
    return max(0.0, min(1.0, float(number)))


def _validate_inputs(descriptor: dict[str, Any], timeline: dict[str, Any]) -> None:
    if not isinstance(descriptor, dict) or descriptor.get("schema_version") != "scene-descriptor/1.0":
        raise ValueError("unsupported scene descriptor schema")
    if not isinstance(timeline, dict) or timeline.get("schema_version") != "render-timeline/1.0":
        raise ValueError("unsupported render timeline schema")
    if timeline.get("scene_id") != descriptor.get("scene_id"):
        raise ValueError("scene performance timeline scene_id does not match the descriptor")
    descriptor_events = descriptor.get("events")
    timeline_events = timeline.get("events")
    if not isinstance(descriptor_events, list) or not isinstance(timeline_events, list):
        raise ValueError("scene performance events must be arrays")
    if len(descriptor_events) != len(timeline_events):
        raise ValueError("scene performance timeline event count does not match the descriptor")
    for index, (source, item) in enumerate(zip(descriptor_events, timeline_events)):
        if not isinstance(source, dict) or not isinstance(item, dict):
            raise ValueError(f"scene performance event {index} must be an object")
        if item.get("event_id") != source.get("event_id"):
            raise ValueError(f"scene performance timeline event {index} does not match the descriptor")


def build_scene_performance(
    descriptor: dict[str, Any],
    timeline: dict[str, Any],
) -> dict[str, Any]:
    """Normalize supported authored events into a deterministic performance plan."""

    _validate_inputs(descriptor, timeline)
    operations: list[dict[str, Any]] = []
    slot_characters: dict[int, str] = {}
    for actor in descriptor.get("initial_actors", []):
        if not isinstance(actor, dict) or actor.get("state") != "visible":
            continue
        slot = actor.get("slot")
        character_id = actor.get("character_id")
        if (
            isinstance(slot, int)
            and not isinstance(slot, bool)
            and 1 <= slot <= 5
            and isinstance(character_id, str)
            and character_id
        ):
            slot_characters[slot] = character_id

    def add_character_tween(
        item: dict[str, Any],
        character_id: str,
        slot: int,
        suffix: str,
        channel: str,
        value_space: str,
        start_value: float,
        end_value: float,
    ) -> None:
        operations.append(
            {
                "operation_id": f"{item['event_id']}/operation/{suffix}",
                "source_event_id": item["event_id"],
                "kind": "numeric-tween",
                "target": {
                    "kind": "character",
                    "character_id": character_id,
                    "slot": slot,
                },
                "channel": channel,
                "value_space": value_space,
                "start_frame": item["start_frame"],
                "end_frame": item["end_frame"],
                "from": start_value,
                "to": end_value,
                "easing": "ease-out-cubic",
            }
        )

    for item in timeline["events"]:
        event = item.get("event", {})
        kind = item.get("kind")
        if kind == "halocue.ba:screen-shake":
            resolved_intensity = _intensity(event.get("intensity"))
            event_id = item["event_id"]
            operations.append(
                {
                    "operation_id": f"{event_id}/operation/shake",
                    "source_event_id": event_id,
                    "kind": "shake",
                    "target": {"kind": "stage", "target_id": "stage/global"},
                    "channel": "geometry.offset",
                    "value_space": "relative-to-baseline",
                    "start_frame": item["start_frame"],
                    "end_frame": item["end_frame"],
                    "amplitude_x_px": _quantize(resolved_intensity * SHAKE_MAX_X_PX, 3),
                    "amplitude_y_px": _quantize(resolved_intensity * SHAKE_MAX_Y_PX, 3),
                    "frequency_hz": SHAKE_FREQUENCY_HZ,
                }
            )
        if kind == "enter":
            slot = event.get("slot")
            character_id = event.get("character_id")
            if (
                not isinstance(slot, int)
                or isinstance(slot, bool)
                or not 1 <= slot <= 5
                or not isinstance(character_id, str)
                or not character_id
            ):
                continue
            add_character_tween(
                item, character_id, slot, "opacity",
                "presentation.opacity", "absolute", 0, 1,
            )
            add_character_tween(
                item, character_id, slot, "offset-y",
                "layout.offset-y", "relative-to-baseline", CHARACTER_ENTER_OFFSET_Y_PX, 0,
            )
            add_character_tween(
                item, character_id, slot, "scale",
                "presentation.scale", "factor-from-baseline", CHARACTER_ENTER_SCALE, 1,
            )
            slot_characters[slot] = character_id
        if kind == "exit":
            slot = event.get("slot")
            character_id = event.get("character_id")
            if not isinstance(character_id, str) or not character_id:
                character_id = slot_characters.get(slot) if isinstance(slot, int) else None
            if (
                not isinstance(slot, int)
                or isinstance(slot, bool)
                or not 1 <= slot <= 5
                or not isinstance(character_id, str)
                or not character_id
            ):
                continue
            add_character_tween(
                item, character_id, slot, "opacity",
                "presentation.opacity", "absolute", 1, 0,
            )
            add_character_tween(
                item, character_id, slot, "offset-y",
                "layout.offset-y", "relative-to-baseline", 0, CHARACTER_EXIT_OFFSET_Y_PX,
            )
            add_character_tween(
                item, character_id, slot, "scale",
                "presentation.scale", "factor-from-baseline", 1, CHARACTER_EXIT_SCALE,
            )
            slot_characters.pop(slot, None)
    source_operation_ids: dict[str, list[str]] = {}
    for operation in operations:
        source_operation_ids.setdefault(operation["source_event_id"], []).append(
            operation["operation_id"]
        )
    return {
        "schema_version": PERFORMANCE_SCHEMA_VERSION,
        "frame_rate": timeline["frame_rate"],
        "scene_id": timeline.get("scene_id"),
        "total_frames": timeline["total_frames"],
        "operations": operations,
        "source_map": [
            {
                "source_event_id": source_event_id,
                "operation_ids": operation_ids,
                "primary_operation_id": operation_ids[0],
            }
            for source_event_id, operation_ids in source_operation_ids.items()
        ],
    }


def sample_scene_performance(
    plan: dict[str, Any],
    frame: int,
    *,
    mode: ExecutionMode = "sample",
) -> dict[str, Any]:
    """Return renderer-neutral stage contributions for one exact frame."""

    if not isinstance(plan, dict) or plan.get("schema_version") != PERFORMANCE_SCHEMA_VERSION:
        raise ValueError("unsupported scene performance schema")
    total_frames = plan.get("total_frames")
    if (
        isinstance(frame, bool)
        or not isinstance(frame, int)
        or not isinstance(total_frames, int)
        or frame < 0
        or frame >= total_frames
    ):
        raise ValueError(f"performance frame must be between 0 and {total_frames - 1}")
    if mode not in {"play", "sample", "skip", "reduced-motion"}:
        raise ValueError(f"unsupported performance execution mode {mode}")
    operations = plan.get("operations")
    if not isinstance(operations, list):
        raise ValueError("scene performance operations must be an array")
    in_range = [
        operation
        for operation in operations
        if operation["start_frame"] <= frame < operation["end_frame"]
    ]
    active = (
        [operation for operation in in_range if operation.get("kind") == "numeric-tween"]
        if mode in {"skip", "reduced-motion"}
        else in_range
    )
    offset_x = 0.0
    offset_y = 0.0
    character_samples: dict[tuple[str, int], dict[str, Any]] = {}
    for operation in active:
        duration_frames = operation["end_frame"] - operation["start_frame"]
        local_frame = frame - operation["start_frame"]
        progress = 1.0 if duration_frames <= 1 else local_frame / (duration_frames - 1)
        if operation["kind"] == "shake":
            envelope = 1.0 - progress
            seconds = local_frame / plan["frame_rate"]
            phase = math.pi * 2 * operation["frequency_hz"] * seconds
            offset_x += operation["amplitude_x_px"] * math.sin(phase) * envelope
            offset_y += operation["amplitude_y_px"] * math.sin(phase * 1.7) * envelope
            continue
        eased = 1.0 - (1.0 - progress) ** 3
        use_final = mode == "skip" or (
            mode == "reduced-motion" and operation["channel"] != "presentation.opacity"
        )
        value = operation["to"] if use_final else (
            operation["from"] + (operation["to"] - operation["from"]) * eased
        )
        target = operation["target"]
        key = (target["character_id"], target["slot"])
        sample = character_samples.setdefault(
            key,
            {
                "character_id": target["character_id"],
                "slot": target["slot"],
                "opacity": None,
                "offset_y_px": 0,
                "scale": 1,
            },
        )
        if operation["channel"] == "presentation.opacity":
            sample["opacity"] = _quantize(value, 6)
        elif operation["channel"] == "layout.offset-y":
            sample["offset_y_px"] = _quantize(value, 6)
        elif operation["channel"] == "presentation.scale":
            sample["scale"] = _quantize(value, 6)
    return {
        "schema_version": PERFORMANCE_SAMPLE_SCHEMA_VERSION,
        "frame": frame,
        "mode": mode,
        "active_operation_ids": [operation["operation_id"] for operation in active],
        "stage": {
            "offset_x_px": _quantize(offset_x, 6),
            "offset_y_px": _quantize(offset_y, 6),
        },
        "characters": list(character_samples.values()),
    }
