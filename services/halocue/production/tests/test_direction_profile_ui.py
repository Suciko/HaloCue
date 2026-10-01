"""Production profile controls against the real page and synthetic HTTP replies.

Set HALOCUE_TEST_BROWSER_CHANNEL=msedge to use an installed Windows Edge.
"""

from __future__ import annotations

import copy
import functools
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from services.halocue._test_support import CHROMIUM_UNSAFE_PORTS


playwright_api = pytest.importorskip("playwright.sync_api")
expect = playwright_api.expect
UI_ROOT = Path(__file__).resolve().parents[1] / "ui"


class QuietStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if urlsplit(self.path).path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()


@pytest.fixture(scope="module")
def ui_url():
    handler = functools.partial(QuietStaticHandler, directory=str(UI_ROOT))
    for _ in range(100):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        if server.server_port not in CHROMIUM_UNSAFE_PORTS:
            break
        server.server_close()
    else:
        pytest.fail("Unable to bind a browser-safe localhost port")
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.fixture(scope="module")
def profile_browser():
    with playwright_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(
                headless=True,
                channel=os.environ.get("HALOCUE_TEST_BROWSER_CHANNEL") or None,
                args=[
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-gpu",
                ],
            )
        except playwright_api.Error as error:
            if "Executable doesn't exist" in str(error) or "not found" in str(error):
                pytest.skip("Install Chromium or select HALOCUE_TEST_BROWSER_CHANNEL.")
            raise
        try:
            yield browser
        finally:
            browser.close()


def run_reply(profile="standard", *, job_state=None, completed=False):
    run = {
        "run_id": "run-synthetic",
        "project": "Synthetic production",
        "state": "waiting_for_review",
        "source_summary": {
            "generation_mode": "ai_direction",
            "line_count": 1,
            "card_count": 1,
            "speakers": [],
        },
    }
    if profile is not None:
        run["source_summary"]["direction_profile"] = profile
    if completed:
        run["last_direction_generation_id"] = "generation-completed"
    result = {
        "run": run,
        "draft": {
            "draft_version": 1,
            "cards": [],
            "cast": {"cast": {}, "detected_speakers": []},
            "counts": {"total": 1, "pending": 1, "blocking_errors": 0},
            "review_ready": False,
        },
        "gates": {"compile": {"passed": False, "blockers": ["pending_review"]}},
        "active_job": None,
        "draft_direction_profile": {
            "id": profile or "standard",
            "generation_id": "generation-completed",
        }
        if completed
        else None,
    }
    if job_state:
        job = {
            "job_id": "job-original",
            "run_id": run["run_id"],
            "kind": "direction_generation",
            "state": job_state,
            "resumable": job_state in {"paused", "cancelled", "interrupted"},
            "can_pause": job_state == "running",
            "can_cancel": job_state in {"running", "paused"},
            "direction_profile": profile or "standard",
            "direction_profile_snapshot": {"id": profile or "standard", "version": "1.0"},
        }
        result["last_job"] = job
        if job_state == "running":
            result["active_job"] = job
            run["state"] = "generating_direction"
    return result


class ProductionApiFixture:
    def __init__(self, result=None):
        self.result = copy.deepcopy(result)
        self.posts = []
        self.profiles = {
            "default_new_project_ui": "conservative",
            "items": [{"id": "standard"}, {"id": "conservative"}],
        }

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path.removeprefix("/production").removeprefix("/api/v1")
        if request.method == "POST":
            payload = request.post_data_json
            if path == "/script-preflight":
                route.fulfill(
                    json={
                        "ok": True,
                        "kind": "static_preflight",
                        "format": {
                            "label": "角色台词格式",
                            "confidence": "medium",
                            "message": "已识别角色台词结构。",
                        },
                        "speakers": [
                            {"name": "Narrator", "count": 1, "sample": "A synthetic scene."}
                        ],
                        "scenes": [
                            {
                                "title": "未分段开场",
                                "line_no": 1,
                                "end_line": 1,
                                "implicit": True,
                                "speakers": [{"name": "Narrator", "count": 1}],
                                "dialogue_count": 1,
                                "directive_count": 0,
                                "has_background": False,
                                "background": "",
                            }
                        ],
                        "directives": {"total": 0, "recognized": 0, "issues": []},
                        "actions": [{"id": "create_run", "available": True}],
                    }
                )
                return
            self.posts.append((path, parsed.query, payload))
            if path == "/production-runs":
                self.result = run_reply(payload.get("direction_profile", "standard"))
                route.fulfill(json=self.result)
                return
            if path.endswith("/direction-generation") or path.startswith("/jobs/"):
                profile = payload.get("direction_profile", "standard")
                if path.startswith("/jobs/"):
                    profile = self.result["last_job"]["direction_profile"]
                self.result["run"]["source_summary"]["direction_profile"] = profile
                job = run_reply(profile, job_state="running")["active_job"]
                job["job_id"] = (
                    "job-new" if path.endswith("/direction-generation") else "job-original"
                )
                self.result["active_job"] = job
                self.result["last_job"] = job
                route.fulfill(json={"job": job, "direction_profile": profile})
                return
            route.fulfill(
                status=400, json={"ok": False, "error": {"code": "unexpected_test_write"}}
            )
            return
        if path == "/health":
            data = {"service": "halocue-production", "version": "test"}
        elif path == "/capabilities":
            data = {
                "capabilities": {
                    "generation_modes": {"ai_direction": {"state": "available"}},
                    "direction_profiles": self.profiles,
                }
            }
        elif path == "/settings/direction-model":
            data = {"model": {"configured": True}}
        elif path == "/production-runs":
            data = {"items": [self.result["run"]] if self.result else []}
        elif path == "/production-runs/run-synthetic":
            data = self.result
        elif path.startswith("/jobs/"):
            data = {"job": self.result.get("active_job") or self.result["last_job"]}
        elif path == "/jobs":
            data = {
                "items": [self.result["last_job"]]
                if self.result and self.result.get("last_job")
                else []
            }
        elif path.endswith("/preflight-summary"):
            data = {"speakers": [], "requests": [], "diagnostics": []}
        else:
            data = {"items": [], "data": []}
        route.fulfill(json=data)


@pytest.fixture
def profile_page(profile_browser, ui_url):
    context = profile_browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.set_default_timeout(15000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console", lambda message: errors.append(message.text) if message.type == "error" else None
    )

    def open_page(result=None, *, profiles=None):
        api = ProductionApiFixture(result)
        if profiles is not None:
            api.profiles = profiles
        page.route("**/api/v1/**", api.handle)
        if result:
            page.add_init_script("localStorage.setItem('halocue.currentRunId', 'run-synthetic');")
        page.goto(ui_url, wait_until="networkidle")
        expect(page.locator("#serviceState")).to_contain_text("halocue-production")
        return page, api

    yield open_page
    context.close()
    assert errors == []


def confirm_source_scene_judgement(page):
    page.locator("#preflightSource").click()
    expect(page.locator("#confirmSceneJudgement")).to_be_visible()
    page.locator("#confirmSceneJudgement").click()
    expect(page.locator("#draftGenerationDecision")).to_be_visible()


def test_scene_judgement_must_be_confirmed_and_becomes_stale_after_edit(profile_page):
    page, api = profile_page()
    page.locator('[data-source-tab="manual"]').click()
    page.locator("#projectName").fill("Scene judgement gate")
    page.locator("#scriptText").fill("Narrator: Before the scene.\n## Platform\nNarrator: Ready.")
    expect(page.locator("#draftGenerationDecision")).to_be_hidden()
    expect(page.locator("#createRunAfterPreflight")).to_be_hidden()

    page.locator("#preflightSource").click()
    expect(page.locator("#confirmSceneJudgement")).to_be_visible()
    expect(page.locator("#draftGenerationDecision")).to_be_hidden()
    assert api.posts == []

    page.locator("#confirmSceneJudgement").click()
    expect(page.locator("#draftGenerationDecision")).to_be_visible()
    page.locator("#scriptText").fill("Narrator: Changed after confirmation.")
    expect(page.locator("#sourcePreflight")).to_be_hidden()
    expect(page.locator("#draftGenerationDecision")).to_be_hidden()
    expect(page.locator("#sourceStatus")).to_contain_text("重新识别分场")
    assert api.posts == []


def test_new_ai_import_defaults_to_conservative_and_submits_profile(profile_page):
    page, api = profile_page()
    page.locator('[data-source-tab="manual"]').click()
    page.locator("#projectName").fill("Synthetic production")
    page.locator("#scriptText").fill("Narrator: A synthetic scene.")
    confirm_source_scene_judgement(page)
    page.locator('input[name="generationMode"][value="ai_direction"]').check()
    expect(
        page.locator('input[name="sourceDirectionProfileChoice"][value="conservative"]')
    ).to_be_checked()
    page.get_by_role("button", name="创建 AA 制作任务", exact=True).click()
    expect(page.locator("#page-mapping")).to_be_visible()
    assert api.posts[0][2]["direction_profile"] == "conservative"
    page.locator("#mappingContinue").click()
    expect(
        page.locator('input[name="directionProfileChoice"][value="conservative"]')
    ).to_be_checked()


def test_older_adapter_disables_unsupported_strategy(profile_page):
    page, _api = profile_page(
        profiles={
            "default_new_project_ui": "standard",
            "items": [{"id": "standard"}],
        }
    )
    page.locator('[data-source-tab="manual"]').click()
    page.locator("#projectName").fill("Synthetic production")
    page.locator("#scriptText").fill("Narrator: A synthetic scene.")
    confirm_source_scene_judgement(page)
    page.locator('input[name="generationMode"][value="ai_direction"]').check()
    expect(
        page.locator('input[name="sourceDirectionProfileChoice"][value="standard"]')
    ).to_be_checked()
    expect(
        page.locator('#sourceDirectionProfile option[value="conservative"]')
    ).to_have_js_property("disabled", True)
    expect(
        page.locator('input[name="sourceDirectionProfileChoice"][value="conservative"]')
    ).to_be_disabled()
    expect(
        page.locator('input[name="sourceDirectionProfileChoice"][value="standard"]')
    ).to_be_enabled()


def test_embedded_workbench_loads_the_same_profile_styles():
    script = (UI_ROOT.parents[1] / "writing" / "web" / "production-embed.js").read_text(
        encoding="utf-8"
    )
    assert '"/production/direction-profile.css"' in script


@pytest.mark.parametrize("profile", [None, "standard", "conservative"])
def test_restored_profile_can_start_selected_strategy_and_locks_while_running(
    profile_page, profile
):
    page, api = profile_page(run_reply(profile))
    selector = page.locator("#directionProfile")
    expect(selector).to_have_value(profile or "standard")
    selected = "standard" if profile == "conservative" else "conservative"
    page.locator(f'input[name="directionProfileChoice"][value="{selected}"]').check()
    page.locator("#generateOrReview").click()
    expect(page.locator("#generationJobState")).to_have_text("正在执行")
    assert api.posts == [
        (
            "/production-runs/run-synthetic/direction-generation",
            "",
            {
                "expected_draft_version": 1,
                "story_type": "auto",
                "layout_mode": "ai",
                "direction_profile": selected,
            },
        )
    ]
    expect(selector).to_be_disabled()
    expect(selector).to_have_value(selected)


@pytest.mark.parametrize("job_state", ["paused", "cancelled", "interrupted"])
def test_changed_profile_requires_confirmed_new_generation_not_resume(profile_page, job_state):
    page, api = profile_page(run_reply("standard", job_state=job_state))
    page.locator('input[name="directionProfileChoice"][value="conservative"]').check()
    expect(page.locator("#resumeGeneration")).to_be_hidden()
    page.locator("#generateOrReview").click()
    expect(page.locator("#actionConfirmDialog")).to_be_visible()
    expect(page.locator("#actionConfirmBody")).to_contain_text("简洁（保守）")
    assert api.posts == []
    page.locator("#actionConfirmDialog").get_by_role("button", name="取消", exact=True).click()
    expect(page.locator("#actionConfirmDialog")).not_to_be_visible()
    assert api.posts == []
    page.locator("#generateOrReview").click()
    page.locator("#actionConfirmAccept").click()
    expect(page.locator("#generationJobState")).to_have_text("正在执行")
    assert len(api.posts) == 1
    assert api.posts[0][0].endswith("/direction-generation")
    assert api.posts[0][2]["direction_profile"] == "conservative"


@pytest.mark.parametrize("job_state", ["paused", "cancelled", "interrupted"])
def test_unchanged_profile_continues_original_job(profile_page, job_state):
    page, api = profile_page(run_reply("conservative", job_state=job_state))
    page.locator("#generateOrReview").click()
    expect(page.locator("#generationJobState")).to_have_text("正在执行")
    assert api.posts == [("/jobs/job-original", "action=resume", {})]


def test_completed_generation_can_be_regenerated_only_after_confirmation(profile_page):
    page, api = profile_page(run_reply("standard", job_state="succeeded", completed=True))
    page.locator('.stage-list [data-stage="generation"]').click()
    page.locator('input[name="directionProfileChoice"][value="conservative"]').check()
    page.locator("#regenerateDirection").click()
    expect(page.locator("#actionConfirmDialog")).to_be_visible()
    assert api.posts == []
    page.locator("#actionConfirmAccept").click()
    expect(page.locator("#generationJobState")).to_have_text("正在执行")
    assert len(api.posts) == 1
    assert api.posts[0][0].endswith("/direction-generation")
    assert api.posts[0][2]["direction_profile"] == "conservative"
    expect(page.locator("#compileButton")).to_be_disabled()


def test_task_list_cannot_resume_old_strategy_after_user_selects_another(profile_page):
    page, api = profile_page(run_reply("standard", job_state="paused"))
    page.locator('input[name="directionProfileChoice"][value="conservative"]').check()
    page.locator("#openTasks").click()
    page.locator('#taskList [data-task-job-action="resume"]').click()
    expect(page.locator("#tasksDialog")).not_to_be_visible()
    expect(page.locator("#generateOrReview")).to_have_text("按新策略重新生成")
    assert api.posts == []


def test_unsubmitted_strategy_survives_same_run_refresh_but_not_reopening(profile_page):
    page, api = profile_page(run_reply("standard", job_state="paused"))
    selector = page.locator("#directionProfile")
    page.locator('input[name="directionProfileChoice"][value="conservative"]').check()
    page.locator("#refreshRun").click()
    expect(selector).to_have_value("conservative")
    page.reload(wait_until="networkidle")
    expect(selector).to_have_value("standard")
    assert api.posts == []


@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("profile", ["standard", "conservative"])
def test_profile_controls_and_confirmation_fit_desktop_and_mobile(
    profile_page, tmp_path, width, profile
):
    page, api = profile_page(run_reply("standard", job_state="succeeded", completed=True))
    page.set_viewport_size({"width": width, "height": 900})
    page.locator('.stage-list [data-stage="generation"]').click()
    page.locator(f'input[name="directionProfileChoice"][value="{profile}"]').check()
    bounds = page.locator("#directionProfileControl .profile-choice-grid").bounding_box()
    assert bounds and 0 <= bounds["x"] and bounds["x"] + bounds["width"] <= width
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshots = Path(os.environ.get("HALOCUE_TEST_SCREENSHOT_DIR") or tmp_path)
    screenshots.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshots / f"direction-{profile}-{width}.png"), full_page=True)
    page.locator("#regenerateDirection").click()
    expect(page.locator("#actionConfirmDialog")).to_be_visible()
    bounds = page.locator("#actionConfirmDialog").bounding_box()
    assert bounds and 0 <= bounds["x"] and bounds["x"] + bounds["width"] <= width
    page.screenshot(
        path=str(screenshots / f"direction-confirm-{profile}-{width}.png"), full_page=True
    )
    assert api.posts == []
    page.locator("#actionConfirmDialog").get_by_role("button", name="取消", exact=True).click()


def test_current_chunk_does_not_claim_generation_is_complete(profile_page):
    result = run_reply("conservative", job_state="running")
    result["active_job"]["progress"] = {
        "phase": "annotating",
        "current": 1,
        "total": 1,
        "percent": 100,
        "detail": "正在标注",
    }
    page, api = profile_page(result)
    page.locator('.stage-list [data-stage="generation"]').click()
    progress = page.locator("#generationProgress")
    expect(progress).not_to_have_attribute("aria-valuenow", "100")
    expect(progress).to_have_attribute("aria-valuetext", "正在处理，完成比例尚未确定")
    expect(page.locator("#generationJobDetail")).to_contain_text("非完成比例")
    assert page.locator("#generationProgressBar").evaluate(
        "e => e.getBoundingClientRect().width > 0"
    )
    page.locator("#openTasks").click()
    expect(page.locator("#taskList progress")).not_to_have_attribute("value", "100")
    assert api.posts == []


@pytest.mark.parametrize("width", [390, 1280])
def test_failed_generation_shows_reason_without_progress_or_duplicate_resume(profile_page, width):
    result = run_reply("conservative", job_state="failed")
    job = result["last_job"]
    job.update(
        resumable=True,
        progress={
            "phase": "annotating",
            "current": 1,
            "total": 2,
            "percent": 50,
            "detail": "正在标注第 1/2 个场景块",
        },
        error={
            "code": "direction_generation_failed",
            "message": "structured_output_invalid: schema 不允许的字段",
        },
    )
    page, api = profile_page(result)
    page.set_viewport_size({"width": width, "height": 900})
    page.locator('.stage-list [data-stage="generation"]').click()
    expect(page.locator("#generationJobDetail")).to_contain_text("本次生成已停止")
    expect(page.locator("#generationJobGuidance")).to_contain_text("当前草稿保留")
    expect(page.locator("#generationProgress")).to_be_hidden()
    expect(page.locator("#generationMetrics")).to_be_hidden()
    expect(page.locator("#resumeGeneration")).to_be_hidden()
    expect(page.locator("#generateOrReview")).to_have_text("继续生成")
    page.locator(".generation-diagnostics > summary").click()
    expect(page.locator("#generationMetrics")).to_be_visible()
    expect(page.locator("#generationMetrics")).to_contain_text("暂无用量数据")
    expect(page.locator("#generationMetrics")).not_to_contain_text("尚未上报")
    page.locator(".generation-log > summary").click()
    expect(page.locator("#generationLog")).to_contain_text("schema 不允许的字段")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert api.posts == []


def test_layout_mode_names_make_ai_backend_boundary_explicit():
    html = (UI_ROOT / "index.html").read_text(encoding="utf-8")
    styles = (UI_ROOT / "direction-profile.css").read_text(encoding="utf-8")
    assert "执行方式" in html
    assert "协同 AI" in html
    assert "AI 判断演出意图，后端修正站位与连续性" in html
    assert "决定谁负责安排镜头与连续性" in html
    assert ".layout-mode-fieldset legend small" in styles


def test_strategy_cards_distinguish_current_and_next_without_writes(profile_page):
    page, api = profile_page(run_reply("standard", job_state="succeeded", completed=True))
    page.locator('.stage-list [data-stage="generation"]').click()
    status = page.locator("#directionProfileStatus")
    expect(status).to_contain_text("当前草稿来源")
    expect(status).to_contain_text("标准")
    page.locator('input[name="directionProfileChoice"][value="conservative"]').check()
    expect(status).to_contain_text("简洁 · 尚未应用")
    expect(status.locator(".profile-status-row").first).to_contain_text("标准")
    expect(page.locator("#directionProfileControl .profile-boundary-note")).to_contain_text(
        "现有草稿不变"
    )
    assert api.posts == []


def test_keyboard_radios_and_reduced_motion(profile_page):
    page, api = profile_page(run_reply("standard"))
    standard = page.locator('input[name="directionProfileChoice"][value="standard"]')
    conservative = page.locator('input[name="directionProfileChoice"][value="conservative"]')
    standard.focus()
    standard.press("ArrowLeft")
    expect(conservative).to_be_checked()
    expect(conservative).to_be_focused()
    assert page.locator("#directionProfileControl").get_attribute("data-input-method") == "keyboard"
    page.emulate_media(reduced_motion="reduce")
    duration = page.locator("#directionProfileControl .profile-choice-check").first.evaluate(
        "e=>getComputedStyle(e).transitionDuration"
    )
    assert duration == "0s"
    assert api.posts == []


def test_failed_attempt_does_not_relabel_existing_draft(profile_page):
    result = run_reply("standard", job_state="failed", completed=True)
    result["draft_direction_profile"] = {"id": "conservative", "generation_id": "previous-success"}
    page, api = profile_page(result)
    expect(page.locator("#directionProfileStatus .profile-status-row").first).to_contain_text(
        "简洁"
    )
    expect(page.locator("#directionProfileStatus")).to_contain_text("标准 · 尚未应用")
    assert api.posts == []


def test_running_strategy_is_locked_and_described(profile_page):
    page, api = profile_page(run_reply("conservative", job_state="running"))
    expect(page.locator("#directionProfileLock")).to_have_text("本次策略已锁定")
    expect(page.locator("#directionProfileStatus")).to_contain_text("正在生成")
    for value in ("conservative", "standard"):
        expect(
            page.locator(f'input[name="directionProfileChoice"][value="{value}"]')
        ).to_be_disabled()
    assert api.posts == []


def test_pointer_transition_is_real_and_keeps_layout_stable(profile_page):
    page, api = profile_page(run_reply("standard", completed=True))
    page.locator('.stage-list [data-stage="generation"]').click()
    root = page.locator("#directionProfileControl")
    root.scroll_into_view_if_needed()
    before = root.bounding_box()
    page.locator('input[name="directionProfileChoice"][value="conservative"]').click()
    after = root.bounding_box()
    assert abs(before["height"] - after["height"]) < 1
    assert root.get_attribute("data-input-method") == "pointer"
    transition = root.locator(".profile-choice-check").first.evaluate(
        "e=>getComputedStyle(e).transitionDuration"
    )
    assert "0.18s" in transition
    expect(root.locator('input[value="conservative"]')).to_be_checked()
    assert api.posts == []


def test_quick_strategy_switch_keeps_last_selection_without_generation(profile_page):
    page, api = profile_page(run_reply("standard", completed=True))
    page.locator('.stage-list [data-stage="generation"]').click()
    for value in ("conservative", "standard", "conservative"):
        page.locator(f'input[name="directionProfileChoice"][value="{value}"]').click()
    expect(page.locator("#directionProfile")).to_have_value("conservative")
    expect(page.locator("#directionProfileStatus")).to_contain_text("简洁 · 尚未应用")
    expect(page.locator("#directionProfileStatus .profile-status-row").first).to_contain_text(
        "标准"
    )
    assert api.posts == []
