from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mapping_page_prioritizes_one_action_and_defers_diagnostics():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    assert 'class="mapping-focus"' in html
    assert 'id="mappingList" class="mapping-list"' in html
    assert 'id="taskPreflightDetails"' in html
    assert 'id="aiPreflightDetails"' in html
    assert '<details class="mapping-support-panel' in html
    # Diagnostics remain available, but are not competing with the mapping task
    # in the initial viewport.
    assert html.index('class="mapping-focus"') < html.index('id="taskPreflightDetails"')
    assert html.index('id="taskPreflightDetails"') < html.index('id="aiPreflightDetails"')


def test_mapping_support_panels_are_compact_and_keyboard_discoverable():
    css = (ROOT / "ui" / "preflight.css").read_text(encoding="utf-8")
    assert ".mapping-focus{" in css
    assert ".mapping-support-panel>summary" in css
    assert ".mapping-support-panel[open]>summary::before" in css
    assert "可选，不影响当前流程" in (ROOT / "ui" / "index.html").read_text(encoding="utf-8")


def test_ai_preflight_restores_the_full_review_decision_chain():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "preflight.css").read_text(encoding="utf-8")

    # The AI review is a real decision surface, not only a hidden optional
    # hint: status, source recognition, cast decisions, scene direction and
    # unresolved choices must remain inspectable before proceeding.
    assert 'id="aiPreflightDetails"' in html
    assert 'class="ai-preflight-decision-surface"' in script
    assert 'class="ai-preflight-alert' in script
    assert 'class="ai-preflight-source-summary"' in script
    assert 'class="ai-preflight-cast-list"' in script
    assert 'class="ai-preflight-scene-list"' in script
    assert 'data-ai-preflight-action="confirm-mapping"' in script
    assert 'data-ai-preflight-action="review-scene"' in script
    assert '.ai-preflight-decision-surface' in styles
    assert '.ai-preflight-alert' in styles


def test_ai_preflight_exposes_mapping_evidence_and_scene_direction_state():
    script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "preflight.css").read_text(encoding="utf-8")

    # A speaker name alone cannot reveal a wrong costume or a narrator mapping.
    # Keep visual/resource evidence next to the decision in both mapping surfaces.
    assert 'class="ai-preflight-cast-identity"' in script
    assert "mappingPreview(mapping)" in script
    assert "服装未标注，需打开素材核对" in script
    assert "骨骼资源已登记" in script
    assert ".ai-preflight-cast-identity" in styles

    # Scene analysis and actual direction generation are separate steps. The UI
    # must name the current state and summarize real draft evidence, not imply
    # that a location/background suggestion is already a generated performance.
    assert "function sceneDirectionState" in script
    assert "待生成演出" in script
    assert "已有演出草稿" in script
    assert "沿用剧本演出" in script
    assert 'class="ai-preflight-scene-state' in script
    assert ".ai-preflight-scene-state" in styles


def test_mapping_continue_action_does_not_cover_support_panels():
    app_css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
    assert "#page-mapping .sticky-actions{position:static" in app_css


def test_background_facets_are_hidden_outside_background_asset_tab():
    embed_css = (ROOT.parent / "writing" / "web" / "production-embed.css").read_text(encoding="utf-8")
    embed_script = (ROOT.parent / "writing" / "web" / "production-embed.js").read_text(encoding="utf-8")
    assert ".embedded-background-groups[hidden] { display: none !important; }" in embed_css
    assert 'controls.hidden = !dialog?.open || kind !== "backgrounds";' in embed_script
    assert "function restoreAssetDialogContext" in embed_script
    assert 'sounds: { title: "音效素材", search: "搜索音效"' in embed_script
    assert 'cg: { title: "插图素材", search: "搜索插图"' in embed_script


def test_resource_previews_are_csp_safe_and_gated_by_catalog_metadata():
    production_html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    production_script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    embedded_script = (
        ROOT.parent / "writing" / "web" / "production-embed.js"
    ).read_text(encoding="utf-8")

    assert "style=" not in production_html
    assert "preview_available" in production_script
    assert "onerror=" not in production_script
    assert 'style="background-image' not in production_script
    assert "preview_available" in embedded_script
    assert 'style="background-image' not in embedded_script


def test_embedded_stage_switch_resets_scroll_and_mobile_toast_clears_content():
    production_script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    embed_styles = (
        ROOT.parent / "writing" / "web" / "production-embed.css"
    ).read_text(encoding="utf-8")

    # The embedded shell, rather than .workspace, owns scrolling on mobile.
    assert 'document.querySelector(".embedded-production-shell")?.scrollTo({ top: 0, behavior: "instant" })' in production_script
    assert 'embeddedShell?.classList.add("toast-visible")' in production_script
    # Toast feedback must not cover the mapping/support panels or pinned action.
    assert ".embedded-production-shell ~ .toast" in embed_styles
    assert "top: 119px" in embed_styles
    assert ".embedded-production-shell.toast-visible > .workspace > .page" in embed_styles


def test_mobile_review_drawer_suppresses_background_focus_and_restores_it():
    embed_script = (
        ROOT.parent / "writing" / "web" / "production-embed.js"
    ).read_text(encoding="utf-8")
    assert 'drawerAccessibilityState = [' in embed_script
    assert 'element.inert = true' in embed_script
    assert 'element.setAttribute("aria-hidden", "true")' in embed_script
    assert 'toast?.classList.remove("visible")' in embed_script
    assert 'drawerOpener?.focus({ preventScroll: true })' in embed_script


def test_embedded_production_keeps_low_frequency_controls_in_one_menu():
    embed_script = (
        ROOT.parent / "writing" / "web" / "production-embed.js"
    ).read_text(encoding="utf-8")
    embed_styles = (
        ROOT.parent / "writing" / "web" / "production-embed.css"
    ).read_text(encoding="utf-8")
    assert 'class="production-more-actions"' in embed_script
    assert 'data-production-proxy="openTasks"' in embed_script
    assert 'data-production-proxy="openSettings"' in embed_script
    assert 'assetButton.disabled = !hasRun;' in embed_script
    assert 'assetButton.setAttribute("aria-disabled", String(!hasRun));' in embed_script
    assert '.production-more-actions > div button' in embed_styles


def test_review_tools_keep_legacy_preview_hook_out_of_the_visible_menu():
    embed_script = (
        ROOT.parent / "writing" / "web" / "production-embed.js"
    ).read_text(encoding="utf-8")
    embed_styles = (
        ROOT.parent / "writing" / "web" / "production-embed.css"
    ).read_text(encoding="utf-8")
    assert 'legacyPreviewTrigger.hidden = true;' in embed_script
    assert 'review.append(legacyPreviewTrigger);' in embed_script
    assert 'toolList.append(legacyPreviewTrigger)' not in embed_script
    assert '.production-review-tools { position: relative; }' in embed_styles
    assert 'right: 0;' in embed_styles
    assert '@media (max-width: 760px)' in embed_styles
    assert '.embedded-production-shell .review-actions {\n    overflow: visible;\n  }' in embed_styles
    assert 'left: 0;' in embed_styles

    shell_styles = (ROOT.parent / "writing" / "web" / "production-embed.css").read_text(encoding="utf-8")
    assert '.app-shell.production-mode .primary-nav .nav-item[data-section="assets"]' in shell_styles
    assert '.app-shell.production-mode .primary-nav .nav-item[data-section="references"]' in shell_styles
    assert '.app-shell.production-mode .primary-nav .nav-item[data-section="tasks"]' in shell_styles


def test_task_and_asset_surfaces_hide_internal_identifiers_from_users():
    production_script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    embed_script = (
        ROOT.parent / "writing" / "web" / "production-embed.js"
    ).read_text(encoding="utf-8")
    embed_styles = (
        ROOT.parent / "writing" / "web" / "production-embed.css"
    ).read_text(encoding="utf-8")

    # IDs remain available in data attributes and API calls, but ordinary
    # task/resource labels must not expose job/run or catalog keys.
    assert 'const association = job.run_id ? "关联当前制作任务" : "后台任务";' in production_script
    assert '<small>${esc(job.job_id)}' not in production_script
    assert '${association}</small>' in production_script
    assert 'class="asset-technical-key" aria-hidden="true"' in production_script
    assert ".production-asset-workbench .asset-technical-key" in embed_styles
    assert 'controls.hidden = !dialog?.open || kind !== "backgrounds"' in embed_script


def test_production_overview_uses_user_language_for_run_and_revision_state():
    production_script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")

    assert '$("#runTitle").textContent = run ? run.project : "尚未建立制作任务";' in production_script
    assert '<small>${esc(run.run_id)}</small>' not in production_script
    assert '${state.currentDraft.draft_version} 版草稿' not in production_script
    assert '当前演出草稿 · ${cards.length} 张卡片 · ${pending} 张待审' in production_script
    assert '最近构建：${esc(run.last_build_id)}' not in production_script
    assert '写入后草稿版本：${esc(generation.draft_version || "-")}' not in production_script
    assert '结果来自 ${esc(latest.model?.name' not in production_script
    assert 'toast(`已打开 ${result.run.project}`)' not in production_script


def test_custom_asset_recognition_is_optional_and_never_claims_rendered_spine():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "previews.css").read_text(encoding="utf-8")

    assert 'accept=".png,.jpg,.jpeg,.wav,.zip"' in html
    assert 'id="recognizeAssetImport"' in html
    assert "expression_suggestions" in script
    assert "未渲染 Spine 动画" in script
    assert "已验证表情 ID" in script
    assert "rendered_animation_count" in script or "validated_face_ids" in script
    assert "renderSpinePreview" in script
    assert "render_spine_preview" in script
    assert "asset_spine_render_not_configured" in script
    assert "accept_recognition" in script
    assert "recognition_digest" in script
    assert ".import-kind { grid-template-columns: repeat(2, minmax(0, 1fr)); }" in styles


def test_asset_import_uses_user_language_for_file_and_character_identity():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "previews.css").read_text(encoding="utf-8")

    assert 'class="import-file-control"' in html
    assert 'id="assetImportFileName"' in html
    assert "角色 Identifier" not in html
    assert "角色标识" in html
    assert "Identifier 和显示名称" not in script
    assert '$("#assetImportFile").addEventListener("change"' in script
    assert ".import-file-control input" in styles


def test_spine_cli_setup_is_discoverable_and_keeps_rendering_optional():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "workspace-migration.css").read_text(encoding="utf-8")

    assert 'data-settings-pane="spine"' in html
    assert 'id="spineForm"' in html
    assert 'id="spineCliPath"' in html
    assert 'id="saveSpineCli"' in html
    assert 'id="clearSpineCli"' in html
    assert 'api("/settings/spine-cli")' in script
    assert 'body: JSON.stringify({ clear: true })' in script
    assert '先渲染编号表情' in html
    assert 'spine-settings-intro' in styles


def test_mobile_review_exposes_edit_current_card_without_opening_a_long_list():
    embedded_script = (
        ROOT.parent / "writing" / "web" / "production-embed.js"
    ).read_text(encoding="utf-8")
    embedded_styles = (
        ROOT.parent / "writing" / "web" / "production-embed.css"
    ).read_text(encoding="utf-8")
    assert 'data-production-edit-current' in embedded_script
    assert 'production-background-timeline-wrap' in embedded_script
    assert '.production-edit-toggle' in embedded_styles


def test_mobile_asset_import_keeps_context_when_kind_selection_scrolls_form():
    embedded_styles = (
        ROOT.parent / "writing" / "web" / "production-embed.css"
    ).read_text(encoding="utf-8")
    preview_styles = (ROOT / "ui" / "previews.css").read_text(encoding="utf-8")

    # Selecting the character kind reveals extra fields and can move the
    # scroll position. The title and compact three-step context must remain
    # available while the user continues through the form.
    assert "#assetImportDialog .asset-import-shell > header" in embedded_styles
    assert "position: sticky" in embedded_styles
    assert ".asset-import-shell .import-steps" in embedded_styles
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in preview_styles


def test_production_stage_state_words_are_semantic_only_and_visual_state_is_distinct():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT.parent / "writing" / "web" / "production-embed.css").read_text(encoding="utf-8")

    assert '<em data-stage-state aria-hidden="true">' in html
    assert 'item.dataset.stageState = visualState;' in script
    assert '.production-flow-strip .stage-list li[data-stage-state="current"]::before' in styles
    assert '.production-flow-strip .stage-list li[data-stage-state="done"]::before' in styles
    assert '.production-flow-strip .stage-list li[data-stage-state="locked"]::before' in styles


def test_production_embed_has_non_blank_loading_and_missing_run_boundaries():
    embed_script = (ROOT.parent / "writing" / "web" / "production-embed.js").read_text(encoding="utf-8")
    embed_styles = (ROOT.parent / "writing" / "web" / "production-embed.css").read_text(encoding="utf-8")
    integration_script = (ROOT.parent / "integrated" / "static" / "integration-shell.js").read_text(encoding="utf-8")

    assert "setProductionSurfaceState" in embed_script
    assert "production-embed-empty" in embed_script
    assert "production-embed-retry" in embed_script
    assert ".production-embed-empty" in embed_styles
    assert ".embedded-production-shell[hidden]" in embed_styles
    assert "display: none !important" in embed_styles
    assert "productionSurfaceReady" in integration_script
    assert "productionSurfaceBlank" in integration_script


def test_recent_run_list_failure_keeps_a_single_recoverable_action():
    production_script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    production_styles = (ROOT / "ui" / "preflight.css").read_text(encoding="utf-8")
    assert 'class="run-list-state run-list-error" role="alert"' in production_script
    assert 'class="text-button run-list-retry">重新读取任务</button>' in production_script
    assert 'retry.disabled = true;' in production_script
    assert ".run-list-error" in production_styles


def test_long_direction_jobs_have_recoverable_controls_and_refresh_restore():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")

    for control in ("pauseGeneration", "resumeGeneration", "cancelGeneration"):
        assert f'id="{control}"' in html
        assert f'$("#{control}").addEventListener("click"' in script
    assert "async function restoreSavedRun()" in script
    assert "await restoreSavedRun();" in script
    assert 'localStorage.getItem("halocue.currentRunId")' in script
    assert 'pollJob(job.job_id, job.label || "后台任务")' in script
    assert "for (let attempt = 0; attempt < 180" not in script


def test_api_timeout_and_job_polling_recover_from_transient_http_failures():
    script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")

    assert "const DEFAULT_API_TIMEOUT_MS = 30000;" in script
    assert "const JOB_POLL_TIMEOUT_MS = 15000;" in script
    assert "new AbortController()" in script
    assert 'failure.code = "request_timeout";' in script
    assert "new Set([408, 429, 500, 502, 503, 504])" in script
    assert "!TRANSIENT_JOB_POLL_STATUSES.has(error.status)" in script


def test_generation_and_compile_buttons_are_derived_from_current_state():
    script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")

    assert "function syncWorkflowControlStates()" in script
    assert 'button.dataset.busyDisabled = "true";' in script
    assert "dataset.locked" not in script
    assert "!!run.last_direction_generation_id" in script
    assert "if (state.currentRun.last_direction_generation_id)" in script
    assert 'compile.textContent = compiling ? "正在编译" : "编译 AA 工程";' in script


def test_job_surfaces_expose_progress_cost_and_failure_diagnostics():
    script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
    preview_styles = (ROOT / "ui" / "previews.css").read_text(encoding="utf-8")

    assert 'pausing: "正在暂停"' in script
    assert 'cancelling: "正在结束"' in script
    assert 'superseded: "旧结果已丢弃"' in script
    assert 'data-task-job-action="pause"' in script
    assert 'data-task-job-action="resume"' in script
    assert 'data-task-job-action="cancel"' in script
    assert "jobLogRows(job, metrics)" in script
    assert "cacheLabel(metrics)" in script
    assert "warmCacheLabel(metrics)" in script
    assert "failedCostLabel(metrics)" in script
    assert "unitCostLabel(metrics)" in script
    assert "promptOptimizationLabel(metrics)" in script
    assert 'record.outcome === "failed"' in script
    assert "job.error.traceback" in script
    assert ".task-progress-row" in styles
    assert ".task-log-rows" in styles
    assert ".dialog-header-actions > button { flex: 0 0 auto; white-space: nowrap; }" in preview_styles


def test_standalone_production_does_not_probe_the_missing_writing_api():
    script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")

    assert 'const IS_STANDALONE_PRODUCTION = location.port === "8892";' in script
    assert "if (IS_STANDALONE_PRODUCTION)" in script
    assert "当前处于独立 AA 制作模式" in script
