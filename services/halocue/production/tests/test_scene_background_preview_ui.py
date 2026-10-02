"""Scene cards carry resource keys, not resource-catalog preview flags."""

from __future__ import annotations

import base64
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import test_direction_profile_ui as fixtures
from test_direction_profile_ui import ProductionApiFixture, run_reply

profile_browser = fixtures.profile_browser
ui_url = fixtures.ui_url

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)


@pytest.mark.parametrize(
    "stage,root", [("mapping", "#mappingScenePlan"), ("generation", "#scenePlan")]
)
def test_scene_preview_uses_image_response_not_draft_flag(profile_browser, ui_url, stage, root):
    result = run_reply()
    cards = []
    for i, key in enumerate(["BG_Available", "BG_Missing", "BG_Black", None]):
        cards.append(
            {
                "card_id": f"scene-{i}",
                "kind": "scene",
                "line_no": i * 2 + 1,
                "current": {"title": f"Scene {i}"},
                "review_state": "pending",
            }
        )
        if key:
            cards.append(
                {
                    "card_id": f"bg-{i}",
                    "kind": "dir",
                    "line_no": i * 2 + 2,
                    "current": {"cmd": "bg", "arg": key},
                    "review_state": "pending",
                }
            )
    result["draft"]["cards"] = cards
    api = ProductionApiFixture(result)
    preview_requests = []
    errors = []

    def handle(route):
        path = urlsplit(route.request.url).path
        if path.endswith("/preview"):
            preview_requests.append(path)
            if "/BG_Available/" in path:
                route.fulfill(content_type="image/png", body=PNG)
            else:
                route.fulfill(status=404, json={"error": {"code": "resource_preview_not_found"}})
            return
        api.handle(route)

    context = profile_browser.new_context(viewport={"width": 1600, "height": 1200})
    try:
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/api/v1/**", handle)
        page.add_init_script("localStorage.setItem('halocue.currentRunId', 'run-synthetic');")
        page.goto(ui_url, wait_until="networkidle")
        page.locator(f'.stage-list [data-stage="{stage}"]').click()
        available = page.locator(f'{root} img[src*="/BG_Available/preview"]')
        expect(available).to_be_visible(timeout=4000)
        page.wait_for_function(
            "selector => { const img = document.querySelector(selector); return img?.complete && img.naturalWidth > 0; }",
            arg=f'{root} img[src*="/BG_Available/preview"]',
        )
        missing = page.locator(f"{root} .media-frame").filter(
            has=page.locator('img[src*="/BG_Missing/preview"]')
        )
        expect(missing.locator(".preview-placeholder")).to_have_text("图片暂不可用")
        expect(missing.locator("img")).to_be_hidden()
        expect(page.locator(root)).to_contain_text("黑屏")
        expect(page.locator(root)).to_contain_text("缺背景")
        assert not any("/BG_Black/" in path for path in preview_requests)
        status = page.locator("#mappingSceneStatus" if stage == "mapping" else "#scenePlanStatus")
        expect(status).not_to_contain_text("背景已齐")
        expect(status).to_contain_text("已指定 3/4")
        expect(status).to_contain_text("1 项预览不可用")
        expect(status).to_contain_text("1 项预览可用")
        expect(page.locator(root + ' [data-background-availability="unavailable"]')).to_contain_text("已指定 · 本机预览不可用")
        assert api.posts == []
        assert errors == []
    finally:
        context.close()

@pytest.mark.parametrize('failed', [True, False])
def test_persistent_preview_retains_error_or_shows_loaded_frame(profile_browser, ui_url, failed):
    result = run_reply(completed=True)
    result["draft"]["cards"] = [{"card_id": "line-preview", "kind": "line", "line_no": 1,
                                  "current": {"who": "旁白", "text": "已有台词仍然可读"},
                                  "review_state": "pending", "issues": []}]
    api = ProductionApiFixture(result)
    errors = []

    def handle(route):
        if urlsplit(route.request.url).path.endswith('/performance-preview'):
            if failed:
                route.fulfill(status=503, json={'ok': False, 'error': {'code': 'preview_unavailable', 'message': '预览服务暂不可用'}})
            else:
                route.fulfill(json={'frames': [{'card_id': result['draft']['cards'][0]['card_id'], 'title': '预览测试', 'text': '已有台词仍然可读', 'background_preview_available': False, 'annotations': []}]})
            return
        api.handle(route)

    context = profile_browser.new_context(viewport={'width': 1440, 'height': 1000})
    try:
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/api/v1/**', handle)
        page.add_init_script("localStorage.setItem('halocue.currentRunId', 'run-synthetic');")
        page.goto(ui_url, wait_until='networkidle')
        page.locator('.stage-list [data-stage="review"]').click()
        preview = page.locator('#persistentPerformancePreview')
        if failed:
            expect(preview).to_contain_text('无法读取草稿预览')
            expect(preview).to_contain_text('预览服务暂不可用')
            expect(preview).not_to_contain_text('选择一张卡片')
            expect(page.locator('#reviewPreviewPlay')).to_be_disabled()
        else:
            expect(preview).to_contain_text('已有台词仍然可读')
            expect(page.locator('#persistentPreviewCounter')).to_have_text('1 / 1')
        assert api.posts == []
        assert errors == []
    finally:
        context.close()
