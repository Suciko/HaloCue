"""Executable Phase 1 work-Agent acceptance with disposable durable data."""

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
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


VIEWPORTS = ((1920, 1080), (1440, 900), (1366, 768), (390, 844))


class WorkAgentAcceptanceProvider(FakeWritingProvider):
    kind = "phase1-acceptance"
    display_name = "Phase 1 acceptance provider"
    is_simulation = True

    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        reply = super().discuss_work(messages, work_context)
        reply["reasoning_summary"] = "先核对当前作品资料，再把本轮建议限制在可审查草稿中。"
        return reply


def build_fixture(service: WritingService, suffix: str) -> tuple[str, str, str]:
    service.provider = WorkAgentAcceptanceProvider()
    work = service.create_work(
        {
            "title": f"Phase1 作品 Agent {suffix}",
            "idea": "白露在雨夜发现旧档案室仍有一盏提示灯亮着。",
        }
    )
    thread = work["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"],
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "我改主意了：不要把提示灯解释成故障，先保留未知原因。",
        },
    )
    thread = discussed["work"]["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"],
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "请创建一个叫《白露》的自定义角色卡，她负责核对档案，但不要直接修改正式资料。",
        },
    )
    thread = discussed["work"]["conversation_threads"][0]
    proposed = service.propose_conversation_knowledge(
        work["id"],
        thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": thread["version"],
            "kind": "character_card",
        },
    )
    return work["id"], thread["id"], proposed["proposal_id"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    with tempfile.TemporaryDirectory(
        prefix="halocue-phase1-", dir=args.output, ignore_cleanup_errors=True
    ) as data_dir:
        service = WritingService(Path(data_dir))
        service.start()
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(service, PROJECT_ROOT / "web")
        )
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    for width, height in VIEWPORTS:
                        work_id, thread_id, proposal_id = build_fixture(
                            service, f"{width}x{height}"
                        )
                        page = browser.new_page(viewport={"width": width, "height": height})
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
                        url = (
                            f"http://127.0.0.1:{server.server_port}/?section=works"
                            f"&work_id={work_id}"
                        )
                        response = page.goto(url, wait_until="domcontentloaded")
                        if response is None or not response.ok:
                            raise AssertionError(f"workbench navigation failed: {url}")
                        page.locator("body:not(.app-loading)").wait_for(timeout=20_000)
                        page.locator(".work-agent-canvas").wait_for(timeout=20_000)
                        proposal_card = page.locator(
                            f'.agent-inline-artifact.proposal:has([data-knowledge-field="{proposal_id}"])'
                        )
                        proposal_card.wait_for(timeout=20_000)
                        page.wait_for_timeout(250)

                        metrics = page.evaluate(
                            """() => ({
                              viewport: {width: innerWidth, height: innerHeight},
                              overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                              inlineStyles: [...document.querySelectorAll('[style]')].map(el => ({
                                id: el.id, className: el.className, style: el.getAttribute('style')
                              })),
                              activeGlobalNav: [...document.querySelectorAll('.primary-nav [data-section].active')]
                                .map(el => el.dataset.section),
                              visibleComposers: [...document.querySelectorAll('.work-agent-composer')]
                                .filter(el => getComputedStyle(el).display !== 'none').length,
                              messages: document.querySelectorAll('.conversation-message').length,
                              thinking: document.querySelectorAll('details.agent-thinking').length,
                              openThinking: document.querySelectorAll('details.agent-thinking[open]').length,
                              runSummaries: document.querySelectorAll('details.agent-presentation-summary').length,
                              openRunSummaries: document.querySelectorAll('details.agent-presentation-summary[open]').length,
                            })"""
                        )
                        assert metrics["viewport"] == {"width": width, "height": height}
                        assert metrics["overflowX"] == 0
                        assert metrics["inlineStyles"] == []
                        assert metrics["activeGlobalNav"] == ["works"]
                        assert metrics["visibleComposers"] == 1
                        assert metrics["messages"] >= 6
                        assert metrics["thinking"] >= 1
                        assert metrics["openThinking"] == 0
                        assert metrics["runSummaries"] == 1
                        assert metrics["openRunSummaries"] == 0

                        page.locator("details.agent-presentation-summary > summary").click()
                        run_summary_text = page.locator(
                            ".agent-presentation-body"
                        ).inner_text()
                        assert "工具" in run_summary_text
                        page.locator("details.agent-presentation-summary > summary").click()

                        if width <= 640:
                            assert page.locator(".mobile-nav").is_visible()
                            assert not page.locator(".primary-nav").is_visible()
                        else:
                            assert page.locator(".work-agent-rail").is_visible()

                        screenshot = args.output / f"phase1-work-agent-{width}x{height}.png"
                        page.screenshot(path=screenshot, full_page=False)

                        apply_button = page.locator(
                            f'[data-knowledge-apply-count="{proposal_id}"]'
                        )
                        assert apply_button.is_enabled()
                        apply_button.click()
                        proposal_card.wait_for(state="detached", timeout=20_000)
                        accepted = service.get_work(work_id)
                        proposal = next(
                            item for item in accepted["proposals"] if item["id"] == proposal_id
                        )
                        assert proposal["status"] == "accepted"
                        assert any(
                            item["kind"] == "character_card"
                            and item["current_revision"]["content"]["name"] == "白露"
                            for item in accepted["artifacts"]
                        )

                        composer = page.locator("#workConversationForm textarea")
                        composer.fill("继续讨论，但保留刚才确认的人物边界。")
                        previous_message_count = page.locator(
                            ".conversation-message"
                        ).count()
                        composer.press("Enter")
                        page.wait_for_function(
                            "count => document.querySelectorAll('.conversation-message').length > count",
                            arg=previous_message_count,
                            timeout=20_000,
                        )
                        page.locator(".agent-running-message").wait_for(
                            state="detached", timeout=20_000
                        )

                        page.reload(wait_until="domcontentloaded")
                        page.locator("body:not(.app-loading)").wait_for(timeout=20_000)
                        page.locator(".work-agent-canvas").wait_for(timeout=20_000)
                        restored_text = page.locator(".work-agent-thread").inner_text()
                        assert "继续讨论，但保留刚才确认的人物边界" in restored_text
                        restored = service.get_work(work_id)
                        restored_thread = next(
                            item
                            for item in restored["conversation_threads"]
                            if item["id"] == thread_id
                        )
                        assert len(restored_thread["messages"]) >= 8
                        assert not console_issues
                        results.append(
                            {
                                "viewport": f"{width}x{height}",
                                "screenshot": screenshot.name,
                                "metrics": metrics,
                                "proposal_status_after_apply": proposal["status"],
                                "restored_message_count": len(restored_thread["messages"]),
                                "console_issues": console_issues,
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

    report = {"fixture": "phase1-work-agent", "results": results, "failures": []}
    (args.output / "browser-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
