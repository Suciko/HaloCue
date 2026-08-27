from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


MODEL_ROOT = Path(__file__).resolve().parents[1] / "packages" / "project-model"
REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME = REPO_ROOT / "apps" / "desktop-client" / "scene-preview" / "aa-runtime.js"
EVENT_REGISTRY_RUNTIME = (
    REPO_ROOT / "apps" / "desktop-client" / "scene-preview" / "scene-events-runtime.js"
)
TIMELINE_SCHEMA = REPO_ROOT / "packages" / "contracts" / "render-timeline" / "1.2.schema.json"
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


def test_non_blocking_character_motion_overlaps_the_following_event():
    timeline = build_render_timeline(
        descriptor(
            [
                {
                    "event_id": "event/nod",
                    "kind": "character-motion",
                    "motion_id": "motion/nod",
                    "duration_ms": 500,
                    "wait_for_completion": False,
                },
                {"event_id": "event/beat", "kind": "wait", "duration_ms": 100},
            ]
        ),
        frame_rate=30,
    )

    assert [
        (item["start_frame"], item["end_frame"], item["wait_for_completion"])
        for item in timeline["events"]
    ] == [(0, 15, False), (0, 3, True)]
    assert timeline["total_frames"] == 15


def test_non_blocking_background_pan_overlaps_the_following_dialogue():
    timeline = build_render_timeline(
        descriptor(
            [
                {
                    "event_id": "event/pan",
                    "kind": "halocue.ba:background-pan",
                    "duration_ms": 900,
                    "wait_for_completion": False,
                },
                {
                    "event_id": "event/line",
                    "kind": "dialogue",
                    "text": "镜头移动时继续对白。",
                    "duration_ms": 300,
                },
            ]
        ),
        frame_rate=30,
    )

    assert [
        (item["start_frame"], item["end_frame"], item["wait_for_completion"])
        for item in timeline["events"]
    ] == [(0, 27, False), (0, 9, True)]
    assert timeline["total_frames"] == 27


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


def test_ba_quick_effects_share_the_deterministic_timeline_contract():
    timeline = build_render_timeline(
        descriptor(
            [
                {
                    "event_id": "event/shake",
                    "kind": "halocue.ba:screen-shake",
                },
                {
                    "event_id": "event/text",
                    "kind": "halocue.ba:screen-text",
                    "text": "提示",
                },
            ]
        )
    )

    assert [item["duration_ms"] for item in timeline["events"]] == [360, 1800]
    assert timeline["events"][1]["start_frame"] == timeline["events"][0]["end_frame"]


@pytest.mark.parametrize(
    "events, message",
    [
        (
            [{"event_id": "event/a", "kind": "wait"}, {"event_id": "event/a", "kind": "wait"}],
            "duplicate",
        ),
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


def test_render_timeline_contract_accepts_the_model_projection():
    schema = json.loads(TIMELINE_SCHEMA.read_text(encoding="utf-8"))
    timeline = build_render_timeline(
        descriptor(
            [
                {"event_id": "event/enter", "kind": "enter", "slot": 1},
                {"event_id": "event/line", "kind": "dialogue", "text": "你好。"},
                {"event_id": "event/wait", "kind": "wait", "duration_ms": 250},
            ]
        )
    )

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(timeline)


def test_browser_runtime_builds_the_same_render_timeline_as_python():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    source = descriptor(
        [
            {"event_id": "event/background", "kind": "background"},
            {"event_id": "event/enter", "kind": "enter", "slot": 3},
            {
                "event_id": "event/nod",
                "kind": "character-motion",
                "slot": 3,
                "motion_id": "motion/nod",
                "duration_ms": 500,
                "wait_for_completion": False,
            },
            {
                "event_id": "event/pan",
                "kind": "halocue.ba:background-pan",
                "duration_ms": 900,
                "wait_for_completion": False,
            },
            {"event_id": "event/line", "kind": "dialogue", "text": "你好。\n再见！"},
            {"event_id": "event/shake", "kind": "halocue.ba:screen-shake"},
            {"event_id": "event/text", "kind": "halocue.ba:screen-text", "text": "提示"},
            {"event_id": "event/exit", "kind": "exit", "slot": 3},
        ]
    )
    script = r"""
const fs = require('fs');
const vm = require('vm');
const sandbox = {window: {}};
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), sandbox);
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  const timeline = sandbox.window.HaloCueAARuntime.buildRenderTimeline(
    JSON.parse(input),
    {frameRate: 30},
  );
  process.stdout.write(JSON.stringify(timeline));
});
"""

    completed = subprocess.run(
        [node, "-e", script, str(RUNTIME), str(EVENT_REGISTRY_RUNTIME)],
        input=json.dumps(source, ensure_ascii=False),
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )

    assert json.loads(completed.stdout) == build_render_timeline(source, frame_rate=30)


def test_browser_sample_prefers_the_latest_authored_event_during_overlap():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    source = descriptor(
        [
            {
                "event_id": "event/nod",
                "kind": "character-motion",
                "duration_ms": 500,
                "wait_for_completion": False,
            },
            {
                "event_id": "event/pan",
                "kind": "halocue.ba:background-pan",
                "duration_ms": 900,
                "wait_for_completion": False,
            },
            {
                "event_id": "event/line",
                "kind": "dialogue",
                "text": "动作中说话",
                "duration_ms": 500,
            },
        ]
    )
    script = r"""
const fs = require('fs');
const vm = require('vm');
const sandbox = {window: {}};
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), sandbox);
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
const source = JSON.parse(process.argv[3]);
const runtime = sandbox.window.HaloCueAARuntime;
const sample = runtime.sampleRenderTimeline(runtime.buildRenderTimeline(source), 1);
process.stdout.write(JSON.stringify({
  item: sample.item?.event_id,
  active: sample.activeItems.map(item => item.event_id),
}));
"""
    completed = subprocess.run(
        [node, "-e", script, str(RUNTIME), str(EVENT_REGISTRY_RUNTIME), json.dumps(source)],
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )

    assert json.loads(completed.stdout) == {
        "item": "event/line",
        "active": ["event/nod", "event/pan", "event/line"],
    }
