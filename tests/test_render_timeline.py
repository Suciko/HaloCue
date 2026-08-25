from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


MODEL_ROOT = Path(__file__).resolve().parents[1] / "packages" / "project-model"
if str(MODEL_ROOT) not in sys.path:
    sys.path.insert(0, str(MODEL_ROOT))

from render_timeline import (  # noqa: E402
    DEFAULT_FRAME_RATE,
    TIMELINE_SCHEMA_VERSION,
    build_render_timeline,
    dialogue_duration_ms,
)


def descriptor(events: list[dict]) -> dict:
    return {
        "schema_version": "scene-descriptor/1.0",
        "scene_id": "scene/timeline",
        "events": events,
    }


def test_timeline_uses_end_exclusive_contiguous_frame_ranges():
    timeline = build_render_timeline(
        descriptor(
            [
                {"event_id": "event/enter", "kind": "enter"},
                {"event_id": "event/wait", "kind": "wait", "duration_ms": 1000},
                {"event_id": "event/exit", "kind": "exit", "duration_ms": 1},
            ]
        ),
        frame_rate=30,
    )

    assert timeline["schema_version"] == TIMELINE_SCHEMA_VERSION
    assert timeline["frame_rate"] == 30
    assert [(item["start_frame"], item["end_frame"]) for item in timeline["events"]] == [
        (0, 15),
        (15, 45),
        (45, 46),
    ]
    assert timeline["total_frames"] == 46


def test_dialogue_duration_is_deterministic_and_preserves_source_event():
    source = {"event_id": "event/line", "kind": "dialogue", "text": "你好。\n再见"}
    first = build_render_timeline(descriptor([source]))
    second = build_render_timeline(json.loads(json.dumps(descriptor([source]), ensure_ascii=False)))

    assert first == second
    assert first["events"][0]["duration_ms"] == dialogue_duration_ms(source["text"])
    assert first["events"][0]["event"] == source
    assert first["total_frames"] > 0


def test_explicit_duration_is_rounded_up_to_a_visible_frame():
    timeline = build_render_timeline(
        descriptor([{"event_id": "event/short", "kind": "wait", "duration_ms": 1.1}]),
        frame_rate=24,
    )

    assert timeline["events"][0]["duration_ms"] == 2
    assert timeline["events"][0]["duration_frames"] == 1


@pytest.mark.parametrize(
    "events, message",
    [
        ([{"event_id": "event/a", "kind": "wait"}, {"event_id": "event/a", "kind": "wait"}], "duplicate"),
        ([{"event_id": "event/a", "kind": "camera"}], "unsupported"),
        ([{"event_id": "event/a", "kind": "wait", "duration_ms": 0}], "positive"),
    ],
)
def test_timeline_rejects_ambiguous_or_unsupported_events(events, message):
    with pytest.raises(ValueError, match=message):
        build_render_timeline(descriptor(events))


def test_default_frame_rate_is_explicit_and_bounded():
    assert DEFAULT_FRAME_RATE == 30
    with pytest.raises(ValueError, match="between 1 and 240"):
        build_render_timeline(descriptor([]), frame_rate=0)
    with pytest.raises(ValueError, match="integer"):
        build_render_timeline(descriptor([]), frame_rate=29.97)
