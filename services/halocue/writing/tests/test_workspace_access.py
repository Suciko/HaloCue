"""Cross-thread/process admission, with real OS locks on temporary directories."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.workspace_access import workspace_access


SOURCE = Path(__file__).resolve().parents[1] / "src"


def child_attempt(data_dir, mode, *, crash=False):
    script = """
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from halocue_writing.workspace_access import workspace_access
from halocue_writing.errors import DomainError
access = workspace_access(Path(sys.argv[2]))
try:
    with getattr(access, sys.argv[3])():
        if sys.argv[4] == 'crash':
            with access.restoring():
                os._exit(7)
        print(json.dumps({'acquired': True}))
except DomainError as error:
    print(json.dumps({'acquired': False, 'code': error.code}))
"""
    return subprocess.run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-c",
            script,
            str(SOURCE),
            str(data_dir),
            mode,
            "crash" if crash else "normal",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )


@pytest.mark.parametrize(
    ("outer", "inner", "allowed"),
    [
        ("operation", "operation", True),
        ("operation", "maintenance", False),
        ("maintenance", "operation", False),
        ("maintenance", "maintenance", False),
    ],
)
def test_cross_process_shared_and_exclusive_admission(tmp_path, outer, inner, allowed):
    access = workspace_access(tmp_path)
    with getattr(access, outer)():
        result = child_attempt(tmp_path, inner)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["acquired"] is allowed
    if not allowed:
        assert observed["code"] == (
            "backup_restore_busy" if inner == "maintenance" else "writing_maintenance_busy"
        )
    after = child_attempt(tmp_path, "maintenance")
    assert after.returncode == 0 and json.loads(after.stdout)["acquired"] is True


def test_nested_operations_do_not_deadlock_but_cannot_upgrade(tmp_path):
    access = workspace_access(tmp_path)
    with access.operation():
        with workspace_access(tmp_path).operation():
            with pytest.raises(DomainError) as captured:
                with access.maintenance():
                    pytest.fail("shared lock upgraded")
            assert captured.value.code == "backup_restore_busy"
    with access.maintenance():
        with access.operation():
            pass


def test_two_normal_threads_can_overlap_but_other_workspace_stays_independent(tmp_path):
    access = workspace_access(tmp_path / "one")
    other = workspace_access(tmp_path / "two")

    def attempt():
        with access.operation():
            with other.maintenance():
                return True

    with access.operation(), ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(attempt).result(timeout=5) is True


def test_process_exit_releases_lock_but_incomplete_restore_blocks_new_process(tmp_path):
    crashed = child_attempt(tmp_path, "maintenance", crash=True)
    assert crashed.returncode == 7, crashed.stderr
    # The OS lock was released, but the safety marker forbids auto-resuming.
    blocked = child_attempt(tmp_path, "operation")
    assert blocked.returncode == 0, blocked.stderr
    assert json.loads(blocked.stdout) == {"acquired": False, "code": "writing_recovery_required"}
    assert workspace_access(tmp_path).recovery_marker.is_file()
