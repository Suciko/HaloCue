"""First-use teaching follows actual failures and invalidated targets."""

import pytest
import threading
import test_authoring_workspace_browser as authoring_fixture
from playwright.sync_api import expect

from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from test_choice_ui_browser import open_page, screenshot
from test_scene_conversation_harness import create_ready_scene
from first_use_fixture_support import DraftingProvider, assert_readable_surface

browser = authoring_fixture.browser
local_authoring = authoring_fixture.local_authoring


def replay(page):
    page.locator("#openHelpButton").click()
    page.get_by_role("button", name="重看新手教学", exact=True).click()
    return page.get_by_role("region", name="首次创作教学")


class FailOnceProvider(FakeWritingProvider):
    def __init__(self):
        self.failed = False

    def discuss_work(self, messages, context):
        if not self.failed:
            self.failed = True
            raise DomainError(
                "writing_provider_failed",
                "模拟模型服务超时。",
                status=502,
                details={"failure_kind": "provider_timeout"},
            )
        return super().discuss_work(messages, context)


def test_failed_turn_highlights_the_real_recovery_and_can_retry(local_authoring, browser):
    service, url = local_authoring
    work = service.create_work({"title": "失败后继续教学"})
    service.provider = FailOnceProvider()
    page = open_page(browser, f"{url}/?section=works&work_id={work['id']}", "dark", (1280, 720))
    task = replay(page)
    composer = page.locator("#workConversationForm")
    composer.locator("textarea").fill("请先讨论活动室里亮起的提示灯。")
    composer.locator('[type="submit"]').click()
    retry = page.locator("[data-agent-retry-run]").filter(visible=True).first
    expect(retry).to_be_visible(timeout=15000)
    expect(task).to_contain_text("这一步还没有完成")
    expect(task).to_contain_text("重试")
    assert_readable_surface(page, ".agent-failure-card:has([data-agent-retry-run])")
    screenshot(page, "first-use-failed-turn-dark-1280")
    retry.click()
    expect(retry).to_have_count(0)
    expect(task).not_to_contain_text("这一步还没有完成")
    assert not any(
        item["kind"] == "scene_script" for item in service.get_work(work["id"])["artifacts"]
    )
    page.close()


def test_superseded_candidate_teaches_using_the_current_scene_settings(local_authoring, browser):
    service, url = local_authoring
    work_id, scene_id, work = create_ready_scene(service, title="改变设定后继续")
    candidate = service.generate_scene_candidate(
        work_id, scene_id, {"expected_version": work["version"]}
    )
    service.update_scene_contract(
        work_id,
        scene_id,
        {
            "expected_version": candidate["work"]["version"],
            "title": "改变设定后继续",
            "location": "活动室",
            "goal": "只观察一次提示灯的回应",
            "stop_boundary": "第一次回应后结束",
        },
    )
    page = open_page(
        browser,
        f"{url}/?section=writing&stage=draft&work_id={work_id}&scene_id={scene_id}",
        "light",
        (1600, 900),
    )
    page.wait_for_function(
        "() => state.context?.scene_id === state.sceneId && Boolean(sceneConversationThread(selectedScene())) && !state._contextLoadingScene"
    )
    task = replay(page)
    expect(task).to_contain_text("之前的候选已失效")
    expect(task).not_to_contain_text("先审查，再采用")
    expect(page.locator("[data-scene-change]")).to_have_count(0)
    assert not service.get_work(work_id)["chapters"][0]["scenes"][0]["current_revision_id"]
    task.get_by_role("button", name="先自己写", exact=True).click()
    page.get_by_role("button", name="开始写作", exact=True).click()
    page.locator("[data-chapter-text]").first.fill("按新设定，提示灯只回应了一次。")
    page.locator("[data-chapter-save]").click()
    expect(task).to_have_count(0)
    page.close()


@pytest.mark.parametrize("restore", [False, True])
def test_trashed_teaching_work_can_be_replaced_deliberately(local_authoring, browser, restore):
    service, url = local_authoring
    work = service.create_work({"title": "移到回收站的教学作品"})
    page = open_page(browser, f"{url}/?section=works&work_id={work['id']}", "light", (1280, 720))
    task = replay(page)
    page.locator('[data-section="projects"]').click()
    page.locator(f'[data-delete-work="{work["id"]}"]').click()
    page.locator('#deleteWorkForm [type="submit"]').click()
    expect(task).to_contain_text("教学作品已移出作品列表")
    expect(task).not_to_contain_text("返回教学作品")
    if restore:
        page.get_by_role("button", name="回收站", exact=True).click()
        expect(task).to_contain_text("恢复原来的教学作品")
        page.get_by_role("button", name="恢复作品", exact=True).click()
        expect(task).to_contain_text("回到作品列表继续")
        page.get_by_role("button", name="返回作品", exact=True).click()
        expect(task).to_contain_text("打开自己的作品继续")
        page.locator(f'.project-open[data-select-work="{work["id"]}"]').click()
        expect(task).to_contain_text("说说你想写什么")
        assert len(service.list_works()) == 1
        assert service.list_deleted_works() == []
        page.close()
        return
    task.get_by_role("button", name="从新作品开始", exact=True).click()
    expect(task).to_contain_text("先建立你自己的作品")
    page.locator('[data-action="new-work"]').filter(visible=True).first.click()
    page.locator('#workDialog input[name="title"]').fill("重新选定的自己的作品")
    page.locator("#workDialog").get_by_role("button", name="建立作品", exact=True).click()
    expect(task).to_contain_text("说说你想写什么")
    assert len(service.list_works()) == 1
    assert len(service.list_deleted_works()) == 1
    page.close()


@pytest.mark.parametrize("cancel", [False, True])
def test_running_first_draft_waits_and_respects_stop(local_authoring, browser, cancel):
    service, url = local_authoring
    work_id, scene_id, _ = create_ready_scene(service, title="等待首次起草")
    started, release = threading.Event(), threading.Event()

    class SlowDraftingProvider(DraftingProvider):
        def discuss_work(self, messages, context):
            started.set()
            assert release.wait(timeout=15)
            return super().discuss_work(messages, context)

    service.provider = SlowDraftingProvider()
    page = open_page(
        browser,
        f"{url}/?section=writing&stage=draft&work_id={work_id}&scene_id={scene_id}",
        "dark",
        (1280, 720),
    )
    page.wait_for_function(
        "() => state.context?.scene_id === state.sceneId && Boolean(sceneConversationThread(selectedScene())) && !state._contextLoadingScene"
    )
    task = replay(page)
    page.locator("#sceneConversationForm textarea").fill("请起草本场。")
    page.locator("#sceneConversationForm").get_by_role("button", name="发送", exact=True).click()
    try:
        assert started.wait(timeout=5)
        expect(task).to_contain_text("正在准备本场候选")
        if cancel:
            page.get_by_role("button", name="停止本轮", exact=True).click()
            expect(task).not_to_contain_text("正在准备本场候选")
        release.set()
        if not cancel:
            expect(task).to_contain_text("先审查，再采用助手的文字")
        else:
            page.reload()
            expect(page.locator("[data-scene-change]")).to_have_count(0)
        assert not service.get_work(work_id)["chapters"][0]["scenes"][0]["current_revision_id"]
    finally:
        release.set()
        page.close()
