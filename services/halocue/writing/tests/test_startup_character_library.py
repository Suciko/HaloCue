"""Fresh-profile character browsing is independent of a work."""

from pathlib import Path
import json
import threading

import pytest

from halocue_writing.app import make_handler
from halocue_writing.bundled_character_catalog import BundledCharacterCatalog
from halocue_writing.service import WritingService
from services.halocue.http_server import LocalHTTPServer
from test_choice_ui_browser import open_page, screenshot


def test_nested_character_core_is_prose_in_catalog(tmp_path):
    (tmp_path / "sample.json").write_text(
        json.dumps(
            {
                "name": "合成人物",
                "aliases": [],
                "core": {"identity": "合成身份", "central_tension": "想帮忙，却不擅长说出口。"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    item = BundledCharacterCatalog(tmp_path).search("")["items"][0]
    assert item["summary"] == "想帮忙，却不擅长说出口。"


@pytest.fixture
def empty_server(tmp_path):
    service = WritingService(tmp_path / "data")
    server = LocalHTTPServer(
        ("127.0.0.1", 0), make_handler(service, Path(__file__).resolve().parents[1] / "web")
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield service, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    worker.join(timeout=3)
    service.close()


@pytest.fixture
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as driver:
        instance = driver.chromium.launch()
        yield instance
        instance.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_no_work_menu_lists_all_cards_and_reads_full_profile(empty_server, browser, theme):
    from playwright.sync_api import expect

    service, url = empty_server
    page = open_page(browser, f"{url}/?section=projects", theme, (1600, 900))
    page.get_by_role("button", name="资料", exact=True).click()
    page.get_by_role("button", name="人物卡", exact=True).click()
    expect(page.locator("[data-preview-reference-character]")).to_have_count(102)
    expect(page.locator(".global-character-catalog")).to_contain_text("102 份")
    assert service.list_works() == []
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(page, f"startup-character-library-{theme}-1600x900")

    page.locator("#officialReferenceSearchForm input").fill("白子")
    page.locator("#officialReferenceSearchForm button").click()
    expect(page.locator(".global-character-catalog .search-summary")).to_contain_text("匹配")
    expect(page.locator('[data-preview-reference-character="砂狼白子"]')).to_be_visible()
    assert page.locator("[data-preview-reference-character]").count() < 102
    page.locator('[data-preview-reference-character="砂狼白子"]').click()
    expect(page.locator(".global-character-profile")).to_contain_text("砂狼白子")
    page.get_by_text("人物核心", exact=True).click()
    expect(page.locator(".character-reference-details details[open] p").first).to_be_visible()
    assert page.locator("[data-import-character]").count() == 0
    assert page.locator("#characterImportDialog").is_visible() is False
    assert service.list_works() == []
    page.get_by_role("button", name="返回人物库", exact=True).click()
    expect(page.locator("#officialReferenceSearchForm input")).to_have_value("白子")
    page.locator("#officialReferenceSearchForm input").fill("")
    page.locator("#officialReferenceSearchForm button").click()
    expect(page.locator("[data-preview-reference-character]")).to_have_count(102)
    page.reload()
    expect(page.locator("[data-preview-reference-character]")).to_have_count(102)
    assert service.list_works() == []
    page.close()


def test_no_work_catalog_retry_and_phone_layout(empty_server, browser):
    from playwright.sync_api import expect

    service, url = empty_server
    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.add_init_script("localStorage.setItem('halocue.ui.theme', 'dark');")
    page.route(
        "**/api/v1/reference-characters/search?**",
        lambda route: route.fulfill(
            status=503, json={"ok": False, "error": {"message": "资料暂不可用"}}
        ),
        times=1,
    )
    page.goto(f"{url}/?section=references&view=characters")
    expect(page.locator(".global-character-catalog [role=alert]")).to_contain_text("资料暂不可用")
    page.locator("#officialReferenceSearchForm button").click()
    expect(page.locator("[data-preview-reference-character]")).to_have_count(102)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert service.list_works() == []
    page.close()
