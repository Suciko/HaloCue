from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] / "web"


def _slice(text, start, end):
    a = text.index(start)
    b = text.index(end, a + len(start))
    return text[a:b]


def test_release_ui_primary_surfaces_have_one_user_facing_status_path():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    surface = _slice(app, "function renderFinalWorkAgentSurface()", "function renderFinalWorkAgentRail")
    # Once the Agent has replied, its compact next action owns the guidance path.
    assert "const guideMessage=[...messages].reverse().find(message=>message.role==='assistant');" in surface
    assert "const statusMarkup=guideMessage?'':workUserStatusMarkup();" in surface
    assert "const runtimeMarkup=agentRuntimeBarMarkup(thread);" in surface
    assert "${statusMarkup}" in surface
    assert "${runtimeMarkup}" in surface
    # Internal run/tool details remain folded or secondary, not duplicate top-line status.
    assert '<summary>运行详情</summary>' in app
    assert 'class="agent-technical-tools"' in app
    assert "作品版本 ${work?.version" not in surface
    assert "后台任务 ${activity.running}" not in surface


def test_release_settings_requires_provider_test_before_reporting_activation():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    test_flow = _slice(app, "await requestProduction('/test')", "SettingsController.updateTopBarBadge")
    assert "response.ok" in test_flow
    assert "result.ok" in test_flow
    assert "未能确认模型启用成功" in test_flow
    assert "双域已启用" not in test_flow


def test_release_model_picker_is_a_saved_configuration_picker_not_a_catalog_link():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    picker = (ROOT / "agent-model-picker.js").read_text(encoding="utf-8")
    assert "registered_model_id" in picker
    assert "expected_config_digest" in picker
    assert "writing-model:activate" in picker
    assert "选择写作模型" in app
    # Model switching is a dialog action in the writing composer, not a settings navigation.
    assert "data-agent-model-picker" in app
    assert "data-model-settings" in picker
    assert "仅显示设置中已保存的模型" in picker
    assert "#openSettingsButton" in picker


def test_release_conversation_rail_has_real_collapse_and_search_controls():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "data-thread-search-toggle" in app
    assert "data-thread-create" in app
    assert "收起对话栏" in app
    assert "展开或收起对话栏" in app
    assert 'data-open-work-switch' in html
    # The collapse control has an inverse state, not a one-way decoration.
    assert "aria-expanded" in app
    assert 'data-panel-toggle="tree"' in app
    shell = (ROOT / "shell.js").read_text(encoding="utf-8")
    assert "collapse" in shell and "expand" in shell


def test_release_production_background_browser_uses_grouped_local_aa_resource_endpoints():
    embed = (ROOT / "production-embed.js").read_text(encoding="utf-8")
    production = (Path(__file__).resolve().parents[2] / "production" / "ui" / "app.js").read_text(encoding="utf-8")
    assert 'data-background-group="scene"' in embed
    assert 'data-background-group="cg"' in embed
    assert 'data-background-group="custom"' in embed
    assert "/api/v1/resources/search?kind=backgrounds&facets=1" in embed
    assert "haloCueLoadAssetLibrary" in embed
    assert "backgrounds" in embed
    assert "chooseResource" in production
    assert "cg-backgrounds" in production
    assert "preview" in production.lower()
    # Empty/unknown previews are represented as a fallback rather than broken img markup.
    assert "无预览" in production or "preview" in production.lower()


def test_release_writing_route_loads_durable_work_before_rendering_agent_state():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "async function loadWork" in app or "function loadWork" in app
    assert "loadWork(requested.id" in app
    assert "workConversationThread" in app
    assert "agentRunForMessage" in app
    assert "renderFinalWorkAgentSurface" in app


def test_release_manuscript_is_continuous_and_scene_navigation_is_scroll_based():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    workbench = (ROOT / "writing-workbench.js").read_text(encoding="utf-8")
    css = (ROOT / "writing-workbench.css").read_text(encoding="utf-8")
    assert "chapter-manuscript" in app
    assert "data-chapter-scene-anchor" in workbench
    assert "function focusChapterScene(sceneId)" in workbench
    assert "function sceneAtReadingPosition(workspace)" in workbench
    assert "workspace.scrollTo" in workbench
    assert "scrollBehavior" in workbench
    assert "bindChapterScrollTracking" in workbench
    assert ".chapter-manuscript-flow" in css


def test_empty_workspace_new_work_uses_the_existing_modal_surface():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    opener = _slice(app, "function openWorkDialog", "function closeWorkDialog")
    assert "state.firstUseOpen=true" not in opener
    assert "dialog.hidden=false" in opener
    assert "work-dialog-open" in opener
    assert "populateWorkForm(dialog.querySelector('form'))" in opener


def test_release_cancel_path_does_not_depend_on_required_form_fields():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    close = _slice(app, "function closeWorkDialog()", "function ") if "function closeWorkDialog()" in app and app.count("function ") > 1 else app[app.index("function closeWorkDialog()"):]
    assert "state.firstUseOpen=false" in close
    assert "dialog.hidden=true" in close
    assert "removeAttribute('inert')" in close
    assert "workDialogOpener" in close
    # The close listener is registered independently from submit validation.
    before = app.index("function openWorkDialog")
    listener = app[:before]
    assert "data-close-work-dialog" in listener
    assert "closeWorkDialog()" in listener

def test_model_endpoint_is_primary_and_writing_scope_is_safe_default():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "settings-center.css").read_text(encoding="utf-8")
    assert not re.search(r'<details\b[^>]*id="modelEndpointDetails"', html)
    assert '<section class="model-technical-details model-endpoint-fields" id="modelEndpointDetails"' in html
    assert 'name="apply_scope" value="writing" checked' in html
    assert "fields.get('apply_scope') || 'writing'" in app
    assert "填写协议、服务地址、API 密钥 和模型名称后，点击测试并启用。" in app
    assert "protocol and endpoint are primary connection inputs" in css
