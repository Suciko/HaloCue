"""Synthetic backup/restore fault boundaries; never uses an installed workspace."""

import hashlib
from pathlib import Path

import pytest

from halocue_writing import backup as backup_module
from halocue_writing.errors import DomainError
from halocue_writing.backup import USER_CONTENT_ROOTS, WritingBackupManager
from halocue_writing.repository import Repository


def populated_repository(path, marker):
    repo = Repository(path)
    with repo.transaction() as connection:
        connection.execute(
            "INSERT INTO works VALUES (?, ?, 'draft', 1, 'synthetic', 'now', 'now')",
            ("work-" + marker, marker),
        )
    for name in USER_CONTENT_ROOTS:
        directory = repo.data_dir / name
        directory.mkdir(exist_ok=True)
        (directory / "sentinel.txt").write_text(marker, encoding="utf-8")
    return repo


def content_snapshot(data_dir):
    return {
        str(path.relative_to(data_dir)): path.read_bytes()
        for name in USER_CONTENT_ROOTS
        for path in (data_dir / name).rglob("*")
        if path.is_file()
    }


def test_restore_safety_backup_failure_preserves_untouched_content(tmp_path, monkeypatch):
    repo = populated_repository(tmp_path / "writing", "original")
    manager = WritingBackupManager(repo.data_dir)
    _, content, summary = manager.export()
    before = content_snapshot(repo.data_dir)
    database_before = hashlib.sha256(repo.db_path.read_bytes()).hexdigest()

    def fail_safety_backup():
        raise OSError("synthetic safety backup failure")

    monkeypatch.setattr(manager, "export", fail_safety_backup)
    with pytest.raises(OSError, match="synthetic safety backup failure"):
        manager.restore(content, summary["backup_hash"])

    assert content_snapshot(repo.data_dir) == before
    assert hashlib.sha256(repo.db_path.read_bytes()).hexdigest() == database_before


def test_restore_keeps_rollback_copy_if_compensation_cannot_finish(tmp_path, monkeypatch):
    incoming = populated_repository(tmp_path / "incoming", "incoming")
    _, content, summary = WritingBackupManager(incoming.data_dir).export()
    current = populated_repository(tmp_path / "current", "original")
    manager = WritingBackupManager(current.data_dir)
    real_replace = backup_module.os.replace
    rollback_path = None

    def fail_install_and_rollback(source, destination):
        nonlocal rollback_path
        source, destination = Path(source), Path(destination)
        if source.parent.name == "data" and destination == current.data_dir / "artifacts":
            raise OSError("synthetic install failure")
        if source.parent.name.startswith("halocue-restore-rollback-"):
            rollback_path = source.parent
            raise OSError("synthetic compensation failure")
        return real_replace(source, destination)

    monkeypatch.setattr(backup_module.os, "replace", fail_install_and_rollback)
    with pytest.raises(DomainError) as captured:
        manager.restore(content, summary["backup_hash"])

    assert captured.value.code == "backup_restore_rollback_failed"
    assert rollback_path is not None
    assert (rollback_path / "agent-runs" / "sentinel.txt").read_text() == "original"
    assert (rollback_path / "artifacts" / "sentinel.txt").read_text() == "original"
    assert Path(captured.value.details["rollback_path"]) == rollback_path
    safety_file = current.data_dir / "backups" / captured.value.details["safety_backup"]
    assert safety_file.is_file()


def test_restore_database_failure_after_write_recovers_original_database(tmp_path, monkeypatch):
    incoming = populated_repository(tmp_path / "incoming", "incoming")
    _, content, summary = WritingBackupManager(incoming.data_dir).export()
    current = populated_repository(tmp_path / "current", "original")
    manager = WritingBackupManager(current.data_dir)
    before = content_snapshot(current.data_dir)
    real_restore = manager._restore_database
    calls = []

    def restore_then_fail(source, destination):
        real_restore(source, destination)
        calls.append(source)
        if len(calls) == 1:
            raise OSError("synthetic database finalization failure")

    monkeypatch.setattr(manager, "_restore_database", restore_then_fail)
    with pytest.raises(OSError, match="synthetic database finalization failure"):
        manager.restore(content, summary["backup_hash"])

    assert content_snapshot(current.data_dir) == before
    connection = current.connect()
    try:
        assert [row[0] for row in connection.execute("SELECT title FROM works")] == ["original"]
    finally:
        connection.close()
    assert len(calls) == 2


@pytest.mark.parametrize("phase", ["move_original", "install_incoming"])
@pytest.mark.parametrize("root_name", USER_CONTENT_ROOTS)
def test_restore_directory_failure_recovers_only_completed_swaps(
    tmp_path, monkeypatch, phase, root_name
):
    incoming = populated_repository(tmp_path / "incoming", "incoming")
    _, content, summary = WritingBackupManager(incoming.data_dir).export()
    current = populated_repository(tmp_path / "current", "original")
    manager = WritingBackupManager(current.data_dir)
    before = content_snapshot(current.data_dir)
    real_replace = backup_module.os.replace

    def fail_at_boundary(source, destination):
        source, destination = Path(source), Path(destination)
        moving_original = source == current.data_dir / root_name
        installing = source.parent.name == "data" and destination == current.data_dir / root_name
        if (phase == "move_original" and moving_original) or (
            phase == "install_incoming" and installing
        ):
            raise OSError("synthetic directory boundary failure")
        return real_replace(source, destination)

    monkeypatch.setattr(backup_module.os, "replace", fail_at_boundary)
    with pytest.raises(OSError, match="synthetic directory boundary failure"):
        manager.restore(content, summary["backup_hash"])

    assert content_snapshot(current.data_dir) == before
    assert not list(tmp_path.glob("halocue-restore-rollback-*"))


def test_restore_failure_removes_new_root_without_inventing_original(tmp_path, monkeypatch):
    incoming = populated_repository(tmp_path / "incoming", "incoming")
    _, content, summary = WritingBackupManager(incoming.data_dir).export()
    current = Repository(tmp_path / "current")
    manager = WritingBackupManager(current.data_dir)
    before = content_snapshot(current.data_dir)
    assert not (current.data_dir / "agent-runs").exists()
    real_replace = backup_module.os.replace

    def fail_after_new_root(source, destination):
        source, destination = Path(source), Path(destination)
        if source.parent.name == "data" and destination == current.data_dir / "artifacts":
            raise OSError("synthetic failure after new directory")
        return real_replace(source, destination)

    monkeypatch.setattr(backup_module.os, "replace", fail_after_new_root)
    with pytest.raises(OSError, match="synthetic failure after new directory"):
        manager.restore(content, summary["backup_hash"])

    assert not (current.data_dir / "agent-runs").exists()
    assert (current.data_dir / "artifacts").is_dir()
    assert content_snapshot(current.data_dir) == before
