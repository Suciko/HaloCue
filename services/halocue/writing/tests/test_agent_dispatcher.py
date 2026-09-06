from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.repository import Repository, canonical_json, new_id, now
from halocue_writing.service import WritingService


class CountingRetryProvider(FakeWritingProvider):
    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        with self._lock:
            self.calls += 1
        time.sleep(0.05)
        return super().discuss_work(messages, work_context)


class BlockingMemoryProvider(FakeWritingProvider):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def extract_memory_bundle(self, memory_context: dict) -> dict:
        self.started.set()
        self.release.wait(timeout=5)
        return super().extract_memory_bundle(memory_context)


def saved_scene(service: WritingService):
    work = service.create_work({"title": "持久队列场景"})
    created = service.create_scene(
        work["id"],
        work["chapters"][0]["id"],
        {"expected_version": work["version"], "title": "终端亮起", "goal": "记录新事实"},
    )
    saved = service.save_scene_manuscript(
        work["id"],
        created["scene_id"],
        {
            "expected_version": created["work"]["version"],
            "base_revision_id": None,
            "blocks": [
                {"id": "block-action", "type": "action", "speaker": "", "text": "终端在口令后亮起。"},
            ],
        },
    )
    return saved["work"], created["scene_id"]


def seed_dispatchable_agent_run(repo: Repository, *, status: str = "queued") -> dict:
    """Create the existing durable run records that a dispatch job coordinates."""
    work_id = new_id("work")
    production_run_id = new_id("run")
    agent_run_id = new_id("agent-run")
    work_item_id = new_id("item")
    attempt_id = new_id("attempt")
    timestamp = now()
    snapshot_uri, snapshot_digest = repo.atomic_write_text(
        f"artifacts/{agent_run_id}/input.json",
        canonical_json({"schema_version": "dispatcher-test/1.0", "work_id": work_id}),
    )
    with repo.transaction() as connection:
        connection.execute(
            """INSERT INTO works
               (id,title,status,version,active_writing_pack_version,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (work_id, "Dispatcher 合同", "active", 1, "test-pack", timestamp, timestamp),
        )
        connection.execute(
            """INSERT INTO production_runs
               (id,work_id,kind,automation_level,status,pinned_input_refs_json,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                production_run_id,
                work_id,
                "creation",
                "review",
                "running",
                "[]",
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            """INSERT INTO agent_runs
               (id,work_id,scope_type,scope_id,instruction,status,policy_json,
                input_snapshot_uri,input_digest,proposal_id,failure_json,created_at,finished_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                agent_run_id,
                work_id,
                "work",
                work_id,
                "执行固定输入",
                status,
                canonical_json({"workflow": "dispatcher.contract"}),
                snapshot_uri,
                snapshot_digest,
                None,
                None,
                timestamp,
                None,
            ),
        )
        connection.execute(
            """INSERT INTO work_items
               (id,run_id,type,scope_type,scope_id,status,input_refs_json,output_refs_json,
                acceptance_json,attempt_count,error_json,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                work_item_id,
                production_run_id,
                "agent.dispatch.contract",
                "work",
                work_id,
                "ready",
                canonical_json([snapshot_uri]),
                "[]",
                canonical_json({"agent_run_id": agent_run_id}),
                1,
                None,
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            """INSERT INTO job_attempts
               (id,work_item_id,ordinal,provider,request_digest,status,output_ref,
                error_code,started_at,finished_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                attempt_id,
                work_item_id,
                1,
                "dispatcher-test",
                snapshot_digest,
                "started",
                None,
                None,
                timestamp,
                None,
            ),
        )
    return {
        "work_id": work_id,
        "production_run_id": production_run_id,
        "agent_run_id": agent_run_id,
        "work_item_id": work_item_id,
        "attempt_id": attempt_id,
    }


def enqueue_seed(repo: Repository, seed: dict) -> dict:
    return repo.enqueue_agent_job(
        agent_run_id=seed["agent_run_id"],
        work_item_id=seed["work_item_id"],
    )


def test_ready_job_is_claimed_atomically_by_only_one_worker(tmp_path):
    first_repo = Repository(tmp_path)
    seed = seed_dispatchable_agent_run(first_repo)
    enqueue_seed(first_repo, seed)
    second_repo = Repository(tmp_path)
    barrier = threading.Barrier(3)
    claims: list[dict | None] = []
    errors: list[BaseException] = []

    def claim(repo: Repository, worker_id: str):
        barrier.wait()
        try:
            claims.append(repo.claim_agent_job(worker_id=worker_id, lease_seconds=30))
        except BaseException as exc:
            errors.append(exc)

    workers = [
        threading.Thread(target=claim, args=(first_repo, "worker-a")),
        threading.Thread(target=claim, args=(second_repo, "worker-b")),
    ]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=2)
        assert not worker.is_alive()

    assert not errors
    claimed = [item for item in claims if item is not None]
    assert len(claimed) == 1
    assert claimed[0]["agent_run_id"] == seed["agent_run_id"]
    assert claimed[0]["work_item_id"] == seed["work_item_id"]
    assert claimed[0]["lease_owner"] in {"worker-a", "worker-b"}
    assert claimed[0]["lease_token"]


def test_second_repository_does_not_recover_an_active_foreign_lease(tmp_path):
    first_repo = Repository(tmp_path)
    seed = seed_dispatchable_agent_run(first_repo)
    enqueue_seed(first_repo, seed)
    claimed = first_repo.claim_agent_job(worker_id="worker-a", lease_seconds=60)
    assert claimed is not None

    second_repo = Repository(tmp_path)

    assert second_repo.heartbeat_agent_job(
        job_id=claimed["id"],
        worker_id="worker-a",
        lease_token=claimed["lease_token"],
        lease_seconds=60,
    ) is True
    assert second_repo.claim_agent_job(worker_id="worker-b", lease_seconds=60) is None


def test_expired_lease_is_recovered_and_can_be_claimed_again(tmp_path):
    repo = Repository(tmp_path)
    seed = seed_dispatchable_agent_run(repo)
    enqueue_seed(repo, seed)
    first_claim = repo.claim_agent_job(worker_id="stopped-worker", lease_seconds=60)
    assert first_claim is not None
    expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with repo.transaction() as connection:
        connection.execute(
            "UPDATE agent_dispatch_jobs SET lease_expires_at=? WHERE id=?",
            (expired_at, first_claim["id"]),
        )

    assert repo.recover_expired_agent_jobs() == 1
    second_claim = repo.claim_agent_job(worker_id="replacement-worker", lease_seconds=60)

    assert second_claim is not None
    assert second_claim["id"] == first_claim["id"]
    assert second_claim["lease_owner"] == "replacement-worker"
    assert second_claim["lease_token"] != first_claim["lease_token"]


def test_expired_bound_conversation_run_is_closed_for_explicit_retry(tmp_path):
    repo = Repository(tmp_path)
    seed = seed_dispatchable_agent_run(repo, status="running")
    job = repo.enqueue_agent_job(
        agent_run_id=seed["agent_run_id"],
        work_item_id=seed["work_item_id"],
        operation="conversation.message",
        payload={"work_id": seed["work_id"], "thread_id": "thread-test"},
    )
    claimed = repo.claim_agent_job(worker_id="stopped-worker", lease_seconds=60)
    expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with repo.transaction() as connection:
        connection.execute(
            "UPDATE agent_dispatch_jobs SET lease_expires_at=? WHERE id=?",
            (expired_at, claimed["id"]),
        )

    recovery = repo.recover_expired_agent_work()

    assert recovery["interrupted_count"] == 1
    assert recovery["requeued_count"] == 0
    assert recovery["interrupted_agent_run_ids"] == [seed["agent_run_id"]]
    with repo.connect() as connection:
        restored_job = connection.execute(
            "SELECT status FROM agent_dispatch_jobs WHERE id=?", (job["id"],)
        ).fetchone()
        restored_run = connection.execute(
            "SELECT status,failure_json FROM agent_runs WHERE id=?", (seed["agent_run_id"],)
        ).fetchone()
        restored_item = connection.execute(
            "SELECT status,error_json FROM work_items WHERE id=?", (seed["work_item_id"],)
        ).fetchone()
    assert restored_job["status"] == "failed"
    assert restored_run["status"] == "failed"
    assert json.loads(restored_run["failure_json"])["code"] == "agent_process_interrupted"
    assert restored_item["status"] == "failed"
    assert repo.claim_agent_job(worker_id="replacement-worker", lease_seconds=60) is None


def test_late_completion_with_an_old_lease_token_is_discarded(tmp_path):
    repo = Repository(tmp_path)
    seed = seed_dispatchable_agent_run(repo)
    enqueue_seed(repo, seed)
    stale_claim = repo.claim_agent_job(worker_id="worker-a", lease_seconds=60)
    assert stale_claim is not None
    with repo.transaction() as connection:
        connection.execute(
            "UPDATE agent_dispatch_jobs SET lease_expires_at=? WHERE id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), stale_claim["id"]),
        )
    repo.recover_expired_agent_jobs()
    current_claim = repo.claim_agent_job(worker_id="worker-b", lease_seconds=60)
    assert current_claim is not None

    assert repo.complete_agent_job(
        job_id=stale_claim["id"],
        worker_id="worker-a",
        lease_token=stale_claim["lease_token"],
    ) is False
    assert repo.complete_agent_job(
        job_id=current_claim["id"],
        worker_id="worker-b",
        lease_token=current_claim["lease_token"],
    ) is True


def test_cancel_terminates_run_work_item_attempt_and_rejects_late_completion(tmp_path):
    repo = Repository(tmp_path)
    seed = seed_dispatchable_agent_run(repo)
    enqueue_seed(repo, seed)
    claim = repo.claim_agent_job(worker_id="worker-a", lease_seconds=60)
    assert claim is not None
    service = WritingService(tmp_path)

    cancelled = service.cancel_agent_run(seed["work_id"], seed["agent_run_id"])

    assert cancelled["status"] == "cancelled"
    restored = service.get_work(seed["work_id"])
    production_run = next(item for item in restored["runs"] if item["id"] == seed["production_run_id"])
    work_item = next(item for item in production_run["work_items"] if item["id"] == seed["work_item_id"])
    attempt = next(item for item in work_item["attempts"] if item["id"] == seed["attempt_id"])
    assert work_item["status"] == "cancelled"
    assert attempt["status"] == "cancelled"
    assert repo.complete_agent_job(
        job_id=claim["id"],
        worker_id="worker-a",
        lease_token=claim["lease_token"],
    ) is False


def test_concurrent_duplicate_enqueue_returns_one_durable_job(tmp_path):
    first_repo = Repository(tmp_path)
    seed = seed_dispatchable_agent_run(first_repo, status="failed")
    with first_repo.transaction() as connection:
        connection.execute(
            "UPDATE agent_runs SET status='queued',failure_json=NULL,finished_at=NULL WHERE id=?",
            (seed["agent_run_id"],),
        )
    second_repo = Repository(tmp_path)
    barrier = threading.Barrier(3)
    jobs: list[dict] = []
    errors: list[BaseException] = []

    def enqueue(repo: Repository):
        barrier.wait()
        try:
            jobs.append(enqueue_seed(repo, seed))
        except BaseException as exc:
            errors.append(exc)

    workers = [threading.Thread(target=enqueue, args=(repo,)) for repo in (first_repo, second_repo)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=2)
        assert not worker.is_alive()

    assert not errors
    assert len(jobs) == 2
    assert jobs[0]["id"] == jobs[1]["id"]
    with first_repo.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM agent_dispatch_jobs WHERE agent_run_id=?",
            (seed["agent_run_id"],),
        ).fetchone()[0]
    assert count == 1


def test_concurrent_retry_with_same_idempotency_key_calls_provider_once(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "并发重试合同", "idea": "讨论旧终端。"})
    thread = work["conversation_threads"][0]

    def fail_discussion(_messages, _context):
        raise DomainError("writing_provider_failed", "临时网络错误。", status=502)

    service.provider.discuss_work = fail_discussion
    with pytest.raises(DomainError) as failed:
        service.post_conversation_message(
            work["id"],
            thread["id"],
            {"expected_thread_version": thread["version"], "text": "重试这一轮。"},
        )
    failed_run_id = failed.value.details["agent_run_id"]
    current_thread = service.get_work(work["id"])["conversation_threads"][0]
    provider = CountingRetryProvider()
    service.provider = provider
    barrier = threading.Barrier(3)
    results: list[dict] = []
    errors: list[BaseException] = []

    def retry():
        barrier.wait()
        try:
            results.append(service.retry_agent_run(
                work["id"],
                failed_run_id,
                {
                    "expected_thread_version": current_thread["version"],
                    "idempotency_key": "retry-click-1",
                },
            ))
        except BaseException as exc:
            errors.append(exc)

    workers = [threading.Thread(target=retry) for _ in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=3)
        assert not worker.is_alive()

    assert not errors
    assert len(results) == 2
    assert results[0]["agent_run_id"] == results[1]["agent_run_id"]
    assert results[0]["retried_from_agent_run_id"] == failed_run_id
    assert results[1]["retried_from_agent_run_id"] == failed_run_id
    assert provider.calls == 1


def test_memory_agent_operation_runs_from_durable_queue(tmp_path):
    service = WritingService(tmp_path)
    work, scene_id = saved_scene(service)

    queued = service.enqueue_agent_operation(
        work["id"],
        {
            "operation": "memory.extract",
            "scope_id": scene_id,
            "request": {"expected_version": work["version"]},
        },
    )

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.get_agent_job(work["id"], queued["id"])
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.02)
    assert job["status"] == "succeeded"
    assert job["agent_run_id"]
    restored = service.get_work(work["id"])
    assert any(item["kind"] == "memory_bundle" for item in restored["proposals"])
    service.close()


def test_cancelled_durable_memory_job_discards_late_proposal(tmp_path):
    service = WritingService(tmp_path)
    work, scene_id = saved_scene(service)
    provider = BlockingMemoryProvider()
    service.provider = provider
    queued = service.enqueue_agent_operation(
        work["id"],
        {
            "operation": "memory.extract",
            "scope_id": scene_id,
            "request": {"expected_version": work["version"]},
        },
    )
    assert provider.started.wait(timeout=2)

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = service.get_agent_job(work["id"], queued["id"])
        if job["agent_run_id"]:
            break
        time.sleep(0.01)
    assert job["agent_run_id"]
    cancelled = service.cancel_agent_job(work["id"], queued["id"])
    assert cancelled["status"] == "cancelled"
    provider.release.set()
    time.sleep(0.1)

    restored = service.get_work(work["id"])
    assert not [item for item in restored["proposals"] if item["kind"] == "memory_bundle"]
    run = next(item for item in restored["agent_runs"] if item["id"] == job["agent_run_id"])
    assert run["status"] == "cancelled"
    service.close()
