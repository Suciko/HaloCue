"""Document commands stay reachable without a permanent button shelf."""

import pytest
import test_authoring_workspace_browser as fixtures
from playwright.sync_api import expect
from manuscript_document_test_support import replace_paragraph
from test_continuous_document_browser import open_document, saved_blocks

browser = fixtures.browser
local_authoring = fixtures.local_authoring


@pytest.mark.parametrize("width,theme", [(1920, "light"), (1600, "light"), (390, "dark")])
def test_disclosed_commands_keep_save_history_and_keyboard_access(
    local_authoring, browser, width, theme
):
    text = "走廊里只剩下提示灯的微光。"
    service, work_id, scene_id, page, errors = open_document(
        local_authoring,
        browser,
        blocks=[{"id": "block-quiet-one", "type": "narration", "speaker": "", "text": text}],
        width=width,
        theme=theme,
    )
    chapter_menu = page.get_by_label("章节操作", exact=True)
    scene_menu = page.get_by_label("本场操作", exact=True)
    save = page.locator("[data-chapter-save]")
    field = page.locator("[data-chapter-text]")
    expect(save).not_to_be_visible()
    expect(page.get_by_role("button", name="任务包交换", exact=True)).not_to_be_visible()
    expect(page.get_by_role("button", name="记录本场进展", exact=True)).not_to_be_visible()
    expect(page.locator(".chapter-authoring-save")).to_have_count(0)

    chapter_menu.focus()
    page.keyboard.press("Enter")
    expect(page.locator("[data-chapter-undo]")).to_be_disabled()
    expect(page.get_by_role("button", name="任务包交换", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    expect(chapter_menu).to_be_focused()
    expect(page.get_by_role("button", name="任务包交换", exact=True)).not_to_be_visible()

    replace_paragraph(page, field, text + "爱丽丝停下脚步。")
    expect(save).to_be_visible()
    chapter_menu.click()
    page.locator("[data-chapter-undo]").click()
    expect(field).to_have_text(text)
    expect(save).not_to_be_visible()
    expect(page.locator(".chapter-document-content")).to_be_focused()
    chapter_menu.click()
    page.locator("[data-chapter-redo]").click()
    expect(field).to_have_text(text + "爱丽丝停下脚步。")
    save.click()
    expect(page.locator("[data-chapter-save-state]")).to_have_text("整章已保存")
    expect(save).not_to_be_visible()
    assert saved_blocks(service, work_id, scene_id)[0]["text"] == field.inner_text()

    scene_menu.click()
    expect(page.get_by_role("button", name="记录本场进展", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="本场无需记录", exact=True)).to_be_visible()
    field.click(position={"x": 2, "y": 4})
    expect(page.get_by_role("button", name="记录本场进展", exact=True)).not_to_be_visible()
    expect(page.locator(".chapter-document-content")).to_be_focused()

    chapter_menu.click()
    page.get_by_role("button", name="任务包交换", exact=True).click()
    expect(page.locator("#externalAgentDialog")).to_be_visible()
    page.locator("[data-external-close]").click()
    expect(page.locator("#externalAgentDialog")).not_to_be_visible()
    expect(chapter_menu).to_be_focused()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width > 760:
        paragraph = field.bounding_box()
        header = page.locator(".chapter-continuous-head").bounding_box()
        assert paragraph["y"] < 360
        assert paragraph["y"] >= header["y"] + header["height"]
    assert not errors
    page.close()


def test_paragraph_menu_moves_and_removes_with_undo(local_authoring, browser):
    _, _, _, page, errors = open_document(
        local_authoring,
        browser,
        blocks=[
            {"id": "block-first", "type": "narration", "speaker": "", "text": "先查看提示灯。"},
            {"id": "block-second", "type": "narration", "speaker": "", "text": "再核对终端记录。"},
        ],
        width=1600,
    )
    page.locator("[data-chapter-block]").nth(1).hover()
    page.get_by_label("第 2 段操作", exact=True).click()
    page.get_by_role("button", name="上移段落", exact=True).last.click()
    expect(page.locator("[data-chapter-text]").first).to_have_text("再核对终端记录。")
    page.keyboard.press("Control+z")
    expect(page.locator("[data-chapter-text]").first).to_have_text("先查看提示灯。")
    page.locator("[data-chapter-block]").nth(1).hover()
    page.get_by_label("第 2 段操作", exact=True).click()
    page.get_by_role("button", name="删除段落", exact=True).last.click()
    expect(page.locator("[data-chapter-text]")).to_have_count(1)
    page.keyboard.press("Control+z")
    expect(page.locator("[data-chapter-text]")).to_have_count(2)
    expect(page.locator("[data-chapter-save]")).not_to_be_visible()
    assert not errors
    page.close()


def test_pending_memory_decision_stays_visible_outside_menu(local_authoring, browser):
    from halocue_writing.providers import FakeWritingProvider

    service, work_id, scene_id, page, errors = open_document(
        local_authoring,
        browser,
        blocks=[
            {
                "id": "block-memory",
                "type": "narration",
                "speaker": "",
                "text": "爱丽丝决定明天核对线索。",
            }
        ],
    )
    service.provider = FakeWritingProvider()
    service.generate_memory_proposal(
        work_id, scene_id, {"expected_version": service.get_work(work_id)["version"]}
    )
    page.reload()
    action = page.get_by_role("button", name="审查记忆候选", exact=True)
    expect(action).to_be_visible()
    expect(page.get_by_label("本场操作", exact=True)).not_to_be_visible()
    action.click()
    expect(page.get_by_role("region", name="本场长期记忆候选", exact=True)).to_be_visible()
    assert not service.get_work(work_id)["memories"]
    assert not errors
    page.close()
