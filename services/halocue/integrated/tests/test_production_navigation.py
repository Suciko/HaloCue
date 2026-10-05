"""Browser acceptance for leaving AA production through the shared navigation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
for context in ("writing", "production", "integrated"):
    import sys

    sys.path.insert(0, str(REPO / "services" / "halocue" / context / "src"))


@pytest.mark.parametrize("size", [(1280, 720), (1600, 900), (2560, 1368)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_aa_source_focus_keeps_workbench_at_window_bottom(runtime, size, theme):
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": size[0], "height": size[1]})
            page.add_init_script(
                f"localStorage.setItem('halocue.ui.theme', '{theme}')"
            )
            page.goto(
                f"http://127.0.0.1:{runtime.port}/?section=references&view=characters",
                wait_until="networkidle",
            )
            page.get_by_role("button", name="AA 制作", exact=True).click()
            page.get_by_role("tab", name="粘贴文本", exact=True).click()
            page.get_by_role("textbox", name="AA 工程名称", exact=True).fill("Scroll QA")
            page.get_by_role("textbox", name="剧本文本", exact=True).fill(
                "## 场景 01\n（旁白）午后，活动室。\n"
                "爱丽丝: 今天想做点什么？\n老师: 先把场景准备好。\n爱丽丝: 明白了。"
            )
            page.get_by_role("button", name="识别并预览分场", exact=True).click()
            page.get_by_role("button", name="确认分场，选择草稿方式", exact=True).click()
            create = page.get_by_role("button", name="创建 AA 制作任务", exact=True)
            # Keyboard focus and scrollIntoView may scroll overflow:hidden
            # ancestors too. The page owns scrolling; its host must stay put.
            create.focus()
            create.evaluate("node => node.scrollIntoView({block: 'end'})")
            # Some Chromium versions stop at the page while others also move
            # the hidden-overflow host. Exercise that ancestor scroll request
            # explicitly so either engine checks the same visual invariant.
            page.locator("#productionModule").evaluate("node => node.scrollTop = 200")
            pw.expect(create).to_be_in_viewport()
            metrics = page.evaluate("""() => {
                const host = document.querySelector('#productionModule');
                const source = host.shadowRoot.querySelector('#page-source');
                return {
                    hostScroll: host.scrollTop,
                    hostBottom: host.getBoundingClientRect().bottom,
                    pageBottom: source.getBoundingClientRect().bottom,
                    viewportBottom: innerHeight,
                    pageScroll: source.scrollTop,
                    canScroll: source.scrollHeight > source.clientHeight,
                    fitsWidth: document.documentElement.scrollWidth <= innerWidth,
                };
            }""")
            assert abs(metrics["hostScroll"]) < 1, metrics
            assert abs(metrics["hostBottom"] - metrics["viewportBottom"]) < 2, metrics
            assert abs(metrics["pageBottom"] - metrics["hostBottom"]) < 2, metrics
            assert metrics["canScroll"] and metrics["pageScroll"] > 0, metrics
            assert metrics["fitsWidth"], metrics
        finally:
            browser.close()

@pytest.mark.parametrize("surface,panel", [("works", "#worksPanel"), ("writing", "#treePanel")])
@pytest.mark.parametrize("with_work", [False, True])
def test_sidebar_resize_collapse_and_restore(runtime, surface, panel, with_work):
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        work = runtime.writing_service.create_work({"title": "Sidebar test"}) if with_work else None
        suffix = f"&work_id={work['id']}" if work else ""
        page.goto(
            f"http://127.0.0.1:{runtime.port}/?section={surface}{suffix}", wait_until="networkidle"
        )
        handle = page.locator('[data-panel-resize="tree"]')
        assert handle.count() == 1, "The sidebar needs an actual resize separator"
        before = page.locator(panel).bounding_box()["width"]
        expected_width = min(before + 60, float(handle.get_attribute("aria-valuemax")))
        box = handle.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 80)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] / 2 + 60, box["y"] + 80, steps=8)
        page.mouse.up()
        assert abs(page.locator(panel).bounding_box()["width"] - expected_width) < 2
        toggle = page.locator('.agent-sidebar-toggle' if surface == "works" and with_work else '.panel-divider-toggle-left')
        assert page.locator("#app").get_attribute("aria-disabled") != "true"
        assert toggle.is_enabled()
        toggle.hover()
        page.wait_for_function("selector => Number(getComputedStyle(document.querySelector(selector)).opacity) >= .99", arg='.agent-sidebar-toggle' if surface == 'works' and with_work else '.panel-divider-toggle-left')
        toggle.click()
        assert not page.locator(panel).is_visible()
        toggle.click()
        assert abs(page.locator(panel).bounding_box()["width"] - expected_width) < 2
        page.reload(wait_until="networkidle")
        assert abs(page.locator(panel).bounding_box()["width"] - expected_width) < 2
        handle.press("End")
        assert abs(page.locator(panel).bounding_box()["width"] - float(handle.get_attribute("aria-valuemax"))) < 2
        handle.press("Home")
        assert abs(page.locator(panel).bounding_box()["width"] - float(handle.get_attribute("aria-valuemin"))) < 2
        if surface == "writing":
            right_handle = page.locator('[data-panel-resize="inspector"]')
            previous = page.locator("#inspector").bounding_box()["width"]
            right_handle.press("ArrowLeft")
            assert abs(page.locator("#inspector").bounding_box()["width"] - previous - 20) < 2
            right = page.locator('.panel-divider-toggle-right')
            right.click()
            assert not page.locator("#inspector").is_visible()
            right.click()
            assert page.locator("#inspector").is_visible()
        page.set_viewport_size({"width": 800, "height": 700})
        assert page.locator("#workspace").bounding_box()["width"] >= 239
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.set_viewport_size({"width": 390, "height": 844})
        assert not handle.is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()


def test_theme_lives_in_appearance_settings(runtime):
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"http://127.0.0.1:{runtime.port}/", wait_until="networkidle")
        assert page.locator(".topbar [data-theme-select]").count() == 0
        page.locator("#openSettingsButton").click()
        page.get_by_role("tab", name="外观", exact=True).click()
        page.locator('[data-theme-choice="dark"]').click()
        pw.expect(page.locator('[data-theme-choice="dark"]')).to_have_attribute(
            "aria-pressed", "true"
        )
        assert page.locator("html").get_attribute("data-theme") == "dark"
        page.reload(wait_until="networkidle")
        assert page.locator("html").get_attribute("data-theme") == "dark"
        browser.close()


def test_first_use_keeps_the_local_composer_available_after_reload(runtime):
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.add_init_script("localStorage.setItem('halocue:onboarding:interface-v2', 'done')")
        page.goto(f"http://127.0.0.1:{runtime.port}/?section=works", wait_until="networkidle")

        first_use = page.locator(".intent-start")
        assert first_use.is_visible()
        pw.expect(page.locator("#intentMessage")).to_be_visible()
        pw.expect(page.locator("[data-intent-submit]")).to_be_visible()
        pw.expect(first_use).to_contain_text("对话不会直接修改正式资料")

        page.reload(wait_until="networkidle")
        pw.expect(page.locator("#intentMessage")).to_be_visible()
        browser.close()


def test_empty_work_starter_has_no_dead_inspector_rail(runtime):
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.add_init_script(
            "localStorage.setItem('halocue:onboarding:interface-v2', 'done');"
            "localStorage.setItem('halocue-writing.panels.v7', JSON.stringify({tree:false, inspector:false}))"
        )
        page.goto(f"http://127.0.0.1:{runtime.port}/?section=works", wait_until="networkidle")

        app = page.locator("#app")
        assert "empty-work-stage" in (app.get_attribute("class") or "")
        nav = page.locator(".primary-nav").bounding_box()
        assert nav["width"] == 64
        # Every hit area stays centered, including the selected item.
        for button in page.locator(".primary-nav .nav-item").all():
            box = button.bounding_box()
            assert abs(box["x"] + box["width"] / 2 - nav["x"] - nav["width"] / 2) < 1
        context_handle = page.locator(".panel-divider-toggle-left")
        assert context_handle.is_visible()
        assert float(context_handle.evaluate("node => getComputedStyle(node).opacity")) >= 0.95
        assert not page.locator("#inspector").is_visible()
        assert not page.locator(".panel-divider-toggle-right").is_visible()
        # Inactive right-hand tracks occupy no space in the empty workspace.
        tracks = app.evaluate("node => getComputedStyle(node).gridTemplateColumns").split()
        assert tracks[-2:] == ["0px", "0px"]
        browser.close()


def test_startup_does_not_reopen_a_blocking_onboarding_tour(runtime):
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"http://127.0.0.1:{runtime.port}/", wait_until="networkidle")
        assert not page.locator("#onboardingTour").is_visible()

        page.reload(wait_until="networkidle")
        assert not page.locator("#onboardingTour").is_visible()
        browser.close()


def test_shared_navigation_leaves_aa_production_and_opens_real_workspaces(runtime):
    pw = pytest.importorskip("playwright.sync_api")
    work = runtime.writing_service.create_work({"title": "AA 导航验收"})
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script(
            "localStorage.setItem('halocue:onboarding:interface-v2', 'done'); localStorage.setItem('halocue-writing.panels.v7', JSON.stringify({tree:false, inspector:false}))"
        )
        page.goto(
            f"http://127.0.0.1:{runtime.port}/?work_id={work['id']}",
            wait_until="networkidle",
        )

        def navigation(section: str):
            return page.locator(f'.primary-nav [data-section="{section}"]')

        # Work status is now a user-facing next-action region, not a removed
        # banner. The conversation and persistent composer must remain usable.
        assert page.locator(".work-agent-canvas").is_visible()
        assert page.locator(".work-agent-bottom").is_visible()
        left_splitter = page.locator(".agent-sidebar-toggle")
        right_splitter = page.locator(".panel-divider-toggle-right")
        assert left_splitter.is_visible()
        # The work Agent starts focused on the conversation; its director rail
        # is not forced open. Writing retains the independently toggleable rail.
        assert not page.locator("#inspector").is_visible()
        left_splitter.click()
        assert "tree-collapsed" in (page.locator("#app").get_attribute("class") or "")
        assert left_splitter.is_visible()
        nav_right = (
            page.locator(".primary-nav").bounding_box()["x"]
            + page.locator(".primary-nav").bounding_box()["width"]
        )
        # When the context rail is closed, its reveal handle must sit outside
        # the dark main navigation—not fold back into it.
        assert left_splitter.bounding_box()["x"] >= nav_right - 1
        left_splitter.click()
        assert "tree-collapsed" not in (page.locator("#app").get_attribute("class") or "")

        page.locator('[data-creation-view="structure"]').click()
        page.locator("#app.writing-workbench-stage").wait_for(state="attached")
        assert right_splitter.is_visible()
        assert page.locator("#inspector").is_visible()
        right_splitter.click()
        page.wait_for_timeout(250)
        assert "inspector-collapsed" in (page.locator("#app").get_attribute("class") or "")
        assert right_splitter.is_visible()
        right_splitter.click()
        page.wait_for_timeout(250)
        assert "inspector-collapsed" not in (page.locator("#app").get_attribute("class") or "")

        checks = {
            "assets": ("asset-stage", "素材库"),
            "references": ("library-stage", "创作资料"),
            "tasks": ("tasks-stage", "后台任务"),
        }
        for section, (workspace_class, heading) in checks.items():
            navigation("production").click()
            page.locator("#app.production-mode").wait_for(state="attached")
            for shared_section in ["projects", "assets", "tasks"]:
                assert navigation(shared_section).is_visible()

            if section == "references":
                page.locator('.primary-nav [data-creation-entry]').click()
                page.locator('[data-creation-view="references"]').click()
            else:
                navigation(section).click()
            page.locator("#app.production-mode").wait_for(state="detached")
            assert workspace_class in (page.locator("#app").get_attribute("class") or "")
            assert f"section={section}" in page.url
            assert page.locator("#workspace").get_by_text(heading, exact=True).is_visible()
            assert page.locator(".production-module-host").get_attribute("hidden") is not None

        assert errors == []
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_production_navigation_uses_router_and_preserves_history(runtime, width):
    pw = pytest.importorskip("playwright.sync_api")
    work = runtime.writing_service.create_work({"title": "路由与未保存保护测试"})
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.goto(
            f"http://127.0.0.1:{runtime.port}/?section=writing&stage=draft&work_id={work['id']}",
            wait_until="networkidle",
        )
        page.wait_for_function("()=>Boolean(window.HaloCueRouter)&&!document.body.classList.contains('app-loading')")
        # Synthetic unsaved state; never create or overwrite a real manuscript.
        page.evaluate("state.manuscriptDirty=true; state.manuscriptSceneId=state.sceneId")
        page.locator(
            (".mobile-nav" if width < 760 else ".primary-nav") + ' [data-section="production"]'
        ).click()
        pw.expect(page.locator("#unsavedManuscriptDialog")).to_be_visible()
        assert page.evaluate("HaloCueRouter.getRoute().section") == "writing"
        assert not page.evaluate("HaloCueProductionEmbed.isOpen()")
        page.locator("[data-unsaved-manuscript-cancel]").click()
        assert page.evaluate("state.manuscriptDirty")
        page.locator(
            (".mobile-nav" if width < 760 else ".primary-nav") + ' [data-section="production"]'
        ).click()
        page.locator("[data-unsaved-manuscript-discard]").click()
        pw.expect(page.locator("#app")).to_have_class(re.compile("production-mode"))
        assert page.evaluate("HaloCueRouter.getRoute().section") == "production"
        assert page.evaluate("history.state.hcIndex") == 1
        page.evaluate("history.back()")
        pw.expect(page).to_have_url(re.compile("section=writing"))
        assert page.evaluate("HaloCueRouter.getRoute().section") == "writing"
        assert not page.evaluate("HaloCueProductionEmbed.isOpen()")
        page.evaluate("state.manuscriptDirty=true; state.manuscriptSceneId=state.sceneId")
        page.evaluate("history.forward()")
        pw.expect(page.locator("#unsavedManuscriptDialog")).to_be_visible()
        pw.expect(page).to_have_url(re.compile("section=writing"))
        assert not page.evaluate("HaloCueProductionEmbed.isOpen()")
        page.locator("[data-unsaved-manuscript-cancel]").click()
        assert page.evaluate("state.manuscriptDirty")
        page.evaluate("history.forward()")
        pw.expect(page.locator("#unsavedManuscriptDialog")).to_be_visible()
        pw.expect(page).to_have_url(re.compile("section=writing"))
        page.locator("[data-unsaved-manuscript-discard]").click()
        pw.expect(page).to_have_url(re.compile("section=production"))
        assert page.evaluate("HaloCueRouter.getRoute().section") == "production"
        assert page.evaluate("history.state.hcIndex") == 1
        page.reload(wait_until="networkidle")
        pw.expect(page.locator("#app")).to_have_class(re.compile("production-mode"))
        assert page.evaluate("HaloCueRouter.getRoute().section") == "production"
        assert page.evaluate("history.state.hcIndex") == 1
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_scene_active_run_is_polled_after_reload_without_generation(runtime, width):
    pw = pytest.importorskip("playwright.sync_api")
    service = runtime.writing_service
    work = service.create_work({"title": "恢复任务测试"})
    # Transport fixture only: no model or formal chapter/scene creation.
    scene_id = "scene-ui-test"
    work["chapters"] = [
        {
            "id": "chapter-ui-test",
            "title": "测试章",
            "scenes": [
                {
                    "id": scene_id,
                    "title": "恢复场景",
                    "chapter_id": "chapter-ui-test",
                    "contract": {},
                    "revisions": [],
                }
            ],
        }
    ]
    work["conversation_threads"] = [
        {
            "id": "thread-ui-test",
            "scope_type": "scene",
            "scope_id": scene_id,
            "status": "active",
            "messages": [],
            "attachments": [],
            "version": 1,
        }
    ]
    work["agent_runs"] = [
        {
            "id": "agent-ui-test",
            "status": "running",
            "scope_id": scene_id,
            "policy": {"thread_id": "thread-ui-test"},
            "tool_calls": [],
        }
    ]
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 900})
        polls = []
        writes = []
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def transport(route):
            url = route.request.url.split("?")[0]
            if url.endswith("/agent-runs/agent-ui-test"):
                polls.append(url)
                route.fulfill(json={"ok": True, "data": work["agent_runs"][0]})
            elif url.endswith("/works/" + work["id"]):
                route.fulfill(json={"ok": True, "data": work})
            elif route.request.method not in ("GET", "HEAD", "OPTIONS"):
                writes.append(url)
                route.fulfill(status=409, json={"error": {"message": "Read-only fixture"}})
            else:
                route.continue_()

        page.route("**/api/**", transport)
        page.goto(
            f"http://127.0.0.1:{runtime.port}/?section=writing&stage=draft&work_id={work['id']}&scene_id={scene_id}"
        )
        page.wait_for_timeout(1700)
        assert polls, "Opening a scene with an active durable run must resume polling"
        if width < 760:
            page.locator("#writingMobileTab-agent").click()
        pw.expect(page.locator(".scene-agent-panel > header h3")).to_have_text("本场助手")
        pw.expect(page.locator(".scene-agent-panel > header p")).to_contain_text("恢复场景")
        pw.expect(page.locator(".scene-agent-panel .agent-running-message")).to_be_visible()
        pw.expect(page.locator("#sceneAgentMessage")).to_be_disabled()
        candidate = page.locator("[data-generate-scene-proposal]")
        pw.expect(candidate).to_be_hidden()
        pw.expect(page.locator('[data-agent-cancel-run="agent-ui-test"]')).to_be_visible()
        polls.clear()
        page.reload()
        page.wait_for_timeout(1700)
        assert polls, "Reload must resume polling without submitting another generation"
        assert not any("agent-runs" in url or url.endswith("/messages") for url in writes)
        assert not errors
        browser.close()


@pytest.mark.parametrize("height", [844, 667])
def test_mobile_scene_chat_keeps_send_visible_and_scrolls_messages(runtime, height):
    pw = pytest.importorskip("playwright.sync_api")
    work = runtime.writing_service.create_work({"title": "长对话布局测试"})
    scene_id = "scene-mobile-chat"
    work["chapters"] = [
        {
            "id": "chapter-chat",
            "title": "测试章",
            "scenes": [
                {
                    "id": scene_id,
                    "title": "当前场景",
                    "chapter_id": "chapter-chat",
                    "contract": {},
                    "revisions": [],
                }
            ],
        }
    ]
    work["conversation_threads"] = [
        {
            "id": "thread-chat",
            "scope_type": "scene",
            "scope_id": scene_id,
            "status": "active",
            "version": 1,
            "attachments": [],
            "messages": [
                {
                    "id": f"message-{i}",
                    "role": "assistant" if i % 2 else "user",
                    "content": {"text": f"第 {i} 条。" + "这是一段可滚动的场景讨论。" * 16},
                }
                for i in range(8)
            ],
        }
    ]
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": height})
        page.add_init_script("localStorage.setItem('halocue.ui.theme','dark')")

        def transport(route):
            if route.request.url.split("?")[0].endswith("/works/" + work["id"]):
                route.fulfill(json={"ok": True, "data": work})
            elif route.request.method not in ("GET", "HEAD", "OPTIONS"):
                route.fulfill(status=409, json={"error": {"message": "Read-only fixture"}})
            else:
                route.continue_()

        page.route("**/api/**", transport)
        page.goto(
            f"http://127.0.0.1:{runtime.port}/?section=writing&stage=draft&work_id={work['id']}&scene_id={scene_id}",
            wait_until="networkidle",
        )
        page.locator("#writingMobileTab-agent").click()
        page.wait_for_timeout(400)
        send = page.locator('#sceneConversationForm button[type="submit"]:not([form])')
        pw.expect(send).to_be_in_viewport()
        assert (
            send.bounding_box()["y"] + send.bounding_box()["height"]
            <= page.locator(".mobile-nav").bounding_box()["y"]
        )
        scroll = page.locator("[data-scene-conversation-scroll]:visible")
        assert scroll.evaluate("e=>e.clientHeight") >= 60
        assert (
            page.locator(".scene-message-body > p").first.evaluate(
                "e=>getComputedStyle(e).whiteSpace"
            )
            == "pre-wrap"
        )
        assert scroll.evaluate("e=>e.scrollHeight-e.clientHeight-e.scrollTop") < 4
        scroll.evaluate("e=>e.scrollTop=30")
        page.locator("#writingMobileTab-manuscript").click()
        page.locator("#writingMobileTab-agent").click()
        assert abs(scroll.evaluate("e=>e.scrollTop") - 30) < 3
        assert (
            page.locator(".scene-conversation-message.user .scene-message-body").first.evaluate(
                "e=>getComputedStyle(e).backgroundColor"
            )
            == "rgb(43, 59, 82)"
        )
        browser.close()

@pytest.mark.parametrize("width", [1440, 390])
def test_cancel_empty_optional_work_form_never_creates_work(runtime, width):
    pw = pytest.importorskip("playwright.sync_api")
    work = runtime.writing_service.create_work({"title": "取消表单隔离测试"})
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": 900})
            writes, errors = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: writes.append(request.url)
                    if request.method == "POST" and request.url.split("?")[0].endswith("/works") else None)
            page.goto(f"http://127.0.0.1:{runtime.port}/?section=works&work_id={work['id']}", wait_until="networkidle")
            page.locator(".hc-work-switch").click()
            page.locator('#workSwitchDialog [data-action="new-work"]').click()
            dialog = page.locator("#workDialog")
            pw.expect(dialog).to_be_visible()
            dialog.locator('[name="title"]').fill("")
            dialog.locator('[name="idea"]').fill("")
            dialog.get_by_role("button", name="取消", exact=True).click()
            pw.expect(dialog).to_be_hidden()
            assert writes == []
            assert errors == []
            assert not page.locator("#app").evaluate("node => node.inert")
        finally:
            browser.close()

@pytest.mark.parametrize("width", [820, 1440])
def test_topbar_named_panel_controls_and_focus_restore(runtime, width):
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": 900})
            work = runtime.writing_service.create_work({"title": "很长的作品标题，用来检查顶部空间分配与功能按钮"})
            page.goto(f"http://127.0.0.1:{runtime.port}/?section=writing&work_id={work['id']}", wait_until="networkidle")
            toolbar = page.locator('.panel-controls')
            tree = toolbar.locator('[data-panel-toggle="tree"]')
            agent = toolbar.locator('[data-panel-toggle="inspector"]')
            focus = toolbar.locator('[data-focus-toggle]')
            assert tree.is_visible() and agent.is_visible() and focus.is_visible()
            assert tree.inner_text() == '目录'
            assert agent.inner_text() == 'Agent'
            assert toolbar.locator('[data-flow-nav]').count() == 0
            if tree.get_attribute('aria-expanded') != 'true':
                tree.click()
            if agent.get_attribute('aria-expanded') == 'true':
                agent.click()
            assert not page.locator('#inspector').is_visible()
            assert page.locator('#treePanel').is_visible()
            focus.click()
            assert focus.get_attribute('aria-pressed') == 'true'
            assert not page.locator('#treePanel').is_visible()
            focus.click()
            assert tree.get_attribute('aria-expanded') == 'true'
            assert agent.get_attribute('aria-expanded') == 'false'
            agent.click()
            assert page.locator('#inspector').is_visible()
            assert agent.get_attribute('aria-expanded') == 'true'
            assert page.locator('.hc-work-switch').bounding_box()['x'] + page.locator('.hc-work-switch').bounding_box()['width'] <= toolbar.bounding_box()['x']
            assert page.locator('.hc-topbar .top-actions').bounding_box()['x'] + page.locator('.hc-topbar .top-actions').bounding_box()['width'] <= width
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.set_viewport_size({"width": 390, "height": 844})
            assert not toolbar.is_visible()
            assert page.locator('.hc-work-switch').is_visible()
            assert page.locator('#saveStatus').is_visible()
            assert not page.locator('#inspector').is_visible()
            assert page.locator('#workspace').bounding_box()['width'] >= 388, page.locator('#app').evaluate("node=>({class:node.className,columns:getComputedStyle(node).gridTemplateColumns,areas:getComputedStyle(node).gridTemplateAreas,style:node.getAttribute('style'),workspace:getComputedStyle(document.querySelector('#workspace')).gridArea})")
        finally:
            browser.close()
@pytest.mark.parametrize("width", [820, 1280])
def test_short_window_navigation_utilities_remain_visible(runtime, width):
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": 520})
            page.goto(f"http://127.0.0.1:{runtime.port}/?section=writing", wait_until="networkidle")
            nav=page.locator('.primary-nav')
            assert abs(nav.bounding_box()['width']-64)<1
            for selector in ['.nav-help','.nav-settings','.nav-feedback']:
                box=nav.locator(selector).bounding_box()
                assert box['y']+box['height']<=520,box
                assert box['height']>=40,box
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        finally:
            browser.close()
@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_writing_seams_reveal_only_on_interaction(runtime, theme):
    pw = pytest.importorskip('playwright.sync_api')
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch()
        try:
            page = browser.new_page(viewport={'width':1440,'height':900})
            work=runtime.writing_service.create_work({'title':'Seam regression'})
            page.goto(f'http://127.0.0.1:{runtime.port}/?section=writing&work_id={work["id"]}',wait_until='networkidle')
            page.evaluate('theme=>document.documentElement.dataset.theme=theme',theme)
            def opacity(selector, value):
                page.wait_for_function('''({selector,value})=>Math.abs(Number(getComputedStyle(document.querySelector(selector)).opacity)-value)<.01''',arg={'selector':selector,'value':value})
            for side,panel in [('left','#treePanel'),('right','#inspector')]:
                selector=f'.panel-divider-toggle-{side}'
                toggle=page.locator(selector)
                handle=page.locator(f'.panel-resizer-{side}')
                page.locator('.brand').focus()
                page.mouse.move(650,25)
                opacity(selector,0)
                assert page.locator(panel).is_visible()
                metrics=handle.evaluate('''e=>{const s=getComputedStyle(e,'::before'),r=e.getBoundingClientRect();return {width:r.width,lineWidth:s.width,left:s.left,right:s.right,color:s.backgroundColor,background:getComputedStyle(e).backgroundColor}}''')
                assert metrics['width']==12 and metrics['lineWidth']=='1px',metrics
                assert metrics['left' if side=='left' else 'right']=='0px',metrics
                assert metrics['background']=='rgba(0, 0, 0, 0)',metrics
                assert page.locator(panel).evaluate('e=>getComputedStyle(e).border'+('RightWidth' if side=='left' else 'LeftWidth'))=='0px'
                panel_box=page.locator(panel).bounding_box()
                toggle_box=toggle.bounding_box()
                edge=panel_box['x']+panel_box['width'] if side=='left' else panel_box['x']
                assert abs(toggle_box['x']+toggle_box['width']/2-edge)<1
                handle.hover(position={'x':6,'y':50})
                opacity(selector,1)
                assert handle.evaluate("e=>getComputedStyle(e,'::before').backgroundColor")==metrics['color']
                assert handle.evaluate("e=>getComputedStyle(e,'::after').height")=='72px'
                toggle.hover()
                opacity(selector,1)
                toggle.click()
                assert not page.locator(panel).is_visible()
                page.mouse.move(650,25)
                opacity(selector,0)
                # The collapsed control is still discoverable at the same edge.
                toggle.hover()
                opacity(selector,1)
                toggle.click()
                assert page.locator(panel).is_visible()
                page.mouse.move(650,25)
                handle.focus()
                handle.press('Tab')
                assert toggle.evaluate('e=>e===document.activeElement')
                opacity(selector,1)
                toggle.press('Enter')
                assert not page.locator(panel).is_visible()
                toggle.press('Enter')
                assert page.locator(panel).is_visible()
            page.emulate_media(reduced_motion='reduce')
            assert page.locator('.panel-divider-toggle-right').evaluate('e=>getComputedStyle(e).transitionDuration')=='0s'
            touch=browser.new_page(viewport={'width':1280,'height':800},has_touch=True,is_mobile=True)
            touch.goto(f'http://127.0.0.1:{runtime.port}/?section=writing&work_id={work["id"]}',wait_until='networkidle')
            assert touch.evaluate("matchMedia('(hover:none)').matches")
            for side in ['left','right']:
                assert touch.locator(f'.panel-divider-toggle-{side}').evaluate('e=>getComputedStyle(e).opacity')=='1'
        finally:
            browser.close()

@pytest.mark.parametrize("theme", ["light", "dark"])
def test_projects_entry_real_routes_and_responsive_layout(runtime, theme):
    """Real service data; opening a work is navigation, never a model command."""
    pw = pytest.importorskip("playwright.sync_api")
    first = runtime.writing_service.create_work({"title": "A story with a long title " * 5})
    second = runtime.writing_service.create_work({"title": "Second story"})
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors, model_calls = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: model_calls.append(request.url)
                if request.method == "POST" and any(x in request.url for x in
                    ["/messages", "/agent-runs", "/generate", "/proposals"]) else None)
        page.goto(f"http://127.0.0.1:{runtime.port}/", wait_until="networkidle")
        pw.expect(page.locator("#app")).to_have_attribute("data-surface", "projects")
        pw.expect(page.locator(".project-card")).to_have_count(2)
        page.locator("#openSettingsButton").click()
        page.get_by_role("tab", name="外观", exact=True).click()
        page.locator(f'[data-theme-choice="{theme}"]').click()
        page.keyboard.press("Escape")
        # Test every planned desktop/compact/mobile size in both themes.
        for width, height in [(1440, 900), (1280, 800), (1024, 768), (820, 520), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            box = page.locator("#workspace").bounding_box()
            assert box["width"] >= width - (66 if width > 760 else 2)
            for button in page.locator(".project-card button").all():
                bounds = button.bounding_box()
                assert bounds["x"] >= box["x"]
                assert bounds["x"] + bounds["width"] <= width + 1
        page.set_viewport_size({"width": 1440, "height": 900})
        page.locator(f'[data-select-work="{first["id"]}"][data-project-destination="structure"]').click()
        pw.expect(page.locator("#app")).to_have_attribute("data-surface", "writing")
        assert first["id"] in page.url and "stage=structure" in page.url
        page.locator('.primary-nav [data-section="projects"]').click()
        page.locator(f'[data-select-work="{second["id"]}"][data-project-destination="references"]').click()
        pw.expect(page.locator("#app")).to_have_attribute("data-surface", "references")
        assert second["id"] in page.url
        page.locator('.brand').click()
        pw.expect(page.locator("#app")).to_have_attribute("data-surface", "projects")
        assert "work_id" not in page.url
        page.reload(wait_until="networkidle")
        pw.expect(page.locator(".project-card")).to_have_count(2)
        assert not errors and not model_calls
        browser.close()


def test_projects_empty_create_is_local_and_can_be_cancelled(runtime):
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        model_calls = []
        page.on("request", lambda request: model_calls.append(request.url)
                if request.method == "POST" and any(x in request.url for x in
                    ["/messages", "/agent-runs", "/generate"]) else None)
        page.goto(f"http://127.0.0.1:{runtime.port}/", wait_until="networkidle")
        page.get_by_role("button", name="建立第一部作品", exact=True).click()
        pw.expect(page.locator("#workDialog")).to_be_visible()
        page.get_by_role("button", name="取消", exact=True).click()
        pw.expect(page.locator(".project-home-empty")).to_be_visible()
        page.get_by_role("button", name="建立第一部作品", exact=True).click()
        form = page.locator("#workForm")
        form.locator('[name="idea"]').fill("A fully local manual writing project")
        form.locator('[name="title"]').fill("Manual first work")
        form.locator('[value="blank"]').check()
        form.locator('[value="ideation"]').check()
        form.get_by_role("button", name="建立作品", exact=True).click()
        pw.expect(page.locator("#app")).to_have_attribute("data-surface", "works")
        pw.expect(page.locator(".hc-work-switch")).to_contain_text("Manual first work")
        page.locator('.primary-nav [data-section="projects"]').click()
        pw.expect(page.locator(".project-card")).to_have_count(1)
        assert not model_calls
        browser.close()


@pytest.mark.parametrize("read_fails", [False, True])
def test_production_missing_release_has_honest_recovery_to_selected_work(runtime, read_fails):
    pw = pytest.importorskip("playwright.sync_api")
    runtime.writing_service.create_work({"title": "Other work"})
    selected = runtime.writing_service.create_work({"title": "Selected production source"})
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        errors, mutations = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{runtime.port}/?section=works&work_id={selected["id"]}', wait_until="networkidle")
        # Both navigation and release discovery are read-only.
        page.on("request", lambda request: mutations.append(request.url) if request.method == "POST" else None)
        if read_fails:
            page.route("**/api/v1/works/*", lambda route: route.fulfill(status=503, json={"ok": False}))
        page.locator('.primary-nav [data-section="production"]').click()
        grid = page.locator("#writingReleasesGrid")
        pw.expect(grid).to_be_visible()
        if read_fails:
            # The embedded workbench may have preloaded before interception.
            page.locator("#refreshWritingReleases").click()
            pw.expect(grid).to_contain_text("不能确认是否已有定稿")
            pw.expect(grid.locator("[data-writing-release-review]")).to_have_count(0)
            page.unroute("**/api/v1/works/*")
            page.locator("#refreshWritingReleases").click()
        link = grid.locator(f'[data-writing-release-review="{selected["id"]}"]')
        pw.expect(link).to_be_visible()
        pw.expect(grid.locator("[data-writing-release-review]")).to_have_count(1)
        pw.expect(grid).to_contain_text("暂无可选的制作定稿")
        link.click()
        pw.expect(page.locator("#app")).to_have_attribute("data-surface", "writing")
        assert "stage=release" in page.url and selected["id"] in page.url
        assert not page.locator("#productionModule").is_visible()
        assert not errors and not mutations
        browser.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_creation_views_share_project_scope_without_global_duplicate_navigation(runtime, theme):
    pw = pytest.importorskip("playwright.sync_api")
    work = runtime.writing_service.create_work({"title": "Very long work title for compact navigation " * 3})
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors, writes = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{runtime.port}/?section=works&work_id={work["id"]}', wait_until="networkidle")
        page.locator("#openSettingsButton").click()
        page.get_by_role("tab", name="外观", exact=True).click()
        page.locator(f'[data-theme-choice="{theme}"]').click()
        page.keyboard.press("Escape")
        page.on("request", lambda request: writes.append(request.url) if request.method == "POST" else None)
        expect = pw.expect
        expect(page.locator('.primary-nav [data-section="writing"]')).to_have_count(0)
        expect(page.locator('.primary-nav [data-section="references"]')).to_have_count(1)
        for width, height in [(1440, 900), (1280, 800), (1024, 768), (820, 520), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            for view in ["works", "structure", "draft", "references", "release"]:
                if page.locator('[data-creation-select]').is_visible():
                    page.locator('[data-creation-select]').select_option(view)
                else:
                    page.locator(f'[data-creation-view="{view}"]').click()
                section = "writing" if view in ["structure", "draft", "release"] else view
                expect(page.locator("#app")).to_have_attribute("data-surface", section)
                assert work["id"] in page.url
                active_nav = '.primary-nav [data-section="references"]' if view == 'references' else '.primary-nav [data-creation-entry]'
                expect(page.locator(active_nav)).to_have_attribute("aria-current", "page")
                expect(page.locator(f'[data-creation-view="{view}"]')).to_have_attribute("aria-current", "page")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                header = page.locator("#creationNavigation").bounding_box()
                assert header["width"] >= 100 and header["x"] + header["width"] <= width, (width,view,header)
            root = ".primary-nav" if width > 760 else ".mobile-nav"
            page.locator(root + ' [data-section="projects"], ' + root + ' [data-mobile="projects"]').click()
            expect(page.locator("#creationNavigation")).to_be_hidden()
            page.locator(root + ' [data-creation-entry]').click()
            expect(page.locator("#app")).to_have_attribute("data-surface", "works")
            assert work["id"] in page.url
        assert not errors and not writes
        browser.close()


@pytest.mark.parametrize("width", [1280, 390])
def test_character_reuse_picker_preserves_source_and_requires_explicit_adoption(runtime, width):
    pw = pytest.importorskip("playwright.sync_api")
    service = runtime.writing_service
    source = service.create_work({"title": "Local reference library"})
    for name in ["Synthetic heroine", "Existing hero", *[f"Synthetic extra {i}" for i in range(10)]]:
        source = service.save_character_card(source["id"], {
            "expected_version": source["version"], "name": name, "source_type": "official_reference",
            "source_refs": [{"kind": "synthetic_test", "label": "Not real official material"}],
            "role": "A synthetic test role with long descriptions " * 15, "trust_status": "confirmed",
            "ba_profile": {"name": name, "notes": {"preserve": [1, 2, 3]}},
        })["work"]
    target = service.create_work({"title": "Target work"})
    target = service.save_character_card(target["id"], {"expected_version": target["version"], "name": "Existing hero", "source_refs": ["User-authored test"]})["work"]
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 844})
        errors, reuse_calls = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: reuse_calls.append(request.url) if request.method == "POST" and request.url.endswith("character-cards:reuse") else None)
        page.goto(f'http://127.0.0.1:{runtime.port}/?section=references&view=characters&work_id={target["id"]}', wait_until="networkidle")
        page.locator('.library-head-actions details > summary').click()
        page.get_by_role("button", name="从其他作品选取", exact=True).click()
        dialog = page.locator("#characterReuseDialog")
        pw.expect(dialog).to_contain_text("Target work")
        pw.expect(dialog.locator('[type="submit"]')).to_be_disabled()
        dialog.locator('[name="source"]').select_option(source["id"])
        pw.expect(dialog.locator('[name="card"]')).to_have_count(12)
        pw.expect(dialog.locator('.is-duplicate [name="card"]')).to_be_disabled()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        metrics=dialog.locator('.character-reuse-list').evaluate("e=>({client:e.clientHeight,scroll:e.scrollHeight,overflow:getComputedStyle(e).overflowY})")
        assert metrics["scroll"] > metrics["client"] and metrics["overflow"] == "auto"
        footer=dialog.locator('footer').bounding_box()
        assert footer["y"]+footer["height"] <= 844
        assert dialog.evaluate("e=>e.scrollHeight<=e.clientHeight+2")
        page.keyboard.press("Escape")
        pw.expect(dialog).to_be_hidden()
        assert not reuse_calls
        page.locator('.library-head-actions details > summary').click()
        page.get_by_role("button", name="从其他作品选取", exact=True).click()
        dialog.locator('[name="source"]').select_option(source["id"])
        dialog.locator('[name="query"]').fill("heroine")
        pw.expect(dialog.locator('[name="card"]')).to_have_count(1)
        dialog.locator('[name="card"]').check()
        dialog.get_by_role("button", name="复制到本作", exact=True).click()
        pw.expect(dialog).to_be_hidden()
        pw.expect(page.locator('.character-record').filter(has_text="Synthetic heroine")).to_be_visible()
        assert len(reuse_calls) == 1
        assert not errors
        result = service.get_work(target["id"])
        assert result["version"] == target["version"] + 1
        copied = next(a["current_revision"]["content"] for a in result["artifacts"] if a["kind"] == "character_card" and a["current_revision"]["content"]["name"] == "Synthetic heroine")
        assert copied["trust_status"] == "unverified"
        assert copied["ba_profile"]["notes"]["preserve"] == [1, 2, 3]
        assert copied["reuse_origin"]["work_id"] == source["id"]
        # Explicit adoption must keep structured provenance, not turn it into
        # the string "[object Object]" or drop import/profile metadata.
        page.locator('.character-record').filter(has_text="Synthetic heroine").click()
        editor = page.locator("#libraryCharacterForm")
        pw.expect(editor).to_be_visible()
        assert "[object Object]" not in editor.locator('[name="source"]').input_value()
        editor.locator('.library-editor-more > summary').first.click()
        editor.locator('[name="trust_status"]').select_option("confirmed")
        editor.get_by_role("button", name="保存人物卡", exact=True).click()
        pw.expect(page.locator("body > #toast")).to_contain_text("人物卡已确认")
        adopted = next(a["current_revision"]["content"] for a in service.get_work(target["id"])["artifacts"] if a["kind"] == "character_card" and a["current_revision"]["content"]["name"] == "Synthetic heroine")
        assert adopted["trust_status"] == "confirmed"
        assert adopted["source_refs"] == copied["source_refs"]
        assert adopted["reuse_origin"] == copied["reuse_origin"]
        assert adopted["ba_profile"] == copied["ba_profile"]
        assert service.get_work(source["id"])["version"] == source["version"]
        browser.close()


@pytest.mark.parametrize("changed_scope", ["target", "source"])
def test_character_reuse_conflict_refresh_never_overwrites_newer_data(runtime, changed_scope):
    pw = pytest.importorskip("playwright.sync_api")
    service = runtime.writing_service
    source = service.create_work({"title": "Reusable source"})
    source_result = service.save_character_card(source["id"], {"expected_version": source["version"], "name": "Reusable", "source_refs": ["Synthetic"]})
    source = source_result["work"]
    target = service.create_work({"title": "Safe target"})
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f'http://127.0.0.1:{runtime.port}/?section=references&view=characters&work_id={target["id"]}', wait_until="networkidle")
        page.locator('.library-head-actions details > summary').click()
        page.get_by_role("button", name="从其他作品选取", exact=True).click()
        dialog=page.locator("#characterReuseDialog")
        dialog.locator('[name="source"]').select_option(source["id"])
        dialog.locator('[name="card"]').check()
        if changed_scope == "target":
            target=service.save_character_card(target["id"], {"expected_version": target["version"], "name": "Do not overwrite", "source_refs": ["Later user edit"]})["work"]
        else:
            service.save_character_card(source["id"], {"expected_version": source["version"], "card_id": source_result["card_id"], "name": "Reusable", "role": "Changed after selection", "source_refs": ["Updated source"]})
        dialog.get_by_role("button", name="复制到本作", exact=True).click()
        pw.expect(dialog.locator('[data-reuse-error]')).to_be_visible()
        assert service.get_work(target["id"])["version"] == target["version"]
        dialog.get_by_role("button", name="刷新资料后重新选择", exact=True).click()
        pw.expect(dialog.locator('[type="submit"]')).to_be_disabled()
        dialog.locator('[name="card"]').check()
        dialog.get_by_role("button", name="复制到本作", exact=True).click()
        pw.expect(dialog).to_be_hidden()
        work=service.get_work(target["id"])
        assert work["version"] == target["version"] + 1
        cards=[a["current_revision"]["content"] for a in work["artifacts"] if a["kind"] == "character_card"]
        if changed_scope == "target":
            assert {card["name"] for card in cards} == {"Reusable", "Do not overwrite"}
        else:
            assert cards[0]["role"] == "Changed after selection"
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_activity_refresh_preserves_focus_details_and_last_success(runtime, width):
    """Synthetic read responses exercise the real router/controller without model calls."""
    pw = pytest.importorskip("playwright.sync_api")
    work = runtime.writing_service.create_work({"title": "活动刷新测试"})
    snapshot = dict(work)
    snapshot["agent_runs"] = [{
        "id": "activity-run", "status": "running", "scope_type": "work",
        "policy": {"thread_id": "activity-thread"},
    }]
    jobs = {"state": "running", "fail": False, "reads": 0}
    posts = []
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: posts.append(req.url) if req.method == "POST" else None)
        page.route(
            f"**/api/v1/works/{work['id']}",
            lambda route: route.fulfill(json={"ok": True, "data": snapshot}),
        )
        page.route(
            f"**/api/v1/works/{work['id']}/activity",
            lambda route: route.fulfill(json={"ok": True, "data": snapshot}),
        )

        def job_response(route):
            jobs["reads"] += 1
            if jobs["fail"]:
                route.fulfill(status=503, json={"ok": False})
            else:
                route.fulfill(json={"ok": True, "items": [{
                    "job_id": "job-test", "run_id": "run-test", "state": jobs["state"],
                    "label": "后台制作检查",
                }]})

        page.route("**/production/api/v1/jobs", job_response)
        page.goto(f"http://127.0.0.1:{runtime.port}/?section=tasks&work_id={work['id']}", wait_until="networkidle")
        pw.expect(page.locator(".production-activity-row")).to_contain_text("运行中")
        posts.clear()  # Startup feedback sync is unrelated; activity actions must be read-only.
        page.locator('[data-activity-filter="all"]').click()
        page.locator('[data-task-details="activity-run"] summary').click()
        page.locator('[data-task-details="activity-run"] summary').focus()
        # No button press: the five-second read loop should pick up a same-version run.
        snapshot["agent_runs"][0]["status"] = "waiting_user"
        jobs["state"] = "completed"
        pw.expect(page.locator(".production-activity-row")).to_contain_text("已完成", timeout=9000)
        pw.expect(page.locator(".task-item.waiting_user")).to_have_count(1)
        pw.expect(page.locator('[data-task-details="activity-run"]')).to_have_attribute("open", "")
        pw.expect(page.locator('[data-task-details="activity-run"] summary')).to_be_focused()
        jobs["fail"] = True
        page.locator("[data-activity-refresh]").click()
        pw.expect(page.locator(".activity-unavailable")).to_contain_text("上次读取")
        pw.expect(page.locator(".production-activity-row")).to_contain_text("已完成")
        pw.expect(page.locator("[data-activity-refresh]")).to_be_focused()
        jobs["fail"] = False
        page.locator("[data-production-activity-refresh]").click()
        pw.expect(page.locator(".activity-unavailable")).to_have_count(0)
        # Leaving the route must stop background jobs polling.
        page.locator('[data-mobile="writing"]').click()
        pw.expect(page.locator(".activity-toolbar")).to_have_count(0)
        settled = jobs["reads"]
        page.wait_for_timeout(5600)
        assert jobs["reads"] == settled
        assert not posts
        assert not errors
        browser.close()


@pytest.mark.parametrize("width,theme", [(1440, "light"), (390, "dark")])
def test_manual_manuscript_partial_proposal_review_and_production_journey(runtime, tmp_path, monkeypatch, width, theme):
    """UI journey with local synthetic rules/provider; never edits persistent user works."""
    from halocue_writing.providers import FakeWritingProvider
    from halocue_writing.workflow_pack import ENGINE_RULE_SOURCE, MODE_SOURCES, WORKFLOW_RULE_SOURCES

    class JourneyProvider(FakeWritingProvider):
        def discuss_work(self, messages, context):
            manuscript = context["scene_conversation_context"]["current_manuscript"]
            blocks = manuscript["content"]["blocks"]
            edits = [
                {"block_id": blocks[0]["id"], "old_text": blocks[0]["text"], "new_text": "灯轻轻闪了一下。"},
                {"block_id": blocks[-1]["id"], "old_text": blocks[-1]["text"], "new_text": "我会在这里等。门外传来脚步声。"},
            ]
            return {"text": "已提出两处修改，等待逐条审阅。", "questions": [],
                    "ready_for_proposal": False, "tool_calls": [{"id": "journey-edit",
                    "tool": "propose_scene_text_edit", "arguments": {
                        "base_revision_id": manuscript["revision_id"],
                        "reason": "按用户要求修改灯光与结尾。", "edits": edits}}]}

    rules = tmp_path / "journey-rules"
    for relative in [p for group in WORKFLOW_RULE_SOURCES.values() for p in group] + list(MODE_SOURCES.values()) + [ENGINE_RULE_SOURCE, "knowledge/老师在场规则.md"]:
        target = rules / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Synthetic test rule. Not official material.\n", encoding="utf-8")
    monkeypatch.setenv("HALOCUE_BA_WRITING_SKILL_DIR", str(rules))
    service = runtime.writing_service
    service.provider = JourneyProvider()
    work = service.create_work({"title": "完整写作流程测试"})
    work = service.save_brief(work["id"], {"expected_version": work["version"], "idea": "两位学生检查走廊的灯。", "mode": "bond_short", "characters": ["甲", "乙"]})["work"]
    work = service.generate_blueprint(work["id"], {"expected_version": work["version"]})["work"]
    for name in ["甲", "乙"]:
        work = service.save_character_card(work["id"], {"expected_version": work["version"], "name": name, "voice_anchors": ["先观察再行动"], "source_refs": ["Synthetic test"], "trust_status": "confirmed"})["work"]
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(f"http://127.0.0.1:{runtime.port}/?section=writing&stage=structure&work_id={work['id']}", wait_until="networkidle")
            page.locator("#openSettingsButton").click()
            page.get_by_role("tab", name="外观", exact=True).click()
            page.locator(f'[data-theme-choice="{theme}"]').click()
            page.keyboard.press("Escape")
            page.set_viewport_size({"width": width, "height": 1000 if width > 760 else 844})
            page.locator('#workspace [data-structure-add-chapter]').click()
            form = page.locator('#structureForm')
            form.locator('[name=title]').fill("手动建立的章节")
            form.get_by_role("button", name="保存结构").click()
            pw.expect(page.locator('#structureDialog')).not_to_be_visible()
            # The current outline opens at the whole-work scope; select the new chapter.
            page.locator('[data-outline-scope]').filter(has_text="手动建立的章节").click()
            pw.expect(page.locator('#outlineDocumentForm h2')).to_contain_text("手动建立的章节")
            page.locator('.authoring-scenes > summary').click()
            page.locator('#workspace [data-structure-add-scene]').click()
            form.locator('[name=title]').fill("走廊的灯")
            form.locator('[name=location]').fill("走廊")
            form.locator('[name=goal]').fill("确认灯亮起而不是电路故障")
            form.get_by_role("button", name="保存结构").click()
            pw.expect(page.locator('#structureDialog')).not_to_be_visible()
            lines = [("narration", "", "灯亮着。"), ("dialogue", "甲", "先确认电源。"), ("dialogue", "乙", "我会在这里等。")]
            for index, (kind, speaker, text) in enumerate(lines):
                page.locator('.chapter-authoring-scene [data-chapter-add]').last.click()
                row = page.locator('[data-chapter-block]').nth(index)
                row.locator('[data-chapter-type]').select_option(kind)
                if speaker:
                    row.locator('[data-chapter-speaker]').fill(speaker)
                row.locator('[data-chapter-text]').fill(text)
            page.locator('[data-chapter-save]').click()
            pw.expect(page.locator('[data-chapter-save-state]')).to_have_text("整章已保存")
            saved = service.get_work(work["id"])
            scene = next(scene for chapter in saved["chapters"] for scene in chapter["scenes"])
            scene_id = scene["id"]
            first_revision = scene["current_revision_id"]
            if width <= 760:
                page.locator('[data-writing-mobile-view="agent"]').click()
            page.locator('#sceneAgentMessage').fill("只提出两处修改：灯轻轻闪一下，结尾加脚步声。")
            page.locator('#sceneConversationForm button[type=submit]:not([data-save-for-agent])').click()
            pw.expect(page.locator('[data-generate-scene-proposal]')).to_have_count(0)
            pw.expect(page.locator('[data-scene-change]')).to_have_count(2, timeout=20000)
            assert next(scene for chapter in service.get_work(work["id"])["chapters"] for scene in chapter["scenes"])["current_revision_id"] == first_revision
            # Changes are already shown at their manuscript paragraph positions.
            page.locator('[data-scene-change]').nth(1).uncheck()
            page.locator('[data-apply-scene-changes]').first.click()
            pw.expect(page.locator('[data-scene-change]')).to_have_count(0)
            updated = service.get_work(work["id"])
            manuscript = next(a for a in updated["artifacts"] if a["kind"] == "scene_script" and a["scope_id"] == scene_id)["current_revision"]
            assert "灯轻轻闪了一下" in manuscript["content"]["text"]
            assert "门外传来脚步声" not in manuscript["content"]["text"]
            assert manuscript["provenance"]["partial_accept"] is True
            if width > 1200:
                page.locator('[data-creation-view="release"]').click()
            else:
                page.locator('[data-creation-select]').select_option('release')
            page.locator('[data-release-quick-review]').click()
            pw.expect(page.locator('[data-action="freeze-release"]')).to_be_enabled(timeout=20000)
            page.locator('[data-action="freeze-release"]').click()
            pw.expect(page.locator('[data-handoff]')).to_be_enabled()
            page.locator('[data-handoff]').click()
            pw.expect(page.locator('[data-release-link-status]')).to_contain_text("已关联", timeout=20000)
            final = service.get_work(work["id"])
            assert len(final["releases"]) == 1
            release = final["releases"][0]
            run = runtime.production_service.repository.get_run(release["production_run_id"])
            assert run.source_summary["upstream_release"]["release_id"] == release["id"]
            assert not errors
        except Exception:
            (tmp_path / "journey-failure.html").write_text(page.content(), encoding="utf-8")
            print("JOURNEY DOM:", page.locator("body").inner_text()[-15000:])
            raise
        finally:
            browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_chapter_draft_and_unsent_instruction_survive_failed_save_and_routes(runtime, width):
    from halocue_writing.providers import FakeWritingProvider
    service = runtime.writing_service
    service.provider = FakeWritingProvider()
    work = service.create_work({"title": "手写与助手草稿"})
    brief = service.save_brief(work["id"], {"expected_version": work["version"], "idea": "检查门外灯光", "mode": "bond_short", "characters": ["甲"]})
    work = service.generate_blueprint(work["id"], {"expected_version": brief["work"]["version"]})["work"]
    chapter = service.create_chapter(work["id"], {"expected_version": work["version"], "title": "第一章"})
    scene = service.create_scene(work["id"], chapter["chapter_id"], {"expected_version": chapter["work"]["version"], "title": "第一场", "goal": "确认灯光来源"})
    other = service.create_work({"title": "不能串稿的作品"})
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": 900 if width > 760 else 844})
        errors, writes = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: writes.append(request.url) if request.method == "POST" else None)
        page.goto(f"http://127.0.0.1:{runtime.port}/?section=writing&stage=draft&work_id={work['id']}&chapter_id={chapter['chapter_id']}&scene_id={scene['scene_id']}", wait_until="networkidle")
        if width <= 760:
            page.locator('button[data-writing-mobile-view="manuscript"]').click()
        page.locator('.chapter-authoring-scene [data-chapter-add]').click()
        page.locator('[data-chapter-text]').fill("这是尚未保存的手写正文。")
        # The chapter editor caches the draft; moving to another view keeps it.
        if page.locator('[data-creation-select]').is_visible():
            page.locator('[data-creation-select]').select_option("references")
        else:
            page.locator('[data-creation-view="references"]').click()
        pw.expect(page.locator("#app")).to_have_attribute("data-surface", "references")
        if page.locator('[data-creation-select]').is_visible():
            page.locator('[data-creation-select]').select_option("draft")
        else:
            page.locator('[data-creation-view="draft"]').click()
        pw.expect(page.locator('[data-chapter-text]')).to_have_value("这是尚未保存的手写正文。")
        if width <= 760:
            page.locator('button[data-writing-mobile-view="agent"]').click()
        else:
            if not page.locator('#inspector').is_visible():
                page.locator('.panel-controls [data-panel-toggle="inspector"]').click()
        pw.expect(page.locator('#sceneAgentMessage')).to_be_visible()
        page.locator('#sceneAgentMessage').fill("这个要求先不要发送：保留手写句子。")
        saves = {"count": 0}
        def fail_once(route):
            saves["count"] += 1
            if saves["count"] == 1:
                route.fulfill(status=503, json={"ok": False, "error": {"code": "test_unavailable", "message": "测试保存暂时失败"}})
            else:
                route.continue_()
        page.route(f"**/api/v1/works/{work['id']}/chapters/{chapter['chapter_id']}/manuscript", fail_once)
        if width <= 760:
            page.locator('button[data-writing-mobile-view="manuscript"]').click()
        page.locator('[data-chapter-save]').click()
        pw.expect(page.locator('[data-chapter-save-state]')).to_contain_text("保存失败：测试保存暂时失败")
        pw.expect(page.locator('[data-chapter-save]')).to_be_enabled()
        assert next(s for c in service.get_work(work["id"])["chapters"] for s in c["scenes"])["current_revision_id"] is None
        if width <= 760:
            page.locator('button[data-writing-mobile-view="agent"]').click()
        pw.expect(page.locator('#sceneAgentMessage')).to_have_value("这个要求先不要发送：保留手写句子。")
        if width <= 760:
            page.locator('button[data-writing-mobile-view="manuscript"]').click()
        page.locator('[data-chapter-save]').click()
        pw.expect(page.locator('[data-chapter-save-state]')).to_have_text("整章已保存")
        assert saves["count"] == 2
        if width > 1200:
            page.locator('[data-creation-view="references"]').click()
            page.locator('[data-creation-view="draft"]').click()
        else:
            page.locator('[data-creation-select]').select_option("references")
            page.locator('[data-creation-select]').select_option("draft")
        if width <= 760:
            page.locator('button[data-writing-mobile-view="agent"]').click()
        else:
            if not page.locator('#inspector').is_visible():
                page.locator('.panel-controls [data-panel-toggle="inspector"]').click()
        pw.expect(page.locator('#sceneAgentMessage')).to_have_value("这个要求先不要发送：保留手写句子。")
        # Work switch keeps the unsent instruction owned by the original work.
        root = '.primary-nav' if width > 760 else '.mobile-nav'
        page.locator(root + ' [data-section="projects"], ' + root + ' [data-mobile="projects"]').click()
        page.locator('.project-card').filter(has_text="不能串稿的作品").get_by_role('button', name='打开构思', exact=False).click()
        pw.expect(page.locator('#workConversationForm textarea')).to_have_value("")
        page.locator(root + ' [data-section="projects"], ' + root + ' [data-mobile="projects"]').click()
        page.locator('.project-card').filter(has_text="手写与助手草稿").get_by_role('button', name='正文', exact=True).click()
        if width <= 760:
            page.locator('button[data-writing-mobile-view="agent"]').click()
        else:
            if not page.locator('#inspector').is_visible():
                page.locator('.panel-controls [data-panel-toggle="inspector"]').click()
        pw.expect(page.locator('#sceneAgentMessage')).to_have_value("这个要求先不要发送：保留手写句子。")
        assert not any('/messages' in url or 'scene-proposal:generate' in url for url in writes)
        assert service.get_work(other['id'])['version'] == other['version']
        assert not errors
        browser.close()
