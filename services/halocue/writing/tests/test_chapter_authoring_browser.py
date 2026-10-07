"""Chapter editing uses one atomic save while retaining scene revisions."""

from pathlib import Path

from test_authoring_workspace_browser import browser as browser, local_authoring as local_authoring
from halocue_writing.providers import FakeWritingProvider


def test_continuous_chapter_edit_saves_two_scenes_atomically(local_authoring, browser):
    service, url = local_authoring
    work = service.create_work({"title": "连续正文", "world_seed": "blank"})
    chapter = work["chapters"][0]["id"]
    first = service.create_scene(work["id"], chapter, {"expected_version": work["version"], "title": "第一场"})
    service.create_scene(work["id"], chapter, {"expected_version": first["work"]["version"], "title": "第二场"})
    page = browser.new_page(viewport={"width": 1366, "height": 768})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"{url}/?section=writing&stage=draft&work_id={work['id']}")
    page.locator(".chapter-authoring-scene").first.wait_for()
    page.wait_for_function("() => Boolean(sceneConversationThread(selectedScene()))")
    initial_version = service.get_work(work["id"])["version"]
    assert page.locator(".chapter-authoring-scene").count() == 2
    for index, text in enumerate(("第一场手写正文", "第二场手写正文")):
        scene = page.locator(".chapter-authoring-scene").nth(index)
        scene.locator("[data-chapter-add]").click()
        scene.locator("[data-chapter-text]").fill(text)
    page.locator("[data-chapter-save]").click()
    from playwright.sync_api import expect
    expect(page.locator("[data-chapter-save-state]")).to_have_text("整章已保存")
    assert not errors
    saved = service.get_work(work["id"])
    assert saved["version"] == initial_version + 1
    assert {item["current_revision"]["content"]["blocks"][0]["text"]
            for item in saved["artifacts"] if item["kind"] == "scene_script"} == {
                "第一场手写正文", "第二场手写正文"
            }
    page.reload()
    expect(page.locator("[data-chapter-text]").first).to_have_value("第一场手写正文")
    expect(page.locator("[data-chapter-text]").nth(1)).to_have_value("第二场手写正文")
    page.close()


def test_background_scene_thread_response_preserves_typing_focus(local_authoring, browser):
    from playwright.sync_api import expect

    service, url = local_authoring
    work = service.create_work({"title": "输入期间读取对话", "world_seed": "blank"})
    made = service.create_scene(work["id"], work["chapters"][0]["id"], {
        "expected_version": work["version"], "title": "正文",
    })
    page = browser.new_page()
    held = []

    def hold_thread(route):
        if route.request.method != "POST":
            route.continue_()
            return
        held.append((route, route.fetch()))

    page.route("**/api/v1/works/*/threads", hold_thread)
    page.goto(f"{url}/?section=writing&stage=draft&work_id={work['id']}")
    page.locator("[data-chapter-add]").click()
    field = page.locator("[data-chapter-text]")
    field.fill("手写")
    expect(field).to_be_focused()
    assert held
    held[0][0].fulfill(response=held[0][1])
    page.wait_for_function("() => Boolean(sceneConversationThread(selectedScene()))")
    expect(field).to_be_focused()
    page.keyboard.type("正文")
    expect(field).to_have_value("手写正文")
    page.locator("[data-chapter-save]").click()
    expect(page.locator("[data-chapter-save-state]")).to_have_text("整章已保存")
    revision = next(a for a in service.get_work(work["id"])["artifacts"]
                    if a["kind"] == "scene_script" and a["scope_id"] == made["scene_id"])
    assert revision["current_revision"]["content"]["blocks"][0]["text"] == "手写正文"
    page.close()


def test_reading_mode_preserves_draft_and_saves_from_preview(local_authoring, browser):
    service, url = local_authoring
    work = service.create_work({"title": "阅读与编辑", "world_seed": "blank"})
    chapter = work["chapters"][0]["id"]
    created = service.create_scene(work["id"], chapter, {"expected_version": work["version"], "title": "第一场"})
    page = browser.new_page()
    page.goto(f"{url}/?section=writing&stage=draft&work_id={work['id']}&chapter_id={chapter}&scene_id={created['scene_id']}")
    scene = page.locator(".chapter-authoring-scene").first
    scene.locator("[data-chapter-add]").click()
    scene.locator("[data-chapter-text]").fill("未保存的手写正文")
    page.locator('[data-chapter-view="read"]').click()
    from playwright.sync_api import expect
    expect(scene.locator("[data-chapter-read-block]")).to_contain_text("未保存的手写正文")
    expect(page.locator("[data-chapter-save]")).to_be_enabled()
    scene.locator("[data-chapter-read-block]").click()
    expect(scene.locator("[data-chapter-text]")).to_be_focused()
    expect(scene.locator("[data-chapter-text]")).to_have_value("未保存的手写正文")
    page.locator('[data-chapter-view="read"]').click()
    page.locator("[data-chapter-save]").click()
    expect(page.locator("[data-chapter-save-state]")).to_have_text("整章已保存")
    saved = service.get_work(work["id"])
    assert next(item for item in saved["artifacts"] if item["kind"] == "scene_script")["current_revision"]["content"]["blocks"][0]["text"] == "未保存的手写正文"
    page.close()


def test_empty_chapter_starts_writing_without_ai(local_authoring, browser):
    service, url = local_authoring
    work = service.create_work({"title": "空章手写", "world_seed": "blank"})
    page = browser.new_page()
    page.goto(f"{url}/?section=writing&stage=draft&work_id={work['id']}")
    page.locator("[data-chapter-start]").click()
    from playwright.sync_api import expect
    expect(page.locator("[data-chapter-text]")).to_have_count(1)
    page.locator("[data-chapter-text]").fill("直接开始本章。")
    page.locator("[data-chapter-save]").click()
    expect(page.locator("[data-chapter-save-state]")).to_have_text("整章已保存")
    assert service.get_work(work["id"])["chapters"][0]["scenes"][0]["title"] == "正文"
    page.close()


def test_reload_with_new_server_revision_requires_explicit_rebase(local_authoring, browser):
    service, url = local_authoring
    work = service.create_work({"title": "章草稿冲突", "world_seed": "blank"})
    chapter = work["chapters"][0]["id"]
    made = service.create_scene(work["id"], chapter, {"expected_version": work["version"], "title": "正文"})
    page = browser.new_page()
    page.on("dialog", lambda dialog: dialog.accept())
    page.goto(f"{url}/?section=writing&stage=draft&work_id={work['id']}")
    page.locator("[data-chapter-add]").click()
    page.locator("[data-chapter-text]").fill("本地写作草稿")
    current = service.get_work(work["id"])
    service.save_scene_manuscript(work["id"], made["scene_id"], {
        "expected_version": current["version"],
        "blocks": [{"id": "block-server", "type": "narration", "speaker": "", "text": "另一窗口的正文"}],
    })
    page.reload()
    from playwright.sync_api import expect
    expect(page.locator(".chapter-authoring-conflict")).to_be_visible()
    expect(page.locator("[data-chapter-text]")).to_have_value("本地写作草稿")
    expect(page.locator("[data-chapter-save]")).to_be_disabled()
    page.locator(".chapter-authoring-conflict summary").click()
    assert "另一窗口的正文" in page.locator(".chapter-authoring-conflict").inner_text()
    page.locator("[data-chapter-rebase]").click()
    expect(page.locator("[data-chapter-save]")).to_be_enabled()
    page.locator("[data-chapter-save]").click()
    expect(page.locator("[data-chapter-save-state]")).to_have_text("整章已保存")
    page.close()


def test_chapter_review_runs_once_and_records_author_decision(local_authoring, browser):
    service, url = local_authoring
    service.provider = FakeWritingProvider()
    work = service.create_work({"title": "整章检查", "world_seed": "blank"})
    chapter = work["chapters"][0]["id"]
    made = service.create_scene(work["id"], chapter, {"expected_version": work["version"], "title": "正文"})
    service.save_scene_manuscript(work["id"], made["scene_id"], {
        "expected_version": made["work"]["version"],
        "blocks": [{"id": "block-review", "type": "narration", "speaker": "", "text": "夜里，学生归还了借阅卡。"}],
    })
    page = browser.new_page()
    page.goto(f"{url}/?section=writing&stage=draft&work_id={work['id']}")
    page.locator("[data-chapter-review-run]").click()
    from playwright.sync_api import expect
    expect(page.locator(".chapter-review-status")).to_have_text("待确认剧情记忆", timeout=20000)
    field = page.locator("[data-chapter-text]").first
    original = field.input_value()
    field.fill(original + "新增内容")
    expect(page.locator('[data-chapter-review-decide="keep"]')).to_be_disabled()
    field.fill(original)
    page.locator('[data-chapter-review-decide="keep"]').click()
    expect(page.locator(".chapter-review-status")).to_have_text("检查完成")
    assert service.authoring.chapters.get(work["id"], chapter)["result"]["decision"] == "keep"
    page.close()


def test_chapter_prose_uses_main_width_and_has_no_inner_scroll(local_authoring, browser):
    service, url = local_authoring
    work = service.create_work({"title": "长篇正文排版", "world_seed": "blank"})
    chapter = work["chapters"][0]["id"]
    for scene_index in range(2):
        made = service.create_scene(work["id"], chapter, {
            "expected_version": work["version"], "title": f"第{scene_index + 1}场",
        })
        blocks = [{
            "id": f"block-{scene_index}-{block_index}",
            "type": "dialogue" if block_index % 2 else "narration",
            "speaker": "爱丽丝" if block_index % 2 else "",
            "text": "雨声沿着档案馆的玻璃滑下。她翻开最后一页，又听见走廊尽头传来轻微的脚步声。" * 2,
        } for block_index in range(4)]
        work = service.save_scene_manuscript(work["id"], made["scene_id"], {
            "expected_version": made["work"]["version"], "blocks": blocks,
        })["work"]
    page = browser.new_page(viewport={"width": 1366, "height": 768})
    page.goto(f"{url}/?section=writing&stage=draft&work_id={work['id']}")
    page.locator("[data-chapter-text]").first.wait_for()
    for _ in range(10):
        metrics = page.locator(".chapter-authoring-block").first.evaluate("""node => {
          const outer=node.getBoundingClientRect(), field=node.querySelector('textarea');
          const text=field.getBoundingClientRect();
          return {outer:outer.width,text:text.width,innerScroll:field.scrollHeight > field.clientHeight+2};
        }""")
        if metrics["outer"]:
            break
        page.wait_for_timeout(100)
    assert metrics["text"] / metrics["outer"] > 0.8
    assert not metrics["innerScroll"]
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    output = Path(__file__).resolve().parents[4] / ".tmp" / "rework-s3-chapter-1366.png"
    output.parent.mkdir(exist_ok=True)
    page.screenshot(path=str(output), full_page=True)
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.screenshot(path=str(output.with_name("rework-s3-chapter-1920.png")), full_page=True)
    page.close()


def test_empty_scene_has_clear_local_start_and_no_paid_review(local_authoring, browser):
    from playwright.sync_api import expect
    service, url = local_authoring
    work = service.create_work({"title": "写作区排布验收", "world_seed": "blank"})
    chapter = work["chapters"][0]["id"]
    made = service.create_scene(work["id"], chapter, {"expected_version": work["version"], "title": "小瞬与点心"})
    page = browser.new_page(viewport={"width": 1280, "height": 820})
    page.goto(f"{url}/?section=writing&stage=draft&work_id={work['id']}&chapter_id={chapter}&scene_id={made['scene_id']}")
    expect(page.locator(".chapter-authoring-empty-scene")).to_be_visible()
    expect(page.get_by_role("button", name="开始写作", exact=True)).to_be_visible()
    expect(page.locator("[data-chapter-review-run]")).to_be_disabled()
    expect(page.get_by_role("heading", name="检查正文与连贯性", exact=True)).to_have_count(1)
    for width in [1280, 820, 390]:
        page.set_viewport_size({"width": width, "height": 820})
        assert page.locator(".chapter-authoring").evaluate("el=>el.scrollWidth<=el.clientWidth+1")
    page.get_by_role("button", name="开始写作", exact=True).click()
    expect(page.locator("[data-chapter-text]")).to_be_focused()
    expect(page.locator(".chapter-authoring-empty-scene")).to_have_count(0)
    page.locator("[data-chapter-text]").fill("测试本地起笔，不调用模型。")
    expect(page.locator("[data-chapter-review-run]")).to_be_disabled()
    saved = service.get_work(work["id"])
    assert not any(item["kind"] == "scene_script" for item in saved["artifacts"])
    assert not saved["agent_runs"]
    page.close()


def test_inserted_paragraph_inherits_previous_type_and_speaker(local_authoring, browser):
    from playwright.sync_api import expect

    service, url = local_authoring
    work = service.create_work({"title": "段落设置继承", "world_seed": "blank"})
    chapter = work["chapters"][0]["id"]
    made = service.create_scene(work["id"], chapter, {
        "expected_version": work["version"], "title": "图书馆",
    })
    service.save_scene_manuscript(work["id"], made["scene_id"], {
        "expected_version": made["work"]["version"],
        "blocks": [
            {"id": "block-narration", "type": "narration", "speaker": "", "text": "雨停了。"},
            {"id": "block-dialogue", "type": "dialogue", "speaker": "安", "text": "明天再来。"},
        ],
    })
    page = browser.new_page()
    page.goto(f"{url}/?section=writing&stage=draft&work_id={work['id']}&chapter_id={chapter}&scene_id={made['scene_id']}")
    scene = page.locator(".chapter-authoring-scene").first

    scene.locator('[data-chapter-add][data-chapter-after="block-dialogue"]').click()
    dialogue = scene.locator("[data-chapter-block]").nth(2)
    expect(dialogue.locator("[data-chapter-type]")).to_have_value("dialogue")
    expect(dialogue.locator("[data-chapter-speaker]")).to_have_value("安")

    scene.locator('[data-chapter-add][data-chapter-after="block-narration"]').click()
    narration = scene.locator("[data-chapter-block]").nth(1)
    expect(narration.locator("[data-chapter-type]")).to_have_value("narration")
    expect(narration.locator("[data-chapter-speaker]")).to_have_value("")
    page.close()


def test_continuous_chapter_exposes_scene_memory_maintenance(local_authoring, browser):
    from playwright.sync_api import expect

    service, url = local_authoring
    work = service.create_work({"title": "场景记忆入口", "world_seed": "blank"})
    chapter = work["chapters"][0]["id"]
    made = service.create_scene(work["id"], chapter, {
        "expected_version": work["version"], "title": "第一场",
    })
    service.save_scene_manuscript(work["id"], made["scene_id"], {
        "expected_version": made["work"]["version"],
        "blocks": [{"id": "block-memory", "type": "narration", "speaker": "", "text": "安决定次日和同伴核对线索。"}],
    })
    page = browser.new_page()
    page.goto(f"{url}/?section=writing&stage=draft&work_id={work['id']}&chapter_id={chapter}&scene_id={made['scene_id']}")
    expect(page.locator(".chapter-authoring-scene")).to_be_visible()
    expect(page.locator("[data-scene-memory]")).to_be_visible()
    expect(page.get_by_role("button", name="沉淀本场变化", exact=True)).to_be_visible()
    page.close()


def test_chapter_review_waits_for_initial_scene_thread(local_authoring, browser, monkeypatch):
    """Automatic thread creation must settle before a versioned chapter review."""
    import threading
    from playwright.sync_api import expect

    service, url = local_authoring
    service.provider = FakeWritingProvider()
    work = service.create_work({'title': '启动版本同步', 'world_seed': 'blank'})
    chapter = work['chapters'][0]['id']
    made = service.create_scene(work['id'], chapter, {'expected_version': work['version'], 'title': '正文'})
    service.save_scene_manuscript(work['id'], made['scene_id'], {
        'expected_version': made['work']['version'],
        'blocks': [{'id': 'block-startup', 'type': 'narration', 'text': '学生归还了借阅卡。'}],
    })
    entered, release = threading.Event(), threading.Event()
    create_thread = service.create_conversation_thread

    def delayed_thread(*args, **kwargs):
        entered.set()
        assert release.wait(15), 'test did not release thread request'
        return create_thread(*args, **kwargs)

    monkeypatch.setattr(service, 'create_conversation_thread', delayed_thread)
    page = browser.new_page()
    try:
        page.goto(f'{url}/?section=writing&stage=draft&work_id={work["id"]}&scene_id={made["scene_id"]}')
        assert entered.wait(5)
        expect(page.locator('[data-chapter-review-run]')).to_be_disabled()
        release.set()
        expect(page.locator('[data-chapter-review-run]')).to_be_enabled()
        page.locator('[data-chapter-review-run]').click()
        expect(page.locator('.chapter-review-status')).to_have_text('待确认剧情记忆', timeout=20000)
    finally:
        release.set()
        page.close()


def test_late_review_status_preserves_manuscript_input_focus(local_authoring, browser, monkeypatch):
    """A read-only status response must leave the author's active editor intact."""
    import threading
    from playwright.sync_api import expect

    service, url = local_authoring
    work = service.create_work({'title': '检查状态不会打断输入', 'world_seed': 'blank'})
    chapter = work['chapters'][0]['id']
    made = service.create_scene(work['id'], chapter, {'expected_version': work['version'], 'title': '正文'})
    saved = service.save_scene_manuscript(work['id'], made['scene_id'], {
        'expected_version': made['work']['version'],
        'blocks': [{'id': 'block-review-focus', 'type': 'narration', 'text': '原来的正文。'}],
    })
    service.create_conversation_thread(work['id'], {
        'expected_version': saved['work']['version'], 'scope_type': 'scene',
        'scope_id': made['scene_id'], 'title': '本场讨论', 'permission_mode': 'review',
    })
    entered, release = threading.Event(), threading.Event()
    route = service.authoring.route

    def delayed_review(method, parts, *args, **kwargs):
        if method == 'GET' and parts and parts[-1] == 'review':
            entered.set()
            assert release.wait(15), 'test did not release status request'
        return route(method, parts, *args, **kwargs)

    monkeypatch.setattr(service.authoring, 'route', delayed_review)
    page = browser.new_page()
    try:
        page.goto(f'{url}/?section=writing&stage=draft&work_id={work["id"]}&chapter_id={chapter}&scene_id={made["scene_id"]}')
        page.locator('[data-chapter-text]').first.wait_for()
        assert entered.wait(5)
        page.wait_for_function('()=>Boolean(state._contextBlocked)')
        field = page.locator('[data-chapter-text]').first
        field.fill('正在修改的正文。')
        field.evaluate('el=>el.setSelectionRange(3,3)')
        expect(field).to_be_focused()
        release.set()
        expect(page.locator('.chapter-review-status')).to_have_text('尚未检查')
        expect(field).to_be_focused()
        expect(field).to_have_value('正在修改的正文。')
        assert field.evaluate('el=>el.selectionStart') == 3
    finally:
        release.set()
        page.close()
