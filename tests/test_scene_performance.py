from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "packages" / "project-model"
RUNTIME = ROOT / "apps" / "desktop-client" / "scene-preview" / "scene-performance-runtime.js"
SCHEMA = ROOT / "packages" / "contracts" / "scene-performance" / "1.4.schema.json"
if str(MODEL_ROOT) not in sys.path:
    sys.path.insert(0, str(MODEL_ROOT))

from render_timeline import build_render_timeline  # noqa: E402
from scene_performance import (  # noqa: E402
    build_scene_performance,
    sample_scene_performance,
)


def _descriptor(intensity: object = 0.35) -> dict:
    return {
        "schema_version": "scene-descriptor/1.0",
        "scene_id": "scene/performance",
        "events": [
            {"event_id": "event/wait", "kind": "wait", "duration_ms": 100},
            {
                "event_id": "event/shake",
                "kind": "halocue.ba:screen-shake",
                "duration_ms": 360,
                "intensity": intensity,
            },
            {"event_id": "event/after", "kind": "wait", "duration_ms": 100},
        ],
    }


def test_performance_plan_normalizes_shake_and_matches_contract():
    descriptor = _descriptor()
    timeline = build_render_timeline(descriptor)
    plan = build_scene_performance(descriptor, timeline)
    operation = plan["operations"][0]

    assert plan["schema_version"] == "scene-performance/1.4"
    assert operation == {
        "operation_id": "event/shake/operation/shake",
        "source_event_id": "event/shake",
        "kind": "shake",
        "target": {"kind": "stage", "target_id": "stage/global"},
        "channel": "geometry.offset",
        "value_space": "relative-to-baseline",
        "start_frame": timeline["events"][1]["start_frame"],
        "end_frame": timeline["events"][1]["end_frame"],
        "amplitude_x_px": 4.9,
        "amplitude_y_px": 2.8,
        "frequency_hz": 12,
    }
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(plan)


def test_non_blocking_shake_operation_overlaps_following_dialogue():
    descriptor = _descriptor()
    descriptor["events"] = [
        {
            "event_id": "event/shake",
            "kind": "halocue.ba:screen-shake",
            "duration_ms": 360,
            "intensity": 0.35,
            "wait_for_completion": False,
        },
        {
            "event_id": "event/line",
            "kind": "dialogue",
            "text": "震屏时继续对白。",
            "duration_ms": 300,
        },
    ]
    timeline = build_render_timeline(descriptor)
    plan = build_scene_performance(descriptor, timeline)

    assert [(event["start_frame"], event["end_frame"]) for event in timeline["events"]] == [
        (0, 11),
        (0, 9),
    ]
    assert plan["operations"][0]["start_frame"] == 0
    assert plan["operations"][0]["end_frame"] == 11
    assert sample_scene_performance(plan, 2)["active_operation_ids"] == [
        "event/shake/operation/shake"
    ]


def test_performance_sampling_is_deterministic_and_modes_share_final_state():
    descriptor = _descriptor()
    timeline = build_render_timeline(descriptor)
    plan = build_scene_performance(descriptor, timeline)
    frame = timeline["events"][1]["start_frame"] + 2

    sampled = sample_scene_performance(plan, frame, mode="sample")
    played = sample_scene_performance(plan, frame, mode="play")

    assert sampled["active_operation_ids"] == ["event/shake/operation/shake"]
    assert sampled["stage"]["offset_x_px"] != 0
    assert sampled["stage"]["offset_y_px"] != 0
    assert played["stage"] == sampled["stage"]
    assert sample_scene_performance(plan, frame, mode="skip")["stage"] == {
        "offset_x_px": 0,
        "offset_y_px": 0,
    }
    assert sample_scene_performance(plan, frame, mode="reduced-motion")["stage"] == {
        "offset_x_px": 0,
        "offset_y_px": 0,
    }


def test_enter_and_exit_share_numeric_tween_channels_and_execution_modes():
    descriptor = _descriptor()
    descriptor["initial_actors"] = [
        {"slot": slot, "character_id": None, "state": "hidden"}
        for slot in range(1, 6)
    ]
    descriptor["events"] = [
        {
            "event_id": "event/enter",
            "kind": "enter",
            "slot": 2,
            "character_id": "character/alice",
        },
        {"event_id": "event/wait", "kind": "wait", "duration_ms": 100},
        {"event_id": "event/exit", "kind": "exit", "slot": 2},
    ]
    timeline = build_render_timeline(descriptor)
    plan = build_scene_performance(descriptor, timeline)
    enter = timeline["events"][0]
    exit_event = timeline["events"][2]

    assert [
        operation["channel"]
        for operation in plan["operations"]
        if operation["source_event_id"] == "event/enter"
    ] == ["presentation.opacity", "layout.offset-y", "presentation.scale"]
    assert len(plan["source_map"][0]["operation_ids"]) == 3
    assert sample_scene_performance(plan, enter["start_frame"])["characters"] == [{
        "character_id": "character/alice",
        "slot": 2,
        "opacity": 0,
        "offset_y_px": 24,
        "rotation_deg": 0,
        "scale": 0.97,
    }]
    assert sample_scene_performance(plan, enter["end_frame"] - 1)["characters"][0] == {
        "character_id": "character/alice",
        "slot": 2,
        "opacity": 1,
        "offset_y_px": 0,
        "rotation_deg": 0,
        "scale": 1,
    }
    assert sample_scene_performance(plan, enter["start_frame"], mode="skip")["characters"][0] == {
        "character_id": "character/alice",
        "slot": 2,
        "opacity": 1,
        "offset_y_px": 0,
        "rotation_deg": 0,
        "scale": 1,
    }
    assert sample_scene_performance(
        plan, enter["start_frame"], mode="reduced-motion"
    )["characters"][0] == {
        "character_id": "character/alice",
        "slot": 2,
        "opacity": 0,
        "offset_y_px": 0,
        "rotation_deg": 0,
        "scale": 1,
    }
    assert sample_scene_performance(plan, exit_event["end_frame"] - 1)["characters"][0] == {
        "character_id": "character/alice",
        "slot": 2,
        "opacity": 0,
        "offset_y_px": 12,
        "rotation_deg": 0,
        "scale": 0.985,
    }


def test_explicit_character_motion_compiles_to_seek_safe_keyframes():
    descriptor = _descriptor()
    descriptor["initial_actors"] = [
        {"slot": 2, "character_id": "character/alice", "state": "visible"},
    ]
    descriptor["events"] = [{
        "event_id": "event/nod",
        "kind": "character-motion",
        "slot": 2,
        "character_id": "character/alice",
        "motion_id": "motion/nod",
        "duration_ms": 500,
    }]
    timeline = build_render_timeline(descriptor)
    plan = build_scene_performance(descriptor, timeline)
    event = timeline["events"][0]

    assert [operation["kind"] for operation in plan["operations"]] == [
        "numeric-keyframes",
        "numeric-keyframes",
    ]
    assert [operation["channel"] for operation in plan["operations"]] == [
        "layout.offset-y",
        "presentation.rotation",
    ]
    peak_frame = event["start_frame"] + round(
        (event["end_frame"] - event["start_frame"] - 1) * 0.32
    )
    sampled = sample_scene_performance(plan, peak_frame)["characters"][0]
    assert sampled["offset_y_px"] > 3.9
    assert sampled["rotation_deg"] > 1.4
    assert sample_scene_performance(plan, event["start_frame"], mode="skip")["characters"] == []
    assert sample_scene_performance(
        plan, event["start_frame"], mode="reduced-motion"
    )["characters"] == []
    assert sample_scene_performance(plan, event["end_frame"] - 1)["characters"][0] == {
        "character_id": "character/alice",
        "slot": 2,
        "opacity": None,
        "offset_y_px": 0,
        "rotation_deg": 0,
        "scale": 1,
    }


def test_appear_motion_rises_then_returns_to_a_clean_baseline():
    descriptor = _descriptor()
    descriptor["initial_actors"] = [
        {"slot": 2, "character_id": "character/alice", "state": "visible"},
    ]
    descriptor["events"] = [{
        "event_id": "event/appear",
        "kind": "character-motion",
        "slot": 2,
        "character_id": "character/alice",
        "motion_id": "motion/appear",
        "duration_ms": 500,
    }]
    timeline = build_render_timeline(descriptor)
    plan = build_scene_performance(descriptor, timeline)
    event = timeline["events"][0]

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(plan)

    assert [operation["channel"] for operation in plan["operations"]] == [
        "presentation.opacity",
        "layout.offset-y",
        "presentation.scale",
    ]
    assert sample_scene_performance(plan, event["start_frame"])["characters"][0] == {
        "character_id": "character/alice",
        "slot": 2,
        "opacity": 0.55,
        "offset_y_px": 10,
        "rotation_deg": 0,
        "scale": 0.985,
    }
    peak_frame = event["start_frame"] + round(
        (event["end_frame"] - event["start_frame"] - 1) * 0.55
    )
    peak = sample_scene_performance(plan, peak_frame)["characters"][0]
    assert peak["opacity"] == 1
    assert peak["offset_y_px"] < 0
    assert peak["scale"] > 1
    assert sample_scene_performance(plan, event["start_frame"], mode="skip")["characters"] == []
    assert sample_scene_performance(
        plan, event["start_frame"], mode="reduced-motion"
    )["characters"] == []
    assert sample_scene_performance(plan, event["end_frame"] - 1)["characters"][0] == {
        "character_id": "character/alice",
        "slot": 2,
        "opacity": 1,
        "offset_y_px": 0,
        "rotation_deg": 0,
        "scale": 1,
    }


def test_explicit_character_motion_rejects_a_stale_target():
    descriptor = _descriptor()
    descriptor["initial_actors"] = [
        {"slot": 1, "character_id": "character/alice", "state": "visible"},
    ]
    descriptor["events"] = [{
        "event_id": "event/wrong-motion-target",
        "kind": "character-motion",
        "slot": 1,
        "character_id": "character/bob",
        "motion_id": "motion/nod",
    }]
    timeline = build_render_timeline(descriptor)

    assert build_scene_performance(descriptor, timeline)["operations"] == []


def test_browser_runtime_builds_and_samples_the_same_performance_plan():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    descriptor = _descriptor()
    descriptor["initial_actors"] = [
        {"slot": slot, "character_id": None, "state": "hidden"}
        for slot in range(1, 6)
    ]
    descriptor["events"] = [
        {
            "event_id": "event/enter",
            "kind": "enter",
            "slot": 2,
            "character_id": "character/alice",
            "motion_id": "motion/nod",
        },
        {
            "event_id": "event/nod",
            "kind": "character-motion",
            "slot": 2,
            "character_id": "character/alice",
            "motion_id": "motion/nod",
            "duration_ms": 500,
        },
        {
            "event_id": "event/appear",
            "kind": "character-motion",
            "slot": 2,
            "character_id": "character/alice",
            "motion_id": "motion/appear",
            "duration_ms": 500,
        },
        {
            "event_id": "event/shake",
            "kind": "halocue.ba:screen-shake",
            "intensity": 0.35,
        },
        {"event_id": "event/exit", "kind": "exit", "slot": 2},
    ]
    timeline = build_render_timeline(descriptor)
    plan = build_scene_performance(descriptor, timeline)
    nod_event = timeline["events"][1]
    nod_span = nod_event["end_frame"] - nod_event["start_frame"] - 1
    appear_event = timeline["events"][2]
    appear_span = appear_event["end_frame"] - appear_event["start_frame"] - 1
    frames = [
        timeline["events"][0]["start_frame"] + 2,
        nod_event["start_frame"] + 2,
        nod_event["start_frame"] + round(nod_span * 0.32),
        nod_event["start_frame"] + round(nod_span * 0.68),
        appear_event["start_frame"],
        appear_event["start_frame"] + round(appear_span * 0.55),
        appear_event["end_frame"] - 1,
        timeline["events"][3]["start_frame"] + 2,
        timeline["events"][4]["start_frame"] + 2,
        timeline["events"][4]["end_frame"] - 1,
    ]
    script = r"""
const fs = require('fs');
const vm = require('vm');
const sandbox = {window: {}};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  const payload = JSON.parse(input);
  const runtime = sandbox.window.HaloCueScenePerformanceRuntime;
  const plan = runtime.buildScenePerformance(payload.descriptor, payload.timeline);
  const samples = payload.frames.map(frame => runtime.sampleScenePerformance(plan, frame, 'sample'));
  process.stdout.write(JSON.stringify({plan, samples}));
});
"""
    completed = subprocess.run(
        [node, "-e", script, str(RUNTIME)],
        input=json.dumps({"descriptor": descriptor, "timeline": timeline, "frames": frames}),
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )
    browser = json.loads(completed.stdout)

    assert browser["plan"] == plan
    assert browser["samples"] == [
        sample_scene_performance(plan, frame, mode="sample") for frame in frames
    ]
