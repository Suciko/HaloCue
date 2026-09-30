"""Expected prerequisites stay in the page instead of appearing as failures."""

import pytest
from playwright.sync_api import expect


def test_locked_writing_step_and_unavailable_corpus_have_inline_guidance(runtime):
    playwright = pytest.importorskip("playwright.sync_api")
    work = runtime.writing_service.create_work({"title": "Synthetic feedback check"})
    origin = f"http://127.0.0.1:{runtime.port}"

    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(
                f"{origin}/?section=writing&work_id={work['id']}&stage=draft",
                wait_until="networkidle",
            )
            expect(page.locator(".chapter-authoring-empty")).to_contain_text("还没有正文")
            expect(page.get_by_role("button", name="开始写本章")).to_be_visible()
            assert not page.locator("#toast").first.evaluate("el => el.classList.contains('show')")

            page.goto(
                f"{origin}/?section=references&work_id={work['id']}&view=official",
                wait_until="networkidle",
            )
            expect(page.locator(".catalog-availability-warning")).to_be_visible()
            expect(page.locator("#officialReferenceSearchForm input")).to_be_disabled()
            expect(page.locator("#officialReferenceSearchForm button")).to_be_disabled()
            assert not page.locator("#toast").first.evaluate("el => el.classList.contains('show')")
        finally:
            browser.close()


def test_reference_categories_keep_detail_routes_reachable_on_mobile(runtime):
    playwright = pytest.importorskip("playwright.sync_api")
    work = runtime.writing_service.create_work({"title": "Synthetic reference navigation"})
    origin = f"http://127.0.0.1:{runtime.port}"
    routes = [
        ("characters", "characters", None),
        ("rules", "world", "世界观分类"),
        ("timeline", "canon", "剧情记录分类"),
        ("memories", "canon", "剧情记录分类"),
        ("relations", "relations", None),
        ("official", "files", "来源资料分类"),
        ("suggestions", "suggestions", None),
    ]

    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            for view, section, subnav in routes:
                page.goto(
                    f"{origin}/?section=references&work_id={work['id']}&view={view}",
                    wait_until="networkidle",
                )
                expect(page.locator("[data-reference-mobile-view]")).to_have_value(section)
                expect(page.locator('#referencesNav [aria-current="page"]')).to_have_attribute(
                    "data-library-view", section
                )
                if subnav:
                    expect(page.get_by_role("navigation", name=subnav)).to_be_visible()
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        finally:
            browser.close()
