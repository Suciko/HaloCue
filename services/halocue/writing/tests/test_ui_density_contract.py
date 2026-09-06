from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def test_settings_are_grouped_and_model_configuration_is_progressively_disclosed():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "shell.css").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")

    assert html.count('class="settings-nav-group"') == 3
    assert "连接" in html
    assert "写作" in html
    assert "数据" in html
    assert 'id="modelConfigDetails"' in html
    assert 'data-model-config-toggle' in html
    assert 'class="model-technical-details"' in html
    assert "modelConfigDetails.open" in script
    assert "settings-nav-group" in css
    assert ".settings-nav {" in css
    assert "overflow-x: visible" in css


def test_settings_do_not_expose_provider_internals_in_the_primary_summary():
    html = (WEB / "index.html").read_text(encoding="utf-8")

    # Technical fields remain available when the user explicitly expands the
    # configuration, but the status summary must speak in user language.
    assert 'class="model-technical-details"' in html
    assert 'summary>技术连接详情</summary>' in html
    assert 'class="active-model-details-grid"' not in html
    assert "Fake Provider" not in html
    assert "DPAPI" not in html


def test_agent_confirmation_is_short_and_traps_background_focus():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "writing-workbench.css").read_text(encoding="utf-8")

    assert 'data-agent-confirm-summary' in html
    assert 'data-agent-confirm-original' in html
    assert 'data-agent-confirm-submit' in html
    assert "intentDialogAccessibility" in script
    assert "aria-hidden" in script
    assert "inert = true" in script
    assert "triggerToRestore.focus" in script
    assert ".agent-intent-confirm-dialog" in css
    assert "max-height" in css


def test_task_center_uses_user_language_and_a_single_recovery_route():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    start = script.index("function renderMobileTasks")
    end = script.index("function artifact", start)
    task_surface = script[start:end]

    assert "data-task-open-scope" in task_surface
    assert "state.surface='writing'" in script
    assert "已由后续运行恢复" in task_surface
    assert "任务位置" in task_surface
    assert "第 ${esc(entry.ordinal)} 次运行" in task_surface
    assert "Attempt ${entry.ordinal}" not in task_surface
    assert "esc(entry.provider)" not in task_surface
    assert "esc(item.error.code" not in task_surface
    assert "${esc(item.scope_type)} · ${esc(item.scope_id)}" not in task_surface


def test_mobile_production_review_has_a_nearby_edit_entry_and_compact_timeline():
    embed = (WEB / "production-embed.js").read_text(encoding="utf-8")
    css = (WEB / "production-embed.css").read_text(encoding="utf-8")

    assert 'data-production-edit-current' in embed
    assert 'className = "production-edit-toggle"' in embed
    assert 'className = "production-background-timeline-wrap"' in embed
    assert ".production-edit-toggle" in css
    assert ".production-background-timeline-wrap" in css
    assert "max-width: 800px" in css


def test_scene_review_keeps_long_decisions_scrollable_and_actions_reachable():
    css = (WEB / "writing-workbench.css").read_text(encoding="utf-8")

    # A candidate can contain many block changes. The choice list and full
    # context must stay bounded so the one primary decision remains reachable
    # on a phone instead of being pushed below several screens of content.
    assert ".writing-workbench-stage .scene-diff-choices" in css
    assert "max-height: min(34vh, 360px)" in css
    assert "overflow-y: auto" in css
    assert ".writing-workbench-stage .scene-inline-review .scene-context-lines" in css
    assert "max-height: min(54vh, 520px)" in css
    assert ".writing-workbench-stage .scene-inline-review .scene-diff-actions" in css
    assert "position: sticky" in css
    assert "scroll-padding-bottom: 156px" in css


def test_scene_review_collapses_repeated_full_context_until_requested():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    assert 'data-scene-full-context-toggle' in script
    assert 'class="scene-context-lines" hidden' in script
    assert "content.hidden=!content.hidden" in script
    assert "收起预览" in script


def test_mobile_section_navigation_closes_the_asset_overlay():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    handler = script.split("document.addEventListener('click',event=>{\n  const button=event.target.closest('button[data-mobile]');", 1)[1]
    handler = handler.split("document.addEventListener('click',event=>{\n  const summary=", 1)[0]
    assert "state.assetSurfaceOpen=false" in handler


def test_mobile_overflow_menu_sits_above_the_fixed_agent_composer():
    css = (WEB / "shell.css").read_text(encoding="utf-8")
    assert ".mobile-nav:has(.mobile-more-menu[open])" in css
    assert "z-index: 60" in css
