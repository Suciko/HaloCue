import io
import json
import base64
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from halocue_writing.errors import DomainError
from halocue_writing.app import make_handler
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


def request(url, method="GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_production_asset_get_is_proxied_to_configured_service(monkeypatch, tmp_path):
    service = WritingService(tmp_path / "data", production_url="http://production.test")
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    real_urlopen = urllib.request.urlopen
    production_timeouts = []

    class ProductionResponse:
        status = 200
        headers = {"Content-Type": "application/json; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return '{"ok":true,"items":[{"key":"BG_Test","name":"测试背景"}]}'.encode("utf-8")

    def routed_urlopen(target, *args, **kwargs):
        url = target.full_url if isinstance(target, urllib.request.Request) else str(target)
        if url.startswith(base):
            return real_urlopen(target, *args, **kwargs)
        if url.startswith("http://production.test/"):
            production_timeouts.append(kwargs.get("timeout"))
            return ProductionResponse()
        raise AssertionError(f"unexpected HTTP request: {url}")

    monkeypatch.setattr(urllib.request, "urlopen", routed_urlopen)
    try:
        status, payload = request(base + "/production/api/v1/resources/background?limit=1")
        assert status == 200
        assert payload["items"][0]["key"] == "BG_Test"
        assert production_timeouts == [30]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_activate_writing_model_http_is_identity_consistent_and_atomic_on_401(
    monkeypatch, tmp_path
):
    service = WritingService(tmp_path / "data")
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    real_urlopen = urllib.request.urlopen

    class SuccessfulModelResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"pong"},"finish_reason":"stop"}]}'

    def routed_urlopen(target, *args, **kwargs):
        url = target.full_url if isinstance(target, urllib.request.Request) else str(target)
        if url.startswith(base):
            return real_urlopen(target, *args, **kwargs)
        if url.startswith("https://provider.good.example/"):
            return SuccessfulModelResponse()
        if url.startswith("https://provider.bad.example/"):
            raise urllib.error.HTTPError(
                url,
                401,
                "Unauthorized",
                hdrs=None,
                fp=io.BytesIO(b'{"error":{"message":"invalid api key"}}'),
            )
        raise AssertionError(f"unexpected HTTP request: {url}")

    monkeypatch.setattr(urllib.request, "urlopen", routed_urlopen)
    try:
        status, activated = request(
            base + "/api/v1/settings/writing-model:activate",
            "POST",
            {
                "preset_id": "custom",
                "provider": "openai",
                "base_url": "https://provider.good.example/v1",
                "model": "good-model",
                "api_key": "sk-good-secret",
                "reasoning_mode": "balanced",
            },
        )

        assert status == 200
        assert activated["ok"] is True
        assert activated["test"]["ok"] is True
        assert activated["model"]["model"] == "good-model"
        assert activated["runtime"]["model"] == "good-model"
        for field in ("provider", "model", "settings_version", "config_revision", "config_digest"):
            assert activated["runtime"][field] == activated["model"][field]

        active_config = service.writing_model_settings_public()["model"]
        active_secret = service.model_settings.secret.load()
        active_provider = service.provider
        active_runtime = active_provider.descriptor()

        status, rejected = request(
            base + "/api/v1/settings/writing-model:activate",
            "POST",
            {
                "preset_id": "custom",
                "provider": "openai",
                "base_url": "https://provider.bad.example/v1",
                "model": "bad-model",
                "api_key": "sk-bad-secret",
                "reasoning_mode": "strict",
            },
        )

        assert status == 502
        assert rejected["ok"] is False
        assert rejected["error"]["code"] == "connection_test_failed"
        diagnostic = rejected["error"]["details"]["diagnostics"][-1]
        assert diagnostic["status"] == "failed"
        assert diagnostic["code"] == 401
        assert service.writing_model_settings_public()["model"] == active_config
        assert service.model_settings.secret.load() == active_secret == "sk-good-secret"
        assert service.provider is active_provider
        assert service.provider.descriptor() == active_runtime
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_saved_writing_model_can_activate_aa_without_returning_secret_to_browser(
    monkeypatch, tmp_path
):
    received = []

    class ProductionHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            received.append(json.loads(self.rfile.read(length).decode("utf-8")))
            body = json.dumps({
                "ok": True,
                "model": {
                    "configured": True,
                    "model": "synthetic-writer",
                    "activation_status": "active",
                },
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    production = ThreadingHTTPServer(("127.0.0.1", 0), ProductionHandler)
    production_thread = threading.Thread(target=production.serve_forever, daemon=True)
    production_thread.start()
    service = WritingService(
        tmp_path / "data",
        production_url=f"http://127.0.0.1:{production.server_port}",
    )
    secret = "SYNTHETIC-ONLY-SECRET"
    monkeypatch.setattr(service.model_settings, "get_credentials", lambda: {
        "preset_id": "custom",
        "provider": "openai",
        "base_url": "https://provider.synthetic.invalid/v1",
        "model": "synthetic-writer",
        "api_key": secret,
        "api_key_env": "",
        "max_tokens": 4096,
        "timeout": 30,
        "reasoning_mode": "balanced",
        "config_revision": "model-config-2",
        "credential_revision": "synthetic-credential-revision",
        "registered_models": [{"api_key": "must-not-be-forwarded"}],
    })
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, activated = request(
            base + "/api/v1/settings/writing-model:activate-direction",
            "POST",
            {"expected_config_revision": "model-config-2"},
        )
        assert status == 200
        assert activated["ok"] is True
        assert activated["model"]["activation_status"] == "active"
        assert secret not in json.dumps(activated)
        assert len(received) == 1
        assert received[0]["api_key"] == secret
        assert received[0]["model"] == "synthetic-writer"
        assert "credential_revision" not in received[0]
        assert "registered_models" not in received[0]

        status, stale = request(
            base + "/api/v1/settings/writing-model:activate-direction",
            "POST",
            {"expected_config_revision": "model-config-1"},
        )
        assert status == 409
        assert stale["error"]["code"] == "model_settings_changed"
        assert len(received) == 1, "stale browser state must never activate an old profile"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        production.shutdown()
        production.server_close()
        production_thread.join(timeout=2)


def test_http_contract_and_static_workspace(tmp_path):
    service = WritingService(tmp_path / "data")
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(base + "/") as response:
            page = response.read().decode("utf-8")
            assert response.status == 200
            assert "HaloCue 写作工作台" in page
            assert page.count('id="feedbackDialog"') == 1
            assert page.count('id="feedbackForm"') == 1
        status, created = request(base + "/api/v1/works", "POST", {"title": "HTTP 作品"})
        assert status == 201
        assert created["ok"] is True
        work = created["data"]
        status, harness = request(base + f"/api/v1/works/{work['id']}/harness")
        assert status == 200
        assert harness["data"]["schema_version"] == "writing-harness-status/1.0"
        assert harness["data"]["primary_action"]["id"] == "brief.build"
        status, doctor = request(base + f"/api/v1/works/{work['id']}/doctor")
        assert status == 200
        assert doctor["data"]["schema_version"] == "writing-harness-doctor/1.0"
        assert doctor["data"]["ok"] is True
        status, conflict = request(
            base + f"/api/v1/works/{work['id']}/brief",
            "POST",
            {"expected_version": 0, "idea": "过期请求", "mode": "bond_short"},
        )
        assert status == 409
        assert conflict == {
            "ok": False,
            "error": {
                "code": "revision_conflict",
                "message": "内容已在其他位置更新，请刷新后重试。",
                "details": {"expected_version": 0, "actual_version": 1},
            },
        }
        status, bad_search = request(base + "/api/v1/official-references/search?q=x")
        assert status == 400
        assert bad_search["error"]["code"] == "validation_error"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_resource_catalog_and_aap_import_http_contracts_are_explicit_and_read_only(tmp_path):
    service = WritingService(tmp_path / "data")
    static = Path(__file__).resolve().parents[1] / "web"
    legacy = tmp_path / "legacy-095.db"
    with sqlite3.connect(legacy) as connection:
        connection.executescript(
            """
            CREATE TABLE bg (name TEXT PRIMARY KEY, label TEXT, place TEXT, time TEXT, mood TEXT, tags TEXT);
            CREATE TABLE character (ident TEXT PRIMARY KEY, name TEXT, club TEXT, spine TEXT, avatar TEXT, source TEXT);
            CREATE TABLE character_variant (ident TEXT, spine_signature TEXT, outfit_key TEXT, spine TEXT);
            CREATE TABLE face_evidence (ident TEXT, spine_signature TEXT, outfit_key TEXT, face_id TEXT, source TEXT, raw TEXT, label TEXT, label_cn TEXT, observed_count INTEGER);
            CREATE TABLE face_official_usage (ident TEXT, spine_signature TEXT, outfit_key TEXT, face_id TEXT);
            CREATE TABLE face_visual_label (ident TEXT, spine_signature TEXT, outfit_key TEXT, face_id TEXT, primary_emotion TEXT, confidence REAL, reviewed INTEGER, semantic_json TEXT, manual_json TEXT);
            INSERT INTO bg VALUES ('BG_Campus', '校园庭院', '千年校舍', 'day', '明亮', '室外,校园');
            INSERT INTO character VALUES ('alice', '爱丽丝', '游戏开发部', 'alice-spine', 'alice.png', 'legacy');
            INSERT INTO character_variant VALUES ('alice', 'sig', '制服', 'alice-spine');
            INSERT INTO face_evidence VALUES ('alice', 'sig', '制服', '03', 'official', 'smile', 'smile', '微笑', 4);
            INSERT INTO face_official_usage VALUES ('alice', 'sig', '制服', '03');
            INSERT INTO face_visual_label VALUES ('alice', 'sig', '制服', '03', 'joy', .92, 1, '{"tone":"warm"}', '{}');
            """
        )
    overlay = tmp_path / "overlay-095.db"
    with sqlite3.connect(overlay) as connection:
        connection.executescript(
            """
            CREATE TABLE scene_visual_label (resource_channel TEXT, asset_key TEXT, confidence REAL, status TEXT, label_json TEXT, manual_json TEXT);
            INSERT INTO scene_visual_label VALUES ('background', 'BG_Campus', .97, 'ready', '{"label":"千年庭院","weather":"晴朗","search_terms_cn":["中庭"]}', '{}');
            """
        )
    legacy_snapshot = legacy.read_bytes()
    overlay_snapshot = overlay.read_bytes()
    project = {
        "ProjectName": "导入预览工程",
        "nodes": {"$values": [{"$type": "ScriptNodeData, Assembly-CSharp", "NodeName": "场景一", "Scripts": {"$values": [{"text": "旁白", "isDialogScript": False}]}}]},
    }
    aap_bytes = json.dumps(project, ensure_ascii=False).encode("utf-8")
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, imported = request(
            base + "/api/v1/resources/catalog:import",
            "POST",
            {"source_path": str(legacy), "source_label": "测试 0.95", "overlay_paths": [str(overlay)]},
        )
        assert status == 200
        assert imported["data"]["imported"]["backgrounds"] == 1
        status, catalog = request(base + "/api/v1/resources/catalog")
        assert status == 200
        assert catalog["data"]["ready"] is True
        status, searched = request(base + "/api/v1/resources/search?kind=backgrounds&q=%E6%A0%A1%E5%9B%AD")
        assert status == 200
        assert searched["data"]["items"][0]["display_name"] == "千年庭院"
        assert "key" not in searched["data"]["items"][0]
        assert searched["data"]["items"][0]["technical"]["key"] == "BG_Campus"
        status, face_search = request(base + "/api/v1/resources/search?kind=faces&q=%E7%88%B1%E4%B8%BD%E4%B8%9D")
        assert status == 200
        assert face_search["data"]["items"][0]["label"] == "微笑"
        assert face_search["data"]["items"][0]["semantic"]["primary_emotion"] == "joy"
        assert face_search["data"]["items"][0]["evidence"]["official_usage_count"] == 1
        status, override = request(
            base + "/api/v1/resources/overrides",
            "POST",
            {"kind": "background", "resource_key": "BG_Campus", "patch": {"display_name": "我常用的庭院"}, "expected_version": 0},
        )
        assert status == 200
        assert override["data"]["version"] == 1
        status, corrected = request(base + "/api/v1/resources/search?kind=backgrounds&q=%E4%B8%AD%E5%BA%AD")
        assert corrected["data"]["items"][0]["display_name"] == "我常用的庭院"
        assert corrected["data"]["items"][0]["user_corrected"] is True
        assert legacy.read_bytes() == legacy_snapshot
        assert overlay.read_bytes() == overlay_snapshot

        encoded = base64.b64encode(aap_bytes).decode("ascii")
        status, preview = request(base + "/api/v1/imports/aap:preview", "POST", {"filename": "导入预览.aap", "content_base64": encoded})
        assert status == 200
        assert preview["data"]["write_boundary"] == "preview_only_until_user_confirmation"
        status, refused = request(base + "/api/v1/imports/aap:stage", "POST", {"filename": "导入预览.aap", "content_base64": encoded})
        assert status == 409
        assert refused["error"]["code"] == "aap_confirmation_required"
        status, staged = request(base + "/api/v1/imports/aap:stage", "POST", {"filename": "导入预览.aap", "content_base64": encoded, "confirm": True})
        assert status == 201
        assert staged["data"]["status"] == "staged_draft"
        assert staged["data"]["write_boundary"] == "staged_import_only_no_formal_revision"
        status, adopted = request(
            base + "/api/v1/imports/aap:adopt",
            "POST",
            {"import_id": staged["data"]["import_id"], "confirm": True},
        )
        assert status == 201
        assert adopted["data"]["status"] == "adopted"
        assert adopted["data"]["revision_ids"]
        status, replay = request(
            base + "/api/v1/imports/aap:adopt",
            "POST",
            {"import_id": staged["data"]["import_id"], "confirm": True},
        )
        assert status == 201
        assert replay["data"]["idempotent_replay"] is True

        story_bytes = "第一章 走廊\n场景一 午后\n星野：天气真好。".encode("utf-8")
        story_encoded = base64.b64encode(story_bytes).decode("ascii")
        status, story_preview = request(base + "/api/v1/imports/story:preview", "POST", {"filename": "旧稿.txt", "content_base64": story_encoded})
        assert status == 200
        assert story_preview["data"]["counts"]["chapters"] == 1
        status, story_refused = request(base + "/api/v1/imports/story:stage", "POST", {"filename": "旧稿.txt", "content_base64": story_encoded})
        assert status == 409
        assert story_refused["error"]["code"] == "story_import_confirmation_required"
        status, story_staged = request(base + "/api/v1/imports/story:stage", "POST", {"filename": "旧稿.txt", "content_base64": story_encoded, "confirm": True})
        assert status == 201
        assert story_staged["data"]["status"] == "staged_draft"
        assert story_staged["data"]["write_boundary"] == "staged_import_only_no_formal_revision"
        status, story_adopted = request(
            base + "/api/v1/imports/story:adopt",
            "POST",
            {"import_id": story_staged["data"]["import_id"], "confirm": True},
        )
        assert status == 201
        assert story_adopted["data"]["status"] == "adopted"
        assert story_adopted["data"]["work_id"]
        assert not list((tmp_path / "data" / "works").glob("**/*")) if (tmp_path / "data" / "works").exists() else True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_commit_projection_http_contract_runs_pinned_revision(tmp_path):
    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "提交投影 HTTP 验收"})
    created = service.create_scene(
        work["id"],
        work["chapters"][0]["id"],
        {
            "expected_version": work["version"],
            "title": "固定正文",
            "goal": "验证派生数据可恢复",
        },
    )
    saved = service.save_scene_manuscript(
        work["id"],
        created["scene_id"],
        {
            "expected_version": created["work"]["version"],
            "expected_base_revision_id": None,
            "blocks": [
                {
                    "id": "block-projection-http",
                    "type": "action",
                    "speaker": "",
                    "text": "旧终端在口令后亮起。",
                }
            ],
        },
    )
    revision_id = saved["revision_id"]
    # Keep this contract deterministic: the endpoint, rather than the background
    # dispatcher, owns the run in this test.
    with service.repo.transaction() as connection:
        connection.execute(
            """UPDATE agent_dispatch_jobs SET status='cancelled',updated_at=?
               WHERE operation='commit.projection' AND status='ready'""",
            (saved["work"]["updated_at"],),
        )
    service._commit_projection_reconciled = True

    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, pending = request(
            base + f"/api/v1/works/{work['id']}/commit-projections/{revision_id}"
        )
        assert status == 200
        assert pending["data"]["status"] == "pending"

        status, completed = request(
            base + f"/api/v1/works/{work['id']}/commit-projections/{revision_id}:run",
            "POST",
            {},
        )
        assert status == 200
        assert completed["data"]["status"] == "completed"
        assert {item["kind"] for item in completed["data"]["items"]} == {
            "summary",
            "search",
            "memory_followup",
            "review_followup",
        }
        assert all(item["output_ref"] for item in completed["data"]["items"])
        status, searched = request(
            base
            + f"/api/v1/works/{work['id']}/projection-search"
            + "?q="
            + urllib.parse.quote("旧终端")
            + "&kind=scene_script"
        )
        assert status == 200
        assert searched["data"]["schema_version"] == "commit-projection-search/1.0"
        assert searched["data"]["complete"] is True
        assert searched["data"]["results"][0]["source"]["revision_id"] == revision_id
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_continuity_review_http_contract_returns_agent_trace(tmp_path):
    service = WritingService(tmp_path / "data")
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        _, created = request(base + "/api/v1/works", "POST", {"title": "连续性接口验收"})
        work = created["data"]
        status, reviewed = request(
            base + f"/api/v1/works/{work['id']}/continuity:review",
            "POST",
            {"expected_version": work["version"]},
        )
        assert status == 200
        assert reviewed["ok"] is True
        assert reviewed["data"]["status"] == "blocked"
        assert reviewed["data"]["snapshot"]["no_scenes"] is True
        assert reviewed["data"]["agent_run_id"].startswith("agent-")
        assert reviewed["data"]["gate_id"].startswith("gate-")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_long_term_memory_http_routes_persist_proposal_decision_and_lifecycle(tmp_path):
    service = WritingService(tmp_path / "data")
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, created = request(base + "/api/v1/works", "POST", {"title": "记忆 HTTP 验收"})
        assert status == 201
        work = created["data"]
        chapter_id = work["chapters"][0]["id"]
        status, scene_created = request(
            base + f"/api/v1/works/{work['id']}/chapters/{chapter_id}/scenes",
            "POST",
            {"expected_version": work["version"], "title": "记录结果", "goal": "留下可追踪事实"},
        )
        assert status == 200
        scene_id = scene_created["data"]["scene_id"]
        work = scene_created["data"]["work"]
        status, saved = request(
            base + f"/api/v1/works/{work['id']}/scenes/{scene_id}/manuscript",
            "POST",
            {
                "expected_version": work["version"],
                "expected_base_revision_id": None,
                "blocks": [
                    {"id": "block-http", "type": "action", "speaker": "", "text": "终端留下了访问记录。"}
                ],
            },
        )
        assert status == 200
        work = saved["data"]["work"]

        status, generated = request(
            base + f"/api/v1/works/{work['id']}/scenes/{scene_id}/memory-proposals:generate",
            "POST",
            {"expected_version": work["version"]},
        )
        assert status == 200
        assert generated["data"]["simulation"] is True
        proposal_id = generated["data"]["proposal_id"]
        work = generated["data"]["work"]

        status, accepted = request(
            base + f"/api/v1/works/{work['id']}/proposals/{proposal_id}/accept",
            "POST",
            {"expected_version": work["version"]},
        )
        assert status == 200
        memory_id = accepted["data"]["memory_ids"][0]
        work = accepted["data"]["work"]

        status, listed = request(base + f"/api/v1/works/{work['id']}/memories")
        assert status == 200
        memory = next(item for item in listed["data"] if item["id"] == memory_id)
        assert memory["confidence_status"] == "confirmed"
        assert memory["lifecycle_status"] == "active"

        status, archived = request(
            base + f"/api/v1/works/{work['id']}/memories/{memory_id}/archive",
            "POST",
            {"expected_version": work["version"]},
        )
        assert status == 200
        assert archived["data"]["lifecycle_status"] == "archived"
        work = archived["data"]["work"]

        status, restored = request(
            base + f"/api/v1/works/{work['id']}/memories/{memory_id}/restore",
            "POST",
            {"expected_version": work["version"]},
        )
        assert status == 200
        assert restored["data"]["lifecycle_status"] == "active"
        memory = next(item for item in restored["data"]["work"]["memories"] if item["id"] == memory_id)
        assert memory["version"] == 3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_chapter_memory_sweep_http_route_returns_durable_proposal(tmp_path):
    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "章节清扫 HTTP"})
    chapter_id = work["chapters"][0]["id"]
    created = service.create_scene(
        work["id"], chapter_id,
        {"expected_version": work["version"], "title": "固定场景", "goal": "留下章节进展"},
    )
    saved = service.save_scene_manuscript(
        work["id"], created["scene_id"],
        {
            "expected_version": created["work"]["version"],
            "expected_base_revision_id": None,
            "blocks": [{"id": "block-http-sweep", "type": "action", "speaker": "", "text": "终端亮起。"}],
        },
    )
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, swept = request(
            base + f"/api/v1/works/{work['id']}/chapters/{chapter_id}/memory:sweep",
            "POST",
            {"expected_version": saved["work"]["version"]},
        )
        assert status == 200
        assert swept["data"]["simulation"] is True
        assert swept["data"]["proposal_id"].startswith("proposal-")
        assert swept["data"]["work"]["memories"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_invalid_memory_provider_bundle_has_stable_http_failure_and_terminal_state(tmp_path):
    class InvalidMemoryProvider(FakeWritingProvider):
        kind = "invalid-memory-http-test"

        def extract_memory_bundle(self, memory_context: dict) -> dict:
            return {"schema_version": "memory-bundle/1.0", "items": []}

    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "非法记忆输出 HTTP"})
    chapter_id = work["chapters"][0]["id"]
    created = service.create_scene(
        work["id"], chapter_id,
        {"expected_version": work["version"], "title": "稳定失败", "goal": "验证错误合同"},
    )
    saved = service.save_scene_manuscript(
        work["id"], created["scene_id"],
        {
            "expected_version": created["work"]["version"],
            "expected_base_revision_id": None,
            "blocks": [
                {"id": "block-invalid-http", "type": "action", "speaker": "", "text": "正文已经固定。"}
            ],
        },
    )
    service.provider = InvalidMemoryProvider()
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, failed = request(
            base + f"/api/v1/works/{work['id']}/scenes/{created['scene_id']}/memory-proposals:generate",
            "POST",
            {"expected_version": saved["work"]["version"]},
        )
        assert status == 502
        assert failed["ok"] is False
        assert failed["error"]["code"] == "provider_output_invalid"
        assert failed["error"]["details"] == {"field": "items"}

        status, fetched = request(base + f"/api/v1/works/{work['id']}")
        assert status == 200
        restored = fetched["data"]
        assert not [item for item in restored["proposals"] if item["kind"] == "memory_bundle"]
        memory_items = [
            item
            for run in restored["runs"]
            for item in run["work_items"]
            if item["type"] == "memory.extract"
        ]
        assert len(memory_items) == 1
        assert memory_items[0]["status"] == "failed"
        assert memory_items[0]["attempts"][0]["status"] == "failed"
        assert all(run["status"] != "running" for run in restored["runs"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_agent_observability_catalog_and_failed_run_retry_http_contract(tmp_path):
    class HTTPUsageProvider(FakeWritingProvider):
        is_simulation = False
        kind = "http-usage-test"
        display_name = "HTTP usage test provider"

        def last_usage(self):
            return {
                "input_tokens": 80,
                "output_tokens": 20,
                "cache_read_tokens": 40,
                "cache_write_tokens": 5,
                "estimated_cost": 0.0015,
            }

    service = WritingService(tmp_path / "data")
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, catalog_response = request(base + "/api/v1/agent-tools")
        assert status == 200
        catalog = catalog_response["data"]
        assert catalog["schema_version"] == "agent-tools/1.0"
        assert catalog["write_boundary"] == "formal_artifacts_require_proposal_acceptance"
        tools = {item["name"]: item for item in catalog["tools"]}
        assert {"read_work_context", "draft_character_card", "create_knowledge_proposal"} <= set(tools)
        assert tools["read_work_context"]["input_schema"]["type"] == "object"
        assert tools["create_knowledge_proposal"]["requires_user_confirmation"] is True
        assert all({"description", "risk", "allowed_modes", "allowed_scopes"} <= set(item) for item in tools.values())

        status, created = request(base + "/api/v1/works", "POST", {"title": "Agent HTTP", "idea": "检查旧广播。"})
        assert status == 201
        work = created["data"]
        current_thread = work["conversation_threads"][0]

        service.provider = HTTPUsageProvider()
        status, discussed = request(
            base + f"/api/v1/works/{work['id']}/threads/{current_thread['id']}/messages",
            "POST",
            {"expected_thread_version": current_thread["version"], "text": "先核对广播来源。"},
        )
        assert status == 200
        current_thread = discussed["data"]["work"]["conversation_threads"][0]

        status, usage_response = request(base + f"/api/v1/works/{work['id']}/agent-usage")
        assert status == 200
        usage = usage_response["data"]
        assert usage["schema_version"] == "agent-usage/1.0"
        assert usage["input_tokens"] == 80
        assert usage["cache_read_tokens"] == 40
        assert usage["cache_hit_rate"] == 0.5
        assert usage["estimated_cost"] == 0.0015
        assert usage["runs_by_status"]

        def fail_discussion(_messages, _context):
            raise DomainError("writing_provider_failed", "HTTP 模型连接失败。", status=502)

        service.provider.discuss_work = fail_discussion
        status, failed = request(
            base + f"/api/v1/works/{work['id']}/threads/{current_thread['id']}/messages",
            "POST",
            {"expected_thread_version": current_thread["version"], "text": "重试前先记录这轮。"},
        )
        assert status == 502
        assert failed["error"]["code"] == "agent_failed"
        failed_run_id = failed["error"]["details"]["agent_run_id"]

        status, restored_response = request(base + f"/api/v1/works/{work['id']}")
        assert status == 200
        restored = restored_response["data"]
        failed_run = next(item for item in restored["agent_runs"] if item["id"] == failed_run_id)
        assert failed_run["status"] == "failed"
        current_thread = restored["conversation_threads"][0]
        user_count_before_retry = sum(
            message["role"] == "user" for message in current_thread["messages"]
        )

        service.provider = FakeWritingProvider()
        status, retried_response = request(
            base + f"/api/v1/works/{work['id']}/agent-runs/{failed_run_id}:retry",
            "POST",
            {"expected_thread_version": current_thread["version"]},
        )
        assert status == 200
        retried = retried_response["data"]
        assert retried["retried_from_agent_run_id"] == failed_run_id
        assert retried["agent_run_id"] != failed_run_id
        messages = retried["work"]["conversation_threads"][0]["messages"]
        assert sum(message["role"] == "user" for message in messages) == user_count_before_retry
        assert messages[-1]["agent_run_id"] == retried["agent_run_id"]
        retried_run = next(
            item for item in retried["work"]["agent_runs"]
            if item["id"] == retried["agent_run_id"]
        )
        assert retried_run["policy"]["retry_of"] == failed_run_id
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_settings_ui_does_not_claim_unverified_or_partial_success():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")

    assert "已配置 · 待测试" in script
    assert "await requestProduction('/test')" in script
    assert "if(!response.ok||result.ok===false)" in script
    assert "未能确认模型启用成功" in script
    assert "双域已启用" not in script


def test_global_production_entry_is_always_available_and_stays_on_one_line():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "shell.css").read_text(encoding="utf-8")

    assert "production.classList.toggle('locked-nav'" not in script
    assert 'production.setAttribute(\'aria-disabled\'' not in script
    assert ".primary-nav .nav-item > span:last-child" in styles
    assert "white-space: nowrap;" in styles


def test_agent_ui_uses_persisted_runs_for_auditable_status_and_retry():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "shell.css").read_text(encoding="utf-8")

    assert "agentRunForMessage" in script
    assert "run?.tool_calls" in script
    assert "data-agent-retry-run" in script
    assert "/agent-runs/${runId}:retry" in script
    assert "expected_thread_version:thread.version" in script
    assert "cache_read_tokens" in script
    assert "cache_write_tokens" in script
    assert "estimated_cost" in script
    assert "blocked:'已阻塞'" in script
    assert "denied:'权限拒绝'" in script
    assert "agentRuntimeBarMarkup(thread)" in script
    assert "/messages:enqueue" in script
    assert "/agent-runs/${runId}" in script
    assert "data-agent-cancel-run" in script
    assert "本轮输入已保存，可以离开页面" in script
    assert '.agent-failure-card' in styles
    assert '.composer-runtime-meta' in styles
    assert '.agent-thinking' in styles
    assert '.agent-technical' in styles
    assert '.agent-stop-button' in styles
    assert "function agentRunHasRecoveryPresentation(runId)" in script
    assert "resolvedByRetry||recoveryPresented?'':" in script
    assert "data-agent-focus-recovery" in script
    assert "恢复卡是本轮唯一的重试入口" in script


def test_agent_retry_refreshes_presentation_after_replacing_work_state():
    script = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    retry_success = "state.work=result.work;\n    await refreshAgentPresentation();\n    setBusy('重试结果已保存');"
    assert script.count(retry_success) >= 2


def test_agent_ui_keeps_tools_and_usage_out_of_the_primary_message_flow():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "shell.css").read_text(encoding="utf-8")

    final_renderer = script[script.rfind("renderConversationMessage=function(message)"):]

    assert '正在思考…' in script
    assert '已思考${elapsed?' in script
    assert '<summary>运行详情</summary>' in script
    assert 'class="agent-technical-tools"' in script
    assert '<ol class="agent-process-steps">' not in script
    assert 'agentRuntimeBarMarkup(thread)' in script
    assert 'total=Number(input)||0' in script
    assert 'class="composer-runtime-meta"' in script
    assert 'agent-runtime-bar' in script
    assert 'content.questions' not in final_renderer
    assert 'content.simulation_notice' not in final_renderer
    assert 'function renderFinalWorkAgentSurface()' in script
    assert 'function renderFinalWorkAgentRail()' in script
    assert 'el.innerHTML=renderFinalWorkAgentSurface()' in script
    assert 'renderFinalWorkAgentRail();' in script
    assert '<span class="agent-thinking-toggle" aria-hidden="true"></span>' in script
    assert 'grouped:index>0&&items[index-1]?.role===message.role' in script
    assert 'conversation-message ${assistant?\'assistant\':\'user\'} ${grouped?\'is-grouped\':\'\'}' in script
    assert '.conversation-message.is-grouped' in styles
    assert '.work-agent-canvas .composer-runtime-meta' in styles
    assert '.work-agent-canvas .agent-runtime-bar' in styles
    assert 'max-height: 260px;' in styles
    assert 'max-height: 220px;' in styles
    assert 'overscroll-behavior: contain;' in styles


def test_agent_decision_card_preserves_audited_choice_contract():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "shell.css").read_text(encoding="utf-8")

    assert "decision_card" in script
    assert "decision_response" in script
    assert "data-decision-option" in script
    assert "data-submit-decision" in script
    assert "data-decision-dismiss" in script
    assert "data-decision-reopen" in script
    assert "const DECISION_CUSTOM_OPTION_ID='__custom__';" in script
    assert 'class="decision-reply-field"' in script
    assert 'placeholder="也可以直接输入其他想法"' in script
    assert "decisionCardCustomDrafts:{}" in script
    assert "state.decisionCardCustomDrafts[key]=customInput.value;" in script
    assert "delete state.decisionCardCustomDrafts[decision.key];" in script
    assert "补充说明（可选）" not in script
    assert "const customSelected=decision.card.allow_custom&&optionId===DECISION_CUSTOM_OPTION_ID;" in script
    assert "const text=customSelected?customText:option.label;" in script
    assert "const dock=event.target.closest('.work-decision-dock');" in script
    assert "dock.querySelector('[data-decision-dismiss]')?.click();" in script
    assert "function focusWorkDecision(" in script
    assert "||dock?.querySelector('[data-confirm-intent], [data-accept-director-proposal], [data-reject-director-proposal]')" in script
    assert "function scheduleWorkDecisionFocus()" in script
    assert "active===document.body||active===document.documentElement||active?.id==='bootScreen'" in script
    assert "requestAnimationFrame(()=>focusWorkDecision());" in script
    assert "requestAnimationFrame(focusIfUnclaimed);" in script
    assert 'element.inert = true' in script
    assert "await api(`/works/${state.work.id}/threads/${thread.id}/messages:enqueue`" in script
    assert "const answeredDecisionIds=new Set(" in script
    assert "!answeredDecisionIds.has(item.id)" in script
    assert ".work-decision-dock" in styles
    assert "position: absolute;" in styles[styles.index(".work-decision-dock"):]
    reopen_styles = styles[styles.index(".decision-reopen"):styles.index(".decision-reopen span:first-child")]
    assert "z-index: 21;" in reopen_styles
    assert ".decision-options" in styles
    assert ".decision-custom-option.selected" in styles
    assert ".decision-custom-field[hidden]" in styles
    assert ".decision-choice-footer" in styles
    assert ".agent-inline-artifact.proposal.pending" in styles
    assert ".proposal-message" in styles
    assert ".artifact-decision-actions" in styles
    assert "prefers-reduced-motion: reduce" in styles


def test_public_message_projection_hides_internal_trace_labels_without_mutating_messages():
    script = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    projection_start = script.index("function publicMessageText(message)")
    projection_end = script.index("function renderConversationMessage(message)", projection_start)
    projection = script[projection_start:projection_end]
    final_renderer = script[script.rfind("renderConversationMessage=function(message)"):]

    # User messages must remain verbatim; only the assistant presentation is
    # projected. The renderer must use that projection, while the persisted
    # message object/API payload stays untouched (the function only reads it).
    assert "if(message?.role!=='assistant')return text;" in projection
    assert "message.content=" not in projection
    assert "message.role=" not in projection
    assert "revision:'当前正文版本'" in projection
    assert "run:'本轮运行'" in projection
    assert "proposal:'候选'" in projection
    assert "sha256:[a-f0-9]{16,}" in projection
    assert "ScriptRelease:'发布版本'" in projection
    assert "publicMessageText(message)" in final_renderer
    assert "esc(messageText(message))" not in final_renderer
    assert "no_direct_writeback" in projection
    assert "当前任务契约与工作流安全规范" in projection
    assert ".replace(/(?<!`)`([^`\\n]+)`(?!`)/g,'$1')" in projection


def test_agent_ui_keeps_next_action_and_mobile_navigation_compact():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "shell.css").read_text(encoding="utf-8")
    html = (web_root / "index.html").read_text(encoding="utf-8")

    assert "function workAgentPendingOrganization" in script
    # The maintainer now requests one Agent-selected inline next-step button.
    # Presence/absence and actual clicks are covered by the discussion browser suite.
    assert "正在整理本轮讨论" in script
    assert "信息足够时 Agent 会自动整理候选" in script
    assert 'content: "切换作品";' in styles
    assert "grid-template-columns: repeat(5, 1fr);" in styles
    assert '<details class="mobile-more-menu">' in html
    assert '<button type="button" data-open-work-switch>切换作品</button>' in html
    assert html.count('data-mobile="agent"') == 0
    assert "button.closest('.mobile-more-menu')?.removeAttribute('open')" in script
    assert ".mobile-more-menu:has(button.active) > summary" in styles
    assert "mobile-thread-open .work-agent-rail-footer" in styles
    assert "display: none !important;" in styles


def test_work_agent_renders_structure_proposals_before_entering_scene_writing():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "shell.css").read_text(encoding="utf-8")

    assert "['brief_blueprint','story_structure'].includes(item.kind)" in script
    assert "hasBlueprint&&!sceneCount" in script
    assert "继续讨论作品结构" in script
    # An optional inline organize action is allowed; the standalone wizard stays removed.
    assert "proposal.kind==='story_structure'" in script
    assert "待采纳" in script
    assert "采纳后才会写入" in script
    assert "采用并建立结构" in script
    assert "若方向或现有结构已变化，本次候选会自动失效" in script
    # Structure is now requested through the conversation/tool contract;
    # the old standalone "整理卷、章与场景树" action must not return.
    assert "data-agent-focus-composer" in script
    assert "title:'整理卷、章与场景树'" not in script
    assert ".structure-proposal-tree" in styles
    assert ".structure-proposal-safety" in styles


def test_agent_knowledge_proposals_distinguish_updates_sources_and_blockers():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "shell.css").read_text(encoding="utf-8")
    renderer = script[
        script.index("function compactParagraphNumber"):
        script.index("function messageAttachmentsMarkup")
    ]

    assert "proposal?.candidate?.operation||'create'" in renderer
    assert "item?.blocking!==false" in renderer
    assert "采用并保存新修订" in renderer
    assert 'disabled aria-disabled="true"' in renderer
    assert "display_label" in renderer
    assert "paragraph_ids" in renderer
    assert "artifact-sources" in renderer
    assert "artifact-conflict" in renderer
    assert "knowledgeFieldChangesMarkup" in renderer
    assert "field_changes" in renderer
    assert "artifact-field-changes" in renderer
    assert "data-partial-knowledge" in renderer
    assert "hasAttribute('data-partial-knowledge')" in script
    assert "selected_fields" in script
    assert "fact?'canon':character?'characters':'world'" in renderer
    assert '.agent-inline-artifact.draft.update' in styles
    assert '.agent-inline-artifact.draft.blocked' in styles
    assert '.artifact-decision-actions button:disabled' in styles
    assert '.artifact-field-changes {' in styles


def test_scene_actions_consume_the_structured_readiness_contract():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")

    assert "readiness.can_run" in script or "readiness?.can_run" in script
    assert "blocking_reasons" in script
    assert "real_ba_writing==='ready'" not in script
    assert "real_ba_writing === 'ready'" not in script
    assert 'real_ba_writing === "ready"' not in script


def test_scene_selection_payload_uses_stable_block_local_offsets():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    selection_handler = script[
        script.index("document.addEventListener('select',event=>{"):
        script.index("registerAppClick(event=>{", script.index("document.addEventListener('select',event=>{"))
    ]

    assert "block_id:block.dataset.blockId" in selection_handler
    assert "local_start:textarea.selectionStart" in selection_handler
    assert "local_end:textarea.selectionEnd" in selection_handler
    assert "revision_id:form.dataset.baseRevision" in selection_handler
    assert "quote:textarea.value.slice(textarea.selectionStart,textarea.selectionEnd)" in selection_handler
    assert "quote:textarea.value.slice(textarea.selectionStart,textarea.selectionEnd),start:" not in selection_handler
    assert "start:textarea.selectionStart,end:textarea.selectionEnd" not in selection_handler


def test_scene_diff_ui_applies_selected_server_change_ids():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "writing-workbench.css").read_text(encoding="utf-8")

    assert "proposal.block_changes" in script
    assert "data-scene-change" in script
    assert "data-select-all-scene-changes" in script
    assert "data-apply-scene-changes" in script
    assert "应用 ${selected.size} 项修改" in script
    assert "selected_change_ids:selected" in script
    assert "取消全选" in script
    assert "inputs.every(input=>input.checked)" in script
    assert ".scene-diff-line.is-removed" in styles
    assert ".scene-diff-line.is-added" in styles
    assert "grid-template-columns: 1fr;" in styles


def test_manuscript_defaults_to_reading_mode_and_keeps_editorial_labels_visible():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "writing-workbench.css").read_text(encoding="utf-8")

    assert 'class="manuscript-reading" data-manuscript-edit' in script
    assert 'class="manuscript-reading-type"' in script
    assert 'class="manuscript-reading-speaker"' in script
    assert "function beginManuscriptEditing(row," in script
    assert "function syncManuscriptReading(row)" in script
    assert "function manuscriptListMarkup(blocks)" in script
    assert "blockRowMarkup(block,index,false" in script
    assert "manuscriptInsertBarMarkup(block.id)" in script
    assert ".writing-workbench-stage .manuscript-block:not(.is-editing) .block-meta" in styles
    assert ".writing-workbench-stage .manuscript-block.is-editing textarea" in styles
    assert ".writing-workbench-stage .manuscript-block .manuscript-reading" in styles


def test_manuscript_dialogue_and_narration_use_distinct_type_systems():
    styles = (
        Path(__file__).resolve().parents[1] / "web" / "writing-workbench.css"
    ).read_text(encoding="utf-8")

    assert 'data-block-type="dialogue"' in styles
    assert 'data-block-type="narration"' in styles
    assert 'font-family: var(--font-ui) !important;' in styles
    assert 'font-family: var(--font-reading) !important;' in styles
    assert 'letter-spacing: .012em !important;' in styles
    assert 'letter-spacing: .03em !important;' in styles


def test_scene_proposal_ui_previews_review_invalidation_without_a_second_action():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")

    assert "function sceneProposalImpactMarkup(proposal)" in script
    assert "应用后的影响" in script
    assert "本场需要重新检查" in script
    assert "连续性与发布检查需要重新运行" in script
    assert "已有制作定稿保持不变" in script
    assert "新正文版本已建立；旧审查结果不再适用，请先检查本场" in script
    assert script.count('data-apply-scene-changes="${esc(proposal.id)}"') == 1


def test_knowledge_proposal_ui_previews_impact_and_explains_batch_selection():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")

    assert "impact_preview" in script
    assert "影响预览" in script
    assert "具体范围" in script
    assert "impact_refs" in script
    assert "全部选择" in script
    assert "data-select-all-knowledge" in script
    assert "应用 ${selectedCount} 项修改" in script


def test_task_center_distinguishes_ready_from_retry_and_exposes_details():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")

    assert "ready:'等待执行'" in script
    assert "ready:'等待重试'" not in script
    assert "查看详情" in script
    assert "data-task-details" in script


def test_production_embed_clears_mobile_active_state_before_marking_production():
    script = (
        Path(__file__).resolve().parents[1] / "web" / "production-embed.js"
    ).read_text(encoding="utf-8")

    assert 'document.querySelectorAll("[data-mobile].active")' in script
    assert 'item.classList.remove("active")' in script


def test_work_agent_scrollbar_is_owned_by_the_full_desktop_workspace():
    styles = (
        Path(__file__).resolve().parents[1] / "web" / "shell.css"
    ).read_text(encoding="utf-8")

    scroll_fix = styles[styles.index("/* The desktop workspace owns scrolling."):]

    assert ".app-shell.work-agent-stage .work-agent-canvas" in scroll_fix
    assert "width: 100%;" in scroll_fix
    assert "max-width: none;" in scroll_fix
    assert "overflow-x: hidden;" in scroll_fix
    assert "calc((100% - 1040px) / 2 + 30px)" in scroll_fix
    assert "width: min(calc(100% - 36px), 988px);" in scroll_fix
    assert "scrollbar-width: thin;" in scroll_fix


def test_mobile_work_canvas_keeps_composer_in_content_flow():
    styles = (
        Path(__file__).resolve().parents[1] / "web" / "writing-workbench.css"
    ).read_text(encoding="utf-8")

    assert ".work-agent-stage .work-agent-canvas" in styles
    assert "overflow-y: auto !important;" in styles
    assert "position: static;" in styles
    assert "margin: 0 10px 24px !important;" in styles


def test_mobile_work_agent_uses_one_scroll_owner_for_plan_and_conversation():
    styles = (
        Path(__file__).resolve().parents[1] / "web" / "shell.css"
    ).read_text(encoding="utf-8")

    scroll_fix = styles[styles.index("/* Mobile Works uses one scroll owner."):]
    assert "display: block;" in scroll_fix
    assert "overflow-y: auto;" in scroll_fix
    assert "padding-bottom: 144px;" in scroll_fix
    assert ".app-shell.work-agent-stage .work-agent-thread" in scroll_fix
    assert "overflow: visible;" in scroll_fix


def test_work_agent_and_writing_use_the_same_secondary_rail_baseline():
    styles = (
        Path(__file__).resolve().parents[1] / "web" / "shell.css"
    ).read_text(encoding="utf-8")

    rail_fix = styles[styles.index("/* The Works conversation rail follows the same structural baseline"):]

    assert "grid-template-columns: 58px 280px minmax(0, 1fr) 0 !important;" in rail_fix
    assert "background: #eef0f3;" in rail_fix
    assert ".work-agent-stage .conversation-message.assistant" in rail_fix
    assert "justify-self: center;" in rail_fix


def test_work_switch_uses_a_clear_down_chevron_instead_of_text_glyph():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "shell.css").read_text(encoding="utf-8")

    assert 'class="rail-work-switch-glyph"' in script
    assert '>⌄</button>' not in script
    assert ".rail-work-switch-glyph {" in styles
    assert "border-right: 1.5px solid currentColor;" in styles
    assert "border-bottom: 1.5px solid currentColor;" in styles


def test_production_embed_removes_imported_inline_styles_for_strict_csp():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "production-embed.js").read_text(encoding="utf-8")
    styles = (web_root / "production-embed.css").read_text(encoding="utf-8")

    assert 'document.importNode(stripInlineStyles(sidebar), true)' in script
    assert 'replace(/\\sstyle="display:none;"/gi, "")' in script
    assert 'querySelectorAll("[style]")' in script
    assert 'removeAttribute("style")' in script
    assert '<div style=' not in script
    assert '.production-embed-error {' in styles
    assert '.app-shell.production-mode .crumb {' in styles
    assert '.app-shell.production-mode .top-actions {' in styles


def test_production_embed_owns_navigation_and_hides_writing_chrome_accessibly():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "production-embed.js").read_text(encoding="utf-8")
    styles = (web_root / "production-embed.css").read_text(encoding="utf-8")

    assert 'document.querySelectorAll("[data-section], [data-mobile]")' in script
    assert 'document.querySelectorAll(".primary-nav, .mobile-nav")' in script
    assert 'navigation.querySelector(\'[data-section="production"]\')' in script
    assert 'restoreNavigationState(previousChrome.navigation)' in script
    assert 'item.inert = true' in script
    assert 'item.setAttribute("aria-hidden", "true")' in script
    assert 'restoreWritingChromeAccessibility(previousChrome.writingChrome)' in script
    assert '@media (max-width: 760px)' in styles


def test_primary_navigation_closes_the_asset_surface_before_section_handlers_render():
    script = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    reset = "if(button.dataset.section&&button.dataset.section!=='assets')state.assetSurfaceOpen=false;"
    assert reset in script
    assert "registerAppClick(event=>{" in script

def test_production_embed_can_prepare_the_hidden_surface_before_first_open():
    script = (
        Path(__file__).resolve().parents[1] / "web" / "production-embed.js"
    ).read_text(encoding="utf-8")

    assert "function ensureProductionSurface()" in script
    assert "async function preload()" in script
    assert 'loadState = "loading"' in script
    assert 'loadState = "ready"' in script
    assert "if (!app()?.classList.contains(\"production-mode\")) element.hidden = true" in script
    assert "window.HaloCueProductionEmbed = { open, close, preload, status" in script


def test_production_embed_does_not_retry_warmup_over_a_visible_open_or_failure():
    script = (
        Path(__file__).resolve().parents[1] / "web" / "production-embed.js"
    ).read_text(encoding="utf-8")

    preload = script[script.index("async function preload()"):script.index("function status()")]
    assert 'app()?.classList.contains("production-mode")' in preload
    assert 'loadState === "failed"' in preload
    assert "return element.shadowRoot;" in preload


def test_production_embed_restores_focus_after_async_surface_open():
    script = (
        Path(__file__).resolve().parents[1] / "web" / "production-embed.js"
    ).read_text(encoding="utf-8")

    open_tail = script[script.index("const root = await ensureProductionSurface();"):]
    assert "await selectRun(root, context.runId);" in open_tail
    assert "element.focus({ preventScroll: true });" in open_tail
    assert open_tail.index("await selectRun(root, context.runId);") < open_tail.index(
        "element.focus({ preventScroll: true });"
    )


def test_production_embed_keeps_handoff_status_out_of_the_ordinary_workbench():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "production-embed.js").read_text(encoding="utf-8")
    styles = (web_root / "production-embed.css").read_text(encoding="utf-8")

    assert "production-handoff-inspector" not in script
    assert "function sanitizeProductionUserLabels(root)" in script
    assert "run-[a-z0-9]+" in script
    assert "root.querySelectorAll('p,small,strong,span,h3')" in script
    assert "data-run-id" in script
    assert ".replace(/\\s*·\\s*run-[a-z0-9]+/ig, '')" in script
    assert "制作任务已打开" in script
    assert "已编译" in script
    assert "场景" in script
    html = (web_root / "index.html").read_text(encoding="utf-8")
    import re
    assert re.search(r'<script src="/production-embed\.js\?v=[^" ]+" defer></script>', html)
    assert "已送往 AA 制作" not in script
    assert 'save.textContent = context.runId ? "制作任务已打开" : "选择制作任务"' in script
    assert "制作任务 ${context.runId}" not in script
    assert "项素材已准备" not in script
    assert "handoff-summary-detail" not in script
    assert "data-handoff-refresh" not in script
    assert 'data-production-proxy="refreshRun"' in script
    assert 'aria-label="刷新制作任务"' in script
    assert "ScriptRelease 与 ProductionRun 已关联" not in script
    assert "<dt>发布标识</dt>" not in script
    assert "<dt>正文 Hash</dt>" not in script
    assert "<dt>制作任务</dt>" not in script
    assert "<dt>引用</dt>" not in script
    assert "<dt>原件版本</dt>" not in script
    assert "<dt>原件 Hash</dt>" not in script
    assert "<dt>任务副本</dt>" not in script
    assert ".production-handoff-inspector" not in styles
    assert ".handoff-reference-title" not in styles


def test_production_embed_separates_background_library_purposes():
    web_root = Path(__file__).resolve().parents[1] / "web"
    embed = (web_root / "production-embed.js").read_text(encoding="utf-8")
    production = (Path(__file__).resolve().parents[2] / "production" / "ui" / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "production-embed.css").read_text(encoding="utf-8")
    assert 'chooseResource("backgrounds", "场景背景"' in production
    assert "backgroundTimelineSource" in production
    assert 'previewResourceUrl("backgrounds"' in production
    assert "background-timeline-node" in production
    assert "ensureProductionSurface" in embed
    assert "embedded-background-preview" in styles

def test_production_embed_background_browser_keeps_ordinary_surface_compact():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "production-embed.js").read_text(encoding="utf-8")
    styles = (web_root / "production-embed.css").read_text(encoding="utf-8")

    assert 'heading.textContent = "选择背景"' in script
    assert 'input.placeholder = "输入地点、氛围或背景名称"' in script
    assert "backgroundCategoryInfo" in script
    assert "IntersectionObserver" in script
    assert "background-preview-placeholder" in script
    assert "embedded-background-browser" in styles
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in styles
    assert "embedded-background-category-list" in styles
    assert "当前任务可用素材" not in script
    assert "只读素材快照" not in script


def test_production_embed_asset_context_updates_are_idempotent():
    script = (
        Path(__file__).resolve().parents[1] / "web" / "production-embed.js"
    ).read_text(encoding="utf-8")

    # This function runs inside a subtree MutationObserver. Reassigning the
    # same text would schedule the observer forever and starve the workbench.
    assert "if (heading && heading.textContent !== selected.title)" in script
    assert "if (label && label.textContent !== selected.search)" in script
    assert "if (input && input.placeholder !== selected.placeholder)" in script


def test_writing_ui_allows_explicit_narrator_only_direction_without_character_cards():
    script = (
        Path(__file__).resolve().parents[1] / "web" / "app.js"
    ).read_text(encoding="utf-8")

    assert "blueprint()?.narrator_only!==true" in script
    assert "narratorOnly=b.narrator_only===true" in script
    assert "纯旁白，不需要人物卡" in script
    assert "cards.length||narratorOnly" in script
    assert "confirmedCards.length||narratorOnly" in script


def test_production_embed_restructures_the_existing_stage_workflow_without_copying_state():
    web_root = Path(__file__).resolve().parents[1] / "web"
    embed = (web_root / "production-embed.js").read_text(encoding="utf-8")
    production = (Path(__file__).resolve().parents[2] / "production" / "ui" / "app.js").read_text(encoding="utf-8")
    assert "ensureProductionSurface" in embed
    assert "window.HaloCueProductionEmbed" in embed
    assert "data-scene-plan-card" in production
    assert "backgroundTimelineSource" in production
    assert "installBackgroundClassification" in production or "chooseResource" in production

def test_production_review_workbench_auto_selects_and_projects_read_only_preview():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "production-embed.js").read_text(encoding="utf-8")
    styles = (web_root / "production-embed.css").read_text(encoding="utf-8")

    assert "function installNativeReviewParity(root)" in script
    assert "installNativeReviewParity(root);" in script
    assert "function installReviewWorkbench(root)" in script
    assert (
        'cards.find(card => card.classList.contains("blocking") || card.classList.contains("pending")) || cards[0]'
        in script
    )
    assert 'navigation.className = "production-review-navigation"' in script
    assert "allFilter.click();" in script
    assert 'refreshedCard?.scrollIntoView({ block: "center", behavior: "smooth" })' in script
    assert "#page-review.production-native-review-parity .card-list .draft-card" in styles
    assert ".production-review-navigation" in styles
    assert "width: calc(100% - 20px);" in styles
    assert "text-align: left;" in styles
    assert "/performance-preview`" in script
    assert "const cacheKey = `${runId}|${version}`" in script
    assert "root.__haloCuePreviewRequestId !== requestId" in script
    assert "frame.card_id === selected" in script
    assert "data-production-timeline-card" in script
    assert "production-preview-retry" in script
    assert ".production-live-preview" in styles
    assert ".production-background-timeline" in styles
    assert ".preview-open .production-review-side" in styles
    assert "transition: transform 220ms var(--production-ease)" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles


def test_production_asset_workbench_deduplicates_and_cancels_stale_background_queries():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "production-embed.js").read_text(encoding="utf-8")

    assert "root.__haloCueResourceCache" in script
    assert "root.__haloCueResourcePending" in script
    assert "if (cache.has(cacheKey)) return cache.get(cacheKey)" in script
    assert "if (pending.has(cacheKey)) return pending.get(cacheKey)" in script
    assert "root.__haloCueBackgroundRequest?.abort()" in script
    assert "new AbortController()" in script
    assert 'error?.name === "AbortError"' in script
    assert "IntersectionObserver" in script
    assert 'title.textContent = "素材工作台"' in script
    assert "初始素材快照" in script
    assert "source.hidden = true" in script


def test_production_settings_separates_workspace_model_and_render_status():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "production-embed.js").read_text(encoding="utf-8")
    styles = (web_root / "production-embed.css").read_text(encoding="utf-8")

    assert "function installSettingsWorkbench(root)" in script
    assert 'renderButton.textContent = "渲染状态"' in script
    assert '<summary>技术详情</summary>' in script
    assert 'pane !== "workspace"' in script
    assert 'pane !== "model"' in script
    assert 'pane !== "render"' in script
    assert ".production-settings-workbench .settings-tabs" in styles
    assert ".production-technical-details" in styles


def test_release_ui_hides_identifiers_and_folds_integrity_details():
    script = (
        Path(__file__).resolve().parents[1] / "web" / "app.js"
    ).read_text(encoding="utf-8")

    assert "<p class=\"code-meta\">${esc(r.id)}" not in script
    assert "已关联 AA 制作任务；素材副本确认情况见下方。" in script
    assert "当前发布版本已完成交接。" not in script
    assert "<summary>技术详情</summary>" in script
    assert "<b>交付内容已确认</b><span>可追溯</span>" in script
    assert "读取不可变 Manifest" not in script
    assert "<dt>正文 Hash</dt>" not in script


def test_main_user_surfaces_use_plain_language_and_fold_run_metrics():
    web_root = Path(__file__).resolve().parents[1] / "web"
    html = (web_root / "index.html").read_text(encoding="utf-8")
    script = (web_root / "app.js").read_text(encoding="utf-8")
    workbench = (web_root / "writing-workbench.js").read_text(encoding="utf-8")

    assert "冻结 ScriptRelease" not in html
    assert "生成制作定稿" in html
    assert '<details class="proposal-runtime-details"><summary>运行详情</summary>' in script
    assert 'aria-label="Agent 状态"' in script
    assert "aria-label=\"Agent 运行信息\"" not in script
    assert "PROPOSAL / 未写入" not in script
    assert "基准 ${esc(revision.id)}" not in script
    assert "scene-arrangement-copy small" in script
    assert "const missingScene=scenes().find(scene=>!scene.current_revision_id)" in script
    assert 'data-release-missing-scene="${esc(missingScene.id)}"' in script
    assert "去完成「${esc(missingScene.title)}」" in script
    assert "button.dataset.releaseMissingScene" in script
    assert "heading.focus({preventScroll:true})" in script
    assert "当前场景" in script
    assert "所有正式修改先成为候选并显示差异" in script
    assert "ProductionRun 副本保持分离" not in workbench
    assert "副本回执按发布版本记录" in workbench
    assert "尚未收到制作任务的素材副本" not in workbench


def test_production_embed_recovers_focus_after_embedded_rerender_when_body_is_active():
    script = (
        Path(__file__).resolve().parents[1] / "web" / "production-embed.js"
    ).read_text(encoding="utf-8")

    assert "function installFocusRecovery(root, element)" in script
    assert "new MutationObserver" in script
    assert "document.activeElement !== document.body" in script
    assert "observer.observe(root, { childList: true, subtree: true })" in script
    assert "installFocusRecovery(root, element);" in script


def test_work_switch_dialog_is_constrained_to_the_viewport():
    web_root = Path(__file__).resolve().parents[1] / "web"
    styles = (web_root / "shell.css").read_text(encoding="utf-8")

    assert '#workSwitchDialog {' in styles
    assert 'max-width: calc(100vw - 32px);' in styles
    assert '#workSwitchDialog .work-switch-dialog {' in styles
    assert 'min-width: 0 !important;' in styles
    assert 'overflow-x: hidden;' in styles


def test_agent_plus_menu_includes_document_upload_without_a_second_toolbar_button():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")

    assert 'data-attachment-upload="image"' in script
    assert 'data-attachment-upload="document"' in script
    assert 'id="workAgentDocumentInput"' in script
    assert '.txt,.md,.pdf,.docx' in script
    assert '.aap' in script
    assert 'data-open-import-dialog' in script
    assert '交给 Agent 转换' in script
    assert "文档已提取文字并加入本轮消息" in script


def test_scene_memory_ui_uses_memory_bundle_workflow_without_hijacking_scene_diff():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "shell.css").read_text(encoding="utf-8")

    assert "p.kind==='scene_script'" in script
    assert "item.kind==='memory_bundle'" in script
    assert "runDurableAgentJob('memory.extract'" in script
    assert "/agent-jobs" in script
    assert "/memory:skip" in script
    assert "selected_item_ids:selectedIds" in script
    assert 'data-memory-item="${esc(proposal.id)}"' in script
    assert "incomplete_memory_scene_ids" in script
    assert "data-memory-open-scene" in script
    assert "memoryLibraryMarkup" in script
    assert "data-memory-lifecycle" in script
    assert "/memories/${memoryId}/${action}" in script
    assert ".scene-memory-review" in styles
    assert ".release-memory-guidance" in styles
    assert ".memory-library-card" in styles


def test_archived_conversations_are_managed_from_settings(tmp_path):
    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "归档接口测试"})
    thread = work["conversation_threads"][0]
    service.update_conversation_thread(
        work["id"],
        thread["id"],
        {"expected_thread_version": thread["version"], "status": "archived"},
    )
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        query = urllib.parse.urlencode({"q": "归档"})
        status, result = request(f"http://127.0.0.1:{server.server_port}/api/v1/settings/conversations?{query}")
        assert status == 200
        assert len(result["data"]) == 1
        assert result["data"][0]["work_title"] == "归档接口测试"
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)


def test_writing_workbench_has_scoped_navigation_agent_and_mobile_contracts():
    web_root = Path(__file__).resolve().parents[1] / "web"
    app = (web_root / "app.js").read_text(encoding="utf-8")
    workbench = (web_root / "writing-workbench.js").read_text(encoding="utf-8")
    assert "data-mobile" in app
    assert "data-panel-toggle" in app
    assert "focusChapterScene" in workbench
    assert "sceneAtReadingPosition" in workbench

def test_mobile_writing_defaults_to_two_views_and_does_not_reserve_hidden_panes():
    web_root = Path(__file__).resolve().parents[1] / "web"
    app = (web_root / "app.js").read_text(encoding="utf-8")
    workbench = (web_root / "writing-workbench.js").read_text(encoding="utf-8")
    styles = (web_root / "writing-workbench.css").read_text(encoding="utf-8")
    assert "mobileView" in app
    assert "state.mobileView = 'writing'" in workbench
    assert "writingMobileView" in workbench
    assert "@media" in styles

def test_writing_workbench_explains_work_readiness_and_locked_actions():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "writing-workbench.js").read_text(encoding="utf-8")
    app_script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "writing-workbench.css").read_text(encoding="utf-8")

    assert "function writingReadinessView()" in script
    assert "if (!readiness.blocked) return '';" in script
    assert "state.agentPresentation?.guidance || state.work?.harness" in script
    assert 'id="writingReadiness"' in script
    assert 'data-writing-return-to-work' in script
    assert 'class="writing-readiness-detail"' in script
    assert 'data-writing-gate=' in script
    assert '添加场景未开放，点击查看原因' in script
    assert '先处理作品中的待审决定，完成后这里会开放建立第一场。' in script
    assert '未开放，点击查看原因' in script
    assert "event.target.closest('[data-writing-gate]')" in script
    assert "focusWritingReadiness" in script
    assert "data-proposal-card" in app_script
    assert ".writing-readiness.is-blocked" in styles
    assert ".writing-gate-locked[data-writing-gate]" in styles
    assert "${draftGate.allowed ? '' : 'disabled'}" not in script
    assert "${formal ? '' : 'disabled'}" not in script


def test_writing_route_reload_uses_full_work_loader_for_agent_state():
    app = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert "loadWork" in app
    assert "workConversationThread" in app
    assert "renderFinalWorkAgentSurface" in app

def test_writing_router_does_not_replace_the_integrated_production_deep_link():
    app = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    embed = (Path(__file__).resolve().parents[1] / "web" / "production-embed.js").read_text(encoding="utf-8")
    assert "requestProduction('/activate')" in app
    assert "production" in app
    assert "production-mode" in embed
    assert "HaloCueProductionEmbed" in embed

def test_first_use_dialog_keeps_primary_action_visible_on_short_viewports():
    styles = (Path(__file__).resolve().parents[1] / "web" / "shell.css").read_text(encoding="utf-8")
    assert "#workDialog" in styles
    assert "transform: translate(-50%, -50%);" in styles
    assert "width: min(560px, calc(100vw - 28px));" in styles
    assert "background: var(--paper);" in styles
    assert "max-height: min(720px, calc(100dvh - 28px));" in styles
    assert "#workDialog .dialog-actions" in styles
    assert "position: sticky;" in styles


def test_creation_route_keeps_one_next_action_visible_on_work_and_writing_surfaces():
    app = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert "function workUserStatusMarkup" in app
    assert "data-user-status-action" in app
    assert "function renderFinalWorkAgentSurface" in app

def test_works_conversation_prioritizes_recent_messages_and_plain_language():
    app = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    styles = (Path(__file__).resolve().parents[1] / "web" / "shell.css").read_text(encoding="utf-8")
    assert "visibleCount" in app
    assert "function workAgentUserHeadline" in app
    assert "function renderFinalWorkAgentSurface" in app
    assert "position: sticky;" in styles

def test_works_conversation_rail_does_not_repeat_the_global_current_work_identity():
    app = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
    assert 'function renderWorkAgentThreadList()' in app
    assert 'data-thread-search-toggle' in app
    assert 'data-thread-create' in app
    assert 'data-open-work-switch' in html

def test_pending_scene_proposal_promotes_diff_to_the_primary_next_action():
    script = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.js").read_text(encoding="utf-8")
    assert "const proposal = typeof pendingProposal === 'function' ? pendingProposal() : null;" in script
    assert "有一份候选等待决定" in script
    assert "data-focus-scene-diff" in script
    assert "function focusSceneDiff(" in script
    assert "diff.querySelectorAll('input[type=\"checkbox\"]')" in script or "data-review-change" in script


def test_scene_generate_command_enters_agent_composer_instead_of_being_silent():
    script = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'data-action="generate-candidate"' in script
    assert "state.writingMobileView='agent'" in script
    assert "#sceneConversationForm textarea[name=\"text\"]" in script
    assert "input.setSelectionRange(input.value.length,input.value.length)" in script


def test_blocked_scene_agent_keeps_discussion_composer_but_denies_candidate_generation():
    script = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert "const discussionOnly=!readiness.canRun" in script
    assert "const canChat=Boolean(thread&&!activeRun)" in script
    assert "data-discussion-only=\"${discussionOnly?'true':'false'}\"" in script
    assert "discussion_only:form.dataset.discussionOnly==='true'" in script
    assert "说说这一场想怎么写…" in script
    assert "正文候选暂不可生成" in script
    assert "当前缺少：" in script
    # Labels no longer change semantics by viewport; candidate gating still does.
    assert "canSend&&!discussionOnly&&!proposal" in script
    assert "canSend=Boolean(canChat&&!preparingContext)" in script
    # Candidate generation is initiated through the discussion composer.
    # Recovery may still expose an explicit retry, but the normal composer no
    # longer renders a duplicate generate button.
    assert "data-generate-scene-proposal ${canPropose?'':'disabled'}" not in script


def test_scene_agent_resumes_polling_after_refresh_from_durable_run():
    script = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert "state.stage==='draft'&&state.sceneId" in script
    assert (
        "const thread=sceneConversationThread(selectedScene()),run=thread?workAgentActiveRun(thread):null"
        in script
    )
    assert "if(run)scheduleAgentRunPoll(run.id);" in script


def test_reference_overview_prioritizes_the_current_decision_on_mobile():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "styles.css").read_text(encoding="utf-8")

    assert "function renderReferences" in script
    assert "reference-mobile-navigation" in script
    assert "libraryDecisionGuideMarkup" in script
    assert "main.querySelector('.library-brief')?.before(guide)" in script
    assert ".library-nav{display:flex;flex-direction:row;overflow-x:auto" in styles
    assert ".library-scope-banner div:nth-child(2),.library-scope-banner .status-chip{display:none}" in styles


def test_work_dialog_cancel_is_not_blocked_by_required_fields():
    web_root = Path(__file__).resolve().parents[1] / "web"
    html = (web_root / "index.html").read_text(encoding="utf-8")
    app = (web_root / "app.js").read_text(encoding="utf-8")
    assert 'id="workDialog"' in html
    assert 'data-close-work-dialog' in html
    assert "function closeWorkDialog()" in app
    assert "function openWorkDialog(" in app

def test_unsaved_manuscript_is_preserved_and_guarded_across_navigation():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    html = (web_root / "index.html").read_text(encoding="utf-8")

    assert "manuscriptDraftBlocks:null" in script
    assert "function activeManuscriptBlocks" in script
    assert "function captureManuscriptDraft" in script
    assert "function requestManuscriptNavigation" in script
    assert "window.addEventListener('beforeunload'" in script
    # The unified router owns history; guard is exercised by integrated browser tests.
    history_handler = script[script.index("window.addEventListener('popstate',()=>{"):script.index("function hcViewKey")]
    assert "state.manuscriptDirty&&(differentWork||routeLeavesManuscript(target))" in history_handler
    assert "requestManuscriptNavigation" in history_handler
    assert "history.go(-delta)" in history_handler
    assert "请先保存正文，再运行依赖正式正文的操作" in script
    assert 'id="unsavedManuscriptDialog"' in html
    assert "继续编辑" in html
    assert "放弃修改并离开" in html


def test_work_agent_projects_official_script_as_a_writing_review_candidate():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "writing-workbench.css").read_text(encoding="utf-8")

    assert "function extractOfficialScript(text)" in script
    assert "function officialScriptCandidateMarkup(message)" in script
    assert 'class="official-script-candidate"' in script
    assert "尚未写入的正文" in script
    assert "data-open-official-script" in script
    assert "state.inspector='decision'" in script
    assert "state.writingMobileView='review'" in script
    assert ".official-script-candidate" in styles


def test_scene_candidate_keeps_full_context_and_selective_change_review():
    web_root = Path(__file__).resolve().parents[1] / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "writing-workbench.css").read_text(encoding="utf-8")
    review_script = (web_root / "change-review.js").read_text(encoding="utf-8")

    assert "function sceneFullContextMarkup(proposal,changes)" in script
    assert 'class="scene-full-context"' in script
    assert "审查 AI 的正文改动" in script
    assert 'class="scene-diff-choice"' in review_script
    assert "data-scene-change" in script
    assert "data-apply-scene-changes" in script
    assert "function sceneChangePreviewMarkup(change)" in script
    assert "data-scene-change-preview" in review_script
    assert "加入这段内容" not in script[script.index("function sceneProposalReviewMarkup"):script.index("function sceneFindingLabel")]
    assert "currentBlocks.slice(cursor,start)" in script
    assert "['旁白','叙述'].includes(speaker)" in script
    assert "无对应文字" not in script
    assert "scene-diff-columns" not in script[script.index("function sceneProposalReviewMarkup"):script.index("function sceneFindingLabel")]
    assert ".scene-context-line.is-removed" in styles
    assert ".scene-context-line.is-added" in styles


def test_agent_composers_stay_docked_and_scene_agent_has_one_scroll_owner():
    styles = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.css").read_text(encoding="utf-8")

    assert ".app-shell.work-agent-stage .work-agent-composer { position: sticky !important" in styles
    assert ".app-shell.work-agent-stage .work-agent-composer { position: fixed !important" in styles
    assert "#inspectorContent:has(.scene-harness) { overflow: hidden !important; }" in styles
    assert ".writing-workbench-stage .writing-mobile-pane .scene-conversation-scroll" in styles
    assert "flex: 1 1 auto !important;" in styles[styles.index(".writing-workbench-stage .writing-mobile-pane .scene-conversation-scroll"):]
    assert "overflow-y: auto !important" in styles


def test_work_composer_permission_control_stays_readable_without_a_blank_mask():
    styles = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.css").read_text(encoding="utf-8")
    script = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert "min-width: 92px !important" in styles
    assert ".permission-menu > summary > span:not(.permission-mark)" in styles
    assert "padding-bottom: 20px !important;" in styles
    assert "bottom: 0;" in styles
    assert "margin-bottom: 0 !important;" in styles
    assert ".app-shell.work-agent-stage .work-agent-composer::before" not in styles
    assert ".app-shell.work-agent-stage .work-agent-composer::after" not in styles
    assert "0 -1px 0 #e1e8e4" in styles
    assert "<span class=\"permission-mark\"" not in script
    assert "<span class=\"permission-option-mark\"" not in script


def test_manuscript_inserts_a_new_block_at_the_selected_gap():
    script = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    styles = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.css").read_text(encoding="utf-8")

    assert "function manuscriptInsertBarMarkup(afterId)" in script
    assert "data-manuscript-insert=\"${esc(afterId||'')}\"" in script
    assert "target.after(row)" in script
    assert "row.after(new DOMParser" in script
    assert "previous.before(row,bar)" in script
    assert "nextBar.after(row,bar)" in script
    assert ".manuscript-insert-bar" in styles
    assert ".manuscript-empty-insert" in styles


def test_manuscript_insert_affordance_is_quiet_until_targeted_and_touchable():
    styles = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.css").read_text(encoding="utf-8")

    assert ".manuscript-insert-bar:hover > span" in styles
    assert ".manuscript-insert-bar:focus-within > span" in styles
    assert "opacity: 0;" in styles[styles.index(".writing-workbench-stage .manuscript-insert-button"):styles.index(".writing-workbench-stage .manuscript-insert-button", styles.index(".writing-workbench-stage .manuscript-insert-button") + 1)]
    assert "pointer-events: auto;" in styles[styles.index("@media (max-width: 760px), (hover: none), (pointer: coarse)"):]
    assert "transform: translateY(-50%) scaleY(1.6);" in styles
    assert "box-shadow: 0 0 0 3px rgba(159, 181, 202, .14)" not in styles
    assert "transition: background-color 180ms var(--wb-ease-out)" in styles


def test_onboarding_explains_key_work_and_scene_controls():
    script = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    workbench = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.js").read_text(encoding="utf-8")
    styles = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.css").read_text(encoding="utf-8")

    assert "state.surface==='writing'&&state.stage==='draft'" in script
    assert "root.addEventListener('click'" in script
    assert "root.addEventListener('keydown'" in script
    assert "event.key==='Escape'" in script
    assert "选择要应用的变化" in script
    assert "Agent 只能产生候选" in script
    assert "正文候选不是聊天文案" in script
    assert "决定正式修改如何落地" in script
    assert "图片或文档只作为当前讨论的输入" in script
    assert "workSwitch && workSwitch.dataset.selectWork === state.work?.id" in workbench
    assert ".onboarding-tour { position: fixed; inset: 0; z-index: 10000; pointer-events: auto; }" in styles
    assert ".onboarding-highlight" in styles and "pointer-events: none" in styles[styles.index(".onboarding-highlight"):styles.index(".onboarding-highlight") + 500]


def test_pending_scene_proposal_is_rendered_inside_manuscript_surface():
    script = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    styles = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.css").read_text(encoding="utf-8")

    assert "manuscriptMarkup(scene,manuscript,proposal" in script
    assert "has-inline-review" in script
    assert "查看待审修改" in script
    assert "完整正文预览" in script
    assert "data-apply-scene-changes" in script
    assert ".manuscript-desk.has-inline-review" in styles


def test_writing_draft_renders_a_continuous_chapter_with_scene_anchors():
    web_root = Path(__file__).resolve().parents[1] / "web"
    app = (web_root / "app.js").read_text(encoding="utf-8")
    workbench = (web_root / "writing-workbench.js").read_text(encoding="utf-8")
    assert "data-chapter-scene-anchor" in app or "data-chapter-scene-anchor" in workbench
    assert "chapter-manuscript" in app
    assert "focusChapterScene" in workbench

def test_writing_shell_defaults_to_manuscript_and_opens_agent_on_demand():
    shell = (Path(__file__).resolve().parents[1] / "web" / "shell.js").read_text(encoding="utf-8")
    assert "let panels" in shell
    assert "window.HaloCuePanels" in shell
    assert "button.dataset.inspector" in shell

def test_scene_switch_preserves_scroll_and_keeps_empty_manuscript_compact():
    web_root = Path(__file__).resolve().parents[1] / "web"
    workbench = (web_root / "writing-workbench.js").read_text(encoding="utf-8")
    styles = (web_root / "writing-workbench.css").read_text(encoding="utf-8")
    assert "focusChapterScene" in workbench
    assert "scrollBehavior" in workbench
    assert "workspace.scrollTo" in workbench
    assert ".manuscript-empty" in styles

def test_continuous_chapter_tracks_the_scene_under_the_reading_position():
    web_root = Path(__file__).resolve().parents[1] / "web"
    workbench = (web_root / "writing-workbench.js").read_text(encoding="utf-8")
    styles = (web_root / "writing-workbench.css").read_text(encoding="utf-8")
    assert "function focusChapterScene(sceneId)" in workbench
    assert "function sceneAtReadingPosition(workspace)" in workbench
    assert "data-chapter-scene-anchor" in workbench
    assert "bindChapterScrollTracking" in workbench
    assert ".chapter-manuscript-flow" in styles

def test_chapter_reading_uses_one_manuscript_surface_and_hides_internal_inspectors():
    web_root = Path(__file__).resolve().parents[1] / "web"
    app = (web_root / "app.js").read_text(encoding="utf-8")
    workbench = (web_root / "writing-workbench.js").read_text(encoding="utf-8")
    styles = (web_root / "writing-workbench.css").read_text(encoding="utf-8")

    assert "function chapterReadingBlockMarkup(block,index)" in app
    assert "chapter-edit-tools" not in app
    assert "编辑本场正文" not in app
    assert "function chapterInlineManuscriptMarkup(scene,artifact)" in app
    assert 'class="chapter-inline-manuscript"' in app
    assert "data-scene-id=\"${esc(scene?.id||'')}\"" in app
    assert "const sceneId=form.dataset.sceneId||state.sceneId" in app
    assert "state._pendingChapterSceneScroll=scene.id" in app
    assert "async function saveLibraryMutation(path,payload,{artifactId=''})" in app
    assert "artifactId=state.editCard?.artifactId||''" in app
    assert "data-manuscript-edit-first" not in app
    assert "data-manuscript-insert=" in app
    assert "manuscript-insert-bar" in app
    assert "添加第一段" in app
    assert "场景 Agent" in app
    assert "章节正文" in app
    assert "查看待审修改" in app
    assert "scope.textContent = `${scene.chapterTitle} · ${scene.title} · 仅处理当前场景`" in workbench
    assert "title.textContent = '本场 Agent'" not in workbench
    assert (
        "state.context = null;"
        not in workbench[
            workbench.find("function syncSceneFromScroll") : workbench.find(
                "function scheduleSceneScrollSync"
            )
        ]
    )
    assert '.writing-workbench-stage .inspector-tabs button[data-inspector="context"]' in styles
    assert '.writing-workbench-stage .inspector-tabs button[data-inspector="decision"]' in styles
    assert (
        ".writing-workbench-stage .scene-agent-panel .agent-context-brief { display: none; }"
        in styles
    )
    assert ".writing-workbench-stage .chapter-inline-manuscript" in styles
    assert ".app-shell.work-agent-stage .work-agent-composer" in styles
    assert "box-shadow: 0 -1px 0 #e1e8e4" in styles
    assert "box-shadow: 0 -18px 24px #fff" not in styles


def test_user_work_status_is_a_small_human_facing_projection(tmp_path):
    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "状态投影测试"})
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, payload = request(base + f"/api/v1/works/{work['id']}/user-status")
        assert status == 200
        projection = payload["data"]
        assert projection["schema_version"] == "work-user-status/1.0"
        assert projection["primary_action"]["id"] == "start_idea"
        assert projection["primary_action"]["label"] == "开始写作想法"
        assert projection["counts"] == {
            "pending_decisions": 0,
            "blocking_issues": 0,
            "active_runs": 0,
            "failed_runs": 0,
            "drafted_scenes": 0,
            "total_scenes": 0,
        }
        conversation = work["conversation_threads"][0]
        service.post_conversation_message(
            work["id"], conversation["id"],
            {"expected_thread_version": conversation["version"], "text": "想写一张没有寄件人的车票。"},
        )
        status, discussed = request(base + f"/api/v1/works/{work['id']}/user-status")
        assert status == 200
        assert discussed["data"]["primary_action"] == {
            "id": "continue_idea",
            "label": "继续讨论",
            "detail": "想法已保存在对话中；信息足够时 Agent 会自动整理候选，你只需要采纳或退回。",
            "target": "agent",
        }
        serialized = json.dumps(projection, ensure_ascii=False)
        for internal in ("revision_id", "run_id", "content_hash", "provider", "schema_version="):
            assert internal not in serialized
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_confirmed_direction_takes_priority_over_old_conversation_overflow(tmp_path):
    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "长对话后的下一步"})
    brief = service.save_brief(
        work["id"], {"expected_version": work["version"], "idea": "废线上的车票", "mode": "bond_short"},
    )
    service.generate_blueprint(
        work["id"], {"expected_version": brief["work"]["version"]},
    )
    with service.repo.transaction() as connection:
        connection.execute(
            "UPDATE conversation_threads SET summary_json=? WHERE work_id=?",
            ('{"archived_message_count": 8}', work["id"]),
        )
    projection = service.get_user_work_status(work["id"])
    assert projection["primary_action"]["id"] == "build_structure"
    assert not any(item["kind"] == "organize" for item in projection["alerts"])


def test_user_work_status_routes_pending_proposals_to_their_user_surface(tmp_path):
    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "待审目标测试", "idea": "记录一条作品事实。"})
    thread = work["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"],
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "请记录事实：旧终端没有连接校内网络。",
        },
    )
    current_thread = next(
        item for item in discussed["work"]["conversation_threads"] if item["id"] == thread["id"]
    )
    proposed = service.propose_conversation_knowledge(
        work["id"],
        thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": current_thread["version"],
            "kind": "canon_fact",
        },
    )

    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, payload = request(base + f"/api/v1/works/{work['id']}/user-status")
        assert status == 200
        assert payload["data"]["primary_action"] == {
            "id": "review_knowledge",
            "label": "审查创作资料",
            "detail": "有 1 项资料候选等待你的决定。",
            "target": "library_suggestions",
        }

        proposal = next(
            item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"]
        )
        with service.repo.transaction() as connection:
            connection.execute(
                "UPDATE proposals SET status='rejected',decided_at=? WHERE id=?",
                (proposal["created_at"], proposal["id"]),
            )
            candidate_uri, candidate_hash = service.repo.atomic_write_text(
                "artifacts/proposals/user-status-scene.json",
                json.dumps({"blocks": []}, ensure_ascii=False) + "\n",
            )
            connection.execute(
                """INSERT INTO proposals
                   (id,work_id,kind,scope_type,scope_id,base_revision_id,candidate_uri,
                    candidate_hash,diff_json,evidence_json,risk,status,provider_json,
                    created_at,decided_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "proposal-user-status-scene", work["id"], "scene_script", "scene",
                    "scene-user-status", None, candidate_uri, candidate_hash, "{}", "{}",
                    "medium", "pending", "{}", proposal["created_at"], None,
                ),
            )

        status, payload = request(base + f"/api/v1/works/{work['id']}/user-status")
        assert status == 200
        assert payload["data"]["primary_action"] == {
            "id": "review_scene_candidate",
            "label": "审查正文候选",
            "detail": "有 1 项候选等待你的决定。",
            "target": "draft",
        }
        serialized = json.dumps(payload["data"], ensure_ascii=False)
        for internal in ("proposal-user-status-scene", "scene-user-status", "revision_id", "run_id", "content_hash", "provider"):
            assert internal not in serialized
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)


def test_activity_snapshot_is_small_and_keeps_only_background_state(tmp_path):
    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "活动快照"})

    snapshot = service.get_activity_snapshot(work["id"])

    assert snapshot["schema_version"] == "work-activity/1.0"
    assert snapshot["id"] == work["id"]
    assert snapshot["title"] == "活动快照"
    assert isinstance(snapshot["version"], int)
    assert set(snapshot) == {
        "schema_version",
        "id",
        "title",
        "version",
        "runs",
        "agent_runs",
        "proposals",
        "conversation_threads",
    }
    assert "artifacts" not in snapshot
    assert "messages" not in snapshot


def test_user_work_status_includes_transparent_deterministic_smart_insights(tmp_path):
    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "智能提醒测试"})
    thread = work["conversation_threads"][0]
    service.post_conversation_message(
        work["id"],
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "我想写一场雨夜车站里的重逢。",
        },
    )

    status = service.get_user_work_status(work["id"])
    insights = {item["id"]: item for item in status["smart_insights"]}

    assert "idea_ready" in insights
    assert "local_simulation" in insights
    assert insights["idea_ready"]["tone"] == "positive"
    assert "不会调用外部模型" in insights["local_simulation"]["detail"]
    assert all(set(item) >= {"id", "tone", "title", "detail"} for item in status["smart_insights"])


def test_user_work_status_ignores_historical_failures_after_later_success(tmp_path):
    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "历史失败不占首屏"})
    uri, digest = service.repo.atomic_write_text(
        "agent-runs/user-status-history/input.json", '{"instruction":"继续"}\n'
    )
    with service.repo.transaction() as connection:
        connection.execute(
            "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "agent-user-status-old-failure", work["id"], "work", work["id"], "继续",
                "failed", "{}", uri, digest, None, '{"code":"provider_timeout"}',
                "2026-08-22T00:00:00+00:00", "2026-08-22T00:00:01+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "agent-user-status-new-success", work["id"], "work", work["id"], "继续",
                "completed", "{}", uri, digest, None, None,
                "2026-08-22T00:01:00+00:00", "2026-08-22T00:01:01+00:00",
            ),
        )

    projection = service.get_user_work_status(work["id"])
    assert projection["counts"]["failed_runs"] == 0
    assert not any(item["kind"] == "recovery" for item in projection["alerts"])
    assert projection["primary_action"]["id"] != "recover_run"


def test_activity_surface_uses_compact_reads_and_opens_actionable_items_first():
    app = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf8")

    assert "`/api/v1/works/${encodeURIComponent(workId)}/activity`" in app
    assert "state.work={...state.work,...work.value}" in app
    assert "buckets.active.length?'active':buckets.attention.length?'attention'" in app
    assert "function smartWorkInsightsMarkup(status)" in app
    assert "基于当前作品状态" in app


def test_work_agent_uses_user_status_instead_of_internal_topline_labels():
    app = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    final_renderer = app[app.index("function renderFinalWorkAgentSurface()"):app.index("function renderFinalWorkAgentRail")]
    assert "works/${workId}/user-status" in app
    assert "当前下一步" in app
    assert "data-user-status-action" in app
    assert "workUserStatusMarkup()" in final_renderer
    assert "${statusMarkup}" in final_renderer
    assert "agent-runtime-bar" in final_renderer

def test_world_rule_list_labels_scope_and_category_separately():
    app = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert "function worldRuleScopeLabel(scope)" in app
    assert "场景范围" in app
    assert "function worldRuleCategoryLabel(category)" in app
    assert "通用规则" in app
    assert "worldRuleScopeLabel(rule.scope)" in app
    assert "worldRuleCategoryLabel(rule.category)" in app


def test_library_archive_actions_use_the_non_blocking_confirmation_dialog():
    web_root = Path(__file__).resolve().parents[1] / "web"
    app = (web_root / "app.js").read_text(encoding="utf-8")
    css = (web_root / "shell.css").read_text(encoding="utf-8")

    assert "function archiveConfirmationDialog()" in app
    assert "data-archive-confirm-accept" in app
    assert "requestArchiveConfirmation({title:`归档「${card?.name||'这张人物卡'}」？`" in app
    assert "acceptLabel:'归档作品事实'" in app
    assert "if(!confirm('归档后" not in app
    assert ".archive-confirmation-dialog" in css


def test_character_card_archive_has_a_versioned_restore_path():
    app = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    server = (Path(__file__).resolve().parents[1] / "src" / "halocue_writing" / "app.py").read_text(encoding="utf-8")

    assert "data-restore-card" in app
    assert "/character-cards/${button.dataset.restoreCard}/restore" in app
    assert 'parts[6] == "restore"' in server


def test_work_canon_archive_keeps_a_user_visible_restore_path():
    app = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert "library-archived-facts" in app
    assert "lifecycle.dataset.restoreCanonFact" in app
    assert "恢复作品事实" in app
    assert "status:'active'" in app


def test_revision_comparison_hides_internal_paths_and_raw_json():
    app = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert "function revisionDisplayEntries(value)" in app
    assert "function revisionValueMarkup(value)" in app
    assert '<code>${esc(change.path)}</code>' not in app
    assert "revision-value-details" in app
