# ruff: noqa: F401, F811
"""Browser coverage for frozen resource annotations (synthetic replies)."""

from urllib.parse import urlsplit

import pytest
from test_direction_profile_ui import ProductionApiFixture, profile_browser, ui_url, run_reply
from playwright.sync_api import expect


@pytest.mark.parametrize("width", [1440, 390])
def test_face_annotation_changes_without_saving_or_injection(profile_browser, ui_url, width):
    result = run_reply(completed=True)
    result["draft"]["cast"] = {
        "cast": {"角色": {"kind": "portrait", "id": "actor", "name": "角色"}}
    }
    result["draft"]["cards"] = [
        {
            "card_id": "line-1",
            "kind": "line",
            "line_no": 1,
            "current": {"who": "角色", "text": "我才没有。", "face": "01"},
            "review_state": "pending",
        }
    ]
    api = ProductionApiFixture(result)
    errors = []

    def handle(route):
        if urlsplit(route.request.url).path.endswith("/resources/characters/actor"):
            route.fulfill(
                json={
                    "frozen": True,
                    "character": {
                        "name": "角色",
                        "faces": [
                            {
                                "id": "01",
                                "semantic_cn": "害羞",
                                "emotion_family": "embarrassment",
                                "usage_hint_cn": "掩饰关心",
                                "beat_fit": ["hesitation"],
                                "hold_policy": "short",
                                "avoid_when_cn": "<img src=x onerror=alert(1)>",
                                "intensity": 0,
                            },
                            {"id": "00", "label": "平静", "hold_policy": "hold"},
                        ],
                    },
                }
            )
        else:
            api.handle(route)

    page = profile_browser.new_page(viewport={"width": width, "height": 900})
    try:
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/api/v1/**", handle)
        page.add_init_script("localStorage.setItem('halocue.currentRunId', 'run-synthetic');")
        page.goto(ui_url, wait_until="networkidle")
        page.locator('.stage-list [data-stage="review"]').click()
        page.locator("#cardList .draft-card").first.click()
        panel = page.locator("#faceAnnotationContent")
        expect(panel).to_contain_text("掩饰关心")
        expect(panel).to_contain_text("短暂反应")
        expect(panel).to_contain_text("0 / 3")
        expect(panel.locator("img")).to_have_count(0)
        page.locator("#editLineFace").select_option("00")
        expect(panel).to_contain_text("可持续保持")
        expect(panel).not_to_contain_text("掩饰关心")
        page.locator("#editLineFace").select_option("")
        expect(panel).to_contain_text("未指定表情")
        expect(panel).to_contain_text("沿用角色此前状态")
        assert api.posts == []
        assert errors == []
    finally:
        page.close()


def test_background_picker_shows_usage_and_real_search_hits(profile_browser, ui_url):
    result = run_reply()
    result["draft"]["cards"] = [
        {
            "card_id": "scene-1",
            "kind": "scene",
            "line_no": 1,
            "current": {"title": "社团室"},
            "review_state": "pending",
        }
    ]
    api = ProductionApiFixture(result)

    def handle(route):
        if urlsplit(route.request.url).path.endswith("/resources/backgrounds"):
            route.fulfill(
                json={
                    "items": [
                        {
                            "key": "BG_Test",
                            "name": "社团室",
                            "place": "社团室",
                            "usage_hint": "整理资料",
                            "avoid_when": "战斗",
                            "has_fixed_characters": True,
                            "dialogue_suitable": False,
                        }
                    ],
                    "total": 1,
                    "offset": 0,
                    "has_more": False,
                }
            )
        else:
            api.handle(route)

    page = profile_browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.route("**/api/v1/**", handle)
        page.add_init_script("localStorage.setItem('halocue.currentRunId', 'run-synthetic');")
        page.goto(ui_url, wait_until="networkidle")
        page.locator('.stage-list [data-stage="mapping"]').click()
        page.locator("[data-mapping-scene-official]").first.click()
        expect(page.locator("#resourceResults")).to_contain_text("整理资料")
        expect(page.locator("#resourceResults")).to_contain_text("不适用 · 战斗")
        expect(page.locator("#resourceResults")).to_contain_text("含固定人物")
        expect(page.locator("#resourceResults")).to_contain_text("不适合普通对话")
        expect(page.locator(".annotation-match")).to_have_count(0)
        page.locator("#resourceSearch").fill("社团室")
        expect(page.locator(".annotation-match")).to_contain_text("地点：社团室")
        assert api.posts == []
    finally:
        page.close()


def test_background_search_keeps_latest_input_while_filter_request_is_pending(
    profile_browser, ui_url
):
    from urllib.parse import parse_qs

    result = run_reply()
    result["draft"]["cards"] = [
        {
            "card_id": "scene-1",
            "kind": "scene",
            "line_no": 1,
            "current": {"title": "社团室"},
            "review_state": "pending",
        }
    ]
    api = ProductionApiFixture(result)
    pending = []

    def reply(route, name):
        route.fulfill(
            json={
                "items": [{"key": "BG_Test", "name": name, "place": name}],
                "total": 1,
                "offset": 0,
                "has_more": False,
            }
        )

    def handle(route):
        parsed = urlsplit(route.request.url)
        if parsed.path.endswith("/resources/backgrounds"):
            query = parse_qs(parsed.query)
            if query.get("q") == ["社团室"]:
                reply(route, "社团室 最新结果")
            elif query.get("ready") == ["0"]:
                pending.append(route)
            else:
                reply(route, "初始结果")
        else:
            api.handle(route)

    page = profile_browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.route("**/api/v1/**", handle)
        page.add_init_script("localStorage.setItem('halocue.currentRunId', 'run-synthetic');")
        page.goto(ui_url, wait_until="networkidle")
        page.locator('.stage-list [data-stage="mapping"]').click()
        page.locator("[data-mapping-scene-official]").first.click()
        expect(page.locator("#resourceResults")).to_contain_text("初始结果")
        with page.expect_request(
            lambda r: "/resources/backgrounds?" in r.url and "ready=0" in r.url
        ):
            page.locator("#resourceReadyFilter").uncheck()
        page.locator("#resourceSearch").fill("社团室")
        expect(page.locator("#resourceResults")).to_contain_text("最新结果", timeout=2500)
        assert pending
        for route in pending:
            reply(route, "过期结果")
        pending.clear()
        page.wait_for_load_state("networkidle")
        expect(page.locator("#resourceResults")).not_to_contain_text("过期结果")
        expect(page.locator(".annotation-match")).to_contain_text("地点：社团室")
        assert api.posts == []
    finally:
        for route in pending:
            route.abort()
        page.close()
