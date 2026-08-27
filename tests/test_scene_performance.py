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
SCHEMA = ROOT / "packages" / "contracts" / "scene-performance" / "1.0.schema.json"
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

    assert plan["schema_version"] == "scene-performance/1.0"
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


def test_browser_runtime_builds_and_samples_the_same_performance_plan():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    descriptor = _descriptor()
    timeline = build_render_timeline(descriptor)
    plan = build_scene_performance(descriptor, timeline)
    frames = [timeline["events"][1]["start_frame"] + offset for offset in (0, 2, 5, 10)]
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
