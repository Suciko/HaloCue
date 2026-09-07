"""Upstream release creation is identity-atomic, without serializing unrelated work."""

import hashlib
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

import pytest

from halocue_production.config import Settings
from halocue_production.errors import ProductionError
from halocue_production.service import ProductionService

REPO = Path(__file__).resolve().parents[4]


def payload(release_id="release-000000000001", text="爱丽丝: 合成测试。\n"):
    return {
        "project": "Synthetic handoff",
        "source": {"kind": "inline", "text": text},
        "script_release": {
            "id": release_id,
            "display_version": "v1",
            "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        },
    }


@pytest.mark.parametrize("other_instance", [False, True])
@pytest.mark.parametrize("identity", ["same", "conflict", "different"])
def test_concurrent_handoff_is_identity_atomic(
    tmp_path, monkeypatch, identity, other_instance, isolated_legacy_root
):
    index = tmp_path / "resources.json"
    index.write_text(json.dumps({"bg": {}, "sounds": [], "characters": []}), encoding="utf-8")
    settings = Settings(
        project_root=REPO / "services/halocue/production",
        data_dir=tmp_path / "data",
        legacy_root=isolated_legacy_root,
        resource_index=index,
        aa_data=None,
        port=0,
    )
    service = ProductionService(settings)
    second_service = ProductionService(settings) if other_instance else service
    started, finish = threading.Event(), threading.Event()
    original = service.adapter.create_performance_draft
    calls_lock = threading.Lock()
    calls = 0

    def delayed(**kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
            first = calls == 1
        if first:
            started.set()
            assert finish.wait(10)
        return original(**kwargs)

    monkeypatch.setattr(service.adapter, "create_performance_draft", delayed)
    second_input = payload()
    if identity == "conflict":
        second_input = payload(text="爱丽丝: 不同正文。\n")
    elif identity == "different":
        second_input = payload(release_id="release-000000000002")
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(service.create_run, payload())
            assert started.wait(4)
            second_future = pool.submit(second_service.create_run, second_input)
            try:
                try:
                    second_future.result(timeout=4 if identity == "different" else 0.3)
                except (TimeoutError, ProductionError):
                    if identity == "different":
                        raise
            finally:
                finish.set()
            first_result = first_future.result(timeout=5)
            if identity == "conflict":
                with pytest.raises(ProductionError) as rejected:
                    second_future.result(timeout=5)
                assert rejected.value.code == "script_release_identity_conflict"
                assert len(service.repository.list_runs()) == 1
            else:
                second_result = second_future.result(timeout=5)
                first_id, second_id = first_result["run"]["run_id"], second_result["run"]["run_id"]
                assert (first_id == second_id) is (identity == "same")
                assert len(service.repository.list_runs()) == (1 if identity == "same" else 2)
    finally:
        finish.set()
        service.jobs.close()
        if other_instance:
            second_service.jobs.close()


@pytest.mark.parametrize("crash", [False, True])
def test_handoff_admission_excludes_another_process_and_survives_owner_exit(tmp_path, crash):
    import os
    import subprocess
    from halocue_production.handoff_lock import handoff_lock

    code = """
import sys
from pathlib import Path
from halocue_production.handoff_lock import handoff_lock
with handoff_lock(Path(sys.argv[1]), 'release-000000000001'):
    print('locked', flush=True)
    sys.stdin.readline()
"""
    env = {**os.environ, "PYTHONPATH": str(REPO / "services/halocue/production/src")}
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path)],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    pool = ThreadPoolExecutor(max_workers=1)
    entered = threading.Event()

    def contender():
        entered.set()
        with handoff_lock(tmp_path, "release-000000000001"):
            return "acquired"

    try:
        assert child.stdout.readline().strip() == "locked"
        future = pool.submit(contender)
        assert entered.wait(2)
        with pytest.raises(TimeoutError):
            future.result(timeout=0.2)
        if crash:
            child.terminate()
        else:
            child.stdin.write("\n")
            child.stdin.flush()
        child.communicate(timeout=5)
        assert future.result(timeout=5) == "acquired"
        assert len(list((tmp_path / ".handoff-locks").glob("*.lock"))) == 1
    finally:
        if child.poll() is None:
            child.terminate()
        child.communicate(timeout=5)
        pool.shutdown(wait=True)


def test_failed_local_creation_releases_admission_for_retry(settings, monkeypatch):
    service = ProductionService(settings)
    original = service.adapter.create_performance_draft

    def fail(**kwargs):
        raise OSError("synthetic draft creation failure")

    try:
        monkeypatch.setattr(service.adapter, "create_performance_draft", fail)
        with pytest.raises(OSError):
            service.create_run(payload())
        monkeypatch.setattr(service.adapter, "create_performance_draft", original)
        created = service.create_run(payload())
        assert created["run"]["run_id"]
        assert len(service.repository.list_runs()) == 1
    finally:
        service.jobs.close()


def test_default_service_fixture_does_not_point_at_checkout_asset_data(settings, tmp_path):
    assert settings.legacy_root.is_relative_to(tmp_path)
    assert settings.legacy_root != REPO
