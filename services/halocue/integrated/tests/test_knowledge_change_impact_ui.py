"""Card -> affected scene -> existing review, via real HTTP and browser UI."""

import json
from urllib.request import urlopen

import pytest
from playwright.sync_api import expect

from services.halocue.writing.tests.test_knowledge_change_impact import (
    edit_card,
    edit_world,
    make_impact_work,
)


@pytest.mark.parametrize("width", [1280, 390])
def test_card_impact_navigation_and_scene_recheck_are_read_only_until_requested(runtime, width):
    service = runtime.writing_service
    work, ids = make_impact_work(service)
    edit_card(service, work["id"], ids["cards"][0], knowledge_boundary="不知道夜间口令")
    edit_world(service, work["id"], "world-archive", summary="夜间需要双人核验")
    before = service.get_work(work["id"])
    base = f"http://127.0.0.1:{runtime.gateway.server_port}"
    with urlopen(f"{base}/api/v1/works/{work['id']}/knowledge-impact") as response:
        report = json.load(response)["data"]
    assert report["summary"] == {
        "needs_review": 1,
        "unchanged": 1,
        "not_reviewed": 1,
        "baseline_unavailable": 0,
    }
    calls = service.provider.review_calls
    with pytest.importorskip("playwright.sync_api").sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(f"{base}/?section=references&view=characters&work_id={work['id']}")
            page.locator(f'[data-edit-card="{ids["cards"][0]}"]').click()
            page.locator('.library-editor-assist > summary').click()
            page.locator('.library-impact-preview > summary').click()
            panel = page.locator(".knowledge-impact-panel")
            expect(panel.get_by_role("status")).to_have_text("关联 2 个场景 · 1 个待复查")
            expect(panel).to_contain_text("知情边界发生变化")
            expect(panel).not_to_contain_text("档案室的传闻（未选用）")
            assert service.get_work(work["id"])["version"] == before["version"]
            assert service.provider.review_calls == calls
            role = page.locator('[name="role"]')
            original = role.input_value()
            role.fill("还没保存的新职责")
            panel.get_by_role("button", name="打开场景").first.click()
            expect(panel.get_by_role("alert")).to_contain_text("卡片还有未保存的修改")
            expect(role).to_have_value("还没保存的新职责")
            role.fill(original)
            panel.get_by_role("button", name="打开场景").first.click()
            scene_panel = page.locator("[data-scene-knowledge-impact]")
            expect(scene_panel).to_be_visible(timeout=15000)
            expect(scene_panel.get_by_role("status")).to_have_text("待复查")
            expect(scene_panel).to_contain_text("本作定义与限制发生变化")
            expect(page.locator('.chapter-authoring-scene.is-current')).to_be_visible()
            assert service.provider.review_calls == calls
            scene_panel.get_by_role("button", name="重新检查本场", exact=True).click()
            expect(scene_panel.get_by_role("status")).to_have_text("资料未变化", timeout=20000)
            assert service.provider.review_calls == calls + 1
            # Scene navigation persists an existing writing_target, not manuscript or knowledge.
            after_artifacts = [
                a
                for a in service.get_work(work["id"])["artifacts"]
                if a["kind"] != "writing_target"
            ]
            assert after_artifacts == before["artifacts"]
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors
        finally:
            browser.close()


def test_impact_error_is_local_retryable_and_does_not_erase_card_draft(runtime):
    work, ids = make_impact_work(runtime.writing_service)
    base = f"http://127.0.0.1:{runtime.gateway.server_port}"
    with pytest.importorskip("playwright.sync_api").sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            page.goto(f"{base}/?section=references&view=world&work_id={work['id']}")
            page.locator('[data-edit-world-entry="entity:world-archive"]').click()
            page.locator('#worldEntityForm [name="summary"]').fill("未保存的夜间规则")
            route = "**/knowledge-impact"
            page.route(
                route,
                lambda request: request.fulfill(
                    status=503, json={"ok": False, "error": {"message": "临时不可用，请重试"}}
                ),
            )
            page.locator('.library-editor-assist > summary').click()
            page.locator('.library-impact-preview > summary').click()
            expect(page.locator('.knowledge-impact-body [role="alert"]')).to_have_text(
                "临时不可用，请重试"
            )
            expect(page.locator('#worldEntityForm [name="summary"]')).to_have_value(
                "未保存的夜间规则"
            )
            page.unroute(route)
            page.get_by_role("button", name="重试", exact=True).click()
            expect(page.locator(".knowledge-impact-summary")).to_have_text("关联 2 个场景")
            expect(page.locator('#worldEntityForm [name="summary"]')).to_have_value(
                "未保存的夜间规则"
            )
        finally:
            browser.close()


def test_recheck_waits_for_existing_navigation_save_before_creating_job(runtime):
    service = runtime.writing_service
    work, ids = make_impact_work(service)
    edit_card(service, work["id"], ids["cards"][0], role="新职责")
    base = f"http://127.0.0.1:{runtime.gateway.server_port}"
    with pytest.importorskip("playwright.sync_api").sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        pending_targets, jobs = [], []
        page.route("**/writing-target", lambda route: pending_targets.append(route))
        page.on(
            "request",
            lambda request: (
                jobs.append(request.post_data_json)
                if request.url.endswith("/agent-jobs") and request.method == "POST"
                else None
            ),
        )
        try:
            page.goto(f"{base}/?section=references&view=characters&work_id={work['id']}")
            page.locator(f'[data-edit-card="{ids["cards"][0]}"]').click()
            page.locator('.library-editor-assist > summary').click()
            page.locator('.library-impact-preview > summary').click()
            page.locator(".knowledge-impact-panel").get_by_role(
                "button", name="打开场景"
            ).first.click()
            panel = page.locator("[data-scene-knowledge-impact]")
            expect(panel.get_by_role("status")).to_have_text("待复查")
            button = panel.get_by_role("button", name="重新检查本场", exact=True)
            button.click()
            expect(button).to_be_disabled()
            # Hold the real navigation request. Review must not race that pending write.
            page.wait_for_timeout(100)
            assert pending_targets
            assert not jobs, "Review was enqueued before the existing writing_target save finished"
            for route in list(pending_targets):
                route.continue_()
            page.unroute("**/writing-target")
            expect(panel.get_by_role("status")).to_have_text("资料未变化", timeout=15000)
            assert len(jobs) == 1
            assert jobs[0]["scope_id"] == ids["scenes"][0]
        finally:
            browser.close()
