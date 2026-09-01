"""Executable Phase 2 scene Diff acceptance with disposable durable data."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from halocue_writing.app import make_handler
from halocue_writing.service import WritingService


VIEWPORTS = ((1920, 1080), (1440, 900), (1366, 768), (390, 844))


def build_fixture(
    service: WritingService, suffix: str, *, empty_base: bool = False
) -> tuple[str, str, str]:
    work = service.create_work({"title": f"Phase2 场景 Diff {suffix}"})
    work_id = work["id"]
    result = service.save_brief(
        work_id,
        {
            "expected_version": work["version"],
            "idea": "夜间的温室门禁记录突然改变",
            "mode": "bond_short",
            "characters": ["爱丽丝"],
        },
    )
    result = service.generate_blueprint(
        work_id, {"expected_version": result["work"]["version"]}
    )
    first_volume_id = result["work"]["volumes"][0]["id"]
    result = service.create_chapter(
        work_id, {
            "expected_version": result["work"]["version"],
            "title": "第一章",
            "volume_id": first_volume_id,
        },
    )
    first_chapter_id = result["chapter_id"]
    result = service.create_volume(
        work_id,
        {"expected_version": result["work"]["version"], "title": "第二卷"},
    )
    result = service.create_chapter(
        work_id, {
            "expected_version": result["work"]["version"],
            "title": "第二卷第一章",
            "volume_id": result["volume_id"],
        },
    )
    result = service.create_scene(
        work_id,
        result["chapter_id"],
        {
            "expected_version": result["work"]["version"],
            "title": "后续调查",
            "location": "旧校舍",
            "goal": "确认异常是否延续",
        },
    )
    result = service.create_scene(
        work_id,
        first_chapter_id,
        {
            "expected_version": result["work"]["version"],
            "title": "门禁记录",
            "location": "温室",
            "goal": "确认记录为何改变",
        },
    )
    scene_id = result["scene_id"]
    result = service.generate_scene_candidate(
        work_id, scene_id, {"expected_version": result["work"]["version"]}
    )
    if empty_base:
        return work_id, scene_id, result["proposal_id"]
    result = service.accept_proposal(
        work_id,
        result["proposal_id"],
        {
            "expected_version": result["work"]["version"],
            "text": "旁白: 夜里的温室没有开灯。\n爱丽丝: 先确认门禁记录。\n",
        },
    )
    result = service.save_character_card(
        work_id,
        {
            "expected_version": result["work"]["version"],
            "card_id": "character-aris",
            "name": "爱丽丝",
            "source_refs": ["用户确认"],
            "voice_anchors": ["先确认眼前的情况。"],
            "trust_status": "confirmed",
        },
    )
    result = service.configure_scene_context(
        work_id,
        scene_id,
        {
            "expected_version": result["work"]["version"],
            "character_card_ids": ["character-aris"],
            "world_item_ids": [],
            "reference_file_ids": [],
        },
    )
    result = service.run_scene_rewrite_agent(
        work_id,
        scene_id,
        {
            "expected_version": result["work"]["version"],
            "instruction": "在末尾增加一个不解释原因的环境动作。",
        },
    )
    return work_id, scene_id, result["proposal_id"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    web_root = PROJECT_ROOT / "web"

    results: list[dict] = []
    with tempfile.TemporaryDirectory(
        prefix="halocue-phase2-", dir=args.output, ignore_cleanup_errors=True
    ) as data_dir:
        service = WritingService(Path(data_dir))
        service.start()
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(service, web_root)
        )
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    for width, height in VIEWPORTS:
                        work_id, scene_id, proposal_id = build_fixture(
                            service,
                            f"{width}x{height}",
                            empty_base=width == 1920,
                        )
                        page = browser.new_page(
                            viewport={"width": width, "height": height}
                        )
                        console_issues: list[dict] = []
                        page.on(
                            "console",
                            lambda message: console_issues.append(
                                {"type": message.type, "text": message.text}
                            )
                            if message.type in {"error", "warning"}
                            else None,
                        )
                        page.on(
                            "pageerror",
                            lambda error: console_issues.append(
                                {"type": "pageerror", "text": str(error)}
                            ),
                        )
                        failed_requests: list[dict] = []
                        page.on(
                            "requestfailed",
                            lambda request: failed_requests.append(
                                {
                                    "url": request.url,
                                    "error": request.failure or "request failed",
                                }
                            ),
                        )
                        homepage_url = (
                            f"http://127.0.0.1:{server.server_port}/?section=works"
                            f"&work_id={work_id}"
                        )
                        response = page.goto(
                            homepage_url, wait_until="domcontentloaded"
                        )
                        if response is None or not response.ok:
                            raise AssertionError(
                                f"work homepage navigation failed: {homepage_url}"
                            )
                        page.locator("body:not(.app-loading)").wait_for(timeout=20_000)
                        status = page.locator(".work-user-status")
                        status.wait_for(timeout=20_000)
                        status_action = status.locator("[data-user-status-action]")
                        assert status.locator("h3").inner_text() == "审查正文候选"
                        assert status_action.inner_text() == "审查正文候选"
                        assert status_action.get_attribute(
                            "data-user-status-action"
                        ) == "review_scene_candidate"
                        assert page.locator(".work-agent-empty").count() == 0

                        homepage_metrics = page.evaluate(
                            """() => {
                              const status = document.querySelector('.work-user-status');
                              const action = status?.querySelector('[data-user-status-action]');
                              const visiblePrimaryActions = [...document.querySelectorAll('.work-user-status button.primary')]
                                .filter(element => element.getClientRects().length).length;
                              const box = action?.getBoundingClientRect();
                              return {
                                overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                                visiblePrimaryActions,
                                actionBox: box ? {top: box.top, right: box.right, bottom: box.bottom, left: box.left} : null,
                                viewport: {width: innerWidth, height: innerHeight},
                              };
                            }"""
                        )
                        assert homepage_metrics["viewport"] == {
                            "width": width,
                            "height": height,
                        }
                        assert homepage_metrics["overflowX"] == 0
                        assert homepage_metrics["visiblePrimaryActions"] == 1
                        action_box = homepage_metrics["actionBox"]
                        assert action_box
                        assert action_box["left"] >= 0
                        assert action_box["right"] <= width
                        assert action_box["top"] >= 0
                        assert action_box["bottom"] <= height

                        homepage_screenshot = (
                            args.output
                            / f"phase2-work-next-action-{width}x{height}.png"
                        )
                        page.screenshot(path=homepage_screenshot, full_page=False)

                        status_action.click()
                        page.wait_for_function(
                            """([workId, sceneId]) => {
                              const params = new URLSearchParams(location.search);
                              return params.get('section') === 'writing'
                                && params.get('work_id') === workId
                                && params.get('scene_id') === sceneId;
                            }""",
                            arg=[work_id, scene_id],
                            timeout=20_000,
                        )
                        diff = page.locator("[data-scene-diff-root]")
                        diff.wait_for(timeout=20_000)
                        page.wait_for_timeout(250)

                        checkbox = page.locator("[data-scene-change]").first
                        apply_button = page.locator(
                            "[data-apply-scene-changes]"
                        )
                        metrics = page.evaluate(
                            """() => ({
                              viewport: {width: innerWidth, height: innerHeight},
                              overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                              activeGlobalNav: [...document.querySelectorAll('.primary-nav [data-section].active')]
                                .map(el => el.dataset.section),
                              diffChanges: document.querySelectorAll('[data-scene-diff-root] [data-scene-change]').length,
                              binderVolumes: document.querySelectorAll('#treePanel [data-writing-volume]').length,
                              scope: document.querySelector('#crumb')?.textContent || '',
                            })"""
                        )
                        assert metrics["viewport"] == {
                            "width": width,
                            "height": height,
                        }
                        assert metrics["overflowX"] == 0
                        assert metrics["activeGlobalNav"] == ["writing"]
                        assert metrics["diffChanges"] >= 1
                        assert metrics["binderVolumes"] == 2
                        choice_previews = page.locator(
                            ".scene-diff-choice [data-scene-change-preview]"
                        )
                        assert choice_previews.count() == metrics["diffChanges"]
                        preview_texts = [
                            choice_previews.nth(index).inner_text().strip()
                            for index in range(choice_previews.count())
                        ]
                        assert all(preview_texts)
                        assert len(set(preview_texts)) == len(preview_texts)
                        assert "加入这段内容" not in diff.inner_text()
                        assert page.locator(".scene-inline-empty").count() == 0
                        assert "无对应文字" not in diff.inner_text()
                        if width == 1920:
                            assert page.locator(
                                ".scene-full-context .scene-context-line.is-added"
                            ).count() == metrics["diffChanges"]
                            assert page.locator(
                                ".scene-full-context .scene-context-line.is-removed"
                            ).count() == 0
                        assert "门禁记录" in metrics["scope"]
                        if width > 640:
                            assert "第一卷 / 第一章 / 门禁记录" in metrics["scope"]

                        panel_metrics = None
                        if width == 1366:
                            page.evaluate(
                                """() => {
                                  window.HaloCuePanels.open('tree');
                                  window.HaloCuePanels.open('inspector');
                                }"""
                            )
                            page.wait_for_timeout(220)
                            panel_metrics = page.evaluate(
                                """() => ({
                                  workspaceWidth: document.querySelector('#workspace').getBoundingClientRect().width,
                                  treeWidth: document.querySelector('.tree-panel').getBoundingClientRect().width,
                                  inspectorWidth: document.querySelector('.inspector').getBoundingClientRect().width,
                                })"""
                            )
                            page.locator('[data-panel-toggle="tree"]').click()
                            page.wait_for_timeout(220)
                            tree_collapsed = page.evaluate(
                                """() => ({
                                  collapsed: document.querySelector('#app').classList.contains('tree-collapsed'),
                                  workspaceWidth: document.querySelector('#workspace').getBoundingClientRect().width,
                                  inert: document.querySelector('.tree-panel').inert,
                                  ariaHidden: document.querySelector('.tree-panel').getAttribute('aria-hidden'),
                                  visibleFocusable: [...document.querySelectorAll('.tree-panel button, .tree-panel a, .tree-panel input, .tree-panel select, .tree-panel textarea')]
                                    .filter(element => !element.closest('[inert]') && element.getClientRects().length).length,
                                })"""
                            )
                            assert tree_collapsed["collapsed"] is True
                            assert tree_collapsed["inert"] is True
                            assert tree_collapsed["ariaHidden"] == "true"
                            assert tree_collapsed["visibleFocusable"] == 0
                            assert tree_collapsed["workspaceWidth"] > panel_metrics["workspaceWidth"]

                            page.reload(wait_until="domcontentloaded")
                            page.locator("body:not(.app-loading)").wait_for(timeout=20_000)
                            assert page.locator("#app").evaluate(
                                "element => element.classList.contains('tree-collapsed')"
                            )
                            assert page.locator(".tree-panel").evaluate("element => element.inert")

                            page.locator('[data-panel-toggle="inspector"]').click()
                            page.wait_for_timeout(220)
                            both_collapsed = page.evaluate(
                                """() => ({
                                  focusMode: document.querySelector('#app').classList.contains('focus-mode'),
                                  workspaceWidth: document.querySelector('#workspace').getBoundingClientRect().width,
                                  inspectorInert: document.querySelector('.inspector').inert,
                                  inspectorAriaHidden: document.querySelector('.inspector').getAttribute('aria-hidden'),
                                  visibleFocusable: [...document.querySelectorAll('.inspector button, .inspector a, .inspector input, .inspector select, .inspector textarea')]
                                    .filter(element => !element.closest('[inert]') && element.getClientRects().length).length,
                                })"""
                            )
                            assert both_collapsed["focusMode"] is True
                            assert both_collapsed["inspectorInert"] is True
                            assert both_collapsed["inspectorAriaHidden"] == "true"
                            assert both_collapsed["visibleFocusable"] == 0
                            assert both_collapsed["workspaceWidth"] > tree_collapsed["workspaceWidth"]

                            page.reload(wait_until="domcontentloaded")
                            page.locator("body:not(.app-loading)").wait_for(timeout=20_000)
                            persisted = page.evaluate(
                                """() => ({
                                  tree: document.querySelector('#app').classList.contains('tree-collapsed'),
                                  inspector: document.querySelector('#app').classList.contains('inspector-collapsed'),
                                  focusMode: document.querySelector('#app').classList.contains('focus-mode'),
                                })"""
                            )
                            assert persisted == {
                                "tree": True,
                                "inspector": True,
                                "focusMode": True,
                            }
                            page.locator('[data-panel-toggle="tree"]').click()
                            page.locator('[data-panel-toggle="inspector"]').click()
                            page.wait_for_timeout(220)

                        if width <= 640:
                            apply_button.scroll_into_view_if_needed()
                            page.wait_for_timeout(120)
                            button_box = apply_button.bounding_box()
                            nav_box = page.locator(".mobile-nav").bounding_box()
                            assert button_box and nav_box
                            assert button_box["y"] + button_box["height"] < nav_box["y"]

                            # Cross-surface navigation must not inherit the
                            # manuscript's long scroll position, and leaving
                            # the catalog must remove its overlay state.
                            page.evaluate(
                                "document.querySelector('#workspace').scrollTop = 240"
                            )
                            page.locator(
                                ".mobile-more-menu > summary"
                            ).click()
                            page.locator(
                                '.mobile-more-menu [data-section="assets"]'
                            ).click()
                            page.locator(".asset-catalog-hero").wait_for(
                                timeout=20_000
                            )
                            assert page.locator("#workspace").evaluate(
                                "element => element.scrollTop"
                            ) == 0
                            page.locator('[data-mobile="writing"]').click()
                            diff.wait_for(timeout=20_000)
                            assert page.locator(".asset-catalog-hero").count() == 0
                            assert page.locator(".writing-mobile-tabs").is_visible()
                            assert page.locator("#workspace").evaluate(
                                "element => element.scrollTop"
                            ) == 0

                        screenshot = args.output / f"phase2-scene-diff-{width}x{height}.png"
                        page.screenshot(path=screenshot, full_page=False)

                        for index in range(page.locator("[data-scene-change]").count()):
                            page.locator("[data-scene-change]").nth(index).uncheck()
                        assert apply_button.is_disabled()
                        assert apply_button.inner_text() == "应用 0 项修改"
                        checkbox.check()
                        assert apply_button.is_enabled()
                        selected_count = page.locator(
                            "[data-scene-change]:checked"
                        ).count()
                        assert apply_button.inner_text() == f"应用 {selected_count} 项修改"
                        apply_button.click()
                        diff.wait_for(state="detached", timeout=20_000)

                        work = service.get_work(work_id)
                        proposal = next(
                            item for item in work["proposals"] if item["id"] == proposal_id
                        )
                        scene = next(
                            scene
                            for chapter in work["chapters"]
                            for scene in chapter["scenes"]
                            if scene["id"] == scene_id
                        )
                        assert proposal["status"] == "accepted"
                        assert scene["current_revision_id"] != proposal["base_revision_id"]
                        assert not console_issues
                        assert not failed_requests
                        results.append(
                            {
                                "viewport": f"{width}x{height}",
                                "screenshot": screenshot.name,
                                "homepage_screenshot": homepage_screenshot.name,
                                "homepage_metrics": homepage_metrics,
                                "metrics": metrics,
                                "panel_metrics": panel_metrics,
                                "selected_change_count": selected_count,
                                "proposal_status_after_apply": proposal["status"],
                                "console_issues": console_issues,
                                "failed_requests": failed_requests,
                            }
                        )
                        page.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)
            service.close()

    report = {
        "fixture": "phase2-scene-writing",
        "results": results,
        "failures": [],
    }
    (args.output / "browser-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
