import pytest

from halocue_writing.errors import DomainError
from halocue_writing.service import WritingService
from halocue_writing.repository import now


def test_trash_is_version_checked_and_restorable_without_losing_artifacts(tmp_path):
    service = WritingService(tmp_path)
    first = service.create_work({"title": "Delete me", "idea": "Keep the original idea"})
    second = service.create_work({"title": "Keep me"})
    before = service.get_work(first["id"])
    with pytest.raises(DomainError) as stale:
        service.trash_work(first["id"], {"expected_version": 0})
    assert stale.value.status == 409
    assert len(service.list_works()) == 2
    receipt = service.trash_work(first["id"], {"expected_version": before["version"]})
    assert receipt["status"] == "deleted"
    assert [item["id"] for item in service.list_works()] == [second["id"]]
    with pytest.raises(DomainError):
        service.get_work(first["id"])
    assert [item["id"] for item in service.list_deleted_works()] == [first["id"]]
    service.restore_work(first["id"], {"expected_version": receipt["version"]})
    restored = service.get_work(first["id"])
    assert restored["artifacts"] == before["artifacts"]
    assert restored["conversation_threads"] == before["conversation_threads"]
    assert service.list_deleted_works() == []
    assert service.get_work(second["id"])["version"] == second["version"]
    service.close()


def test_active_agent_work_cannot_be_trashed(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "Busy work"})
    timestamp = now()
    with service.repo.transaction() as connection:
        connection.execute(
            "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "test-running",
                work["id"],
                "work",
                work["id"],
                "Test pending task",
                "queued",
                "{}",
                "synthetic://task",
                "sha256:test",
                None,
                None,
                timestamp,
                timestamp,
            ),
        )
    with pytest.raises(DomainError) as busy:
        service.trash_work(work["id"], {"expected_version": work["version"]})
    assert busy.value.code == "work_busy"
    assert service.get_work(work["id"])["version"] == work["version"]
    assert service.list_deleted_works() == []
    service.close()
