"""Run the release handoff UI against synthetic IO and real Chromium DOM events."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
CASES = [
    "pending_retry_complete_keeps_open_task",
    "failed_retry_is_actionable_and_duplicate_clicks_submit_once",
    "hanging_status_is_bounded_and_independent",
    "stale_status_after_rerender_or_work_switch_is_ignored",
    "retry_completion_cannot_switch_work",
    "rerender_during_retry_keeps_single_submission",
    "first_handoff_preserves_view_and_reports_pending_proof",
    "offline_unknown_and_invalid_proof_are_not_complete",
    "not_required_and_complete_do_not_offer_replay",
    "proof_does_not_remove_frozen_integrity_details",
    "detached_status_and_retry_failures_do_not_touch_new_view",
    "partial_replay_remains_pending_and_recoverable",
    "http_failure_and_hanging_json_are_bounded",
    "returning_to_work_during_retry_reads_its_own_status",
    "late_pre_handoff_status_cannot_erase_success",
    "invalid_replay_response_remains_actionable",
    "paper_card_renders_at_desktop_and_mobile_widths",
]


@pytest.fixture(scope="module")
def node_browser_runtime():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the release handoff DOM cases")
    playwright = pytest.importorskip("playwright.sync_api")
    # Reuse the installed Python Playwright package's bundled Node runtime API;
    # do not download browsers or add a production dependency for this harness.
    import playwright as package

    runtime = Path(package.__file__).parent / "driver" / "package"
    with playwright.sync_playwright() as p:
        executable = Path(p.chromium.executable_path)
        if not executable.exists():
            executable = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        if not executable.exists():
            pytest.skip("A local Chromium or Edge installation is required")
    return node, runtime, executable


@pytest.mark.parametrize("case", CASES)
def test_release_handoff_ui(case, node_browser_runtime):
    node, runtime, executable = node_browser_runtime
    result = subprocess.run(
        [
            node,
            str(HERE / "release_handoff_ui_cases.cjs"),
            case,
            str(HERE.parent / "web" / "app.js"),
            str(runtime),
            str(executable),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "case": case,
        "passed": True,
        "external_requests": 0,
        "real_dom": True,
    }
