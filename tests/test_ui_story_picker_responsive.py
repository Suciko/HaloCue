# -*- coding: utf-8 -*-
"""Real Chromium checks for the cross-device story picker."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import assetdb
import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright


HERE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app_url(tmp_path_factory):
    state = tmp_path_factory.mktemp("story-picker-state")
    stories = state / "stories"
    stories.mkdir()
    sample = stories / "story-picker-browser-sample.txt"
    sample.write_text("凯伊：浏览器测试", encoding="utf-8")
    aa_data = tmp_path_factory.mktemp("story-picker-aa") / "data"
    for name in ("projects", "saves", "overrides", "settings"):
        (aa_data / name).mkdir(parents=True)
    assetdb.connect(state / "aa_assets.db").close()
    install = state / "AzureArchive" / "App"
    executable = install / "AzureArchive.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"MZ")
    unity_data = install / "AzureArchive_Data"
    unity_data.mkdir()
    (unity_data / "app.info").write_text(
        "foxxlight\nAzureArchive\n", encoding="utf-8"
    )
    (state / "aa_config.json").write_text(
        json.dumps({
            "aa_executable": str(executable),
            "aa_data": str(aa_data),
        }),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["HALOCUE_USER_DATA_DIR"] = str(state)
    ready = state / "ready.json"
    log_path = state / "server.log"
    # Exercise the real server with an owned story root. Read its actual bound
    # port instead of racing a closed free-port reservation against startup.
    entry = "\n".join([
        "import sys, webui",
        "webui.STORY_ROOT = sys.argv[1]",
        "for name in ('STORY_FILE_PICKER', 'SETTINGS_FILE_PICKER', 'ASSET_FILE_PICKER'):",
        "    previous = getattr(webui, name)",
        "    setattr(webui, name, webui.StoryFilePicker(",
        "        roots=[sys.argv[1]], upload_dir=previous.upload_dir,",
        "        allowed_suffixes=previous.allowed_suffixes))",
        "webui.main(sys.argv[2:])",
    ])
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [
                sys.executable, "-c", entry, str(stories), "--no-browser", "--port", "0",
                "--ready-file", str(ready), "--aa-data", str(aa_data),
            ],
            cwd=HERE,
            stdout=log,
            stderr=log,
            env=environment,
        )
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(log_path.read_text(encoding="utf-8", errors="replace")[-4000:])
                if ready.is_file():
                    payload = json.loads(ready.read_text(encoding="utf-8"))
                    assert payload["host"] == "127.0.0.1"
                    assert 0 < payload["port"] < 65536
                    break
                time.sleep(0.1)
            else:
                detail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
                raise RuntimeError(f"webui.py did not publish readiness in 60s: {detail}")
            yield f"http://127.0.0.1:{payload['port']}"
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


def _open_picker(page, app_url, width):
    page.set_viewport_size({"width": width, "height": 820})
    page.goto(app_url, wait_until="networkidle")
    setup = page.request.get(app_url + "/api/setup/status").json()
    assert setup["aa"]["program"]["status"] == "recognized", setup
    page.get_by_role("button", name="选择文件").click()
    page.locator("#storyPickerHost").wait_for()


@pytest.mark.parametrize("width", [1200, 390])
def test_picker_opens_host_browser_directly_and_fits(browser, app_url, tmp_path, width):
    page = browser.new_page()
    try:
        _open_picker(page, app_url, width)
        shell = page.locator(".story-picker-shell").bounding_box()
        assert shell["x"] >= 0 and shell["x"] + shell["width"] <= width
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        assert page.locator("#storyPickerSource").count() == 0
        assert page.get_by_role("button", name="返回来源选择").count() == 0
        assert page.locator("#storyPickerHost").is_visible()
        page.screenshot(path=str(tmp_path / f"story-picker-host-direct-{width}.png"), full_page=True)
    finally:
        page.close()


@pytest.mark.parametrize("width", [1200, 390])
def test_host_browser_has_stable_rows_and_reachable_footer(browser, app_url, tmp_path, width):
    page = browser.new_page()
    errors = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        _open_picker(page, app_url, width)
        row = page.locator(".story-picker-entry", has_text="story-picker-browser-sample.txt")
        row.wait_for()
        page.screenshot(path=str(tmp_path / f"story-picker-host-{width}.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        assert row.bounding_box()["height"] >= 42
        row.click()
        assert page.locator("#storyPickerOpen").is_enabled()
        footer = page.locator(".story-picker-footer").bounding_box()
        assert footer["y"] >= 0 and footer["y"] + footer["height"] <= 820
        if width == 390:
            assert row.locator(".story-picker-entry-type").evaluate("el => getComputedStyle(el).display") == "none"
            assert row.locator(".story-picker-entry-modified").evaluate("el => getComputedStyle(el).display") == "none"
        else:
            assert row.locator(".story-picker-entry-type").is_visible()
            assert row.locator(".story-picker-entry-modified").is_visible()
    finally:
        page.close()
    assert errors == []


def test_host_selection_opens_story_through_the_real_browser(browser, app_url):
    page = browser.new_page(viewport={"width": 1200, "height": 820})
    errors = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(app_url, wait_until="networkidle")
        page.get_by_role("button", name="选择文件").click()
        row = page.locator(".story-picker-entry", has_text="story-picker-browser-sample.txt")
        row.wait_for()
        row.dblclick()
        page.locator("#storyContextName", has_text="story-picker-browser-sample.txt").wait_for()
        assert page.locator("#path").input_value() == "story-picker-browser-sample.txt"
        source_label = page.locator("#storyContextName").inner_text()
        assert source_label.split(" / ")[-1] == "story-picker-browser-sample.txt"
        assert "\\" not in source_label and ":" not in source_label
        assert page.locator("#mBrowse").is_hidden()
    finally:
        page.close()
    assert errors == []


@pytest.mark.parametrize("width", [1200, 390])
def test_settings_locks_root_scrollbar_but_keeps_drawer_scroll(browser, app_url, width):
    page = browser.new_page(viewport={"width": width, "height": 900})
    try:
        page.goto(app_url, wait_until="domcontentloaded")
        page.locator('[data-action="open-settings"]').click()
        page.locator("#settingsDrawer.open").wait_for()
        page.wait_for_timeout(100)
        assert page.locator("#settingsDrawer").evaluate("el => getComputedStyle(el).overflowY") == "auto"
        assert page.evaluate("getComputedStyle(document.documentElement).overflowY") == "hidden"
        assert page.evaluate("getComputedStyle(document.documentElement).scrollbarWidth") == "none"
        assert page.evaluate("getComputedStyle(document.body).scrollbarWidth") == "none"
    finally:
        page.close()


@pytest.mark.parametrize("width", [1280, 390])
def test_settings_drawer_open_state_stays_inside_viewport(browser, app_url, width):
    """The visible settings surface must remain reachable at desktop and mobile widths."""
    page = browser.new_page(viewport={"width": width, "height": 720})
    try:
        page.goto(app_url, wait_until="domcontentloaded")
        page.locator('[data-action="open-settings"]').click()
        drawer = page.locator("#settingsDrawer.open")
        drawer.wait_for()
        page.wait_for_timeout(300)
        box = drawer.bounding_box()
        assert box is not None
        assert box["x"] >= 0
        assert box["x"] + box["width"] <= width
        assert page.locator("#modelRoleOverview").bounding_box()["x"] >= 0
    finally:
        page.close()
