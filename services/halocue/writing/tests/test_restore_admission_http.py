"""Real loopback HTTP admission; requests do not call any external endpoint."""

import base64
import json
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from halocue_writing.app import make_handler
from halocue_writing.backup import WritingBackupManager
from halocue_writing.service import WritingService


def request(base, route, payload=None):
    encoded = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        base + route, data=encoded, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


@pytest.fixture
def server(tmp_path):
    service = WritingService(tmp_path / "writing")
    work = service.create_work({"title": "Snapshot"})
    _, content, summary = service.export_writing_backup()
    payload = {
        "content_base64": base64.b64encode(content).decode(),
        "expected_backup_hash": summary["backup_hash"],
        "replace_all_works": True,
    }
    http = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(service, Path(__file__).resolve().parents[1] / "web")
    )
    # Avoid poller timing in the request/race test; dispatcher tests separately
    # verify claim admission and waking after maintenance.
    service.close()
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield service, f"http://127.0.0.1:{http.server_port}", payload, work
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=5)
        service.close()


def test_http_restore_rejects_parallel_get_post_and_second_restore(server, monkeypatch):
    service, base, payload, work = server
    entered, release = threading.Event(), threading.Event()
    actual_restore = WritingBackupManager.restore

    def blocked_restore(manager, *args):
        entered.set()
        assert release.wait(timeout=10)
        return actual_restore(manager, *args)

    monkeypatch.setattr(WritingBackupManager, "restore", blocked_restore)
    with ThreadPoolExecutor(max_workers=1) as pool:
        restore = pool.submit(request, base, "/api/v1/settings/backups/restore", payload)
        try:
            assert entered.wait(timeout=5)
            for route, body in [
                ("/api/v1/works", {"title": "Rejected"}),
                ("/api/v1/works/" + work["id"], None),
                ("/api/v1/works/" + work["id"] + "/source:preview", {}),
                ("/api/v1/works/" + work["id"] + "/adaptations", {}),
            ]:
                status, result = request(base, route, body)
                assert status == 409 and result["error"]["code"] == "writing_maintenance_busy"
            status, result = request(base, "/api/v1/settings/backups/restore", payload)
            assert status == 409 and result["error"]["code"] == "backup_restore_busy"
            assert service.agent_dispatcher.run_once()["handled"] is False
        finally:
            release.set()
        status, result = restore.result(timeout=10)
        assert status == 200 and result["data"]["restored"] is True
    status, result = request(base, "/api/v1/works", {"title": "After"})
    assert status == 201 and result["data"]["title"] == "After"


def test_http_inflight_request_prevents_restore_before_service_method_is_entered(
    server, monkeypatch
):
    service, base, payload, work = server
    entered, release = threading.Event(), threading.Event()
    original = service.create_work

    def delayed_create(body):
        entered.set()
        assert release.wait(timeout=10)
        return original(body)

    monkeypatch.setattr(service, "create_work", delayed_create)
    with ThreadPoolExecutor(max_workers=1) as pool:
        creation = pool.submit(request, base, "/api/v1/works", {"title": "In flight"})
        try:
            assert entered.wait(timeout=5)
            status, result = request(base, "/api/v1/settings/backups/restore", payload)
            assert status == 409 and result["error"]["code"] == "backup_restore_busy"
        finally:
            release.set()
        assert creation.result(timeout=10)[0] == 201
    assert any(item["title"] == "In flight" for item in service.list_works())
