"""Guidance uses real UI/state while all model replies and data are synthetic."""

from __future__ import annotations

import pytest
import test_discussion_guidance_browser as guidance_fixture
from playwright.sync_api import expect

from test_choice_ui_browser import open_page, screenshot
from test_discussion_guidance import send
from test_scene_conversation_harness import create_ready_scene

browser = guidance_fixture.browser
flow_server = guidance_fixture.flow_server


@pytest.mark.parametrize("theme,size", [("light", (1600, 900)), ("dark", (1280, 720))])
def test_guided_reply_pause_and_dismiss_keep_input_and_persist(flow_server, browser, theme, size):
    service, provider, work, url = flow_server
    page = open_page(browser, f"{url}/?section=works&work_id={work['id']}", theme, size)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    mode = page.get_by_label("用户引导模式")
    expect(mode).to_be_visible()
    mode.select_option("guided")
    panel = page.get_by_role("region", name="当前任务引导")
    # A labelled section is a region. It sits beside the existing one-button action.
    expect(panel).to_contain_text("接下来安排章节与场景")
    field = page.locator("#workConversationForm textarea")
    field.fill("先保留我的想法，还没有发送。")
    before = service.get_work(work["id"])["version"]
    calls = provider.calls
    page.get_by_role("button", name="暂停", exact=True).click()
    expect(panel).to_have_count(0)
    expect(field).to_have_value("先保留我的想法，还没有发送。")
    assert service.get_work(work["id"])["version"] == before
    assert provider.calls == calls
    page.reload()
    expect(page.get_by_role("button", name="恢复引导")).to_be_visible()
    expect(page.locator(".agent-reply-next-step")).to_be_hidden()
    page.get_by_role("button", name="恢复引导").click()
    panel.get_by_role("button", name="继续讨论", exact=True).click()
    expect(panel).to_have_count(0)
    expect(page.locator(".agent-reply-next-step")).to_be_hidden()
    send(service, service.get_work(work["id"]), "还想继续讨论人物。")
    page.reload()
    expect(panel).to_have_count(0)
    page.get_by_role("button", name="下一步", exact=True).click()
    expect(panel).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert errors == []
    screenshot(page, f"guided-workflow-{theme}-{size[0]}")
    page.close()


def test_guidance_carries_into_scene_and_never_sends_prepared_request(flow_server, browser):
    service, provider, _work, url = flow_server
    work_id, scene_id, _work = create_ready_scene(service, title="陪跑开场")
    provider.next_step = "draft"
    send(service, service.get_work(work_id), "先写活动室的开场。")
    page = open_page(browser, f"{url}/?section=works&work_id={work_id}", "light", (1600, 900))
    page.get_by_label("用户引导模式").select_option("guided")
    calls = provider.calls
    page.locator(".agent-reply-next-step").get_by_role("button", name="进入正文写作").click()
    page.wait_for_url("**section=writing**stage=draft**")
    expect(page.get_by_label("用户引导模式")).to_have_value("guided")
    panel = page.get_by_role("region", name="当前任务引导")
    expect(panel).to_contain_text("陪跑开场")
    # Readiness remains owned by the existing workspace; guidance only prepares.
    prepare = panel.get_by_role("button", name="准备试写", exact=True)
    expect(prepare).to_be_visible()
    prepare.click()
    field = page.locator('#sceneConversationForm textarea[name="text"]')
    expect(field).to_have_value(__import__("re").compile(".*陪跑开场.*"))
    assert provider.calls == calls
    assert not service.get_work(work_id)["chapters"][0]["scenes"][0]["current_revision_id"]
    field.fill("我的修改要求，不能被替换")
    prepare.click()
    expect(field).to_have_value("我的修改要求，不能被替换")
    assert provider.calls == calls
    # The scene handoff and guidance keep the same explicit target.
    assert f"scene:{scene_id}" in panel.get_attribute("data-task-key")
    page.close()


def test_manual_draft_pause_and_refresh_preserve_the_same_prose(flow_server, browser):
    service, _provider, _work, url = flow_server
    work_id, scene_id, work = create_ready_scene(service, title="自己写的开场")
    chapter_id = work["chapters"][0]["id"]
    page = open_page(
        browser,
        f"{url}/?section=writing&work_id={work_id}&stage=draft&chapter_id={chapter_id}&scene_id={scene_id}",
        "dark",
        (1280, 720),
    )
    page.get_by_label("用户引导模式").select_option("guided")
    panel = page.get_by_role("region", name="当前任务引导")
    panel.get_by_role("button", name="自己写", exact=True).click()
    field = page.locator("[data-chapter-text]").first
    field.fill("这是我还没保存的正文。")
    expect(panel).to_contain_text("先保存正在修改的正文")
    page.get_by_role("button", name="暂停", exact=True).click()
    expect(field).to_have_value("这是我还没保存的正文。")
    assert not service.get_work(work_id)["chapters"][0]["scenes"][0]["current_revision_id"]
    page.reload()
    expect(page.locator("[data-chapter-text]").first).to_have_value("这是我还没保存的正文。")
    expect(page.get_by_role("button", name="恢复引导")).to_be_visible()
    page.get_by_role("button", name="恢复引导").click()
    panel.get_by_role("button", name="保存正文", exact=True).click()
    expect(panel).to_contain_text("正文已保存，可以继续打磨")
    assert service.get_work(work_id)["chapters"][0]["scenes"][0]["current_revision_id"]
    page.close()


def test_current_candidate_guides_review_but_only_explicit_apply_changes_prose(
    flow_server, browser
):
    service, _provider, _work, url = flow_server
    work_id, scene_id, work = create_ready_scene(service, title="等待审查的开场")
    candidate = service.generate_scene_candidate(
        work_id, scene_id, {"expected_version": work["version"]}
    )
    chapter_id = work["chapters"][0]["id"]
    page = open_page(
        browser,
        f"{url}/?section=writing&work_id={work_id}&stage=draft&chapter_id={chapter_id}&scene_id={scene_id}",
        "light",
        (1600, 900),
    )
    # Initial context/thread assembly can replace the first manuscript DOM.
    page.wait_for_function(
        "() => state.context?.scene_id === state.sceneId && "
        "Boolean(sceneConversationThread(selectedScene())) && !state._contextLoadingScene"
    )
    panel = page.get_by_role("region", name="当前任务引导")
    expect(panel).to_contain_text("在原文位置核对这份修改")
    panel.get_by_role("button", name="查看第一处改动").click()
    expect(
        page.locator("[data-review-change]").first.locator("[data-scene-change]")
    ).to_be_focused()
    assert not service.get_work(work_id)["chapters"][0]["scenes"][0]["current_revision_id"]
    page.locator(f'[data-apply-scene-changes="{candidate["proposal_id"]}"]').first.click()
    expect(panel).to_contain_text("正文已保存，可以继续打磨")
    assert service.get_work(work_id)["chapters"][0]["scenes"][0]["current_revision_id"]
    screenshot(page, "guided-workflow-adopted-light-1600")
    page.close()


def test_guidance_updates_do_not_steal_composer_focus_or_ime_input(flow_server, browser):
    service, _provider, _work, url = flow_server
    work_id, scene_id, work = create_ready_scene(service, title="输入保护")
    chapter_id = work["chapters"][0]["id"]
    page = open_page(
        browser,
        f"{url}/?section=writing&work_id={work_id}&stage=draft&chapter_id={chapter_id}&scene_id={scene_id}",
        "dark",
        (1280, 720),
    )
    field = page.locator('#sceneConversationForm textarea[name="text"]')
    expect(field).to_be_visible()
    field.fill("继续写我正在输入的这一段")
    field.evaluate("element => element.setSelectionRange(3, 7)")
    field.dispatch_event("compositionstart")
    assert page.evaluate("HaloCueGuidance.canReveal()") is False
    page.evaluate("HaloCueGuidance.mount()")
    expect(field).to_be_focused()
    expect(field).to_have_value("继续写我正在输入的这一段")
    assert field.evaluate("element => [element.selectionStart, element.selectionEnd]") == [3, 7]
    field.dispatch_event("compositionend")
    assert page.evaluate("HaloCueGuidance.canReveal()") is False
    page.close()
