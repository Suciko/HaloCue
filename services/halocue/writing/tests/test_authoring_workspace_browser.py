"""Exercise world-first and outline authoring through the real local HTTP UI."""

import threading
from services.halocue.http_server import LocalHTTPServer as ThreadingHTTPServer
from services.halocue._test_support import CHROMIUM_UNSAFE_PORTS
from pathlib import Path

import pytest

from halocue_writing.app import make_handler
from halocue_writing.service import WritingService


WEB = Path(__file__).resolve().parents[1] / "web"


@pytest.fixture
def local_authoring(tmp_path):
    service = WritingService(tmp_path)
    service.start()
    for _ in range(100):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, WEB))
        if server.server_port not in CHROMIUM_UNSAFE_PORTS:
            break
        server.server_close()
    else:
        service.close()
        raise RuntimeError("No available browser-safe test port")
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
        browser = driver.chromium.launch()
        yield browser
        browser.close()


def test_chapter_outline_shows_adopted_plan_and_opens_scoped_discussion(local_authoring, browser):
    service, url = local_authoring
    work = service.create_work({"title": "章纲展示", "idea": "两位学生夜访档案室。"})
    card = service.save_character_card(work["id"], {
        "expected_version": work["version"], "card_id": "student-a", "name": "学生甲",
        "source_type": "custom", "trust_status": "confirmed", "source_refs": ["用户设定"],
    })
    brief = service.save_brief(work["id"], {
        "expected_version": card["work"]["version"], "idea": "两位学生夜访档案室。", "intent_only": True,
    })
    blueprint = service.generate_blueprint(work["id"], {"expected_version": brief["work"]["version"]})
    confirmed = service.confirm_blueprint(work["id"], {
        "expected_version": blueprint["work"]["version"], "mode": "bond_short",
        "character_card_ids": ["student-a"], "sensei_presence": "auto",
    })
    chapter_id = confirmed["work"]["chapters"][0]["id"]
    created = service.create_scene(work["id"], chapter_id, {
        "expected_version": confirmed["work"]["version"], "title": "第一场",
    })
    thread = created["work"]["conversation_threads"][0]
    discussed = service.post_conversation_message(work["id"], thread["id"], {
        "expected_thread_version": thread["version"], "text": "本章先核对记录，再发现矛盾。",
        "task_scope": {"surface": "chapter", "chapter_id": chapter_id},
    })
    thread = discussed["work"]["conversation_threads"][0]
    proposed = service.organize_conversation_proposal(work["id"], thread["id"], {
        "expected_version": discussed["work"]["version"],
        "expected_thread_version": thread["version"],
        "task_scope": {"surface": "chapter", "chapter_id": chapter_id},
    })
    accepted = service.accept_proposal(work["id"], proposed["proposal_id"], {
        "expected_version": proposed["work"]["version"],
    })
    plan = next(item for item in accepted["work"]["artifacts"] if item["kind"] == "chapter_plan")["current_revision"]["content"]
    page = browser.new_page(viewport={"width": 1366, "height": 768})
    page.goto(f"{url}/?section=writing&stage=structure&work_id={work['id']}&chapter_id={chapter_id}&scene_id={created['scene_id']}")
    from playwright.sync_api import expect
    expect(page.locator(".outline-plan-accepted")).to_contain_text(plan["chapter_goal"])
    expect(page.locator(".outline-plan-accepted li")).to_have_count(len(plan["beats"]) + len(plan["continuity_notes"]))
    page.locator("[data-outline-discuss]").click()
    page.wait_for_url("**section=works**")
    expect(page.locator("#workConversationForm textarea")).to_be_focused()
    expect(page.locator(".work-agent-thread")).to_contain_text("本章先核对记录，再发现矛盾。")
    page.close()


def test_world_first_copy_and_outline_survive_reload(local_authoring, browser):
    service, url = local_authoring
    page = browser.new_page(viewport={"width": 1366, "height": 768})
    page.goto(f"{url}/?section=projects")
    page.get_by_role("button", name="世界底稿").first.click()
    page.locator("#worldDraftForm").wait_for()
    page.locator("#worldDraftForm [name=title]").fill("雨后的学院")
    page.locator("#worldDraftForm [name=overview]").fill("午夜的旧机房会回应学生。")
    page.locator("#worldDraftForm [type=submit]").click()
    page.wait_for_url("**world_id=*")
    page.locator("#worldCreateWorkForm [name=title]").fill("旧机房故事")
    page.locator("#worldCreateWorkForm [name=destination]").select_option("outline")
    page.locator("#worldCreateWorkForm [type=submit]").click()
    page.wait_for_url("**stage=structure*")
    page.locator("#outlineText").wait_for()
    page.locator("#outlineText").fill("总纲：寻找旧机房的秘密。")
    page.locator("#outlineDocumentForm [type=submit]").click()
    from playwright.sync_api import expect
    expect(page.locator(".authoring-outline-state")).to_have_text("已保存")
    page.reload()
    expect(page.locator("#outlineText")).to_have_value("总纲：寻找旧机房的秘密。")
    page.locator('[data-outline-scope^="volume:"]').first.click()
    expect(page.locator("#outlineText")).to_have_value("")
    page.locator('[data-outline-scope^="work:"]').first.click()
    expect(page.locator("#outlineText")).to_have_value("总纲：寻找旧机房的秘密。")
    world = service.authoring.list_worlds()[0]
    assert service.authoring.get_world(world["id"])["content"]["overview"] == "午夜的旧机房会回应学生。"
    page.close()


def test_outline_conflict_preserves_draft_and_retries_against_current_version(local_authoring, browser):
    service, url = local_authoring
    work = service.create_work({"title": "大纲冲突样本", "world_seed": "blank"})
    page = browser.new_page()
    page.goto(f"{url}/?section=writing&stage=structure&work_id={work['id']}")
    page.locator("#outlineText").wait_for()
    page.locator("#outlineText").fill("本地草稿")
    service.authoring.save_outline(work["id"], {
        "expected_version": work["version"],
        "scope_type": "work", "scope_id": work["id"],
        "expected_base_revision_id": None, "text": "另一窗口的版本",
    })
    page.locator("#outlineDocumentForm [type=submit]").click()
    page.get_by_text("重新载入比较").first.wait_for()
    assert page.locator("#outlineText").input_value() == "本地草稿"
    page.get_by_text("重新载入比较").first.click()
    from playwright.sync_api import expect
    expect(page.locator(".authoring-conflict-compare pre").first).to_have_text("另一窗口的版本")
    expect(page.locator("#outlineText")).to_have_value("本地草稿")
    page.locator("[data-outline-rebase]").click()
    page.locator("#outlineDocumentForm [type=submit]").click()
    expect(page.locator(".authoring-outline-state")).to_have_text("已保存")
    assert service.authoring.get_outline(work["id"])["documents"][0]["text"] == "本地草稿"
    page.close()


def test_work_world_overview_save_preserves_world_cards(local_authoring, browser):
    service, url = local_authoring
    world = service.authoring.save_world({"title": "BA 底稿", "world_seed": "ba_starter"})
    work = service.create_work({
        "title": "从底稿起步", "world_draft_id": world["id"],
        "world_draft_revision_id": world["current_revision_id"],
    })
    original_count = len(world["content"]["entities"])
    page = browser.new_page()
    page.goto(f"{url}/?section=references&view=world&work_id={work['id']}")
    textarea = page.locator("#workWorldOverviewText")
    textarea.wait_for()
    assert world["current_revision_id"] in page.locator(".authoring-work-overview").inner_text()
    textarea.fill("这部作品的世界总说明。")
    page.locator("#workWorldOverviewForm [type=submit]").click()
    from playwright.sync_api import expect
    expect(textarea).to_have_value("这部作品的世界总说明。")
    expect(page.locator("#workWorldOverviewForm .authoring-form-actions span")).to_have_text("已保存")
    saved = service.get_work(work["id"])
    content = next(item for item in saved["artifacts"] if item["kind"] == "world_bible")["current_revision"]["content"]
    assert content["overview"] == "这部作品的世界总说明。"
    assert len(content["entities"]) == original_count
    assert service.authoring.get_world(world["id"])["content"]["overview"] != content["overview"]
    page.close()


def test_refreshed_outline_draft_detects_new_server_revision(local_authoring, browser):
    service, url = local_authoring
    work = service.create_work({"title": "大纲刷新冲突", "world_seed": "blank"})
    page = browser.new_page()
    page.on("dialog", lambda dialog: dialog.accept())
    page.goto(f"{url}/?section=writing&stage=structure&work_id={work['id']}")
    field = page.locator("#outlineText")
    field.wait_for()
    field.fill("本地草稿")
    latest = service.get_work(work["id"])
    service.authoring.save_outline(work["id"], {
        "expected_version": latest["version"], "scope_type": "work", "scope_id": work["id"],
        "expected_base_revision_id": None, "text": "外部保存的大纲",
    })
    page.reload()
    from playwright.sync_api import expect
    expect(field).to_have_value("本地草稿")
    expect(page.locator("#outlineDocumentForm [type=submit]")).to_be_disabled()
    assert "外部保存的大纲" in page.locator(".authoring-conflict-compare").inner_text()
    page.locator("[data-outline-rebase]").click()
    expect(page.locator("#outlineDocumentForm [type=submit]")).to_be_enabled()
    page.locator("#outlineDocumentForm [type=submit]").click()
    expect(page.locator(".authoring-outline-state")).to_have_text("已保存")
    page.close()


def test_refreshed_world_draft_detects_new_server_version(local_authoring, browser):
    service, url = local_authoring
    world = service.authoring.save_world({"title": "世界冲突", "overview": "起始"})
    page = browser.new_page()
    page.on("dialog", lambda dialog: dialog.accept())
    page.goto(f"{url}/?section=worlds&world_id={world['id']}")
    page.locator("#worldDraftForm [name=overview]").fill("本地世界")
    service.authoring.save_world({"expected_version": world["version"], "title": "世界冲突", "overview": "外部世界"}, world["id"])
    page.reload()
    from playwright.sync_api import expect
    expect(page.locator("#worldDraftForm [name=overview]")).to_have_value("本地世界")
    expect(page.locator("#worldDraftForm [type=submit]")).to_be_disabled()
    assert "外部世界" in page.locator(".authoring-conflict-compare").inner_text()
    page.locator("[data-world-rebase]").click()
    expect(page.locator("#worldDraftForm [type=submit]")).to_be_enabled()
    page.close()
