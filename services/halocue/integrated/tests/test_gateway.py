from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
for source_root in (
    PROJECT_ROOT / "src",
    WORKSPACE_ROOT / "writing" / "src",
    WORKSPACE_ROOT / "production" / "src",
):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from halocue_integrated.gateway import route_request
from halocue_integrated.manifest import INTEGRATION_BUILD_ID, INTEGRATION_VERSION
from halocue_integrated.production_assets import IntegratedProductionService
from halocue_integrated.server import IntegratedRuntime
from halocue_production.config import Settings
from halocue_production.errors import ProductionError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def synthetic_resource_index(tmp_path: Path) -> Path:
    path = tmp_path / "synthetic-resources.json"
    path.write_text(
        json.dumps(
            {
                "bg": {"BG_Synthetic": "sha256:synthetic-background"},
                "sounds": ["SE_Synthetic"],
                "characters": [],
                "enums": {"emoticon": {}, "action": {}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_route_request_keeps_api_domains_separate():
    assert route_request("/api/v1/works") == ("writing", "/api/v1/works")
    assert route_request("/api/v1/works/work-1?detail=1") == (
        "writing",
        "/api/v1/works/work-1?detail=1",
    )
    assert route_request("/api/v1/workspaces", "http://127.0.0.1:8910/production/") == (
        "production",
        "/api/v1/workspaces",
    )
    assert route_request("/production/api/v1/health") == ("production", "/api/v1/health")
    assert route_request("/production/app.js") == ("production", "/app.js")
    assert route_request("/api/v1/health", "http://127.0.0.1:8910/production/") == (
        "production",
        "/api/v1/health",
    )


def test_integrated_runtime_serves_both_workbenches_and_apis(tmp_path):
    runtime = IntegratedRuntime(
        host="127.0.0.1",
        port=0,
        writing_data_dir=tmp_path / "writing",
        production_data_dir=tmp_path / "production",
        resource_index=synthetic_resource_index(tmp_path),
    )
    runtime.start_upstreams()
    gateway_thread = threading.Thread(target=runtime.gateway.serve_forever, daemon=True)
    gateway_thread.start()
    base = f"http://127.0.0.1:{runtime.port}"
    try:
        with urllib.request.urlopen(base + "/", timeout=5) as response:
            writing_html = response.read().decode("utf-8")
        no_redirect = urllib.request.build_opener(NoRedirect())
        redirect_results = []
        for path in ("/production", "/production/?run_id=run-1&work_id=work-1", "/production/index.html"):
            request = urllib.request.Request(base + path)
            try:
                no_redirect.open(request, timeout=5)
            except urllib.error.HTTPError as error:
                redirect_results.append((error.code, error.headers.get("Location")))
        fragment_request = urllib.request.Request(
            base + "/integration/production-fragment",
            headers={"X-HaloCue-Embed": "production"},
        )
        with urllib.request.urlopen(fragment_request, timeout=5) as response:
            production_fragment = response.read().decode("utf-8")
        unmarked_fragment_status = None
        try:
            urllib.request.urlopen(base + "/integration/production-fragment", timeout=5)
        except urllib.error.HTTPError as error:
            unmarked_fragment_status = error.code
        with urllib.request.urlopen(base + "/api/v1/health", timeout=5) as response:
            writing_health = response.read().decode("utf-8")
        with urllib.request.urlopen(base + "/production/api/v1/health", timeout=5) as response:
            production_health = response.read().decode("utf-8")
        with urllib.request.urlopen(base + "/production/app.js", timeout=5) as response:
            production_js = response.read().decode("utf-8")
        with urllib.request.urlopen(base + "/production/app-embedded.js", timeout=5) as response:
            embedded_production_js = response.read().decode("utf-8")
        with urllib.request.urlopen(base + "/integration-shell.js", timeout=5) as response:
            integration_shell_js = response.read().decode("utf-8")
        with urllib.request.urlopen(base + "/writing-workbench.js", timeout=5) as response:
            writing_workbench_js = response.read().decode("utf-8")
        with urllib.request.urlopen(base + "/production-embed.js", timeout=5) as response:
            production_embed_js = response.read().decode("utf-8")
        with urllib.request.urlopen(base + "/integration/manifest", timeout=5) as response:
            integration_manifest = json.loads(response.read().decode("utf-8"))
    finally:
        runtime.close()
        gateway_thread.join(timeout=3)

    assert "integration-shell.js" in writing_html
    assert "production-embed.js" in writing_html
    assert "production-embed.css" in writing_html
    assert 'class="halocue-integrated-production"' not in writing_html
    assert redirect_results == [
        (308, "/?section=production"),
        (308, "/?section=production&run_id=run-1&work_id=work-1"),
        (308, "/?section=production"),
    ]
    assert unmarked_fragment_status == 404
    assert 'class="stage-sidebar"' in production_fragment
    assert 'class="workspace"' in production_fragment
    assert "/integration/production-fragment" in production_embed_js
    assert '"X-HaloCue-Embed": "production"' in production_embed_js
    assert 'fetch("/production/"' not in production_embed_js
    assert "halocue-writing" in writing_health
    assert "halocue-production" in production_health
    assert 'const API_ROOT = "/production/api/v1";' in production_js
    assert 'const API_ROOT = "/production/api/v1";' in embedded_production_js
    assert 'const productionRoot = productionHost?.shadowRoot;' in embedded_production_js
    assert 'productionRoot.addEventListener("click"' in embedded_production_js
    assert 'document.addEventListener("click"' not in embedded_production_js
    assert "speaker_details || []" in embedded_production_js
    assert "item.speaker === speaker" in embedded_production_js
    assert "source_summary?.dialogue_count || 0" not in embedded_production_js
    assert 'productionNav.matches(\'.locked-nav,[aria-disabled="true"]\')' in integration_shell_js
    assert 'classList.contains("production-mode")' in integration_shell_js
    assert 'close?.({ section: destination })' in integration_shell_js
    assert 'waitFor(() => !document.body.classList.contains("app-loading"), 120)' in integration_shell_js
    assert "initialProductionNavigationCancelled" in integration_shell_js
    assert "window.HaloCueProductionEmbed.close();" not in integration_shell_js
    assert "close({ section: destination })" not in integration_shell_js
    assert 'if (section === "production" && !initialProductionNavigationCancelled)' in integration_shell_js
    assert 'section && !["works", "writing", "references", "tasks"].includes(section)' in integration_shell_js
    assert "The writing workbench owns its deep-link route" in integration_shell_js
    assert 'params.get("stage") === "release"' not in integration_shell_js
    assert "warmProductionSurface" in integration_shell_js
    assert "HaloCueProductionEmbed?.preload" in integration_shell_js
    assert 'event.target.closest(\'[data-section="production"]\')' in integration_shell_js
    assert '"requestIdleCallback" in window' in integration_shell_js
    assert "productionWarmup" in integration_shell_js
    assert "initialRequestedRoute.get('section') === 'production'" in writing_workbench_js
    assert writing_workbench_js.index("initialRequestedRoute.get('section') === 'production'") < writing_workbench_js.index(
        "await applyRouteFromLocation(initialRequestedRoute);"
    )
    assert "normalizeReleaseHash" in production_js
    assert "只有冻结后的 ScriptRelease 才能进入 AA 制作" in production_js
    assert "爱丽丝: 准备完成" not in production_js
    assert 'state.sourceMode = target;' in production_js
    assert 'state.upstreamRelease = null;' in production_js
    assert "HaloCueIntegrationDiagnostics" in integration_shell_js
    assert 'schema: "integration-diagnostics/1.0"' in integration_shell_js
    assert "documentIdentityStable" in integration_shell_js
    assert "shellIdentityStable" in integration_shell_js
    assert "navigationEntryCountStable" in integration_shell_js
    assert "productionUsesShadowRoot" in integration_shell_js
    assert "noBlankSamples" in integration_shell_js
    assert "integrationDocumentStable" in integration_shell_js
    assert "integrationNavigationStable" in integration_shell_js
    assert "integrationBlankSamples" in integration_shell_js
    manifest = integration_manifest["data"]
    assert manifest["schema"] == "integration-manifest/1.0"
    assert manifest["component"] == {"id": "halocue-integrated", "version": INTEGRATION_VERSION}
    assert manifest["build"] == {
        "id": INTEGRATION_BUILD_ID,
        "kind": "workspace_snapshot",
        "git_commit": None,
    }
    assert manifest["entrypoint"] == "/"
    assert manifest["workspaces"]["production"] == {
        "owner": "08-HaloCue-1.0",
        "surface": "#productionModule",
        "api_mount": "/production/api/v1/",
        "asset_prefix": "/production/",
    }
    assert manifest["navigation"] == {
        "mode": "same_document",
        "history": "push_state",
        "production_surface": "shadow_root",
    }


def test_script_release_crosses_the_real_writing_production_boundary(tmp_path):
    runtime = IntegratedRuntime(
        host="127.0.0.1",
        port=0,
        writing_data_dir=tmp_path / "writing",
        production_data_dir=tmp_path / "production",
        resource_index=synthetic_resource_index(tmp_path),
    )
    runtime.start_upstreams()
    try:
        writing = runtime.writing_service
        work = writing.create_work({"title": "集成交接测试"})
        brief = writing.save_brief(
            work["id"],
            {
                "expected_version": work["version"],
                "idea": "爱丽丝与凯伊调查深夜启动的旧机器",
                "mode": "bond_short",
                "characters": ["爱丽丝", "凯伊"],
            },
        )
        blueprint = writing.generate_blueprint(
            work["id"], {"expected_version": brief["work"]["version"]}
        )
        chapter = writing.create_chapter(
            work["id"],
            {"expected_version": blueprint["work"]["version"], "title": "第一章"},
        )
        scene = writing.create_scene(
            work["id"],
            chapter["chapter_id"],
            {
                "expected_version": chapter["work"]["version"],
                "title": "提示灯",
                "location": "游戏开发部活动室",
                "goal": "确认异常提示灯的来源",
            },
        )
        candidate = writing.generate_scene_candidate(
            work["id"],
            scene["scene_id"],
            {"expected_version": scene["work"]["version"]},
        )
        accepted = writing.accept_proposal(
            work["id"],
            candidate["proposal_id"],
            {"expected_version": candidate["work"]["version"]},
        )
        scene_review = writing.review_scene(
            work["id"],
            scene["scene_id"],
            {"expected_version": accepted["work"]["version"]},
        )
        memory_ready = writing.skip_scene_memory_maintenance(
            work["id"],
            scene["scene_id"],
            {
                "expected_version": scene_review["work"]["version"],
                "note": "集成交接夹具没有需要沉淀的长期事实。",
            },
        )
        continuity_review = writing.review_continuity(
            work["id"], {"expected_version": memory_ready["work"]["version"]}
        )
        release_review = writing.review_release(
            work["id"], {"expected_version": continuity_review["work"]["version"]}
        )
        frozen = writing.freeze_release(
            work["id"], {"expected_version": release_review["work"]["version"]}
        )
        handoff = writing.handoff_release(frozen["release_id"])
        production = runtime.production_service.run_detail(handoff["production_run_id"])
    finally:
        runtime.writing_server.shutdown()
        runtime.writing_server.server_close()
        runtime.production_server.shutdown()
        runtime.production_server.server_close()
        runtime.production_service.jobs.close()
        for thread in runtime._threads:
            thread.join(timeout=3)
        runtime.gateway.server_close()

    origin = production["run"]["source_summary"]["upstream_release"]
    assert origin["release_id"] == frozen["release_id"]
    assert origin["work_id"] == work["id"]
    assert origin["writing_pack_version"] == frozen["manifest"]["writing_pack_version"]
    assert production["run"]["release_id"] != frozen["release_id"]


def test_one_sentence_intent_reaches_production_without_bypassing_user_decisions(tmp_path):
    runtime = IntegratedRuntime(
        host="127.0.0.1",
        port=0,
        writing_data_dir=tmp_path / "writing",
        production_data_dir=tmp_path / "production",
        resource_index=synthetic_resource_index(tmp_path),
    )
    runtime.start_upstreams()
    try:
        writing = runtime.writing_service
        intent = writing.plan_intent(
            {
                "message": "我想写爱丽丝与凯伊在夜间活动室调查异常提示灯的短篇，先写第一幕。",
                "idempotency_key": "integrated-one-sentence-closed-loop",
            }
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            intent = writing.get_intent_plan(intent["plan_id"])
            if intent["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)

        assert intent["status"] == "waiting_user"
        work = writing.get_work(intent["work_id"])
        thread = next(
            item
            for item in work["conversation_threads"]
            if item["id"] == intent["thread_id"]
        )
        scene = next(
            item
            for chapter in work["chapters"]
            for item in chapter["scenes"]
            if item["id"] == intent["target"]["scene_id"]
        )
        assert scene["current_revision_id"] is None
        assert not [
            item
            for item in work["artifacts"]
            if item["kind"] in {"brief", "story_blueprint"}
            and item.get("current_revision_id")
        ]

        direction = writing.organize_conversation_proposal(
            work["id"],
            thread["id"],
            {
                "expected_version": work["version"],
                "expected_thread_version": thread["version"],
            },
        )
        direction_proposal = next(
            item
            for item in direction["work"]["proposals"]
            if item["id"] == direction["proposal_id"]
        )
        assert direction_proposal["kind"] == "brief_blueprint"
        assert direction_proposal["status"] == "pending"
        assert not [
            item
            for item in direction["work"]["artifacts"]
            if item["kind"] in {"brief", "story_blueprint"}
            and item.get("current_revision_id")
        ]

        direction_accepted = writing.accept_proposal(
            work["id"],
            direction["proposal_id"],
            {"expected_version": direction["work"]["version"]},
        )
        accepted_artifacts = {
            item["kind"]: item
            for item in direction_accepted["work"]["artifacts"]
            if item["kind"] in {"brief", "story_blueprint"}
        }
        assert accepted_artifacts["brief"]["current_revision_id"]
        assert accepted_artifacts["story_blueprint"]["current_revision_id"]

        scene_candidate = writing.generate_scene_candidate(
            work["id"],
            scene["id"],
            {"expected_version": direction_accepted["work"]["version"]},
        )
        pending_scene = next(
            item
            for item in scene_candidate["work"]["proposals"]
            if item["id"] == scene_candidate["proposal_id"]
        )
        unchanged_scene = next(
            item
            for chapter in scene_candidate["work"]["chapters"]
            for item in chapter["scenes"]
            if item["id"] == scene["id"]
        )
        assert pending_scene["kind"] == "scene_script"
        assert pending_scene["status"] == "pending"
        assert unchanged_scene["current_revision_id"] is None

        scene_accepted = writing.accept_proposal(
            work["id"],
            scene_candidate["proposal_id"],
            {"expected_version": scene_candidate["work"]["version"]},
        )
        assert scene_accepted["revision_id"]
        scene_review = writing.review_scene(
            work["id"],
            scene["id"],
            {"expected_version": scene_accepted["work"]["version"]},
        )
        assert scene_review["work"]["releases"] == []
        memory_ready = writing.skip_scene_memory_maintenance(
            work["id"],
            scene["id"],
            {
                "expected_version": scene_review["work"]["version"],
                "note": "集成闭环夹具没有需要沉淀的长期事实。",
            },
        )
        continuity = writing.review_continuity(
            work["id"], {"expected_version": memory_ready["work"]["version"]}
        )
        assert continuity["status"] == "passed"
        assert continuity["work"]["releases"] == []
        release_review = writing.review_release(
            work["id"], {"expected_version": continuity["work"]["version"]}
        )
        assert release_review["status"] == "passed"
        assert release_review["work"]["releases"] == []

        frozen = writing.freeze_release(
            work["id"], {"expected_version": release_review["work"]["version"]}
        )
        release_before_handoff = writing.get_release(frozen["release_id"])
        handoff = writing.handoff_release(frozen["release_id"])
        release_after_handoff = writing.get_release(frozen["release_id"])
        production = runtime.production_service.run_detail(handoff["production_run_id"])

        assert release_after_handoff["id"] == release_before_handoff["id"]
        assert release_after_handoff["content_hash"] == release_before_handoff["content_hash"]
        assert release_after_handoff["manifest"] == release_before_handoff["manifest"]
        assert release_after_handoff["text"] == release_before_handoff["text"]
        assert release_before_handoff["production_run_id"] is None
        assert release_after_handoff["production_run_id"] == handoff["production_run_id"]
        assert production["run"]["source_summary"]["upstream_release"]["release_id"] == frozen["release_id"]
        assert production["run"]["release_id"] != frozen["release_id"]
        assert writing.handoff_release(frozen["release_id"])["production_run_id"] == handoff["production_run_id"]

        # Continue through the production-owned review, deterministic compile,
        # install preflight, and install contracts in an isolated AA workspace.
        # The integration test must never write to the user's configured AA
        # data or mutate the frozen ScriptRelease.
        aa_data = tmp_path / "aa-data"
        for name in ("projects", "saves", "overrides", "settings"):
            (aa_data / name).mkdir(parents=True, exist_ok=True)
        configured = runtime.production_service.configure_aa_workspace({"path": str(aa_data)})
        assert configured["aa_workspace"]["valid"] is True

        run_id = handoff["production_run_id"]
        production = runtime.production_service.run_detail(run_id)
        for speaker in production["run"]["source_summary"]["speakers"]:
            production = runtime.production_service.update_cast(
                run_id,
                {
                    "speaker": speaker,
                    "mapping": {"kind": "narrator"},
                    "expected_draft_version": production["draft"]["draft_version"],
                },
            )
        production = runtime.production_service.approve_review(
            run_id,
            {
                "card_ids": None,
                "expected_draft_version": production["draft"]["draft_version"],
            },
        )
        assert production["gates"]["compile"] == {"passed": True, "blockers": []}

        status, compile_started = runtime.production_service.compile(
            run_id,
            {"expected_draft_version": production["draft"]["draft_version"]},
        )
        assert status == 202
        compile_job_id = compile_started["job"]["job_id"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            compile_job = runtime.production_service.job_detail(compile_job_id)["job"]
            if compile_job["state"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert compile_job["state"] == "succeeded", compile_job

        compiled = runtime.production_service.run_detail(run_id)
        build_id = compile_started["build_id"]
        assert compiled["run"]["state"] == "compiled"
        assert compiled["run"]["last_build_id"] == build_id
        build_bundle = compile_job["result"]["bundle"]
        assert Path(build_bundle["bundle_dir"]).is_relative_to(tmp_path / "production")

        target = {"build_id": build_id, "category": "集成验收", "story_name": "一句想法闭环"}
        install_check = runtime.production_service.check_install(run_id, target)
        assert install_check["target"]["available"] is True
        assert install_check["target"]["conflict"] is False

        installed = runtime.production_service.install(run_id, target)
        assert installed["run"]["state"] == "installed"
        assert Path(installed["install"]["aap_path"]).is_file()
        assert Path(installed["install"]["aap_path"]).is_relative_to(aa_data)
        assert runtime.production_service.check_install(run_id, target)["target"]["conflict"] is True
        with pytest.raises(ProductionError) as repeated_install:
            runtime.production_service.install(run_id, target)
        assert repeated_install.value.code == "build_not_installable"
        assert repeated_install.value.status == 409

        release_after_install = writing.get_release(frozen["release_id"])
        assert release_after_install["id"] == release_before_handoff["id"]
        assert release_after_install["content_hash"] == release_before_handoff["content_hash"]
        assert release_after_install["manifest"] == release_before_handoff["manifest"]
        assert release_after_install["text"] == release_before_handoff["text"]
    finally:
        runtime.writing_server.shutdown()
        runtime.writing_server.server_close()
        runtime.production_server.shutdown()
        runtime.production_server.server_close()
        runtime.production_service.jobs.close()
        for thread in runtime._threads:
            thread.join(timeout=3)
        runtime.gateway.server_close()


def test_scene_asset_handoff_creates_a_verified_production_run_receipt(tmp_path):
    runtime = IntegratedRuntime(
        host="127.0.0.1",
        port=0,
        writing_data_dir=tmp_path / "writing",
        production_data_dir=tmp_path / "production",
        resource_index=synthetic_resource_index(tmp_path),
    )
    runtime.start_upstreams()
    try:
        catalog = runtime.production_service.list_resources("backgrounds", limit=1)
        assert catalog["items"], "integration fixture requires one AA background"
        asset = catalog["items"][0]
        asset_id = asset["key"]
        asset_hash = str(asset["aa_hash"])

        writing = runtime.writing_service
        work = writing.create_work({"title": "素材交接集成测试"})
        brief = writing.save_brief(
            work["id"],
            {
                "expected_version": work["version"],
                "idea": "爱丽丝在走廊确认背景位置。",
                "mode": "bond_short",
                "characters": ["爱丽丝"],
            },
        )
        blueprint = writing.generate_blueprint(
            work["id"], {"expected_version": brief["work"]["version"]}
        )
        chapter = writing.create_chapter(
            work["id"],
            {"expected_version": blueprint["work"]["version"], "title": "第一章"},
        )
        scene = writing.create_scene(
            work["id"],
            chapter["chapter_id"],
            {
                "expected_version": chapter["work"]["version"],
                "title": "走廊",
                "location": "教学楼走廊",
                "goal": "确认背景",
            },
        )
        selected = writing.set_scene_asset_references(
            work["id"],
            scene["scene_id"],
            {
                "expected_version": scene["work"]["version"],
                "references": [
                    {
                        "asset_kind": "background",
                        "source_type": "resource_index",
                        "source_asset_id": asset_id,
                        "display_name": asset.get("name") or asset_id,
                        "source_version": "integration-catalog/1",
                        "content_hash": asset_hash,
                        "content_hash_kind": "aa_resource_hash",
                        "source_snapshot": {
                            "source": "resource_index",
                            "asset_id": asset_id,
                            "key": asset_id,
                            "name": asset.get("name") or asset_id,
                            "aa_hash": asset["aa_hash"],
                        },
                    }
                ],
            },
        )
        candidate = writing.generate_scene_candidate(
            work["id"], scene["scene_id"],
            {"expected_version": selected["work"]["version"]},
        )
        accepted = writing.accept_proposal(
            work["id"], candidate["proposal_id"],
            {"expected_version": candidate["work"]["version"]},
        )
        scene_review = writing.review_scene(
            work["id"], scene["scene_id"],
            {"expected_version": accepted["work"]["version"]},
        )
        memory_ready = writing.skip_scene_memory_maintenance(
            work["id"], scene["scene_id"],
            {
                "expected_version": scene_review["work"]["version"],
                "note": "集成夹具没有长期事实。",
            },
        )
        continuity = writing.review_continuity(
            work["id"], {"expected_version": memory_ready["work"]["version"]}
        )
        release_review = writing.review_release(
            work["id"], {"expected_version": continuity["work"]["version"]}
        )
        frozen = writing.freeze_release(
            work["id"], {"expected_version": release_review["work"]["version"]}
        )

        handoff = writing.handoff_release(frozen["release_id"])
        receipt = runtime.production_service.resource_usage(handoff["production_run_id"])
        reference = writing.get_work(work["id"])["chapters"][-1]["scenes"][0]["asset_references"][0]
    finally:
        runtime.writing_server.shutdown()
        runtime.writing_server.server_close()
        runtime.production_server.shutdown()
        runtime.production_server.server_close()
        runtime.production_service.jobs.close()
        for thread in runtime._threads:
            thread.join(timeout=3)
        runtime.gateway.server_close()

    assert runtime.production_service.capabilities()["scene_asset_handoff"]["state"] == "available"
    assert handoff["asset_handoff"]["status"] == "complete"
    assert receipt["schema_version"] == "production-asset-usage/1.0"
    assert receipt["references"][0]["source_asset_id"] == asset_id
    assert receipt["references"][0]["production_copy"]["copy_id"].startswith("copy-")
    assert reference["production_copy"] == receipt["references"][0]["production_copy"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("content_hash", "tampered-hash"),
        ("snapshot_asset_id", "library-asset-000000000002"),
        ("snapshot_sha256", "tampered-hash"),
        ("source_version", "2"),
    ],
)
def test_custom_asset_handoff_rejects_a_stale_or_tampered_frozen_reference(
    tmp_path, field, value
):
    service = IntegratedProductionService(
        Settings.from_env(host="127.0.0.1", port=0, data_dir=tmp_path / "production")
    )
    asset_id = "library-asset-000000000001"
    digest = "a" * 64
    service.custom_asset_detail = lambda _asset_id: {
        "asset": {
            "asset_id": asset_id,
            "kind": "background",
            "sha256": digest,
            "metadata_version": 1,
        }
    }
    reference = {
        "reference_id": "scene_asset_ref-1",
        "asset_kind": "background",
        "source_type": "custom_library",
        "source_asset_id": asset_id,
        "source_version": "1",
        "content_hash": digest,
        "content_hash_kind": "file_sha256",
        "source_snapshot": {
            "source": "custom_library",
            "asset_id": asset_id,
            "metadata_version": 1,
            "sha256": digest,
        },
        "production_copy": None,
    }
    if field == "snapshot_asset_id":
        reference["source_snapshot"]["asset_id"] = value
    elif field == "snapshot_sha256":
        reference["source_snapshot"]["sha256"] = value
    else:
        reference[field] = value

    try:
        with pytest.raises(ProductionError) as caught:
            service._validate_reference("scene-1", reference)
    finally:
        service.jobs.close()

    assert caught.value.code == "asset_handoff_source_mismatch"
    assert caught.value.status == 409
