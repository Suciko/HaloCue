# -*- coding: utf-8 -*-
"""Small structural contracts for the single-story workbench visual system."""

from pathlib import Path


HERE = Path(__file__).resolve().parents[1]


def test_workbench_keeps_navigation_in_context_not_a_fixed_sidebar():
    html = (HERE / "ui.html").read_text(encoding="utf-8")
    assert 'class="topbar"' in html
    assert 'id="recentStories"' in html
    assert 'id="storyAssetStrip"' in html
    assert 'id="reviewPhase"' in html and 'review-layout is-hidden' in html
    assert "sidebar" not in html.lower()


def test_asset_polish_preserves_mobile_touch_targets_and_overflow_guards():
    css = (HERE / "css" / "layout.css").read_text(encoding="utf-8")
    assert ".asset-card-list,.asset-task-list" in css
    assert ".asset-preview-audio" in css
    assert ".asset-strip-empty" in css
    assert "overflow-wrap:anywhere" in css
    assert ".topbar-actions button{min-width:48px;min-height:44px" in css
    assert ".asset-filter,.asset-import-local,.asset-task-retry{min-height:44px}" in css
    assert "@media(prefers-reduced-motion:reduce)" in css
    assert ".story-context-bar{\n  position:static;\n  top:auto;" in css
    assert css.count(".story-context-bar{position:static;top:auto;align-items:flex-start;flex-direction:column}") >= 2


def test_aa_settings_rows_and_progress_have_stable_responsive_geometry():
    css = (HERE / "css" / "layout.css").read_text(encoding="utf-8")
    assert ".aa-status-row{display:grid;grid-template-columns:88px minmax(0,1fr)" in css
    assert ".aa-status-value{overflow-wrap:anywhere" in css
    assert ".aa-index-progress{height:" in css
    assert "#buildAAIndex{min-height:44px" in css
    assert ".aa-install-actions button{min-height:44px" in css
    assert "@media(max-width:640px)" in css
    assert ".aa-status-row{grid-template-columns:1fr" in css


def test_workflow_progressively_reveals_only_actionable_stages():
    html = (HERE / "ui.html").read_text(encoding="utf-8")
    css = (HERE / "css" / "layout.css").read_text(encoding="utf-8")
    assert 'id="workflowProgress"' in html
    assert 'id="reviewPhase"' in html and 'review-layout is-hidden' in html
    assert 'class="bar is-hidden"' in html
    assert ".step.off{display:none" in css
    assert ".review-layout.is-hidden,.bar.is-hidden{display:none}" in css


def test_asset_task_states_and_sources_remain_explicit_in_the_dom_contract():
    source = (HERE / "js" / "assets.js").read_text(encoding="utf-8")
    for state in ("validating", "waiting_for_aa", "failed", "interrupted", "available"):
        assert state in source
    assert "asset-task-status" in source
    assert "来源 ·" in source
