from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import subprocess

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "packages" / "project-model"
if str(MODEL_ROOT) not in sys.path:
    sys.path.insert(0, str(MODEL_ROOT))

from scene_events import (  # noqa: E402
    DEFAULT_EVENT_DURATION_MS,
    SUPPORTED_EVENT_KINDS,
    scene_event_registry,
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_schema_and_registry_are_consistent():
    manifest = _json(ROOT / "packages" / "contracts" / "scene-events" / "1.2.json")
    schema = _json(ROOT / "packages" / "contracts" / "scene-events" / "1.2.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(manifest)
    definitions = scene_event_registry.definitions()
    assert [event["kind"] for event in definitions] == [
        event["kind"] for event in manifest["events"]
    ]
    assert len({event["kind"] for event in definitions}) == len(definitions)
    assert set(SUPPORTED_EVENT_KINDS) == {
        event["kind"] for event in definitions if event["timeline_supported"]
    }
    assert scene_event_registry.supports_non_blocking("character-motion") is True
    assert all(
        not event["supports_non_blocking"]
        for event in definitions
        if event["kind"] != "character-motion"
    )
    timeline_schema = _json(ROOT / "packages" / "contracts" / "render-timeline" / "1.2.schema.json")
    assert set(timeline_schema["$defs"]["timelineEvent"]["properties"]["kind"]["enum"]) == set(
        SUPPORTED_EVENT_KINDS
    )


def test_browser_adapter_manifest_matches_canonical_json():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    runtime = ROOT / "apps" / "desktop-client" / "scene-preview" / "scene-events-runtime.js"
    script = r"""
const fs = require('fs');
const vm = require('vm');
const sandbox = {window: {}};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
process.stdout.write(JSON.stringify(sandbox.window.HaloCueSceneEventRegistry.manifest));
"""
    completed = subprocess.run(
        [node, "-e", script, str(runtime)],
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )
    manifest = _json(ROOT / "packages" / "contracts" / "scene-events" / "1.2.json")
    assert json.loads(completed.stdout) == manifest


def test_fixed_defaults_are_read_from_the_manifest():
    assert DEFAULT_EVENT_DURATION_MS == {
        "background": 500,
        "enter": 500,
        "exit": 500,
        "character-motion": 500,
        "wait": 1000,
        "halocue.ba:background-pan": 900,
        "halocue.ba:screen-shake": 360,
        "halocue.ba:screen-text": 1800,
        "halocue.ba:hit-effect": 420,
    }


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), "1", True])
def test_duration_policy_rejects_non_positive_or_non_numeric_overrides(value):
    with pytest.raises(ValueError, match="finite positive"):
        scene_event_registry.duration_ms({"kind": "wait", "duration_ms": value})


def test_dialogue_policy_matches_aa_typewriter_costs():
    assert scene_event_registry.duration_ms({"kind": "dialogue", "text": "你好。"}) == 842
    assert scene_event_registry.duration_ms({"kind": "dialogue", "text": ""}) == 650
    assert scene_event_registry.duration_ms({"kind": "dialogue", "text": "A\n🙂"}) == 938


def test_unknown_events_are_rejected_by_timeline_but_namespaced_events_are_not_deleted():
    with pytest.raises(ValueError, match="unsupported render event kind"):
        scene_event_registry.duration_ms({"kind": "camera"})
    assert scene_event_registry.is_descriptor_renderable("halocue.ba:camera-track") is False
    assert scene_event_registry.is_descriptor_renderable("dialogue") is True
