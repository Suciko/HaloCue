"""Real UI/service round trip with a synthetic provider and isolated data."""

import re

import pytest
from playwright.sync_api import expect

from services.halocue.writing.tests.test_card_assistance import (
    CardAssistanceProvider,
    make_card_work,
)


def card(service, work_id):
    return next(
        item for item in service.get_work(work_id)["artifacts"] if item["kind"] == "character_card"
    )


@pytest.mark.parametrize("width", [1280, 390])
def test_card_assistance_draft_return_and_partial_acceptance(runtime, width):
    service = runtime.writing_service
    service.provider = CardAssistanceProvider()
    work, context = make_card_work(service)
    base = f"http://127.0.0.1:{runtime.gateway.server_port}"
    with pytest.importorskip("playwright.sync_api").sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(f"{base}/?section=references&view=characters&work_id={work['id']}")
            page.locator(f'[data-edit-card="{context["target_id"]}"]').click()
            page.locator('[name="role"]').fill("这段手写草稿尚未保存")
            page.locator('.library-editor-assist > summary').click()
            page.locator('[data-card-assistance-panel] > summary').click()
            page.get_by_label("这次想怎么改", exact=True).fill(
                "职责更谨慎，知情边界更明确，声音不变"
            )
            page.get_by_role("button", name="带草稿去讨论", exact=True).click()
            expect(page.locator("[data-card-assistance-banner]")).to_be_visible()
            expect(page.locator(".card-assistance-draft-preview pre")).to_contain_text(
                "这段手写草稿尚未保存"
            )
            assert not service.provider.contexts
            assert card(service, work["id"])["current_revision_id"] == context["base_revision_id"]
            page.get_by_role("button", name="返回卡片", exact=True).click()
            expect(page.locator('[name="role"]')).to_have_value("这段手写草稿尚未保存")
            # Re-entering the same unsent request is safe, without detouring to navigation.
            page.get_by_label("这次想怎么改", exact=True).fill("先调整职责和知情边界，保留声音")
            page.get_by_role("button", name="带草稿去讨论", exact=True).click()
            expect(page.locator("#workConversationForm textarea")).to_have_value(
                re.compile("先调整职责和知情边界")
            )
            page.locator('#workConversationForm button[type="submit"]').click()
            organize = page.locator('[data-agent-propose-knowledge="character_card"]')
            expect(organize).to_be_visible(timeout=20000)
            expect(page.get_by_text("助手提供的线索（待核对）", exact=True)).to_be_visible()
            organize.click()
            apply = page.locator("[data-accept-director-proposal][data-partial-knowledge]")
            expect(apply).to_be_visible(timeout=20000)
            expect(page.locator(".card-assistance-provenance").last).to_be_visible()
            assert len(card(service, work["id"])["revisions"]) == 1
            # All writing fields are allowed; choose just the role change.
            checks = page.locator("[data-knowledge-field]")
            for checkbox in checks.all():
                checkbox.set_checked(checkbox.get_attribute("value") == "role")
            apply.click()
            expect(
                page.locator("[data-proposal-card] > summary").filter(has_text="已写入正式资料")
            ).to_be_visible(timeout=10000)
            saved = card(service, work["id"])
            assert len(saved["revisions"]) == 2
            content = saved["current_revision"]["content"]
            assert content["role"] == "在交付档案前先核验老师的来意。"
            assert content["voice_anchors"] == ["短句，温和但不盲从"]
            assert content["knowledge_boundary"] == "只知道公开记录"
            assert content["source_type"] == "custom"
            page.get_by_role("button", name="返回卡片", exact=True).click()
            expect(page.locator('[name="role"]')).to_have_value(content["role"])
            expect(
                page.get_by_text("卡片已有新修订，当前展示已保存内容；未用旧草稿覆盖。", exact=True)
            ).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors
        finally:
            browser.close()


@pytest.mark.parametrize("width", [1280, 390])
def test_world_assistance_scope_and_end_context(runtime, width):
    service = runtime.writing_service
    service.provider = CardAssistanceProvider()
    work, context = make_card_work(service, "world_card")
    base = f"http://127.0.0.1:{runtime.gateway.server_port}"
    with pytest.importorskip("playwright.sync_api").sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(f"{base}/?section=references&view=world&work_id={work['id']}")
            page.locator(f'[data-edit-world-entry="entity:{context["target_id"]}"]').click()
            page.locator('.library-editor-assist > summary').click()
            page.locator('[data-card-assistance-panel] > summary').click()
            page.get_by_role("button", name="带草稿去讨论", exact=True).click()
            expect(page.locator("[data-card-assistance-error]")).to_contain_text("请先写一句")
            page.get_by_label("这次想怎么改", exact=True).fill("只补充进入档案室的限制，不改别名")
            expect(page.locator("[data-card-assistance-error]")).to_be_hidden()
            page.get_by_label("允许调整", exact=True).select_option("summary")
            page.get_by_role("button", name="带草稿去讨论", exact=True).click()
            page.locator('#workConversationForm button[type="submit"]').click()
            page.locator('[data-agent-propose-knowledge="world_card"]').click(timeout=20000)
            apply = page.locator("[data-accept-director-proposal][data-partial-knowledge]")
            expect(apply).to_be_visible(timeout=20000)
            expect(page.locator("[data-knowledge-field]")).to_have_count(1)
            assert page.locator("[data-knowledge-field]").get_attribute("value") == "summary"
            apply.click()
            expect(
                page.locator("[data-proposal-card] > summary").filter(has_text="已写入正式资料")
            ).to_be_visible(timeout=10000)
            saved = next(
                a for a in service.get_work(work["id"])["artifacts"] if a["kind"] == "world_bible"
            )
            entry = saved["current_revision"]["content"]["entities"][0]
            assert entry["summary"] == "夜间需要双人确认后才能进入档案室。"
            assert entry["aliases"] == []
            assert entry["confidence_status"] == "open"
            assert entry["source"] == "用户初始设定"
            page.get_by_role("button", name="结束本次定向调整，保留卡片草稿").click()
            expect(page.locator("[data-card-assistance-banner]")).to_have_count(0)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors
        finally:
            browser.close()


def test_old_backend_disables_assistant_without_disabling_manual_editing(runtime, monkeypatch):
    service = runtime.writing_service
    work, context = make_card_work(service)
    capabilities = service.capabilities()
    capabilities["capabilities"].remove("card_assistance/1.0")
    monkeypatch.setattr(service, "capabilities", lambda: capabilities)
    base = f"http://127.0.0.1:{runtime.gateway.server_port}"
    with pytest.importorskip("playwright.sync_api").sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            page.goto(f"{base}/?section=references&view=characters&work_id={work['id']}")
            page.locator(f'[data-edit-card="{context["target_id"]}"]').click()
            page.locator('.library-editor-assist > summary').click()
            page.locator('[data-card-assistance-panel] > summary').click()
            expect(page.get_by_role("button", name="带草稿去讨论", exact=True)).to_be_disabled()
            expect(page.get_by_text("当前后端尚未启用定向调整", exact=False)).to_be_visible()
            expect(page.get_by_role("button", name="保存人物卡", exact=True)).to_be_enabled()
        finally:
            browser.close()
