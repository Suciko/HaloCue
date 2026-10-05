"""Reported filled-input model choices and complete bundled reference browsing."""

import pytest
from playwright.sync_api import expect


def test_fetched_models_are_all_selectable_with_a_filled_model(runtime, monkeypatch):
    models = ["gpt-6-astra", *[f"fixture-writer-{n}" for n in range(6)]]
    monkeypatch.setattr(
        runtime.writing_service,
        "fetch_writing_models",
        lambda payload: {"models": models, "model_details": []},
    )
    work = runtime.writing_service.create_work({"title": "Model list check"})
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1600, "height": 900})
            page.goto(f"http://127.0.0.1:{runtime.port}/?section=works&work_id={work['id']}")
            page.locator("#openSettingsButton").click()
            page.get_by_role("tab", name="模型服务", exact=True).click()
            page.get_by_role("button", name="自定义接口", exact=False).click()
            page.locator("#settingsModelName").fill("gpt-6-astra")
            page.locator("#settingsBaseUrl").fill("http://127.0.0.1:48100/v1")
            page.locator("#fetchModelsBtn").click()
            expect(page.locator("#modelDiagnosticsCard")).to_contain_text("7 个")
            page.get_by_role("button", name="选择模型", exact=True).click()
            options = page.get_by_role("listbox", name="可用模型").get_by_role("option")
            expect(options).to_have_count(7)
            options.filter(has_text="fixture-writer-5").click()
            expect(page.locator("#settingsModelName")).to_have_value("fixture-writer-5")
            page.get_by_role("button", name="选择模型", exact=True).click()
            expect(options).to_have_count(7)
            page.locator("#settingsBaseUrl").fill("http://127.0.0.1:48101/v1")
            expect(page.get_by_role("button", name="选择模型", exact=True)).to_be_disabled()
            page.locator("#fetchModelsBtn").click()
            expect(page.locator("#modelDiagnosticsCard")).to_contain_text("7 个")
            monkeypatch.setattr(
                runtime.writing_service,
                "fetch_writing_models",
                lambda payload: {"models": [], "model_details": []},
            )
            page.locator("#fetchModelsBtn").click()
            expect(page.locator("#modelDiagnosticsCard")).to_contain_text("未获取到模型")
            expect(page.get_by_role("button", name="选择模型", exact=True)).to_be_disabled()
        finally:
            browser.close()


def test_delete_current_and_last_work_then_restore(runtime):
    first = runtime.writing_service.create_work({"title": "First disposable work"})
    last = runtime.writing_service.create_work({"title": "Last disposable work"})
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1600, "height": 900})
            origin = f"http://127.0.0.1:{runtime.port}"
            page.goto(f"{origin}/?section=projects&work_id={first['id']}")
            page.get_by_role("button", name="删除作品：First disposable work", exact=True).click()
            dialog = page.locator("#deleteWorkDialog")
            expect(dialog).to_contain_text("First disposable work")
            dialog.get_by_role("button", name="取消", exact=True).click()
            assert len(runtime.writing_service.list_works()) == 2
            for title in ["First disposable work", "Last disposable work"]:
                page.get_by_role("button", name=f"删除作品：{title}", exact=True).click()
                dialog.get_by_role("button", name="删除作品", exact=True).click()
                expect(dialog).not_to_be_visible()
                expect(page.locator(".project-card").filter(has_text=title)).to_have_count(0)
            assert runtime.writing_service.list_works() == []
            expect(page.locator(".project-home-empty")).to_be_visible()
            page.reload()
            expect(page.locator(".project-home-empty")).to_be_visible()
            page.get_by_role("button", name="回收站", exact=True).click()
            row = page.locator(".project-card").filter(has_text="First disposable work")
            row.get_by_role("button", name="恢复作品", exact=True).click()
            expect(row).to_have_count(0)
            page.get_by_role("button", name="返回作品", exact=True).click()
            expect(page.locator(".project-card")).to_have_count(1)
            page.get_by_role("button", name="打开构思", exact=False).click()
            expect(page.locator("#currentWorkName")).to_have_text("First disposable work")
            assert [item["id"] for item in runtime.writing_service.list_deleted_works()] == [
                last["id"]
            ]
        finally:
            browser.close()


def test_reference_browser_has_complete_count_and_separate_sources(runtime):
    work = runtime.writing_service.create_work({"title": "Reference sources check"})
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1600, "height": 900})
            page.goto(
                f"http://127.0.0.1:{runtime.port}/?section=references&work_id={work['id']}&view=overview"
            )
            page.get_by_role("button", name="浏览随包人物参考", exact=True).click()
            expect(page.locator(".search-summary")).to_contain_text("102")
            expect(page.locator("[data-reference-character]")).to_have_count(102)
            expect(page.get_by_role("button", name="人物参考", exact=True)).to_have_attribute(
                "aria-pressed", "true"
            )
            assert page.locator(".bundled-reference-record").count() == 0
            while not page.locator('[data-reference-character="龙华妃咲"]').is_visible():
                page.locator("[data-official-more]").click()
            expect(page.locator('[data-reference-character="龙华妃咲"]')).to_be_visible()
            page.get_by_role("button", name="原作摘录", exact=True).click()
            expect(page.locator("#officialReferenceSearchForm input")).to_have_attribute(
                "placeholder", "输入台词、故事标题或人物名"
            )
            expect(page.locator("[data-reference-character]")).to_have_count(0)
        finally:
            browser.close()
