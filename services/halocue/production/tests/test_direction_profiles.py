from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import replace

import pytest

from halocue_production.errors import ProductionError
from halocue_production.service import ProductionService


class FixtureProvider:
    name = "fixture"
    model = "direction-profile-fixture"
    cfg = {"max_tokens": 4096, "annotation_max_tokens": 4096, "reasoning_mode": "balanced"}

    def __init__(self, *, blocked=False, fail=False):
        self.entered = threading.Event()
        self.released = threading.Event()
        self.blocked = blocked
        self.fail = fail
        self.stats = {"calls": 0, "in": 0, "out": 0}
        self.request_records = []
        self.reasoning_records = []

    def complete_json(self, _static, _volatile, user, _schema):
        self.stats["calls"] += 1
        self.entered.set()
        if self.blocked:
            assert self.released.wait(10), "fixture model was not released"
        if self.fail:
            raise RuntimeError("fixture provider failed")
        fingerprints = re.findall(r"\[TARGET ([^\]]+)\].*?fingerprint=([0-9a-f]+)", user)
        rows = []
        for source_id, fingerprint in fingerprints:
            row = dict.fromkeys(
                ("face", "emo", "act", "fx", "se", "bg_request", "place", "bgfx", "trans", "shot"),
                "",
            )
            row.update(
                source_id=source_id,
                text_fingerprint=fingerprint,
                bg="BG_Classroom",
                shake=False,
                move=0,
            )
            rows.append(row)
        return {"lines": rows, "state_delta": {}, "memory_events": []}

    def report(self):
        return "fixture"


@pytest.fixture
def direction_service(settings, tmp_path, monkeypatch):
    index = tmp_path / "profile-resources.json"
    index.write_text(
        json.dumps(
            {
                "bg": {"BG_Black": 1, "BG_Classroom": 2},
                "sounds": [],
                "characters": [],
                "enums": {"emoticon": {}, "action": {}},
            }
        ),
        encoding="utf-8",
    )
    service = ProductionService(replace(settings, resource_index=index))
    monkeypatch.setenv("HALOCUE_PROFILE_TEST_KEY", "fixture-secret")
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "fixture",
            "api_key_env": "HALOCUE_PROFILE_TEST_KEY",
        }
    )
    yield service
    service.jobs.close()


def mapped_run(service, profile="standard"):
    created = service.create_run(
        {
            "project": "Direction profile",
            "generation_mode": "ai_direction",
            "direction_profile": profile,
            "source": {"kind": "inline", "text": "Narrator: Hello.\n"},
        }
    )
    mapped = service.update_cast(
        created["run"]["run_id"],
        {
            "speaker": "Narrator",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    return created["run"]["run_id"], mapped["draft"]["draft_version"]


def finished_job(service, job_id):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        job = service.job_detail(job_id)["job"]
        if job["state"] in {"succeeded", "failed", "paused", "cancelled", "superseded"}:
            return job
        time.sleep(0.01)
    pytest.fail(f"Job did not settle: {job}")


@pytest.mark.parametrize(
    "selection, expected", [(None, "standard"), ("conservative", "conservative")]
)
def test_created_run_keeps_direction_profile_after_restart(settings, selection, expected):
    service = ProductionService(settings)
    payload = {
        "project": "Profile fixture",
        "source": {"kind": "inline", "text": "Narrator: Hello.\n"},
    }
    if selection is not None:
        payload["direction_profile"] = selection
    try:
        created = service.create_run(payload)
        run_id = created["run"]["run_id"]
        assert created["run"]["source_summary"]["direction_profile"] == expected
    finally:
        service.jobs.close()
    restored = ProductionService(settings)
    try:
        assert restored.run_detail(run_id)["run"]["source_summary"]["direction_profile"] == expected
    finally:
        restored.jobs.close()


@pytest.mark.parametrize("selection", ["", "invalid", "STANDARD", {}, [], False])
def test_create_run_rejects_invalid_direction_profile(settings, selection):
    service = ProductionService(settings)
    try:
        with pytest.raises(ProductionError) as failure:
            service.create_run(
                {
                    "project": "Invalid profile",
                    "direction_profile": selection,
                    "source": {"kind": "inline", "text": "Narrator: Hello.\n"},
                }
            )
        assert failure.value.code == "invalid_direction_profile"
        assert failure.value.status == 400
        assert service.list_runs()["items"] == []
    finally:
        service.jobs.close()


def test_generation_freezes_selected_profile_and_ignores_client_snapshot(
    direction_service, monkeypatch
):
    service = direction_service
    provider = FixtureProvider()
    monkeypatch.setattr(service.direction_models, "provider", lambda: provider)
    run_id, version = mapped_run(service, "conservative")
    _, accepted = service.generate_direction(
        run_id,
        {
            "expected_draft_version": version,
            "direction_profile_snapshot": {
                "id": "standard",
                "version": "999",
                "rules_sha256": "secret-forgery",
            },
        },
    )
    job = finished_job(service, accepted["job"]["job_id"])
    assert job["state"] == "succeeded", job
    snapshot = job["direction_profile_snapshot"]
    assert snapshot["id"] == "conservative"
    assert snapshot["version"] == "1.0"
    assert re.fullmatch(r"[0-9a-f]{64}", snapshot["rules_sha256"])
    assert accepted["direction_profile_snapshot"] == snapshot
    audit = service.direction_proposals(run_id)["generations"][0]
    assert audit["direction_profile_snapshot"] == snapshot
    assert "secret-forgery" not in json.dumps(job)


def test_active_job_only_deduplicates_same_valid_profile(direction_service, monkeypatch):
    service = direction_service
    provider = FixtureProvider(blocked=True)
    monkeypatch.setattr(service.direction_models, "provider", lambda: provider)
    run_id, version = mapped_run(service, "conservative")
    payload = {"expected_draft_version": version}
    _, first = service.generate_direction(run_id, payload)
    try:
        assert provider.entered.wait(3)
        audit = service.direction_proposals(run_id)["generations"][0]
        assert audit["status"] == "running"
        assert audit["direction_profile_snapshot"] == first["direction_profile_snapshot"]
        _, duplicate = service.generate_direction(run_id, payload)
        assert duplicate["job"]["job_id"] == first["job"]["job_id"]
        assert duplicate["deduplicated"] is True
        for profile, code, status in [
            ("invalid", "invalid_direction_profile", 400),
            ("standard", "direction_profile_conflict", 409),
        ]:
            with pytest.raises(ProductionError) as failure:
                service.generate_direction(run_id, {**payload, "direction_profile": profile})
            assert (failure.value.code, failure.value.status) == (code, status)
    finally:
        provider.released.set()
        finished_job(service, first["job"]["job_id"])


@pytest.mark.parametrize("operation, state", [("pause_job", "paused"), ("cancel_job", "cancelled")])
def test_stopped_generation_keeps_profile_and_does_not_commit_late_results(
    direction_service,
    monkeypatch,
    operation,
    state,
):
    service = direction_service
    provider = FixtureProvider(blocked=True)
    monkeypatch.setattr(service.direction_models, "provider", lambda: provider)
    run_id, version = mapped_run(service, "conservative")
    _, accepted = service.generate_direction(run_id, {"expected_draft_version": version})
    try:
        assert provider.entered.wait(3)
        getattr(service, operation)(accepted["job"]["job_id"])
    finally:
        provider.released.set()
    job = finished_job(service, accepted["job"]["job_id"])
    assert job["state"] == state
    assert job["direction_profile_snapshot"] == accepted["direction_profile_snapshot"]
    assert service.run_detail(run_id)["draft"]["draft_version"] == version
    assert all(
        card["current"].get("bg") != "BG_Classroom"
        for card in service.run_detail(run_id)["draft"]["cards"]
    )


def test_retry_after_restart_retains_original_profile_even_after_another_mode_ran(
    direction_service,
    monkeypatch,
):
    service = direction_service
    provider = FixtureProvider(blocked=True)
    monkeypatch.setattr(service.direction_models, "provider", lambda: provider)
    run_id, version = mapped_run(service, "conservative")
    payload = {"expected_draft_version": version}
    _, original = service.generate_direction(run_id, payload)
    try:
        assert provider.entered.wait(3)
        service.pause_job(original["job"]["job_id"])
    finally:
        provider.released.set()
    assert finished_job(service, original["job"]["job_id"])["state"] == "paused"

    replacement_provider = FixtureProvider(blocked=True)
    monkeypatch.setattr(service.direction_models, "provider", lambda: replacement_provider)
    _, replacement_job = service.generate_direction(
        run_id, {**payload, "direction_profile": "standard"}
    )
    try:
        assert replacement_provider.entered.wait(3)
        service.cancel_job(replacement_job["job"]["job_id"])
    finally:
        replacement_provider.released.set()
    assert finished_job(service, replacement_job["job"]["job_id"])["state"] == "cancelled"
    assert replacement_job["generation_id"] != original["generation_id"]
    assert service.run_detail(run_id)["run"]["source_summary"]["direction_profile"] == "standard"
    service.jobs.close()

    restored = ProductionService(service.settings)
    monkeypatch.setattr(restored.direction_models, "provider", FixtureProvider)
    try:
        assert (
            restored.job_detail(original["job"]["job_id"])["job"]["direction_profile_snapshot"]
            == original["direction_profile_snapshot"]
        )
        retried = restored.retry_job(original["job"]["job_id"])
        job = finished_job(restored, retried["job"]["job_id"])
        assert job["state"] == "succeeded", job
        assert job["direction_profile_snapshot"] == original["direction_profile_snapshot"]
        assert job["result"]["generation_id"] == original["generation_id"]
        assert job["resumed_from_job_id"] == original["job"]["job_id"]
    finally:
        restored.jobs.close()


@pytest.mark.parametrize("change", ["version", "rules"])
def test_rule_upgrade_rejects_resume_without_new_model_call(direction_service, monkeypatch, change):
    service = direction_service
    provider = FixtureProvider(blocked=True)
    monkeypatch.setattr(service.direction_models, "provider", lambda: provider)
    run_id, version = mapped_run(service, "conservative")
    _, original = service.generate_direction(run_id, {"expected_draft_version": version})
    try:
        assert provider.entered.wait(3)
        service.pause_job(original["job"]["job_id"])
    finally:
        provider.released.set()
    assert finished_job(service, original["job"]["job_id"])["state"] == "paused"
    import prompt

    if change == "version":
        monkeypatch.setattr(prompt, "PROFILE_VERSION", "1.1")
    else:
        monkeypatch.setattr(
            prompt, "CONSERVATIVE_RULES", prompt.CONSERVATIVE_RULES + "\nNew rules."
        )
    with pytest.raises(ProductionError) as failure:
        service.retry_job(original["job"]["job_id"])
    assert (failure.value.code, failure.value.status) == ("direction_profile_changed", 409)
    assert len(service.list_jobs()["items"]) == 1
    assert provider.stats["calls"] == 1
    assert (
        service.job_detail(original["job"]["job_id"])["job"]["direction_profile_snapshot"]
        == original["direction_profile_snapshot"]
    )


def test_failed_model_generation_retains_profile_audit(direction_service, monkeypatch):
    service = direction_service
    provider = FixtureProvider(fail=True)
    monkeypatch.setattr(service.direction_models, "provider", lambda: provider)
    run_id, version = mapped_run(service, "conservative")
    _, accepted = service.generate_direction(run_id, {"expected_draft_version": version})
    job = finished_job(service, accepted["job"]["job_id"])
    assert job["state"] == "failed", job
    audit = service.direction_proposals(run_id)["generations"][0]
    assert audit["status"] == "failed"
    assert audit["direction_profile_snapshot"] == accepted["direction_profile_snapshot"]
    assert service.run_detail(run_id)["draft"]["draft_version"] == version
    assert job["result"]["metrics"]["requests"] == audit["metrics"]["requests"]
    assert service.run_detail(run_id)["last_job"]["result"]["metrics"] == job["result"]["metrics"]
    monkeypatch.setattr(service.adapter, "direction_proposals", lambda _: {"generations": [{
        "generation_id": accepted["generation_id"], "metrics": {"requests": 99},
    }]})
    assert service.job_detail(job["job_id"])["job"]["result"]["metrics"]["requests"] == audit["metrics"]["requests"]


def test_failed_job_projects_complete_receipts_but_does_not_invent_missing_tokens(direction_service, monkeypatch):
    service = direction_service
    monkeypatch.setattr(service.direction_models, "provider", lambda: FixtureProvider(fail=True))
    run_id, version = mapped_run(service, "conservative")
    _, accepted = service.generate_direction(run_id, {"expected_draft_version": version})
    job_id = accepted["job"]["job_id"]
    assert finished_job(service, job_id)["state"] == "failed"
    records = [{"input_tokens": 10, "output_tokens": 3, "cache_read_tokens": 0, "outcome": "failed"},
               {"input_tokens": 20, "output_tokens": 4, "cache_read_tokens": 0, "outcome": "failed"}]
    monkeypatch.setattr(service.adapter, "direction_proposals", lambda _: {"generations": [{
        "generation_id": accepted["generation_id"],
        "metrics": {"requests": 2, "failed_request_count": 2, "request_records": records},
    }]})
    raw_job = service.jobs.get(job_id).to_dict()
    raw_job["events"] = []
    metrics = service._job_with_direction_metrics(raw_job)["result"]["metrics"]
    assert (metrics["input_tokens"], metrics["output_tokens"], metrics["failed_request_input_tokens"]) == (30, 7, 30)
    assert metrics["cache_read_tokens"] == 0 and metrics["cache_reported"] is True
    records[1].pop("input_tokens")
    metrics = service._job_with_direction_metrics(raw_job)["result"]["metrics"]
    assert "input_tokens" not in metrics and "failed_request_input_tokens" not in metrics


def test_capabilities_describe_profiles_and_compatibility_defaults(settings):
    service = ProductionService(settings)
    try:
        profiles = service.capabilities()["direction_profiles"]
        assert profiles["version"] == "1.0"
        assert profiles["default_api"] == "standard"
        assert profiles["default_new_project_ui"] == "conservative"
        assert {item["id"] for item in profiles["items"]} == {"standard", "conservative"}
    finally:
        service.jobs.close()


def test_older_annotation_module_keeps_standard_but_declines_conservative(settings, monkeypatch):
    import prompt

    monkeypatch.delattr(prompt, "profile_snapshot")
    monkeypatch.delattr(prompt, "PROFILE_VERSION")
    service = ProductionService(settings)
    try:
        profiles = service.capabilities()["direction_profiles"]
        assert profiles["default_new_project_ui"] == "standard"
        assert [item["id"] for item in profiles["items"]] == ["standard"]
        payload = {
            "project": "Old module",
            "source": {"kind": "inline", "text": "Narrator: Hello.\n"},
        }
        assert (
            service.create_run(payload)["run"]["source_summary"]["direction_profile"] == "standard"
        )
        with pytest.raises(ProductionError) as failure:
            service.create_run({**payload, "direction_profile": "conservative"})
        assert (failure.value.code, failure.value.status) == ("direction_profile_unavailable", 409)
    finally:
        service.jobs.close()


def test_background_allowlist_error_has_stable_public_code(direction_service, monkeypatch):
    class MissingBackgroundProvider(FixtureProvider):
        def complete_json(self, *args):
            result = super().complete_json(*args)
            for row in result["lines"]:
                row["bg"] = "BG_Unlisted"
            return result

    service = direction_service
    monkeypatch.setattr(service.direction_models, "provider", MissingBackgroundProvider)
    run_id, version = mapped_run(service, "conservative")
    _, accepted = service.generate_direction(run_id, {"expected_draft_version": version})
    job = finished_job(service, accepted["job"]["job_id"])
    assert job["state"] == "failed"
    assert job["error"]["code"] == "background_not_in_manifest"
    assert service.run_detail(run_id)["draft"]["draft_version"] == version


def test_conservative_fallback_reaches_reviewed_build_without_installing(
    direction_service,
    tmp_path,
    monkeypatch,
):
    class NoBackgroundProvider(FixtureProvider):
        def complete_json(self, *args):
            result = super().complete_json(*args)
            for row in result["lines"]:
                row["bg"] = ""
            return result

    service = direction_service
    workspace = tmp_path / "synthetic-aa-workspace"
    for child in ("projects", "saves", "overrides", "settings"):
        (workspace / child).mkdir(parents=True)
    service.configure_aa_workspace({"path": str(workspace)})
    monkeypatch.setattr(service.direction_models, "provider", NoBackgroundProvider)
    run_id, version = mapped_run(service, "conservative")
    _, generated = service.generate_direction(run_id, {"expected_draft_version": version})
    assert finished_job(service, generated["job"]["job_id"])["state"] == "succeeded"
    current = service.run_detail(run_id)
    assert current["run"]["state"] == "waiting_for_review"
    assert any(
        d["code"] == "background_approximate_match"
        for d in service.direction_proposals(run_id)["generations"][0]["diagnostics"]
    )
    with pytest.raises(ProductionError):
        service.compile(run_id, {"expected_draft_version": current["draft"]["draft_version"]})
    approved = service.approve_review(
        run_id,
        {
            "card_ids": None,
            "expected_draft_version": current["draft"]["draft_version"],
        },
    )
    _, compiled = service.compile(
        run_id, {"expected_draft_version": approved["draft"]["draft_version"]}
    )
    job = finished_job(service, compiled["job"]["job_id"])
    assert job["state"] == "succeeded", job
    assert service.run_detail(run_id)["run"]["last_build_id"] == compiled["build_id"]
    assert list((workspace / "projects").iterdir()) == []
    assert list((workspace / "saves").iterdir()) == []


@pytest.mark.parametrize(
    "change",
    [
        {"base_url": "https://different.invalid/v1"},
        {"max_tokens": 2048},
        {"reasoning_mode": "quality"},
    ],
)
def test_direction_retry_rejects_changed_model_configuration(
    direction_service, monkeypatch, change
):
    service = direction_service
    provider = FixtureProvider(blocked=True)
    monkeypatch.setattr(service.direction_models, "provider", lambda: provider)
    run_id, version = mapped_run(service)
    _, original = service.generate_direction(run_id, {"expected_draft_version": version})
    try:
        assert provider.entered.wait(3)
        service.pause_job(original["job"]["job_id"])
    finally:
        provider.released.set()
    assert finished_job(service, original["job"]["job_id"])["state"] == "paused"
    service.configure_direction_model({"api_key_env": "HALOCUE_PROFILE_TEST_KEY", **change})
    with pytest.raises(ProductionError) as rejected:
        service.retry_job(original["job"]["job_id"])
    assert rejected.value.code == "direction_model_changed"
    assert len(service.list_jobs()["items"]) == 1
    assert provider.stats["calls"] == 1


def test_cancelled_preflight_does_not_publish_late_analysis(direction_service, monkeypatch):
    service = direction_service
    entered, released = threading.Event(), threading.Event()

    class LatePreflight:
        name = "synthetic"
        model = "preflight"

        def complete_json(self, *args):
            entered.set()
            assert released.wait(8)
            return {"potential_speakers": [], "scenes": [], "ambiguities": []}

    monkeypatch.setattr(service.direction_models, "provider", LatePreflight)
    run_id, _ = mapped_run(service)
    _, accepted = service.start_ai_preflight(run_id)
    try:
        assert entered.wait(3)
        service.cancel_job(accepted["job"]["job_id"])
    finally:
        released.set()
    assert finished_job(service, accepted["job"]["job_id"])["state"] == "cancelled"
    assert service.ai_preflights(run_id)["items"] == []


def test_completed_preflight_publish_is_not_later_reported_cancelled(
    direction_service, monkeypatch
):
    service = direction_service
    committed, finish = threading.Event(), threading.Event()
    original = service.adapter.execute_ai_preflight

    class Preflight:
        name = "synthetic"
        model = "preflight"

        def complete_json(self, *args):
            return {"potential_speakers": [], "scenes": [], "ambiguities": []}

    def hold_after_publish(**kwargs):
        result = original(**kwargs)
        committed.set()
        assert finish.wait(8)
        return result

    monkeypatch.setattr(service.direction_models, "provider", Preflight)
    monkeypatch.setattr(service.adapter, "execute_ai_preflight", hold_after_publish)
    run_id, _ = mapped_run(service)
    _, job = service.start_ai_preflight(run_id)
    try:
        assert committed.wait(3)
        with pytest.raises(ProductionError) as rejected:
            service.cancel_job(job["job"]["job_id"])
        assert rejected.value.code == "job_not_cancellable"
    finally:
        finish.set()
    assert finished_job(service, job["job"]["job_id"])["state"] == "succeeded"
    assert len(service.ai_preflights(run_id)["items"]) == 1


def test_old_direction_job_without_model_identity_requires_new_generation(
    direction_service, monkeypatch
):
    service = direction_service
    provider = FixtureProvider(blocked=True)
    monkeypatch.setattr(service.direction_models, "provider", lambda: provider)
    run_id, version = mapped_run(service)
    _, accepted = service.generate_direction(run_id, {"expected_draft_version": version})
    try:
        assert provider.entered.wait(3)
        service.pause_job(accepted["job"]["job_id"])
    finally:
        provider.released.set()
    assert finished_job(service, accepted["job"]["job_id"])["state"] == "paused"
    record = service.jobs.get(accepted["job"]["job_id"])
    record.retry_context.pop("model_identity")
    with pytest.raises(ProductionError) as rejected:
        service.retry_job(record.job_id)
    assert rejected.value.code == "job_retry_unavailable"
    assert service.job_detail(record.job_id)["job"]["retryable"] is False
    assert service.job_detail(record.job_id)["job"]["resumable"] is False


def test_generation_fails_fast_while_model_activation_owns_config_lock(
    direction_service, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError

    service = direction_service
    monkeypatch.setattr(service.direction_models, "provider", FixtureProvider)
    run_id, version = mapped_run(service)
    entered, release = threading.Event(), threading.Event()

    def activation_in_progress():
        with service.direction_model_settings.activation_lock:
            entered.set()
            assert release.wait(6)

    thread = threading.Thread(target=activation_in_progress)
    thread.start()
    try:
        assert entered.wait(2)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                service.generate_direction, run_id, {"expected_draft_version": version}
            )
            try:
                with pytest.raises(ProductionError) as blocked:
                    future.result(timeout=1)
                assert blocked.value.code == "direction_model_busy"
            except TimeoutError:
                pytest.fail("generation held state lock while waiting for activation")
            finally:
                release.set()
    finally:
        release.set()
        thread.join(3)


def test_retry_cannot_deduplicate_to_fresh_job_after_model_change(direction_service, monkeypatch):
    service = direction_service
    original_provider = FixtureProvider(blocked=True)
    monkeypatch.setattr(service.direction_models, "provider", lambda: original_provider)
    run_id, version = mapped_run(service)
    _, first = service.generate_direction(run_id, {"expected_draft_version": version})
    try:
        assert original_provider.entered.wait(3)
        service.pause_job(first["job"]["job_id"])
    finally:
        original_provider.released.set()
    assert finished_job(service, first["job"]["job_id"])["state"] == "paused"
    service.configure_direction_model(
        {"model": "different", "api_key_env": "HALOCUE_PROFILE_TEST_KEY"}
    )
    fresh_provider = FixtureProvider(blocked=True)
    monkeypatch.setattr(service.direction_models, "provider", lambda: fresh_provider)
    _, second = service.generate_direction(run_id, {"expected_draft_version": version})
    try:
        assert fresh_provider.entered.wait(3)
        with pytest.raises(ProductionError) as rejected:
            service.retry_job(first["job"]["job_id"])
        assert rejected.value.code == "direction_model_changed"
        assert len(service.list_jobs()["items"]) == 2
    finally:
        service.cancel_job(second["job"]["job_id"])
        fresh_provider.released.set()
    finished_job(service, second["job"]["job_id"])


def test_committed_profile_survives_failed_attempt_and_read_is_nonmutating(
    direction_service, monkeypatch
):
    service = direction_service
    monkeypatch.setattr(service.direction_models, "provider", lambda: FixtureProvider())
    run_id, version = mapped_run(service, "conservative")
    assert service.run_detail(run_id)["draft_direction_profile"] is None
    _, first = service.generate_direction(run_id, {"expected_draft_version": version})
    assert finished_job(service, first["job"]["job_id"])["state"] == "succeeded"
    detail = service.run_detail(run_id)
    committed = detail["draft_direction_profile"]
    assert committed["id"] == "conservative"
    assert committed["generation_id"] == detail["run"]["last_direction_generation_id"]
    frozen_draft = detail["draft"]
    monkeypatch.setattr(service.direction_models, "provider", lambda: FixtureProvider(fail=True))
    _, failed = service.generate_direction(
        run_id,
        {"expected_draft_version": frozen_draft["draft_version"], "direction_profile": "standard"},
    )
    assert finished_job(service, failed["job"]["job_id"])["state"] == "failed"
    after = service.run_detail(run_id)
    assert after["run"]["source_summary"]["direction_profile"] == "standard"
    assert after["draft_direction_profile"] == committed
    assert after["draft"] == frozen_draft


def test_missing_profile_record_is_unknown_not_inferred_from_attempt(direction_service):
    service = direction_service
    run_id, _ = mapped_run(service, "standard")
    run = service.repository.get_run(run_id)
    run.last_direction_generation_id = "direction-123456abcdef"
    service.repository.save_run(run)
    assert service.run_detail(run_id)["draft_direction_profile"] is None
    assert service.adapter.committed_direction_profile(run.draft_token, "../../outside") is None
