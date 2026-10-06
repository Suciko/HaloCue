# ruff: noqa: F401, F811
"""Scene advice remains read-only until explicit candidate adoption."""

import base64
from urllib.parse import urlsplit, parse_qs

import pytest
from playwright.sync_api import expect
from test_direction_profile_ui import ProductionApiFixture, profile_browser, ui_url, run_reply


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)


def test_timeline_replace_uses_background_resolution_for_clicked_card(profile_browser, ui_url):
    result = run_reply(completed=True)
    result["draft"]["cards"] = [
        {"card_id": "line-1", "kind": "line", "line_no": 1,
         "current": {"who": "旁白", "text": "测试"}, "review_state": "pending"},
        {"card_id": "bg-2", "kind": "dir", "line_no": 2,
         "current": {"cmd": "bg", "arg": "BG_Old"}, "review_state": "pending"},
    ]
    api = ProductionApiFixture(result)
    writes = []

    def handle(route):
        path = urlsplit(route.request.url).path
        if route.request.method in {"POST", "PATCH"}:
            writes.append((route.request.method, path, route.request.post_data_json))
            result["draft"]["cards"][1]["current"]["arg"] = "BG_New"
            result["draft"]["draft_version"] = 2
            route.fulfill(json=result)
        elif path.endswith("/resources/backgrounds"):
            route.fulfill(json={"items": [{"key": "BG_New", "name": "新背景", "preview_available": True}],
                                "total": 1, "offset": 0, "has_more": False})
        elif path.endswith("/preview"):
            route.fulfill(content_type="image/png", body=PNG)
        else:
            api.handle(route)

    page = profile_browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.route("**/api/v1/**", handle)
        page.add_init_script("localStorage.setItem('halocue.currentRunId','run-synthetic')")
        page.goto(ui_url)
        page.locator('.stage-list [data-stage="review"]').click()
        page.locator('[data-background-replace="bg-2"]').click()
        page.locator('[data-resource-key="BG_New"]').click()
        expect(page.locator('[data-background-jump="bg-2"]')).to_contain_text("BG_New")
        assert writes == [("POST", "/api/v1/production-runs/run-synthetic/cards/bg-2/background-resolution",
                           {"action": "select", "background_key": "BG_New", "expected_draft_version": 1})]
    finally:
        page.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_scene_condition_sorting_and_conflict_cancel(profile_browser, ui_url, width):
    result = run_reply()
    result["draft"]["cards"] = [
        {
            "card_id": "scene-1",
            "kind": "scene",
            "line_no": 1,
            "current": {"title": "社团室 深夜"},
            "review_state": "pending",
        }
    ]
    api = ProductionApiFixture(result)
    queries = []

    def handle(route):
        parsed = urlsplit(route.request.url)
        if parsed.path.endswith("/resources/backgrounds"):
            query = parse_qs(parsed.query)
            queries.append(query)
            route.fulfill(
                json={
                    "items": [
                        {
                            "key": "BG_Day",
                            "name": "白天社团室",
                            "scene_match": {
                                "status": "conflict",
                                "matches": ["地点：社团室"],
                                "conflicts": ["时间冲突：需要夜间，素材标记为白天"],
                                "unknown": [],
                                "current": False,
                            },
                        }
                    ],
                    "total": 1,
                    "offset": 0,
                    "has_more": False,
                    "scene_context": {
                        "title": "社团室 深夜",
                        "requirements": {"time": "夜间", "place": "社团室"},
                        "sources": {"time": "场景标题", "place": "场景标题"},
                        "counts": {"match": 0, "unknown": 0, "conflict": 1},
                        "read_only": True,
                    },
                }
            )
        else:
            api.handle(route)

    page = profile_browser.new_page(viewport={"width": width, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.route("**/api/v1/**", handle)
        page.add_init_script("localStorage.setItem('halocue.currentRunId', 'run-synthetic');")
        page.goto(ui_url, wait_until="networkidle")
        page.locator('.stage-list [data-stage="mapping"]').click()
        page.locator("[data-mapping-scene-official]").click()
        expect(page.locator("#resourceSceneSummary")).to_contain_text("场景标题")
        assert queries[-1]["scene_card_id"] == ["scene-1"]
        assert queries[-1]["scope"] == ["library"]
        if not page.locator("#resourceTimeFilter").is_visible():
            page.get_by_text("更多筛选条件", exact=True).click()
        with page.expect_response(lambda r: "scene_time=%E7%99%BD%E5%A4%A9" in r.url):
            page.locator("#resourceTimeFilter").select_option("白天")
        assert queries[-1]["scene_time"] == ["白天"]
        assert "time" not in queries[-1], "Scene preference must not silently hide conflicts"
        with page.expect_response(lambda r: "scene_place=%E7%A4%BE%E5%9B%A2%E5%AE%A4" in r.url):
            page.locator("#resourceScenePlace").fill("社团室")
        assert queries[-1]["scene_place"] == ["社团室"]
        tile = page.locator('[data-resource-key="BG_Day"]')
        expect(tile).not_to_contain_text("时间冲突")
        expect(page.locator(".background-gallery-details .annotation-caution").first).not_to_be_visible()
        tile.click()
        expect(page.locator("#actionConfirmDialog")).to_be_visible()
        expect(page.locator("#actionConfirmBody")).to_contain_text("需要夜间")
        page.locator("#actionConfirmDialog").get_by_role("button", name="取消", exact=True).click()
        expect(page.locator("#resourceDialog")).to_be_visible()
        assert api.posts == []
        assert not errors
        assert page.locator("#resourceDialog").evaluate("e => e.scrollWidth <= e.clientWidth + 1")
    finally:
        page.close()



def test_background_picker_loads_unknown_preview_without_inventing_asset_name(profile_browser, ui_url):
    result = run_reply()
    result["draft"]["cards"] = [
        {
            "card_id": "scene-1",
            "kind": "scene",
            "line_no": 1,
            "current": {"title": "游戏开发部社团室 · 午后 · 室内"},
            "review_state": "pending",
        },
        {
            "card_id": "bg-1",
            "kind": "dir",
            "line_no": 2,
            "current": {"cmd": "bg", "arg": "BG_GameDevRoom"},
            "review_state": "pending",
        },
    ]
    api = ProductionApiFixture(result)

    def handle(route):
        path = urlsplit(route.request.url).path
        if path.endswith("/resources/backgrounds"):
            route.fulfill(
                json={
                    "items": [{"key": "BG_GameDevRoom", "name": "Game Dev Room"}],
                    "total": 1,
                    "offset": 0,
                    "has_more": False,
                    "scene_context": {"title": "游戏开发部社团室 · 午后 · 室内", "read_only": True},
                }
            )
        elif path.endswith("/preview"):
            route.fulfill(content_type="image/png", body=PNG)
        else:
            api.handle(route)

    context = profile_browser.new_context(viewport={"width": 1440, "height": 900})
    try:
        page = context.new_page()
        page.route("**/api/v1/**", handle)
        page.add_init_script("localStorage.setItem('halocue.currentRunId', 'run-synthetic');")
        page.goto(ui_url, wait_until="networkidle")
        page.locator('.stage-list [data-stage="mapping"]').click()
        page.locator("[data-mapping-scene-official]").click()
        tile = page.locator('[data-resource-key="BG_GameDevRoom"]')
        expect(tile.locator("img")).to_be_visible()
        expect(tile.locator("img")).to_have_js_property("naturalWidth", 1)
        expect(tile.locator("strong")).to_have_text("Game Dev Room")
        expect(tile.locator("strong")).not_to_have_text("游戏开发部社团室")
        expect(tile).not_to_contain_text("BG_GameDevRoom")
        details = page.locator(".background-gallery-details")
        expect(details.locator("code")).not_to_be_visible()
        details.locator("summary").click()
        expect(details.locator("code")).to_have_text("BG_GameDevRoom")
        assert api.posts == []
        details.locator("summary").click()
        expect(details.locator("code")).not_to_be_visible()
        expect(tile.locator(".preview-placeholder")).not_to_have_text("无预览")
        assert api.posts == []
    finally:
        context.close()


@pytest.mark.parametrize("fail_second", [False, True])
@pytest.mark.parametrize("width", [390, 1440])
def test_background_gallery_defaults_ready_and_scroll_loads_more(profile_browser, ui_url, fail_second, width):
    result = run_reply()
    result["draft"]["cards"] = [{"card_id": "scene-1", "kind": "scene", "line_no": 1, "current": {"title": "测试场景"}, "review_state": "pending"}]
    api = ProductionApiFixture(result)
    requests = []
    def handle(route):
        parsed = urlsplit(route.request.url)
        if parsed.path.endswith("/resources/backgrounds"):
            q = parse_qs(parsed.query)
            requests.append(q)
            offset = int(q.get("offset", [0])[0])
            if fail_second and offset == 80 and sum(x.get("offset") == ["80"] for x in requests) == 1:
                route.fulfill(status=503, json={"error": {"message": "测试加载失败"}})
                return
            items = [{"key": f"BG_{i}", "name": f"背景 {i}", "preview_available": True} for i in range(offset, min(offset + 80, 83))]
            route.fulfill(json={"items": items, "offset": offset, "total": 83, "has_more": offset == 0})
        elif parsed.path.endswith("/preview"):
            route.fulfill(content_type="image/png", body=PNG)
        else:
            api.handle(route)
    page = profile_browser.new_page(viewport={"width": width, "height": 900})
    try:
        page.route("**/api/v1/**", handle)
        page.add_init_script("localStorage.setItem('halocue.currentRunId','run-synthetic')")
        page.goto(ui_url)
        page.locator('.stage-list [data-stage="mapping"]').click()
        page.locator('[data-mapping-scene-official]').click()
        expect(page.locator('#resourceReadyFilter')).to_be_checked()
        expect(page.locator('.background-gallery-item')).to_have_count(80)
        assert requests[0]['ready'] == ['1']
        expect(page.locator('#resourceLoadMore')).not_to_be_visible()
        page.locator('.background-gallery-item').last.scroll_into_view_if_needed()
        page.locator('#resourceResults').evaluate("e => e.scrollTop = e.scrollHeight")
        if fail_second:
            expect(page.locator('#resourceLoadMore')).to_be_visible()
            expect(page.locator('#resourceLoadMore')).to_have_text('重试加载')
            assert len(requests) == 2
            page.locator('#resourceLoadMore').click()
        expect(page.locator('.background-gallery-item')).to_have_count(83)
        assert len(requests) == (3 if fail_second else 2)
        assert len(set(page.locator('[data-resource-key]').evaluate_all("els => els.map(e => e.dataset.resourceKey)"))) == 83
        expect(page.locator('#resourceLoadMore')).not_to_be_visible()
        assert api.posts == []
    finally:
        page.close()
