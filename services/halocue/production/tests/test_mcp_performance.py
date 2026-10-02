import base64
import json
import os
import subprocess
import sys
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "services/halocue/writing/src"))

from halocue_production.errors import ProductionError  # noqa: E402
from halocue_production.mcp_workspace import FILES, JOURNAL  # noqa: E402
from halocue_production.service import ProductionService  # noqa: E402
from halocue_writing.app import make_handler  # noqa: E402
from halocue_writing.errors import DomainError  # noqa: E402
from halocue_writing.service import WritingService  # noqa: E402


@pytest.fixture
def workspace(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("HALOCUE_USER_DATA_DIR", str(tmp_path / "user-data"))
    index = tmp_path / "synthetic-resources.json"
    index.write_text(
        json.dumps(
            {
                "bg": {"BG_Black": 1, "BG_Classroom": 2},
                "sounds": ["SE_Confirm"],
                "characters": [
                    {
                        "identifier": "alice",
                        "name": "爱丽丝",
                        "spine": "synthetic/alice",
                        "faces": [{"id": "00"}, {"id": "01", "semantic_cn": "认真"}],
                    }
                ],
                "enums": {"emoticon": {}, "action": {}},
            }
        ),
        encoding="utf-8",
    )
    production = ProductionService(replace(settings, resource_index=index))
    writing = WritingService(tmp_path / "writing")
    writing.mcp_workspace.production = production.mcp_workspace
    created = production.create_run(
        {
            "project": "AA 合成测试",
            "source": {
                "kind": "inline",
                "text": "# 测试\n## 教室\n爱丽丝: 提示灯亮了。\n爱丽丝: 先确认眼前的情况。\n",
            },
        }
    )
    run_id = created["run"]["run_id"]
    production.update_cast(
        run_id,
        {
            "speaker": "爱丽丝",
            "mapping": {"kind": "portrait", "id": "alice"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    grant = writing.mcp_workspace.connect({"run_ids": [run_id]})
    credentials = json.loads(
        writing.mcp_workspace._connection_path(grant["connection_id"]).read_text()
    )
    yield writing, production, run_id, credentials
    writing.close()
    production.jobs.close()


def call(workspace, tool, **args):
    writing, _, _, credentials = workspace
    return writing.mcp_workspace.call(
        credentials["connection_id"], credentials["token"], {"tool": tool, "arguments": args}
    )


def read(workspace, **args):
    return call(workspace, "read_production", run_id=workspace[2], **args)


def line_number(window):
    return next(c["card"] for c in window["cards"] if c["kind"] == "line")


def propose(workspace, window, edits=None):
    return call(
        workspace,
        "propose_performance_edit",
        read_id=window["read_id"],
        edits=edits
        or [
            {"card": line_number(window), "operation": "update", "fields": {"face": "01"}},
            {
                "card": line_number(window),
                "operation": "insert_after",
                "fields": {"cmd": "wait", "arg": "500"},
            },
        ],
    )


def decide(workspace, proposal, action="approve"):
    _, production, run_id, _ = workspace
    version = production.run_detail(run_id)["draft"]["draft_version"]
    return production.decide_direction_proposal(
        run_id, proposal["proposal_id"], {"action": action, "expected_draft_version": version}
    )


def test_aa_batch_requires_author_decision_preserves_frozen_prose_and_previews(workspace):
    writing, production, run_id, _ = workspace
    state = writing.mcp_workspace.status()
    assert state["allowed_work_ids"] == [] and state["allowed_run_ids"] == [run_id]
    assert call(workspace, "find_productions", query="AA")["productions"][0]["run_id"] == run_id
    before = production.run_detail(run_id)
    token = before["run"]["draft_token"]
    root = production.adapter.store.get_draft_path(token)
    frozen = (root / "source.txt").read_bytes()
    window = read(workspace)
    assert "version" not in window and "card_id" not in json.dumps(window)
    resources = call(workspace, "search_production_resources", run_id=run_id, kind="characters")
    assert resources["items"][0]["key"] == "alice"
    face = call(
        workspace,
        "search_production_resources",
        run_id=run_id,
        kind="character_details",
        character="alice",
    )
    assert face["character"]["faces"][1]["id"] == "01"
    proposal = propose(workspace, window)
    assert proposal["state"] == "pending" and not proposal["duplicate"]
    assert production.run_detail(run_id)["draft"] == before["draft"]
    assert propose(workspace, window)["duplicate"]
    after = decide(workspace, proposal)
    lines = [c for c in after["draft"]["cards"] if c["kind"] == "line"]
    old = [c for c in before["draft"]["cards"] if c["kind"] == "line"]
    assert [c["current"]["text"] for c in lines] == [c["current"]["text"] for c in old]
    assert [c["card_id"] for c in lines] == [c["card_id"] for c in old]
    assert lines[0]["current"]["face"] == "01"
    assert lines[1]["current"] == old[1]["current"]
    assert (root / "source.txt").read_bytes() == frozen
    assert any(f.get("title") == "@wait" for f in production.performance_preview(run_id)["frames"])
    assert propose(workspace, window)["state"] == "approved"
    assert decide(workspace, proposal)["draft"]["draft_version"] == after["draft"]["draft_version"]
    assert after["run"]["last_build_id"] is None
    assert not (root / JOURNAL).exists()


def test_foreign_run_read_scope_and_revocation(workspace):
    writing, production, _, _ = workspace
    foreign = production.create_run(
        {"project": "未授权", "source": {"kind": "inline", "text": "旁白: 合成。\n"}}
    )["run"]["run_id"]
    assert len(call(workspace, "find_productions")["productions"]) == 1
    with pytest.raises(DomainError, match="没有授权"):
        call(workspace, "read_production", run_id=foreign)
    window = read(workspace)
    writing.mcp_workspace.disconnect()
    with pytest.raises(DomainError) as error:
        propose(workspace, window)
    assert error.value.status == 403


@pytest.mark.parametrize(
    "fields,operation",
    [
        ({"text": "改写原文"}, "update"),
        ({"who": "另一个角色"}, "update"),
        ({"face": "99"}, "update"),
        ({"face": "01\n@raw bad"}, "update"),
        ({"cmd": "raw", "arg": "bad"}, "insert_after"),
        ({"cmd": "bg", "arg": "invented"}, "insert_after"),
        ({"cmd": "se", "arg": "invented"}, "insert_after"),
        ({"cmd": "wait", "arg": "abc"}, "insert_after"),
        ({"cmd": "move", "arg": "爱丽丝 8"}, "insert_after"),
    ],
)
def test_performance_rejects_prose_raw_injection_invalid_choices(workspace, fields, operation):
    window = read(workspace)
    with pytest.raises(DomainError):
        propose(
            workspace,
            window,
            [{"card": line_number(window), "operation": operation, "fields": fields}],
        )


def test_unread_stale_and_other_connection_snapshots(workspace):
    writing, production, run_id, _ = workspace
    window = read(workspace, query="提示灯", limit=1)
    assert window["cards"][0]["card"] > 1
    with pytest.raises(DomainError) as error:
        propose(
            workspace,
            window,
            [{"card": line_number(window) + 1, "operation": "update", "fields": {"face": "01"}}],
        )
    assert error.value.code == "mcp_unread_card"
    production.update_card(
        run_id,
        production.run_detail(run_id)["draft"]["cards"][-1]["card_id"],
        {
            "patch": {"text": "作者手动修改。"},
            "expected_draft_version": production.run_detail(run_id)["draft"]["draft_version"],
        },
    )
    with pytest.raises(DomainError) as error:
        propose(workspace, window)
    assert error.value.code == "mcp_read_stale"
    fresh = read(workspace)
    grant = writing.mcp_workspace.connect({"run_ids": [run_id]})
    workspace[3].update(
        json.loads(writing.mcp_workspace._connection_path(grant["connection_id"]).read_text())
    )
    with pytest.raises(DomainError) as error:
        propose(workspace, fresh)
    assert error.value.code == "mcp_access_denied"


def test_reject_and_stale_accept_do_not_write(workspace):
    _, production, run_id, _ = workspace
    before = production.run_detail(run_id)["draft"]
    proposal = propose(workspace, read(workspace))
    decide(workspace, proposal, "reject")
    assert production.run_detail(run_id)["draft"] == before
    assert propose(workspace, read(workspace))["state"] == "pending"
    stale = production.run_detail(run_id)["external_agent_proposals"][-1]
    production.approve_review(
        run_id, {"scope": "all", "expected_draft_version": before["draft_version"]}
    )
    with pytest.raises(ProductionError) as error:
        decide(workspace, stale)
    assert error.value.code == "proposal_stale"
    assert decide(workspace, stale, "reject")


def test_batch_rolls_back_if_second_edit_fails(workspace, monkeypatch):
    _, production, run_id, _ = workspace
    proposal = propose(workspace, read(workspace))
    root = production.adapter.store.get_draft_path(
        production.run_detail(run_id)["run"]["draft_token"]
    )
    before = {name: (root / name).read_bytes() for name in FILES}

    def fail(**_):
        raise OSError("synthetic write failure")

    monkeypatch.setattr(production.adapter, "insert_card", fail)
    with pytest.raises(OSError):
        decide(workspace, proposal)
    assert {name: (root / name).read_bytes() for name in FILES} == before
    assert not (root / JOURNAL).exists()


def test_restart_recovers_interrupted_accept_and_keeps_receipts(workspace):
    _, production, run_id, _ = workspace
    window = read(workspace)
    proposal = propose(workspace, window)
    root = production.adapter.store.get_draft_path(
        production.run_detail(run_id)["run"]["draft_token"]
    )
    images = {name: base64.b64encode((root / name).read_bytes()).decode() for name in FILES}
    (root / JOURNAL).write_text(json.dumps(images))
    (root / "edited.txt").write_text("interrupted partial write")
    restarted = ProductionService(production.settings)
    try:
        assert restarted.run_detail(run_id)["external_agent_proposals"][0]["state"] == "pending"
        assert not (root / JOURNAL).exists()
        production.mcp_workspace = restarted.mcp_workspace
        workspace[0].mcp_workspace.production = restarted.mcp_workspace
        assert propose(workspace, window)["proposal_id"] == proposal["proposal_id"]
    finally:
        restarted.jobs.close()


def test_official_sdk_can_operate_aa_over_authenticated_http(workspace):
    writing, _, run_id, _ = workspace
    runtime = ROOT / ".venv-agent/Scripts/python.exe"
    if not runtime.exists():
        pytest.skip("optional MCP runtime absent")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(writing, ROOT / "services/halocue/writing/web")
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = writing.mcp_workspace.config(f"http://127.0.0.1:{server.server_port}")[
            "mcpServers"
        ]["halocue"]
        result = subprocess.run(
            [
                str(runtime),
                str(Path(__file__).with_name("aa_mcp_probe.py")),
                json.dumps(config),
                run_id,
            ],
            cwd=ROOT,
            env={**os.environ, "PYTHONUTF8": "1"},
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=50,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["aa_workflow"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_contract_roundtrip_and_legacy_grant_migration(workspace):
    import jsonschema

    writing, _, run_id, _ = workspace
    snapshot = writing.mcp_workspace.status()
    schema = json.loads(
        (ROOT / "packages/contracts/mcp-workspace-connection/1.1.schema.json").read_text()
    )
    jsonschema.validate(json.loads(json.dumps(snapshot)), schema)
    proposal = propose(workspace, read(workspace))
    schema = json.loads(
        (ROOT / "packages/contracts/external-performance-proposal/1.0.schema.json").read_text()
    )
    jsonschema.validate(json.loads(json.dumps(proposal)), schema)
    with writing.repo.transaction() as db:
        # Simulate the previous database: AA scope did not exist and is never inferred.
        db.execute("ALTER TABLE mcp_connections DROP COLUMN run_ids_json")
    writing.repo._init_schema()
    migrated = writing.mcp_workspace.status()
    assert migrated["connected"] and migrated["allowed_run_ids"] == []
    with pytest.raises(DomainError):
        call(workspace, "read_production", run_id=run_id)
    legacy = {k: migrated[k] for k in ("connected", "connection_id", "allowed_work_ids", "works")}
    legacy.update(
        schema_version="halocue-mcp-connection/1.0",
        capabilities=["read_materials", "read_scene", "propose_scene_edit"],
    )
    schema = json.loads(
        (ROOT / "packages/contracts/mcp-workspace-connection/1.0.schema.json").read_text()
    )
    jsonschema.validate(json.loads(json.dumps(legacy)), schema)


def test_inserted_directives_keep_order_and_existing_identities(workspace):
    _, production, run_id, _ = workspace
    window = read(workspace)
    anchor = line_number(window)
    proposal = propose(
        workspace,
        window,
        [
            {"card": anchor, "operation": "insert_after", "fields": {"cmd": "wait", "arg": "300"}},
            {"card": anchor, "operation": "insert_after", "fields": {"cmd": "wait", "arg": "600"}},
        ],
    )
    after = decide(workspace, proposal)
    cards = after["draft"]["cards"]
    assert [cards[anchor + i]["current"]["arg"] for i in (0, 1)] == ["300", "600"]
    assert len({c["card_id"] for c in cards}) == len(cards)
    assert production.run_detail(run_id)["draft"]["cards"] == cards


def test_aa_choice_catalog_is_frozen_and_does_not_invoke_model(workspace, monkeypatch):
    _, production, run_id, _ = workspace
    monkeypatch.setattr(
        production.direction_models, "provider", lambda: pytest.fail("MCP invoked a provider")
    )
    result = call(
        workspace, "search_production_resources", run_id=run_id, kind="performance_choices"
    )
    assert "stage" in result["directive_commands"] and "raw" not in result["directive_commands"]
    proposal = propose(workspace, read(workspace))
    decide(workspace, proposal)


def test_accepted_external_performance_compiles_in_isolated_aa_workspace(
    workspace, tmp_path, monkeypatch
):
    import aa_project_assets

    monkeypatch.setattr(aa_project_assets, "is_aa_running", lambda: False)
    _, production, run_id, _ = workspace
    aa_root = tmp_path / "aa-workspace"
    for name in ("projects", "saves", "overrides", "settings"):
        (aa_root / name).mkdir(parents=True)
    production.configure_aa_workspace({"path": str(aa_root)})
    after = decide(workspace, propose(workspace, read(workspace)))
    approved = production.approve_review(
        run_id, {"card_ids": None, "expected_draft_version": after["draft"]["draft_version"]}
    )
    assert approved["draft"]["review_ready"]
    token = approved["run"]["draft_token"]
    build_id = production.adapter.create_compile_snapshot(token, approved["draft"]["draft_version"])
    built = production.adapter.execute_compile(token, build_id)
    assert built["build_id"] == build_id
    assert Path(built["bundle_dir"]).is_relative_to(production.settings.data_dir)
    assert not list((aa_root / "projects").iterdir())


def test_background_and_sound_use_only_frozen_choices(workspace):
    _, production, run_id, _ = workspace
    window = read(workspace)
    root = production.adapter.store.get_draft_path(production._run(run_id).draft_token)
    frozen_resources = (root / "resources.json").read_bytes()
    assert (
        call(workspace, "search_production_resources", run_id=run_id, kind="sounds")["items"][0][
            "key"
        ]
        == "SE_Confirm"
    )
    proposal = propose(
        workspace,
        window,
        [
            {
                "card": line_number(window),
                "operation": "insert_after",
                "fields": {"cmd": "bg", "arg": "BG_Classroom"},
            },
            {
                "card": line_number(window),
                "operation": "insert_after",
                "fields": {"cmd": "se", "arg": "SE_Confirm"},
            },
        ],
    )
    assert (root / "resources.json").read_bytes() == frozen_resources
    after = decide(workspace, proposal)
    directions = [c["current"] for c in after["draft"]["cards"] if c["kind"] == "dir"]
    assert directions == [{"cmd": "bg", "arg": "BG_Classroom"}, {"cmd": "se", "arg": "SE_Confirm"}]
    assert (root / "resources.json").read_bytes() == frozen_resources
    assert production.performance_preview(run_id)["frames"][-1]["background_key"] == "BG_Classroom"


def test_receipt_survives_read_window_eviction(workspace):
    _, production, run_id, _ = workspace
    window = read(workspace)
    proposal = propose(workspace, window)
    root = production.adapter.store.get_draft_path(production._run(run_id).draft_token)
    path = root / "mcp-performance.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["reads"] = {}
    path.write_text(json.dumps(state), encoding="utf-8")
    retry = propose(workspace, window)
    assert retry["duplicate"] and retry["proposal_id"] == proposal["proposal_id"]
