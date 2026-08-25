from __future__ import annotations

import json
import sys
from pathlib import Path


MODEL_ROOT = Path(__file__).resolve().parents[1] / "packages" / "project-model"
if str(MODEL_ROOT) not in sys.path:
    sys.path.insert(0, str(MODEL_ROOT))

from project_model import (  # noqa: E402
    build_aa_scene_descriptor,
    deserialize_project,
    validate_project,
)


def valid_project() -> dict:
    return {
        "schema_version": "halocue-project/1.0",
        "project_id": "project/demo",
        "title": "合成 BA 场景",
        "characters": [
            {
                "character_id": "character/alice",
                "name": "Alice",
                "resource_id": "synthetic/character/alice/portrait",
                "avatar_key": "Student_Portrait_Alice",
                "spine_key": "CharacterSpine_alice",
                "stage_media": {
                    "kind": "portrait",
                    "preview_uri": "./assets/synthetic-alice-stage.png",
                    "anchor_x": 0.5,
                    "anchor_y": 1,
                },
            },
            {
                "character_id": "character/bob",
                "name": "Bob",
                "resource_id": "synthetic/character/bob/portrait",
                "stage_media": {
                    "kind": "spine-frame",
                    "preview_uri": "./assets/synthetic-bob-stage.png",
                },
            },
        ],
        "resources": [
            {
                "resource_id": "synthetic/background/classroom",
                "role": "background",
                "logical_key": "background/classroom",
                "focus_x": 0.42,
                "focus_y": 0.68,
            },
            {
                "resource_id": "synthetic/character/alice/portrait",
                "role": "character_portrait",
                "logical_key": "character/alice/portrait",
            },
            {
                "resource_id": "synthetic/character/bob/portrait",
                "role": "character_portrait",
                "logical_key": "character/bob/portrait",
            },
        ],
        "chapters": [
            {
                "chapter_id": "chapter/intro",
                "title": "序章",
                "scenes": [
                    {
                        "scene_id": "scene/classroom",
                        "title": "教室",
                        "events": [
                            {
                                "event_id": "event/background",
                                "kind": "background",
                                "resource_id": "synthetic/background/classroom",
                            },
                            {
                                "event_id": "event/alice-enter",
                                "kind": "enter",
                                "character_id": "character/alice",
                                "slot": 1,
                            },
                            {
                                "event_id": "event/alice-line",
                                "kind": "dialogue",
                                "character_id": "character/alice",
                                "text": "欢迎来到教室。",
                            },
                            {
                                "event_id": "event/bob-enter",
                                "kind": "enter",
                                "character_id": "character/bob",
                                "slot": 4,
                            },
                        ],
                    }
                ],
            }
        ],
    }


def test_valid_project_has_no_diagnostics_and_round_trips_without_losing_ids():
    project = valid_project()

    assert validate_project(project) == []

    restored = deserialize_project(json.loads(json.dumps(project, ensure_ascii=False)))
    assert restored == project


def test_validation_reports_duplicate_ids_and_unresolved_references():
    project = valid_project()
    project["characters"].append(project["characters"][0].copy())
    project["chapters"][0]["scenes"][0]["events"][2]["resource_id"] = "resource/missing"

    diagnostics = validate_project(project)

    assert {item["code"] for item in diagnostics} >= {
        "project.duplicate_id",
        "project.unresolved_resource",
    }
    assert all(item["severity"] == "error" for item in diagnostics)


def test_aa_preview_is_deterministic_and_uses_five_stable_slots():
    descriptor = build_aa_scene_descriptor(valid_project(), "scene/classroom")

    assert descriptor["schema_version"] == "scene-descriptor/1.0"
    assert descriptor["scene_id"] == "scene/classroom"
    assert [slot["slot"] for slot in descriptor["actors"]] == [1, 2, 3, 4, 5]
    assert descriptor["actors"][0]["character_id"] == "character/alice"
    assert descriptor["actors"][0]["display_name"] == "Alice"
    assert descriptor["actors"][0]["stage_media"]["kind"] == "portrait"
    assert descriptor["actors"][0]["avatar_key"] == "Student_Portrait_Alice"
    assert descriptor["actors"][3]["character_id"] == "character/bob"
    assert all(actor["state"] == "hidden" for actor in descriptor["initial_actors"])
    assert descriptor["initial_background"] == descriptor["background"]
    assert descriptor["background"]["resource_id"] == "synthetic/background/classroom"
    assert descriptor["background"]["focus_x"] == 0.42
    assert descriptor["background"]["focus_y"] == 0.68
    assert build_aa_scene_descriptor(valid_project(), "scene/classroom") == descriptor


def test_validation_rejects_avatar_as_stage_media():
    project = valid_project()
    project["characters"][0]["stage_media"] = {
        "kind": "avatar",
        "preview_uri": "./assets/avatar.png",
    }

    diagnostics = validate_project(project)

    assert {
        "code": "project.unknown_stage_media_kind",
        "severity": "error",
        "path": "characters[0].stage_media.kind",
        "message": "stage_media kind must be one of ['portrait', 'spine-frame']",
    } in diagnostics


def test_deserialize_rejects_unknown_project_version():
    project = valid_project()
    project["schema_version"] = "halocue-project/9.0"

    try:
        deserialize_project(project)
    except ValueError as exc:
        assert "halocue-project/1.0" in str(exc)
    else:
        raise AssertionError("unknown project version must be rejected")


def test_validation_reports_non_object_entities_as_structured_diagnostics():
    project = valid_project()
    project["characters"] = ["not-an-entity"]

    diagnostics = validate_project(project)

    assert {
        "code": "project.invalid_entity",
        "severity": "error",
        "path": "characters[0]",
        "message": "character must be a JSON object",
    } in diagnostics
