"""Planning model waits must not own the SQLite writer or publish stale results."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from halocue_writing.service import WritingService
from halocue_writing.providers import FakeWritingProvider


@pytest.fixture
def service(tmp_path):
    value = WritingService(tmp_path / "writing")
    yield value
    value.close()


@pytest.mark.parametrize("operation", ["work", "chapter", "legacy"])
def test_planning_wait_does_not_hold_sqlite_writer(service, operation):
    work = service.create_work({"title": "Synthetic planning", "idea": "寻找旧录音。"})
    thread = work["conversation_threads"][0]
    if operation == "legacy":
        work = service.save_brief(
            work["id"], {"expected_version": work["version"], "idea": "寻找旧录音。"}
        )["work"]
    started, finish = threading.Event(), threading.Event()

    class Slow(FakeWritingProvider):
        def generate_blueprint(self, *args, **kwargs):
            started.set()
            assert finish.wait(10)
            return super().generate_blueprint(*args, **kwargs)

        def generate_chapter_plan(self, *args, **kwargs):
            started.set()
            assert finish.wait(10)
            return super().generate_chapter_plan(*args, **kwargs)

    service.provider = Slow()

    def invoke():
        if operation == "legacy":
            return service.generate_blueprint(work["id"], {"expected_version": work["version"]})
        payload = {
            "expected_version": work["version"],
            "expected_thread_version": thread["version"],
        }
        if operation == "chapter":
            payload["task_scope"] = {"surface": "chapter", "chapter_id": work["chapters"][0]["id"]}
        return service.organize_conversation_proposal(work["id"], thread["id"], payload)

    lock_error = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(invoke)
        try:
            assert started.wait(3)
            connection = sqlite3.connect(service.repo.db_path, timeout=0.15)
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.rollback()
            except sqlite3.OperationalError as exc:
                lock_error = str(exc)
            finally:
                connection.close()
        finally:
            finish.set()
        result = future.result(timeout=5)
    assert result
    assert lock_error is None, lock_error


def prepared_operation(service, operation):
    work = service.create_work({"title": "Synthetic planning race", "idea": "寻找旧录音。"})
    thread = work["conversation_threads"][0]
    if operation == "legacy":
        work = service.save_brief(
            work["id"], {"expected_version": work["version"], "idea": "寻找旧录音。"}
        )["work"]

    def invoke():
        if operation == "legacy":
            return service.generate_blueprint(work["id"], {"expected_version": work["version"]})
        payload = {
            "expected_version": work["version"],
            "expected_thread_version": thread["version"],
        }
        if operation == "chapter":
            payload["task_scope"] = {"surface": "chapter", "chapter_id": work["chapters"][0]["id"]}
        return service.organize_conversation_proposal(work["id"], thread["id"], payload)

    return work, thread, invoke


class GatedPlanner(FakeWritingProvider):
    def __init__(self, started, finish, *, fail=False):
        self.started, self.finish, self.fail = started, finish, fail
        self.calls = 0

    def descriptor(self):
        return {**super().descriptor(), "config_digest": "frozen-planner"}

    def _wait(self):
        self.calls += 1
        self.started.set()
        assert self.finish.wait(8)
        if self.fail:
            raise RuntimeError("synthetic provider failure")

    def generate_blueprint(self, *args, **kwargs):
        self._wait()
        return super().generate_blueprint(*args, **kwargs)

    def generate_chapter_plan(self, *args, **kwargs):
        self._wait()
        return super().generate_chapter_plan(*args, **kwargs)


@pytest.mark.parametrize("operation", ["work", "chapter", "legacy"])
@pytest.mark.parametrize("change", ["unrelated", "same-work", "failure"])
def test_planning_publication_is_fixed_to_input_versions(service, operation, change):
    from halocue_writing.errors import DomainError

    work, _, invoke = prepared_operation(service, operation)
    other = service.create_work({"title": "Other work"})
    started, finish = threading.Event(), threading.Event()
    service.provider = GatedPlanner(started, finish, fail=change == "failure")
    before = service.get_work(work["id"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(invoke)
        try:
            assert started.wait(3)
            if change != "failure":
                target = work if change == "same-work" else other
                save = pool.submit(
                    service.save_brief,
                    target["id"],
                    {
                        "expected_version": target["version"],
                        "idea": "新的作者决定。",
                    },
                )
                saved = save.result(timeout=2)
                assert not pending.done()
                assert saved["work"]["version"] > target["version"]
        finally:
            finish.set()
        if change == "same-work":
            with pytest.raises(DomainError) as rejected:
                pending.result(timeout=5)
            assert rejected.value.status == 409
        elif change == "failure":
            with pytest.raises(RuntimeError, match="synthetic provider failure"):
                pending.result(timeout=5)
        else:
            result = pending.result(timeout=5)
            assert result.get("proposal_id") or result.get("revision_id")
    if change != "unrelated":
        after = service.get_work(work["id"])
        assert after["proposals"] == before["proposals"]
        assert after["conversation_threads"] == before["conversation_threads"]
        assert [
            a for a in after["artifacts"] if a["kind"] in {"story_blueprint", "chapter_plan"}
        ] == [a for a in before["artifacts"] if a["kind"] in {"story_blueprint", "chapter_plan"}]


@pytest.mark.parametrize("operation", ["work", "chapter"])
def test_archiving_thread_during_planning_rejects_late_proposal(service, operation):
    from halocue_writing.errors import DomainError

    work, thread, invoke = prepared_operation(service, operation)
    started, finish = threading.Event(), threading.Event()
    service.provider = GatedPlanner(started, finish)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(invoke)
        try:
            assert started.wait(3)
            archive = pool.submit(
                service.update_conversation_thread,
                work["id"],
                thread["id"],
                {
                    "expected_thread_version": thread["version"],
                    "status": "archived",
                },
            )
            archive.result(timeout=2)
        finally:
            finish.set()
        with pytest.raises(DomainError) as rejected:
            pending.result(timeout=5)
        assert rejected.value.status == 409
    assert service.get_work(work["id"])["proposals"] == []


@pytest.mark.parametrize("operation", ["work", "chapter", "legacy"])
def test_simultaneous_planning_publishes_only_one_result(service, operation):
    from halocue_writing.errors import DomainError

    work, _, invoke = prepared_operation(service, operation)
    started, finish = threading.Event(), threading.Event()
    service.provider = GatedPlanner(started, finish)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invoke)
        assert started.wait(3)
        second = pool.submit(invoke)
        finish.set()
        outcomes = []
        for pending in (first, second):
            try:
                outcomes.append(pending.result(timeout=5))
            except DomainError as error:
                assert error.status == 409
                outcomes.append(error)
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    current = service.get_work(work["id"])
    if operation == "legacy":
        assert (
            len([item for item in current["artifacts"] if item["kind"] == "story_blueprint"]) == 1
        )
    else:
        assert len(current["proposals"]) == 1


@pytest.mark.parametrize("operation", ["work", "chapter", "legacy"])
def test_planning_result_keeps_captured_provider_after_active_provider_changes(service, operation):
    work, _, invoke = prepared_operation(service, operation)
    started, finish = threading.Event(), threading.Event()
    frozen = GatedPlanner(started, finish)
    service.provider = frozen
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(invoke)
        try:
            assert started.wait(3)
            service.provider = FakeWritingProvider()
        finally:
            finish.set()
        result = pending.result(timeout=5)
    assert frozen.calls == 1
    if operation == "legacy":
        with service.repo.connect() as connection:
            row = connection.execute(
                "SELECT provenance_json FROM revisions WHERE id=?", (result["revision_id"],)
            ).fetchone()
        import json

        assert json.loads(row[0])["provider"]["config_digest"] == "frozen-planner"
    else:
        proposal = next(
            item for item in result["work"]["proposals"] if item["id"] == result["proposal_id"]
        )
        assert proposal["provider"]["config_digest"] == "frozen-planner"


@pytest.mark.parametrize("operation", ["work", "chapter"])
def test_planning_rechecks_expired_policy_even_without_thread_version_change(service, operation):
    from halocue_writing.errors import DomainError

    work, thread, invoke = prepared_operation(service, operation)
    started, finish = threading.Event(), threading.Event()
    service.provider = GatedPlanner(started, finish)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(invoke)
        try:
            assert started.wait(3)
            # Expiry can elapse without either author/version counter changing.
            with service.repo.transaction() as connection:
                connection.execute(
                    "UPDATE authorization_policies SET expires_at=? WHERE thread_id=?",
                    ("2000-01-01T00:00:00+00:00", thread["id"]),
                )
        finally:
            finish.set()
        with pytest.raises(DomainError) as rejected:
            pending.result(timeout=5)
        assert rejected.value.code == "agent_policy_expired"
    assert service.get_work(work["id"])["proposals"] == []
