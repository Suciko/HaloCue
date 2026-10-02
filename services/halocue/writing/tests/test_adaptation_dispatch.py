"""Durable adaptation jobs use synthetic providers and temporary workspaces."""

import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.service import WritingService
from test_adaptation_integrity import prepared, valid_reply, ReplyProvider


def request(url, method="GET", body=None):
    # Do not import ambiguous test_http_api: production and writing both define it.
    import urllib.request

    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return response.status, json.loads(response.read())


class BlockingReply(ReplyProvider):
    def __init__(self, reply):
        super().__init__(reply)
        self.started = threading.Event()
        self.release = threading.Event()

    def generate_scene(self, context):
        self.started.set()
        assert self.release.wait(8), "synthetic provider not released"
        return super().generate_scene(context)


def queue(service, work, source, plan, **kwargs):
    return service.adaptation_jobs.enqueue(
        work["id"], plan["id"], source["chapters"][0]["id"], kwargs
    )


def terminal(service, work_id, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = service.get_agent_job(work_id, job_id)
        if result["status"] in {"succeeded", "failed", "cancelled"}:
            return result
        time.sleep(0.01)
    pytest.fail("adaptation job did not finish")


def test_queue_returns_durable_run_before_blocking_provider_completes(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    provider = BlockingReply(json.dumps(valid_reply(source["chapters"][0])))
    service.provider = provider
    try:
        queued = queue(service, work, source, plan)
        assert queued["agent_run_id"]
        assert provider.started.wait(2)
        run = service.get_agent_run(work["id"], queued["agent_run_id"])
        assert run["status"] == "running"
        assert run["policy"]["workflow"] == "adaptation.chapter.generate"
        assert not service.get_work(work["id"])["proposals"]
        provider.release.set()
        assert terminal(service, work["id"], queued["job"]["id"])["status"] == "succeeded"
        finished = service.get_agent_run(work["id"], queued["agent_run_id"])
        assert finished["status"] == "completed"
        assert finished["proposal_id"]
        assert service.adaptations.get(plan["id"])["budget"]["reserved_calls"] == 1
    finally:
        provider.release.set()
        service.close()


def test_cancelled_job_discards_late_candidate_and_preserves_charged_attempt(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    provider = BlockingReply(json.dumps(valid_reply(source["chapters"][0])))
    service.provider = provider
    try:
        queued = queue(service, work, source, plan)
        assert provider.started.wait(2)
        service.cancel_agent_job(work["id"], queued["job"]["id"])
        provider.release.set()
        service.close()
        assert not service.get_work(work["id"])["proposals"]
        assert service.get_agent_run(work["id"], queued["agent_run_id"])["status"] == "cancelled"
        assert service.adaptations.get(plan["id"])["budget"]["reserved_calls"] == 1
    finally:
        provider.release.set()
        service.close()


def test_queued_cancel_costs_no_call_and_can_retry_through_existing_run_api(tmp_path, monkeypatch):
    service, work, source, plan = prepared(tmp_path)
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    first = queue(service, work, source, plan)
    second = queue(service, work, source, plan)
    assert first["agent_run_id"] == second["agent_run_id"]
    assert second["deduplicated"] is True
    service.cancel_agent_job(work["id"], first["job"]["id"])
    assert service.adaptations.get(plan["id"])["budget"]["reserved_calls"] == 0
    retry = service.retry_agent_run(work["id"], first["agent_run_id"], {})
    assert retry["agent_run_id"] != first["agent_run_id"]
    assert service.agent_dispatcher.run_once()["handled"]
    assert service.get_agent_run(work["id"], retry["agent_run_id"])["status"] == "completed"
    assert service.adaptations.get(plan["id"])["budget"]["reserved_calls"] == 1


def test_queued_request_survives_restart_without_automatically_changing_inputs(
    tmp_path, monkeypatch
):
    service, work, source, plan = prepared(tmp_path)
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    queued = queue(service, work, source, plan)
    restored = WritingService(service.repo.data_dir)
    assert restored.get_agent_job(work["id"], queued["job"]["id"])["status"] == "ready"
    assert restored.agent_dispatcher.run_once()["handled"]
    assert restored.get_agent_run(work["id"], queued["agent_run_id"])["status"] == "completed"


@pytest.mark.parametrize("change", ["plan", "source", "lease"])
def test_late_result_checks_pinned_inputs_and_lease(tmp_path, change):
    service, work, source, plan = prepared(tmp_path)
    provider = BlockingReply(json.dumps(valid_reply(source["chapters"][0])))
    service.provider = provider
    try:
        queued = queue(service, work, source, plan)
        assert provider.started.wait(2)
        with service.repo.transaction() as connection:
            if change == "plan":
                connection.execute(
                    "UPDATE adaptations SET plan_json='{}' WHERE id=?", (plan["id"],)
                )
            elif change == "source":
                connection.execute("DELETE FROM work_sources WHERE work_id=?", (work["id"],))
            else:
                past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
                connection.execute(
                    "UPDATE agent_dispatch_jobs SET lease_expires_at=? WHERE id=?",
                    (past, queued["job"]["id"]),
                )
        provider.release.set()
        service.close()
        assert not service.get_work(work["id"])["proposals"]
    finally:
        provider.release.set()
        service.close()


def test_http_generation_returns_202_before_model_finishes(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from http.server import ThreadingHTTPServer
    from pathlib import Path
    from halocue_writing.app import make_handler

    service, work, source, plan = prepared(tmp_path)
    provider = BlockingReply(json.dumps(valid_reply(source["chapters"][0])))
    service.provider = provider
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(service, Path(__file__).resolve().parents[1] / "web")
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/v1/works/{work['id']}/adaptations/{plan['id']}/chapters/{source['chapters'][0]['id']}/candidate:generate"
        response = pool.submit(request, url, "POST", {})
        assert provider.started.wait(3)
        status, body = response.result(timeout=1)
        assert status == 202
        assert body["data"]["agent_run_id"]
        assert body["data"]["job"]["operation"] == "adaptation.chapter.generate"
    finally:
        provider.release.set()
        pool.shutdown(wait=True)
        service.close()
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_expired_running_adaptation_requires_explicit_retry(tmp_path, monkeypatch):
    service, work, source, plan = prepared(tmp_path)
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    queued = queue(service, work, source, plan)
    claim = service.repo.claim_agent_work(lease_owner="dead-worker")
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with service.repo.transaction() as c:
        c.execute("UPDATE agent_runs SET status='running' WHERE id=?", (queued["agent_run_id"],))
        c.execute(
            "UPDATE agent_dispatch_jobs SET lease_expires_at=? WHERE id=?",
            (past, claim["job"]["id"]),
        )
    restored = WritingService(service.repo.data_dir)
    assert restored.get_agent_run(work["id"], queued["agent_run_id"])["status"] == "failed"
    assert restored.get_agent_job(work["id"], queued["job"]["id"])["status"] == "failed"
    assert restored.agent_dispatcher.run_once()["handled"] is False


def test_model_configuration_change_before_execution_never_charges_call(tmp_path, monkeypatch):
    service, work, source, plan = prepared(tmp_path)
    provider = ReplyProvider(json.dumps(valid_reply(source["chapters"][0])))
    provider.descriptor = lambda: {"config_digest": "config-A"}
    service.provider = provider
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    queued = queue(service, work, source, plan)
    provider.descriptor = lambda: {"config_digest": "config-B"}
    service.agent_dispatcher.run_once()
    assert provider.calls == 0
    assert (
        service.get_agent_run(work["id"], queued["agent_run_id"])["failure"]["code"]
        == "provider_config_changed"
    )
    assert service.adaptations.get(plan["id"])["budget"]["reserved_calls"] == 0


def test_failed_physical_candidate_attempt_stays_charged_and_budget_blocks_retry(
    tmp_path, monkeypatch
):
    service, work, source, plan = prepared(tmp_path, max_calls=1)
    service.provider = ReplyProvider("invalid json")
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    queued = queue(service, work, source, plan)
    service.agent_dispatcher.run_once()
    assert service.get_agent_run(work["id"], queued["agent_run_id"])["status"] == "failed"
    retry = service.retry_agent_run(work["id"], queued["agent_run_id"], {})
    service.agent_dispatcher.run_once()
    assert (
        service.get_agent_run(work["id"], retry["agent_run_id"])["failure"]["code"]
        == "adaptation_budget_exhausted"
    )
    assert service.provider.calls == 1
    assert service.adaptations.get(plan["id"])["budget"]["reserved_calls"] == 1


def test_dispatcher_reports_committed_adaptation_as_succeeded(tmp_path, monkeypatch):
    service, work, source, plan = prepared(tmp_path)
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    queue(service, work, source, plan)
    outcome = service.agent_dispatcher.run_once()
    assert outcome["status"] == "succeeded"
    assert outcome["applied"] is True


def test_recovery_does_not_regenerate_already_committed_candidate(tmp_path, monkeypatch):
    service, work, source, plan = prepared(tmp_path)
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    queued = queue(service, work, source, plan)
    claim = service.repo.claim_agent_work(lease_owner="synthetic-crash")
    service.adaptation_jobs.dispatch(claim["job"])
    with service.repo.transaction() as c:
        # Simulate a crash after candidate transaction but before dispatcher completion.
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        c.execute(
            "UPDATE agent_dispatch_jobs SET status='running',lease_expires_at=? WHERE id=?",
            (past, queued["job"]["id"]),
        )
    restored = WritingService(service.repo.data_dir)
    assert restored.get_agent_job(work["id"], queued["job"]["id"])["status"] == "succeeded"
    assert restored.get_agent_run(work["id"], queued["agent_run_id"])["status"] == "completed"
    assert restored.agent_dispatcher.run_once()["handled"] is False
    assert len(restored.get_work(work["id"])["proposals"]) == 1


def test_retry_rejects_changed_plan_instead_of_rebasing_old_job(tmp_path, monkeypatch):
    service, work, source, plan = prepared(tmp_path)
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    queued = queue(service, work, source, plan)
    service.cancel_agent_job(work["id"], queued["job"]["id"])
    with service.repo.transaction() as c:
        c.execute("UPDATE adaptations SET plan_json='{}' WHERE id=?", (plan["id"],))
    with pytest.raises(DomainError) as rejected:
        service.retry_agent_run(work["id"], queued["agent_run_id"], {})
    assert rejected.value.code == "adaptation_inputs_changed"
    assert service.adaptations.get(plan["id"])["budget"]["reserved_calls"] == 0


def test_concurrent_requests_deduplicate_one_queued_execution(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    service, work, source, plan = prepared(tmp_path)
    other = WritingService(service.repo.data_dir)
    for instance in (service, other):
        monkeypatch.setattr(instance.agent_dispatcher, "start", lambda: None)
    barrier = threading.Barrier(2)

    def enqueue(instance):
        barrier.wait(3)
        return queue(instance, work, source, plan)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(enqueue, (service, other)))
    assert len({result["agent_run_id"] for result in results}) == 1
    assert sum(result["deduplicated"] for result in results) == 1
    assert service.adaptations.get(plan["id"])["budget"]["reserved_calls"] == 0


def test_http_adaptation_cannot_be_queued_under_another_work(tmp_path, monkeypatch):
    service, work, source, plan = prepared(tmp_path)
    other = service.create_work({"title": "other"})
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    with pytest.raises(DomainError) as rejected:
        service.adaptation_jobs.enqueue(other["id"], plan["id"], source["chapters"][0]["id"])
    assert rejected.value.status == 404


def test_postcommit_response_failure_does_not_fail_completed_job(tmp_path, monkeypatch):
    service, work, source, plan = prepared(tmp_path)
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    queued = queue(service, work, source, plan)
    original = service.adaptations.get

    def get(adaptation_id):
        value = original(adaptation_id)
        if value["chapters"][0]["status"] == "candidate":
            raise OSError("synthetic response assembly failure after commit")
        return value

    monkeypatch.setattr(service.adaptations, "get", get)
    result = service.agent_dispatcher.run_once()
    assert result["status"] == "succeeded"
    assert service.get_agent_job(work["id"], queued["job"]["id"])["status"] == "succeeded"
    assert len(service.get_work(work["id"])["proposals"]) == 1


def test_local_coverage_http_reports_completed_not_queued(tmp_path):
    from http.server import ThreadingHTTPServer
    from pathlib import Path
    from halocue_writing.app import make_handler

    service, work, source, plan = prepared(tmp_path)
    provider = ReplyProvider("must not call a provider for local source coverage")
    service.provider = provider
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(service, Path(__file__).resolve().parents[1] / "web")
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/v1/works/{work['id']}/adaptations/{plan['id']}/run"
        status, body = request(url, "POST", {})
        assert status == 200
        assert body["data"]["chapters"][0]["candidate"]["source_only"] is True
        assert provider.calls == 0
    finally:
        server.shutdown()
        server.server_close()
        worker.join(3)
        service.close()


def test_simulation_pinned_job_cannot_switch_to_real_provider(tmp_path, monkeypatch):
    service, work, source, plan = prepared(tmp_path)
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    queued = queue(service, work, source, plan)
    replacement = ReplyProvider(json.dumps(valid_reply(source["chapters"][0])))
    replacement.is_simulation = False
    replacement.descriptor = lambda: {
        "kind": "synthetic-real",
        "config_digest": "real-config",
        "is_simulation": False,
    }
    service.provider = replacement
    service.agent_dispatcher.run_once()
    assert replacement.calls == 0
    assert (
        service.get_agent_run(work["id"], queued["agent_run_id"])["failure"]["code"]
        == "provider_config_changed"
    )
    assert service.adaptations.get(plan["id"])["budget"]["reserved_calls"] == 0


def test_retry_between_run_failure_and_job_finalization_creates_new_run(tmp_path, monkeypatch):
    service, work, source, plan = prepared(tmp_path)
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    service.provider = ReplyProvider("bad json")
    queued = queue(service, work, source, plan)
    fail = service.repo.fail_agent_work
    retried = []

    def failure_boundary(**kwargs):
        retried.append(
            service.retry_agent_run(
                work["id"], queued["agent_run_id"], {"idempotency_key": "retry-gap"}
            )
        )
        return fail(**kwargs)

    monkeypatch.setattr(service.repo, "fail_agent_work", failure_boundary)
    service.agent_dispatcher.run_once()
    assert retried[0]["agent_run_id"] != queued["agent_run_id"]
    cached = service.retry_agent_run(
        work["id"], queued["agent_run_id"], {"idempotency_key": "retry-gap"}
    )
    assert cached["agent_run_id"] == retried[0]["agent_run_id"]


def test_adaptation_task_updates_existing_production_run_summary(tmp_path, monkeypatch):
    service, work, source, plan = prepared(tmp_path)
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    queue(service, work, source, plan)
    with service.repo.connect() as c:
        run = c.execute(
            "SELECT status FROM production_runs WHERE work_id=? AND kind='creation'", (work["id"],)
        ).fetchone()
    assert run["status"] == "running"
    service.agent_dispatcher.run_once()
    with service.repo.connect() as c:
        run = c.execute(
            "SELECT status FROM production_runs WHERE work_id=? AND kind='creation'", (work["id"],)
        ).fetchone()
    assert run["status"] == "waiting_user"


def test_expired_adaptation_preserves_running_summary_for_queued_sibling(tmp_path, monkeypatch):
    service, work, source, plan = prepared(tmp_path, text="第一章\n门开了。\n第二章\n灯亮了。")
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    first = queue(service, work, source, plan)
    second = service.adaptation_jobs.enqueue(work["id"], plan["id"], source["chapters"][1]["id"])
    claimed = service.repo.claim_agent_work(lease_owner="dead-worker")
    assert claimed["job"]["id"] == first["job"]["id"]
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with service.repo.transaction() as c:
        c.execute("UPDATE agent_runs SET status='running' WHERE id=?", (first["agent_run_id"],))
        c.execute(
            "UPDATE agent_dispatch_jobs SET lease_expires_at=? WHERE id=?",
            (past, first["job"]["id"]),
        )
    restored = WritingService(service.repo.data_dir)
    assert restored.get_agent_run(work["id"], first["agent_run_id"])["status"] == "failed"
    assert restored.get_agent_job(work["id"], second["job"]["id"])["status"] == "ready"
    with restored.repo.connect() as c:
        run = c.execute(
            "SELECT status FROM production_runs WHERE work_id=? AND kind='creation'", (work["id"],)
        ).fetchone()
    assert run["status"] == "running"


def test_enqueue_honors_provider_identity_confirmed_in_ui(tmp_path, monkeypatch):
    service, work, source, plan = prepared(tmp_path)
    expected = service.provider.descriptor()
    replacement = ReplyProvider("not called")
    replacement.descriptor = lambda: {
        "kind": "synthetic-real",
        "is_simulation": False,
        "config_digest": "changed",
    }
    service.provider = replacement
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    with pytest.raises(DomainError) as rejected:
        queue(service, work, source, plan, expected_provider=expected)
    assert rejected.value.code == "provider_config_changed"
    with service.repo.connect() as c:
        assert (
            c.execute(
                "SELECT COUNT(*) FROM agent_dispatch_jobs WHERE operation='adaptation.chapter.generate'"
            ).fetchone()[0]
            == 0
        )
    assert replacement.calls == 0
