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
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
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
        path = parsed.path.removeprefix("/api/v1")
        if request.method == "POST":
            payload = request.post_data_json
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


def test_new_ai_import_defaults_to_conservative_and_submits_profile(profile_page):
    page, api = profile_page()
    page.locator('[data-source-tab="manual"]').click()
    page.locator("#projectName").fill("Synthetic production")
    page.locator("#scriptText").fill("Narrator: A synthetic scene.")
    page.locator('input[name="generationMode"][value="ai_direction"]').check()
    expect(page.get_by_label("新任务演出策略")).to_have_value("conservative")
    page.get_by_role("button", name="建立制作任务", exact=True).click()
    expect(page.locator("#page-mapping")).to_be_visible()
    assert api.posts[0][2]["direction_profile"] == "conservative"
    page.locator("#mappingContinue").click()
    expect(page.get_by_role("combobox", name="演出策略", exact=True)).to_have_value("conservative")


def test_older_adapter_disables_unsupported_strategy(profile_page):
    page, _api = profile_page(
        profiles={
            "default_new_project_ui": "standard",
            "items": [{"id": "standard"}],
        }
    )
    page.locator('input[name="generationMode"][value="ai_direction"]').check()
    expect(page.get_by_label("新任务演出策略")).to_have_value("standard")
    expect(
        page.locator('#sourceDirectionProfile option[value="conservative"]')
    ).to_have_js_property("disabled", True)


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
    selector = page.get_by_role("combobox", name="演出策略", exact=True)
    expect(selector).to_have_value(profile or "standard")
    selected = "standard" if profile == "conservative" else "conservative"
    selector.select_option(selected)
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
    page.get_by_role("combobox", name="演出策略", exact=True).select_option("conservative")
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
    page.get_by_role("combobox", name="演出策略", exact=True).select_option("conservative")
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
    page.get_by_role("combobox", name="演出策略", exact=True).select_option("conservative")
    page.locator("#openTasks").click()
    page.locator('#taskList [data-task-job-action="resume"]').click()
    expect(page.locator("#tasksDialog")).not_to_be_visible()
    expect(page.locator("#generateOrReview")).to_have_text("按新策略重新生成")
    assert api.posts == []


def test_unsubmitted_strategy_survives_same_run_refresh_but_not_reopening(profile_page):
    page, api = profile_page(run_reply("standard", job_state="paused"))
    selector = page.get_by_role("combobox", name="演出策略", exact=True)
    selector.select_option("conservative")
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
    selector = page.get_by_role("combobox", name="演出策略", exact=True)
    selector.select_option(profile)
    bounds = selector.bounding_box()
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
