"""Executable Phase 5 release-gate and ScriptRelease acceptance.

The fixture deliberately leaves non-blocking review findings open.  The browser
must still enforce continuity -> release review -> freeze in that order, then
surface the immutable release identity and its BA/source-set provenance.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from halocue_writing.app import make_handler
from halocue_writing.release_integrity import source_set_digest
from halocue_writing.service import WritingService


VIEWPORTS = ((1920, 1080), (1440, 900), (1366, 768), (390, 844))
SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


def build_fixture(service: WritingService, suffix: str) -> dict:
    """Build a reviewed manuscript that is ready for continuity review only."""
    work = service.create_work({"title": f"Phase5 发布交接 {suffix}"})
    work_id = work["id"]
    result = service.save_brief(
        work_id,
        {
            "expected_version": work["version"],
            "idea": "老师在夜间温室核对一条被改写的门禁记录。",
            "mode": "bond_short",
            "characters": ["老师"],
        },
    )
    result = service.generate_blueprint(
        work_id, {"expected_version": result["work"]["version"]}
    )
    chapter_id = result["work"]["chapters"][0]["id"]
    result = service.create_scene(
        work_id,
        chapter_id,
        {
            "expected_version": result["work"]["version"],
            "title": "温室门禁",
            "location": "格黑娜旧温室",
            "goal": "确认门禁记录改变的时间与影响",
        },
    )
    scene_id = result["scene_id"]
    result = service.generate_scene_candidate(
        work_id, scene_id, {"expected_version": result["work"]["version"]}
    )
    manuscript = "\n".join(
        [
            "旁白: 作者已经安排好了这一幕，门禁灯在空旷温室里亮起。",
            "旁白: 玻璃上的雨水把室内外切成两层，旧记录仍停在昨夜。",
            "旁白: 温度计没有异常，只有访问时间被向后挪了三分钟。",
            "旁白: 老师把纸页压在桌角，没有替任何人先下结论。",
            "旁白: 远处的灌溉声停下，新的脚步却没有立刻出现。",
            "旁白: " + "门禁指示灯沿着潮湿的玻璃投下一道很长的光。" * 12,
            "老师: 先看记录。",
            "老师: 再核时间。",
            "老师: 保留原件。",
            "老师: 不先推断。",
            "老师: 等下一条证据。",
        ]
    ) + "\n"
    result = service.accept_proposal(
        work_id,
        result["proposal_id"],
        {"expected_version": result["work"]["version"], "text": manuscript},
    )
    result = service.review_scene(
        work_id, scene_id, {"expected_version": result["work"]["version"]}
    )
    finding_counts = {"blocking": 0, "warning": 0, "info": 0}
    for finding in result["findings"]:
        finding_counts[finding["severity"]] += 1
    assert finding_counts == {"blocking": 1, "warning": 2, "info": 1}

    blocking = next(
        finding for finding in result["findings"] if finding["severity"] == "blocking"
    )
    result = service.resolve_review_finding(
        work_id,
        blocking["id"],
        {
            "expected_version": result["work"]["version"],
            "note": "验收夹具已确认该元叙事项不进入最终发布阻塞。",
        },
    )
    result = service.skip_scene_memory_maintenance(
        work_id,
        scene_id,
        {
            "expected_version": result["work"]["version"],
            "note": "本场只用于发布门禁验收，不沉淀新的长期事实。",
        },
    )
    assert result["status"] == "skipped"
    return {
        "work_id": work_id,
        "scene_id": scene_id,
        "expected_open": {"blocking": 0, "warning": 2, "info": 1},
        "expected_resolved": 1,
    }


def collect_page_metrics(page: Page) -> dict:
    return page.evaluate(
        """() => ({
          viewport: {width: innerWidth, height: innerHeight},
          overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          activeGlobalNav: [...document.querySelectorAll('.primary-nav [data-section].active')]
            .map(element => element.dataset.section),
          findingRows: {
            blocking: document.querySelectorAll('.release-finding-row.blocking').length,
            warning: document.querySelectorAll('.release-finding-row.warning').length,
            info: document.querySelectorAll('.release-finding-row.info').length,
          },
        })"""
    )


def abbreviated_digest(value: str) -> str:
    digest = value.removeprefix("sha256:")
    return f"{digest[:12]}...{digest[-8:]}"


def release_source_summary(summary_text: str, artifact_text: str, manifest: dict) -> dict:
    """Assert that the release card visibly identifies both immutable sources."""
    ba_digest = manifest["ba_writing_source_digest"]
    source_digest = manifest["source_set_digest"]
    ba_label_visible = "BA Skill" in summary_text
    source_label_visible = "来源集" in summary_text
    ba_digest_visible = abbreviated_digest(ba_digest) in summary_text
    source_digest_visible = abbreviated_digest(source_digest) in summary_text

    assert "Hash" in artifact_text
    assert ba_label_visible and ba_digest_visible
    assert source_label_visible and source_digest_visible
    return {
        "ba_label_visible": ba_label_visible,
        "ba_digest_visible": ba_digest_visible,
        "source_label_visible": source_label_visible,
        "source_digest_visible": source_digest_visible,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    web_root = PROJECT_ROOT / "web"

    results: list[dict] = []
    with tempfile.TemporaryDirectory(
        prefix="halocue-phase5-", dir=args.output, ignore_cleanup_errors=True
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
                        fixture = build_fixture(service, f"{width}x{height}")
                        work_id = fixture["work_id"]
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
                        url = (
                            f"http://127.0.0.1:{server.server_port}/?section=writing"
                            f"&work_id={work_id}&stage=release"
                        )
                        response = page.goto(url, wait_until="domcontentloaded")
                        if response is None or not response.ok:
                            raise AssertionError(f"release workbench navigation failed: {url}")
                        page.locator("body:not(.app-loading)").wait_for(timeout=20_000)
                        findings_surface = page.locator(".release-findings-surface")
                        findings_surface.wait_for(timeout=20_000)
                        page.wait_for_timeout(250)

                        continuity_button = page.locator(
                            '[data-action="review-continuity"]'
                        )
                        release_review_button = page.locator(
                            '[data-action="review-release"]'
                        )
                        freeze_button = page.locator('[data-action="freeze-release"]')
                        assert continuity_button.is_enabled()
                        assert release_review_button.is_disabled()
                        assert freeze_button.is_disabled()
                        assert service.get_work(work_id)["releases"] == []

                        counts_text = page.locator(".release-finding-counts").inner_text()
                        assert "0 阻塞" in counts_text
                        assert "2 建议" in counts_text
                        assert "1 提示" in counts_text
                        assert "1 已处理" in counts_text
                        metrics_before = collect_page_metrics(page)
                        assert metrics_before["viewport"] == {
                            "width": width,
                            "height": height,
                        }
                        assert metrics_before["overflowX"] == 0
                        assert metrics_before["activeGlobalNav"] == ["writing"]
                        assert metrics_before["findingRows"] == fixture["expected_open"]

                        findings_surface.scroll_into_view_if_needed()
                        page.wait_for_timeout(120)
                        findings_screenshot = (
                            args.output
                            / f"phase5-finding-layers-{width}x{height}.png"
                        )
                        page.screenshot(path=findings_screenshot, full_page=False)

                        continuity_button.click()
                        try:
                            page.locator(".release-review-step.is-complete").wait_for(
                                timeout=30_000
                            )
                        except Exception:
                            debug_work = service.get_work(work_id)
                            debug = {
                                "body": page.locator("body").inner_text(),
                                "frontend": page.evaluate(
                                    """() => {
                                      const gate=(state.work?.gates||[]).find(item=>item.kind==='continuity.review');
                                      const sourceIds=scenes().map(scene=>scene.current_revision_id).filter(Boolean);
                                      const dependencyRefs=(state.work?.artifacts||[])
                                        .filter(item=>['brief','story_blueprint','work_canon','world_bible','character_card'].includes(item.kind)&&item.current_revision_id)
                                        .map(item=>({kind:item.kind,scope_type:item.scope_type,scope_id:item.scope_id,revision_id:item.current_revision_id,content_hash:item.current_revision?.content_hash}))
                                        .sort((left,right)=>`${left.kind}:${left.scope_id}`.localeCompare(`${right.kind}:${right.scope_id}`));
                                      const configuredDigest=String(state.capabilities?.ba_writing_skill?.source_digest||'');
                                      return {sourceIds,dependencyRefs,activeWritingPack:state.work?.active_writing_pack_version,configuredDigest,gate:gate?.snapshot};
                                    }"""
                                ),
                                "gates": debug_work["gates"],
                                "agent_runs": debug_work["agent_runs"][-3:],
                                "writing_runs": debug_work.get("writing_runs", [])[-3:],
                            }
                            (args.output / "phase5-debug.json").write_text(
                                json.dumps(debug, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8",
                            )
                            page.screenshot(
                                path=args.output / "phase5-debug.png", full_page=False
                            )
                            raise
                        release_review_button = page.locator(
                            '[data-action="review-release"]'
                        )
                        freeze_button = page.locator('[data-action="freeze-release"]')
                        assert release_review_button.is_enabled()
                        assert freeze_button.is_disabled()
                        continuity_state = service.get_work(work_id)
                        assert next(
                            gate
                            for gate in continuity_state["gates"]
                            if gate["kind"] == "continuity.review"
                        )["status"] == "passed"
                        assert not any(
                            gate["kind"] == "release.review"
                            for gate in continuity_state["gates"]
                        )

                        release_review_button.click()
                        page.locator('[data-action="freeze-release"]:not([disabled])').wait_for(
                            timeout=30_000
                        )
                        page.locator('[data-action="freeze-release"]').click()
                        release_artifact = page.locator(
                            ".artifact", has_text="交给制作的定稿"
                        ).first
                        release_artifact.wait_for(timeout=20_000)

                        work_state = service.get_work(work_id)
                        release_row = work_state["releases"][0]
                        release = service.get_release(release_row["id"])
                        manifest = release["manifest"]
                        assert release["content_hash"] == manifest["content_hash"]
                        assert SHA256_PATTERN.fullmatch(release["content_hash"])
                        assert SHA256_PATTERN.fullmatch(
                            manifest["ba_writing_source_digest"]
                        )
                        assert SHA256_PATTERN.fullmatch(manifest["source_set_digest"])
                        assert manifest["source_set_digest"] == source_set_digest(manifest)
                        assert manifest["writing_pack_version"]
                        assert manifest["gate_snapshot_ids"]
                        assert len(manifest["gate_snapshot_ids"]) == 2
                        gates_by_id = {
                            gate["id"]: gate for gate in work_state["gates"]
                        }
                        gate_order = [
                            gates_by_id[gate_id]["kind"]
                            for gate_id in manifest["gate_snapshot_ids"]
                        ]
                        assert gate_order == ["continuity.review", "release.review"]

                        integrity_summary = release_artifact.locator(
                            ".release-integrity-summary.is-verified"
                        )
                        integrity_summary.wait_for(timeout=20_000)
                        integrity_summary.locator("summary").click()
                        integrity_summary.locator("details[open] dl").wait_for(
                            timeout=5_000
                        )
                        artifact_text = release_artifact.inner_text()
                        assert release["content_hash"] in artifact_text
                        source_summary = release_source_summary(
                            integrity_summary.inner_text(), artifact_text, manifest
                        )
                        metrics_after = collect_page_metrics(page)
                        assert metrics_after["overflowX"] == 0

                        release_artifact.scroll_into_view_if_needed()
                        page.locator("#toast.show").wait_for(
                            state="detached", timeout=7_000
                        )
                        page.wait_for_timeout(150)
                        screenshot = (
                            args.output
                            / f"phase5-release-handoff-{width}x{height}.png"
                        )
                        page.screenshot(path=screenshot, full_page=False)
                        assert not console_issues
                        results.append(
                            {
                                "viewport": f"{width}x{height}",
                                "finding_screenshot": findings_screenshot.name,
                                "screenshot": screenshot.name,
                                "metrics_before": metrics_before,
                                "metrics_after": metrics_after,
                                "finding_counts": {
                                    "open": fixture["expected_open"],
                                    "resolved": fixture["expected_resolved"],
                                },
                                "gate_order": [*gate_order, "release.freeze"],
                                "release_id": release["id"],
                                "content_hash": release["content_hash"],
                                "ba_writing_source_digest": manifest[
                                    "ba_writing_source_digest"
                                ],
                                "source_set_digest": manifest["source_set_digest"],
                                "source_summary": source_summary,
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

    report = {
        "fixture": "phase5-release-gates-and-handoff",
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
