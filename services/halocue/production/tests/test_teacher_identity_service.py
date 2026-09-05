from __future__ import annotations

from dataclasses import replace

import pytest

from halocue_production.errors import ProductionError
from halocue_production.service import ProductionService


@pytest.fixture
def service(settings, tmp_path):
    index = tmp_path / "teacher-resources.json"
    index.write_text(
        '{"bg":{"BG_Black":1,"BG_Classroom":2},"characters":[],"sounds":[],"enums":{"emoticon":{},"action":{}}}',
        encoding="utf-8",
    )
    instance = ProductionService(replace(settings, resource_index=index))
    yield instance
    instance.jobs.close()


def test_teacher_capabilities_offer_exact_presets_without_a_model(service):
    capability = service.capabilities()["teacher_identity"]
    assert capability["state"] == "available"
    assert capability["schema_version"] == "teacher-identity/1.0"
    assert capability["presentation"] == "slot_zero"
    assert capability["presets"] == [
        {"id": "sensei_shale", "display_name": "sensei", "organization": "沙勒"},
        {"id": "sensei_xialai", "display_name": "sensei", "organization": "夏莱"},
        {"id": "teacher_shale", "display_name": "老师", "organization": "沙勒"},
        {"id": "teacher_xialai", "display_name": "老师", "organization": "夏莱"},
        {"id": "custom", "display_name": None, "organization": None},
    ]


def create_teacher_run(service):
    return service.create_run(
        {
            "project": "Teacher identity fixture",
            "source": {
                "kind": "inline",
                "text": "SourceTeacher: Hello.\nClerk: Welcome.\nSenseiAlias: Goodbye.\n",
            },
        }
    )


def select_teacher(service, run, *, speaker="SourceTeacher", preset="teacher_shale", **fields):
    return service.update_cast(
        run["run"]["run_id"],
        {
            "speaker": speaker,
            "expected_draft_version": run["draft"]["draft_version"],
            "mapping": {
                "kind": "teacher",
                "schema_version": "teacher-identity/1.0",
                "preset_id": preset,
                **fields,
            },
        },
    )


def test_teacher_selection_freezes_resource_and_preserves_source_identity(service, settings):
    created = create_teacher_run(service)
    original_cards = [(c["card_id"], c["current"]) for c in created["draft"]["cards"]]
    selected = select_teacher(service, created)
    identity = selected["draft"]["cast"]["teacher_identity"]
    cast = selected["draft"]["cast"]["cast"]
    assert cast["SourceTeacher"]["id"] == identity["character_id"]
    assert cast.get("Clerk", {}).get("role") != "teacher"
    assert [(c["card_id"], c["current"]) for c in selected["draft"]["cards"]] == original_cards
    assert selected["draft"]["draft_version"] == created["draft"]["draft_version"] + 1
    resource = service.run_character_resource(selected["run"]["run_id"], identity["character_id"])[
        "character"
    ]
    assert (resource["name"], resource["club"]) == ("老师", "沙勒")
    assert resource["portrait"] is False
    assert resource["faces"] == []
    restarted = ProductionService(service.settings)
    try:
        restored = restarted.run_detail(selected["run"]["run_id"])
        assert restored["draft"]["cast"]["teacher_identity"] == identity
    finally:
        restarted.jobs.close()


def test_teacher_rename_updates_explicit_aliases_not_source_or_ordinary_voice(service):
    created = create_teacher_run(service)
    selected = select_teacher(service, created)
    identifier = selected["draft"]["cast"]["teacher_identity"]["character_id"]
    alias = select_teacher(service, selected, speaker="SenseiAlias")
    clerk = service.update_cast(
        alias["run"]["run_id"],
        {
            "speaker": "Clerk",
            "mapping": {"kind": "voice", "display_name": "Receptionist"},
            "expected_draft_version": alias["draft"]["draft_version"],
        },
    )
    renamed = select_teacher(
        service, clerk, preset="custom", display_name="Commander", organization=""
    )
    cast = renamed["draft"]["cast"]["cast"]
    for speaker in ("SourceTeacher", "SenseiAlias"):
        assert (cast[speaker]["id"], cast[speaker]["name"], cast[speaker]["club"]) == (
            identifier,
            "Commander",
            "",
        )
    assert cast["Clerk"] == clerk["draft"]["cast"]["cast"]["Clerk"]
    preview = service.performance_preview(renamed["run"]["run_id"])
    frames = [frame for frame in preview["frames"] if frame["card_kind"] == "line"]
    for frame in (frames[0], frames[2]):
        assert frame["title"] == "Commander"
        assert frame["speaker"]["name"] == "Commander"
        assert frame["speaker"]["organization"] == ""
        assert frame["speaker"]["source_name"] in ("SourceTeacher", "SenseiAlias")
    assert frames[1]["speaker"] == {
        "name": "Clerk",
        "mapping_kind": "voice",
        "character_id": "Receptionist",
    }


def test_repeat_teacher_selection_retains_review_and_stale_selection_conflicts(service):
    created = service.create_run(
        {"project": "Teacher review", "source": {"kind": "inline", "text": "Teacher: Hello.\n"}}
    )
    selected = select_teacher(service, created, speaker="Teacher")
    approved = service.approve_review(
        selected["run"]["run_id"],
        {
            "card_ids": None,
            "expected_draft_version": selected["draft"]["draft_version"],
        },
    )
    repeated = select_teacher(service, approved, speaker="Teacher")
    assert repeated["draft"]["draft_version"] == approved["draft"]["draft_version"]
    assert repeated["draft"]["review_ready"] is True
    assert repeated["run"]["state"] == "ready_to_compile"
    with pytest.raises(ProductionError) as stale:
        select_teacher(service, created, speaker="Teacher")
    assert (stale.value.code, stale.value.status) == ("revision_conflict", 409)


def test_teacher_http_contract_round_trip_and_unknown_version(service):
    from test_http_api import api, request

    with api(service.settings) as base:
        status, _, created = request(
            base,
            "/api/v1/production-runs",
            {
                "project": "Teacher contract",
                "source": {"kind": "inline", "text": "Sensei: Ready.\n"},
            },
            "POST",
        )
        assert status == 201
        path = f"/api/v1/production-runs/{created['run']['run_id']}"
        payload = {
            "speaker": "Sensei",
            "expected_draft_version": 1,
            "mapping": {
                "kind": "teacher",
                "schema_version": "teacher-identity/1.0",
                "preset_id": "sensei_xialai",
            },
        }
        status, _, selected = request(base, path + "/cast-bindings", payload, "POST")
        assert status == 200
        _, _, loaded = request(base, path)
        assert loaded["draft"]["cast"] == selected["draft"]["cast"]
        payload["expected_draft_version"] = selected["draft"]["draft_version"]
        payload["mapping"]["schema_version"] = "teacher-identity/99.0"
        status, _, invalid = request(base, path + "/cast-bindings", payload, "POST")
        assert status == 400
        assert invalid == {
            "ok": False,
            "error": {
                "code": "teacher_identity_version_unsupported",
                "message": "不支持该老师身份合同版本",
                "details": {},
            },
        }
        _, _, unchanged = request(base, path)
        assert unchanged["draft"] == loaded["draft"]


def test_teacher_cannot_be_selected_as_portrait_or_injected_into_ordinary_mapping(service):
    selected = select_teacher(service, create_teacher_run(service))
    identifier = selected["draft"]["cast"]["teacher_identity"]["character_id"]
    for mapping, expected_code in [
        ({"kind": "portrait", "id": identifier}, "teacher_requires_no_portrait"),
        ({"kind": "voice", "role": "teacher"}, "invalid_cast_binding"),
        ({"kind": "voice", "display_name": identifier}, "teacher_identity_conflict"),
    ]:
        with pytest.raises(ProductionError) as error:
            service.update_cast(
                selected["run"]["run_id"],
                {
                    "speaker": "Clerk",
                    "mapping": mapping,
                    "expected_draft_version": selected["draft"]["draft_version"],
                },
            )
        assert error.value.code == expected_code


def test_unsupported_legacy_teacher_capability_keeps_other_mappings_working(service, monkeypatch):
    monkeypatch.setattr(service.adapter.store, "update_teacher_identity", None)
    assert service.capabilities()["teacher_identity"]["state"] == "unavailable"
    created = create_teacher_run(service)
    with pytest.raises(ProductionError) as error:
        select_teacher(service, created)
    assert error.value.code == "teacher_identity_unavailable"
    result = service.update_cast(
        created["run"]["run_id"],
        {
            "speaker": "Clerk",
            "mapping": {"kind": "voice"},
            "expected_draft_version": 1,
        },
    )
    assert result["draft"]["cast"]["cast"]["Clerk"]["kind"] == "voice"


def test_teacher_change_supersedes_late_model_result_without_overwriting_identity(
    service, monkeypatch
):
    from test_direction_profiles import FixtureProvider, finished_job

    monkeypatch.setenv("HALOCUE_TEACHER_FIXTURE_KEY", "synthetic-secret")
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "teacher-fixture",
            "api_key_env": "HALOCUE_TEACHER_FIXTURE_KEY",
        }
    )
    provider = FixtureProvider(blocked=True)
    monkeypatch.setattr(service.direction_models, "provider", lambda: provider)
    created = service.create_run(
        {
            "project": "Teacher during generation",
            "generation_mode": "ai_direction",
            "source": {"kind": "inline", "text": "SourceTeacher: Keep this text.\n"},
        }
    )
    selected = select_teacher(service, created)
    assert provider.stats["calls"] == 0
    run_id = selected["run"]["run_id"]
    _, started = service.generate_direction(
        run_id, {"expected_draft_version": selected["draft"]["draft_version"]}
    )
    try:
        assert provider.entered.wait(5), str(
            service.job_detail(started["job"]["job_id"])["job"].get("error")
        )
        renamed = select_teacher(service, selected, preset="sensei_xialai")
    finally:
        provider.released.set()
    job = finished_job(service, started["job"]["job_id"])
    assert job["state"] == "superseded", job
    loaded = service.run_detail(run_id)
    assert loaded["draft"] == renamed["draft"]
    assert loaded["draft"]["cast"]["teacher_identity"]["preset_id"] == "sensei_xialai"
    assert provider.stats["calls"] == 1
