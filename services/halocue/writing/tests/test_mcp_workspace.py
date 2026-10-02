import json
import base64
import os
import subprocess
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from halocue_writing.app import make_handler
from halocue_writing.errors import DomainError
from halocue_writing.service import WritingService
from test_external_agents import ROOT, exchange as external_exchange

exchange = external_exchange


def connect(service, work_id):
    state = service.mcp_workspace.connect({"work_ids": [work_id]})
    config = json.loads(service.mcp_workspace._connection_path(state["connection_id"]).read_text())
    return state["connection_id"], config["token"]


def call(service, credentials, tool, **arguments):
    return service.mcp_workspace.call(*credentials, {"tool": tool, "arguments": arguments})


def read_scene(service, credentials, payload, **args):
    return call(service, credentials, "read_scene", scene_id=payload["scene_id"], **args)


def submit(service, credentials, read_id, text="窗外细雨未歇。", paragraph=1):
    return call(
        service,
        credentials,
        "propose_scene_edit",
        read_id=read_id,
        edits=[{"paragraph": paragraph, "text": text}],
    )


def test_direct_agent_workflow_needs_no_task_package_or_version_hash_arguments(exchange):
    service, payload, _ = exchange
    credentials = connect(service, payload["work_id"])
    scenes = call(service, credentials, "find_scenes", query="提示灯")["scenes"]
    assert len(scenes) == 1 and scenes[0]["scene_id"] == payload["scene_id"]
    cards = call(
        service, credentials, "search_materials", scene_id=scenes[0]["scene_id"], query="爱丽丝"
    )
    assert cards["items"]
    window = read_scene(service, credentials, payload, limit=1)
    assert window["paragraphs"] == [
        {"paragraph": 1, "type": "narration", "speaker": None, "text": "窗外下着一场雨。"}
    ]
    assert window["next_start"] == 2
    assert not any(
        key in json.dumps(window)
        for key in ("text_sha256", "base_revision_id", "replace_proposal_id")
    )
    receipt = submit(service, credentials, window["read_id"])
    retry = submit(service, credentials, window["read_id"])
    assert retry["duplicate"] and retry["proposal_id"] == receipt["proposal_id"]
    assert receipt["status"] == "pending" and "窗外细雨未歇。" in "\n".join(receipt["diff"])
    assert receipt["view_path"] == scenes[0]["view_path"]
    work = service.get_work(payload["work_id"])
    scene = work["chapters"][0]["scenes"][0]
    with service.repo.transaction() as db:
        assert db.execute("SELECT count(*) FROM external_agent_tasks").fetchone()[0] == 0
        assert (
            db.execute(
                "SELECT count(*) FROM proposals WHERE kind='scene_script' AND status='pending'"
            ).fetchone()[0]
            == 1
        )
        formal = service._revision_content(db, scene["current_revision_id"])
    assert formal["blocks"][0]["text"] == "窗外下着一场雨。"
    service.accept_proposal(
        payload["work_id"], receipt["proposal_id"], {"expected_version": work["version"]}
    )
    assert submit(service, credentials, window["read_id"])["status"] == "accepted"


def test_connection_scope_revoke_and_no_formal_write_tool(exchange):
    from test_scene_conversation_harness import create_ready_scene

    service, payload, _ = exchange
    credentials = connect(service, payload["work_id"])
    _, foreign_scene, _ = create_ready_scene(service, title="未授权作品")
    assert len(call(service, credentials, "find_scenes")["scenes"]) == 1
    for tool in ("read_scene", "search_materials"):
        with pytest.raises(DomainError):
            call(service, credentials, tool, scene_id=foreign_scene)
    with pytest.raises(DomainError):
        call(service, (credentials[0], "wrong"), "find_scenes")
    for tool in ("accept_proposal", "save_scene_manuscript", "connect", "run_model", "shell"):
        with pytest.raises(DomainError):
            call(service, credentials, tool)
    window = read_scene(service, credentials, payload)
    service.mcp_workspace.disconnect()
    with pytest.raises(DomainError):
        submit(service, credentials, window["read_id"])
    new_credentials = connect(service, payload["work_id"])
    with pytest.raises(DomainError):
        call(service, credentials, "find_scenes")
    with pytest.raises(DomainError):
        submit(service, new_credentials, window["read_id"])
    assert call(service, new_credentials, "find_scenes")["scenes"]


def test_unread_blocks_and_stale_revisions_rejected(exchange):
    service, payload, _ = exchange
    credentials = connect(service, payload["work_id"])
    window = read_scene(service, credentials, payload, limit=1)
    with pytest.raises(DomainError, match="只能修改"):
        submit(service, credentials, window["read_id"], text="另一个提示灯。", paragraph=2)
    scene = service.get_work(payload["work_id"])["chapters"][0]["scenes"][0]
    service.save_scene_manuscript(
        payload["work_id"],
        payload["scene_id"],
        {
            "expected_version": payload["expected_version"],
            "expected_base_revision_id": scene["current_revision_id"],
            "blocks": [{"id": "block-a", "type": "narration", "text": "作者已修改。"}],
        },
    )
    with pytest.raises(DomainError, match="版本已变化"):
        submit(service, credentials, window["read_id"])


def test_pending_candidate_is_read_and_refined_without_candidate_ids(exchange):
    service, payload, _ = exchange
    credentials = connect(service, payload["work_id"])
    original = read_scene(service, credentials, payload)
    first = submit(service, credentials, original["read_id"])
    with pytest.raises(DomainError, match="待决定"):
        submit(service, credentials, original["read_id"], text="旧读取不能覆盖候选。")
    pending = read_scene(service, credentials, payload)
    assert pending["source"] == "pending_candidate"
    assert pending["paragraphs"][0]["text"] == "窗外细雨未歇。"
    second = submit(service, credentials, pending["read_id"], text="窗外雨声渐轻。")
    with pytest.raises(DomainError, match="已变化"):
        submit(service, credentials, pending["read_id"], text="这个读取也已过期。")
    work = service.get_work(payload["work_id"])
    statuses = {p["id"]: p["status"] for p in work["proposals"]}
    assert statuses[first["proposal_id"]] == "superseded"
    assert statuses[second["proposal_id"]] == "pending"
    service.accept_proposal(
        payload["work_id"], second["proposal_id"], {"expected_version": work["version"]}
    )
    current = read_scene(service, credentials, payload)
    assert current["source"] == "saved_manuscript"
    assert [p["text"] for p in current["paragraphs"]] == ["窗外雨声渐轻。", "提示灯亮了。"]


@pytest.mark.parametrize(
    "edits",
    [
        [],
        [{"paragraph": True, "text": "无效。"}],
        [{"paragraph": 1, "text": []}],
        [{"paragraph": 1, "text": "第一段\n第二段"}],
        [{"paragraph": 1, "text": "修改。", "apply": True}],
        [{"paragraph": 1, "text": "修改。"}] * 2,
    ],
)
def test_bad_edits_fail_atomically(exchange, edits):
    service, payload, _ = exchange
    credentials = connect(service, payload["work_id"])
    window = read_scene(service, credentials, payload)
    with pytest.raises(DomainError):
        call(service, credentials, "propose_scene_edit", read_id=window["read_id"], edits=edits)
    assert service.get_work(payload["work_id"])["version"] == payload["expected_version"]


def test_official_mcp_host_operates_workspace_directly(exchange):
    service, payload, _ = exchange
    credentials = connect(service, payload["work_id"])
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(service, ROOT / "services/halocue/writing/web")
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(HTTPError) as error:
            urlopen(
                Request(
                    endpoint + "/api/v1/mcp/bridge/" + credentials[0] + "/call",
                    data=b'{"tool":"find_scenes","arguments":{}}',
                    headers={"Content-Type": "application/json"},
                )
            )
        assert error.value.code == 403
        config = service.mcp_workspace.config(endpoint)["mcpServers"]["halocue"]
        assert credentials[1] not in json.dumps(config)
        with pytest.raises(HTTPError) as error:
            urlopen(
                Request(
                    endpoint + "/api/v1/mcp/disconnect",
                    data=b"{}",
                    headers={"Origin": "https://evil.example", "Content-Type": "application/json"},
                )
            )
        assert error.value.code == 403
        probe = Path(__file__).with_name("workspace_mcp_probe.py")
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [config["command"], str(probe), json.dumps(config)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=40,
        )
        assert result.returncode == 0, (result.stdout or "") + (result.stderr or "")
        assert json.loads(result.stdout)["direct_workflow"]
        with service.repo.transaction() as db:
            assert db.execute("SELECT count(*) FROM external_agent_tasks").fetchone()[0] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_connection_survives_restart_but_backup_cannot_resurrect_it(exchange):
    import jsonschema

    service, payload, root = exchange
    credentials = connect(service, payload["work_id"])
    schema = json.loads(
        (ROOT / "packages/contracts/mcp-workspace-connection/1.0.schema.json").read_text()
    )
    jsonschema.validate(service.mcp_workspace.status(), schema)
    restarted = WritingService(root / "writing")
    try:
        assert call(restarted, credentials, "find_scenes")["scenes"]
    finally:
        restarted.close()
    # Saving fixture material queues knowledge discovery. Restoration must keep
    # the normal admission rule, so cancel those jobs before testing revocation.
    with service.repo.transaction() as db:
        jobs = db.execute(
            "SELECT id FROM agent_dispatch_jobs WHERE status IN ('ready', 'running')"
        ).fetchall()
    for job in jobs:
        service.repo.cancel_agent_work(job_id=job["id"])
    _, content, summary = service.export_writing_backup()
    service.mcp_workspace.disconnect()
    service.restore_writing_backup(
        {
            "content_base64": base64.b64encode(content).decode(),
            "expected_backup_hash": summary["backup_hash"],
            "replace_all_works": True,
        }
    )
    assert not service.mcp_workspace.status()["connected"]
    with pytest.raises(DomainError):
        call(service, credentials, "find_scenes")


@pytest.mark.parametrize(
    "arguments",
    [
        {"scene_id": []},
        {"scene_id": None},
        {"scene_id": "foreign"},
        {"scene_id": "foreign", "work_id": "injected"},
    ],
)
def test_invalid_and_foreign_scope_arguments_rejected(exchange, arguments):
    service, payload, _ = exchange
    credentials = connect(service, payload["work_id"])
    with pytest.raises(DomainError):
        call(service, credentials, "read_scene", **arguments)


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("find_scenes", {"query": None}),
        ("find_scenes", {"offset": -1}),
        ("find_scenes", {"query": "x" * 501}),
        ("search_materials", {"kind": []}),
        ("search_materials", {"query": []}),
        ("read_scene", {"limit": 41}),
        ("read_scene", {"start": 0}),
    ],
)
def test_http_boundary_validates_arguments_without_sdk(exchange, tool, arguments):
    service, payload, _ = exchange
    credentials = connect(service, payload["work_id"])
    if tool != "find_scenes":
        arguments = {"scene_id": payload["scene_id"], **arguments}
    with pytest.raises(DomainError):
        call(service, credentials, tool, **arguments)
