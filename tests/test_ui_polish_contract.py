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
    assert ".topbar-actions button{width:100%;min-width:0;min-height:44px" in css
    assert ".asset-filter,.asset-import-kind,.asset-import-history,.asset-import-local,.asset-import-inbox,.asset-task-retry{min-height:44px}" in css
    assert ".bgc{border:2px solid transparent;border-radius:8px;overflow:hidden;cursor:pointer;background:var(--bg);color:var(--fg)}" in css
    assert "@media(prefers-reduced-motion:reduce)" in css
    assert ".story-context-bar{\n  position:static;\n  top:auto;" in css
    assert css.count(".story-context-bar{position:static;top:auto;align-items:flex-start;flex-direction:column}") >= 2


def test_material_sort_and_recency_keep_stable_catalog_geometry():
    css = (HERE / "css" / "layout.css").read_text(encoding="utf-8")
    assert ".asset-sort-select" in css
    assert ".asset-workbench-recency" in css
    assert "grid-column:1/-1" in css
    assert "text-overflow:ellipsis" in css


def test_unified_import_dialog_has_contained_responsive_layout():
    css = (HERE / "css" / "layout.css").read_text(encoding="utf-8")
    assert ".asset-import-dialog{position:fixed" in css
    assert ".asset-import-dialog-shell{display:grid" in css
    assert ".asset-import-file-picker{display:grid" in css
    assert ".asset-import-history-root{min-height:" in css
    assert "@media(max-width:680px)" in css
    assert "@media(max-width:470px)" in css
    assert "@media(max-width:390px)" in css
    assert ".asset-import-dialog-shell{min-height:100dvh" in css


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


def test_preflight_is_the_only_cast_and_background_confirmation_surface():
    html = (HERE / "ui.html").read_text(encoding="utf-8")
    app = (HERE / "js" / "app.js").read_text(encoding="utf-8")
    assert html.count("<h3>角色映射</h3>") == 1
    assert 'id="s2"' not in html
    assert 'id="s3"' not in html
    assert "背景使用链确认" not in html
    assert 'id="backgroundPlanSummary"' not in html
    assert 'id="backgroundPickerPanel"' not in html
    assert '<span class="num">3</span>生成审查草稿' in html
    assert 'id="mBackgroundPicker"' in html
    assert 'data-action="import-generation-result"' in html
    assert "导入生成结果" in html
    assert 'class="row modal-heading generation-prompt-heading"' in html
    assert 'id="generationImportResult"' in html
    assert "<h3>素材引用</h3>" not in html
    assert "背景用 <b>@bg" not in html
    assert "<summary>可用指令</summary>" not in html
    assert "@bg" not in html
    assert "本场没有 @bg 指令" not in app
    assert "演出信息由系统根据已确认的规划生成" in html
