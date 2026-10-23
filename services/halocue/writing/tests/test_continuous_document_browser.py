"""Reading and editing use the same structured, locally bundled document."""

import pytest
import test_authoring_workspace_browser as fixtures
from playwright.sync_api import expect
from manuscript_document_test_support import replace_paragraph

browser = fixtures.browser
local_authoring = fixtures.local_authoring


def open_document(local_authoring, browser, blocks=None, width=1920, theme="light"):
    service, url = local_authoring
    work = service.create_work({"title": "连续正文", "world_seed": "blank"})
    scene = service.create_scene(
        work["id"],
        work["chapters"][0]["id"],
        {"expected_version": work["version"], "title": "自己的开场"},
    )
    if blocks is not None:
        service.save_scene_manuscript(
            work["id"],
            scene["scene_id"],
            {"expected_version": scene["work"]["version"], "blocks": blocks},
        )
    page = browser.new_page(viewport={"width": width, "height": 1080 if width == 1920 else 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(f"localStorage.setItem('halocue.theme', '{theme}')")
    page.goto(
        f"{url}/?section=writing&stage=draft&work_id={work['id']}&scene_id={scene['scene_id']}"
    )
    page.locator(".chapter-document-content").wait_for()
    page.wait_for_function("() => Boolean(sceneConversationThread(selectedScene()))")
    return service, work["id"], scene["scene_id"], page, errors


def saved_blocks(service, work_id, scene_id):
    return next(
        a
        for a in service.get_work(work_id)["artifacts"]
        if a["kind"] == "scene_script" and a["scope_id"] == scene_id
    )["current_revision"]["content"]["blocks"]


@pytest.mark.parametrize("width,theme", [(1920, "light"), (1920, "dark"), (390, "dark")])
def test_direct_typing_split_join_and_structural_undo(local_authoring, browser, width, theme):
    service, work_id, scene_id, page, errors = open_document(
        local_authoring, browser, width=width, theme=theme
    )
    expect(page.locator("[data-chapter-view]")).to_have_count(0)
    field = page.locator("[data-chapter-text]").first
    replace_paragraph(page, field, "深夜，提示灯亮起。")
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    expect(page.locator("[data-chapter-text]")).to_have_count(2)
    page.keyboard.insert_text("爱丽丝停下脚步。")
    expect(page.locator("[data-chapter-text]").nth(1)).to_have_text("爱丽丝停下脚步。")
    ids = page.locator("[data-chapter-block]").evaluate_all(
        "nodes=>nodes.map(node=>node.dataset.blockId)"
    )
    assert len(set(ids)) == 2
    page.keyboard.press("Shift+Enter")
    page.keyboard.insert_text("窗外传来脚步声。")
    expect(page.locator("[data-chapter-text]")).to_have_count(2)
    assert (
        page.locator("[data-chapter-text]").nth(1).inner_text()
        == "爱丽丝停下脚步。\n窗外传来脚步声。"
    )
    page.locator("[data-chapter-text]").nth(1).evaluate("""node=>{
      const range=document.createRange();range.setStart(node.firstChild,0);range.collapse(true);
      getSelection().removeAllRanges();getSelection().addRange(range);
    }""")
    page.keyboard.press("Backspace")
    expect(page.locator("[data-chapter-text]")).to_have_count(1)
    page.keyboard.press("Control+z")
    expect(page.locator("[data-chapter-text]")).to_have_count(2)
    page.keyboard.press("Control+Shift+z")
    expect(page.locator("[data-chapter-text]")).to_have_count(1)
    expect(page.locator("#saveStatus")).to_have_text("正文未保存")
    page.keyboard.press("Control+s")
    expect(page.locator("[data-chapter-save-state]")).to_have_text("整章已保存")
    assert len(saved_blocks(service, work_id, scene_id)) == 1
    assert saved_blocks(service, work_id, scene_id)[0]["id"] == ids[0]
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert errors == []
    page.close()


def test_native_composition_and_async_refresh_keep_caret_and_history(local_authoring, browser):
    service, work_id, scene_id, page, errors = open_document(local_authoring, browser)
    field = page.locator("[data-chapter-text]").first
    field.click()
    cdp = page.context.new_cdp_session(page)
    cdp.send("Input.imeSetComposition", {"text": "爱丽丝", "selectionStart": 3, "selectionEnd": 3})
    page.evaluate("render()")  # A real response requests a root refresh during IME input.
    cdp.send("Input.insertText", {"text": "爱丽丝"})
    expect(field).to_have_text("爱丽丝")
    page.wait_for_function("()=>!hcComposing && !hcRenderAgain")
    assert field.evaluate("node=>node.contains(getSelection().anchorNode)")
    page.keyboard.insert_text("停下了脚步。")
    expect(field).to_have_text("爱丽丝停下了脚步。")
    assert field.get_attribute("aria-label") == "第 1 段正文"
    page.keyboard.press("Control+s")
    expect(page.locator("[data-chapter-save-state]")).to_have_text("整章已保存")
    assert saved_blocks(service, work_id, scene_id)[0]["text"] == "爱丽丝停下了脚步。"
    assert field.evaluate("node=>node.contains(getSelection().anchorNode)")
    assert errors == []
    page.close()


def test_click_in_sentence_places_caret_at_clicked_text(local_authoring, browser):
    original = "雨声沿着窗沿落下。她停在了门口。"
    _, _, _, page, errors = open_document(
        local_authoring, browser, [{"id": "block-click", "type": "narration", "text": original}]
    )
    field = page.locator("[data-chapter-text]").first
    point = field.evaluate("""node=>{
      const range=document.createRange();range.setStart(node.firstChild,5);range.setEnd(node.firstChild,6);
      const r=range.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};
    }""")
    page.mouse.click(point["x"], point["y"])
    offset = field.evaluate("node=>getSelection().anchorOffset")
    assert offset in (5, 6)
    page.keyboard.insert_text("轻轻")
    expect(field).to_have_text(original[:offset] + "轻轻" + original[offset:])
    assert errors == []
    page.close()


def test_cross_paragraph_selection_paste_and_history_survive_save(local_authoring, browser):
    originals = [
        {"id": "block-first", "type": "narration", "text": "甲乙丙丁"},
        {"id": "block-second", "type": "dialogue", "speaker": "爱丽丝", "text": "戊己庚辛"},
        {"id": "block-third", "type": "action", "text": "原样保留"},
    ]
    service, work_id, scene_id, page, errors = open_document(local_authoring, browser, originals)
    points = page.evaluate("""()=>{
      const fields=document.querySelectorAll('[data-chapter-text]');
      const point=node=>{const r=document.createRange();r.setStart(node.firstChild,2);r.setEnd(node.firstChild,3);const b=r.getBoundingClientRect();return {x:b.x+1,y:b.y+b.height/2};};
      return [point(fields[0]),point(fields[1])];
    }""")
    page.mouse.move(points[0]["x"], points[0]["y"])
    page.mouse.down()
    page.mouse.move(points[1]["x"], points[1]["y"], steps=12)
    page.mouse.up()
    page.wait_for_function("""()=>{
      const key=document.querySelector('.chapter-document-content').dataset.documentKey;
      const s=HaloCueManuscriptDocument.get(key).view.state.selection;
      return !s.empty && !s.$from.sameParent(s.$to);
    }""")
    page.keyboard.insert_text("替换")
    assert page.locator("[data-chapter-text]").count() == 2, page.locator(
        "[data-chapter-text]"
    ).all_text_contents()
    expect(page.locator("[data-chapter-text]").first).to_have_text("甲乙替换庚辛")
    page.locator("[data-chapter-save]").click()
    expect(page.locator("[data-chapter-save-state]")).to_have_text("整章已保存")
    page.keyboard.press("Control+z")
    expect(page.locator("[data-chapter-text]")).to_have_count(3)
    expect(page.locator("[data-chapter-text]").nth(1)).to_have_text("戊己庚辛")
    expect(page.locator("#saveStatus")).to_have_text("正文未保存")
    page.keyboard.press("Control+Shift+z")
    expect(page.locator("[data-chapter-text]")).to_have_count(2)
    page.keyboard.press("End")
    page.evaluate("""() => {
      const data=new DataTransfer();data.setData('text/plain','第一行\\n第二行');
      document.querySelector('.chapter-document-content').dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data}));
    }""")
    expect(page.locator("[data-chapter-text]")).to_have_count(3)
    page.keyboard.press("Control+s")
    expect(page.locator("[data-chapter-save-state]")).to_have_text("整章已保存")
    blocks = saved_blocks(service, work_id, scene_id)
    assert blocks[-1]["id"] == "block-third" and blocks[-1]["text"] == "原样保留"
    assert len({b["id"] for b in blocks}) == len(blocks)
    assert errors == []
    page.close()


def test_text_selection_only_scopes_assistant_after_explicit_action(local_authoring, browser):
    _, _, _, page, errors = open_document(
        local_authoring,
        browser,
        [{"id": "block-agent-selection", "type": "narration", "text": "提示灯终于暗了下去。"}],
    )
    page.locator("[data-chapter-text]").first.click()
    page.locator("[data-chapter-text]").first.evaluate("""node=>{
      const range=document.createRange();range.setStart(node.firstChild,0);range.setEnd(node.firstChild,3);
      getSelection().removeAllRanges();getSelection().addRange(range);
    }""")
    actions = page.get_by_role("group", name="选中正文的操作")
    expect(actions).to_be_visible()
    assert page.evaluate("state.sceneTextSelection") is None
    actions.get_by_role("button", name="建议改写", exact=True).click()
    expect(page.locator("#sceneConversationForm textarea")).to_be_focused()
    assert page.evaluate("state.sceneTextSelection.quote") == "提示灯"
    expect(page.locator("#sceneConversationForm textarea")).to_have_value(
        "帮我把这段改得自然些，保留原意和人物语气。"
    )
    assert errors == []
    page.close()
