"""Real HTTP/Chromium evidence for reply rendering and stage navigation."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from halocue_writing.app import make_handler
from halocue_writing.service import WritingService
from services.halocue.http_server import LocalHTTPServer
from test_choice_ui_browser import assert_visible_box, open_page, screenshot
from test_discussion_guidance import REPLY, ChapterOrganizer, QuietProvider, make_catalog, send
from test_scene_conversation_harness import create_ready_scene


class WrappedProvider(QuietProvider):
    next_step = "structure"

    def discuss_work(self, messages, context):
        self.calls = getattr(self, "calls", 0) + 1
        return {
            "text": "对白保持简短。\n```json\n"
            + json.dumps({**REPLY, "next_step": self.next_step}, ensure_ascii=False)
            + "\n```",
            "questions": [],
        }


@pytest.fixture
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as driver:
        instance = driver.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture
def flow_server(tmp_path):
    service = WritingService(tmp_path / "data")
    service.bundled_characters = make_catalog(tmp_path / "cards")
    provider = WrappedProvider()
    service.provider = provider
    work = service.create_work({"title": "创作引导演示"})
    work = send(service, work, "想写日奈和亚子的日常。")
    server = LocalHTTPServer(
        ("127.0.0.1", 0), make_handler(service, Path(__file__).resolve().parents[1] / "web")
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield service, provider, work, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    worker.join(timeout=3)
    service.close()


@pytest.mark.parametrize(
    "theme,size", [("light", (1440, 900)), ("dark", (960, 560)), ("dark", (390, 844))]
)
def test_public_reply_questions_receipt_and_outline_navigation(flow_server, browser, theme, size):
    from playwright.sync_api import expect

    service, provider, work, url = flow_server
    page = open_page(browser, f"{url}/?section=works&work_id={work['id']}", theme, size)
    reply = page.locator(".conversation-message.assistant").last
    expect(reply).to_contain_text(REPLY["text"])
    expect(reply.locator(".agent-reply-questions")).to_contain_text(REPLY["questions"][0])
    expect(reply.locator(".agent-character-resolution")).to_contain_text("已加入本作品：")
    expect(reply.locator(".agent-character-resolution")).to_contain_text("空崎日奈")
    expect(reply.locator(".agent-character-resolution")).to_contain_text("天雨亚子")
    assert '"ready_for_proposal"' not in reply.inner_text()
    assert reply.locator("pre").count() == 0
    next_step = reply.locator(".agent-reply-next-step")
    next_step.scroll_into_view_if_needed()
    assert_visible_box(page, next_step)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(page, f"discussion-public-{theme}-{size[0]}x{size[1]}")
    before = service.get_work(work["id"])
    calls = provider.calls
    next_step.get_by_role("button", name="进入章节大纲", exact=True).click()
    page.wait_for_url("**section=writing**stage=structure**")
    expect(page.locator("#outlineText")).to_be_visible()
    assert service.get_work(work["id"])["version"] == before["version"]
    assert provider.calls == calls
    page.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_on_demand_activity_shows_real_results_and_no_default_tools(flow_server, browser, theme):
    from playwright.sync_api import expect
    from test_agent_on_demand import LookupThenDraft

    service, _provider, work, url = flow_server
    page = open_page(browser, f"{url}/?section=works&work_id={work['id']}", theme, (1600, 900))
    reply = page.locator(".conversation-message.assistant").last
    assert reply.locator('.agent-tool-step[data-origin="agent"]').count() == 0
    preparation = reply.locator('.agent-character-resolution')
    expect(preparation).to_have_count(1)
    preparation.locator("summary").click()
    expect(preparation).to_contain_text("系统按对话中的人物准备资料")
    expect(preparation).to_contain_text("已加入本作品：")
    expect(preparation).to_contain_text("空崎日奈")
    expect(preparation).to_contain_text("天雨亚子")
    assert reply.locator(".agent-tool-step .agent-tool-category").inner_text() == "人物资料"
    assert "工具完成不代表" not in reply.inner_text()
    service.provider = LookupThenDraft(service)
    current = service.get_work(work["id"])
    send(service, current, "查下本作人物，再整理一个原创人物卡草稿。")
    page.reload()
    reply = page.locator(".conversation-message.assistant").last
    tool = reply.locator('.agent-tool-step[data-origin="agent"]').first
    tool.locator("summary").click()
    expect(tool).to_contain_text("找到 2 张人物卡")
    expect(tool).to_contain_text("空崎日奈")
    expect(tool.locator(".agent-tool-category")).to_have_text("人物资料")
    assert "load_workflow_template" not in reply.text_content()
    assert "read_work_context" not in reply.text_content()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(page, f"agent-on-demand-{theme}-1600x900")
    page.close()


def test_actual_lookup_is_visible_while_model_followup_is_pending(flow_server, browser):
    from playwright.sync_api import expect

    service, _provider, work, url = flow_server
    started, release = threading.Event(), threading.Event()

    class WaitingLookup(QuietProvider):
        is_simulation = False

        def discuss_work(self, messages, context):
            if context.get("tool_followup"):
                started.set()
                release.wait(timeout=15)
                return {"text": "检索完成，可以继续写这段误会。", "questions": []}
            return {"text": "查看人物。", "questions": [], "tool_calls": [{
                "id": "visible-lookup", "tool": "search_character_cards", "arguments": {"query": ""},
            }]}

    service.provider = WaitingLookup()
    service.start()
    page = open_page(browser, f"{url}/?section=works&work_id={work['id']}", "dark", (1600, 900))
    try:
        page.get_by_role("textbox", name="给创作导演发送消息").fill("查一下当前人物卡。")
        page.get_by_role("button", name="发送消息", exact=True).click()
        assert started.wait(timeout=5)
        running = page.locator(".agent-running-message")
        expect(running).to_contain_text("查找本作人物卡")
        running.locator(".agent-tool-step summary").click()
        expect(running).to_contain_text("找到 2 张人物卡")
        screenshot(page, "agent-live-tool-dark-1600x900")
    finally:
        release.set()
    expect(page.locator(".conversation-message.assistant").last).to_contain_text("检索完成")
    page.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_legacy_json_projects_without_rewriting_history_and_open_draft(flow_server, browser, theme):
    from playwright.sync_api import expect

    service, provider, _work, url = flow_server
    work_id, scene_id, work = create_ready_scene(service, title="午后办公室")
    work = send(service, work, "方向差不多了，现在直接开始写正文。")
    message = work["conversation_threads"][0]["messages"][-1]
    legacy = {
        **message["content"],
        "text": "对白保持简短。\n```json\n"
        + json.dumps({**REPLY, "next_step": "draft"}, ensure_ascii=False)
        + "\n```",
        "questions": [],
    }
    with service.repo.transaction() as connection:
        connection.execute(
            "UPDATE conversation_messages SET content_json=? WHERE id=?",
            (json.dumps(legacy, ensure_ascii=False), message["id"]),
        )
    page = open_page(browser, f"{url}/?section=works&work_id={work_id}", theme, (1440, 900))
    reply = page.locator(".conversation-message.assistant").last
    expect(reply.locator(".agent-reply-questions")).to_contain_text(REPLY["questions"][0])
    assert '"reasoning_summary"' not in reply.inner_text()
    page.reload()
    expect(page.locator(".agent-reply-questions").last).to_contain_text(REPLY["questions"][0])
    saved = service.get_work(work_id)["conversation_threads"][0]["messages"][-1]
    assert saved["content"] == legacy
    calls = provider.calls
    page.locator(".agent-reply-next-step").last.get_by_role(
        "button", name="进入正文写作", exact=True
    ).click()
    page.wait_for_url(f"**stage=draft**scene_id={scene_id}**")
    expect(page.locator(f'[data-chapter-scene="{scene_id}"]')).to_be_visible()
    expect(page.get_by_role("button", name="回看构思", exact=True)).to_be_visible()
    assert provider.calls == calls
    assert not service.get_work(work_id)["chapters"][0]["scenes"][0]["current_revision_id"]
    screenshot(page, f"discussion-open-draft-{theme}")
    page.get_by_role("button", name="回看构思", exact=True).click()
    page.wait_for_url("**section=works**")
    expect(page.locator(".conversation-message.user").last).to_contain_text("直接开始写正文")
    page.close()


def test_recovered_choice_sends_and_is_not_repeated(flow_server, browser):
    from playwright.sync_api import expect

    service, _provider, work, url = flow_server
    message = work["conversation_threads"][0]["messages"][-1]
    card = {
        "kind": "choose",
        "title": "这一场怎么收尾？",
        "submit_label": "发送",
        "allow_custom": True,
        "options": [
            {"id": "quiet", "label": "安静睡着", "description": "以午后的安静收束。"},
            {"id": "joke", "label": "保留笑点", "description": "以一句对白收束。"},
        ],
    }
    raw = {
        **message["content"],
        "text": "```json\n"
        + json.dumps({**REPLY, "decision_card": card}, ensure_ascii=False)
        + "\n```",
        "decision_card": None,
    }
    with service.repo.transaction() as connection:
        connection.execute(
            "UPDATE conversation_messages SET content_json=? WHERE id=?",
            (json.dumps(raw, ensure_ascii=False), message["id"]),
        )
    page = open_page(browser, f"{url}/?section=works&work_id={work['id']}", "dark", (960, 560))
    dock = page.locator(".decision-choice-dock")
    expect(dock).to_be_visible()
    dock.locator('[data-option-id="quiet"]').click()
    dock.locator("[data-submit-decision]").click()
    expect(dock).to_have_count(0)
    expect(page.locator(".conversation-message.user").last).to_contain_text("安静睡着")
    page.reload()
    expect(page.locator(".decision-choice-dock")).to_have_count(0)
    page.close()


def test_author_can_organize_then_review_without_writing_formal_direction(flow_server, browser):
    from playwright.sync_api import expect

    service, provider, work, url = flow_server
    provider.next_step = "organize"
    work = send(service, work, "方向差不多了，整理一下。")
    page = open_page(browser, f"{url}/?section=works&work_id={work['id']}", "dark", (1440, 900))
    page.locator(".agent-reply-next-step").last.get_by_role(
        "button", name="整理当前构思", exact=True
    ).click()
    expect(
        page.locator("[data-accept-director-proposal]").filter(visible=True).first
    ).to_be_visible()
    pending = service.get_work(work["id"])
    assert any(
        proposal["kind"] == "brief_blueprint" and proposal["status"] == "pending"
        for proposal in pending["proposals"]
    )
    assert not any(
        artifact["kind"] in {"brief", "story_blueprint", "scene_script"}
        for artifact in pending["artifacts"]
    )
    review = page.locator(".agent-reply-next-step").last.get_by_role(
        "button", name="查看候选", exact=True
    )
    expect(review).to_be_visible()
    review.click()
    expect(
        page.locator("[data-accept-director-proposal]").filter(visible=True).first
    ).to_be_in_viewport()
    screenshot(page, "discussion-organize-review-dark")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_work_switch_is_legible_in_both_themes(flow_server, browser, theme):
    from playwright.sync_api import expect

    _service, _provider, work, url = flow_server
    page = open_page(browser, f"{url}/?section=works&work_id={work['id']}", theme, (1600, 900))
    page.locator(".hc-work-switch").click()
    dialog = page.locator("#workSwitchDialog")
    expect(dialog).to_be_visible()
    row = dialog.locator(".work-switch-row.active")
    expect(row).to_contain_text(work["title"])
    assert_visible_box(page, dialog)
    colors = row.evaluate(
        "el=>({bg:getComputedStyle(el).backgroundColor,fg:getComputedStyle(el.querySelector('b')).color})"
    )

    def luminance(color):
        rgb = [
            float(item) / 255 for item in color.removeprefix("rgb(").removesuffix(")").split(",")
        ]
        values = [
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in rgb
        ]
        return sum(value * weight for value, weight in zip(values, (0.2126, 0.7152, 0.0722)))

    bg, fg = luminance(colors["bg"]), luminance(colors["fg"])
    assert (max(bg, fg) + 0.05) / (min(bg, fg) + 0.05) >= 4.5
    if theme == "dark":
        assert bg < 0.2
    screenshot(page, f"discussion-work-switch-{theme}-1600x900")
    row.click()
    expect(dialog).not_to_be_visible()
    page.close()


def test_chapter_plan_can_be_completed_in_ideation_and_synced_to_outline(flow_server, browser):
    from playwright.sync_api import expect

    service, _provider, _work, url = flow_server
    work_id, scene_id, work = create_ready_scene(service, title="夜间活动室")
    chapter_id = work["chapters"][0]["id"]
    service.provider = QuietProvider()
    work = send(service, work, "结尾只保留第一次回应，不添加反派。")
    service.provider = ChapterOrganizer(chapter_id)
    page = open_page(browser, f"{url}/?section=works&work_id={work_id}", "dark", (1600, 900))
    page.locator("#workConversationForm textarea").fill("把夜间调查这一章整理成细纲。")
    page.locator('#workConversationForm [type="submit"]').click()
    accept = page.get_by_role("button", name="采纳章节细纲", exact=True)
    expect(accept).to_be_visible(timeout=15000)
    expect(page.locator(".proposal-message").last).to_contain_text("同步到章节大纲")
    assert not any(
        item["kind"] == "chapter_plan" for item in service.get_work(work_id)["artifacts"]
    )
    accept.click()
    expect(accept).to_have_count(0)
    page.locator('.creation-navigation [data-creation-view="structure"]').click()
    expect(page.locator(".outline-plan-accepted")).to_contain_text("找到提示灯的回应规律")
    expect(page.locator("#outlineText")).to_contain_text("不添加反派")
    expect(page.locator(".authoring-chapter-plan")).not_to_contain_text("还没有正式细纲")
    screenshot(page, "discussion-chapter-outline-synced-dark-1600x900")
    page.reload()
    expect(page.locator(".outline-plan-accepted")).to_contain_text("找到提示灯的回应规律")
    page.locator("[data-outline-discuss]").click()
    page.wait_for_url("**section=works**")
    expect(page.locator(".work-agent-thread")).to_contain_text("把夜间调查这一章整理成细纲")
    expect(page.locator("#workConversationForm textarea")).to_be_focused()
    assert not service.get_work(work_id)["chapters"][0]["scenes"][0]["current_revision_id"]
    assert service.get_work(work_id)["chapters"][0]["scenes"][0]["id"] == scene_id
    page.close()
    page.close()


@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080)])
def test_agent_controls_single_small_button_at_16_by_9(flow_server, browser, size):
    from playwright.sync_api import expect

    service, provider, work, url = flow_server
    provider.next_step = None
    work = send(service, work, "人物还有哪些可能？")
    page = open_page(browser, f"{url}/?section=works&work_id={work['id']}", "dark", size)
    expect(page.locator(".agent-reply-next-step")).to_have_count(0)
    provider.next_step = "organize"
    send(service, work, "方向已经清楚，可以继续。")
    page.reload()
    button = page.locator(".agent-reply-next-step").last
    expect(button.locator("button")).to_have_count(1)
    expect(button.locator("p,b,section")).to_have_count(0)
    height = button.evaluate("element => element.getBoundingClientRect().height")
    assert height <= 44
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(page, f"discussion-single-button-dark-{size[0]}x{size[1]}")
    page.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("size", [(1280, 720), (1600, 900)])
def test_outline_director_keeps_send_visible_below_long_history(flow_server, browser, theme, size):
    from playwright.sync_api import expect

    service, _provider, _work, url = flow_server
    work_id, scene_id, work = create_ready_scene(service, title="夜间活动室")
    service.provider = QuietProvider()
    for _ in range(4):
        work = send(service, work, "保留活动室的细节，结尾不要添加反派。" * 12)
    chapter_id = work["chapters"][0]["id"]
    page = open_page(
        browser,
        f"{url}/?section=writing&work_id={work_id}&stage=structure"
        f"&chapter_id={chapter_id}&scene_id={scene_id}",
        theme,
        size,
    )
    inspector = page.locator("#inspector")
    composer = inspector.locator("#workConversationForm")
    expect(composer).to_be_visible()
    button = composer.get_by_role("button", name="发送", exact=True)
    box = assert_visible_box(page, button, inspector)
    bounds = inspector.bounding_box()
    assert bounds["y"] + bounds["height"] - box["y"] - box["height"] >= 12
    assert inspector.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
    transcript = inspector.locator(".conversation-scroll")
    assert transcript.evaluate("el => el.scrollHeight > el.clientHeight")
    reply_count = inspector.locator(".conversation-message.assistant").count()
    composer.locator("textarea").fill("沿用前面的结尾，继续核对本章节奏。")
    button.click()
    expect(inspector.locator(".conversation-message.user").last).to_contain_text("继续核对本章节奏")
    # The queued input can appear before the running composer replaces Send.
    # Measure the restored footer only after the new assistant reply arrives.
    expect(inspector.locator(".conversation-message.assistant")).to_have_count(reply_count + 1)
    expect(composer.get_by_role("button", name="发送", exact=True)).to_be_visible()
    assert_visible_box(page, composer.get_by_role("button", name="发送", exact=True), inspector)
    screenshot(page, f"outline-director-footer-{theme}-{size[0]}x{size[1]}")
    page.close()
