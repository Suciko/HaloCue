# -*- coding: utf-8 -*-
"""Real Chromium checks for the cross-device story picker."""

import socket
import os
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.browser


def _free_port():
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def app_url(tmp_path_factory, empty_llm_config_path):
    port = _free_port()
    story_root = tmp_path_factory.mktemp("story-picker-host")
    sample = story_root / "story-picker-browser-sample.txt"
    sample.write_text("凯伊：浏览器测试", encoding="utf-8")
    aa_data = tmp_path_factory.mktemp("story-picker-aa") / "data"
    for name in ("projects", "saves", "overrides", "settings"):
        (aa_data / name).mkdir(parents=True)
    runner = (
        "import sys; from pathlib import Path; import webui; "
        "from story_file_picker import StoryFilePicker; "
        "root=Path(sys.argv[1]); port=sys.argv[2]; aa_data=sys.argv[3]; "
        "webui.LLMCFG=sys.argv[4]; "
        "webui.STORY_FILE_PICKER=StoryFilePicker(roots=[root], "
        "upload_dir=root/'uploads'); "
        "sys.argv=['webui.py','--no-browser','--port',port,'--aa-data',aa_data]; "
        "webui.main()"
    )
    process = subprocess.Popen(
        [
            sys.executable, "-c", runner, str(story_root), str(port), str(aa_data),
            str(empty_llm_config_path),
        ],
        cwd=HERE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(process.stderr.read())
        with closing(socket.socket()) as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.1)
    else:
        process.terminate()
        raise RuntimeError("webui.py did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        process.wait(timeout=10)


def _open_picker(page, app_url, width):
    page.set_viewport_size({"width": width, "height": 820})
    page.goto(app_url, wait_until="networkidle")
    page.get_by_role("button", name="选择文件").click()
    page.locator("#storyPickerHost").wait_for()


def _console_error(message):
    location = message.location.get("url", "")
    return f"{message.text} [{location}]"


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
    page.on("console", lambda message: errors.append(_console_error(message)) if message.type == "error" else None)
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
    page.on("console", lambda message: errors.append(_console_error(message)) if message.type == "error" else None)
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
