"""First-use teaching uses the author's real work, then retires globally."""

from urllib.parse import parse_qs, urlsplit

import pytest
import test_authoring_workspace_browser as authoring_fixture
from playwright.sync_api import expect

from test_choice_ui_browser import open_page, screenshot
from test_scene_conversation_harness import create_ready_scene

browser = authoring_fixture.browser
local_authoring = authoring_fixture.local_authoring


def assert_pointer_clear_of(page, target):
    tip = page.get_by_role("region", name="首次创作教学").bounding_box()
    box = target.bounding_box()
    assert (
        tip["x"] + tip["width"] <= box["x"]
        or tip["x"] >= box["x"] + box["width"]
        or tip["y"] + tip["height"] <= box["y"]
        or tip["y"] >= box["y"] + box["height"]
    ), (tip, box)


@pytest.mark.parametrize(
    "theme,size", [("light", (1600, 900)), ("dark", (1280, 720)), ("dark", (960, 640))]
)
def test_first_work_manual_task_completes_and_never_reappears(
    local_authoring, browser, theme, size
):
    service, url = local_authoring
    page = open_page(browser, f"{url}/?section=projects", theme, size)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    task = page.get_by_role("region", name="首次创作教学")
    expect(task).to_contain_text("从你自己的作品开始")
    screenshot(page, f"first-use-welcome-{theme}-{size[0]}")
    assert service.list_works() == []
    task.get_by_role("button", name="带我开始").click()
    expect(task).to_contain_text("1 / 4")
    page.locator('[data-action="new-work"]').filter(visible=True).first.click()
    dialog = page.locator("#workDialog")
    expect(dialog.locator(".hc-first-use-layer:popover-open")).to_be_visible()
    assert_pointer_clear_of(page, dialog.locator('input[name="title"]'))
    dialog.locator('input[name="title"]').fill("我的第一部作品")
    dialog.get_by_role("button", name="建立作品", exact=True).click()
    expect(task).to_contain_text("2 / 4")
    expect(page.locator(".hc-first-use-layer:popover-open")).to_be_visible()
    screenshot(page, f"first-use-own-work-{theme}-{size[0]}")
    assert len(service.list_works()) == 1
    work_id = parse_qs(urlsplit(page.url).query)["work_id"][0]
    task.get_by_role("button", name="先自己写", exact=True).click()
    structure_view = page.locator('[data-creation-view="structure"]')
    if structure_view.is_visible():
        structure_view.click()
    else:
        expect(task).to_contain_text("视图菜单")
        page.locator("[data-creation-select]").select_option("structure")
    expect(task).to_contain_text("添加故事的第一场")
    page.locator("[data-structure-add-scene]").filter(visible=True).first.click()
    scene_dialog = page.locator("#structureDialog")
    expect(scene_dialog.locator(".hc-first-use-layer:popover-open")).to_be_visible()
    assert_pointer_clear_of(page, scene_dialog.locator('input[name="title"]'))
    scene_dialog.locator('input[name="title"]').fill("我写的开场")
    scene_dialog.get_by_role("button", name="保存结构").click()
    expect(task).to_contain_text("4 / 4")
    page.get_by_role("button", name="开始写作", exact=True).click()
    expect(task).to_contain_text("先在亮起的段落里写一句")
    expect(task).not_to_contain_text("保存这段正文")
    field = page.locator("[data-chapter-text]").first
    page.locator("[data-chapter-type]").first.select_option("dialogue")
    field.fill("这是我自己的第一段故事。")
    expect(task).to_contain_text("先在亮起的段落里写一句")
    page.locator("[data-chapter-speaker]").first.fill("爱丽丝")
    expect(task).to_contain_text("写好后，点这里保存")
    field.focus()
    expect(field).to_be_focused()
    assert_pointer_clear_of(page, field)
    page.locator("[data-chapter-save]").click()
    expect(task).to_have_count(0)
    expect(
        page.get_by_text("第一段正文已保存，首次创作教学已完成。以后可从帮助里重看。", exact=True)
    ).to_be_visible()
    assert service.get_work(work_id)["chapters"][0]["scenes"][0]["current_revision_id"]
    screenshot(page, f"first-use-complete-{theme}-{size[0]}")
    expect(task).to_have_count(0)
    expect(page.locator("[data-guidance-controls],[data-guidance-panel]")).to_have_count(0)
    page.reload()
    expect(task).to_have_count(0)
    expect(page.locator("[data-guidance-controls],[data-guidance-panel]")).to_have_count(0)
    next_work = service.create_work({"title": "学会之后的新作品"})
    page.goto(f"{url}/?section=works&work_id={next_work['id']}")
    expect(task).to_have_count(0)
    expect(page.locator("[data-guidance-controls],[data-guidance-panel]")).to_have_count(0)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert errors == []
    page.close()


def test_skipping_is_global_and_existing_authors_are_not_prompted(local_authoring, browser):
    service, url = local_authoring
    page = open_page(browser, f"{url}/?section=projects", "light", (1280, 720))
    task = page.get_by_role("region", name="首次创作教学")
    task.get_by_role("button", name="我已熟悉，跳过").click()
    page.reload()
    expect(task).to_have_count(0)
    assert service.list_works() == []
    work = service.create_work({"title": "已经在用的软件"})
    page.goto(f"{url}/?section=works&work_id={work['id']}")
    expect(task).to_have_count(0)
    expect(page.locator("[data-guidance-controls],[data-guidance-panel]")).to_have_count(0)
    page.close()
    returning = open_page(
        browser, f"{url}/?section=works&work_id={work['id']}", "dark", (1280, 720)
    )
    expect(returning.get_by_role("region", name="首次创作教学")).to_have_count(0)
    expect(returning.locator("[data-guidance-controls],[data-guidance-panel]")).to_have_count(0)
    # Replay is a deliberate Help action and binds the current real work.
    returning.locator("#openHelpButton").click()
    returning.get_by_role("button", name="重看新手教学", exact=True).click()
    expect(returning.get_by_role("region", name="首次创作教学")).to_be_visible()
    returning.close()


def test_paused_first_task_resumes_only_when_requested(local_authoring, browser):
    _service, url = local_authoring
    page = open_page(browser, f"{url}/?section=projects", "dark", (1280, 720))
    task = page.get_by_role("region", name="首次创作教学")
    task.get_by_role("button", name="带我开始").click()
    task.get_by_role("button", name="稍后继续").click()
    page.reload()
    expect(task).to_have_count(0)
    page.locator("#openHelpButton").click()
    page.get_by_role("button", name="继续首次创作教学", exact=True).click()
    expect(task).to_contain_text("1 / 4")
    page.close()


def test_following_the_original_create_button_starts_teaching(local_authoring, browser):
    _service, url = local_authoring
    page = open_page(browser, f"{url}/?section=projects", "light", (1280, 720))
    task = page.get_by_role("region", name="首次创作教学")
    expect(task).to_contain_text("从你自己的作品开始")
    # The illuminated product button also works without a separate tutorial CTA.
    page.locator('[data-action="new-work"]').filter(visible=True).first.click()
    dialog = page.locator("#workDialog")
    dialog.locator('input[name="title"]').fill("直接开始的作品")
    dialog.get_by_role("button", name="建立作品", exact=True).click()
    expect(task).to_contain_text("2 / 4")
    page.reload()
    expect(task).to_contain_text("2 / 4")
    page.close()


def test_spotlight_follows_hidden_agent_and_yields_to_settings(local_authoring, browser):
    service, url = local_authoring
    work_id, scene_id, work = create_ready_scene(service, title="自己的开场")
    chapter_id = work["chapters"][0]["id"]
    page = open_page(
        browser,
        f"{url}/?section=writing&stage=draft&work_id={work_id}&chapter_id={chapter_id}&scene_id={scene_id}",
        "light",
        (1600, 900),
    )
    page.wait_for_function(
        "() => state.context?.scene_id === state.sceneId && Boolean(sceneConversationThread(selectedScene())) && !state._contextLoadingScene"
    )
    toggle = page.locator('[data-panel-toggle="inspector"]').filter(visible=True).first
    if page.locator("#sceneConversationForm").is_visible():
        toggle.click()
    page.locator("#openHelpButton").click()
    page.get_by_role("button", name="重看新手教学", exact=True).click()
    task = page.get_by_role("region", name="首次创作教学")
    expect(task).to_contain_text("先点亮起的“Agent”")
    toggle.click()
    expect(task).to_contain_text("在亮起的输入框告诉助手")
    field = page.locator('#sceneConversationForm textarea[name="text"]')
    field.fill("请先讨论开场，不要直接生成正文。")
    page.set_viewport_size({"width": 1280, "height": 720})
    expect(field).to_have_value("请先讨论开场，不要直接生成正文。")
    expect(field).to_be_focused()
    expect(task).to_be_in_viewport(ratio=1)
    assert_pointer_clear_of(page, field)
    page.locator("#openSettingsButton").click()
    expect(page.locator(".hc-first-use-layer:popover-open")).to_have_count(0)
    page.locator("#settingsDialog [data-close-settings]").click()
    expect(task).to_be_visible()
    expect(field).to_have_value("请先讨论开场，不要直接生成正文。")
    assert not service.get_work(work_id)["chapters"][0]["scenes"][0]["current_revision_id"]
    screenshot(page, "first-use-spotlight-agent-resize-light-1280")
    page.close()


def test_ai_candidate_is_taught_as_review_and_only_adoption_completes(local_authoring, browser):
    service, url = local_authoring
    work_id, scene_id, work = create_ready_scene(service, title="我的试写")
    candidate = service.generate_scene_candidate(
        work_id, scene_id, {"expected_version": work["version"]}
    )
    chapter_id = work["chapters"][0]["id"]
    page = open_page(
        browser,
        f"{url}/?section=writing&stage=draft&work_id={work_id}&chapter_id={chapter_id}&scene_id={scene_id}",
        "light",
        (1600, 900),
    )
    page.wait_for_function(
        "() => state.context?.scene_id === state.sceneId && Boolean(sceneConversationThread(selectedScene())) && !state._contextLoadingScene"
    )
    page.locator("#openHelpButton").click()
    page.get_by_role("button", name="重看新手教学", exact=True).click()
    task = page.get_by_role("region", name="首次创作教学")
    expect(task).to_contain_text("先审查，再采用助手的文字")
    expect(task).to_be_in_viewport(ratio=1)
    screenshot(page, "first-use-review-light-1600")
    assert not service.get_work(work_id)["chapters"][0]["scenes"][0]["current_revision_id"]
    expect(page.locator("[data-scene-change]").first).to_be_visible()
    page.locator(f'[data-apply-scene-changes="{candidate["proposal_id"]}"]').first.click()
    expect(task).to_have_count(0)
    expect(
        page.get_by_text("第一段正文已保存，首次创作教学已完成。以后可从帮助里重看。", exact=True)
    ).to_be_visible()
    page.reload()
    expect(task).to_have_count(0)
    # Replaying an already-authored work requires a new edit; old prose isn't learning evidence.
    page.locator("#openHelpButton").click()
    page.get_by_role("button", name="重看新手教学", exact=True).click()
    expect(task).to_contain_text("试着修改并保存一处正文")
    task.get_by_role("button", name="稍后继续").click()
    page.reload()
    page.locator("#openHelpButton").click()
    page.get_by_role("button", name="继续首次创作教学", exact=True).click()
    expect(task).to_contain_text("试着修改并保存一处正文")
    assert len(service.list_works()) == 1
    page.close()
