# -*- coding: utf-8 -*-
"""真实 Chromium 下验证素材工作台断点、溢出和窄屏导航。"""

import base64
import io
import json
import socket
import subprocess
import sys
import time
import wave
from contextlib import closing
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


HERE = Path(__file__).resolve().parents[1]


def _free_port():
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def app_url():
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "webui.py", "--no-browser", "--port", str(port)],
        cwd=HERE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
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
    yield f"http://127.0.0.1:{port}"
    process.terminate()
    process.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


ASSETS = {
    "characters": [{
        "kind": "character", "aa_key": "custom_arona", "sha256": "char-digest",
        "name": "阿洛娜超长测试名称用于确认状态文字不会覆盖素材名称",
        "registered_in_current": False, "preview_available": True,
        "preview_token": "preview-character", "copies": [{"copy_token": "copy-character"}],
        "details": {"file_count": 4, "face_count": 7},
    }],
    "backgrounds": [{
        "kind": "background", "aa_key": "rain_roof", "sha256": "bg-digest",
        "name": "雨夜天台", "registered_in_current": False, "preview_available": True,
        "preview_token": "preview-background", "copies": [{"copy_token": "copy-background"}],
        "details": {"resolution": "1920x1080", "labels": {"place": "屋顶"}},
    }],
    "sounds": [{
        "kind": "sound", "aa_key": "door", "sha256": "sound-digest",
        "name": "开门声", "registered_in_current": False, "preview_available": True,
        "preview_token": "preview-sound", "copies": [{"copy_token": "copy-sound"}],
        "details": {"duration": 1.25, "codec": "wav"},
    }],
    "bgms": [],
}


def _open_workbench(page, app_url, width, tmp_path):
    page.set_viewport_size({"width": width, "height": 900})

    def route_api(route):
        path = route.request.url.split("/api/", 1)[-1].split("?", 1)[0]
        if path == "assets/library":
            body = ASSETS
        elif path == "stories/recent" or path == "drafts" or path == "backgrounds":
            body = []
        elif path == "llm/profiles":
            body = {"profiles": []}
        elif path == "setup/status":
            body = {"aa": {"connected": True}, "database": {"ready": True}, "model": {"configured": False}}
        elif path == "state":
            body = {"stats": {}}
        else:
            body = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))

    page.route("**/api/**", route_api)
    page.goto(app_url, wait_until="networkidle")
    page.evaluate("window.openAssetWorkbench({origin:'preflight',story_token:'story-1',asset_kind:'background',tasks:[{task_id:'background:雨夜天台:第 46 行',kind:'background',requested_name:'雨夜天台',source_location:{label:'第 46 行'},reason:'剧本引用但当前剧情未登记',candidate_keys:[]}]})")
    page.locator(".asset-workbench-row").first.wait_for()
    page.screenshot(path=str(tmp_path / f"asset-workbench-{width}.png"), full_page=True)


@pytest.mark.parametrize("width,columns", [(1200, 3), (900, 2), (680, 1), (470, 1), (390, 1)])
def test_asset_workbench_has_no_overflow_and_expected_columns(browser, app_url, tmp_path, width, columns):
    page = browser.new_page()
    try:
        _open_workbench(page, app_url, width, tmp_path)
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        assert page.locator("#assetWorkbenchBody").get_attribute("data-visible-columns") == str(columns)
        assert page.locator(".asset-workbench-filters input").evaluate("el => getComputedStyle(el).writingMode") == "horizontal-tb"
        assert page.locator(".asset-kind-segments button").first.evaluate("el => getComputedStyle(el).writingMode") == "horizontal-tb"
        row = page.locator(".asset-workbench-row").first
        name_box = row.locator(".asset-name").bounding_box()
        state_box = row.locator(".asset-state").bounding_box()
        assert name_box["y"] + name_box["height"] <= state_box["y"] + 1
    finally:
        page.close()


@pytest.mark.parametrize("width", [680, 470, 390])
def test_narrow_workbench_detail_return_and_tasks_remain_reachable(browser, app_url, tmp_path, width):
    page = browser.new_page()
    try:
        _open_workbench(page, app_url, width, tmp_path)
        page.locator(".asset-workbench-row").first.click()
        assert page.locator("#assetWorkbenchDetail").is_visible()
        page.locator("[data-workbench-action='back-catalog']").click()
        assert page.locator("#assetWorkbenchList").is_visible()
        page.locator("#assetWorkbenchTaskToggle").click()
        assert page.locator("#assetWorkbenchTasks").is_visible()
        assert "雨夜天台" in page.locator("#assetWorkbenchTasks").inner_text()
    finally:
        page.close()


def test_real_browser_workbench_preview_copy_face_flow_has_no_console_errors(browser, app_url, tmp_path):
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    errors = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(str(error)))
    phases = []
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    audio_buffer = io.BytesIO()
    with wave.open(audio_buffer, "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(8000)
        sound.writeframes(b"\x00\x00" * 800)

    def route_api(route):
        url = route.request.url
        path = url.split("/api/", 1)[-1].split("?", 1)[0]
        if path == "assets/library/preview":
            if "preview-sound" in url:
                route.fulfill(status=200, content_type="audio/wav", body=audio_buffer.getvalue())
            else:
                route.fulfill(status=200, content_type="image/png", body=png)
            return
        if path == "assets/library":
            body = ASSETS
        elif path == "assets/library/copy-to-story":
            body = {"ok": True, "state": "registered", "asset": {"kind": "background", "aa_key": "rain_roof"}}
        elif path == "assets/faces/job":
            body = {"running": False, "done": False, "ident": ""}
        elif path in {"stories/recent", "drafts", "backgrounds"}:
            body = []
        elif path == "llm/profiles":
            body = {"profiles": []}
        elif path == "setup/status":
            body = {"aa": {"connected": True}, "database": {"ready": True}, "model": {"configured": False}}
        elif path == "state":
            body = {"stats": {}}
        else:
            body = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))

    try:
        page.route("**/api/**", route_api)
        page.goto(app_url, wait_until="networkidle")
        page.evaluate("""window.__transferPhases=[];
          const setState=window.AssetWorkbench.transfer.setState.bind(window.AssetWorkbench.transfer);
          window.AssetWorkbench.transfer.setState=(state,options)=>{window.__transferPhases.push(state);return setState(state,options);};
          window.openAssetWorkbench({origin:'topbar',story_token:'story-1'});""")
        page.locator(".asset-workbench-row").first.wait_for()

        page.get_by_role("button", name="背景", exact=True).click()
        page.locator(".asset-workbench-row").click()
        image = page.locator(".asset-preview-image")
        image.wait_for()
        assert image.get_attribute("src").endswith("preview-background")
        assert image.evaluate("el => el.naturalWidth") == 1
        page.get_by_role("button", name="复制到当前剧情").click()
        page.wait_for_timeout(250)
        phases = page.evaluate("window.__transferPhases")
        assert "本章已登记" in phases

        page.get_by_role("button", name="音效", exact=True).click()
        page.locator(".asset-workbench-row").click()
        assert page.locator(".asset-preview-audio").get_attribute("src").endswith("preview-sound")

        page.get_by_role("button", name="骨骼", exact=True).click()
        page.locator(".asset-workbench-row").click()
        avatar = page.locator(".asset-preview-avatar")
        avatar.wait_for()
        assert avatar.evaluate("el => el.naturalWidth") == 1
        page.get_by_role("button", name="打开表情标注").click()
        assert page.locator("#faceWorkspace").get_attribute("aria-hidden") == "false"
        page.wait_for_timeout(250)
        face_box = page.locator("#faceWorkspace").bounding_box()
        assert face_box["x"] >= 0 and face_box["x"] + face_box["width"] <= 1200
        page.screenshot(path=str(tmp_path / "face-workspace-open.png"), full_page=True)
        page.locator("[data-face-action='close']").last.click()
        page.wait_for_timeout(250)
        assert page.locator("#assetWorkbench").is_visible()
        page.screenshot(path=str(tmp_path / "asset-workbench-flow.png"), full_page=True)
    finally:
        page.close()

    assert all(phase in phases for phase in ("正在校验", "正在复制", "正在登记", "本章已登记"))
    assert errors == []
@pytest.mark.parametrize("width", [1200, 390])
def test_visual_background_label_editor_is_reachable_without_overflow(
    browser, app_url, tmp_path, width
):
    """Background semantics must remain editable on desktop and the narrow workbench."""
    page = browser.new_page()
    try:
        _open_workbench(page, app_url, width, tmp_path)
        page.get_by_role("button", name="背景", exact=True).click()
        page.locator(".asset-workbench-row").click()
        editor = page.locator(".background-label-editor")
        editor.wait_for()
        fields = editor.locator("[data-background-label-field]")
        assert fields.count() == 9
        assert editor.locator("[data-background-label-field='place']").input_value() == "屋顶"
        assert editor.get_by_role("button", name="AI 识别场景", exact=True).is_visible()
        assert editor.get_by_role("button", name="保存标注", exact=True).is_visible()
        assert editor.evaluate("el => el.scrollWidth <= el.clientWidth")
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        page.screenshot(path=str(tmp_path / f"background-label-editor-{width}.png"), full_page=True)
    finally:
        page.close()
