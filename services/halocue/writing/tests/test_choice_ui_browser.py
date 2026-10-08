"""Real HTTP interactions for the reported modal and composer choice defects."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from halocue_writing.app import make_handler
from services.halocue.http_server import LocalHTTPServer
from services.halocue.writing.tests.in_app_browser_decision_card_fixture_server import (
    DecisionCardProvider,
    DecisionFixtureService,
    revision_count,
)

WEB = Path(__file__).resolve().parents[1] / "web"
SIZES = [(1440, 900), (960, 560), (390, 844)]


@pytest.fixture
def choice_server(tmp_path):
    service = DecisionFixtureService(tmp_path)
    service.provider = DecisionCardProvider()
    service.start()
    work = service.create_work({"title": "选项交互验收", "idea": "雨夜寻找录音。"})
    server = LocalHTTPServer(("127.0.0.1", 0), make_handler(service, WEB))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield service, work, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    worker.join(timeout=3)
    service.close()


@pytest.fixture
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        yield browser
        browser.close()


def open_page(browser, url, theme, size):
    page = browser.new_page(viewport={"width": size[0], "height": size[1]})
    page.add_init_script(f"localStorage.setItem('halocue.ui.theme', '{theme}');")
    page.goto(url)
    page.locator("#bootScreen").wait_for(state="hidden")
    return page


def screenshot(page, name):
    evidence = os.environ.get("HALOCUE_UI_EVIDENCE")
    if evidence:
        target = Path(evidence)
        target.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target / f"{name}.png"))


def assert_visible_box(page, target, container=None):
    box = target.bounding_box()
    assert box is not None
    bounds = container.bounding_box() if container else {"x": 0, "y": 0, **page.viewport_size}
    assert box["x"] >= bounds["x"] - 1
    assert box["y"] >= bounds["y"] - 1
    assert box["x"] + box["width"] <= bounds["x"] + bounds["width"] + 1
    assert box["y"] + box["height"] <= bounds["y"] + bounds["height"] + 1
    return box


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("size", SIZES)
def test_new_work_theme_fields_and_footer_stay_visible(choice_server, browser, theme, size):
    from playwright.sync_api import expect

    service, work, url = choice_server
    page = open_page(browser, f"{url}/?section=projects&work_id={work['id']}", theme, size)
    if size[0] <= 640:
        page.locator(".mobile-more-menu").click()
        page.locator(".mobile-more-menu [data-open-work-switch]").click()
        page.locator('#workSwitchDialog [data-action="new-work"]').click()
    else:
        page.locator('[data-action="new-work"]').filter(visible=True).first.click()
    dialog = page.locator("#workDialog")
    expect(dialog).to_be_visible()
    assert_visible_box(page, dialog)
    button = dialog.locator('[data-submit="work"]')
    box = assert_visible_box(page, button, dialog)
    dialog_box = dialog.bounding_box()
    assert dialog_box["y"] + dialog_box["height"] - box["y"] - box["height"] >= 16
    title = dialog.locator('[name="title"]')
    expect(title).to_be_visible()
    assert 36 <= title.bounding_box()["height"] <= 48
    surfaces = dialog.locator(
        'input[name="title"], textarea, select, .dialog-actions, .work-start-picker label'
    )
    colors = surfaces.evaluate_all("els => els.map(el => getComputedStyle(el).backgroundColor)")
    if theme == "dark":
        for color in colors:
            rgb = [int(value) for value in color.removeprefix("rgb(").removesuffix(")").split(", ")]
            assert sum(rgb[:3]) / 3 < 100, color
    dialog.locator(".work-dialog-fields").evaluate("el => el.scrollTop = el.scrollHeight")
    assert_visible_box(page, button, dialog)
    screenshot(page, f"work-modal-{theme}-{size[0]}x{size[1]}")
    button.click()
    expect(dialog).to_be_hidden()
    assert len(service.list_works()) == 2
    page.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("size", SIZES)
def test_choice_floats_above_composer_and_preset_sends_once(choice_server, browser, theme, size):
    from playwright.sync_api import expect

    service, work, url = choice_server
    initial_revisions = revision_count(work)
    page = open_page(browser, f"{url}/?section=works&work_id={work['id']}", theme, size)
    dock = page.locator(".decision-choice-dock")
    expect(dock).to_be_visible()
    box = assert_visible_box(page, dock)
    composer = page.locator("#workConversationForm")
    assert box["y"] + box["height"] <= composer.bounding_box()["y"]
    assert box["x"] == pytest.approx(composer.bounding_box()["x"], abs=1)
    assert box["width"] == pytest.approx(composer.bounding_box()["width"], abs=1)
    assert_visible_box(page, dock.locator("[data-submit-decision]"), dock)
    reply = dock.get_by_role("textbox", name="输入其他想法").bounding_box()
    assert reply["height"] <= 44
    assert reply["width"] >= box["width"] * 0.6
    page.locator("[data-work-discussion-scroll]").evaluate("el => el.scrollTop = 0")
    assert dock.bounding_box()["y"] == pytest.approx(box["y"], abs=1)
    second = dock.locator('[data-option-id="direction_b"]')
    second.click()
    expect(second).to_have_attribute("aria-checked", "true")
    expect(dock.locator("[data-decision-selection-status]")).to_have_text("已选择：先定开场事件")
    screenshot(page, f"choice-{theme}-{size[0]}x{size[1]}")
    dock.locator("[data-submit-decision]").click()
    expect(dock).to_have_count(0)
    expect(page.locator(".conversation-message.user").last).to_contain_text("先定开场事件")
    saved = service.get_work(work["id"])
    replies = [
        m
        for m in saved["conversation_threads"][0]["messages"]
        if m.get("content", {}).get("decision_response")
    ]
    assert len(replies) == 1
    assert replies[0]["content"]["decision_response"]["option_id"] == "direction_b"
    assert revision_count(saved) == initial_revisions
    page.reload()
    expect(page.locator("#bootScreen")).to_be_hidden()
    expect(page.locator(".decision-choice-dock")).to_have_count(0)
    page.close()


def test_new_work_failure_keeps_inline_error_and_fields_until_retry(choice_server, browser):
    from playwright.sync_api import expect

    service, work, url = choice_server
    page = open_page(browser, f"{url}/?section=projects&work_id={work['id']}", "dark", (1280, 720))
    page.locator('[data-action="new-work"]').filter(visible=True).first.click()
    dialog = page.locator("#workDialog")
    title = dialog.locator('[name="title"]')
    title.fill("网络失败后保留的作品")
    page.route("**/works", lambda route: route.fulfill(
        status=503, content_type="application/json",
        body='{"error":{"code":"unavailable","message":"暂时无法建立作品，请重试。"}}',
    ), times=1)
    dialog.locator('[data-submit="work"]').click()
    notice = dialog.locator("#workDialogError")
    expect(notice).to_contain_text("暂时无法建立作品，请重试。")
    expect(title).to_have_value("网络失败后保留的作品")
    expect(dialog.locator('[data-submit="work"]')).to_be_enabled()
    # The persistent explanation outlives the toast.
    expect(page.locator("#toast")).not_to_have_class("visible", timeout=10000)
    expect(notice).to_be_visible()
    assert_visible_box(page, dialog.locator('[data-submit="work"]'), dialog)
    dialog.locator('[data-submit="work"]').click()
    expect(dialog).to_be_hidden()
    assert len(service.list_works()) == 2
    page.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_custom_answer_is_direct_preserved_on_failure_and_retries(choice_server, browser, theme):
    from playwright.sync_api import expect

    service, work, url = choice_server
    service.fail_first_decision = True
    page = open_page(browser, f"{url}/?section=works&work_id={work['id']}", theme, (960, 560))
    dock = page.locator(".decision-choice-dock")
    answer = dock.get_by_role("textbox", name="输入其他想法")
    expect(answer).to_be_visible()
    answer.fill("两个都要，主次分明。")
    expect(dock.locator('[role="radio"][aria-checked="true"]')).to_have_count(0)
    expect(dock.locator("[data-decision-selection-status]")).to_have_text("将发送你的想法")
    answer.press("Enter")
    expect(dock.locator('[role="alert"]')).to_contain_text("这次选择没有保存，请重试。")
    expect(answer).to_have_value("两个都要，主次分明。")
    expect(dock.locator("[data-submit-decision]")).to_be_enabled()
    screenshot(page, f"choice-retry-{theme}")
    answer.press("Enter")
    expect(dock).to_have_count(0)
    saved = service.get_work(work["id"])
    replies = [
        m
        for m in saved["conversation_threads"][0]["messages"]
        if m.get("content", {}).get("decision_response")
    ]
    assert len(replies) == 1
    response = replies[0]["content"]["decision_response"]
    assert response["option_id"] == "__custom__"
    assert response["custom_text"] == "两个都要，主次分明。"
    assert revision_count(saved) == revision_count(work)
    page.close()


def test_keyboard_selection_and_dismiss_preserve_custom_draft(choice_server, browser):
    from playwright.sync_api import expect

    _, work, url = choice_server
    page = open_page(browser, f"{url}/?section=works&work_id={work['id']}", "dark", (1440, 900))
    dock = page.locator(".decision-choice-dock")
    first = dock.locator('[data-option-id="direction_a"]')
    first.focus()
    first.press("ArrowDown")
    expect(dock.locator('[data-option-id="direction_b"]')).to_have_attribute("aria-checked", "true")
    answer = dock.get_by_role("textbox", name="输入其他想法")
    answer.fill("先讨论第三个方向。")
    answer.press("Escape")
    expect(dock).to_have_count(0)
    page.locator("[data-decision-reopen]").click()
    expect(answer).to_have_value("先讨论第三个方向。")
    expect(answer).to_be_focused()
    expect(dock.locator("[data-decision-selection-status]")).to_have_text("将发送你的想法")
    page.close()


@pytest.mark.parametrize("size", [(960, 560), (390, 844)])
def test_long_options_scroll_without_hiding_reply_or_send(choice_server, browser, size):
    from playwright.sync_api import expect

    class LongChoices(DecisionCardProvider):
        def discuss_work(self, messages, work_context):
            response = super().discuss_work(messages, work_context)
            if "decision_card" in response:
                response["decision_card"]["options"] = [
                    {
                        "id": f"direction_{i}",
                        "label": f"方向 {i}",
                        "description": "保留主要人物的关系变化，分清故事推进的主次。" * 8,
                    }
                    for i in range(6)
                ]
            return response

    service, _, url = choice_server
    service.provider = LongChoices()
    work = service.create_work({"title": "长选项验收", "idea": "讨论故事方向。"})
    page = open_page(browser, f"{url}/?section=works&work_id={work['id']}", "dark", size)
    dock = page.locator(".decision-choice-dock")
    expect(dock).to_be_visible()
    assert_visible_box(page, dock)
    send = dock.locator("[data-submit-decision]")
    assert_visible_box(page, send, dock)
    last = dock.locator('[data-option-id="direction_5"]')
    last.click()
    expect(last).to_have_attribute("aria-checked", "true")
    assert_visible_box(page, send, dock)
    screenshot(page, f"choice-long-dark-{size[0]}x{size[1]}")
    send.click()
    expect(dock).to_have_count(0)
    page.close()
