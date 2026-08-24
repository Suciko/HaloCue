import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from halocue_writing.app import make_handler
from halocue_writing.errors import DomainError, RevisionConflict
from halocue_writing.service import WritingService


def create_ready_scene(service: WritingService):
    work = service.create_work({"title": "场景素材引用测试"})
    card = service.save_character_card(
        work["id"],
        {
            "expected_version": work["version"],
            "name": "爱丽丝",
            "source_type": "custom",
            "trust_status": "confirmed",
            "source_refs": ["用户确认"],
            "voice_anchors": ["先确认眼前的情况。"],
            "ooc_constraints": ["不替别人猜测动机"],
        },
    )
    brief = service.save_brief(
        work["id"],
        {
            "expected_version": card["work"]["version"],
            "idea": "爱丽丝在深夜的温室发现一盏没有登记的灯。",
            "mode": "bond_short",
            "characters": ["爱丽丝"],
        },
    )
    blueprint = service.generate_blueprint(
        work["id"], {"expected_version": brief["work"]["version"]}
    )
    chapter = service.create_chapter(
        work["id"], {"expected_version": blueprint["work"]["version"], "title": "温室夜巡"}
    )
    scene = service.create_scene(
        work["id"],
        chapter["chapter_id"],
        {
            "expected_version": chapter["work"]["version"],
            "title": "夜间门禁",
            "location": "温室入口",
            "goal": "确认灯光出现的原因",
        },
    )
    return work["id"], scene["scene_id"], scene["work"]


def scene_asset_reference(asset_kind="background", source_asset_id="BG_Greenhouse"):
    return {
        "asset_kind": asset_kind,
        "source_type": "resource_index",
        "source_asset_id": source_asset_id,
        "display_name": "温室入口背景" if asset_kind == "background" else "爱丽丝角色",
        "source_version": "aa-resource-index/2026-08-18",
        "content_hash": "aa-hash-121522699",
        "content_hash_kind": "aa_resource_hash",
        "source_snapshot": {
            "key": source_asset_id,
            "name": "温室入口背景" if asset_kind == "background" else "爱丽丝角色",
            "source": "resource_index",
        },
    }


def request_json(url: str, body: dict):
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_scene_asset_references_are_persisted_in_context_without_editing_manuscript(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_ready_scene(service)
    result = service.set_scene_asset_references(
        work_id,
        scene_id,
        {"expected_version": work["version"], "references": [scene_asset_reference()]},
    )

    assert result["changed"] is True
    assert result["invalidated_proposal_ids"] == []
    scene = result["work"]["chapters"][-1]["scenes"][0]
    assert scene["current_revision_id"] is None
    assert scene["asset_references"][0]["source_asset_id"] == "BG_Greenhouse"
    assert scene["asset_references"][0]["content_hash_kind"] == "aa_resource_hash"
    assert scene["asset_references"][0]["production_copy"] is None

    context = service.assemble_context(work_id, scene_id)
    assert context["scene_asset_references"] == scene["asset_references"]
    assert context["scene_asset_reference_digest"]
    assert context["scene_writing_pack"]["scene_asset_references"] == scene["asset_references"]
    assert context["scene_writing_pack"]["scene_asset_reference_digest"] == context["scene_asset_reference_digest"]

    with service.repo.connect() as connection:
        conversation_context = service._scene_conversation_context(
            connection,
            work_id,
            {"task_scope": {"surface": "scene", "scene_id": scene_id}},
        )
    assert conversation_context["scene_asset_references"] == scene["asset_references"]

    restored = WritingService(tmp_path).get_work(work_id)
    restored_scene = restored["chapters"][-1]["scenes"][0]
    assert restored_scene["asset_references"] == scene["asset_references"]
    assert restored_scene["current_revision_id"] is None


def test_scene_asset_suggestions_are_read_only_and_explicitly_local_rules(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_ready_scene(service)

    result = service.suggest_scene_assets(work_id, scene_id)

    assert result["schema_version"] == "scene-asset-suggestions/1.0"
    assert result["source"] == "local-rules"
    assert result["provider"] == "fake / local-rules"
    assert result["can_call_model"] is False
    assert result["existing_references"] == []
    assert result["suggestions"][0] == {
        "asset_kind": "background",
        "label": "本场背景",
        "query": "温室入口",
        "reason": "场景地点为“温室入口”。",
    }
    assert {item["asset_kind"] for item in result["suggestions"]} == {"background", "sound"}
    assert service.get_work(work_id)["version"] == work["version"]

    selected = service.set_scene_asset_references(
        work_id,
        scene_id,
        {"expected_version": work["version"], "references": [scene_asset_reference()]},
    )
    after_selection = service.suggest_scene_assets(work_id, scene_id)
    assert "background" not in {item["asset_kind"] for item in after_selection["suggestions"]}
    assert after_selection["existing_references"][0]["production_copy"] is None
    assert selected["work"]["chapters"][-1]["scenes"][0]["current_revision_id"] is None


def test_scene_asset_reference_write_uses_work_version_and_validates_slots(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_ready_scene(service)
    first = service.set_scene_asset_references(
        work_id,
        scene_id,
        {"expected_version": work["version"], "references": [scene_asset_reference()]},
    )

    with pytest.raises(RevisionConflict):
        service.set_scene_asset_references(
            work_id,
            scene_id,
            {"expected_version": work["version"], "references": []},
        )

    with pytest.raises(DomainError) as duplicate:
        service.set_scene_asset_references(
            work_id,
            scene_id,
            {
                "expected_version": first["work"]["version"],
                "references": [scene_asset_reference(), scene_asset_reference("background", "BG_Second")],
            },
        )
    assert getattr(duplicate.value, "code", "") == "validation_error"


def test_custom_asset_reference_rejects_background_cg_type_mixup(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_ready_scene(service)
    mismatched = scene_asset_reference()
    mismatched.update(
        {
            "source_type": "custom_library",
            "source_asset_id": "library-asset-0123456789ab",
            "display_name": "自定义插图",
            "source_version": "2",
            "content_hash": "sha256:custom",
            "content_hash_kind": "file_sha256",
            "source_snapshot": {
                "source": "custom_library",
                "asset_id": "library-asset-0123456789ab",
                "kind": "cg",
                "metadata_version": 2,
                "sha256": "sha256:custom",
            },
        }
    )
    with pytest.raises(DomainError) as error:
        service.set_scene_asset_references(
            work_id,
            scene_id,
            {"expected_version": work["version"], "references": [mismatched]},
        )
    assert getattr(error.value, "code", "") == "validation_error"
    assert service.get_work(work_id)["version"] == work["version"]


def test_writing_catalog_reference_rejects_background_cg_type_mixup(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_ready_scene(service)
    mismatched = scene_asset_reference()
    mismatched["source_snapshot"] = {
        "source": "writing_catalog",
        "kind": "cg",
        "key": mismatched["source_asset_id"],
        "name": "剧情特写",
    }

    with pytest.raises(DomainError) as error:
        service.set_scene_asset_references(
            work_id,
            scene_id,
            {"expected_version": work["version"], "references": [mismatched]},
        )

    assert getattr(error.value, "code", "") == "validation_error"
    assert service.get_work(work_id)["version"] == work["version"]


def test_scene_asset_reference_http_contract_returns_refreshed_work(tmp_path):
    service = WritingService(tmp_path / "data")
    work_id, scene_id, work = create_ready_scene(service)
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{server.server_port}/api/v1/works/{work_id}/scenes/{scene_id}/asset-suggestions"
        ) as suggestion_response:
            suggestion_payload = json.loads(suggestion_response.read().decode("utf-8"))
        assert suggestion_payload["data"]["source"] == "local-rules"
        assert suggestion_payload["data"]["can_call_model"] is False

        status, response = request_json(
            f"http://127.0.0.1:{server.server_port}/api/v1/works/{work_id}/scenes/{scene_id}/asset-references",
            {"expected_version": work["version"], "references": [scene_asset_reference()]},
        )
        assert status == 200
        assert response["ok"] is True
        assert response["data"]["work"]["version"] == work["version"] + 1
        scene = response["data"]["work"]["chapters"][-1]["scenes"][0]
        assert scene["asset_references"][0]["source_snapshot"]["key"] == "BG_Greenhouse"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_scene_asset_references_are_frozen_in_script_release_manifest(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_ready_scene(service)
    selected = service.set_scene_asset_references(
        work_id,
        scene_id,
        {"expected_version": work["version"], "references": [scene_asset_reference()]},
    )
    candidate = service.generate_scene_candidate(
        work_id,
        scene_id,
        {"expected_version": selected["work"]["version"]},
    )
    accepted = service.accept_proposal(
        work_id,
        candidate["proposal_id"],
        {"expected_version": candidate["work"]["version"]},
    )
    reviewed = service.review_scene(
        work_id,
        scene_id,
        {"expected_version": accepted["work"]["version"]},
    )
    skipped = service.skip_scene_memory_maintenance(
        work_id,
        scene_id,
        {"expected_version": reviewed["work"]["version"], "note": "本场无新增长期记忆。"},
    )
    continuity = service.review_continuity(
        work_id,
        {"expected_version": skipped["work"]["version"]},
    )
    release_review = service.review_release(
        work_id,
        {"expected_version": continuity["work"]["version"]},
    )
    release = service.freeze_release(
        work_id,
        {"expected_version": release_review["work"]["version"]},
    )

    manifest = service.get_release(release["release_id"])["manifest"]
    frozen = manifest["asset_references"]
    assert frozen[0]["scene_id"] == scene_id
    assert frozen[0]["references"][0]["source_asset_id"] == "BG_Greenhouse"
    assert frozen[0]["references"][0]["content_hash"] == "aa-hash-121522699"
    assert frozen[0]["references"][0]["production_copy"] is None
    assert frozen[0]["digest"].startswith("sha256:")


def test_harness_requires_continuity_review_after_assets_change(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_ready_scene(service)
    candidate = service.generate_scene_candidate(
        work_id,
        scene_id,
        {"expected_version": work["version"]},
    )
    accepted = service.accept_proposal(
        work_id,
        candidate["proposal_id"],
        {"expected_version": candidate["work"]["version"]},
    )
    reviewed = service.review_scene(
        work_id,
        scene_id,
        {"expected_version": accepted["work"]["version"]},
    )
    memory_ready = service.skip_scene_memory_maintenance(
        work_id,
        scene_id,
        {
            "expected_version": reviewed["work"]["version"],
            "note": "连续性 gate 状态测试显式跳过。",
        },
    )
    continuity = service.review_continuity(
        work_id,
        {"expected_version": memory_ready["work"]["version"]},
    )
    selected = service.set_scene_asset_references(
        work_id,
        scene_id,
        {
            "expected_version": continuity["work"]["version"],
            "references": [scene_asset_reference()],
        },
    )
    release_review = service.review_release(
        work_id,
        {"expected_version": selected["work"]["version"]},
    )
    assert release_review["status"] == "passed"

    status = service.get_harness_status(work_id)

    assert status["phase"] == "release_review"
    assert status["primary_action"]["id"] == "continuity.review"


def test_asset_change_after_both_reviews_blocks_release_freeze(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_ready_scene(service)
    candidate = service.generate_scene_candidate(
        work_id,
        scene_id,
        {"expected_version": work["version"]},
    )
    accepted = service.accept_proposal(
        work_id,
        candidate["proposal_id"],
        {"expected_version": candidate["work"]["version"]},
    )
    reviewed = service.review_scene(
        work_id,
        scene_id,
        {"expected_version": accepted["work"]["version"]},
    )
    memory_ready = service.skip_scene_memory_maintenance(
        work_id,
        scene_id,
        {
            "expected_version": reviewed["work"]["version"],
            "note": "素材 Gate 失效测试显式跳过。",
        },
    )
    continuity = service.review_continuity(
        work_id,
        {"expected_version": memory_ready["work"]["version"]},
    )
    release_review = service.review_release(
        work_id,
        {"expected_version": continuity["work"]["version"]},
    )
    assert continuity["status"] == "passed"
    assert release_review["status"] == "passed"

    changed = service.set_scene_asset_references(
        work_id,
        scene_id,
        {
            "expected_version": release_review["work"]["version"],
            "references": [scene_asset_reference()],
        },
    )

    with pytest.raises(DomainError) as error:
        service.freeze_release(
            work_id,
            {"expected_version": changed["work"]["version"]},
        )

    assert error.value.code == "release_blocked"
    assert error.value.details["reason"] == "release_review_not_current"
    status = service.get_harness_status(work_id)
    assert status["primary_action"]["id"] == "continuity.review"

    continuity_after_change = service.review_continuity(
        work_id,
        {"expected_version": changed["work"]["version"]},
    )
    status = service.get_harness_status(work_id)
    assert status["primary_action"]["id"] == "release.review"
    release_review_after_change = service.review_release(
        work_id,
        {"expected_version": continuity_after_change["work"]["version"]},
    )
    release = service.freeze_release(
        work_id,
        {"expected_version": release_review_after_change["work"]["version"]},
    )
    assert release["manifest"]["asset_references"][0]["references"][0]["source_asset_id"] == "BG_Greenhouse"


def test_release_ui_explains_asset_snapshot_drift_and_rechecks_dependencies():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "shell.css").read_text(encoding="utf-8")

    assert "function releaseSceneRevisionRefs()" in script
    assert "asset_references" in script
    assert "素材引用变化" in script
    assert "正式资料依赖发生变化" in script
    assert "release-gate-drift" in script
    assert ".release-gate-drift" in styles


def test_release_ui_shows_freeze_preflight_before_immutable_handoff():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "shell.css").read_text(encoding="utf-8")

    assert "release-freeze-preflight" in script
    assert "冻结前复核" in script
    assert "生成定稿不会修改作品原件" in script
    assert "素材引用" in script
    assert "正式资料" in script
    assert "审查记录" in script
    assert ".release-freeze-preflight" in styles
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in styles


def test_asset_gate_drift_fixture_is_isolated_and_fake_only():
    source = (Path(__file__).resolve().parents[1] / "tests" / "in_app_browser_asset_gate_drift_fixture_server.py").read_text(encoding="utf-8")

    assert "TemporaryDirectory" in source
    assert "review_continuity" in source
    assert "set_scene_asset_references" in source
    assert '"provider": "fake / local-rules"' in source


def _freeze_asset_release(service):
    work_id, scene_id, work = create_ready_scene(service)
    selected = service.set_scene_asset_references(work_id, scene_id, {"expected_version": work["version"], "references": [scene_asset_reference()]})
    candidate = service.generate_scene_candidate(work_id, scene_id, {"expected_version": selected["work"]["version"]})
    accepted = service.accept_proposal(work_id, candidate["proposal_id"], {"expected_version": candidate["work"]["version"]})
    reviewed = service.review_scene(work_id, scene_id, {"expected_version": accepted["work"]["version"]})
    skipped = service.skip_scene_memory_maintenance(work_id, scene_id, {"expected_version": reviewed["work"]["version"], "note": "素材交接测试。"})
    continuity = service.review_continuity(work_id, {"expected_version": skipped["work"]["version"]})
    release_review = service.review_release(work_id, {"expected_version": continuity["work"]["version"]})
    release = service.freeze_release(work_id, {"expected_version": release_review["work"]["version"]})
    return work_id, scene_id, release


class _AssetProductionHandler(BaseHTTPRequestHandler):
    capabilities = []
    usage = None
    posts = []

    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == "/api/v1/capabilities":
            body = {"ok": True, "data": {"schema_version": "production-capabilities/1.0", "capabilities": type(self).capabilities}}
        elif self.path == "/api/v1/production-runs":
            body = {"ok": True, "items": []}
        elif self.path.endswith("/resource-usage"):
            body = type(self).usage or {}
        else:
            self.send_response(404); self.end_headers(); return
        raw = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).posts.append(payload)
        raw = json.dumps({"ok": True, "run_id": "run-assets"}).encode()
        self.send_response(201); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)


def _asset_server(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_asset_handoff_blocks_when_production_does_not_advertise_capability(tmp_path):
    service = WritingService(tmp_path)
    _, _, release = _freeze_asset_release(service)
    _AssetProductionHandler.capabilities = ["script_release_handoff"]
    _AssetProductionHandler.usage = None
    _AssetProductionHandler.posts = []
    server, thread = _asset_server(_AssetProductionHandler)
    service.production_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(DomainError) as error:
            service.handoff_release(release["release_id"])
        assert error.value.code == "production_asset_handoff_unsupported"
        assert service.get_release(release["release_id"])["production_run_id"] is None
        assert _AssetProductionHandler.posts == []
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_asset_handoff_stays_explicitly_blocked_when_production_is_offline(tmp_path, monkeypatch):
    service = WritingService(tmp_path)
    _, _, release = _freeze_asset_release(service)

    calls = []

    def offline(_request, timeout=0):
        calls.append(timeout)
        raise urllib.error.URLError("production service offline")

    monkeypatch.setattr("halocue_writing.service.urllib.request.urlopen", offline)

    with pytest.raises(DomainError) as error:
        service.handoff_release(release["release_id"])

    assert error.value.code == "production_asset_handoff_unavailable"
    assert error.value.status == 503
    assert error.value.details["capability"]["status"] == "offline"
    assert service.get_release(release["release_id"])["production_run_id"] is None
    assert calls


def test_supported_asset_handoff_stays_pending_until_matching_receipt(tmp_path):
    service = WritingService(tmp_path)
    _, scene_id, release = _freeze_asset_release(service)
    _AssetProductionHandler.capabilities = ["scene_asset_handoff"]
    _AssetProductionHandler.usage = {"schema_version": "production-asset-usage/1.0", "production_run_id": "run-assets", "references": []}
    _AssetProductionHandler.posts = []
    server, thread = _asset_server(_AssetProductionHandler)
    service.production_url = f"http://127.0.0.1:{server.server_port}"
    try:
        result = service.handoff_release(release["release_id"])
        assert result["asset_handoff"]["status"] == "pending"
        assert result["asset_handoff"]["expected_count"] == 1
        assert _AssetProductionHandler.posts[0]["asset_handoff"]["references"][0]["scene_id"] == scene_id
        reference = service.get_work(release["work"]["id"])["chapters"][-1]["scenes"][0]["asset_references"][0]
        receipt = {"schema_version": "production-asset-usage/1.0", "production_run_id": "run-assets", "references": [{"scene_id": scene_id, "reference_id": reference["id"], "source_asset_id": reference["source_asset_id"], "source_version": reference["source_version"], "content_hash": reference["content_hash"], "production_copy": {"copy_id": "copy-1", "content_hash": "sha256:" + "1" * 64}}]}
        assert service.reconcile_production_asset_copies(release["release_id"], receipt)["status"] == "complete"
        updated = service.get_work(release["work"]["id"])["chapters"][-1]["scenes"][0]["asset_references"][0]
        assert updated["production_copy"]["copy_id"] == "copy-1"
        assert service.production_asset_status(release["release_id"])["status"] == "complete"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_retrying_an_existing_production_run_reconciles_a_late_asset_receipt(tmp_path):
    service = WritingService(tmp_path)
    _, scene_id, release = _freeze_asset_release(service)
    _AssetProductionHandler.capabilities = ["scene_asset_handoff"]
    _AssetProductionHandler.usage = {
        "schema_version": "production-asset-usage/1.0",
        "production_run_id": "run-assets",
        "references": [],
    }
    _AssetProductionHandler.posts = []
    server, thread = _asset_server(_AssetProductionHandler)
    service.production_url = f"http://127.0.0.1:{server.server_port}"
    try:
        first = service.handoff_release(release["release_id"])
        assert first["asset_handoff"]["status"] == "pending"
        reference = service.get_work(release["work"]["id"])["chapters"][-1]["scenes"][0]["asset_references"][0]
        _AssetProductionHandler.usage = {
            "schema_version": "production-asset-usage/1.0",
            "production_run_id": "run-assets",
            "references": [{
                "scene_id": scene_id,
                "reference_id": reference["id"],
                "source_asset_id": reference["source_asset_id"],
                "source_version": reference["source_version"],
                "content_hash": reference["content_hash"],
                "production_copy": {"copy_id": "copy-late", "content_hash": "sha256:" + "3" * 64},
            }],
        }
        retry = service.handoff_release(release["release_id"])
        assert retry["idempotent"] is True
        assert retry["asset_handoff"]["status"] == "complete"
        assert service.get_work(release["work"]["id"])["chapters"][-1]["scenes"][0]["asset_references"][0]["production_copy"]["copy_id"] == "copy-late"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_asset_receipt_source_mismatch_is_rejected_without_persisting_copy(tmp_path):
    service = WritingService(tmp_path)
    _, scene_id, release = _freeze_asset_release(service)
    with service.repo.transaction() as connection:
        connection.execute("UPDATE script_releases SET production_run_id=? WHERE id=?", ("run-assets", release["release_id"]))
    reference = service.get_work(release["work"]["id"])["chapters"][-1]["scenes"][0]["asset_references"][0]
    receipt = {"schema_version": "production-asset-usage/1.0", "production_run_id": "run-assets", "references": [{"scene_id": scene_id, "reference_id": reference["id"], "source_asset_id": "forged", "source_version": reference["source_version"], "content_hash": reference["content_hash"], "production_copy": {"copy_id": "copy-forged", "content_hash": "sha256:" + "2" * 64}}]}
    with pytest.raises(DomainError) as error:
        service.reconcile_production_asset_copies(release["release_id"], receipt)
    assert error.value.code == "production_asset_usage_mismatch"
    assert service.get_work(release["work"]["id"])["chapters"][-1]["scenes"][0]["asset_references"][0]["production_copy"] is None


def test_asset_status_http_endpoint_is_explicit_about_pending_copy(tmp_path):
    service = WritingService(tmp_path / "data")
    _, _, release = _freeze_asset_release(service)
    _AssetProductionHandler.capabilities = ["scene_asset_handoff"]
    _AssetProductionHandler.usage = {"schema_version": "production-asset-usage/1.0", "production_run_id": "run-assets", "references": []}
    _AssetProductionHandler.posts = []
    production, production_thread = _asset_server(_AssetProductionHandler)
    service.production_url = f"http://127.0.0.1:{production.server_port}"
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/api/v1/releases/{release['release_id']}/production-assets") as response:
            payload = json.loads(response.read().decode())
        assert payload["ok"] is True
        assert payload["data"]["status"] == "not_handed_off"
        assert payload["data"]["capability"]["status"] == "supported"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
        production.shutdown(); production.server_close(); production_thread.join(timeout=2)
