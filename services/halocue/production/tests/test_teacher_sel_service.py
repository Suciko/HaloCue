from __future__ import annotations

import json

import pytest

from halocue_production.errors import ProductionError
from halocue_production.service import ProductionService
import test_teacher_identity_service as teacher_tests
from test_teacher_identity_service import select_teacher, create_teacher_run

service = teacher_tests.service


def test_sel_capability_and_preview_keep_original_cards(service):
    capability = service.capabilities()["teacher_presentation"]
    assert capability["state"] == "available"
    assert capability["schema_version"] == "teacher-presentation/1.0"
    assert capability["default_mode"] == "slot_zero"
    assert [row["id"] for row in capability["modes"]] == ["slot_zero", "sel_single"]
    created = create_teacher_run(service)
    selected = select_teacher(
        service,
        created,
        presentation={"schema_version": "teacher-presentation/1.0", "mode": "sel_single"},
    )
    preview = service.performance_preview(selected["run"]["run_id"])
    first = preview["frames"][0]
    assert first["presentation"] == "teacher_selection"
    assert first["teacher_reply"]["source_card_id"] == created["draft"]["cards"][0]["card_id"]
    assert first["teacher_reply"]["text"] == first["text"] == "Hello."
    assert preview["frames"][1]["presentation"] == "dialogue"
    assert "teacher_reply" not in preview["frames"][1]
    assert [(c["card_id"], c["source_id"], c["current"]) for c in selected["draft"]["cards"]] == [
        (c["card_id"], c["source_id"], c["current"]) for c in created["draft"]["cards"]
    ]


def test_old_client_rename_keeps_sel_after_restart_and_switch_back_requires_review(service):
    selected = select_teacher(
        service,
        create_teacher_run(service),
        presentation={"schema_version": "teacher-presentation/1.0", "mode": "sel_single"},
    )
    renamed = select_teacher(
        service, selected, preset="custom", display_name="Advisor", organization=""
    )
    assert renamed["draft"]["cast"]["teacher_presentation"]["mode"] == "sel_single"
    reopened = ProductionService(service.settings)
    try:
        current = reopened.run_detail(selected["run"]["run_id"])
        assert current["draft"]["cast"] == renamed["draft"]["cast"]
        changed = select_teacher(
            reopened,
            current,
            presentation={"schema_version": "teacher-presentation/1.0", "mode": "slot_zero"},
        )
        assert changed["draft"]["draft_version"] == current["draft"]["draft_version"] + 1
        assert (
            reopened.performance_preview(current["run"]["run_id"])["frames"][0]["presentation"]
            == "dialogue"
        )
        assert (
            changed["draft"]["cast"]["teacher_identity"]["character_id"]
            == current["draft"]["cast"]["teacher_identity"]["character_id"]
        )
    finally:
        reopened.jobs.close()


def test_sel_http_round_trip_unknown_version_and_stale_version(service):
    from test_http_api import api, request

    with api(service.settings) as base:
        _, _, created = request(
            base,
            "/api/v1/production-runs",
            {"project": "Sel HTTP", "source": {"kind": "inline", "text": "Teacher: Ready.\n"}},
            "POST",
        )
        path = f"/api/v1/production-runs/{created['run']['run_id']}/cast-bindings"
        payload = {
            "speaker": "Teacher",
            "expected_draft_version": 1,
            "mapping": {
                "kind": "teacher",
                "schema_version": "teacher-identity/1.0",
                "preset_id": "teacher_shale",
                "presentation": {
                    "schema_version": "teacher-presentation/99.0",
                    "mode": "sel_single",
                },
            },
        }
        status, _, invalid = request(base, path, payload, "POST")
        assert status == 400
        assert invalid["error"]["code"] == "teacher_presentation_version_unsupported"
        payload["mapping"]["presentation"]["schema_version"] = "teacher-presentation/1.0"
        status, _, selected = request(base, path, payload, "POST")
        assert status == 200
        assert (
            selected["draft"]["cast"]["teacher_presentation"] == payload["mapping"]["presentation"]
        )
        status, _, stale = request(base, path, payload, "POST")
        assert (status, stale["error"]["code"]) == (409, "revision_conflict")
        assert str(service.settings.data_dir) not in json.dumps(selected)


def test_old_adapter_rejects_mode_before_mutating_identity(service, monkeypatch):
    monkeypatch.delattr(service.adapter._teacher_module, "PRESENTATION_SCHEMA_VERSION")
    assert service.capabilities()["teacher_identity"]["state"] == "available"
    assert service.capabilities()["teacher_presentation"]["state"] == "unavailable"
    created = create_teacher_run(service)
    with pytest.raises(ProductionError) as caught:
        select_teacher(
            service,
            created,
            presentation={"schema_version": "teacher-presentation/1.0", "mode": "sel_single"},
        )
    assert caught.value.code == "teacher_presentation_unavailable"
    assert service.run_detail(created["run"]["run_id"])["draft"]["draft_version"] == 1
    assert (
        select_teacher(service, created)["draft"]["cast"]["cast"]["SourceTeacher"]["role"]
        == "teacher"
    )


def test_switching_presentation_supersedes_late_model_result(service, monkeypatch):
    from test_direction_profiles import FixtureProvider, finished_job

    monkeypatch.setenv("HALOCUE_SEL_TEST_KEY", "synthetic-secret")
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "sel-fixture",
            "api_key_env": "HALOCUE_SEL_TEST_KEY",
        }
    )
    provider = FixtureProvider(blocked=True)
    monkeypatch.setattr(service.direction_models, "provider", lambda: provider)
    created = service.create_run(
        {
            "project": "Sel late result",
            "generation_mode": "ai_direction",
            "source": {"kind": "inline", "text": "SourceTeacher: Ready.\n"},
        }
    )
    selected = select_teacher(service, created)
    _, job = service.generate_direction(
        selected["run"]["run_id"], {"expected_draft_version": selected["draft"]["draft_version"]}
    )
    try:
        assert provider.entered.wait(5)
        changed = select_teacher(
            service,
            selected,
            presentation={"schema_version": "teacher-presentation/1.0", "mode": "sel_single"},
        )
    finally:
        provider.released.set()
    assert finished_job(service, job["job"]["job_id"])["state"] == "superseded"
    assert service.run_detail(selected["run"]["run_id"])["draft"] == changed["draft"]
    assert provider.stats["calls"] == 1


@pytest.mark.parametrize(
    "text,code",
    [
        ("", "teacher_reply_empty"),
        ("[s1] Injected", "teacher_reply_unsafe_text"),
        ("#wait;1", "teacher_reply_unsafe_text"),
    ],
)
def test_unsafe_or_empty_reply_blocks_review_gate_but_can_switch_back(service, text, code):
    created = service.create_run(
        {"project": "Reply gate", "source": {"kind": "inline", "text": f"SourceTeacher: {text}\n"}}
    )
    selected = select_teacher(
        service,
        created,
        presentation={"schema_version": "teacher-presentation/1.0", "mode": "sel_single"},
    )
    assert selected["draft"]["counts"]["blocking_errors"] >= 1
    assert code in {issue["code"] for issue in selected["draft"]["diagnostics"]}
    assert selected["gates"]["compile"]["passed"] is False
    reverted = select_teacher(
        service,
        selected,
        presentation={"schema_version": "teacher-presentation/1.0", "mode": "slot_zero"},
    )
    assert code not in {issue["code"] for issue in reverted["draft"]["diagnostics"]}
