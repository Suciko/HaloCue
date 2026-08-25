"""Build a deterministic frame timeline for preview and video adapters.

The timeline deliberately contains no browser timers, audio callbacks, or
renderer objects. It is a pure projection of a validated scene descriptor so
the editor preview and an offline FFmpeg export can agree on frame boundaries.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any


TIMELINE_SCHEMA_VERSION = "render-timeline/1.0"
DEFAULT_FRAME_RATE = 30
SUPPORTED_EVENT_KINDS = frozenset({"background", "dialogue", "enter", "exit", "wait"})

# These values mirror the independently implemented AA preview typewriter
# policy. They are product defaults, not a requirement for future exporters.
TYPEWRITER_GRAPHEME_MS = 32
TYPEWRITER_PUNCTUATION_PAUSE_MS = 96
TYPEWRITER_NEWLINE_PAUSE_MS = 192
DIALOGUE_HOLD_MS = 650
DEFAULT_EVENT_DURATION_MS = {
    "background": 500,
    "enter": 500,
    "exit": 500,
    "wait": 1000,
}
PUNCTUATION = frozenset("，。！？；：、,.!?;:")


def _require_frame_rate(frame_rate: Any) -> int:
    if isinstance(frame_rate, bool) or not isinstance(frame_rate, int):
        raise ValueError("frame_rate must be an integer")
    if not 1 <= frame_rate <= 240:
        raise ValueError("frame_rate must be between 1 and 240")
    return frame_rate


def _duration_frames(duration_ms: int, frame_rate: int) -> int:
    # End frames are exclusive. Ceiling prevents a visible event from being
    # rounded down to zero and keeps every event boundary reproducible.
    return max(1, math.ceil(duration_ms * frame_rate / 1000))


def dialogue_duration_ms(text: Any) -> int:
    """Return the default readable duration for one dialogue event."""

    value = str(text or "")
    if not value:
        return DIALOGUE_HOLD_MS
    duration = DIALOGUE_HOLD_MS
    for grapheme in value:
        duration += TYPEWRITER_GRAPHEME_MS
        if grapheme == "\n":
            duration += TYPEWRITER_NEWLINE_PAUSE_MS
        elif grapheme in PUNCTUATION:
            duration += TYPEWRITER_PUNCTUATION_PAUSE_MS
    return duration


def event_duration_ms(event: dict[str, Any]) -> int:
    """Resolve an event's explicit duration or its stable kind default."""

    explicit = event.get("duration_ms")
    if explicit is not None:
        if isinstance(explicit, bool) or not isinstance(explicit, (int, float)):
            raise ValueError("event duration_ms must be a finite positive number")
        if not math.isfinite(explicit) or explicit <= 0:
            raise ValueError("event duration_ms must be a finite positive number")
        return max(1, math.ceil(explicit))

    kind = event.get("kind")
    if kind == "dialogue":
        return dialogue_duration_ms(event.get("text"))
    try:
        return DEFAULT_EVENT_DURATION_MS[kind]
    except KeyError as exc:
        raise ValueError(f"unsupported render event kind {kind!r}") from exc


def build_render_timeline(
    descriptor: dict[str, Any],
    *,
    frame_rate: int = DEFAULT_FRAME_RATE,
) -> dict[str, Any]:
    """Build a stable, end-exclusive frame timeline from a scene descriptor."""

    if not isinstance(descriptor, dict):
        raise ValueError("scene descriptor must be an object")
    if descriptor.get("schema_version") != "scene-descriptor/1.0":
        raise ValueError("unsupported scene descriptor schema")
    events = descriptor.get("events")
    if not isinstance(events, list):
        raise ValueError("scene descriptor events must be an array")

    fps = _require_frame_rate(frame_rate)
    timeline_events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    cursor = 0
    for index, source in enumerate(events):
        if not isinstance(source, dict):
            raise ValueError(f"event {index} must be an object")
        event_id = source.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError(f"event {index} must have a non-empty event_id")
        if event_id in seen_ids:
            raise ValueError(f"duplicate event_id {event_id!r}")
        seen_ids.add(event_id)
        kind = source.get("kind")
        if kind not in SUPPORTED_EVENT_KINDS:
            raise ValueError(f"unsupported render event kind {kind!r}")

        duration_ms = event_duration_ms(source)
        duration_frames = _duration_frames(duration_ms, fps)
        start_frame = cursor
        end_frame = start_frame + duration_frames
        timeline_events.append(
            {
                "event_id": event_id,
                "kind": kind,
                "start_frame": start_frame,
                "end_frame": end_frame,
                "duration_frames": duration_frames,
                "duration_ms": duration_ms,
                "event": deepcopy(source),
            }
        )
        cursor = end_frame

    return {
        "schema_version": TIMELINE_SCHEMA_VERSION,
        "frame_rate": fps,
        "scene_id": descriptor.get("scene_id"),
        "events": timeline_events,
        "total_frames": cursor,
    }

