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
CHROMIUM_UNSAFE_PORTS = {
    1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53,
    69, 77, 79, 87, 95, 101, 102, 103, 104, 109, 110, 111, 113, 115,
    117, 119, 123, 135, 137, 139, 143, 161, 179, 389, 427, 465, 512,
    513, 514, 515, 526, 530, 531, 532, 540, 548, 554, 556, 563, 587,
    601, 636, 989, 990, 993, 995, 1719, 1720, 1723, 2049, 3659, 4045,
    5060, 5061, 6000, 6566, 6665, 6666, 6667, 6668, 6669, 6697, 10080,
}


def _free_port():
    while True:
        with closing(socket.socket()) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port not in CHROMIUM_UNSAFE_PORTS:
            return port


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


@pytest.mark.parametrize("width,mode", [(1200, "local"), (390, "history")])
def test_unified_workbench_import_refreshes_and_keeps_layout_stable(browser, app_url, tmp_path, width, mode):
    page = browser.new_page(viewport={"width": width, "height": 820})
    errors, imported = [], {"done": False}

    def catalog():
        values = [ASSETS["backgrounds"][0]]
        if imported["done"]:
            values.append({
                "kind": "background", "aa_key": "new_rain", "sha256": "new-digest",
                "name": "新雨夜背景", "registered_in_current": True, "preview_available": False,
                "copies": [{"copy_token": "copy-new", "registered_at": "2026-08-07T08:00:00Z"}],
                "imported_at": "2026-08-07T08:00:00Z", "details": {"resolution": "1920x1080"},
            })
        return {"characters": [], "backgrounds": values, "sounds": [], "bgms": []}

    def route_api(route):
        path = route.request.url.split("/api/", 1)[-1].split("?", 1)[0]
        if path == "assets/library":
            body = catalog()
        elif path == "assets/host":
            body = {
                "location_token": "asset-root", "parent_token": "", "roots": [], "breadcrumbs": [],
                "entries": [{"entry_token": "entry-bg", "kind": "file", "name": "rain.png", "type": "PNG", "size": 42}],
            }
        elif path == "assets/select":
            body = {"file_token": "picked-bg", "name": "rain.png", "size": 42}
        elif path == "assets/validate":
            body = {"ok": True, "kind": "background", "aa_key": "new_rain", "sha256": "new-digest"}
        elif path == "assets/register":
            imported["done"] = True
            body = {"ok": True, "status": "registered", "kind": "background", "aa_key": "new_rain", "sha256": "new-digest"}
        elif path == "history/projects":
            body = [{"history_token": "history-1", "project": "旧剧情"}]
        elif path == "history/assets":
            body = [{"history_asset_token": "history-bg", "kind": "background", "name": "新雨夜背景", "aa_key": "new_rain", "sha256": "new-digest", "project": "旧剧情", "imported_at": "2026-08-07T08:00:00Z"}]
        elif path == "story/assets/copy":
            imported["done"] = True
            body = {"ok": True, "kind": "background", "aa_key": "new_rain", "sha256": "new-digest"}
        elif path == "story/assets":
            body = {"characters": [], "backgrounds": [], "sounds": [], "bgms": [], "counts": {}}
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
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/api/**", route_api)
        page.goto(app_url, wait_until="networkidle")
        page.evaluate("""window.StoryStore.set({story_token:'story-1',project:'当前剧情'});
          window.openAssetWorkbench({origin:'topbar',story_token:'story-1'});""")
        page.locator(".asset-workbench-row").first.wait_for()
        page.locator("[data-workbench-filter='sort']").select_option("name-asc")
        page.locator("#assetWorkbenchImport").click()
        dialog = page.locator("#assetImportDialog")
        dialog.wait_for(state="visible")
        dialog.get_by_role("button", name="背景", exact=True).click()
        if mode == "local":
            dialog.get_by_role("button", name="选择文件", exact=True).click()
            picker = dialog.locator("#assetImportFilePicker")
            picker.locator(".story-picker-entry", has_text="rain.png").click()
            picker.locator("[data-picker-role='open']").click()
            dialog.locator("#assetImportSubmit").click()
        else:
            dialog.get_by_role("button", name="从历史导入", exact=True).click()
            dialog.get_by_role("button", name="复制到当前剧情", exact=True).click()
        page.locator(".asset-workbench-row", has_text="新雨夜背景").wait_for()
        assert page.locator("[data-workbench-filter='sort']").input_value() == "name-asc"
        assert page.evaluate("window.AssetWorkbench.selected().aa_key") == "new_rain"
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        page.screenshot(path=str(tmp_path / f"asset-import-{mode}-{width}.png"), full_page=True)
    finally:
        page.close()

    assert errors == []


@pytest.mark.parametrize("width", [1200, 390])
def test_preflight_scene_chain_and_generation_prompt_fit_viewport(browser, app_url, tmp_path, width):
    page = browser.new_page(viewport={"width": width, "height": 760})
    errors = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route_api(route):
        path = route.request.url.split("/api/", 1)[-1].split("?", 1)[0]
        if path in {"stories/recent", "drafts", "backgrounds"}:
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
        assert page.locator("#s2, #s3").count() == 0
        assert page.locator("#s4 .num").inner_text() == "3"
        page.evaluate("""window.AppRuntime.renderPreflight({
          ai_status:'completed', usage_chain_status:'completed', characters:[], assets:[], issues:[],
          usage_chain:[{segment:'深夜抵达与初次会面',location:'基沃托斯郊外的雨夜车站候车厅',start:'第 1 行',end:'第 18 行',evidence:'雨水拍打玻璃，凯伊推开候车厅的门。',needs:[
            {kind:'background',name:'雨夜车站候车厅',status:'approximate',location:'第 1 行',reason:'官方背景库只有普通车站，缺少雨夜候车厅细节',confidence:.93,generation_prompt:'请生成一张用于剧情演出的日系二次元游戏背景图。\\n场景：基沃托斯郊外的雨夜车站候车厅。\\n横向 16:9，无人物、无文字、无水印。',candidates:[{aa_key:'BG_Station',label:'Station',confidence:.70,reason:'普通车站，缺少雨夜候车厅细节',preview_available:false}]},
            {kind:'bgm',name:'克制而略带不安的夜间氛围',status:'unsupported',location:'第 1 行',reason:'当前版本待验证',confidence:.68},
            {kind:'sound',name:'雨声与推门声',status:'missing',location:'第 2 行',reason:'正文包含明确的环境声和动作',confidence:.88}
          ]}]
        })""")
        workflow = page.locator(".usage-custom-background")
        assert workflow.evaluate("el => !el.open")
        workflow.locator("summary").click()
        assert workflow.evaluate("el => el.open")
        assert workflow.locator("[data-usage-action]").count() == 4
        page.screenshot(path=str(tmp_path / f"preflight-chain-workflow-{width}.png"), full_page=True)
        trigger = page.locator("[data-usage-action='generate-prompt']")
        trigger.click()
        dialog = page.locator("#mGenerationPrompt .box")
        dialog.wait_for(state="visible")
        page.screenshot(path=str(tmp_path / f"preflight-chain-prompt-{width}.png"), full_page=True)

        assert page.evaluate("document.documentElement.scrollWidth") <= width
        assert page.locator("#preflightScenePlan").evaluate("el => el.scrollWidth <= el.clientWidth")
        assert page.locator("#generationPromptText").evaluate("el => el.scrollWidth <= el.clientWidth")
        box = dialog.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= width
        assert "雨夜车站候车厅" in page.locator("#generationPromptText").input_value()
        assert errors == []
    finally:
        page.close()


@pytest.mark.parametrize("width", [1200, 390])
def test_story_asset_import_controls_fit_without_a_duplicate_type_selector(browser, app_url, tmp_path, width):
    page = browser.new_page(viewport={"width": width, "height": 760})

    def route_api(route):
        path = route.request.url.split("/api/", 1)[-1].split("?", 1)[0]
        if path in {"stories/recent", "drafts", "backgrounds"}:
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
        page.evaluate("""window.StoryStore.set({story_token:'story-1',project:'测试'});
          window.StoryAssets.items={characters:[],backgrounds:[],sounds:[],bgms:[],counts:{}};
          window.StoryAssets.filter='all';window.StoryAssets.render();""")
        controls = page.locator("#storyAssetStrip .asset-strip-controls")
        selector = controls.locator(".asset-import-kind")
        page.screenshot(path=str(tmp_path / f"story-asset-import-controls-{width}.png"), full_page=True)

        assert selector.count() == 0
        assert controls.locator(".asset-import-history").count() == 0
        assert controls.locator(".asset-import-local").count() == 0
        controls.get_by_role("button", name="背景", exact=True).click()
        assert controls.get_by_role("button", name="从历史导入背景", exact=True).is_visible()
        assert controls.get_by_role("button", name="从本地导入背景", exact=True).is_visible()
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        assert controls.evaluate("el => el.scrollWidth <= el.clientWidth")
        topbar_library = page.locator(".topbar-actions [data-library-action='open']")
        assert topbar_library.evaluate("""el => {const range=document.createRange();range.selectNodeContents(el);return range.getClientRects().length;}""") == 1
    finally:
        page.close()


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
