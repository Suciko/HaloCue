"""Maintenance admission uses synthetic workspaces, no models or installed AA."""

import base64
import threading

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.service import WritingService


def backup_payload(service):
    _, content, summary = service.export_writing_backup()
    return {
        "content_base64": base64.b64encode(content).decode("ascii"),
        "expected_backup_hash": summary["backup_hash"],
        "replace_all_works": True,
    }


@pytest.mark.parametrize("cancel_before_restore", [False, True])
def test_restore_rejects_running_durable_handler_until_it_has_finished(
    tmp_path, cancel_before_restore
):
    service = WritingService(tmp_path / "writing")
    work = service.create_work({"title": "Original workspace"})
    payload = backup_payload(service)
    entered = threading.Event()
    release = threading.Event()
    outcomes = []

    def blocking_handler(job):
        entered.set()
        assert release.wait(timeout=10)
        return {"done": True}

    service.agent_dispatcher.register("test.blocking", blocking_handler)
    queued = service.repo.enqueue_agent_work(
        operation="test.blocking", payload={"work_id": work["id"]}
    )
    thread = threading.Thread(target=lambda: outcomes.append(service.agent_dispatcher.run_once()))
    thread.start()
    try:
        assert entered.wait(timeout=5)
        if cancel_before_restore:
            service.repo.cancel_agent_work(job_id=queued["job"]["id"])
        with pytest.raises(DomainError) as captured:
            service.restore_writing_backup(payload)
        assert captured.value.code == "backup_restore_busy"
        assert service.get_work(work["id"])["title"] == "Original workspace"
        expected_status = "cancelled" if cancel_before_restore else "running"
        assert service.get_agent_job(work["id"], queued["job"]["id"])["status"] == expected_status
    finally:
        release.set()
        thread.join(timeout=10)
        service.close()
    assert not thread.is_alive()
    assert outcomes[0]["applied"] is not cancel_before_restore
    assert service.restore_writing_backup(payload)["restored"] is True


def test_restore_rejects_queued_work_before_any_claim(tmp_path):
    service = WritingService(tmp_path / "writing")
    service.create_work({"title": "Do not drop pending work"})
    payload = backup_payload(service)
    queued = service.repo.enqueue_agent_work(operation="test.pending")

    with pytest.raises(DomainError) as captured:
        service.restore_writing_backup(payload)
    assert captured.value.code == "backup_restore_busy"
    assert queued["job"]["id"] in captured.value.details["pending_job_ids"]

    service.repo.cancel_agent_work(job_id=queued["job"]["id"])
    assert service.restore_writing_backup(payload)["restored"] is True


def test_direct_service_write_is_rejected_during_restore_and_works_afterwards(
    tmp_path, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from halocue_writing.backup import WritingBackupManager

    service = WritingService(tmp_path / "writing")
    service.create_work({"title": "Snapshot"})
    payload = backup_payload(service)
    entered = threading.Event()
    release = threading.Event()
    actual_restore = WritingBackupManager.restore

    def delayed_restore(manager, *args):
        entered.set()
        assert release.wait(timeout=10)
        return actual_restore(manager, *args)

    monkeypatch.setattr(WritingBackupManager, "restore", delayed_restore)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.restore_writing_backup, payload)
        try:
            assert entered.wait(timeout=5)
            with pytest.raises(DomainError) as captured:
                service.create_work({"title": "Must not be acknowledged then overwritten"})
            assert captured.value.code == "writing_maintenance_busy"
        finally:
            release.set()
        assert future.result(timeout=10)["restored"] is True
    created = service.create_work({"title": "After restore"})
    assert created["title"] == "After restore"


def test_failed_compensation_keeps_workspace_closed_to_new_writes(tmp_path, monkeypatch):
    from pathlib import Path
    from halocue_writing import backup as backup_module
    from halocue_writing.repository import Repository

    service = WritingService(tmp_path / "writing")
    service.create_work({"title": "Original data"})
    payload = backup_payload(service)
    replace = backup_module.os.replace

    def fail_install_and_compensation(source, destination):
        source, destination = Path(source), Path(destination)
        if source.parent.name == "data" and destination == service.repo.data_dir / "artifacts":
            raise OSError("synthetic install failure")
        if source.parent.name.startswith("halocue-restore-rollback-"):
            raise OSError("synthetic rollback failure")
        return replace(source, destination)

    monkeypatch.setattr(backup_module.os, "replace", fail_install_and_compensation)
    with pytest.raises(DomainError) as failed:
        service.restore_writing_backup(payload)
    assert failed.value.code == "backup_restore_rollback_failed"
    with pytest.raises(DomainError) as blocked:
        service.create_work({"title": "Must not write to partial restore"})
    assert blocked.value.code == "writing_recovery_required"
    with pytest.raises(DomainError) as restarted:
        Repository(service.repo.data_dir)
    assert restarted.value.code == "writing_recovery_required"


@pytest.mark.parametrize("error_type", [OSError, KeyboardInterrupt])
def test_restore_failure_releases_gate_after_complete_rollback(tmp_path, monkeypatch, error_type):
    from pathlib import Path
    from halocue_writing import backup as backup_module

    service = WritingService(tmp_path / "writing")
    service.create_work({"title": "Unchanged"})
    payload = backup_payload(service)
    replace = backup_module.os.replace

    def fail_after_first_move(source, destination):
        source, destination = Path(source), Path(destination)
        if source.parent.name == "data" and destination == service.repo.data_dir / "artifacts":
            raise error_type("synthetic interrupted restore")
        return replace(source, destination)

    monkeypatch.setattr(backup_module.os, "replace", fail_after_first_move)
    with pytest.raises(error_type):
        service.restore_writing_backup(payload)
    assert service.list_works()[0]["title"] == "Unchanged"
    assert service.create_work({"title": "Can write after rollback"})["title"].startswith("Can")
    assert not service.data_access.recovery_marker.exists()


def test_direct_read_in_progress_blocks_restore(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    service = WritingService(tmp_path / "writing")
    work = service.create_work({"title": "Live read"})
    payload = backup_payload(service)
    entered, release = threading.Event(), threading.Event()
    real_connect = service.repo.connect

    def slow_connect():
        if threading.current_thread().name.startswith("ThreadPoolExecutor"):
            entered.set()
            assert release.wait(timeout=10)
        return real_connect()

    monkeypatch.setattr(service.repo, "connect", slow_connect)
    with ThreadPoolExecutor(max_workers=1) as pool:
        reading = pool.submit(service.get_work, work["id"])
        try:
            assert entered.wait(timeout=5)
            with pytest.raises(DomainError) as captured:
                service.restore_writing_backup(payload)
            assert captured.value.code == "backup_restore_busy"
        finally:
            release.set()
        assert reading.result(timeout=10)["title"] == "Live read"


def test_restore_preserves_repository_consumers_and_external_settings(tmp_path):
    service = WritingService(tmp_path / "writing")
    service.create_work({"title": "Snapshot"})
    payload = backup_payload(service)
    repository = service.repo
    service.save_user_preferences({"char_warning_threshold": 57})
    assert service.restore_writing_backup(payload)["restored"] is True
    assert service.repo is repository
    for component in [service.sources, service.adaptations, service.agent_presentation]:
        assert component.repo is repository
    for component in [
        service.commit_projection,
        service.current_projection,
        service.writing_harness,
    ]:
        assert component.repository is repository
    assert service.agent_dispatcher.repository is repository
    assert service.user_preferences()["preferences"]["char_warning_threshold"] == 57


def test_dispatcher_does_not_claim_during_maintenance_then_resumes(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    service = WritingService(tmp_path / "writing")
    done = threading.Event()
    service.agent_dispatcher.register("test.resume", lambda job: done.set())
    service.repo.enqueue_agent_work(operation="test.resume")
    with service.data_access.maintenance(), ThreadPoolExecutor(max_workers=1) as pool:
        blocked = pool.submit(service.agent_dispatcher.run_once).result(timeout=5)
        assert blocked["blocked"] == "writing_maintenance_busy"
        assert not done.is_set()
    service.start()
    try:
        assert done.wait(timeout=5)
    finally:
        assert service.close()["stopped"] is True


def test_post_restore_initialization_failure_does_not_reopen_partial_runtime(tmp_path, monkeypatch):
    service = WritingService(tmp_path / "writing")
    service.create_work({"title": "Snapshot"})
    payload = backup_payload(service)

    def failed_initialization():
        raise OSError("synthetic schema initialization error")

    monkeypatch.setattr(service.repo, "initialize_after_restore", failed_initialization)
    with pytest.raises(OSError, match="schema initialization"):
        service.restore_writing_backup(payload)
    with pytest.raises(DomainError) as captured:
        service.list_works()
    assert captured.value.code == "writing_recovery_required"


def test_public_writing_entrypoints_keep_complete_operation_admission():
    import inspect
    from halocue_writing.adaptation import AdaptationService
    from halocue_writing.source_catalog import SourceCatalog

    # Prevent future public entrypoints from silently bypassing maintenance.
    # close must remain callable while a worker holds access; restore is exclusive.
    excluded = {"close", "restore_writing_backup"}
    for cls in (WritingService, AdaptationService, SourceCatalog):
        for name, member in vars(cls).items():
            if name.startswith("_") or name in excluded or not inspect.isfunction(member):
                continue
            assert getattr(member, "workspace_operation", False), f"{cls.__name__}.{name}"


def test_secondary_instances_and_direct_catalog_operations_cannot_bypass_restore(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from halocue_writing.repository import Repository

    first = WritingService(tmp_path / "writing")
    second = WritingService(tmp_path / "writing")

    def assert_rejected():
        actions = [
            lambda: second.create_work({"title": "No"}),
            lambda: second.sources.apply("unused-work", {}),
            lambda: second.adaptations.create("unused-work", {}),
            lambda: second.repo.atomic_write_text("artifacts/no.txt", "no"),
            lambda: Repository(tmp_path / "writing"),
            lambda: second.start(),
            lambda: second.trash_work("unused-work", {"expected_version": 1}),
            lambda: second.restore_work("unused-work", {"expected_version": 1}),
        ]
        for action in actions:
            with pytest.raises(DomainError) as captured:
                action()
            assert captured.value.code == "writing_maintenance_busy"
        with pytest.raises(DomainError) as captured:
            with second.repo.transaction():
                pytest.fail("transaction admitted")
        assert captured.value.code == "writing_maintenance_busy"

    with first.data_access.maintenance(), ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(assert_rejected).result(timeout=5)
    assert second.create_work({"title": "Works later"})["title"] == "Works later"


def test_incoming_ready_job_resumes_only_after_restored_runtime_is_initialized(tmp_path):
    source = WritingService(tmp_path / "source")
    restored_work = source.create_work({"title": "Imported queue"})
    source.repo.enqueue_agent_work(operation="test.imported")
    payload = backup_payload(source)
    target = WritingService(tmp_path / "target")
    done = threading.Event()
    observed = []

    def read_restored_work(job):
        observed.append(target.get_work(restored_work["id"])["title"])
        done.set()

    target.agent_dispatcher.register("test.imported", read_restored_work)
    # Deterministically start the idle worker behind admission, then perform
    # a service restore. It must not observe half-initialized imported data.
    with target.data_access.maintenance():
        target.start()
        try:
            assert target.restore_writing_backup(payload)["restored"] is True
            assert not done.is_set()
        except BaseException:
            target.close()
            raise
    try:
        assert done.wait(timeout=5)
        assert observed == ["Imported queue"]
    finally:
        assert target.close()["stopped"] is True


def test_restore_completion_never_restarts_a_concurrently_closed_dispatcher(tmp_path, monkeypatch):
    service = WritingService(tmp_path / "writing")
    service.create_work({"title": "Shutdown race"})
    payload = backup_payload(service)
    actual_descriptor = service.agent_dispatcher.descriptor
    closed = []

    def close_after_running_snapshot():
        snapshot = actual_descriptor()
        if not closed:
            assert snapshot["running"] is True
            closed.append(service.close())
        return snapshot

    with service.data_access.maintenance():
        service.start()
        monkeypatch.setattr(service.agent_dispatcher, "descriptor", close_after_running_snapshot)
        try:
            assert service.restore_writing_backup(payload)["restored"] is True
            assert closed == [{"stopped": True, "worker_id": service.agent_dispatcher.worker_id}]
            assert actual_descriptor()["running"] is False
        finally:
            service.close()
