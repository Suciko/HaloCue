"""Executable Phase 3 knowledge Proposal acceptance with disposable durable data."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from halocue_writing.app import make_handler
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


VIEWPORTS = ((1920, 1080), (1440, 900), (1366, 768), (390, 844))


class KnowledgeUpdateProvider(FakeWritingProvider):
    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        return {
            "text": "我整理了凯伊在温室调查中的两项人物约束。",
            "ready_for_proposal": True,
            "artifact_preview": {
                "kind": "character_card",
                "title": "凯伊",
                "status": "discussion_draft",
                "content": {
                    "name": "凯伊",
                    "role": "负责核对门禁记录，并在证据不足时暂停判断。",
                    "knowledge_boundary": "知道温室门禁记录曾在夜间改变。",
                },
            },
        }

    def project_commit_revision(self, projection_kind: str, projection_input: dict) -> dict:
        scene_id = projection_input["scene_id"]
        content = {
            "summary": {"text": "温室门禁在教师授权后开放。"},
            "search": {"terms": ["温室", "门禁", "教师授权"]},
            "memory_followup": {"required": True, "scene_id": scene_id},
            "review_followup": {"required": True, "scene_id": scene_id},
        }[projection_kind]
        return {
            "schema_version": "commit-projection-output/1.0",
            "kind": projection_kind,
            "source_revision_id": projection_input["revision_id"],
            "content": content,
        }

    def extract_memory_bundle(self, memory_context: dict) -> dict:
        return {
            "schema_version": "memory-bundle/1.0",
            "summary": "发现一条需要长期维护的门禁事实。",
            "items": [],
            "knowledge_suggestions": [
                {
                    "kind": "canon_fact",
                    "text": "温室夜间关闭，但教师可以临时授权进入。",
                    "scope": "work",
                    "confidence_status": "open",
                    "source_block_ids": ["block-gate"],
                }
            ],
        }


def build_fixture(service: WritingService, suffix: str) -> tuple[str, str, str]:
    work = service.create_work({"title": f"Phase3 资料影响 {suffix}"})
    result = service.save_brief(
        work["id"],
        {
            "expected_version": work["version"],
            "idea": "凯伊调查夜间变化的温室门禁记录。",
            "mode": "bond_short",
            "characters": ["凯伊"],
        },
    )
    result = service.generate_blueprint(
        work["id"], {"expected_version": result["work"]["version"]}
    )
    chapter_id = result["work"]["chapters"][0]["id"]
    result = service.create_scene(
        work["id"],
        chapter_id,
        {
            "expected_version": result["work"]["version"],
            "title": "核对门禁",
            "location": "温室",
            "goal": "确认访问记录为何改变",
        },
    )
    scene_id = result["scene_id"]
    result = service.save_character_card(
        work["id"],
        {
            "expected_version": result["work"]["version"],
            "card_id": "character-kei",
            "name": "凯伊",
            "role": "负责核对门禁记录。",
            "source_type": "custom",
            "source_refs": ["用户确认"],
            "trust_status": "confirmed",
        },
    )
    result = service.save_world_bible(
        work["id"],
        {
            "expected_version": result["work"]["version"],
            "title": "温室调查设定",
            "source_type": "custom",
            "entities": [
                {
                    "id": "world-greenhouse",
                    "name": "温室",
                    "kind": "place",
                    "summary": "夜间门禁记录会保留访问变化。",
                    "source": "用户确认",
                    "source_type": "custom",
                    "confidence_status": "confirmed",
                    "participants": ["凯伊"],
                    "participant_character_ids": ["character-kei"],
                }
            ],
            "rules": [],
            "timeline": [
                {
                    "id": "event-curfew-change",
                    "text": "温室门禁记录在夜间发生变化。",
                    "category": "当前剧情",
                    "source": "用户确认",
                    "confidence_status": "confirmed",
                    "participants": ["凯伊"],
                    "participant_character_ids": ["character-kei"],
                }
            ],
        },
    )
    result = service.save_world_bible(
        work["id"],
        {
            "expected_version": result["work"]["version"],
            "title": "温室调查设定",
            "source_type": "custom",
            "entities": [
                {
                    "id": "world-greenhouse",
                    "name": "温室",
                    "kind": "place",
                    "summary": "夜间关闭，但教师可临时授权进入；门禁会保留访问变化。",
                    "source": "用户确认",
                    "source_type": "custom",
                    "confidence_status": "confirmed",
                    "participants": ["凯伊"],
                    "participant_character_ids": ["character-kei"],
                }
            ],
            "rules": [],
            "timeline": [
                {
                    "id": "event-curfew-change",
                    "text": "温室门禁记录在夜间发生变化。",
                    "category": "当前剧情",
                    "source": "用户确认",
                    "confidence_status": "confirmed",
                    "participants": ["凯伊"],
                    "participant_character_ids": ["character-kei"],
                }
            ],
        },
    )
    result = service.configure_scene_context(
        work["id"],
        scene_id,
        {
            "expected_version": result["work"]["version"],
            "character_card_ids": ["character-kei"],
            "world_item_ids": [],
            "reference_file_ids": [],
        },
    )
    service.provider = KnowledgeUpdateProvider()
    result = service.save_scene_manuscript(
        work["id"],
        scene_id,
        {
            "expected_version": result["work"]["version"],
            "base_revision_id": None,
            "blocks": [
                {
                    "id": "block-gate",
                    "type": "action",
                    "speaker": "",
                    "text": "教师出示授权后，温室门禁在夜间短暂开放。",
                }
            ],
        },
    )
    service.run_commit_projection(work["id"], result["revision_id"])
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        discovered = service.get_work(work["id"])
        background_suggestion = next(
            (
                item
                for item in discovered["proposals"]
                if item["status"] == "pending"
                and item["evidence"].get("background_suggestion")
            ),
            None,
        )
        if background_suggestion:
            break
        dispatched = service.agent_dispatcher.run_once()
        if not dispatched["handled"]:
            time.sleep(0.05)
            continue
        if dispatched.get("status") != "succeeded":
            raise AssertionError(dispatched)
    else:
        raise AssertionError("knowledge.discover did not produce a reviewable suggestion")
    thread = result["work"]["conversation_threads"][0]
    result = service.post_conversation_message(
        work["id"],
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "更新凯伊的职责和知情边界，但先让我逐项审查。",
        },
    )
    result = service.propose_conversation_knowledge(
        work["id"],
        thread["id"],
        {
            "expected_version": result["work"]["version"],
            "expected_thread_version": result["work"]["conversation_threads"][0]["version"],
            "kind": "character_card",
        },
    )
    return work["id"], result["proposal_id"], background_suggestion["id"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    web_root = PROJECT_ROOT / "web"

    results: list[dict] = []
    with tempfile.TemporaryDirectory(
        prefix="halocue-phase3-", dir=args.output, ignore_cleanup_errors=True
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
                        work_id, proposal_id, background_suggestion_id = build_fixture(
                            service, f"{width}x{height}"
                        )
                        page = browser.new_page(viewport={"width": width, "height": height})
                        console_issues: list[dict] = []
                        page.on(
                            "console",
                            lambda message: console_issues.append(
                                {"type": message.type, "text": message.text}
                            ) if message.type in {"error", "warning"} else None,
                        )
                        page.on(
                            "pageerror",
                            lambda error: console_issues.append(
                                {"type": "pageerror", "text": str(error)}
                            ),
                        )
                        url = (
                            f"http://127.0.0.1:{server.server_port}/?section=works"
                            f"&work_id={work_id}"
                        )
                        response = page.goto(url, wait_until="domcontentloaded")
                        if response is None or not response.ok:
                            raise AssertionError(f"work Agent navigation failed: {url}")
                        page.locator("body:not(.app-loading)").wait_for(timeout=20_000)
                        checkboxes = page.locator(
                            f'[data-knowledge-field="{proposal_id}"]'
                        )
                        checkboxes.first.wait_for(timeout=20_000)
                        apply_button = page.locator(
                            f'[data-knowledge-apply-count="{proposal_id}"]'
                        )
                        impact = page.locator(".knowledge-impact-preview").last
                        proposal_card = checkboxes.first.locator(
                            "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' agent-inline-artifact ') and contains(concat(' ', normalize-space(@class), ' '), ' proposal ')][1]"
                        )
                        proposal_card.evaluate(
                            """element => {
                              element.scrollIntoView({block: 'start', inline: 'nearest'});
                              const scroller = element.closest('.conversation-thread-scroll, .agent-thread, main');
                              if (scroller) scroller.scrollTop = Math.max(0, scroller.scrollTop - 12);
                            }"""
                        )
                        page.wait_for_timeout(200)

                        metrics = page.evaluate(
                            """() => ({
                              viewport: {width: innerWidth, height: innerHeight},
                              overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                              activeGlobalNav: [...document.querySelectorAll('.primary-nav [data-section].active')]
                                .map(el => el.dataset.section),
                              proposalCards: document.querySelectorAll('.agent-inline-artifact.proposal').length,
                              visibleComposer: [...document.querySelectorAll('.conversation-composer')]
                                .filter(el => el.getBoundingClientRect().width > 0).length,
                            })"""
                        )
                        assert metrics["viewport"] == {"width": width, "height": height}
                        assert metrics["overflowX"] == 0
                        assert metrics["activeGlobalNav"] == ["works"]
                        assert metrics["proposalCards"] >= 1
                        assert metrics["visibleComposer"] == 1
                        assert "场景《核对门禁》" in impact.inner_text()

                        screenshot = args.output / f"phase3-knowledge-impact-{width}x{height}.png"
                        page.screenshot(path=screenshot, full_page=False)

                        impact.scroll_into_view_if_needed()
                        for index in range(checkboxes.count()):
                            checkboxes.nth(index).uncheck()
                        assert apply_button.is_disabled()
                        assert apply_button.inner_text() == "应用 0 项修改"
                        checkboxes.first.check()
                        assert apply_button.is_enabled()
                        assert apply_button.inner_text() == "应用 1 项修改"
                        apply_button.click()
                        checkboxes.first.wait_for(state="detached", timeout=20_000)

                        work_state = service.get_work(work_id)
                        proposal = next(
                            item for item in work_state["proposals"] if item["id"] == proposal_id
                        )
                        card = next(
                            item for item in work_state["artifacts"]
                            if item["kind"] == "character_card" and item["scope_id"] == "character-kei"
                        )
                        assert proposal["status"] == "accepted"
                        assert card["current_revision"]["provenance"]["partial_accept"] is True
                        assert card["current_revision"]["provenance"]["applied_fields"]

                        projection_url = (
                            f"http://127.0.0.1:{server.server_port}/?section=references"
                            f"&work_id={work_id}"
                        )
                        projection_response = page.goto(
                            projection_url, wait_until="domcontentloaded"
                        )
                        if projection_response is None or not projection_response.ok:
                            raise AssertionError(
                                f"knowledge projection navigation failed: {projection_url}"
                            )
                        page.locator("body:not(.app-loading)").wait_for(timeout=20_000)
                        page.locator('[data-library-view="relations"]').first.click()
                        projection_status = page.locator(".structure-projection")
                        projection_status.wait_for(timeout=20_000)
                        page.locator(".knowledge-node.character").first.wait_for(timeout=20_000)
                        projection_metrics = page.evaluate(
                            """() => ({
                              overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                              graphNodes: document.querySelectorAll('.knowledge-node').length,
                              graphLinks: document.querySelectorAll('.knowledge-link').length,
                              structureVolumes: document.querySelectorAll('.structure-projection-volumes > div').length,
                            })"""
                        )
                        assert projection_metrics["overflowX"] == 0
                        assert projection_metrics["graphNodes"] >= 3
                        assert projection_metrics["graphLinks"] >= 1
                        assert projection_metrics["structureVolumes"] >= 1
                        assert "当前正式修订" in page.locator(".library-main").inner_text()
                        projection_screenshot = (
                            args.output / f"phase3-current-projection-{width}x{height}.png"
                        )
                        page.screenshot(path=projection_screenshot, full_page=False)

                        page.locator('[data-library-view="suggestions"]').click()
                        suggestion_card = page.locator(".background-suggestion-card")
                        suggestion_card.wait_for(timeout=20_000)
                        suggestion_text = suggestion_card.inner_text()
                        assert "温室夜间关闭，但教师可以临时授权进入" in suggestion_text
                        assert "直接证据" in suggestion_text
                        assert "1 个正文块" in suggestion_text
                        suggestion_screenshot = (
                            args.output / f"phase3-background-suggestion-{width}x{height}.png"
                        )
                        page.screenshot(path=suggestion_screenshot, full_page=False)
                        page.locator(
                            f'[data-accept-director-proposal="{background_suggestion_id}"]'
                        ).click()
                        suggestion_card.wait_for(state="detached", timeout=20_000)
                        accepted_background = next(
                            item
                            for item in service.get_work(work_id)["proposals"]
                            if item["id"] == background_suggestion_id
                        )
                        assert accepted_background["status"] == "accepted"

                        page.locator('[data-library-view="world"]').click()
                        page.locator(
                            '[data-edit-world-entry="entity:world-greenhouse"]'
                        ).click()
                        page.locator('[data-world-history]').click()
                        comparison_button = page.locator(
                            '[data-compare-revision]:not([disabled])'
                        ).first
                        comparison_button.click()
                        comparison_dialog = page.locator("#revisionCompareDialog")
                        comparison_dialog.wait_for(state="visible", timeout=20_000)
                        comparison_dialog.locator(
                            ".revision-compare-change"
                        ).first.wait_for(timeout=20_000)
                        comparison_paths = comparison_dialog.locator(
                            ".revision-compare-change > header code"
                        ).all_inner_texts()
                        assert "/entities/world-greenhouse/summary" in comparison_paths
                        assert "/entities" not in comparison_paths
                        assert "sha256:sha256:" not in page.locator(
                            "#revisionCompareMeta"
                        ).inner_text()
                        comparison_screenshot = (
                            args.output / f"phase3-revision-compare-{width}x{height}.png"
                        )
                        page.screenshot(path=comparison_screenshot, full_page=False)
                        page.locator('[data-close-revision-compare]').click()

                        assert not console_issues
                        results.append({
                            "viewport": f"{width}x{height}",
                            "screenshot": screenshot.name,
                            "metrics": metrics,
                            "proposal_status_after_apply": proposal["status"],
                            "applied_fields": card["current_revision"]["provenance"]["applied_fields"],
                            "projection_screenshot": projection_screenshot.name,
                            "projection_metrics": projection_metrics,
                            "background_suggestion_screenshot": suggestion_screenshot.name,
                            "background_suggestion_status_after_apply": accepted_background["status"],
                            "revision_comparison_screenshot": comparison_screenshot.name,
                            "revision_comparison_paths": comparison_paths,
                            "console_issues": console_issues,
                        })
                        page.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)
            service.close()

    report = {"fixture": "phase3-knowledge-impact", "results": results, "failures": []}
    (args.output / "browser-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
