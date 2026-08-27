from __future__ import annotations

import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "packages" / "project-model"
if str(MODEL_ROOT) not in sys.path:
    sys.path.insert(0, str(MODEL_ROOT))

from project_model import build_aa_scene_descriptor, deserialize_project, validate_project  # noqa: E402


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_cue_project_and_character_capability_examples_match_contracts():
    project_schema = _json(
        ROOT / "packages" / "contracts" / "halocue-project" / "1.1.schema.json"
    )
    capability_schema = _json(
        ROOT
        / "packages"
        / "contracts"
        / "character-capabilities"
        / "1.0.schema.json"
    )
    project = _json(MODEL_ROOT / "example.synthetic.json")
    capability = _json(
        ROOT
        / "packages"
        / "contracts"
        / "character-capabilities"
        / "example.synthetic.json"
    )

    Draft202012Validator.check_schema(project_schema)
    Draft202012Validator.check_schema(capability_schema)
    Draft202012Validator(project_schema).validate(project)
    Draft202012Validator(capability_schema).validate(capability)
    assert deserialize_project(project) == project


def test_namespaced_advanced_event_survives_simple_preview_projection():
    project = _json(MODEL_ROOT / "example.synthetic.json")
    advanced = {
        "event_id": "event/advanced-camera",
        "kind": "halocue.ba:camera-track",
        "zoom": 1.12,
        "extension_payload": {"curve": "ease-out"},
    }
    project["chapters"][0]["scenes"][0]["cues"][0]["events"].insert(2, advanced)

    diagnostics = validate_project(project)
    assert diagnostics == [
        {
            "code": "project.unknown_event_kind",
            "severity": "warning",
            "path": "chapters[0].scenes[0].cues[0].events[2].kind",
            "message": "unsupported event kind 'halocue.ba:camera-track'",
        }
    ]
    restored = deserialize_project(project)
    assert restored["chapters"][0]["scenes"][0]["cues"][0]["events"][2] == advanced
    descriptor = build_aa_scene_descriptor(restored, "scene/classroom")
    assert [event["event_id"] for event in descriptor["events"]] == [
        "event/background",
        "event/alice-enter",
        "event/alice-line",
    ]


def test_non_finite_duration_is_rejected():
    project = _json(MODEL_ROOT / "example.synthetic.json")
    project["chapters"][0]["scenes"][0]["cues"][0]["events"][0]["duration_ms"] = float("inf")

    assert any(item["code"] == "project.invalid_duration" for item in validate_project(project))


def test_preview_intent_contract_accepts_an_explicit_event_playhead_target():
    schema = _json(
        ROOT / "packages" / "contracts" / "preview-intent" / "1.0.schema.json"
    )
    intent = {
        "schema_version": "preview-intent/1.0",
        "scene_id": "scene/classroom",
        "cue_id": "cue/classroom/001",
        "selection_kind": "event",
        "selected_event_id": "event/alice-line",
        "target": {
            "event_id": "event/alice-line",
            "frame": 42,
            "alignment": "start",
            "resolution": "selected-event",
        },
    }

    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(intent)
    mismatched_alignment = json.loads(json.dumps(intent))
    mismatched_alignment["target"]["alignment"] = "end"
    assert not validator.is_valid(mismatched_alignment)


def test_preview_intent_1_1_contract_accepts_only_exact_playhead_targets():
    schema = _json(
        ROOT / "packages" / "contracts" / "preview-intent" / "1.1.schema.json"
    )
    intent = {
        "schema_version": "preview-intent/1.1",
        "scene_id": "scene/classroom",
        "cue_id": "cue/classroom/001",
        "selection_kind": "playhead",
        "selected_event_id": None,
        "target": {
            "event_id": "event/alice-line",
            "frame": 47,
            "alignment": "exact",
            "resolution": "explicit-frame",
        },
    }

    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(intent)
    event_selection = json.loads(json.dumps(intent))
    event_selection["selection_kind"] = "event"
    event_selection["selected_event_id"] = "event/alice-line"
    assert not validator.is_valid(event_selection)
