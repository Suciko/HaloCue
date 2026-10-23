"""First-use teaching uses the author's real work, then retires globally."""

from urllib.parse import parse_qs, urlsplit

import pytest
import test_authoring_workspace_browser as authoring_fixture
from playwright.sync_api import expect
from manuscript_document_test_support import replace_paragraph

from test_choice_ui_browser import open_page, screenshot
from test_scene_conversation_harness import create_ready_scene
from test_discussion_guidance import make_catalog
from first_use_fixture_support import DraftingProvider, assert_readable_surface

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
    "theme,size",
    [
        ("light", (1920, 1080)),
        ("dark", (1920, 1080)),
        ("light", (1600, 900)),
        ("dark", (1280, 720)),
        ("dark", (960, 640)),
    ],
)
def test_first_ai_work_follows_direction_structure_and_scene_review(
    local_authoring, browser, tmp_path, theme, size
):
    service, url = local_authoring
    service.bundled_characters = make_catalog(tmp_path / "cards")
    service.provider = DraftingProvider()
    page = open_page(browser, f"{url}/?section=projects", theme, size)
    # Verify the display conditions separately from screenshot pixel dimensions.
    session = page.context.new_cdp_session(page)
    metrics = session.send("Page.getLayoutMetrics")["cssVisualViewport"]
    session.detach()
    assert (metrics["clientWidth"], metrics["clientHeight"]) == size
    assert metrics["zoom"] == pytest.approx(1)
    assert metrics["scale"] == pytest.approx(1)
    assert page.evaluate(
        "[document.documentElement, document.body].every(node => getComputedStyle(node).zoom === '1')"
    )
    task = page.get_by_role("region", name="首次创作教学")
    task.get_by_role("button", name="带我开始", exact=True).click()
    page.locator('[data-action="new-work"]').filter(visible=True).first.click()
    page.locator('#workDialog input[name="title"]').fill("自己的 AI 开场")
    page.locator("#workDialog").get_by_role("button", name="建立作品", exact=True).click()
    expect(task).to_contain_text("说说你想写什么")
    composer = page.locator("#workConversationForm")
    composer.locator("textarea").fill(
        "我想写日奈和亚子夜里检查档案室的故事，老师不出场。两人核对记录，发现提示灯回应就结束。请整理故事方向。"
    )
    composer.locator('[type="submit"]').click()
    expect(task).to_contain_text("按这条回复继续")
    page.locator(".agent-reply-next-step button").click()
    accept = page.get_by_role("button", name="采纳为正式方向", exact=True)
    expect(accept).to_be_visible(timeout=15000)
    expect(task).to_contain_text("确认故事方向")
    expect(task).to_contain_text("还没有正文")
    work_id = parse_qs(urlsplit(page.url).query)["work_id"][0]
    assert not any(
        item["kind"] == "story_blueprint" for item in service.get_work(work_id)["artifacts"]
    )
    accept.click()
    expect(task).to_contain_text("方向已确认，接着安排场景")
    expect(task).to_contain_text("在输入框里")
    assert_pointer_clear_of(page, composer.locator("textarea"))
    assert not service.get_work(work_id)["chapters"][0]["scenes"]
    task.get_by_role("button", name="稍后继续", exact=True).click()
    page.reload()
    expect(task).to_have_count(0)
    page.locator("#openHelpButton").click()
    page.get_by_role("button", name="继续首次创作教学", exact=True).click()
    expect(task).to_contain_text("方向已确认，接着安排场景")
    composer.locator("textarea").fill("请整理章节和场景结构，一章一场，结束在提示灯第一次回应。")
    composer.locator('[type="submit"]').click()
    page.get_by_role("button", name="整理章节安排", exact=True).click()
    structure = page.get_by_role("button", name="采用并建立结构", exact=True)
    expect(structure).to_be_visible(timeout=15000)
    expect(task).to_contain_text("确认章节和场景安排")
    expect(task).to_contain_text("建立目录和空白场景")
    structure.click()
    expect(task).to_contain_text("打开这一场的正文")
    draft_view = page.locator('[data-creation-view="draft"]')
    if draft_view.is_visible():
        draft_view.click()
    else:
        expect(task).to_contain_text("视图菜单")
        page.locator("[data-creation-select]").select_option("draft")
    first_scene = service.get_work(work_id)["chapters"][0]["scenes"][0]["id"]
    if not page.locator(f'[data-scene="{first_scene}"]').filter(visible=True).count():
        page.locator('[data-panel-toggle="tree"]').filter(visible=True).first.click()
    page.locator(f'[data-scene="{first_scene}"]').filter(visible=True).click()
    expect(task).to_contain_text("先选人物和参考资料")
    if not page.locator("#sceneConversationForm").is_visible():
        page.locator('[data-panel-toggle="inspector"]').filter(visible=True).first.click()
    page.get_by_role("button", name="选择本场人物", exact=True).click()
    expect(task).to_contain_text("为这一场选好人物")
    assert_readable_surface(page, "#sceneContextForm", ".context-check b")
    for choice in page.locator('#sceneContextForm input[name="character_card_ids"]').all():
        choice.check()
    page.get_by_role("button", name="保存资料选择", exact=True).click()
    page.locator('[data-inspector="agent"]').filter(visible=True).click()
    expect(task).to_contain_text("在这里告诉助手")
    scene_composer = page.locator("#sceneConversationForm")
    scene_composer.locator("textarea").fill("起草本场，保持刚才确认的结尾。")
    scene_composer.get_by_role("button", name="发送", exact=True).click()
    expect(page.locator("[data-scene-change]").first).to_be_visible(timeout=15000)
    expect(task).to_contain_text("看看这段写得怎么样")
    expect(task).to_contain_text("保存为正式正文")
    current = service.get_work(work_id)
    assert not any(item["kind"] == "scene_script" for item in current["artifacts"])
    for choice in page.locator("[data-scene-change]").all():
        choice.uncheck()
    expect(task).to_contain_text("先勾选想留下的文字")
    expect(page.locator("[data-apply-scene-changes]").first).to_be_disabled()
    page.locator("[data-scene-change]").first.check()
    expect(task).to_contain_text("勾选想留下的部分")
    expect(task).to_be_in_viewport(ratio=1)
    page.locator("[data-apply-scene-changes]").first.click()
    expect(task).to_have_count(0)
    assert any(item["kind"] == "scene_script" for item in service.get_work(work_id)["artifacts"])
    page.close()


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
    page.locator("[data-chapter-text]").first.click()
    expect(task).to_contain_text("写下你自己的第一段")
    expect(task).not_to_contain_text("保存这段正文")
    field = page.locator("[data-chapter-text]").first
    page.locator("[data-chapter-type]").first.select_option("dialogue")
    replace_paragraph(page, field, "这是我自己的第一段故事。")
    expect(task).to_contain_text("先把这一段填好")
    page.locator("[data-chapter-speaker]").first.fill("爱丽丝")
    expect(task).to_contain_text("写好后，点这里保存")
    field.click()
    assert field.evaluate("node=>node.contains(getSelection().anchorNode)")
    assert_pointer_clear_of(page, field)
    page.locator("[data-chapter-save]").click()
    expect(task).to_have_count(0)
    expect(
        page.get_by_text("正文保存好了。接下来可以自己写了，想重看操作时去“帮助”就行。", exact=True)
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
    expect(task).to_contain_text("点“Agent”")
    toggle.click()
    expect(task).to_contain_text("在这里告诉助手")
    field = page.locator('#sceneConversationForm textarea[name="text"]')
    field.click()
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
    expect(task).to_contain_text("看看这段写得怎么样")
    expect(task).to_contain_text("读一遍新稿")
    expect(task).not_to_contain_text("改前")
    expect(task).to_be_in_viewport(ratio=1)
    screenshot(page, "first-use-review-light-1600")
    assert not service.get_work(work_id)["chapters"][0]["scenes"][0]["current_revision_id"]
    expect(page.locator("[data-scene-change]").first).to_be_visible()
    page.locator(f'[data-apply-scene-changes="{candidate["proposal_id"]}"]').first.click()
    expect(task).to_have_count(0)
    expect(
        page.get_by_text("正文保存好了。接下来可以自己写了，想重看操作时去“帮助”就行。", exact=True)
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


def test_spotlight_tracks_panel_resize_without_a_page_redraw(local_authoring, browser):
    service, url = local_authoring
    work_id, scene_id, work = create_ready_scene(service, title="调整面板时继续写")
    page = open_page(
        browser,
        f"{url}/?section=writing&stage=draft&work_id={work_id}&scene_id={scene_id}",
        "light",
        (1600, 900),
    )
    page.wait_for_function(
        "() => state.context?.scene_id === state.sceneId && Boolean(sceneConversationThread(selectedScene())) && !state._contextLoadingScene"
    )
    page.locator("#openHelpButton").click()
    page.get_by_role("button", name="重看新手教学", exact=True).click()
    task = page.get_by_role("region", name="首次创作教学")
    expect(task).to_contain_text("在这里告诉助手")
    field = page.locator('#sceneConversationForm textarea[name="text"]')
    field.click()
    field.fill("保留这句正在写的要求")
    form = page.locator("#sceneConversationForm")
    before = form.bounding_box()
    resize = page.locator('[data-panel-resize="inspector"]')
    resize.press("Home")
    resize.press("ArrowLeft")
    resize.press("ArrowLeft")
    after = form.bounding_box()
    assert abs(after["x"] - before["x"]) > 10
    page.wait_for_function(
        """() => {
          const hole = document.querySelector('.hc-first-use-layer mask rect:nth-child(2)');
          const form = document.querySelector('#sceneConversationForm').getBoundingClientRect();
          return hole && Math.abs(Number(hole.getAttribute('x')) - (form.left - 5)) < 2;
        }""",
        timeout=2000,
    )
    expect(field).to_have_value("保留这句正在写的要求")
    assert_pointer_clear_of(page, field)
    screenshot(page, "first-use-spotlight-panel-resize-light-1600")
    page.close()


@pytest.mark.parametrize("has_prose", [False, True])
def test_direct_document_teaching_needs_no_mode_switch(local_authoring, browser, has_prose):
    service, url = local_authoring
    work = service.create_work({"title": "阅读时继续教学", "world_seed": "blank"})
    made = service.create_scene(
        work["id"],
        work["chapters"][0]["id"],
        {"expected_version": work["version"], "title": "自己的开场"},
    )
    if has_prose:
        service.save_scene_manuscript(
            work["id"],
            made["scene_id"],
            {
                "expected_version": made["work"]["version"],
                "base_revision_id": None,
                "blocks": [
                    {"id": "block-first-line", "type": "narration", "text": "保留原来这一句。"}
                ],
            },
        )
    page = open_page(
        browser,
        f"{url}/?section=writing&stage=draft&work_id={work['id']}&scene_id={made['scene_id']}",
        "dark",
        (1280, 720),
    )
    page.wait_for_function("() => Boolean(sceneConversationThread(selectedScene()))")
    page.locator("#openHelpButton").click()
    page.get_by_role("button", name="重看新手教学", exact=True).click()
    task = page.get_by_role("region", name="首次创作教学")
    expect(page.locator("[data-chapter-view]")).to_have_count(0)
    expect(task).to_contain_text("直接")
    field = page.locator("[data-chapter-text]").first
    assert_pointer_clear_of(page, field)
    if has_prose:
        expect(field).to_have_text("保留原来这一句。")
    replace_paragraph(page, field, "我在自己的作品里继续写。")
    expect(task).to_contain_text("写好后，点这里保存")
    expect(field).to_have_text("我在自己的作品里继续写。")
    page.locator("[data-chapter-save]").click()
    expect(task).to_have_count(0)
    page.close()
