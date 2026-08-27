from __future__ import annotations

import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "packages" / "project-model"
if str(MODEL_ROOT) not in sys.path:
    sys.path.insert(0, str(MODEL_ROOT))

from project_model import migrate_project  # noqa: E402
from scene_evaluation import evaluate_scene  # noqa: E402


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_scene_evaluation_binds_descriptor_and_timeline():
    project = _json(MODEL_ROOT / "example.synthetic.json")
    scene_id = project["chapters"][0]["scenes"][0]["scene_id"]

    evaluation = evaluate_scene(project, scene_id)

    assert evaluation["schema_version"] == "scene-evaluation/1.1"
    assert evaluation["scene_id"] == scene_id
    assert evaluation["timeline"]["scene_id"] == scene_id
    assert evaluation["timeline"]["events"][-1]["end_frame"] == evaluation["timeline"]["total_frames"]
    assert evaluation["performance"]["total_frames"] == evaluation["timeline"]["total_frames"]


def test_scene_evaluation_reports_advanced_events_without_mutating_project():
    project = migrate_project(_json(MODEL_ROOT / "example.synthetic.json"))
    scene = project["chapters"][0]["scenes"][0]
    scene["cues"][0]["events"].append(
        {
            "event_id": "event/advanced-camera",
            "kind": "halocue.ba:camera-track",
            "zoom": 1.12,
        }
    )

    evaluation = evaluate_scene(project, scene["scene_id"])

    assert evaluation["diagnostics"] == [
        {
            "code": "scene.advanced_event_omitted",
            "severity": "warning",
            "path": "scene:scene/classroom.cues[0].events[3]",
            "message": "专业演出 halocue.ba:camera-track 会保留在项目中，但当前 AA 预览不直接渲染。",
        }
    ]
    assert scene["cues"][0]["events"][-1]["event_id"] == "event/advanced-camera"
    assert all(event["event_id"] != "event/advanced-camera" for event in evaluation["descriptor"]["events"])


def test_scene_evaluation_keeps_visual_quick_effects_in_the_render_timeline():
    project = migrate_project(_json(MODEL_ROOT / "example.synthetic.json"))
    scene = project["chapters"][0]["scenes"][0]
    scene["cues"][0]["events"].append(
        {
            "event_id": "event/quick-shake",
            "kind": "halocue.ba:screen-shake",
            "duration_ms": 360,
            "intensity": 0.35,
        }
    )

    evaluation = evaluate_scene(project, scene["scene_id"])

    assert evaluation["diagnostics"] == []
    assert evaluation["descriptor"]["events"][-1]["event_id"] == "event/quick-shake"
    assert evaluation["timeline"]["events"][-1]["kind"] == "halocue.ba:screen-shake"
    assert evaluation["performance"]["operations"][-1]["source_event_id"] == "event/quick-shake"


def test_scene_evaluation_matches_contract_schema():
    project = _json(MODEL_ROOT / "example.synthetic.json")
    scene_id = project["chapters"][0]["scenes"][0]["scene_id"]
    schema = _json(ROOT / "packages" / "contracts" / "scene-evaluation" / "1.1.schema.json")
    timeline_schema = _json(ROOT / "packages" / "contracts" / "render-timeline" / "1.0.schema.json")
    performance_schema = _json(ROOT / "packages" / "contracts" / "scene-performance" / "1.0.schema.json")
    evaluation = evaluate_scene(project, scene_id)

    Draft202012Validator.check_schema(schema)
    registry = Registry().with_resource(
        timeline_schema["$id"], Resource.from_contents(timeline_schema)
    )
    registry = registry.with_resource(
        performance_schema["$id"], Resource.from_contents(performance_schema)
    )
    Draft202012Validator(schema, registry=registry).validate(evaluation)
