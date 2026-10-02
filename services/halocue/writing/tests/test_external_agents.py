import json
import base64
import io
import zipfile
import os
import subprocess
import sys
import threading
from copy import deepcopy
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from halocue_writing.app import make_handler
from halocue_writing.errors import DomainError
from halocue_writing.external_agents import RESULT_SCHEMA
from halocue_writing.service import WritingService
from test_scene_conversation_harness import create_ready_scene


ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def exchange(tmp_path, monkeypatch):
    monkeypatch.setenv("HALOCUE_USER_DATA_DIR", str(tmp_path / "user-data"))
    service = WritingService(tmp_path / "writing")
    work_id, scene_id, work = create_ready_scene(service)
    saved = service.save_scene_manuscript(
        work_id,
        scene_id,
        {
            "expected_version": work["version"],
            "base_revision_id": None,
            "blocks": [
                {"id": "block-a", "type": "narration", "text": "窗外下着一场雨。"},
                {"id": "block-b", "type": "dialogue", "speaker": "爱丽丝", "text": "提示灯亮了。"},
            ],
        },
    )
    payload = {
        "work_id": work_id,
        "scene_id": scene_id,
        "expected_version": saved["work"]["version"],
        "instruction": "润色爱丽丝的开场，仅修改第一段。",
        "start": 1,
        "limit": 1,
    }
    yield service, payload, tmp_path
    service.close()


def result_for(package):
    block = package["source"]["blocks"][0]
    return {
        "schema_version": "external-agent-result/1.0",
        "task_id": package["task_id"],
        "input_hash": package["input_hash"],
        "base_revision_id": package["scope"]["base_revision_id"],
        "reason": "保留雨夜气氛，精简开头。",
        "edits": [
            {
                "block_id": block["id"],
                "old_text_sha256": block["text_sha256"],
                "new_text": "窗外细雨未歇。",
            }
        ],
    }


def test_file_round_trip_creates_one_reviewable_proposal_without_formal_write(exchange):
    import jsonschema

    service, payload, _ = exchange
    created = service.external_agents.create(payload)
    package = json.loads(json.dumps(created["package"]))
    contracts = ROOT / "packages/contracts/external-agent-task"
    jsonschema.validate(package, json.loads((contracts / "task-1.0.schema.json").read_text()))
    assert package["result_schema"] == json.loads(
        (contracts / "result-1.0.schema.json").read_text()
    )
    assert [block["id"] for block in package["source"]["blocks"]] == ["block-a"]
    assert package["character_cards"][0]["name"] == "爱丽丝"
    serialized = json.dumps(package)
    assert "source_refs" not in serialized and "token" not in package
    result = result_for(package)
    jsonschema.validate(result, RESULT_SCHEMA)
    submitted = service.external_agents.submit(json.loads(json.dumps(result)))
    duplicate = service.external_agents.submit(result)
    assert duplicate == {"proposal_id": submitted["proposal_id"], "duplicate": True}
    work = service.get_work(payload["work_id"])
    proposal = next(p for p in work["proposals"] if p["id"] == submitted["proposal_id"])
    assert proposal["status"] == "pending" and "窗外细雨未歇。" in proposal["candidate"]
    scene = next(s for c in work["chapters"] for s in c["scenes"] if s["id"] == payload["scene_id"])
    assert scene["current_revision_id"] == result["base_revision_id"]
    assert service.external_agents.status(package["task_id"])["status"] == "submitted"
    decision = service.accept_proposal(
        payload["work_id"],
        submitted["proposal_id"],
        {"expected_version": work["version"], "decision": "accept", "note": "作者明确采纳"},
    )
    assert decision["work"]["version"] > work["version"]


@pytest.mark.parametrize(
    "mutation",
    ["hash", "revision", "outside", "paragraph_hash", "extra", "duplicate", "multiline", "empty"],
)
def test_invalid_or_out_of_scope_result_is_atomic(exchange, mutation):
    service, payload, _ = exchange
    package = service.external_agents.create(payload)["package"]
    result = result_for(package)
    if mutation == "hash":
        result["input_hash"] = "sha256:" + "0" * 64
    if mutation == "revision":
        result["base_revision_id"] = "foreign-revision"
    if mutation == "outside":
        result["edits"][0]["block_id"] = "block-b"
    if mutation == "paragraph_hash":
        result["edits"][0]["old_text_sha256"] = "sha256:" + "0" * 64
    if mutation == "extra":
        result["apply"] = True
    if mutation == "duplicate":
        result["edits"].append(deepcopy(result["edits"][0]))
    if mutation == "multiline":
        result["edits"][0]["new_text"] = "第一段\n第二段"
    if mutation == "empty":
        result["edits"] = []
    before = service.get_work(payload["work_id"])
    with pytest.raises(DomainError):
        service.external_agents.submit(result)
    assert service.get_work(payload["work_id"])["version"] == before["version"]
    assert service.external_agents.status(package["task_id"])["status"] == "open"


def test_changed_revision_and_pending_proposal_reject_late_results(exchange):
    service, payload, _ = exchange
    first = service.external_agents.create(payload)["package"]
    second = service.external_agents.create(payload)["package"]
    service.external_agents.submit(result_for(first))
    with pytest.raises(DomainError, match="待决定"):
        service.external_agents.submit(result_for(second))


def test_saved_new_revision_rejects_result(exchange):
    service, payload, _ = exchange
    package = service.external_agents.create(payload)["package"]
    service.save_scene_manuscript(
        payload["work_id"],
        payload["scene_id"],
        {
            "expected_version": payload["expected_version"],
            "expected_base_revision_id": package["scope"]["base_revision_id"],
            "blocks": [{"id": "block-a", "type": "narration", "text": "作者已经改写开头。"}],
        },
    )
    with pytest.raises(DomainError, match="版本已变化"):
        service.external_agents.submit(result_for(package))


def test_revoke_expiry_and_scoped_connection(exchange):
    service, payload, root = exchange
    package = service.external_agents.create(payload)["package"]
    connection_file = (
        root / "user-data/integrated/external-agent-connections" / (package["task_id"] + ".json")
    )
    token = json.loads(connection_file.read_text())["token"]
    service.external_agents.authorize(package["task_id"], token)
    with pytest.raises(DomainError):
        service.external_agents.authorize(package["task_id"], "wrong")
    service.external_agents.revoke(package["task_id"])
    with pytest.raises(DomainError):
        service.external_agents.authorize(package["task_id"], token)
    with pytest.raises(DomainError):
        service.external_agents.submit(result_for(package))
    other = service.external_agents.create(payload)["package"]
    with service.repo.transaction() as db:
        db.execute(
            "UPDATE external_agent_tasks SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
            (other["task_id"],),
        )
    with pytest.raises(DomainError):
        service.external_agents.package(other["task_id"])
    assert service.external_agents.status(other["task_id"])["status"] == "expired"


def test_failed_connection_write_does_not_leave_a_created_task(exchange, monkeypatch):
    service, payload, _ = exchange

    def fail_write(*args):
        raise DomainError(
            "external_connection_write_failed", "synthetic unavailable directory", status=503
        )

    monkeypatch.setattr(service.external_agents, "_save_connection", fail_write)
    with pytest.raises(DomainError):
        service.external_agents.create(payload)
    assert service.external_agents.list_tasks(payload["work_id"], payload["scene_id"]) == []


def test_task_survives_service_restart(exchange):
    service, payload, root = exchange
    created = service.external_agents.create(payload)
    restarted = WritingService(root / "writing")
    try:
        assert restarted.external_agents.package(created["task"]["id"]) == created["package"]
    finally:
        restarted.close()


@pytest.mark.parametrize("old_backup", [False, True])
def test_backup_restores_task_history_without_connection_secrets(exchange, old_backup):
    service, payload, root = exchange
    package = service.external_agents.create(payload)["package"]
    connection = (
        root / "user-data/integrated/external-agent-connections" / (package["task_id"] + ".json")
    )
    token = json.loads(connection.read_text())["token"]
    if old_backup:
        with service.repo.transaction() as db:
            db.execute("DROP TABLE external_agent_tasks")
    _, content, summary = service.export_writing_backup()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert all("external-agent-connections" not in name for name in archive.namelist())
        assert all(token.encode() not in archive.read(name) for name in archive.namelist())
    restored = WritingService(root / "restored")
    try:
        restored.restore_writing_backup(
            {
                "content_base64": base64.b64encode(content).decode(),
                "expected_backup_hash": summary["backup_hash"],
                "replace_all_works": True,
            }
        )
        tasks = restored.external_agents.list_tasks(payload["work_id"], payload["scene_id"])
        assert len(tasks) == (0 if old_backup else 1)
        if not old_backup:
            assert restored.external_agents.package(package["task_id"]) == package
            assert restored.external_agents.submit(result_for(package))["proposal_id"]
    finally:
        restored.close()


def test_mcp_bridge_auth_and_scope_over_http(exchange):
    service, payload, root = exchange
    package = service.external_agents.create(payload)["package"]
    config_path = (
        root / "user-data/integrated/external-agent-connections" / (package["task_id"] + ".json")
    )
    config = json.loads(config_path.read_text())
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(service, ROOT / "services/halocue/writing/web")
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        bridge = base + "/api/v1/external-agent/bridge/" + package["task_id"]
        with pytest.raises(HTTPError) as error:
            urlopen(bridge + "/task")
        assert error.value.code == 403
        req = Request(
            bridge + "/window?offset=0&limit=1",
            headers={"X-HaloCue-External-Token": config["token"]},
        )
        with urlopen(req) as response:
            body = json.load(response)
        assert len(body["data"]["blocks"]) == 1
        mcp_config = service.external_agents.mcp_config(package["task_id"], base)
        assert mcp_config["mcpServers"]["halocue_task"]["env"]["PYTHONUTF8"] == "1"
        assert config["token"] not in json.dumps(mcp_config)
        for endpoint in (
            "https://127.0.0.1:80",
            "http://evil.example:80",
            "http://localhost:80/path",
        ):
            with pytest.raises(DomainError):
                service.external_agents.mcp_config(package["task_id"], endpoint)
        with pytest.raises(HTTPError) as error:
            urlopen(
                Request(
                    base + "/api/v1/external-agent/tasks",
                    data=json.dumps(payload).encode(),
                    headers={"Origin": "https://evil.example", "Content-Type": "application/json"},
                )
            )
        assert error.value.code == 403
        # A real official SDK client initializes and calls the stdio server.
        candidate = (
            ROOT / ".venv-agent" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        sdk_python = os.environ.get("HALOCUE_MCP_TEST_PYTHON") or (
            str(candidate) if candidate.is_file() else sys.executable
        )
        probe = Path(__file__).with_name("external_agent_mcp_probe.py")
        result = subprocess.run(
            [
                sdk_python,
                str(probe),
                str(ROOT / "services/halocue/external_agent_mcp.py"),
                str(config_path),
                base,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
            timeout=40,
        )
        assert result.returncode == 0, (result.stdout or "") + (result.stderr or "")
        assert json.loads(result.stdout)["proposal_created"] is True
        assert service.external_agents.status(package["task_id"])["status"] == "submitted"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
