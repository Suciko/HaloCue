(() => {
  const scrollBehavior = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth";
  "use strict";

  const state = {
    currentRun: null,
    currentDraft: null,
    currentJob: null,
    directionProfile: "standard",
    gates: null,
    capabilities: null,
    selectedCard: null,
    selectedSpeaker: null,
    mappingAliasTarget: null,
    teacherMappingContext: null,
    characterCatalog: [],
    currentStage: "source",
    filter: "all",
    model: null,
    resourcePicker: null,
    resourceItems: [],
    resourceOffset: 0,
    resourceTotal: 0,
    resourceHasMore: false,
    resourceLoading: false,
    sceneBackgroundTarget: null,
    backgroundPromptScene: null,
    cgBackgroundKey: null,
    insertAfterCardId: null,
    assetLibraryKind: "characters",
    assetLibraryOffset: 0,
    assetLibraryTotal: 0,
    assetLibraryItems: [],
    selectedAssetKey: null,
    assetUsage: {},
    reviewAssetsKey: "",
    reviewAssetsRequest: 0,
    assetImport: null,
    assetWorkbenchContext: "",
    taskPreflight: null,
    aiPreflight: null,
    characterCatalogRunId: null,
    performancePreview: null,
    performancePreviewKey: "",
    performancePreviewLoading: false,
    performancePreviewError: "",
    previewIndex: 0,
    previewCompleted: false,
    previewPlayTimer: null,
    installOptions: null,
    installCheckTimer: null,
    busy: false,
    sourceMode: "writing",
    sourceFileName: null,
    upstreamRelease: null,
    sourcePreflight: null,
    sourcePreflightSignature: "",
    sourcePreflightConfirmed: false,
    aaEnvironment: null,
    spineCli: null,
    jobActionPending: null,
  };
  const IS_STANDALONE_PRODUCTION = location.port === "8892";
  const API_ROOT = location.port === "8891"
    ? "http://127.0.0.1:8892/api/v1"
    : "/api/v1";
  const DEFAULT_API_TIMEOUT_MS = 30000;
  const JOB_POLL_TIMEOUT_MS = 15000;
  const TRANSIENT_JOB_POLL_STATUSES = new Set([408, 429, 500, 502, 503, 504]);

  let pendingConfirmation = null;
  let confirmationOpener = null;
  let resourcePageObserver = null;
  let resourceSearchTimer = null;
  let resourceSearchController = null;
  let busyDepth = 0;
  const jobPolls = new Map();

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const esc = (value) => String(value ?? "").replace(/[&<>\"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '\"': "&quot;"
  }[char]));
  const text = (value, fallback = "") => String(value ?? fallback);
  const previewUrl = (kind, key) => state.currentRun
    ? `${API_ROOT}/production-runs/${encodeURIComponent(state.currentRun.run_id)}/resources/${kind}/${encodeURIComponent(key)}/preview`
    : `${API_ROOT}/resources/${kind}/${encodeURIComponent(key)}/preview`;
  // null means availability is unknown: let the task preview endpoint resolve it.
  const previewImage = (kind, key, label, className, available = false) => available !== false
    ? `<span class="resource-thumb media-frame"><img class="${className}" src="${previewUrl(kind, key)}" alt="" loading="lazy" decoding="async"><span class="preview-placeholder" aria-hidden="true">预览</span></span>`
    : '<span class="resource-thumb media-frame preview-unavailable"><span class="preview-placeholder is-visible" aria-hidden="true">无预览</span></span>';

  function hasChinese(value) {
    return /[\u3400-\u9fff]/.test(String(value || ""));
  }

  function sceneTitleLabel(title) {
    return String(title || "").split("·")[0].trim();
  }

  function resourceDisplayName(item, context = {}) {
    const values = [
      item?.name_zh_cn,
      item?.display_name_zh_cn,
      item?.label_cn,
      item?.place_cn,
      item?.label,
      item?.place,
      item?.display_name,
    ];
    const chinese = values.find(hasChinese);
    if (chinese) return String(chinese);
    if (context.kind === "backgrounds" && item?.key === context.currentBackgroundKey && hasChinese(context.currentBackgroundLabel)) {
      return context.currentBackgroundLabel;
    }
    return String(item?.name || item?.key || "未命名素材");
  }

  // A background directive is an assignment, not proof of readable local media.
  // Keep availability in this rendered view; late image events cannot mutate a draft.
  function sceneBackgroundAvailability(key) {
    const status = !key ? "unassigned" : key === "BG_Black" ? "builtin" : "pending";
    const labels = { unassigned: "未指定背景", builtin: "内置黑屏 · 无需图片", pending: "已指定 · 本机预览待核验" };
    return `<p class="scene-background-availability" data-background-availability="${status}" role="status">${labels[status]}</p>`;
  }

  function updateSceneBackgroundSummary(root) {
    if (!root) return;
    const status = root.id === "mappingScenePlan" ? $("#mappingSceneStatus") : $("#scenePlanStatus");
    if (!status) return;
    const values = [...root.querySelectorAll("[data-background-availability]")].map(node => node.dataset.backgroundAvailability);
    const count = value => values.filter(item => item === value).length;
    const parts = [`${values.length} 个场景`, `已指定 ${values.length - count("unassigned")}/${values.length}`];
    if (count("unassigned")) parts.push(`${count("unassigned")} 项未指定`);
    if (count("unavailable")) parts.push(`${count("unavailable")} 项预览不可用`);
    if (count("pending")) parts.push(`${count("pending")} 项预览待核验`);
    if (count("available")) parts.push(`${count("available")} 项预览可用`);
    if (count("builtin")) parts.push(`${count("builtin")} 项内置黑屏`);
    if (root.dataset.materialRequests !== "0" && root.dataset.materialRequests) parts.push(`${root.dataset.materialRequests} 项素材请求`);
    status.textContent = parts.join(" · ");
  }

  function settleSceneBackgroundPreview(image, available) {
    const row = image.closest(".scene-plan-card, .mapping-scene-card");
    const label = row?.querySelector("[data-background-availability]");
    if (!label || !image.isConnected) return;
    label.dataset.backgroundAvailability = available ? "available" : "unavailable";
    label.textContent = available ? "已指定 · 本机预览可显示" : "已指定 · 本机预览不可用，请检查资源";
    row.classList.toggle("ready", available);
    row.classList.toggle("asset-preview-unavailable", !available);
    updateSceneBackgroundSummary(row.closest("#scenePlan, #mappingScenePlan"));
  }

  function askConfirmation({ title, body, confirmLabel = "确认", danger = false }) {
    const dialog = $("#actionConfirmDialog");
    if (!dialog) return Promise.resolve(false);
    if (pendingConfirmation) pendingConfirmation(false);
    $("#actionConfirmTitle").textContent = title || "确认继续？";
    $("#actionConfirmBody").textContent = body || "这项操作会修改当前制作任务。";
    const accept = $("#actionConfirmAccept");
    accept.textContent = confirmLabel;
    accept.className = danger ? "primary danger-button" : "primary";
    confirmationOpener = document.activeElement;
    return new Promise((resolve) => {
      pendingConfirmation = resolve;
      dialog.showModal();
      requestAnimationFrame(() => accept.focus());
    });
  }

  function savedLayoutMode() {
    try {
      const mode = localStorage.getItem("halocue.layoutMode");
      return ["pure_ai", "ai", "rules"].includes(mode) ? mode : "ai";
    } catch (_) {
      return "ai";
    }
  }

  function selectedLayoutMode() {
    const mode = $('input[name="layoutMode"]:checked')?.value;
    return ["pure_ai", "ai", "rules"].includes(mode) ? mode : "ai";
  }

  function setLayoutMode(value) {
    const mode = ["pure_ai", "ai", "rules"].includes(value) ? value : "ai";
    const input = $(`input[name="layoutMode"][value="${mode}"]`);
    if (input) input.checked = true;
  }

  function rememberLayoutMode() {
    try { localStorage.setItem("halocue.layoutMode", selectedLayoutMode()); } catch (_) { /* unavailable */ }
  }

  function savedRunId() {
    try { return localStorage.getItem("halocue.currentRunId") || ""; } catch (_) { return ""; }
  }

  function rememberRun(run) {
    try {
      if (run?.run_id) localStorage.setItem("halocue.currentRunId", run.run_id);
      else localStorage.removeItem("halocue.currentRunId");
    } catch (_) { /* unavailable */ }
  }

  function toast(message, tone = "normal") {
    const element = $("#toast");
    const embeddedShell = document.querySelector(".embedded-production-shell");
    element.textContent = message;
    element.dataset.tone = tone;
    element.classList.add("visible");
    embeddedShell?.classList.add("toast-visible");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => {
      element.classList.remove("visible");
      embeddedShell?.classList.remove("toast-visible");
    }, 3600);
  }

  async function api(path, options = {}) {
    const {
      timeoutMs = DEFAULT_API_TIMEOUT_MS,
      signal: upstreamSignal,
      headers: optionHeaders,
      ...fetchOptions
    } = options;
    const controller = new AbortController();
    let timedOut = false;
    const abortFromUpstream = () => controller.abort(upstreamSignal?.reason);
    if (upstreamSignal) upstreamSignal.addEventListener("abort", abortFromUpstream, { once: true });
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, Math.max(1, Number(timeoutMs) || DEFAULT_API_TIMEOUT_MS));
    try {
      const response = await fetch(`${API_ROOT}${path}`, {
        headers: { "Content-Type": "application/json", ...(optionHeaders || {}) },
        ...fetchOptions,
        signal: controller.signal,
      });
      let payload = {};
      try { payload = await response.json(); } catch (_) { /* empty response */ }
      if (!response.ok || payload.ok === false) {
        const error = payload.error || { code: "request_failed", message: `请求失败（${response.status}）`, details: {} };
        const failure = new Error(error.message || error.code);
        failure.code = error.code;
        failure.details = error.details || {};
        failure.status = response.status;
        throw failure;
      }
      return payload;
    } catch (error) {
      if (timedOut && error?.name === "AbortError") {
        const failure = new Error("请求等待超时，后台任务可能仍在运行，正在重新获取状态。");
        failure.code = "request_timeout";
        failure.status = 0;
        throw failure;
      }
      throw error;
    } finally {
      clearTimeout(timer);
      if (upstreamSignal) upstreamSignal.removeEventListener("abort", abortFromUpstream);
    }
  }

  function setBusy(value) {
    busyDepth = value ? busyDepth + 1 : Math.max(0, busyDepth - 1);
    const busy = busyDepth > 0;
    if (busy === state.busy) return;
    state.busy = busy;
    document.body.classList.toggle("is-busy", busy);
    syncWorkflowControlStates();
    if (busy) {
      $$('button:not([disabled])').forEach((button) => {
        button.dataset.busyDisabled = "true";
        button.disabled = true;
      });
      return;
    }
    $$('button[data-busy-disabled="true"]').forEach((button) => {
      delete button.dataset.busyDisabled;
      button.disabled = false;
    });
    syncWorkflowControlStates();
    renderGenerationJob();
  }

  function handleError(error) {
    if (error.code === "revision_conflict") {
      toast("草稿已经被其他操作更新，已刷新当前版本。", "warning");
      return refreshCurrentRun();
    }
    toast(error.message || "操作失败，请稍后重试。", "danger");
    return Promise.resolve();
  }

  async function refreshCapabilities() {
    const [health, caps] = await Promise.all([api("/health"), api("/capabilities")]);
    state.capabilities = caps.capabilities;
    const profiles = state.capabilities.direction_profiles;
    const allowedProfiles = new Set((profiles?.items || [{ id: "standard" }]).map(item => item.id));
    const defaultProfile = profiles?.default_new_project_ui || "standard";
    $$('#sourceDirectionProfile option, #directionProfile option').forEach((option) => {
      option.disabled = !allowedProfiles.has(option.value);
      if (option.parentElement.id === "sourceDirectionProfile") {
        option.defaultSelected = option.value === defaultProfile;
      }
    });
    if (!allowedProfiles.has($("#sourceDirectionProfile").value)) {
      $("#sourceDirectionProfile").value = defaultProfile;
    }
    const status = $("#serviceState");
    status.textContent = `${health.service} · ${health.version}`;
    status.classList.add("online");
    const ai = state.capabilities.generation_modes?.ai_direction;
    const radio = document.querySelector('input[value="ai_direction"]');
    const aiChoice = $("#aiModeChoice");
    if (radio) radio.disabled = false;
    aiChoice?.classList.toggle("needs-setup", ai?.state !== "available");
    if (aiChoice) aiChoice.dataset.availability = ai?.state || "not_configured";
    $("#aiModeState").textContent = ai?.state === "available"
      ? `已就绪 · ${ai.model || "已配置模型"}` : "需要先配置演出模型";
    updateGenerationModeUi();
    syncProfilePickers();
    renderAiPreflight();
  }

  function showStage(stage, { force = false } = {}) {
    const access = stageAccess(stage);
    if (!force && !access.allowed) {
      toast(access.reason, "warning");
      return;
    }
    state.currentStage = stage;
    $$(".stage-list li").forEach((item) => {
      const active = item.dataset.stage === stage;
      item.classList.toggle("active", active);
      item.setAttribute("aria-current", active ? "step" : "false");
      item.setAttribute("aria-label", `${item.querySelector("strong")?.textContent || "步骤"}${active ? "，当前步骤" : "，点击进入"}`);
    });
    $$(".page").forEach((page) => page.classList.toggle("active", page.id === `page-${stage}`));
    const labels = { source: "选择剧本", mapping: "角色与素材", generation: "场景制作计划", review: "审查与安装" };
    $("#breadcrumb").textContent = `制作 / ${labels[stage]}`;
    $("#pageTitle").textContent = stage === "source" ? "把已有剧本转换为 AA 工程" : labels[stage];
    document.querySelector(".workspace").scrollTo({ top: 0, behavior: "instant" });
    // The embedded workbench scrolls its shell rather than .workspace. Reset
    // that container after replacing the active page so the sticky step strip
    // cannot cover the new page heading when switching from a long source page.
    document.querySelector(".embedded-production-shell")?.scrollTo({ top: 0, behavior: "instant" });
    if (stage === "mapping") renderMapping();
    if (stage === "generation") renderGeneration();
    if (stage === "review") { renderReview(); renderInstallPanel(); }
    renderWorkflowState();
  }

  const stageOrder = ["source", "mapping", "generation", "review"];

  function workflowSnapshot() {
    const run = state.currentRun;
    const draft = state.currentDraft;
    const speakers = run?.source_summary?.speakers || draft?.cast?.detected_speakers || [];
    const missingMappings = run
      ? speakers.filter((speaker) => mappingFor(speaker).kind === "unset").length
      : 0;
    const mappingDone = !!run && missingMappings === 0;
    const directionRequired = run?.source_summary?.generation_mode === "ai_direction";
    const generationDone = mappingDone && !!draft && (
      !directionRequired || !!run.last_direction_generation_id
    );
    const reviewDone = run?.state === "installed";
    const done = {
      source: !!run,
      mapping: mappingDone,
      generation: generationDone,
      review: reviewDone,
    };
    let recommendedStage = "source";
    let recommendedLabel = "选择剧本并建立任务";
    if (run && missingMappings) {
      recommendedStage = "mapping";
      recommendedLabel = `处理 ${missingMappings} 位未映射说话者`;
    } else if (run && !generationDone) {
      recommendedStage = "generation";
      recommendedLabel = run.state === "generating_direction"
        ? "查看演出生成状态"
        : run.state === "direction_paused"
          ? "继续未完成的演出生成"
          : ["direction_failed", "direction_interrupted"].includes(run.state)
            ? "查看错误并继续生成"
            : run.state === "direction_cancelled"
              ? "继续或重新生成演出"
              : "完成场景制作计划";
    } else if (run && !reviewDone) {
      recommendedStage = "review";
      recommendedLabel = state.gates?.compile?.passed ? "编译并安装 AA 工程" : "继续逐卡审查";
    } else if (reviewDone) {
      recommendedStage = "review";
      recommendedLabel = "查看已安装工程";
    }
    return {
      done,
      completed: Object.values(done).filter(Boolean).length,
      missingMappings,
      recommendedStage,
      recommendedLabel,
    };
  }

  function stageAccess(stage) {
    if (stage === "source") return { allowed: true, reason: "" };
    if (!state.currentRun) return { allowed: false, reason: "先建立一个制作任务。" };
    const snapshot = workflowSnapshot();
    if (["generation", "review"].includes(stage) && snapshot.missingMappings > 0) {
      return { allowed: false, reason: `请先完成 ${snapshot.missingMappings} 位说话者的角色映射。` };
    }
    if (stage === "review" && !snapshot.done.generation) {
      return {
        allowed: false,
        reason: state.currentRun.state === "generating_direction"
          ? "演出仍在生成；请先等待完成，或在生成页暂停/结束任务。"
          : "演出生成尚未完成，请先在生成页继续或重新开始。",
      };
    }
    if (stage === "review" && !state.currentDraft) {
      return { allowed: false, reason: "草稿还没有载入，请先完成场景制作计划。" };
    }
    return { allowed: true, reason: "" };
  }

  function renderWorkflowState() {
    const snapshot = workflowSnapshot();
    $("#flowProgressLabel").textContent = `${snapshot.completed} / 4`;
    $("#flowProgressBar").style.width = `${snapshot.completed * 25}%`;
    $$(".stage-list li").forEach((item) => {
      const stage = item.dataset.stage;
      const active = stage === state.currentStage;
      const done = snapshot.done[stage];
      const needsMapping = !!state.currentRun
        && snapshot.missingMappings > 0
        && ["generation", "review"].includes(stage);
      item.classList.toggle("done", done);
      item.classList.toggle("blocked", needsMapping);
      item.classList.toggle("locked", !state.currentRun && stage !== "source");
      const access = stageAccess(stage);
      item.setAttribute("aria-disabled", access.allowed ? "false" : "true");
      item.tabIndex = access.allowed ? 0 : -1;
      const label = active ? "当前" : done ? "已完成" : needsMapping ? "需先映射" : state.currentRun || stage === "source" ? "可进入" : "未开始";
      const visualState = active ? "current" : done ? "done" : !access.allowed ? "locked" : "available";
      item.dataset.stageState = visualState;
      item.querySelector("[data-stage-state]").textContent = label;
      item.setAttribute("aria-label", `${item.querySelector("strong")?.textContent || "步骤"}，${label}${active ? "" : "，点击进入"}`);
    });
  }

  function upstreamReleaseFor(run) {
    const origin = run?.source_summary?.upstream_release;
    return origin && origin.kind === "halocue_writing" ? origin : null;
  }

  function writingReleaseLabel(origin) {
    return origin?.display_version ? `写作定稿 ${origin.display_version}` : "写作定稿";
  }

  function updateShell() {
    const run = state.currentRun;
    const origin = upstreamReleaseFor(run);
    $(".app-shell")?.dispatchEvent(new CustomEvent("halocue:production-context", {
      bubbles: true, composed: true, detail: {
        runId: run?.run_id || "", title: run?.project || "选择制作任务",
        workId: origin?.work_id || "", releaseId: origin?.release_id || "",
      },
    }));
    $("#runTitle").textContent = run ? run.project : "尚未建立制作任务";
    const labels = {
      waiting_for_review: "等待审查", ready_to_compile: "待编译检查", compiling: "正在编译",
      compiled: "编译完成", installed: "已安装", generating_direction: "正在生成演出",
      direction_failed: "演出生成失败", direction_paused: "演出已暂停",
      direction_cancelled: "演出已结束", direction_interrupted: "演出生成中断",
      compile_failed: "编译失败", compile_interrupted: "编译中断"
    };
    $("#sideState").textContent = run ? (labels[run.state] || run.state) : "等待剧本";
    $("#sideDetail").textContent = run
      ? `${run.source_summary?.line_count || 0} 行 · ${run.source_summary?.card_count || 0} 张卡片 · ${run.source_summary?.speakers?.length || 0} 位说话者`
      : "输入已有剧本即可开始，不需要先进入写作系统。";
    const sideOrigin = $("#sideOrigin");
    sideOrigin.hidden = !run;
    sideOrigin.textContent = origin
      ? `来源：${writingReleaseLabel(origin)}`
      : run ? "来源：直接导入剧本" : "";
    sideOrigin.classList.toggle("from-writing", !!origin);
    $("#openRunOverview").disabled = !run;
    renderWorkflowState();
  }

  const blockerLabels = {
    draft_missing: "演出草稿尚未建立",
    blocking_diagnostics: "草稿仍有阻断问题",
    pending_review: "仍有卡片等待审查",
    unresolved_issues: "草稿仍有未解决警告",
    compile_not_configured: "编译环境尚未配置",
    resource_index_not_configured: "本任务缺少冻结的 AA 资源索引",
    resource_index_incomplete: "本任务冻结的 AA 资源索引不完整",
    build_missing: "尚未生成可安装构建",
    build_stale: "当前构建来自旧草稿",
    aa_workspace_not_configured: "AA 工作区尚未配置",
  };

  function renderRunOverview() {
    const run = state.currentRun;
    const draft = state.currentDraft;
    const body = $("#runOverviewBody");
    if (!run) {
      body.innerHTML = '<p class="empty">尚未建立制作任务。</p>';
      $("#runOverviewContinue").disabled = true;
      return;
    }
    const snapshot = workflowSnapshot();
    const counts = draft?.counts || {};
    const origin = upstreamReleaseFor(run);
    const mode = run.source_summary?.generation_mode === "ai_direction" ? "AI 安排演出" : "仅转换格式";
    const blockers = run.state === "installed"
      ? []
      : run.last_build_id
        ? state.gates?.install?.blockers || []
        : state.gates?.compile?.blockers || [];
    const statusLabels = {
      waiting_for_review: "等待审查",
      ready_to_compile: "待编译检查",
      compiling: "正在编译",
      compiled: "等待安装",
      installed: "已经安装",
      generating_direction: "正在生成演出",
      direction_failed: "演出生成失败",
      direction_paused: "演出已暂停",
      direction_cancelled: "演出已结束",
      direction_interrupted: "演出生成中断",
      compile_failed: "编译失败",
      compile_interrupted: "编译中断",
    };
    const sourceOrigin = origin
      ? `<section class="overview-origin from-writing" aria-label="写作端交接信息">
          <header><span>来源</span><b>来自写作工作台</b><em>已确认写作定稿</em></header>
          <dl><div><dt>定稿版本</dt><dd>${esc(origin.display_version || "已确认")}</dd></div></dl>
        </section>`
      : `<section class="overview-origin direct-import" aria-label="剧本来源">
          <header><span>来源</span><b>直接导入剧本</b><em>已从本地剧本建立任务</em></header>
        </section>`;
    body.innerHTML = `<section class="overview-title"><div><small>当前制作任务</small><h4>${esc(run.project)}</h4><p>${esc(mode)} · ${esc(statusLabels[run.state] || run.state)}</p></div><b>${snapshot.completed}/4</b></section>
      ${sourceOrigin}
      <section class="overview-metrics" aria-label="任务数据"><article><small>剧本文本</small><strong>${esc(run.source_summary?.line_count || 0)} 行</strong></article><article><small>演出草稿</small><strong>${esc(draft?.cards?.length || run.source_summary?.card_count || 0)} 张</strong></article><article><small>待审卡片</small><strong>${esc(counts.pending || 0)} 张</strong></article><article><small>阻断问题</small><strong>${esc(counts.blocking_errors || 0)} 项</strong></article></section>
      <ol class="overview-stage-list">${stageOrder.map((stage, index) => { const names = { source: "剧本已冻结", mapping: "角色映射", generation: "演出草稿", review: "审查与安装" }; const done = snapshot.done[stage]; const current = stage === state.currentStage; return `<li class="${done ? "done" : current ? "current" : ""}"><b>${done ? "完" : index + 1}</b><span><strong>${names[stage]}</strong><small>${done ? "已完成" : current ? "正在处理" : "尚未完成"}</small></span></li>`; }).join("")}</ol>
      <section class="overview-blockers ${blockers.length ? "has-blockers" : "ready"}"><small>${blockers.length ? "当前阻断" : "当前状态"}</small><strong>${blockers.length ? blockers.map((item) => blockerLabels[item] || item).join("；") : run.state === "installed" ? "工程已经安装到 AA" : "没有发现新的阻断项"}</strong>${run.last_installed_project ? `<p>已安装为 ${esc(run.last_installed_project)}</p>` : ""}</section>`;
    $("#runOverviewHint").textContent = `推荐：${snapshot.recommendedLabel}`;
    const action = $("#runOverviewContinue");
    action.disabled = false;
    action.dataset.stage = snapshot.recommendedStage;
    action.textContent = snapshot.recommendedLabel;
  }

  function openRunOverview() {
    if (!state.currentRun) return;
    renderRunOverview();
    const dialog = $("#runOverviewDialog");
    if (!dialog.open) dialog.showModal();
  }

  function adoptRunResult(result, { replaceJob = false } = {}) {
    const selectedId = state.selectedCard?.card_id;
    const previousRun = state.currentRun;
    state.currentRun = result.run || state.currentRun;
    if (previousRun?.run_id !== state.currentRun?.run_id
      || previousRun?.source_summary?.direction_profile !== state.currentRun?.source_summary?.direction_profile) {
      state.directionProfile = state.currentRun?.source_summary?.direction_profile === "conservative"
        ? "conservative" : "standard";
    }
    if (previousRun?.run_id !== state.currentRun?.run_id) state.draftDirectionProfile = null;
    if (Object.prototype.hasOwnProperty.call(result, "draft_direction_profile")) state.draftDirectionProfile = result.draft_direction_profile;
    if (Object.prototype.hasOwnProperty.call(result, "draft")) state.currentDraft = result.draft;
    if (Object.prototype.hasOwnProperty.call(result, "gates")) state.gates = result.gates;
    if (replaceJob || Object.prototype.hasOwnProperty.call(result, "active_job")) {
      state.currentJob = result.active_job || result.last_job || null;
    }
    if (state.currentJob?.kind === "direction_generation" && jobIsActive(state.currentJob)) {
      state.directionProfile = directionJobProfile();
    }
    state.selectedCard = state.currentDraft?.cards?.find((card) => card.card_id === selectedId) || null;
    if (previousRun?.run_id !== state.currentRun?.run_id) {
      state.taskPreflight = null; state.aiPreflight = null;
      state.characterCatalog = []; state.characterCatalogRunId = "";
    }
    rememberRun(state.currentRun);
    productionShell?.dispatchEvent(new CustomEvent("halocue:production-run-changed", {
      bubbles: true, composed: true,
      detail: { run: state.currentRun, draft: state.currentDraft, stage: currentRunOpeningStage() },
    }));
  }

  function trackActiveRunJob(result) {
    const job = result?.active_job;
    if (!job || ["succeeded", "failed", "interrupted", "paused", "cancelled", "superseded"].includes(job.state)) return;
    pollJob(job.job_id, job.label || "后台任务").catch(handleError);
  }

  function currentRunOpeningStage() {
    const snapshot = workflowSnapshot();
    if (snapshot.missingMappings) return "mapping";
    if (!snapshot.done.generation) return "generation";
    return "review";
  }

  async function restoreSavedRun() {
    const runId = savedRunId();
    if (!runId) return false;
    try {
      const result = await api(`/production-runs/${encodeURIComponent(runId)}`);
      adoptRunResult(result, { replaceJob: true });
      await loadTaskPreflight();
      updateShell();
      showStage(currentRunOpeningStage(), { force: true });
      trackActiveRunJob(result);
      return true;
    } catch (error) {
      if (error.code === "run_not_found" || error.status === 404) {
        rememberRun(null);
        return false;
      }
      throw error;
    }
  }

  async function refreshCurrentRun() {
    if (!state.currentRun?.run_id) return;
    const runId = state.currentRun.run_id;
    const ticket = runOpeningEpoch;
    const result = await api(`/production-runs/${encodeURIComponent(runId)}`);
    if (ticket !== runOpeningEpoch || state.currentRun?.run_id !== runId) return;
    adoptRunResult(result, { replaceJob: true });
    await loadTaskPreflight();
    if (ticket !== runOpeningEpoch || state.currentRun?.run_id !== runId) return;
    updateShell();
    renderMapping();
    renderGeneration();
    renderReview();
    renderInstallPanel();
    trackActiveRunJob(result);
  }

  async function loadRuns() {
    const list = $("#runList");
    const refresh = $("#reloadRuns");
    if (!list) return;
    const previousRefreshLabel = refresh?.textContent || "刷新";
    if (refresh) {
      refresh.disabled = true;
      refresh.textContent = "读取中...";
    }
    try {
      const result = await api("/production-runs");
      if (!result.items?.length) { list.innerHTML = '<p class="empty">暂无制作任务</p>'; return; }
      const stateLabels = { waiting_for_review: "等待审查", ready_to_compile: "待编译检查", compiling: "正在编译", compiled: "编译完成", installed: "已安装", generating_direction: "正在生成演出", direction_failed: "演出生成失败", direction_paused: "演出已暂停", direction_cancelled: "演出已结束", direction_interrupted: "演出生成中断", compile_failed: "编译失败", compile_interrupted: "编译中断" };
      list.innerHTML = result.items.slice(0, 8).map((run) => `<button class="run-row" data-run-id="${esc(run.run_id)}">
        <span><strong>${esc(run.project)}</strong><small>${esc(stateLabels[run.state] || "处理中")}</small></span><b>打开</b></button>`).join("");
      $$("[data-run-id]").forEach((button) => button.addEventListener("click", () => openRun(button.dataset.runId).catch(handleError)));
    } catch (error) {
      list.innerHTML = `<div class="run-list-state run-list-error" role="alert"><strong>最近任务读取失败</strong><p>${esc(error.message || "制作任务暂时无法读取，请重试。")}</p><button type="button" class="text-button run-list-retry">重新读取任务</button></div>`;
      list.querySelector(".run-list-retry")?.addEventListener("click", async (event) => {
        const retry = event.currentTarget;
        retry.disabled = true;
        retry.textContent = "正在读取...";
        await loadRuns();
      }, { once: true });
    } finally {
      if (refresh) {
        refresh.disabled = false;
        refresh.textContent = previousRefreshLabel;
      }
    }
  }

  let runOpeningEpoch = 0;
  async function openRun(runId) {
    const ticket = ++runOpeningEpoch;
    try {
      const result = await api(`/production-runs/${encodeURIComponent(runId)}`);
      if (ticket !== runOpeningEpoch) return false;
      adoptRunResult(result, { replaceJob: true });
      await loadTaskPreflight();
      if (ticket !== runOpeningEpoch) return false;
      updateShell();
      showStage(currentRunOpeningStage(), { force: true });
      trackActiveRunJob(result);
      return true;
    } catch (error) {
      if (ticket !== runOpeningEpoch) return false;
      throw error;
    }
  }

  async function createRun(event) {
    event.preventDefault();
    if (state.busy) return;
    const form = event.currentTarget;
    let payload;
    try {
      const signature = sourcePreflightSignature();
      if (!state.sourcePreflight || state.sourcePreflightSignature !== signature) {
        invalidateSourcePreflight({ quiet: true });
        throw new Error("剧本内容已经变化，请重新读取并判断场景后再建立审查草稿。");
      }
      if (!state.sourcePreflightConfirmed) {
        throw new Error("请先确认场景判断，再选择审查草稿生成方式。");
      }
      payload = {
        project: $("#projectName").value.trim(),
        source: sourcePayload(),
        generation_mode: $('input[name="generationMode"]:checked')?.value || "format_only",
        direction_profile: $("#sourceDirectionProfile").value,
      };
    } catch (error) {
      handleError(error);
      return;
    }
    if (state.upstreamRelease) {
      payload.script_release = state.upstreamRelease;
    }
    setBusy(true);
    try {
      const result = await api("/production-runs", { method: "POST", body: JSON.stringify(payload) });
      adoptRunResult(result, { replaceJob: true });
      await loadTaskPreflight();
      updateShell(); await loadRuns(); showStage("mapping", { force: true });
      toast("制作任务已建立，开始确认角色映射。");
      form.reset();
      invalidateSourcePreflight({ quiet: true });
      updateGenerationModeUi();
      state.sourceFileName = null;
      state.upstreamRelease = null;
      $("#activeSourceBadge")?.classList.add("hidden");
      $("#dropzonePrompt")?.classList.remove("hidden");
      $("#dropzoneFileInfo")?.classList.add("hidden");
      $("#scriptFileStatus").textContent = "支持 .txt、.md、Markdown 剧本文档（最大 5 MiB）";
    } catch (error) { handleError(error); } finally { setBusy(false); }
  }

  function sourcePayload() {
    if (state.sourceMode === "writing" && !state.upstreamRelease) {
      throw new Error("请先选择一份已冻结的写作定稿，或切换到文件/手动来源。");
    }
    if (state.sourceMode === "file" && !state.sourceFileName) {
      throw new Error("请先选择要导入的剧本文件。");
    }
    const source = { kind: state.sourceMode === "file" ? "file_upload" : "inline", text: $("#scriptText").value };
    if (state.sourceMode === "file") source.filename = state.sourceFileName;
    return source;
  }

  function sourcePreflightSignature() {
    const release = state.upstreamRelease || {};
    return JSON.stringify({
      mode: state.sourceMode,
      project: $("#projectName")?.value.trim() || "",
      text: $("#scriptText")?.value || "",
      filename: state.sourceFileName || "",
      release_id: release.id || "",
      release_hash: release.content_hash || "",
    });
  }

  function invalidateSourcePreflight({ quiet = false } = {}) {
    const hadPreflight = Boolean(state.sourcePreflight || state.sourcePreflightSignature);
    state.sourcePreflight = null;
    state.sourcePreflightSignature = "";
    state.sourcePreflightConfirmed = false;
    const panel = $("#sourcePreflight");
    if (panel) {
      panel.classList.add("hidden");
      panel.innerHTML = "";
    }
    $("#draftGenerationDecision")?.classList.add("hidden");
    if (!quiet && hadPreflight) {
      $("#sourceStatus").textContent = "剧本已修改，请重新识别分场。";
    }
    syncSourceReadAction({ updateStatus: !hadPreflight });
  }

  function syncSourceReadAction({ updateStatus = true } = {}) {
    const button = $("#preflightSource");
    const missingRelease = state.sourceMode === "writing" && !state.upstreamRelease;
    const missingScript = !$("#scriptText")?.value.trim();
    const missingName = !$("#projectName")?.value.trim();
    if (button) button.disabled = missingRelease || missingScript || missingName;
    if (!updateStatus) return;
    const status = $("#sourceStatus");
    if (status && !state.sourcePreflight) status.textContent = missingRelease ? "请先选择已冻结的写作定稿。"
      : missingScript ? "请先导入或粘贴剧本。"
      : missingName ? "请填写 AA 工程名称。" : "剧本已就绪，可以预览分场。";
  }

  function normalizeReleaseHash(value) {
    const match = String(value || "").trim().match(/^(?:sha256:)?([a-f0-9]{64})$/i);
    if (!match) throw new Error("写作定稿缺少有效的 SHA-256，已停止交接。");
    return match[1].toLowerCase();
  }

  function writingReleaseEntryMarkup(works = []) {
    const currentId = new URLSearchParams(location.search).get("work_id");
    const current = works.find(work => work.id === currentId);
    const choices = current ? [current] : works;
    return `<div class="writing-releases-empty writing-release-entry">
      <h4>${works.length ? '暂无可选的制作定稿' : '还没有写作作品'}</h4>
      <div class="release-entry-actions">${choices.map(work => `<a class="quiet release-entry-link" href="/?section=writing&amp;stage=release&amp;work_id=${encodeURIComponent(work.id)}" data-writing-release-review="${esc(work.id)}"><span>${esc(work.title || '未命名作品')}</span><b>打开定稿页 →</b></a>`).join('') || '<a class="quiet release-entry-link" href="/?section=projects" data-writing-projects>打开作品中心 →</a>'}</div>
    </div>`;
  }

  async function loadWritingWorksAndReleases() {
    const grid = $("#writingReleasesGrid");
    if (!grid) return;
    if (IS_STANDALONE_PRODUCTION) {
      grid.innerHTML = '<div class="writing-releases-empty"><p>当前处于独立 AA 制作模式，可通过上方“从本机文件导入”直接载入剧本。</p></div>';
      return;
    }
    try {
      grid.innerHTML = '<p class="empty">正在获取写作工作台作品与定稿...</p>';
      const response = await fetch("/api/v1/works", { headers: { "Accept": "application/json" } });
      if (!response.ok) throw new Error("写作服务暂时不可用，请检查连接后重试。");
      const json = await response.json();
      const works = json.data || json.works || [];
      if (!works.length) {
        grid.innerHTML = writingReleaseEntryMarkup();
        return;
      }

      const releaseItems = [];
      let unreadWorks = 0;
      for (const work of works) {
        try {
          const wResp = await fetch(`/api/v1/works/${encodeURIComponent(work.id)}`, { headers: { "Accept": "application/json" } });
          if (!wResp.ok) { unreadWorks++; continue; }
          const wJson = await wResp.json();
          const wData = wJson.data || wJson.work || {};
          const releases = wData.releases || [];
          for (const rel of releases) {
            let sceneCount = 1;
            try {
              sceneCount = rel.scenes?.length || (rel.source_revision_ids_json ? JSON.parse(rel.source_revision_ids_json).length : 1);
            } catch (_) {}
            releaseItems.push({
              workId: work.id,
              workTitle: wData.title || work.title || "未命名作品",
              releaseId: rel.id,
              displayVersion: rel.display_version || "v1",
              sceneCount,
              releasedAt: rel.released_at,
            });
          }
        } catch (_) { unreadWorks++; }
      }

      const unreadNotice = unreadWorks ? `<div class="writing-releases-empty" role="status"><p>${unreadWorks} 部作品暂未读取成功，不能确认是否已有定稿。请使用上方「刷新作品列表」重试。</p></div>` : '';
      if (!releaseItems.length) {
        grid.innerHTML = unreadNotice || writingReleaseEntryMarkup(works);
        return;
      }

      grid.innerHTML = unreadNotice + releaseItems.map(item => `
        <article class="writing-release-card formal-release">
          <div class="release-card-body">
            <div class="release-card-head">
              <span class="release-tag published">定稿 ${esc(item.displayVersion)}</span>
              <small>${item.releasedAt ? new Date(item.releasedAt).toLocaleDateString() : '进行中'}</small>
            </div>
            <h4>${esc(item.workTitle)}</h4>
            <p>包含 ${esc(item.sceneCount)} 个冻结场景 · 建立任务后执行 AA 初审</p>
          </div>
          <button type="button" class="primary select-writing-release-btn" data-work-id="${esc(item.workId)}" data-release-id="${esc(item.releaseId || '')}" data-work-title="${esc(item.workTitle)}" data-version="${esc(item.displayVersion)}">
            选用此剧本制作
          </button>
        </article>
      `).join('');

      $$('.select-writing-release-btn').forEach(btn => {
        btn.addEventListener('click', () => selectWritingRelease(btn.dataset.workId, btn.dataset.releaseId, btn.dataset.workTitle, btn.dataset.version));
      });

    } catch (err) {
      grid.innerHTML = `<div class="writing-releases-empty"><p>未能读取写作工作台：${esc(err.message)}</p></div>`;
    }
  }

  async function selectWritingRelease(workId, releaseId, workTitle, version) {
    try {
      setBusy(true);
      let scriptText = "";
      let upstream = null;
      if (releaseId) {
        const resp = await fetch(`/api/v1/releases/${encodeURIComponent(releaseId)}`, { headers: { "Accept": "application/json" } });
        if (!resp.ok) throw new Error("无法读取发布定稿内容");
        const json = await resp.json();
        const relData = json.data || json;
        scriptText = relData.text || "";
        upstream = {
          schema_version: "1.0",
          id: relData.id,
          work_id: relData.work_id,
          display_version: relData.display_version,
          content_hash: normalizeReleaseHash(relData.content_hash),
          writing_pack_version: relData.writing_pack_version || "ba-writing.productized/1.0.0",
        };
      } else {
        throw new Error("只有冻结后的 ScriptRelease 才能进入 AA 制作。");
      }

      invalidateSourcePreflight({ quiet: true });
      $("#scriptText").value = scriptText;
      $("#projectName").value = `${workTitle} - ${version || '第一章'}`;
      state.upstreamRelease = upstream;
      state.sourceMode = "writing";
      state.sourceFileName = null;
      $("#scriptText").readOnly = true;
      syncSourceEditFields();

      const badge = $("#activeSourceBadge");
      if (badge) {
        badge.classList.remove("hidden");
        $("#activeSourceTitle").textContent = `${workTitle} (${version || '写作端'})`;
      }
      toast(`已成功载入《${workTitle}》剧本！`);
      $("#sourceForm")?.scrollIntoView({ behavior: scrollBehavior(), block: "center" });
    } catch (err) {
      toast(err.message || "加载剧本失败", "danger");
    } finally {
      setBusy(false);
    }
  }

  function setupModernDropzone() {
    const dropzone = $("#scriptDropzone");
    const fileInput = $("#scriptFile");
    const browseBtn = $("#browseFileBtn");
    const prompt = $("#dropzonePrompt");
    const info = $("#dropzoneFileInfo");
    const rechoose = $("#dropzoneRechoose");
    const clear = $("#dropzoneClear");

    if (!dropzone || !fileInput) return;

    browseBtn?.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); fileInput.click(); });
    dropzone.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      fileInput.click();
    });

    ["dragenter", "dragover"].forEach(name => {
      dropzone.addEventListener(name, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.add("dragover");
      });
    });

    ["dragleave", "drop"].forEach(name => {
      dropzone.addEventListener(name, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.remove("dragover");
      });
    });

    dropzone.addEventListener("drop", (e) => {
      const file = e.dataTransfer?.files?.[0];
      if (file) handleChosenFile(file);
    });

    fileInput.addEventListener("change", (e) => {
      const file = e.target.files?.[0];
      if (file) handleChosenFile(file);
    });

    rechoose?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      fileInput.value = "";
      fileInput.click();
    });

    clear?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      fileInput.value = "";
      state.sourceFileName = null;
      prompt.classList.remove("hidden");
      info.classList.add("hidden");
      $("#scriptText").value = "";
      $("#projectName").value = "";
      invalidateSourcePreflight();
    });

    async function handleChosenFile(file) {
      if (file.size > 5 * 1024 * 1024) {
        toast("剧本文件不能超过 5 MiB。", "warning");
        return;
      }
      const suffix = file.name.toLowerCase().split(".").pop();
      if (!["txt", "md", "markdown"].includes(suffix)) {
        toast("请选择 TXT、MD 或 Markdown 剧本。", "warning");
        return;
      }
      try {
        const content = (await file.text()).replace(/^\uFEFF/, "");
        invalidateSourcePreflight({ quiet: true });
        $("#scriptText").value = content;
        $("#scriptText").readOnly = false;
        state.sourceMode = "file";
        state.sourceFileName = file.name;
        state.upstreamRelease = null;
        $("#activeSourceBadge")?.classList.add("hidden");

        prompt.classList.add("hidden");
        info.classList.remove("hidden");
        $("#dropzoneFileName").textContent = file.name;
        const lineCount = Math.max(1, content.split(/\r?\n/).length);
        const sizeKb = (file.size / 1024).toFixed(1);
        $("#dropzoneFileMeta").textContent = `${sizeKb} KB · ${lineCount} 行`;

        if (!$("#projectName").value.trim()) {
          $("#projectName").value = file.name.replace(/\.(txt|md|markdown)$/i, "");
        }
        syncSourceReadAction();
        toast(`已成功读取 ${file.name}`);
      } catch (err) {
        toast("读取文件失败", "danger");
      }
    }
  }

  function syncSourceEditFields() {
    const show = state.sourceMode !== "writing" || Boolean(state.upstreamRelease);
    $$(".source-edit-field").forEach(field => { field.hidden = !show; });
    syncSourceReadAction();
  }

  function setSourceMode(target) {
    if (state.sourceMode !== target) invalidateSourcePreflight();
    state.sourceMode = target;
    $$("[data-source-tab]").forEach(tab => {
      const active = tab.dataset.sourceTab === target;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.tabIndex = active ? 0 : -1;
    });
    $("#sourcePaneWriting")?.classList.toggle("hidden", target !== "writing");
    $("#sourcePaneFile")?.classList.toggle("hidden", target !== "file");
    $("#sourcePaneManual")?.classList.toggle("hidden", target !== "manual");
    $("#scriptText").readOnly = target === "writing" && Boolean(state.upstreamRelease);
    if (target !== "writing") {
      state.upstreamRelease = null;
      $("#activeSourceBadge")?.classList.add("hidden");
    }
    if (target !== "file") state.sourceFileName = null;
    syncSourceEditFields();
  }

  function setupSourceTabs() {
    $$("[data-source-tab]").forEach(tab => {
      tab.addEventListener("click", () => setSourceMode(tab.dataset.sourceTab));
      tab.addEventListener("keydown", event => {
        if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        event.preventDefault();
        const tabs = $$("[data-source-tab]");
        const next = (tabs.indexOf(tab) + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
        setSourceMode(tabs[next].dataset.sourceTab);
        tabs[next].focus();
      });
    });

    $("#refreshWritingReleases")?.addEventListener("click", loadWritingWorksAndReleases);
    $("#writingReleasesGrid")?.addEventListener("click", event => {
      const review = event.target.closest("[data-writing-release-review]");
      const projects = event.target.closest("[data-writing-projects]");
      // Embedded mode keeps navigation and unsaved guards in the shared router.
      // Standalone HTML retains ordinary links if the writing shell is absent.
      if (review && window.HaloCueRouter?.openWork) {
        event.preventDefault();window.HaloCueRouter.openWork(review.dataset.writingReleaseReview, "release");
      } else if (projects && window.HaloCueRouter?.navigate) {
        event.preventDefault();window.HaloCueRouter.navigate({section:"projects"});
      }
    });

    $("#clearActiveSource")?.addEventListener("click", () => {
      invalidateSourcePreflight();
      state.upstreamRelease = null;
      $("#activeSourceBadge")?.classList.add("hidden");
      setSourceMode("manual");
      toast("已解除定稿绑定，可继续手动编辑");
    });
  }

  function updateGenerationModeUi() {
    const selected = $('input[name="generationMode"]:checked')?.value || "format_only";
    $("#sourceDirectionProfileControl")?.classList.toggle("hidden", selected !== "ai_direction");
    const aiReady = state.capabilities?.generation_modes?.ai_direction?.state === "available";
    const notice = $("#generationModeNotice");
    const button = $("#configureGenerationModel");
    if (!notice || !button) return;
    notice.querySelector("span").textContent = selected === "ai_direction"
      ? aiReady ? "模型已就绪；映射完成后会生成演出草稿。" : "已选择 AI 安排演出，建立任务前需要配置模型。"
      : "当前将保留已有演出指令，并进入映射与审查。";
    notice.classList.toggle("hidden", selected !== "ai_direction" || aiReady);
    button.classList.toggle("hidden", selected !== "ai_direction" || aiReady);
  }

  function preflightTone(confidence) {
    return confidence === "high" ? "pass" : confidence === "medium" ? "notice" : "warning";
  }

  function sceneSpeakerSummary(scene) {
    const speakers = Array.isArray(scene.speakers) ? scene.speakers : [];
    if (!speakers.length) return "未识别到场内说话者";
    return speakers.slice(0, 4).map((item) => typeof item === "string" ? item : item.name).filter(Boolean).join("、")
      + (speakers.length > 4 ? ` 等 ${speakers.length} 位` : "");
  }

  function renderSourcePreflight(result) {
    const panel = $("#sourcePreflight");
    const format = result.format || {};
    const speakers = result.speakers || [];
    const scenes = result.scenes || [];
    const directives = result.directives || {};
    const issues = directives.issues || [];
    const actions = result.actions || [];
    const canCreate = actions.find((action) => action.id === "create_run")?.available !== false;
    const missingBackgrounds = scenes.filter((scene) => !scene.has_background).length;
    panel.classList.remove("hidden");
    panel.innerHTML = `<header class="preflight-head"><div><h3>分场预览</h3>${format.confidence !== "high" ? `<p>${esc(format.message || "请检查识别结果。")}</p>` : ""}</div><b class="preflight-status ${preflightTone(format.confidence)}">${esc(format.label || "格式检查")}</b></header>
      <div class="preflight-summary-strip">
        <span><small>场景</small><b>${scenes.length}</b></span>
        <span><small>说话者</small><b>${speakers.length}</b></span>
        <span><small>已有 AA 指令</small><b>${esc(directives.total || 0)}</b></span>
        <span class="${missingBackgrounds ? "needs-attention" : ""}"><small>待补背景</small><b>${missingBackgrounds}</b></span>
      </div>
      <section class="scene-judgement" aria-labelledby="sceneJudgementTitle">
        <header><div><h4 id="sceneJudgementTitle">识别到的场景</h4></div>${scenes.some((scene) => scene.implicit) ? "<p>有未命名场景，建议补充场景标题。</p>" : ""}</header>
        <ol class="scene-judgement-list">${scenes.map((scene, index) => `<li class="${scene.implicit ? "implicit" : ""}">
          <span class="scene-order">${index + 1}</span>
          <div class="scene-judgement-main"><div class="scene-title-row"><b>${esc(scene.title || "未分段开场")}</b>${scene.implicit ? '<em>未写场景标题</em>' : ""}</div><small>第 ${esc(scene.line_no || 1)}–${esc(scene.end_line || scene.line_no || 1)} 行 · ${esc(sceneSpeakerSummary(scene))}</small></div>
          <div class="scene-evidence"><span>${esc(scene.dialogue_count || 0)} 段台词</span><span>${esc(scene.directive_count || 0)} 条指令</span><strong class="${scene.has_background ? "has-background" : "missing-background"}">${scene.has_background ? `背景：${esc(scene.background || "已指定")}` : "尚未指定背景"}</strong></div>
        </li>`).join("") || '<li class="implicit"><span class="scene-order">!</span><div class="scene-judgement-main"><b>没有可判断的场景</b><small>请检查剧本文本后重新读取。</small></div></li>'}</ol>
      </section>
      ${issues.length ? `<div class="preflight-detail-grid"><article class="has-issues"><strong>${issues.length} 个格式问题</strong><ul>${issues.slice(0, 4).map((issue) => `<li><b>第 ${esc(issue.line_no)} 行</b><span>${esc(issue.message)}<em>${esc(issue.action)}</em></span></li>`).join("")}</ul></article></div>` : ""}
      <footer class="preflight-confirm"><button type="button" class="primary" id="confirmSceneJudgement" ${canCreate ? "" : "disabled"}>确认分场，选择草稿方式</button></footer>`;
    $("#confirmSceneJudgement")?.addEventListener("click", () => {
      if (state.sourcePreflightSignature !== sourcePreflightSignature()) {
        invalidateSourcePreflight();
        toast("剧本已经变化，请重新判断场景。", "warning");
        return;
      }
      state.sourcePreflightConfirmed = true;
      $("#draftGenerationDecision")?.classList.remove("hidden");
      $("#sourceStatus").textContent = "分场已确认，可以建立任务。";
      $("#confirmSceneJudgement").textContent = "场景判断已确认";
      $("#confirmSceneJudgement").disabled = true;
      updateGenerationModeUi();
      $("#draftGenerationDecision")?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
    });
    panel.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
  }

  async function preflightSource() {
    const source = $("#scriptText").value;
    if (!source.trim()) { toast("请先输入要读取的剧本文本。", "warning"); $("#scriptText").focus(); return; }
    if (!$("#projectName").value.trim()) { toast("请先填写 AA 工程名称。", "warning"); $("#projectName").focus(); return; }
    const button = $("#preflightSource");
    button.disabled = true;
    button.textContent = "正在识别分场…";
    try {
      const signature = sourcePreflightSignature();
      const result = await api("/script-preflight", { method: "POST", body: JSON.stringify({ source: sourcePayload() }) });
      if (signature !== sourcePreflightSignature()) {
        invalidateSourcePreflight({ quiet: true });
        toast("读取期间剧本发生变化，请重新判断场景。", "warning");
        return;
      }
      state.sourcePreflight = result;
      state.sourcePreflightSignature = signature;
      state.sourcePreflightConfirmed = false;
      $("#draftGenerationDecision")?.classList.add("hidden");
      renderSourcePreflight(result);
      $("#sourceStatus").textContent = "已识别分场，请核对。";
    } catch (error) { handleError(error); } finally { button.textContent = "重新识别并预览分场"; syncSourceReadAction({ updateStatus: false }); }
  }

  function mappingFor(speaker) {
    const cast = state.currentDraft?.cast?.cast || {};
    return cast[speaker] || { kind: "unset" };
  }

  function mappingLabel(mapping) {
    if (!mapping || mapping.kind === "unset") return "尚未映射";
    if (mapping.role === "teacher") return mapping.name || "老师";
    if (mapping.kind === "narrator") return "旁白（不显示角色）";
    if (mapping.kind === "voice") return mapping.display_name || "无立绘角色";
    return mapping.name || mapping.display_name || "已选择角色";
  }

  function mappingStatusLabel(mapping) {
    if (!mapping || mapping.kind === "unset") return "尚未映射";
    if (mapping.role === "teacher") return "老师身份";
    if (mapping.kind === "narrator") return "旁白";
    if (mapping.kind === "voice") return "无立绘角色";
    return mapping.name || "已选立绘角色";
  }

  function mappingResource(mapping) {
    if (!mapping || mapping.kind !== "portrait") return null;
    const identifier = String(mapping.id || "").trim();
    if (!identifier) return null;
    return state.characterCatalog?.find((item) => String(item.identifier || item.key || "") === identifier) || mapping;
  }

  function mappingPreview(mapping) {
    const resource = mappingResource(mapping);
    if (mapping?.kind === "unset") {
      return '<span class="mapping-avatar mapping-avatar-empty" aria-hidden="true">待选择</span>';
    }
    if (!resource || mapping.kind !== "portrait") {
      return '<span class="mapping-avatar mapping-avatar-empty" aria-hidden="true">无立绘</span>';
    }
    return resource.preview_available === true
      ? previewImage("characters", resource.identifier || resource.key, resource.name || mapping.name || "角色头像", "mapping-avatar-image", true)
      : '<span class="mapping-avatar mapping-avatar-empty" aria-hidden="true">待预览</span>';
  }

  function mappingEvidence(mapping) {
    if (!mapping || mapping.kind === "unset") return ["尚未选择角色资源"];
    if (mapping.role === "teacher") return ["老师身份已登记", "无立绘，不占用站位"];
    if (mapping.kind === "narrator") return ["旁白，不使用角色服装"];
    if (mapping.kind === "voice") return ["语音角色，不显示角色立绘"];
    const resource = mappingResource(mapping) || mapping;
    const outfit = resource?.outfit_key || mapping.outfit_key || "";
    const spine = resource?.spine || mapping.spine || "";
    const faceCount = resource?.face_count ?? mapping.face_count;
    return [
      outfit ? `服装：${outfit}` : "服装未标注，需打开素材核对",
      spine ? "骨骼资源已登记" : "骨骼资源待核对",
      faceCount != null ? `${faceCount} 个已登记表情` : "表情数量待核对",
    ];
  }

  function sceneDirectionState(scene, index, sceneList) {
    const start = Number(scene?.start_line || scene?.line_no || 1);
    const nextStart = Number(sceneList?.[index + 1]?.start_line || sceneList?.[index + 1]?.line_no || 0);
    const end = Number(scene?.end_line || (nextStart > start ? nextStart - 1 : Number.MAX_SAFE_INTEGER));
    const cards = (state.currentDraft?.cards || []).filter((card) => {
      const line = Number(card.line_no || 0);
      return line >= start && line <= end;
    });
    const hasDirection = cards.some((card) => {
      const current = card.current || {};
      return ["face", "emo", "act", "fx"].some((field) => String(current[field] || "").trim());
    });
    if (hasDirection) return { className: "ready", label: "已有演出草稿", detail: "可在逐卡审查中继续调整" };
    const runState = state.currentRun?.state;
    if (runState === "generating_direction") return { className: "running", label: "演出生成中", detail: "等待生成任务完成" };
    if (runState === "direction_failed") return { className: "failed", label: "演出生成失败", detail: "回到场景制作计划重试" };
    if (state.currentRun?.source_summary?.generation_mode === "ai_direction") {
      return { className: "pending", label: "待生成演出", detail: "完成角色映射后进入场景制作计划" };
    }
    return { className: "stable", label: "沿用剧本演出", detail: "当前任务不会自动添加 AI 演出" };
  }

  function preflightRequestLabel(request) {
    return request.kind === "background_request" ? "背景请求" : "音效请求";
  }

  function renderTaskPreflight() {
    const panel = $("#taskPreflight");
    const summary = state.taskPreflight;
    if (!panel || !state.currentRun) return;
    if (!summary) { panel.innerHTML = '<p class="empty">正在读取本任务的初审摘要。</p>'; return; }
    const speakers = summary.speakers || [];
    const requests = summary.requests || [];
    const diagnostics = summary.diagnostics || [];
    const errors = diagnostics.filter((item) => item.severity === "error");
    const unmapped = speakers.filter((item) => item.mapping?.kind === "unset");
    const action = summary.next_action || {};
    const issueCount = unmapped.length + requests.length + errors.length;
    const statusClass = issueCount ? (errors.length ? "has-errors" : "needs-work") : "ready";
    const summaryText = issueCount
      ? `需要处理 ${issueCount} 项 · ${unmapped.length ? `${unmapped.length} 位角色待确认` : ""}${requests.length ? `${unmapped.length ? " · " : ""}${requests.length} 项素材待处理` : ""}${errors.length ? `${unmapped.length || requests.length ? " · " : ""}${errors.length} 项编译阻断` : ""}`
      : `检查通过 · ${speakers.length} 位说话者已处理 · 无素材缺口`;
    const detailLabel = issueCount ? "查看问题" : "查看检查明细";
    panel.innerHTML = `<header class="task-preflight-head task-preflight-compact ${statusClass}"><div class="task-preflight-status-line"><span class="task-preflight-status-dot" aria-hidden="true"></span><div><small>系统初审 · 基于冻结草稿</small><h3>${esc(summaryText)}</h3><p>${esc(issueCount ? "先处理标出的项目，再进入场景制作。" : "可以继续角色确认和逐卡审查。")}</p></div></div><div class="task-preflight-actions"><button type="button" class="quiet" id="refreshTaskPreflight" title="重新读取初审摘要">刷新</button><button type="button" class="quiet" data-task-preflight-details>${detailLabel}</button></div></header>
      <details class="task-preflight-detail-list" ${issueCount ? "open" : ""}><summary><span>${issueCount ? "待处理项目" : "检查明细"}</span><small>${issueCount ? "只显示需要你决定的内容" : "正常项已收起"}</small></summary>
        <div class="task-preflight-grid">
          <article class="${unmapped.length ? "needs-work" : "is-muted"}"><small>角色映射</small><strong>${unmapped.length ? `${unmapped.length} 位待确认` : `${speakers.length} 位已处理`}</strong><p>${unmapped.length ? "未映射角色会阻止后续生成与编译。" : "每位说话者都有明确的处理方式。"}</p>${unmapped.length ? `<ul>${unmapped.map((speaker) => `<li><span><b>${esc(speaker.speaker)}</b><em>${esc(speaker.count)} 段台词</em></span><strong class="mapping-state missing">待确认</strong></li>`).join("")}</ul>` : ""}</article>
          <article class="${requests.length ? "needs-work" : "is-muted"}"><small>素材请求</small><strong>${requests.length ? `${requests.length} 项待处理` : "没有缺口"}</strong><p>${requests.length ? "在审查器内处理冻结素材清单中的请求。" : "未检测到需要单独处理的背景或音效请求。"}</p>${requests.length ? `<ul>${requests.slice(0, 3).map((request) => `<li><span><b>${esc(preflightRequestLabel(request))}</b><em>第 ${esc(request.line_no || "-")} 行 · ${esc(request.description || "等待处理")}</em></span><button type="button" data-preflight-card="${esc(request.card_id)}">打开处理</button></li>`).join("")}${requests.length > 3 ? `<li><em>另有 ${requests.length - 3} 项素材请求</em></li>` : ""}</ul>` : ""}</article>
          <article class="${errors.length ? "has-errors" : diagnostics.length ? "needs-work" : "is-muted"}"><small>编译诊断</small><strong>${errors.length ? `${errors.length} 项阻断` : diagnostics.length ? `${diagnostics.length} 项提示` : "没有阻断"}</strong><p>${errors.length ? "先处理阻断项，编译门禁才会打开。" : diagnostics.length ? "提示不会自动修改草稿。" : "可以继续逐卡审查。"}</p>${diagnostics.length ? `<ul>${diagnostics.slice(0, 3).map((item) => `<li><b>${esc(item.line_no ? `第 ${item.line_no} 行` : item.code)}</b><em>${esc(item.message)}</em></li>`).join("")}${diagnostics.length > 3 ? `<li><em>另有 ${diagnostics.length - 3} 项诊断</em></li>` : ""}</ul>` : ""}</article>
        </div>
        <footer class="task-preflight-next"><div><small>下一步</small><strong>${esc(action.label || "确认角色映射")}</strong><p>${esc(action.detail || "请继续完成当前步骤。")}</p></div></footer>
      </details>`;
    $("#refreshTaskPreflight")?.addEventListener("click", loadTaskPreflight);
    $("[data-task-preflight-details]")?.addEventListener("click", () => {
      const details = $(".task-preflight-detail-list");
      if (details) details.open = true;
    });
    $$("[data-preflight-card]").forEach((button) => button.addEventListener("click", () => {
      const card = state.currentDraft?.cards?.find((item) => item.card_id === button.dataset.preflightCard);
      if (!card) return;
      state.selectedCard = card;
      showStage("review", { force: true });
    }));
  }

  async function loadTaskPreflight() {
    if (!state.currentRun?.run_id) { state.taskPreflight = null; state.aiPreflight = null; renderAiPreflight(); return; }
    const runId = state.currentRun.run_id;
    try {
      const result = await api(`/production-runs/${encodeURIComponent(runId)}/preflight-summary`);
      if (state.currentRun?.run_id !== runId) return;
      state.taskPreflight = result;
    } catch (error) {
      if (state.currentRun?.run_id !== runId) return;
      state.taskPreflight = null;
      toast(error.message || "无法读取任务初审摘要。", "warning");
    }
    renderTaskPreflight();
    await loadAiPreflights();
    if (state.currentRun?.run_id !== runId) return;
    await loadCharacterCatalog();
  }

  async function loadCharacterCatalog() {
    if (!state.currentRun?.run_id || state.characterCatalogRunId === state.currentRun.run_id) return;
    const runId = state.currentRun.run_id;
    try {
      const result = await api(`/production-runs/${encodeURIComponent(runId)}/resources/characters?q=&limit=200`);
      if (state.currentRun?.run_id !== runId) return;
      state.characterCatalog = Array.isArray(result.items) ? result.items : [];
      state.characterCatalogRunId = runId;
      if (state.currentStage === "mapping") renderMapping();
    } catch (_) {
      // Mapping remains usable without previews; the picker can retry its own request.
    }
  }

  function renderAiPreflight() {
    const panel = $("#aiPreflight");
    if (!panel) return;
    if (!state.currentRun) { panel.innerHTML = ""; return; }
    const capability = state.capabilities?.ai_preflight || {};
    const available = capability.state === "available";
    const latest = state.aiPreflight?.items?.[0];
    const analysis = latest?.analysis || {};
    const speakers = analysis.potential_speakers || [];
    const scenes = analysis.scenes || [];
    const ambiguities = analysis.ambiguities || [];
    const source = state.currentRun.source_summary || {};
    const speakerDetails = Array.isArray(source.speaker_details) && source.speaker_details.length
      ? source.speaker_details
      : (source.speakers || state.currentDraft?.cast?.detected_speakers || []).map((speaker) => ({ speaker, count: 0, sample: "" }));
    const sourceScenes = Array.isArray(source.scenes) ? source.scenes : [];
    const format = source.format?.label || source.format_label || (source.speakers?.length ? "角色：台词" : "混合剧本格式");
    const alertClass = latest ? (ambiguities.length ? "warning" : "success") : "pending";
    const alertText = latest
      ? (ambiguities.length ? `AI 初审发现 ${ambiguities.length} 项需要你确认，建议先处理角色和场景歧义。` : "未发现阻塞问题，可以检查并确认角色映射和演出规划。")
      : (available ? "规则检查已完成，AI 演出规划尚未运行。运行后会补充场景、角色和素材线索。" : "AI 初审需要先配置模型；当前不会用模拟结果代替真实建议。");
    const action = available
      ? `<button type="button" id="runAiPreflight" class="quiet" ${state.busy ? "disabled" : ""}>${state.busy ? "AI 初审处理中" : latest ? "重新运行 AI 初审" : "运行 AI 初审"}</button>`
      : `<button type="button" id="configureAiPreflight" class="quiet">去配置模型</button>`;
    const castRows = speakerDetails.length
      ? speakerDetails.map((item) => {
        const speaker = item.speaker || item.name || "未命名说话者";
        const mapping = mappingFor(speaker);
        const mapped = mapping && mapping.kind && mapping.kind !== "unset";
        const evidence = mappingEvidence(mapping);
        return `<li class="ai-preflight-cast-row"><span class="ai-preflight-cast-identity">${mappingPreview(mapping)}<span><b>${esc(speaker)}</b><em>${esc(item.count || 0)} 段台词${item.sample ? ` · “${esc(item.sample)}”` : ""}</em><small>${esc(evidence.join(" · "))}</small></span></span><span class="ai-preflight-cast-state ${mapped ? "ready" : "missing"}">${esc(mapped ? mappingStatusLabel(mapping) : "待确认")}</span><button type="button" class="quiet" data-ai-preflight-action="confirm-mapping" data-speaker="${esc(speaker)}">${mapped ? "修改" : "选择角色"}</button></li>`;
      }).join("")
      : '<li><em>没有识别到说话者，请检查剧本格式。</em></li>';
    const sceneRows = scenes.length
      ? scenes.map((scene, index) => { const direction = sceneDirectionState(scene, index, scenes); return `<li class="ai-preflight-scene-row"><span><b>第 ${esc(scene.start_line)}-${esc(scene.end_line)} 行</b><strong>${esc(scene.location || "地点待确认")}${scene.time ? ` · ${esc(scene.time)}` : ""}</strong><em class="ai-preflight-scene-state ${direction.className}">${esc(direction.label)} · ${esc(direction.detail)}</em><small class="ai-preflight-scene-background">背景建议：${esc(scene.background_need || "未给出")}</small></span><button type="button" class="quiet" data-ai-preflight-action="review-scene" data-line="${esc(scene.start_line || "")}">查看场景</button></li>`; }).join("")
      : sourceScenes.length
        ? sourceScenes.map((scene, index) => { const direction = sceneDirectionState(scene, index, sourceScenes); return `<li class="ai-preflight-scene-row"><span><b>第 ${esc(scene.line_no || "-")} 行</b><strong>${esc(scene.title || "未命名场景")}</strong><em class="ai-preflight-scene-state ${direction.className}">${esc(direction.label)} · ${esc(direction.detail)}</em><small class="ai-preflight-scene-background">背景建议：运行 AI 初审后补充</small></span><button type="button" class="quiet" data-ai-preflight-action="review-scene" data-line="${esc(scene.line_no || "")}">查看场景</button></li>`; }).join("")
        : '<li><em>暂未识别场景变化；可以运行 AI 初审补充规划。</em></li>';
    const ambiguityRows = ambiguities.length
      ? ambiguities.slice(0, 6).map((item) => `<li><b>第 ${esc(item.line || "-")} 行</b><span>${esc(item.message || "需要人工确认")}</span></li>`).join("")
      : '<li><em>没有发现必须由你决定的场景或角色歧义。</em></li>';
    const aiSummary = latest
      ? (ambiguities.length ? `有 ${ambiguities.length} 项建议待确认` : "建议已生成，可以按需查看")
      : (available ? "尚未运行，可按需生成" : "需要先配置模型");
    const aiSummaryDetail = latest
      ? "AI 只提供参考，不会改写已冻结的场景判断。"
      : "这是可选步骤，不影响角色映射和场景制作。";
    const result = `<details class="ai-preflight-detail-list" ${ambiguities.length ? "open" : ""}>
      <summary><span>${latest ? "查看 AI 建议" : "查看说明与识别明细"}</span><small>角色、场景和素材建议</small></summary>
      <div class="ai-preflight-decision-surface">
        <div class="ai-preflight-alert ${alertClass}" role="status"><strong>${esc(alertText)}</strong><span>${latest ? "建议不会自动修改草稿；确认后仍需在下方工作面执行。" : "只读取创建任务时冻结的剧本，不写入角色映射、素材或演出草稿。"}</span></div>
        <div class="ai-preflight-source-summary"><span><small>剧本识别</small><b>${esc(format)}</b></span><span><small>剧本行数</small><b>${esc(source.line_count || 0)} 行</b></span><span><small>说话者</small><b>${esc(speakerDetails.length)} 位 · ${esc(source.dialogue_count || 0)} 段台词</b></span><span><small>场景</small><b>${esc(latest ? scenes.length : sourceScenes.length)} 段</b></span></div>
        <div class="ai-preflight-decision-grid">
          <article class="ai-preflight-cast-panel"><header><div><small>角色映射</small><h4>确认每个说话者怎么出场</h4></div><button type="button" class="quiet" data-ai-preflight-action="mapping">查看全部映射</button></header><ul class="ai-preflight-cast-list">${castRows}</ul></article>
          <article class="ai-preflight-scene-panel"><header><div><small>场景演出规划</small><h4>${latest ? "地点、时间和背景建议" : "规则识别到的场景"}</h4></div><button type="button" class="quiet" data-ai-preflight-action="assets">处理素材</button></header><ul class="ai-preflight-scene-list">${sceneRows}</ul></article>
        </div>
        <article class="ai-preflight-issues-panel ${ambiguities.length ? "has-errors" : ""}"><header><div><small>需要处理</small><h4>${ambiguities.length ? `${ambiguities.length} 项待确认` : "暂无必须处理的问题"}</h4></div><span>${latest ? "AI 只提供建议" : "运行后显示"}</span></header><ul>${ambiguityRows}</ul></article>
        <footer class="ai-preflight-decision-footer"><span>${latest ? "确认映射和演出规划后，再进入场景制作计划。" : "先运行 AI 初审，再检查角色、场景和素材建议。"}</span><button type="button" class="quiet" data-ai-preflight-action="confirm-mapping">回到角色映射</button></footer>
      </div>
    </details>`;
    panel.innerHTML = `<header class="ai-preflight-head ai-preflight-compact"><div><small>可选 · AI 演出建议</small><h3>${esc(aiSummary)}</h3><p>${esc(aiSummaryDetail)}</p></div><div class="ai-preflight-actions">${action}${latest ? `<button type="button" class="quiet" data-ai-preflight-details>查看建议</button>` : ""}</div></header>${result}`;
    $("#runAiPreflight")?.addEventListener("click", startAiPreflight);
    $("#configureAiPreflight")?.addEventListener("click", () => openSettingsDialog("model"));
    $("[data-ai-preflight-details]")?.addEventListener("click", () => {
      const details = $(".ai-preflight-detail-list");
      if (details) details.open = true;
    });
    $$('[data-ai-preflight-action]').forEach((button) => button.addEventListener("click", () => {
      const actionName = button.dataset.aiPreflightAction;
      if (actionName === "rerun") startAiPreflight();
      if (actionName === "mapping") $("#mappingList")?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
      if (actionName === "confirm-mapping") {
        if (button.dataset.speaker) openMapping(button.dataset.speaker);
        else $("#mappingList")?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
      }
      if (actionName === "review-scene") {
        const card = (state.currentDraft?.cards || []).find((item) => String(item.line_no || "") === String(button.dataset.line || ""));
        if (card) state.selectedCard = card;
        showStage("review", { force: true });
      }
      if (actionName === "assets") openAssetLibrary();
    }));
  }

  async function loadAiPreflights() {
    if (!state.currentRun?.run_id) { state.aiPreflight = null; renderAiPreflight(); return; }
    const runId = state.currentRun.run_id;
    try {
      const result = await api(`/production-runs/${encodeURIComponent(runId)}/ai-preflights`);
      if (state.currentRun?.run_id !== runId) return;
      state.aiPreflight = result;
    } catch (error) {
      if (state.currentRun?.run_id !== runId) return;
      state.aiPreflight = null;
      toast(error.message || "无法读取 AI 初审结果。", "warning");
    }
    renderAiPreflight();
  }

  async function startAiPreflight() {
    if (!state.currentRun || state.busy) return;
    setBusy(true);
    try {
      const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/ai-preflights`, { method: "POST", body: "{}" });
      toast("AI 初审已提交：它只读取冻结剧本，不会修改草稿。", "normal");
      await pollJob(result.job.job_id, "AI 初审");
      await loadAiPreflights();
      toast("AI 初审已完成，请确认建议后再决定是否处理映射或素材。", "normal");
    } catch (error) { handleError(error); } finally { setBusy(false); }
  }

  function draftSceneGroups() {
    const cards = state.currentDraft?.cards || [];
    const groups = [];
    const hasSceneCards = cards.some((card) => card.kind === "scene");
    let current = null;
    for (const card of cards) {
      if (card.kind === "scene") {
        current = { card, title: card.current?.title || "未命名场景", cards: [] };
        groups.push(current);
      } else if (current === null) {
        if (hasSceneCards) continue;
        current = { card: null, title: "开场段落", cards: [] };
        groups.push(current);
      }
      current.cards.push(card);
    }
    return groups.map((scene, index) => {
      const next = groups[index + 1];
      const firstLine = Number(scene.card?.line_no || scene.cards.find((card) => card.line_no)?.line_no || 1);
      const lastLine = next
        ? Math.max(firstLine, Number(next.card?.line_no || firstLine + 1) - 1)
        : Math.max(firstLine, ...scene.cards.map((card) => Number(card.line_no || firstLine)));
      const background = scene.card
        ? sceneBackgroundCard(scene.card)
        : scene.cards.find((card) => card.kind === "dir" && card.current?.cmd === "bg");
      const speakers = [...new Set(scene.cards.filter((card) => card.kind === "line").map((card) => String(card.current?.who || "旁白")))];
      const evidence = scene.cards.filter((card) => card.kind === "line" || card.kind === "meta").slice(0, 3).map((card) => {
        if (card.kind === "line") return `${card.current?.who || "旁白"}：${card.current?.text || ""}`;
        return card.current?.text || card.raw || "";
      }).filter(Boolean);
      return { ...scene, index, firstLine, lastLine, background, speakers, evidence };
    });
  }

  function aiSceneForDraft(scene) {
    const scenes = state.aiPreflight?.items?.[0]?.analysis?.scenes || [];
    return scenes.find((item) => {
      const start = Number(item.start_line || item.line_no || 0);
      return start >= scene.firstLine && start <= scene.lastLine;
    }) || scenes[scene.index] || null;
  }

  function sceneBackgroundCandidates(aiScene) {
    if (!aiScene) return [];
    const values = aiScene.background_candidates || aiScene.candidates || aiScene.backgrounds || [];
    return Array.isArray(values) ? values.filter(Boolean) : [];
  }

  function backgroundGenerationPrompt(scene) {
    const evidence = Array.isArray(scene?.evidence) && scene.evidence.length
      ? scene.evidence.map((line) => `- ${line}`).join("\n")
      : "- 没有额外台词证据，请以场景标题为主。";
    return [
      "请生成一张用于剧情演出的日系二次元游戏背景图。",
      `场景：${scene?.title || "未命名场景"}`,
      `剧情位置：第 ${scene?.firstLine || "-"}–${scene?.lastLine || "-"} 行`,
      "原文证据：",
      evidence,
      "构图要求：横向 16:9，环境空间关系清晰，保留角色站位与对白区域。",
      "画面要求：纯环境背景，不出现角色、文字、UI、Logo 或水印；光线、时间与气氛贴合剧情。",
      "质量要求：细节清楚、低噪点、透视稳定，适合作为视觉小说或剧情演出的背景。",
    ].join("\n");
  }

  function openBackgroundPrompt(scene, { importImmediately = false } = {}) {
    if (!scene) return;
    state.backgroundPromptScene = {
      card_id: scene.card?.card_id || scene.cards?.[0]?.card_id || "",
      title: scene.title || "未命名场景",
      firstLine: scene.firstLine,
      lastLine: scene.lastLine,
      evidence: scene.evidence || [],
    };
    $("#backgroundPromptTitle").textContent = "生图提示词";
    $("#backgroundPromptScene").textContent = `场景：${state.backgroundPromptScene.title} · 第 ${state.backgroundPromptScene.firstLine || "-"}–${state.backgroundPromptScene.lastLine || "-"} 行`;
    $("#backgroundPromptText").value = backgroundGenerationPrompt(state.backgroundPromptScene);
    $("#backgroundPromptStatus").textContent = "提示词只保存在当前窗口，不会改写剧本。";
    $("#backgroundPromptDialog").showModal();
    if (importImmediately) openGeneratedBackgroundImport();
  }

  async function copyBackgroundPrompt() {
    const value = $("#backgroundPromptText").value;
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      $("#backgroundPromptStatus").textContent = "已复制，可粘贴到图片生成工具。";
    } catch (_) {
      $("#backgroundPromptText").select();
      $("#backgroundPromptStatus").textContent = "提示词已选中，请复制。";
    }
  }

  function openGeneratedBackgroundImport() {
    const sceneCard = (state.currentDraft?.cards || []).find((card) => card.card_id === state.backgroundPromptScene?.card_id);
    if (!sceneCard) {
      $("#backgroundPromptStatus").textContent = "原场景已变化，请关闭后从场景卡重新打开。";
      return;
    }
    $("#backgroundPromptDialog").close();
    openSceneBackgroundImport(sceneCard);
    $("#assetImportDialog h3").textContent = "导入生成结果";
    $("#assetImportStatus").textContent = "选择刚刚生成的背景图片；登记后会自动插入当前场景。";
  }

  function openSceneAssetWorkbench(scene) {
    state.assetLibraryKind = "backgrounds";
    $$('[data-asset-kind]').forEach((button) => button.classList.toggle("active", button.dataset.assetKind === "backgrounds"));
    const target = scene?.title ? `当前场景：“${scene.title}”` : "当前场景";
    state.assetWorkbenchContext = `${target} · 可先在这里核对背景，再回到场景卡选择使用。`;
    openAssetLibrary({ preserveContext: true });
  }

  function renderMappingScenePlan() {
    const target = $("#mappingScenePlan");
    if (!target || !state.currentDraft) return;
    const scenes = draftSceneGroups();

    target.innerHTML = scenes.length ? scenes.map((scene) => {
      const aiScene = aiSceneForDraft(scene);
      const direction = sceneDirectionState(aiScene || { start_line: scene.firstLine, end_line: scene.lastLine }, scene.index, scenes);
      const candidates = sceneBackgroundCandidates(aiScene);
      const confidence = Number(aiScene?.confidence ?? candidates[0]?.confidence);
      const reason = aiScene?.reason || aiScene?.background_reason || candidates[0]?.reason || "依据场景标题、台词原文与当前冻结背景核对。";
      const evidence = scene.evidence.length ? scene.evidence.map((line) => `<li>${esc(line)}</li>`).join("") : "<li>本场景没有可展示的台词证据。</li>";
      const sceneId = scene.card?.card_id || scene.cards[0]?.card_id || "";
      const backgroundKey = scene.background?.current?.arg || "";
      const backgroundPreview = backgroundKey && backgroundKey !== "BG_Black"
        ? previewImage("backgrounds", backgroundKey, resourceDisplayName({ key: backgroundKey }, { kind: "backgrounds", currentBackgroundKey: backgroundKey, currentBackgroundLabel: sceneTitleLabel(scene.title) }), "mapping-scene-thumb-image", null)
        : `<span class="mapping-scene-thumb-empty">${backgroundKey === "BG_Black" ? "黑屏" : "缺背景"}</span>`;
      const backgroundName = backgroundKey
        ? resourceDisplayName({ key: backgroundKey }, { kind: "backgrounds", currentBackgroundKey: backgroundKey, currentBackgroundLabel: sceneTitleLabel(scene.title) })
        : (aiScene?.background_need || "尚未确定背景");
      const stateLabel = scene.background ? "当前采用" : "待补充";
      return `<article class="mapping-scene-card ${scene.background?.current?.arg === "BG_Black" ? "ready" : "background-unverified"}">
        <header><div><small>场景 ${esc(scene.index + 1)} · 第 ${esc(scene.firstLine)}–${esc(scene.lastLine)} 行</small><h5>${esc(scene.title)}</h5></div><span>${stateLabel}</span></header>
        <details class="mapping-scene-evidence"><summary>原文证据 · ${scene.evidence.length} 条</summary><ul>${evidence}</ul></details>
        <section class="mapping-scene-background"><div class="mapping-scene-thumb">${backgroundPreview}</div><div><small>当前背景</small><strong>${esc(backgroundName)}</strong>${sceneBackgroundAvailability(backgroundKey)}<details class="mapping-scene-details"><summary>查看判断依据</summary><div><p>${esc(reason)}</p>${backgroundKey ? `<small class="mapping-scene-resource-key">资源标识：${esc(backgroundKey)}</small><p class="scene-background-protection">已指定背景受保护 · 重新安排演出不会在本场景内另换背景；需要调整时请手动更换。</p>` : ""}<em>${Number.isFinite(confidence) ? `匹配置信度 ${Math.round(confidence * 100)}%` : "未提供虚构置信度"} · ${esc(direction.label)}</em></div></details></div></section>
        ${candidates.length ? `<details class="mapping-scene-candidates"><summary>其他候选（${esc(candidates.length)}）</summary>${candidates.slice(0, 4).map((candidate) => `<p><b>${esc(candidate.label || candidate.name || candidate.aa_key || candidate.key || "候选背景")}</b><small>${esc(candidate.reason || "与场景语义接近")}</small></p>`).join("")}</details>` : ""}
        <footer><button type="button" class="primary" data-mapping-scene-official="${esc(sceneId)}">${scene.background ? "更换AA / 任务背景" : "查找AA 背景"}</button><button type="button" data-mapping-scene-prompt="${esc(sceneId)}">生成生图提示词</button><button type="button" data-mapping-scene-generated="${esc(sceneId)}">导入生成结果</button><button type="button" data-mapping-scene-history="${esc(sceneId)}">从历史项目导入</button><button type="button" data-mapping-scene-import="${esc(sceneId)}">添加自定义背景</button><button type="button" data-mapping-scene-workbench="${esc(sceneId)}">打开素材工作台</button><small class="mapping-stage-note">场景审查将在第 4 步统一进行</small></footer>
      </article>`;
    }).join("") : '<p class="empty">草稿中还没有可制作的场景。</p>';
    updateSceneBackgroundSummary(target);
    const issues = scenes.filter((scene) => !scene.background);
    const issuePanel = $("#mappingSceneIssues");
    issuePanel.hidden = issues.length === 0;
    issuePanel.innerHTML = issues.length ? `<header><small>待补素材</small><strong>${issues.length} 个场景缺少背景</strong></header><ul>${issues.map((scene) => `<li>第 ${esc(scene.firstLine)} 行“${esc(scene.title)}”还没有背景；可从 AA 本地资源、任务素材或自定义素材中选择。</li>`).join("")}</ul>` : "";
    const sceneById = (id) => scenes.find((scene) => (scene.card?.card_id || scene.cards[0]?.card_id) === id);
    $$('[data-mapping-scene-official]').forEach((button) => button.addEventListener("click", () => {
      const scene = sceneById(button.dataset.mappingSceneOfficial);
      if (!scene?.card) return;
      chooseResource("backgrounds", "场景背景", (item) => insertSceneBackground(scene.card, item), {
        sceneCardId: scene.card.card_id, source: "snapshot", eyebrow: "AA 与本任务背景", title: `为“${scene.title}”选择背景`, status: "这里只改变当前场景背景，不会重新判断场景或改写剧本。", selectionNote: "将采用此背景并建立可审查的 @bg 卡。", actionLabel: "采用此结果", kind: "backgrounds", currentBackgroundKey: scene.background?.current?.arg || "", currentBackgroundLabel: sceneTitleLabel(scene.title),
      });
    }));
    $$('[data-mapping-scene-prompt]').forEach((button) => button.addEventListener("click", () => {
      const scene = sceneById(button.dataset.mappingScenePrompt); if (scene) openBackgroundPrompt(scene);
    }));
    $$('[data-mapping-scene-generated]').forEach((button) => button.addEventListener("click", () => {
      const scene = sceneById(button.dataset.mappingSceneGenerated); if (scene) openBackgroundPrompt(scene, { importImmediately: true });
    }));
    $$('[data-mapping-scene-workbench]').forEach((button) => button.addEventListener("click", () => {
      const scene = sceneById(button.dataset.mappingSceneWorkbench); if (scene) openSceneAssetWorkbench(scene);
    }));
    $$('[data-mapping-scene-history]').forEach((button) => button.addEventListener("click", () => {
      const scene = sceneById(button.dataset.mappingSceneHistory); if (scene?.card) chooseSceneLibraryBackground(scene.card);
    }));
    $$('[data-mapping-scene-import]').forEach((button) => button.addEventListener("click", () => {
      const scene = sceneById(button.dataset.mappingSceneImport); if (scene?.card) openSceneBackgroundImport(scene.card);
    }));
  }

  function renderMapping() {
    if (!state.currentDraft || !state.currentRun) return;
    renderTaskPreflight();
    const speakers = state.currentRun.source_summary?.speakers || state.currentDraft.cast?.detected_speakers || [];
    $("#mappingCount").textContent = `${speakers.length} 位说话者`;
    const missing = speakers.filter((speaker) => mappingFor(speaker).kind === "unset").length;
    $("#mappingStatus").textContent = missing ? `${missing} 位说话者尚未映射` : "角色映射已完成；背景缺口可继续核对。";
    $("#mappingContinue").disabled = state.busy || missing > 0;
    $("#mappingList").innerHTML = speakers.length ? speakers.map((speaker) => {
      const mapping = mappingFor(speaker);
      const resource = mappingResource(mapping);
      const speakerDetail = (state.currentRun.source_summary?.speaker_details || []).find((item) => item.speaker === speaker) || {};
      const outfit = resource?.outfit_key || mapping.outfit_key || "";
      const previewState = mapping.kind === "portrait" && resource?.preview_available !== true ? "头像暂不可用" : "";
      const evidence = mappingEvidence(mapping);
      const source = resource ? resourceSourceLabel(resource) : mapping.kind === "portrait" ? "映射资源待核对" : "不使用角色资源";
      const role = mapping.role === "teacher" ? "老师身份" : mapping.kind === "portrait" ? "AA 骨骼角色" : mapping.kind === "voice" ? "语音角色" : mapping.kind === "narrator" ? "旁白" : "待确认";
      return `<article class="mapping-row ${mapping.kind === "unset" ? "is-missing" : "is-ready"}"><div class="mapping-speaker-cell">${mappingPreview(mapping)}<span><strong>${esc(speaker)}</strong><small>${esc(speakerDetail.count || 0)} 段台词${speakerDetail.sample ? ` · “${esc(speakerDetail.sample)}”` : ""}</small></span></div>
        <div class="mapping-value"><span class="mapping-role-chip">${esc(role)}</span><b>${esc(mappingLabel(mapping))}</b>${previewState ? `<small class="mapping-primary-status">${esc(previewState)}</small>` : ""}<details class="mapping-evidence-details"><summary>查看资源证据</summary><div><small>${esc(source)}${outfit ? ` · ${esc(outfit)}` : ""}</small><small>${esc(evidence.join(" · "))}</small>${resource?.face_count != null ? `<small>${esc(resource.face_count)} 个已登记表情</small>` : ""}</div></details></div>
        <button class="mapping-edit" data-speaker="${esc(speaker)}">${mapping.kind === "unset" ? "选择角色" : "修改"}</button></article>`;
    }).join("") : '<p class="empty">没有检测到说话者，请检查剧本格式。</p>';
    $$(".mapping-edit").forEach((button) => button.addEventListener("click", () => openMapping(button.dataset.speaker)));
    renderMappingScenePlan();
  }

  async function openMapping(speaker) {
    state.selectedSpeaker = speaker;
    state.teacherMappingContext = {
      runId: state.currentRun.run_id, speaker, draftVersion: state.currentDraft.draft_version,
    };
    $("#mappingDialogTitle").textContent = "选择对应角色";
    $("#mappingDialogSpeaker").textContent = `当前说话者：${speaker}`;
    $("#characterSearch").value = "";
    const currentMapping = mappingFor(speaker);
    const currentResource = mappingResource(currentMapping);
    state.mappingAliasTarget = currentMapping.kind === "portrait" ? currentResource : null;
    const currentEvidence = currentMapping.kind === "unset" ? "" : mappingEvidence(currentMapping).join(" · ");
    $("#mappingCurrentSummary").innerHTML = `<div>${mappingPreview(currentMapping)}<span><small>当前绑定</small><strong>${esc(mappingLabel(currentMapping))}</strong>${currentEvidence ? `<em>${esc(currentEvidence)}</em>` : ""}</span></div><b class="${currentMapping.kind === "unset" ? "missing" : "ready"}">${currentMapping.kind === "unset" ? "待确认" : "已绑定"}</b>`;
    $("#mappingAliasTools").hidden = !state.mappingAliasTarget;
    $("#mappingAliasHint").textContent = state.mappingAliasTarget
      ? `保存“${speaker}”为“${currentResource?.name || currentResource?.identifier || currentMapping.name || currentMapping.id}”的本机搜索别名。`
      : "先绑定一个有立绘的角色，之后可以把当前说话者保存为本机搜索别名。";
    $("#saveMappingAlias").disabled = !state.mappingAliasTarget;
    $("#mappingDialogStatus").textContent = "下面按自定义骨骼和官方骨骼分组；选择后只更新当前说话者。";
    const capability = teacherCapability();
    $("#chooseTeacherIdentity").hidden = !capability;
    $("#teacherPreset").innerHTML = (capability?.presets || []).map((preset) =>
      `<option value="${esc(preset.id)}">${esc(preset.id === "custom" ? "自定义" : `${preset.display_name} / ${preset.organization}`)}</option>`).join("");
    const identity = state.currentDraft.cast?.teacher_identity;
    $("#teacherPreset").value = identity?.preset_id || "teacher_shale";
    if (!$("#teacherPreset").value) $("#teacherPreset").selectedIndex = 0;
    $("#teacherDisplayName").value = identity?.display_name || "";
    $("#teacherDisplayName").setCustomValidity("");
    $("#teacherOrganization").value = identity?.organization || "";
    const presentation = teacherPresentationMode();
    $$('#teacherPresentationControl input').forEach((input) => { input.checked = input.value === presentation; });
    $("#teacherPresentationControl").classList.toggle("hidden", !teacherPresentationCapability());
    showTeacherIdentity(!!capability && mappingFor(speaker).role === "teacher");
    $("#mappingDialog").showModal();
    await searchCharacters("");
  }

  function teacherCapability() {
    const capability = state.capabilities?.teacher_identity;
    return capability?.schema_version === "teacher-identity/1.0"
      && capability.presentation === "slot_zero" && Array.isArray(capability.presets)
      && capability.presets.length ? capability : null;
  }

  function teacherPresentationCapability() {
    const capability = state.capabilities?.teacher_presentation;
    const modes = Array.isArray(capability?.modes)
      ? capability.modes.map((mode) => typeof mode === "string" ? mode : mode?.id) : [];
    return capability?.state === "available" && capability.schema_version === "teacher-presentation/1.0"
      && ["slot_zero", "sel_single"].every((mode) => modes.includes(mode)) ? capability : null;
  }

  function teacherPresentationMode() {
    return state.currentDraft?.cast?.teacher_presentation?.mode || "slot_zero";
  }

  function teacherPresentationBlocked() {
    const stored = state.currentDraft?.cast?.teacher_presentation;
    return !!stored && (stored.schema_version !== "teacher-presentation/1.0"
      || !["slot_zero", "sel_single"].includes(stored.mode)
      || (stored.mode !== "slot_zero" && !teacherPresentationCapability()));
  }

  function showTeacherIdentity(show) {
    const visible = show && !!teacherCapability();
    $("#teacherIdentityForm").classList.toggle("hidden", !visible);
    $("#characterResults").classList.toggle("hidden", visible);
    $("#characterSearch").classList.toggle("hidden", visible);
    $("#chooseTeacherIdentity").setAttribute("aria-expanded", String(visible));
    $("#mappingDialogStatus").textContent = visible ? "" : "选择后只会更新当前说话者的映射。";
    updateTeacherPreset();
  }

  function updateTeacherPreset() {
    const custom = $("#teacherPreset").value === "custom";
    const blocked = teacherPresentationBlocked();
    $("#teacherCustomFields").classList.toggle("hidden", !custom);
    $("#teacherPreset").disabled = blocked;
    $("#teacherDisplayName").disabled = !custom || blocked;
    $("#teacherOrganization").disabled = !custom || blocked;
    $("#saveTeacherIdentity").disabled = blocked || state.busy;
    $$('#teacherPresentationControl input').forEach((input) => { input.disabled = blocked; });
    const identity = state.currentDraft?.cast?.teacher_identity;
    $("#saveTeacherIdentity").textContent = identity ? "保存老师身份" : "创建并绑定老师";
    const aliases = Object.entries(state.currentDraft?.cast?.cast || {})
      .filter(([, mapping]) => mapping.role === "teacher").map(([speaker]) => speaker);
    $("#teacherIdentityScope").textContent = blocked
      ? `当前已保存${teacherPresentationMode() === "sel_single" ? " Sel 回答" : "的老师呈现配置"}，此后端不支持修改；已有配置保持不变。`
      : aliases.length
        ? `本任务共用同一老师身份，已绑定：${aliases.join("、")}。名称、组织和台词呈现修改将同步生效。`
        : `将为“${state.selectedSpeaker}”登记无立绘老师身份。`;
  }

  async function saveTeacherIdentity(event) {
    event.preventDefault();
    if (!teacherCapability() || teacherPresentationBlocked() || state.busy || pendingConfirmation) return;
    const mapping = {
      kind: "teacher", schema_version: "teacher-identity/1.0", preset_id: $("#teacherPreset").value,
    };
    if (teacherPresentationCapability()) {
      mapping.presentation = {
        schema_version: "teacher-presentation/1.0",
        mode: $('#teacherPresentationControl input:checked')?.value,
      };
    }
    if (mapping.preset_id === "custom") {
      mapping.display_name = $("#teacherDisplayName").value.trim();
      mapping.organization = $("#teacherOrganization").value.trim();
      if (!mapping.display_name) {
        $("#teacherDisplayName").setCustomValidity("请输入老师名称。");
        $("#teacherDisplayName").reportValidity();
        return;
      }
    }
    const identity = state.currentDraft?.cast?.teacher_identity;
    const preset = teacherCapability().presets.find((item) => item.id === mapping.preset_id);
    const displayName = mapping.preset_id === "custom" ? mapping.display_name : preset?.display_name;
    const organization = mapping.preset_id === "custom" ? mapping.organization : preset?.organization;
    const aliases = Object.entries(state.currentDraft?.cast?.cast || {})
      .filter(([, item]) => item.role === "teacher").map(([speaker]) => speaker);
    const identityChanged = identity && (identity.display_name !== displayName || identity.organization !== organization);
    const presentationChanged = mapping.presentation && mapping.presentation.mode !== teacherPresentationMode();
    if (identity && aliases.length && (identityChanged || presentationChanged)) {
      const presentationNotice = presentationChanged
        ? `台词将统一改为${mapping.presentation.mode === "sel_single" ? " Sel 回答" : "普通对白（槽 0）"}，相关卡片需要重新审查。` : "";
      const accepted = await askConfirmation({
        title: "更新共用的老师身份？",
        body: `“${aliases.join("”、“")}”将同步显示为“${displayName}${organization ? ` / ${organization}` : "（无组织）"}”。${presentationNotice}原剧本中的名称和台词保持不变。`,
        confirmLabel: "更新老师身份",
      });
      if (!accepted) return;
    }
    await saveMapping(mapping, state.teacherMappingContext);
  }

  function isCustomCharacterResource(item) {
    const source = String(item?.source || "").toLowerCase();
    const spine = String(item?.spine || "").replaceAll("/", "\\").toLowerCase();
    return source.includes("custom") || source.includes("import") || source.includes("library") || spine.startsWith("characters\\") || /^characters[\\/]/i.test(String(item?.spine || ""));
  }

  function characterPickerRow(item) {
    const selected = String(mappingFor(state.selectedSpeaker).id || "") === String(item.identifier || "");
    const context = [item.club, item.outfit_key].filter(Boolean).join(" · ");
    const previewStatus = item.preview_available === true ? "" : "头像暂不可用";
    return `<button type="button" class="character-row resource-row ${selected ? "is-selected" : ""}" data-character-id="${esc(item.identifier)}" data-character-name="${esc(item.name)}" title="资源标识：${esc(item.identifier)}" aria-pressed="${selected}" aria-label="选择 ${esc(item.name)} 映射给当前说话者">
      ${previewImage("characters", item.identifier, item.name, "resource-thumb avatar-thumb", item.preview_available === true)}<span class="character-result-copy"><strong>${esc(item.name)}</strong>${context ? `<small>${esc(context)}</small>` : ""}${previewStatus ? `<em>${previewStatus}</em>` : ""}</span><b>${selected ? "已选择" : "选择"}</b></button>`;
  }

  async function searchCharacters(query) {
    try {
      const path = state.currentRun
        ? `/production-runs/${encodeURIComponent(state.currentRun.run_id)}/resources/characters?q=${encodeURIComponent(query)}&limit=60`
        : `/resources/characters?q=${encodeURIComponent(query)}&limit=60`;
      const result = await api(path);
      const rows = (result.items || []).filter((item) => item.role !== "teacher"
        && item.source !== "halocue_teacher"
        && item.identifier !== state.currentDraft?.cast?.teacher_identity?.character_id);
      state.characterCatalog = rows;
      state.characterCatalogRunId = state.currentRun?.run_id || null;
      const custom = rows.filter(isCustomCharacterResource);
      const official = rows.filter((item) => !isCustomCharacterResource(item));
      $("#characterResults").innerHTML = rows.length ? [
        custom.length ? `<section class="character-result-group"><header><span>自定义骨骼</span><b>${custom.length}</b></header>${custom.map(characterPickerRow).join("")}</section>` : "",
        official.length ? `<section class="character-result-group"><header><span>官方骨骼</span><b>${official.length}</b></header>${official.map(characterPickerRow).join("")}</section>` : "",
      ].join("") : '<p class="empty">没有匹配的角色；试试角色名称或社团。</p>';
      $$("[data-character-id]").forEach((button) => button.addEventListener("click", () => saveMapping({
        kind: "portrait", id: button.dataset.characterId, name: button.dataset.characterName,
        ...(state.characterCatalog.find((item) => item.identifier === button.dataset.characterId) || {})
      })));
    } catch (error) { $("#mappingDialogStatus").textContent = error.message; }
  }

  function saveLocalCharacterAlias() {
    if (!state.mappingAliasTarget || !state.selectedSpeaker) return;
    try {
      const aliases = JSON.parse(localStorage.getItem("halocue.characterAliases") || "{}");
      aliases[state.selectedSpeaker] = {
        identifier: state.mappingAliasTarget.identifier || state.mappingAliasTarget.id,
        name: state.mappingAliasTarget.name || state.mappingAliasTarget.identifier || state.mappingAliasTarget.id,
        saved_at: new Date().toISOString(),
      };
      localStorage.setItem("halocue.characterAliases", JSON.stringify(aliases));
      $("#saveMappingAlias").textContent = "别名已保存";
      $("#mappingDialogStatus").textContent = "本机搜索别名已保存；它不会改写任务冻结资源或剧本。";
    } catch (_) {
      $("#mappingDialogStatus").textContent = "浏览器未允许保存本机别名。";
    }
  }

  async function saveMapping(mapping, context = null) {
    if (!state.selectedSpeaker || !state.currentDraft || state.busy) return;
    const speaker = context?.speaker || state.selectedSpeaker;
    const runId = context?.runId || state.currentRun.run_id;
    const version = context?.draftVersion ?? state.currentDraft.draft_version;
    setBusy(true);
    try {
      const result = await api(`/production-runs/${encodeURIComponent(runId)}/cast-bindings`, {
        method: "POST", body: JSON.stringify({ speaker, mapping, expected_draft_version: version })
      });
      adoptRunResult(result);
      state.characterCatalogRunId = null;
      await loadTaskPreflight();
      $("#mappingDialog").close(); updateShell(); renderMapping(); renderGeneration(); toast(`已更新 ${speaker} 的映射`);
    } catch (error) {
      $("#mappingDialogStatus").textContent = error.code === "revision_conflict"
        ? "草稿已更新，请关闭后重新确认映射。" : error.message || "保存失败，请稍后重试。";
      await handleError(error);
    } finally { setBusy(false); }
  }

  const terminalJobStates = new Set([
    "succeeded", "failed", "interrupted", "paused", "cancelled", "superseded",
  ]);

  const jobStateLabels = {
    queued: "等待执行",
    running: "正在执行",
    pausing: "正在暂停",
    paused: "已暂停",
    cancelling: "正在结束",
    cancelled: "已结束",
    succeeded: "已完成",
    failed: "失败",
    interrupted: "服务重启中断",
    superseded: "旧结果已丢弃",
  };

  function jobIsActive(job) {
    return !!job && !terminalJobStates.has(job.state);
  }

  function directionJobProfile(job = state.currentJob) {
    const profile = job?.direction_profile_snapshot?.id || job?.direction_profile;
    return profile === "conservative" ? "conservative" : "standard";
  }

  function canResumeSelectedDirection() {
    return state.currentJob?.kind === "direction_generation"
      && state.currentJob.run_id === state.currentRun?.run_id
      && state.currentJob.resumable
      && directionJobProfile() === state.directionProfile;
  }

  const profileNames = { conservative: "简洁", standard: "标准" };

  function syncProfilePickers() {
    for (const id of ["sourceDirectionProfile", "directionProfile"]) {
      const select = $("#" + id);
      const root = $("#" + id + "Control");
      if (!select || !root) continue;
      const source = id === "sourceDirectionProfile";
      const locked = select.disabled;
      root.dataset.selected = select.value;
      root.querySelectorAll('input[type="radio"]').forEach((radio) => {
        const option = [...select.options].find((item) => item.value === radio.value);
        radio.checked = radio.value === select.value;
        radio.disabled = locked || !option || option.disabled;
        radio.closest(".profile-choice").title = option?.disabled ? "当前制作后端不支持此策略" : "";
      });
      const badge = $("#" + id + "Lock");
      const active = !source && state.currentJob?.kind === "direction_generation" && jobIsActive(state.currentJob);
      badge.hidden = !locked;
      badge.textContent = active ? "本次策略已锁定" : state.currentRun?.state === "compiling" && !source ? "编译中 · 暂不可切换" : "处理中 · 暂不可切换";
      const current = state.draftDirectionProfile?.id;
      const validCurrent = Object.hasOwn(profileNames, current || "");
      const currentName = validCurrent ? profileNames[current] : state.currentRun?.last_direction_generation_id ? "策略记录不可用" : "尚未生成演出";
      const nextName = profileNames[select.value] || "未选择";
      const pendingDifferent = !source && validCurrent && current !== select.value;
      const status = $("#" + id + "Status");
      status.dataset.changed = String(pendingDifferent);
      const row = (label, value) => `<div class="profile-status-row"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
      const content = source
        ? row("新任务默认", nextName) + row("生效时机", "建立任务后首次生成")
        : row("当前草稿来源", currentName) + row(active ? "正在生成" : "下次生成", `${nextName}${pendingDifferent ? " · 尚未应用" : ""}`);
      if (status.innerHTML !== content) status.innerHTML = content;
      const note = root.querySelector(".profile-boundary-note");
      const message = source ? "选择新任务的默认演出风格，不会跳过场景确认和审查。"
        : active ? "本次任务使用已锁定策略；完成后仍需逐卡审查。"
          : pendingDifferent ? "仅影响下次生成。点击“重新生成”并确认后才会应用，现有草稿不变。"
            : "仅影响下次生成，不会立即改写当前草稿。";
      if (note.textContent !== message) note.textContent = message;
    }
  }

  function setupProfilePickers() {
    $$('[data-profile-picker]').forEach((root) => {
      const select = $("#" + root.dataset.profilePicker);
      root.addEventListener("keydown", () => { root.dataset.inputMethod = "keyboard"; });
      root.addEventListener("pointerdown", () => { root.dataset.inputMethod = "pointer"; });
      root.querySelectorAll('input[type="radio"]').forEach((radio) => radio.addEventListener("change", () => {
        if (select.disabled || radio.disabled) { syncProfilePickers(); return; }
        select.value = radio.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        syncProfilePickers();
      }));
      select.addEventListener("change", syncProfilePickers);
    });
    syncProfilePickers();
  }

  function syncWorkflowControlStates() {
    const snapshot = workflowSnapshot();
    const mapping = $("#mappingContinue");
    if (mapping) {
      mapping.disabled = state.busy || !state.currentRun || snapshot.missingMappings > 0;
    }

    const directionActive = state.currentJob?.kind === "direction_generation"
      && jobIsActive(state.currentJob);
    const generation = $("#generateOrReview");
    if (generation) {
      const needsDirectionGeneration = state.currentRun?.source_summary?.generation_mode === "ai_direction";
      generation.disabled = state.busy || !state.currentRun || !state.currentDraft
        || (needsDirectionGeneration && !!state.currentDraft?.counts?.blocking_errors)
        || !!state.jobActionPending
        || (needsDirectionGeneration && !!$("#directionProfile").selectedOptions[0]?.disabled)
        || (needsDirectionGeneration && directionActive)
        || state.currentRun?.state === "compiling";
    }
    $$('#layoutModeFieldset input[name="layoutMode"]').forEach((input) => {
      input.disabled = state.busy || directionActive;
    });
    $("#sourceDirectionProfile").disabled = state.busy;
    $("#directionProfile").disabled = state.busy || directionActive
      || !!state.jobActionPending || state.currentRun?.state === "compiling";
    $("#regenerateDirection").disabled = generation?.disabled !== false;
    syncProfilePickers();

    const compiling = state.currentRun?.state === "compiling"
      || (state.currentJob?.kind === "compile" && jobIsActive(state.currentJob));
    const compiled = ["compiled", "installed"].includes(state.currentRun?.state);
    const compile = $("#compileButton");
    if (compile) {
      compile.disabled = state.busy || !state.gates?.compile?.passed || compiling || compiled;
      compile.textContent = compiling ? "正在编译" : compiled ? "已编译（可安装）" : "编译 AA 工程";
    }
  }

  function generationMetrics(job) {
    const result = job?.result || {};
    if (result.metrics && typeof result.metrics === "object") return result.metrics;
    if (result.agent?.metrics && typeof result.agent.metrics === "object") return result.agent.metrics;
    const summary = [...(job?.events || [])].reverse().find((event) => event.kind === "generation_summary");
    return summary?.metrics || {};
  }

  function numberLabel(value) {
    if (value === null || value === undefined || value === "") return "尚未上报";
    return Number.isFinite(Number(value)) ? Number(value).toLocaleString("zh-CN") : "尚未上报";
  }

  function cacheLabel(metrics) {
    if (metrics.cache_reported !== true) return "服务未上报";
    const parts = [];
    if (metrics.cache_hit_rate !== null && metrics.cache_hit_rate !== undefined && Number.isFinite(Number(metrics.cache_hit_rate))) {
      parts.push(`${Math.round(Number(metrics.cache_hit_rate) * 100)}%`);
    } else {
      parts.push("命中率未上报");
    }
    if (metrics.cache_read_tokens !== null && metrics.cache_read_tokens !== undefined) {
      parts.push(`读取 ${numberLabel(metrics.cache_read_tokens)}`);
    }
    if (metrics.cache_write_tokens !== null && metrics.cache_write_tokens !== undefined) {
      parts.push(`写入 ${numberLabel(metrics.cache_write_tokens)}`);
    }
    return parts.join(" · ");
  }

  function warmCacheLabel(metrics) {
    if (metrics.warm_cache_hit_rate === null || metrics.warm_cache_hit_rate === undefined || !Number.isFinite(Number(metrics.warm_cache_hit_rate))) {
      return "供应商未上报";
    }
    const prefix = metrics.stable_prefix_consistent === false ? "前缀变化 · " : "";
    return `${prefix}${Math.round(Number(metrics.warm_cache_hit_rate) * 100)}% · 命中 ${numberLabel(metrics.warm_cache_read_tokens)} · 未缓存 ${numberLabel(metrics.warm_uncached_input_tokens)}`;
  }

  function failedCostLabel(metrics) {
    if (metrics.failed_request_count === null || metrics.failed_request_count === undefined) return "尚未上报";
    const tokens = metrics.failed_request_input_tokens === null || metrics.failed_request_input_tokens === undefined
      ? "Token 未上报"
      : `输入 ${numberLabel(metrics.failed_request_input_tokens)} · 输出 ${numberLabel(metrics.failed_request_output_tokens)}`;
    return `${numberLabel(metrics.failed_request_count)} 次 · ${tokens}`;
  }

  function unitCostLabel(metrics) {
    const value = metrics.uncached_input_tokens_per_completed_target;
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "供应商未上报";
    return `${numberLabel(Math.round(Number(value) * 10) / 10)} 未缓存输入 / 条`;
  }

  function promptOptimizationLabel(metrics) {
    const optimization = metrics.prompt_optimization;
    if (!optimization) return "尚未上报";
    const reduction = Number(optimization.resource_prompt_reduction);
    const resource = Number.isFinite(reduction)
      ? `资源提示减少 ${Math.max(0, Math.round(reduction * 100))}%`
      : "资源提示已裁剪";
    const source = optimization.source_context_strategy === "window"
      ? "剧本按窗口发送"
      : "全文前缀";
    return `${resource} · ${source} · ${numberLabel(optimization.background_count)} 背景 / ${numberLabel(optimization.sound_count)} 音效`;
  }

  function jobLogRows(job, metrics) {
    const rows = (job?.events || []).map((event) => {
      const detail = event.detail || event.message || event.reason || event.state || event.kind || "状态更新";
      const context = [
        event.chunk_current && event.chunk_total ? `块 ${event.chunk_current}/${event.chunk_total}` : "",
        event.request_index ? `请求 ${event.request_index}` : "",
        event.retry_count ? `重试 ${event.retry_count}` : "",
        event.subdivision_count ? `细分 ${event.subdivision_count}` : "",
      ].filter(Boolean).join(" · ");
      const time = event.at ? new Date(event.at).toLocaleTimeString("zh-CN", { hour12: false }) : "运行中";
      return `<div class="job-log-row ${event.level === "error" ? "error" : ""}"><time>${esc(time)}</time><p><strong>${esc(detail)}</strong>${context ? `<br>${esc(context)}` : ""}</p></div>`;
    });
    (metrics.request_records || []).forEach((record, index) => {
      const request = record.agent_request_index || record.request_index || index + 1;
      const failed = record.outcome === "failed";
      const usage = [
        failed ? `失败 ${record.error_code || "unknown"}` : record.outcome === "succeeded" ? "成功" : "",
        record.input_tokens != null ? `输入 ${numberLabel(record.input_tokens)}` : "",
        record.output_tokens != null ? `输出 ${numberLabel(record.output_tokens)}` : "",
        record.cache_read_tokens != null ? `缓存 ${numberLabel(record.cache_read_tokens)}` : "",
        record.finish_reason ? `结束 ${record.finish_reason}` : "",
      ].filter(Boolean).join(" · ");
      rows.push(`<div class="job-log-row ${failed ? "error" : ""}"><time>请求 ${esc(request)}</time><p><strong>${esc(record.chunk_id || record.scene_id || "模型调用")}</strong>${usage ? `<br>${esc(usage)}` : ""}</p></div>`);
    });
    if (job?.error) {
      const details = job.error.details && Object.keys(job.error.details).length
        ? `\n${JSON.stringify(job.error.details, null, 2)}` : "";
      rows.push(`<div class="job-log-row error"><time>错误</time><p><strong>${esc(job.error.code || "job_failed")} · ${esc(job.error.message || "任务失败")}</strong>${job.error.traceback || details ? `<pre class="job-log-error">${esc((job.error.traceback || "") + details)}</pre>` : ""}</p></div>`);
    }
    return rows;
  }

  function jobProgressDisplay(job) {
    if (job.state === "succeeded") return { percent: 100, indeterminate: false };
    const progress = job.progress || {};
    const raw = Number(progress.percent);
    // Annotation current is the chunk being worked on, not a completed count.
    const currentChunk = job.kind === "direction_generation" && progress.phase === "annotating";
    const measured = !currentChunk && progress.percent != null && Number.isFinite(raw) && raw >= 0 && raw < 100;
    return { percent: measured ? raw : 0, indeterminate: jobIsActive(job) && (!progress.total || !measured) };
  }

  function renderGenerationJob() {
    const panel = $("#generationJob");
    const job = state.currentJob;
    const visible = job?.kind === "direction_generation" && job.run_id === state.currentRun?.run_id;
    panel.classList.toggle("hidden", !visible);
    if (!visible) return;
    const progress = job.progress || {};
    const { percent, indeterminate } = jobProgressDisplay(job);
    const progressNode = $("#generationProgress");
    progressNode.classList.toggle("indeterminate", indeterminate);
    if (indeterminate) progressNode.removeAttribute("aria-valuenow");
    else progressNode.setAttribute("aria-valuenow", String(Math.round(percent)));
    progressNode.setAttribute("aria-valuetext", indeterminate ? "正在处理，完成比例尚未确定" : `${Math.round(percent)}%`);
    $("#generationProgressBar").style.width = `${percent}%`;
    panel.dataset.state = job.state;
    $("#generationJobState").textContent = jobStateLabels[job.state] || job.state;
    const titles = {
      queued: "演出任务正在排队",
      running: "AI 正在安排演出",
      pausing: "正在保存检查点并暂停",
      paused: "演出任务已经暂停",
      cancelling: "正在结束演出任务",
      cancelled: "演出任务已经结束",
      succeeded: "演出草稿已经生成",
      failed: "演出生成失败",
      interrupted: "演出任务被服务重启中断",
      superseded: "旧演出结果已丢弃",
    };
    $("#generationJobTitle").textContent = titles[job.state] || job.label || "演出任务";
    const count = progress.total
      ? ` · 当前场景块 ${numberLabel(progress.current)} / ${numberLabel(progress.total)}${job.state === "succeeded" ? " · 已完成" : "（非完成比例）"}`
      : "";
    $("#generationJobDetail").textContent = `${progress.detail || job.next_action?.detail || "等待后台状态更新。"}${count}`;

    const metrics = generationMetrics(job);
    $("#generationMetrics").innerHTML = [
      ["模型请求", numberLabel(metrics.requests)],
      ["恢复动作", `${numberLabel(metrics.retries)} 次重试（传输 ${numberLabel(metrics.transport_retries)}） · ${numberLabel(metrics.subdivisions)} 次细分`],
      ["Token", `${numberLabel(metrics.input_tokens)} 输入 · ${numberLabel(metrics.output_tokens)} 输出`],
      ["提示缓存", cacheLabel(metrics)],
      ["暖缓存", warmCacheLabel(metrics)],
      ["失败消耗", failedCostLabel(metrics)],
      ["单位产出", unitCostLabel(metrics)],
      ["输入裁剪", promptOptimizationLabel(metrics)],
    ].map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join("");

    const pending = state.jobActionPending;
    $("#pauseGeneration").hidden = !job.can_pause;
    $("#pauseGeneration").disabled = state.busy || !!pending || !job.can_pause;
    $("#resumeGeneration").hidden = !canResumeSelectedDirection();
    $("#resumeGeneration").disabled = state.busy || !!pending || !canResumeSelectedDirection();
    $("#cancelGeneration").hidden = !job.can_cancel;
    $("#cancelGeneration").disabled = state.busy || !!pending || !job.can_cancel;
    const rows = jobLogRows(job, metrics);
    $("#generationLogCount").textContent = String(rows.length);
    $("#generationLog").innerHTML = rows.join("") || '<p class="empty">等待第一条运行记录。</p>';
  }

  function renderScenePlan() {
    const target = $("#scenePlan");
    if (!target || !state.currentDraft) return;
    const scenes = draftSceneGroups();
    const cards = state.currentDraft.cards || [];
    const requestCount = cards.filter((card) => ["background_request", "sound_request"].includes(card.kind)).length;
    target.dataset.materialRequests = String(requestCount);
    target.innerHTML = scenes.length ? scenes.map((scene) => {
      const aiScene = aiSceneForDraft(scene);
      const backgroundKey = scene.background?.current?.arg || "";
      const backgroundLabel = backgroundKey
        ? resourceDisplayName({ key: backgroundKey }, { kind: "backgrounds", currentBackgroundKey: backgroundKey, currentBackgroundLabel: sceneTitleLabel(scene.title) })
        : (aiScene?.background_need || "尚未设置");
      const preview = backgroundKey && backgroundKey !== "BG_Black"
        ? previewImage("backgrounds", backgroundKey, backgroundKey, "scene-plan-thumb-image", null)
        : `<span class="scene-plan-thumb-empty">${backgroundKey === "BG_Black" ? "黑屏" : "缺背景"}</span>`;
      const pending = scene.cards.filter((card) => card.review_state === "pending").length;
      const dialogueCount = scene.cards.filter((card) => card.kind === "line").length;
      const requests = scene.cards.filter((card) => ["background_request", "sound_request"].includes(card.kind));
      const evidence = scene.evidence.length ? scene.evidence.map((line) => `<li>${esc(line)}</li>`).join("") : "<li>本场景没有台词证据。</li>";
      const reason = aiScene?.background_reason || aiScene?.reason || (scene.background ? "当前背景来自冻结草稿，可继续更换或保留。" : "当前草稿没有背景卡，需要人工选择素材。 ");
      const sceneId = scene.card?.card_id || scene.cards[0]?.card_id || "";
      return `<article class="scene-plan-row scene-plan-card ${scene.background?.current?.arg === "BG_Black" ? "ready" : "background-unverified"}">
        <div class="scene-plan-card-heading"><span class="scene-plan-number">${esc(String(scene.index + 1).padStart(2, "0"))}</span><div><small>第 ${esc(scene.firstLine)}–${esc(scene.lastLine)} 行</small><strong>${esc(scene.title)}</strong></div><b>${scene.background ? "当前采用" : "待补充"}</b></div>
        <details class="scene-plan-evidence"><summary>原文证据 · ${scene.evidence.length} 条</summary><ul>${evidence}</ul></details>
        <div class="scene-plan-background-block"><div class="scene-plan-thumb">${preview}</div><div><small>背景</small><strong>${esc(backgroundLabel)}</strong><p>${esc(reason)}</p>${sceneBackgroundAvailability(backgroundKey)}<em>人物 / 旁白：${esc(scene.speakers.join("、") || "无台词")} · ${dialogueCount} 段台词 · ${scene.cards.length} 张卡片${pending ? ` · ${pending} 张待审` : " · 已审"}</em>${backgroundKey ? `<details class="scene-plan-evidence scene-plan-resource-details"><summary>素材信息</summary><ul><li>资源标识：${esc(backgroundKey)}</li></ul></details>` : ""}</div></div>
        ${requests.length ? `<section class="scene-plan-gap"><small>素材缺口</small>${requests.map((request) => `<p>${esc(request.current?.description || request.current?.query || request.raw || request.kind)}</p>`).join("")}</section>` : ""}
        <footer><button type="button" class="primary" data-scene-plan-official="${esc(sceneId)}">${scene.background ? "更换AA / 任务背景" : "查找AA 背景"}</button><button type="button" data-scene-plan-prompt="${esc(sceneId)}">生成生图提示词</button><button type="button" data-scene-plan-generated="${esc(sceneId)}">导入生成结果</button><button type="button" data-scene-plan-history="${esc(sceneId)}">从历史项目导入</button><button type="button" data-scene-plan-import="${esc(sceneId)}">添加自定义背景</button><button type="button" data-scene-plan-workbench="${esc(sceneId)}">打开素材工作台</button><button type="button" data-scene-plan-card="${esc(sceneId)}">打开场景审查</button></footer>
      </article>`;
    }).join("") : '<p class="empty">草稿中还没有可制作的场景。</p>';
    updateSceneBackgroundSummary(target);
    const sceneById = (id) => scenes.find((scene) => (scene.card?.card_id || scene.cards[0]?.card_id) === id);
    $$('[data-scene-plan-official]').forEach((button) => button.addEventListener("click", () => {
      const scene = sceneById(button.dataset.scenePlanOfficial); if (!scene?.card) return;
      chooseResource("backgrounds", "场景背景", (item) => insertSceneBackground(scene.card, item), {
        source: "snapshot", eyebrow: "AA 与本任务背景", title: `为“${scene.title}”选择背景`, status: "选择后建立或替换当前场景的 @bg 卡，不改写剧本。", selectionNote: "将采用此背景。", actionLabel: "采用此结果",
      });
    }));
    $$('[data-scene-plan-history]').forEach((button) => button.addEventListener("click", () => {
      const scene = sceneById(button.dataset.scenePlanHistory); if (scene?.card) chooseSceneLibraryBackground(scene.card);
    }));
    $$('[data-scene-plan-prompt]').forEach((button) => button.addEventListener("click", () => {
      const scene = sceneById(button.dataset.scenePlanPrompt); if (scene) openBackgroundPrompt(scene);
    }));
    $$('[data-scene-plan-generated]').forEach((button) => button.addEventListener("click", () => {
      const scene = sceneById(button.dataset.scenePlanGenerated); if (scene) openBackgroundPrompt(scene, { importImmediately: true });
    }));
    $$('[data-scene-plan-workbench]').forEach((button) => button.addEventListener("click", () => {
      const scene = sceneById(button.dataset.scenePlanWorkbench); if (scene) openSceneAssetWorkbench(scene);
    }));
    $$('[data-scene-plan-import]').forEach((button) => button.addEventListener("click", () => {
      const scene = sceneById(button.dataset.scenePlanImport); if (scene?.card) openSceneBackgroundImport(scene.card);
    }));
    $$('[data-scene-plan-card]').forEach((button) => button.addEventListener("click", () => {
      const scene = sceneById(button.dataset.scenePlanCard); if (!scene) return;
      state.selectedCard = scene.card || scene.cards[0] || null;
      showStage("review", { force: true });
    }));
  }

  function renderGeneration() {
    if (!state.currentRun || !state.currentDraft) return;
    const mode = state.currentRun.source_summary?.generation_mode || "format_only";
    $("#directionProfileControl").classList.toggle("hidden", mode !== "ai_direction");
    $("#directionProfile").value = state.directionProfile;
    setLayoutMode(state.currentRun.source_summary?.layout_mode || savedLayoutMode());
    $("#layoutModeFieldset")?.classList.toggle("hidden", mode !== "ai_direction");
    $("#generationModeBadge").textContent = mode === "ai_direction" ? "AI 安排演出" : "仅转换格式";
    $("#generationDescription").textContent = mode === "ai_direction" ? "角色映射完成后，后台模型会在冻结草稿副本上安排演出。" : "格式草稿已经建立，下一步是处理素材请求并逐卡审查。";
    const missingMappings = workflowSnapshot().missingMappings;
    const cards = [
      ["角色映射", missingMappings ? `${missingMappings} 位待确认` : "已通过", missingMappings === 0],
      ["演出草稿", `${state.currentDraft.counts?.total || 0} 张卡片`, true],
      ["审查门", state.currentDraft.review_ready ? "已通过" : `${state.currentDraft.counts?.pending || 0} 张待审`, !!state.currentDraft.review_ready],
    ];
    $("#generationGates").innerHTML = cards.map(([label, value, pass]) => `<div class="gate-card ${pass ? "pass" : "block"}"><small>${label}</small><b>${esc(value)}</b><small>${pass ? "可以继续" : "需要处理"}</small></div>`).join("");
    renderScenePlan();
    const action = $("#generateOrReview");
    const hasCompletedDirection = !!state.currentRun.last_direction_generation_id;
    const directionActive = state.currentJob?.kind === "direction_generation"
      && jobIsActive(state.currentJob);
    const resumable = state.currentJob?.kind === "direction_generation" && state.currentJob.resumable;
    $("#regenerateDirection").hidden = mode !== "ai_direction" || !hasCompletedDirection || directionActive;
    if (mode === "ai_direction" && directionActive) {
      $("#generationActionTitle").textContent = "AI 正在安排演出";
      $("#generationActionCopy").textContent = "可以在下方查看实时进度、请求记录，或暂停和结束任务。";
      action.textContent = "生成中";
    } else if (mode === "ai_direction" && resumable && !canResumeSelectedDirection()) {
      $("#generationActionTitle").textContent = "按新策略重新生成";
      $("#generationActionCopy").textContent = "旧任务及其检查点保留，新策略将创建独立的生成任务。";
      action.textContent = "按新策略重新生成";
    } else if (mode === "ai_direction" && resumable) {
      $("#generationActionTitle").textContent = "继续未完成的演出任务";
      $("#generationActionCopy").textContent = "继续时会复用同一检查点，只处理尚未完成的分块。";
      action.textContent = "继续生成";
    } else if (mode === "ai_direction" && !hasCompletedDirection) {
      $("#generationActionTitle").textContent = "运行 AI 安排演出";
      $("#generationActionCopy").textContent = "后台任务会保留检查点，完成后回到逐卡审查。";
      action.textContent = "开始安排演出";
    } else {
      $("#generationActionTitle").textContent = "打开草稿审查";
      $("#generationActionCopy").textContent = "逐卡处理未登记背景、音效和待审内容。";
      action.textContent = "进入审查";
    }
    syncWorkflowControlStates();
    renderGenerationJob();
  }

  async function startGeneration({ restart = false } = {}) {
    if (!state.currentRun || !state.currentDraft || state.busy || state.jobActionPending) return;
    const mode = state.currentRun.source_summary?.generation_mode;
    if (mode !== "ai_direction") { showStage("review", { force: true }); return; }
    if (state.currentJob?.kind === "direction_generation" && jobIsActive(state.currentJob)) return;
    if (!restart && canResumeSelectedDirection()) {
      await resumeGenerationJob();
      return;
    }
    const previousDirection = state.currentJob?.kind === "direction_generation"
      && state.currentJob.run_id === state.currentRun.run_id;
    if (state.currentRun.last_direction_generation_id) {
      if (!restart && (!previousDirection || !state.currentJob.resumable)) {
        showStage("review", { force: true });
        return;
      }
    }
    const runId = state.currentRun.run_id;
    const draftVersion = state.currentDraft.draft_version;
    const profile = state.directionProfile;
    if (previousDirection || restart) {
      const profileLabel = profile === "conservative" ? "简洁（保守）" : "标准（原版）";
      if (!await askConfirmation({
        title: "重新生成演出草稿？",
        body: `将按${profileLabel}基于当前草稿新建生成任务，保留已有指令，不复用旧检查点。完成后需要重新审查，可能产生新的模型费用。`,
        confirmLabel: "重新生成",
      })) return;
      if (state.currentRun?.run_id !== runId || state.currentDraft?.draft_version !== draftVersion
        || state.directionProfile !== profile || state.busy || state.jobActionPending
        || jobIsActive(state.currentJob)) {
        toast("当前任务已变化，请检查后重新发起。", "warning");
        return;
      }
    }
    setBusy(true);
    try {
      const result = await api(`/production-runs/${state.currentRun.run_id}/direction-generation`, {
        method: "POST", body: JSON.stringify({
          expected_draft_version: state.currentDraft.draft_version,
          story_type: "auto",
          layout_mode: selectedLayoutMode(),
          direction_profile: state.directionProfile,
        })
      });
      state.currentJob = result.job;
      state.currentRun.source_summary.layout_mode = result.layout_mode || selectedLayoutMode();
      rememberLayoutMode();
      await refreshCurrentRun();
      showStage("generation", { force: true });
      pollJob(result.job.job_id, "演出安排").catch(handleError);
    } catch (error) { handleError(error); } finally { setBusy(false); renderGeneration(); }
  }

  async function pauseGenerationJob() {
    const job = state.currentJob;
    if (!job?.can_pause || state.jobActionPending) return;
    state.jobActionPending = "pause";
    renderGenerationJob();
    try {
      const result = await api(`/jobs/${encodeURIComponent(job.job_id)}?action=pause`, { method: "POST", body: "{}" });
      state.currentJob = result.job;
      toast("已请求暂停；正在中止当前模型连接并保存检查点。", "warning");
    } catch (error) {
      handleError(error);
    } finally {
      state.jobActionPending = null;
      renderGeneration();
    }
  }

  async function resumeGenerationJob() {
    const job = state.currentJob;
    if (!canResumeSelectedDirection() || state.jobActionPending) return;
    state.jobActionPending = "resume";
    renderGenerationJob();
    try {
      const result = await api(`/jobs/${encodeURIComponent(job.job_id)}?action=resume`, { method: "POST", body: "{}" });
      state.currentJob = result.job;
      await refreshCurrentRun();
      showStage("generation", { force: true });
      pollJob(result.job.job_id, "演出安排").catch(handleError);
      toast("已从检查点继续生成。", "normal");
    } catch (error) {
      handleError(error);
    } finally {
      state.jobActionPending = null;
      renderGeneration();
    }
  }

  async function cancelGenerationJob() {
    const job = state.currentJob;
    if (!job?.can_cancel || state.jobActionPending) return;
    const confirmed = await askConfirmation({
      title: "结束当前演出任务？",
      body: "未完成内容不会写入草稿；已经完成的分块检查点会保留，之后仍可继续。",
      confirmLabel: "结束任务",
      danger: true,
    });
    if (!confirmed) return;
    state.jobActionPending = "cancel";
    renderGenerationJob();
    try {
      const result = await api(`/jobs/${encodeURIComponent(job.job_id)}?action=cancel`, { method: "POST", body: "{}" });
      state.currentJob = result.job;
      toast("已请求结束；迟到的模型结果不会覆盖草稿。", "warning");
    } catch (error) {
      handleError(error);
    } finally {
      state.jobActionPending = null;
      renderGeneration();
    }
  }

  function cardStatus(card) {
    if (card.issues?.some((issue) => issue.severity === "error")) return "blocking";
    if (card.review_state === "pending") return "pending";
    return "approved";
  }

  function renderReviewWorkflow(pending, canCompile) {
    let active = 0;
    let message = "先选择一张待处理卡片";
    if (state.selectedCard) {
      const status = cardStatus(state.selectedCard);
      active = status === "blocking" ? 1 : state.selectedCard.review_state === "pending" ? 2 : 0;
      message = status === "blocking"
        ? "当前卡片有问题，先完成修改或素材处理"
        : state.selectedCard.review_state === "pending"
          ? "当前卡片可以确认，完成后继续下一张"
          : "这张卡片已经审查，可以选择下一张";
    }
    if (pending === 0 && canCompile) {
      active = 3;
      message = "所有卡片均已通过，可以编译 AA 工程";
    }
    $("#reviewFlowState").textContent = message;
    $$("[data-review-step]").forEach((item) => {
      const index = Number(item.dataset.reviewStep);
      item.classList.toggle("active", index === active);
      item.classList.toggle("done", index < active || (index === 2 && pending === 0));
    });
  }

  const cardKindLabels = { line: "对白", dir: "演出指令", scene: "场景", title: "章节标题", unknown: "未识别内容", background_request: "背景请求", sound_request: "音效请求" };
  const directiveLabels = { bg: "切换背景", place: "地点", camera_hold: "保持镜头", wait: "停顿", enter: "角色入场", exit: "角色退场", move: "角色移动", se: "音效", bgm: "背景音乐", shot: "镜头", trans: "转场", bgfx: "背景效果", fx: "画面效果" };
  function cardKindLabel(card) { return cardKindLabels[card?.kind] || "文本内容"; }
  function cardHeadline(card) {
    const current = card.current || {};
    if (card.kind === "line") return `${current.who || "未映射"}：${current.text || ""}`;
    if (card.kind === "dir") return `${directiveLabels[current.cmd] || current.cmd || "演出指令"} · ${current.arg || "无参数"}`;
    return current.title || current.text || current.description || current.query || card.raw || cardKindLabel(card);
  }

  function selectedCardSummary(card) {
    if (!card) return "尚未选择卡片";
    const detail = cardHeadline(card);
    return `第 ${card.line_no || "-"} 张 · ${detail}`;
  }

  function renderSelectedCardToolbar() {
    const card = state.selectedCard;
    const toolbar = $("#selectedCardToolbar");
    if (toolbar) toolbar.hidden = !card;
    const cards = state.currentDraft?.cards || [];
    const index = card ? cards.findIndex((item) => item.card_id === card.card_id) : -1;
    const label = $("#selectedCardToolbarLabel");
    if (label) label.textContent = selectedCardSummary(card);
    const setDisabled = (selector, disabled) => { const button = $(selector); if (button) button.disabled = disabled; };
    setDisabled("#toolbarEditCard", !card);
    setDisabled("#toolbarInsertLine", !card);
    setDisabled("#toolbarInsertDirection", !card);
    setDisabled("#toolbarMoveEarlier", !card || index <= 0);
    setDisabled("#toolbarMoveLater", !card || index < 0 || index >= cards.length - 1);
    setDisabled("#toolbarDeleteCard", !card || card.kind === "background_request");
    setDisabled("#toolbarBindCharacter", !card || card.kind !== "line" || !String(card.current?.who || "").trim());
  }

  function backgroundTimelineSource(card) {
    const key = String(card?.current?.arg || "");
    if (key === "BG_Black") return "黑屏";
    return key.startsWith("BG_CS_") ? "AA CG 背景" : "AA / 任务背景";
  }

  function renderBackgroundTimeline() {
    const track = $("#backgroundTimelineTrack");
    const summary = $("#backgroundTimelineSummary");
    if (!track || !summary) return;
    const cards = (state.currentDraft?.cards || []).filter((card) => card.kind === "dir" && String(card.current?.cmd || "").toLowerCase() === "bg");
    summary.textContent = cards.length ? `共 ${cards.length} 次切换 · 点击节点跳到对应卡片` : "当前草稿没有显式背景切换";
    if (!cards.length) {
      track.innerHTML = '<p class="empty">没有找到 @bg 卡；可在场景卡中选择AA 背景、历史素材或黑屏。</p>';
      return;
    }
    track.innerHTML = cards.map((card, index) => {
      const key = String(card.current?.arg || "未命名背景");
      const preview = key === "BG_Black"
        ? '<span class="background-timeline-placeholder">黑屏</span>'
        : `<img src="${esc(previewResourceUrl("backgrounds", key))}" alt="" loading="lazy" decoding="async"><span class="background-timeline-placeholder" hidden>素材缺失</span>`;
      return `<article class="background-timeline-node ${state.selectedCard?.card_id === card.card_id ? "selected" : ""}" data-background-card-id="${esc(card.card_id)}"><button type="button" class="background-timeline-jump" data-background-jump="${esc(card.card_id)}">${preview}<span class="background-timeline-copy"><strong>${esc(key)}</strong><small>${esc(backgroundTimelineSource(card))} · 第 ${esc(card.line_no || "-")} 张</small></span></button><div class="background-timeline-actions"><button type="button" data-background-replace="${esc(card.card_id)}">更换</button><button type="button" data-background-history="${esc(card.card_id)}">历史素材</button></div></article>${index < cards.length - 1 ? '<span class="background-timeline-arrow" aria-hidden="true">→</span>' : ""}`;
    }).join("");
    track.querySelectorAll("img").forEach((image) => {
      image.addEventListener("error", () => {
        image.hidden = true;
        const placeholder = image.nextElementSibling;
        if (placeholder) placeholder.hidden = false;
        image.closest(".background-timeline-node")?.classList.add("is-missing");
      }, { once: true });
    });
    $$('[data-background-jump]').forEach((button) => button.addEventListener("click", () => {
      selectCard(button.dataset.backgroundJump);
      requestAnimationFrame(() => $("[data-card-id='" + CSS.escape(button.dataset.backgroundJump) + "']")?.scrollIntoView({ behavior: scrollBehavior(), block: "center" }));
    }));
    $$('[data-background-replace]').forEach((button) => button.addEventListener("click", () => {
      const card = cards.find((item) => item.card_id === button.dataset.backgroundReplace);
      if (!card) return;
      chooseResource("backgrounds", "背景", (item) => resolveCard("background-resolution", { action: "select", background_key: item.key }, card), {
        eyebrow: "背景时间线", title: `更换第 ${card.line_no || "-"} 张背景`, status: "选中后直接替换这张 @bg 卡，并保留可审查状态。", selectionNote: "将替换当前背景卡。", actionLabel: "采用此背景",
      });
    }));
    $$('[data-background-history]').forEach((button) => button.addEventListener("click", () => {
      const card = cards.find((item) => item.card_id === button.dataset.backgroundHistory);
      if (card) chooseTimelineLibraryBackground(card);
    }));
  }

  async function chooseTimelineLibraryBackground(card) {
    await chooseResource("backgrounds", "历史背景", async (item) => {
      try {
        const attached = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/library-assets/${encodeURIComponent(item.asset_id)}`, {
          method: "POST", body: JSON.stringify({ expected_draft_version: state.currentDraft.draft_version }),
        });
        applyRun(attached);
        const refreshed = state.currentDraft?.cards?.find((candidate) => candidate.card_id === card.card_id);
        if (refreshed) await resolveCard("background-resolution", { action: "select", background_key: item.key }, refreshed);
      } catch (error) { handleError(error); }
    }, {
      source: "library", eyebrow: "背景时间线", title: "从历史素材库更换背景", status: "素材会先冻结到当前任务，再替换这张背景卡。", selectionNote: "将导入当前任务并替换背景卡。", actionLabel: "导入并使用", emptyText: "历史素材库里还没有背景图片。",
    });
  }

  function syncPreviewIndexToSelectedCard() {
    const selected = state.selectedCard?.card_id;
    const frames = state.performancePreview?.frames || [];
    if (!selected || !frames.length) return;
    const index = frames.findIndex((frame) => frame.card_id === selected);
    if (index >= 0) state.previewIndex = index;
  }

  function persistentPreviewLabel(frame) {
    if (frame.presentation === "cg" || frame.cg) return "CG 空镜段落";
    if (frame.presentation === "request") return "需要处理";
    if (frame.presentation === "direction") return "演出指令";
    if (frame.presentation === "teacher_selection") return "老师回答";
    return "当前台词";
  }

  function renderPersistentPerformancePreview() {
    const target = $("#persistentPerformancePreview");
    const counter = $("#persistentPreviewCounter");
    if (!target || !counter) return;
    const frames = state.performancePreview?.frames || [];
    const frame = frames[state.previewIndex];
    if (!frame) {
      target.className = "persistent-preview-empty";
      target.innerHTML = state.performancePreviewLoading
        ? "<strong>正在读取草稿预览</strong><p>不会修改草稿或调用模型。</p>"
        : state.performancePreviewError
          ? `<strong>无法读取草稿预览</strong><p>${esc(state.performancePreviewError)}</p>`
          : "<strong>选择一张卡片</strong><p>预览会显示当前背景、卡片内容和演出注释。</p>";
      counter.textContent = "— / —";
      $("#reviewPreviewPrevious").disabled = true;
      $("#reviewPreviewNext").disabled = true;
      $("#reviewPreviewPlay").disabled = true;
      return;
    }
    const background = frame.background_key && frame.background_preview_available === true
      ? `<img src="${esc(previewResourceUrl("backgrounds", frame.background_key))}" alt="" loading="lazy" decoding="async">`
      : "";
    const annotations = frame.annotations?.length
      ? `<div class="persistent-preview-annotations">${frame.annotations.map((item) => `<span>${esc(item.kind)}：${esc(item.value)}</span>`).join("")}</div>`
      : "";
    const organization = frame.speaker?.role === "teacher" && frame.speaker.organization ? ` · ${frame.speaker.organization}` : "";
    target.className = "persistent-preview-stage";
    target.innerHTML = `${background}<div class="persistent-preview-card"><small>${esc(persistentPreviewLabel(frame))}</small><strong>${esc(frame.title || "未命名卡片")}${esc(organization)}</strong><p>${esc(frame.text || "此卡没有可显示的文本。")}</p>${annotations}</div>`;
    counter.textContent = `${state.previewIndex + 1} / ${frames.length}`;
    $("#reviewPreviewPrevious").disabled = state.previewIndex <= 0;
    $("#reviewPreviewNext").disabled = state.previewIndex >= frames.length - 1;
    $("#reviewPreviewPlay").disabled = frames.length < 2;
    $("#reviewPreviewPlay").textContent = state.previewPlayTimer ? "暂停" : "播放";
  }

  async function ensurePerformancePreview(force = false) {
    if (!state.currentRun || !state.currentDraft) return;
    const key = `${state.currentRun.run_id}:${state.currentDraft.draft_version}`;
    if (!force && state.performancePreviewKey === key && state.performancePreview) {
      syncPreviewIndexToSelectedCard();
      renderPersistentPerformancePreview();
      return;
    }
    if (state.performancePreviewLoading && state.performancePreviewKey === key) return;
    state.performancePreviewLoading = true;
    state.performancePreviewError = "";
    state.performancePreview = null;
    state.performancePreviewKey = key;
    renderPersistentPerformancePreview();
    try {
      state.performancePreview = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/performance-preview`);
      syncPreviewIndexToSelectedCard();
      renderPersistentPerformancePreview();
      if ($("#performancePreviewDialog")?.open) renderPerformancePreview();
    } catch (error) {
      state.performancePreview = null;
      state.performancePreviewError = error.message || "请刷新后重试。";
    } finally {
      state.performancePreviewLoading = false;
      renderPersistentPerformancePreview();
    }
  }

  function stopPersistentPreviewPlayback() {
    if (state.previewPlayTimer) clearInterval(state.previewPlayTimer);
    state.previewPlayTimer = null;
    renderPersistentPerformancePreview();
  }

  function togglePersistentPreviewPlayback() {
    if (state.previewPlayTimer) {
      stopPersistentPreviewPlayback();
      return;
    }
    const frames = state.performancePreview?.frames || [];
    if (frames.length < 2) return;
    state.previewPlayTimer = setInterval(() => {
      if (state.previewIndex >= frames.length - 1) {
        stopPersistentPreviewPlayback();
        return;
      }
      state.previewIndex += 1;
      state.previewCompleted = false;
      renderPersistentPerformancePreview();
      renderPerformancePreview();
      const frame = frames[state.previewIndex];
      if (frame?.card_id) {
        state.selectedCard = state.currentDraft?.cards?.find((card) => card.card_id === frame.card_id) || state.selectedCard;
        renderReview();
      }
    }, 1800);
    renderPersistentPerformancePreview();
  }

  async function loadReviewAssets(force = false) {
    const host = $("#reviewTaskAssets");
    if (!host || !state.currentRun || !state.currentDraft) return;
    const runId = state.currentRun.run_id;
    const key = `${runId}:${state.currentDraft.draft_version}`;
    if (!force && state.reviewAssetsKey === key) return;
    state.reviewAssetsKey = key;
    const request = ++state.reviewAssetsRequest;
    host.setAttribute("aria-busy", "true");
    $("#reviewTaskAssetCount").textContent = "读取中";
    host.innerHTML = '<p class="empty">正在读取本任务登记的素材…</p>';
    try {
      const result = await api(`/production-runs/${encodeURIComponent(runId)}/assets`);
      if (request !== state.reviewAssetsRequest || state.currentRun?.run_id !== runId) return;
      const items = Array.isArray(result.items) ? result.items : [];
      const names = { background: "背景", sound: "音效", character: "角色", cg: "插图" };
      host.innerHTML = items.length
        ? `<ul>${items.map(item => `<li><span>${esc(names[item.kind] || "素材")}</span><div><strong>${esc(item.name || item.key || "未命名素材")}</strong><small>${esc(item.key || "")} · ${item.library_asset_id ? "历史素材副本" : "本任务登记"}</small></div></li>`).join("")}</ul>`
        : '<p class="empty">本任务尚未登记自定义素材。AA 背景和角色不计入这里。</p>';
      $("#reviewTaskAssetCount").textContent = `${items.length} 项`;
    } catch (error) {
      if (request !== state.reviewAssetsRequest || state.currentRun?.run_id !== runId) return;
      // Do not confuse a failed read with an empty library or auto-retry on every card.
      host.innerHTML = `<p class="empty">素材读取失败：${esc(error.message || "请重试")}</p>`;
      $("#reviewTaskAssetCount").textContent = "读取失败";
    } finally {
      if (request === state.reviewAssetsRequest) host.setAttribute("aria-busy", "false");
    }
  }

  // Read-only explanation of the authoritative backend gates. Actions only navigate.
  function reviewReadinessMarkup() {
    const compile = state.gates?.compile;
    const install = state.gates?.install;
    const guidance = {
      draft_missing: ["回到场景制作计划，等待草稿载入。", ""],
      blocking_diagnostics: ["先定位有问题的卡片，处理标出的错误。", "blocking"],
      unresolved_issues: ["逐项核对卡片提示和未落实的素材请求。", "issues"],
      pending_review: ["检查内容后，由你逐张标记已审。", "pending"],
      compile_not_configured: ["检查本机 AA 制作环境；不会在这里自动安装。", "environment"],
      resource_index_not_configured: ["本任务没有可用于编译的冻结资源索引。检查环境后重新准备任务，刷新界面不能替换旧快照。", "environment"],
      resource_index_incomplete: ["本任务冻结资源不完整。检查环境与缺少的素材；当前任务不会自动换用新索引。", "environment"],
      build_missing: ["先完成卡片审查，再点击页面底部的「编译 AA 工程」。", ""],
      build_stale: ["草稿在上次编译后发生变化，需重新审查并编译。", ""],
      aa_workspace_not_configured: ["在制作环境中选择并核对 AA 工作区，安装前还会确认目标。", "environment"],
    };
    const rows = (gate, stage) => {
      if (!gate) return `<li><b>${stage}状态尚未读取</b><p>使用顶部「刷新当前任务」重新读取，不会自动执行编译或安装。</p></li>`;
      if (gate.passed) return `<li class="is-ready"><b>${stage}检查已通过</b><p>通过检查不代表已经执行；仍由你决定是否继续。</p></li>`;
      const blockers = Array.isArray(gate.blockers) ? [...new Set(gate.blockers)] : [];
      if (!blockers.length) return `<li><b>${stage}尚未就绪</b><p>暂未收到具体原因，请刷新当前任务后再检查。</p></li>`;
      return blockers.map(code => {
        const [detail, action] = guidance[code] || ["刷新当前任务后查看详细诊断；不会跳过这项检查。", ""];
        const label = action === "environment" ? "查看制作环境" : action === "pending" ? "定位待审卡片" : "定位问题卡片";
        return `<li><div><b>${esc(blockerLabels[code] || "有一项检查尚未通过")}</b><p>${esc(detail)}</p>${guidance[code] ? "" : `<code>${esc(code)}</code>`}</div>${action ? `<button type="button" class="quiet" data-review-next="${esc(action)}">${label}</button>` : ""}</li>`;
      }).join("");
    };
    const unresolved = [compile, install].reduce((count, gate) => count + (gate?.passed ? 0 : Math.max(1, gate?.blockers?.length || 0)), 0);
    return `<details class="production-release-checklist"><summary>交付前检查 · ${unresolved ? `${unresolved} 项待完成` : "已就绪"}</summary><div class="production-gate-columns"><section><h4>编译之前</h4><ul>${rows(compile, "编译")}</ul></section><section><h4>安装之前</h4><ul>${rows(install, "安装")}</ul></section></div><p class="production-check-boundary">这里只说明缺口和操作位置，不会自动确认卡片、编译、安装或调用模型。</p></details>`;
  }

  function focusReviewNext(action) {
    if (action === "environment") { void openSettingsDialog("workspace"); return; }
    const cards = state.currentDraft?.cards || [];
    const card = action === "pending" ? cards.find(item => item.review_state === "pending")
      : action === "blocking" ? cards.find(item => item.issues?.some(issue => issue.severity === "error"))
        : cards.find(item => item.issues?.length || ["background_request", "sound_request"].includes(item.kind));
    if (!card) { toast("没有找到对应卡片，请刷新任务后查看诊断。", "warning"); return; }
    state.filter = "all";
    $$("[data-filter]").forEach(button => button.classList.toggle("active", button.dataset.filter === "all"));
    selectCard(card.card_id);
    const button = $("#cardList")?.querySelector(`[data-card-id="${CSS.escape(card.card_id)}"]`);
    button?.scrollIntoView({ behavior: scrollBehavior(), block: "center" });
    button?.focus({ preventScroll: true });
  }

  function renderReview() {
    if (!state.currentDraft) return;
    loadReviewAssets();
    const cards = state.currentDraft.cards || [];
    const pending = state.currentDraft.counts?.pending || 0;
    const diagnostics = (state.currentDraft.diagnostics || []).filter((item) => item && typeof item === "object");
    const blocking = diagnostics.filter((item) => item.severity === "error");
    const warnings = diagnostics.filter((item) => item.severity !== "error");
    const requests = cards.filter((card) => ["background_request", "sound_request"].includes(card.kind));
    const priority = (card) => {
      if (card.issues?.some((issue) => issue.severity === "error")) return 0;
      if (card.kind === "background_request" || card.kind === "sound_request") return 1;
      if (card.review_state === "pending") return 2;
      return 3;
    };
    const prioritySummary = $("#reviewPrioritySummary");
    if (prioritySummary) {
      const headline = blocking.length
        ? `先处理 ${blocking.length} 项阻断问题`
        : requests.length
          ? `先处理 ${requests.length} 项素材请求`
          : pending
            ? `按待审顺序确认 ${pending} 张卡片`
            : "审查队列已清空";
      const detail = blocking.length
        ? blocking.slice(0, 3).map((item) => `${item.line_no ? `第 ${item.line_no} 行 · ` : ""}${item.message || item.code || "阻断问题"}`).join("；")
        : requests.length
          ? "素材请求会优先显示在卡片列表顶部，处理后再继续确认台词与演出。"
          : warnings.length
            ? `还有 ${warnings.length} 项提示，确认卡片时请一并核对。`
            : "当前没有诊断项或待处理请求。";
      prioritySummary.className = `review-priority-summary ${blocking.length ? "has-blockers" : requests.length || warnings.length ? "needs-attention" : "ready"}`;
      const checklistOpen = prioritySummary.querySelector(".production-release-checklist")?.open;
      const next = blocking.length ? "blocking" : requests.length || warnings.length ? "issues" : pending ? "pending" : "";
      const nextLabel = next === "pending" ? "开始审查下一张" : "定位待处理卡片";
      prioritySummary.innerHTML = `<div class="production-review-next"><div><small>审查优先级</small><strong>${esc(headline)}</strong><p>${esc(detail)}</p></div>${next ? `<button type="button" class="quiet" data-review-next="${next}">${nextLabel}</button>` : `<span>${state.gates?.compile?.passed ? "可以编译" : "检查交付条件"}</span>`}</div>${reviewReadinessMarkup()}`;
      if (checklistOpen) prioritySummary.querySelector(".production-release-checklist").open = true;
    }
    $("#reviewSummary").textContent = `当前演出草稿 · ${cards.length} 张卡片 · ${pending} 张待审`;
    $("#reviewSummary").setAttribute("aria-live", "polite");
    const visible = cards.filter((card) => {
      const status = cardStatus(card);
      if (state.filter === "all") return true;
      if (state.filter === "direction") return ["line", "dir", "scene"].includes(card.kind);
      return status === state.filter;
    }).sort((left, right) => priority(left) - priority(right) || (left.line_no || 0) - (right.line_no || 0));
    $("#cardList").innerHTML = visible.length ? visible.map((card) => {
      const status = cardStatus(card);
      const current = card.current || {};
      const headline = cardHeadline(card);
      const issue = card.issues?.[0]?.message || (card.review_state === "pending" ? "等待确认" : "已审查");
      const cgBadge = card.cg ? `<b class="cg-badge" title="${esc(card.cg.label)}">CG</b>` : "";
      return `<button class="draft-card ${status} ${card.cg ? "in-cg" : ""} ${state.selectedCard?.card_id === card.card_id ? "selected" : ""}" data-card-id="${esc(card.card_id)}"><span>${esc(String(card.line_no || "").padStart(2, "0"))}</span><span><small>${esc(cardKindLabel(card))} · ${esc(issue)} ${cgBadge}</small><p>${esc(headline)}</p></span><em>${card.review_state === "pending" ? "待审" : ""}</em></button>`;
    }).join("") : '<p class="empty">当前筛选没有卡片。</p>';
    $$("[data-card-id]").forEach((button) => button.addEventListener("click", () => selectCard(button.dataset.cardId)));
    const canCompile = !!state.gates?.compile?.passed;
    const compiled = ["compiled", "installed"].includes(state.currentRun?.state);
    $("#compileGate").textContent = compiled ? "编译完成" : canCompile ? "可以编译" : "等待审查";
    $("#compileBlockers").textContent = compiled
      ? `构建 ${state.currentRun?.last_build_id || "已生成"} 已完成；请在右侧预检安装目标。`
      : canCompile ? "草稿已通过后端编译门，可以生成 AA 工程。" : (state.gates?.compile?.blockers || []).map(code => blockerLabels[code] || code).join("、") || "完成角色映射、处理请求并审查全部卡片。";
    syncWorkflowControlStates();
    renderReviewWorkflow(pending, canCompile);
    renderSelectedCardToolbar();
    renderBackgroundTimeline();
    const installButton = $("#openInstallDialog");
    if (installButton) {
      installButton.hidden = !compiled;
      installButton.classList.toggle("hidden", !compiled);
    }
    if (state.selectedCard) renderInspector();
    else {
      $("#inspectorTitle").textContent = "选择一张卡片";
      $("#inspectorBody").innerHTML = "<p>在左侧选择卡片后，可编辑内容或处理素材请求。</p>";
    }
    ensurePerformancePreview();
  }

  function selectCard(cardId) {
    state.selectedCard = state.currentDraft?.cards?.find((card) => card.card_id === cardId) || null;
    syncPreviewIndexToSelectedCard();
    stopPersistentPreviewPlayback();
    renderReview();
    if (state.selectedCard) renderInspector();
    renderPersistentPerformancePreview();
  }

  function previewResourceUrl(kind, key) {
    if (!state.currentRun || !key) return "";
    return `${API_ROOT}/production-runs/${encodeURIComponent(state.currentRun.run_id)}/resources/${kind}/${encodeURIComponent(key)}/preview`;
  }

  function renderPerformancePreview() {
    const target = $("#performancePreview");
    const status = $("#performancePreviewStatus");
    const preview = state.performancePreview;
    if (!target || !status || !preview) return;
    const frames = preview.frames || [];
    const frame = frames[state.previewIndex];
    if (!frame) {
      target.className = "performance-preview-empty";
      target.innerHTML = "<strong>草稿里还没有可预览的卡片</strong><p>先建立制作任务或插入至少一张卡片。</p>";
      status.textContent = "没有修改草稿。";
      $("#previewPrevious").disabled = true;
      $("#previewNext").disabled = true;
      $("#previewOpenCard").disabled = true;
      return;
    }
    const isCg = frame.presentation === "cg" || !!frame.cg;
    const isTeacherReply = frame.presentation === "teacher_selection";
    const background = frame.background_key && frame.background_preview_available === true
      ? `<img class="preview-stage-image" src="${esc(previewResourceUrl("backgrounds", frame.background_key))}" alt="" loading="lazy" decoding="async">`
      : "";
    const cg = "";
    const annotations = frame.annotations?.length
      ? `<div class="preview-annotations">${frame.annotations.map((item) => `<span>${esc(item.kind)}：${esc(item.value)}</span>`).join("")}</div>`
      : "";
    const statusLabel = frame.review_state === "approved" ? "已审" : "待审";
    const organization = frame.speaker?.role === "teacher" && frame.speaker.organization
      ? `<small class="preview-speaker-organization">${esc(frame.speaker.organization)}</small>` : "";
    const reply = frame.teacher_reply;
    const dialogue = isTeacherReply
      ? state.previewCompleted
        ? '<div class="preview-reply-complete" role="status">本段预览结束</div>'
        : reply?.reply_id && typeof reply.text === "string"
          ? `<button type="button" class="preview-teacher-reply" data-teacher-reply-id="${esc(reply.reply_id)}">${esc(reply.text)}</button>`
          : '<div class="preview-reply-complete" role="status">老师回答暂不可预览</div>'
      : `<div class="preview-dialogue ${isCg ? "is-cg" : ""}"><small>${esc(isCg ? "CG 空镜段落" : frame.presentation === "request" ? "需要处理" : frame.presentation === "direction" ? "演出指令" : "当前台词")}</small><strong>${esc(frame.title || "未命名卡片")}</strong>${organization}<p>${esc(frame.text || "此卡没有可显示的文本。")}</p>${annotations}</div>`;
    target.className = `performance-preview-frame presentation-${esc(frame.presentation)}`;
    target.innerHTML = `<section class="preview-stage">${background}<div class="preview-stage-overlay"></div><div class="preview-progress">${state.previewIndex + 1} / ${frames.length} · 第 ${esc(frame.line_no || "-")} 张 · ${esc(statusLabel)}</div>${cg}${dialogue}</section><div class="preview-card-strip" aria-label="草稿卡片定位">${frames.map((item, index) => `<button type="button" class="${index === state.previewIndex ? "active" : ""}" data-preview-index="${index}" aria-label="跳到第 ${esc(item.line_no || "-")} 张卡片">${esc(String(item.line_no || index + 1).padStart(2, "0"))}</button>`).join("")}</div>`;
    status.textContent = state.previewCompleted ? "本段预览结束，草稿没有被修改。"
      : `当前展示第 ${frame.line_no || "-"} 张卡片；预览是只读的，修改请回到这张卡。`;
    $("#previewPrevious").disabled = state.previewIndex === 0;
    $("#previewNext").disabled = (isTeacherReply && !state.previewCompleted)
      || state.previewIndex >= frames.length - 1;
    $("#previewOpenCard").disabled = !frame.card_id;
    $$('[data-preview-index]').forEach((button) => button.addEventListener("click", () => {
      state.previewIndex = Number(button.dataset.previewIndex) || 0;
      state.previewCompleted = false;
      renderPerformancePreview();
    }));
    target.querySelector('[data-teacher-reply-id]')?.addEventListener("click", () => {
      if (state.performancePreview?.frames?.[state.previewIndex]?.teacher_reply?.reply_id !== reply.reply_id) return;
      if (state.previewIndex < frames.length - 1) stepPerformancePreview(1);
      else {
        state.previewCompleted = true;
        renderPerformancePreview();
      }
      (target.querySelector('[data-teacher-reply-id]') || $("#previewOpenCard"))?.focus();
    });
  }

  async function openPerformancePreview() {
    if (!state.currentRun) { toast("先建立并载入一份演出草稿。", "warning"); return; }
    const dialog = $("#performancePreviewDialog");
    state.previewCompleted = false;
    $("#performancePreview").className = "performance-preview-empty";
    $("#performancePreview").innerHTML = "<strong>正在读取当前草稿</strong><p>预览会使用本任务冻结的背景、CG 和角色映射。</p>";
    $("#performancePreviewStatus").textContent = "正在读取，不会修改草稿。";
    dialog.showModal();
    try {
      await ensurePerformancePreview();
      const selected = state.selectedCard?.card_id;
      const selectedIndex = (state.performancePreview?.frames || []).findIndex((item) => item.card_id === selected);
      state.previewIndex = selectedIndex >= 0 ? selectedIndex : 0;
      renderPerformancePreview();
    } catch (error) {
      $("#performancePreview").className = "performance-preview-empty preview-error";
      $("#performancePreview").innerHTML = `<strong>无法读取草稿预览</strong><p>${esc(error.message)}</p>`;
      $("#performancePreviewStatus").textContent = "草稿没有被修改。";
    }
  }

  function proposalFieldLabel(field) {
    return { face: "表情", emo: "情绪气泡", act: "角色动作", fx: "画面效果" }[field] || field || "演出字段";
  }

  function renderDirectionProposals(audit) {
    const target = $("#directionProposals");
    const status = $("#directionProposalsStatus");
    const generations = audit.generations || [];
    if (audit.generation_mode !== "ai_direction") {
      target.className = "direction-proposals-empty";
      target.innerHTML = "<strong>这份草稿没有使用 AI 安排演出</strong><p>当前任务使用的是“仅转换格式”。没有模型建议需要查看，下一步请继续逐卡审查演出内容。</p>";
      status.textContent = "没有调用 AI，也没有修改草稿。";
      return;
    }
    if (!generations.length) {
      target.className = "direction-proposals-empty";
      target.innerHTML = "<strong>还没有 AI 演出运行记录</strong><p>完成或中止一次 AI 演出任务后，可在这里查看结果摘要。</p>";
      status.textContent = "没有重新调用模型，也没有修改草稿。";
      return;
    }
    target.className = "";
    target.innerHTML = `<section class="proposal-summary"><strong>${audit.total ? `共 ${audit.total} 条 AI 演出建议` : "AI 没有生成可写入的演出修改"}</strong><p>每次运行的状态、请求与错误都会保留。只有能唯一对应到当前台词的建议才允许保留或撤销。</p></section>${generations.map((generation) => {
      const metrics = generation.metrics || {};
      const generationLabels = { succeeded: "已完成", incomplete: "未完成", failed: "失败", superseded: "旧结果已丢弃" };
      const auditDetails = [
        `状态 ${generationLabels[generation.status] || generation.status || "未知"}`,
        `请求 ${numberLabel(metrics.requests)}`,
        `重试 ${numberLabel(metrics.retries)}`,
        `细分 ${numberLabel(metrics.subdivisions)}`,
        `缓存 ${cacheLabel(metrics)}`,
      ].join(" · ");
      const error = generation.error
        ? `<div class="proposal-generation-error"><strong>${esc(generation.error.code || "direction_generation_failed")}</strong><p>${esc(generation.error.message || "演出生成失败")}</p></div>`
        : "";
      const diagnostics = (generation.diagnostics || []).length
        ? `<details class="proposal-generation-diagnostics"><summary>生成诊断（${generation.diagnostics.length}）</summary><ul>${generation.diagnostics.map((item) => `<li><strong>${esc(item.code || item.level || "诊断")}</strong><span>${esc(item.message || item.detail || "")}</span></li>`).join("")}</ul></details>`
        : "";
      const proposals = (generation.proposals || []).map((proposal) => {
        const suggested = proposal.type === "suggested_fix";
        const before = proposal.before || "未设置";
        const after = proposal.after || "未设置";
        const action = proposal.can_apply_safely ? `<div class="proposal-actions"><button type="button" data-proposal-action="approve" data-proposal-id="${esc(proposal.proposal_id)}">保留这项标注</button><button type="button" class="danger" data-proposal-action="reject" data-proposal-id="${esc(proposal.proposal_id)}">撤销并恢复原值</button></div>` : "";
        return `<li class="proposal-item ${suggested ? "suggested" : "applied"}"><div><strong>${esc(proposalFieldLabel(proposal.field))}：${esc(after)}</strong><p>${suggested ? "模型提出了这个值，但系统没有把它写入草稿。" : "模型已把这个值写进生成后的草稿，仍需要你在逐卡审查中确认。"}</p><div class="proposal-change"><span>原值：${esc(before)}</span><span>建议值：${esc(after)}</span></div><p>${esc(proposal.apply_reason)}</p>${action}</div><b>${suggested ? "仅供参考" : proposal.can_apply_safely ? "可确认或撤销" : "已写入草稿"}</b></li>`;
      }).join("");
      return `<section class="proposal-generation state-${esc(generation.status || "unknown")}"><header><div><h4>一次生成记录 · ${esc(generation.proposal_count)} 条建议</h4><small>${esc(auditDetails)}</small></div></header>${error}${diagnostics}${proposals ? `<ul class="proposal-list">${proposals}</ul>` : '<p class="proposal-generation-empty">这次运行没有产生可写入的建议，草稿未被覆盖。</p>'}</section>`;
    }).join("")}`;
    status.textContent = "运行记录只读；打开此窗口不会修改草稿或调用模型。";
    $$('[data-proposal-action]').forEach((button) => button.addEventListener("click", () => decideDirectionProposal(button.dataset.proposalId, button.dataset.proposalAction)));
  }

  async function decideDirectionProposal(proposalId, action) {
    if (!state.currentRun || !state.currentDraft) return;
    const verb = action === "reject" ? "撤销并恢复生成前的值" : "保留这项 AI 标注";
    if (!await askConfirmation({ title: `${verb}？`, body: action === "reject" ? "这会修改对应台词，并让该卡回到待审。" : "这只记录你的确认，不会改写台词。", confirmLabel: action === "reject" ? "撤销标注" : "保留标注", danger: action === "reject" })) return;
    try {
      const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/direction-proposals/${encodeURIComponent(proposalId)}`, { method: "POST", body: JSON.stringify({ action, expected_draft_version: state.currentDraft.draft_version }) });
      applyRun(result);
      toast(action === "reject" ? "已撤销 AI 标注；请重新审查这张卡。" : "已记录：保留这项 AI 标注。");
      await openDirectionProposals();
    } catch (error) { handleError(error); }
  }

  async function openDirectionProposals() {
    if (!state.currentRun) { toast("先建立并载入一份演出草稿。", "warning"); return; }
    const dialog = $("#directionProposalsDialog");
    dialog.showModal();
    $("#directionProposals").className = "direction-proposals-empty";
    $("#directionProposals").innerHTML = "<strong>正在读取 AI 演出记录</strong><p>这只会读取本任务保存的生成记录，不会重新调用模型。</p>";
    $("#directionProposalsStatus").textContent = "正在读取，不会修改草稿。";
    try {
      renderDirectionProposals(await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/direction-proposals`));
    } catch (error) {
      $("#directionProposals").className = "direction-proposals-empty";
      $("#directionProposals").innerHTML = `<strong>无法读取 AI 演出记录</strong><p>${esc(error.message)}</p>`;
      $("#directionProposalsStatus").textContent = "草稿没有被修改。";
    }
  }

  function stepPerformancePreview(delta) {
    const frames = state.performancePreview?.frames || [];
    state.previewIndex = Math.max(0, Math.min(frames.length - 1, state.previewIndex + delta));
    state.previewCompleted = false;
    renderPerformancePreview();
    renderPersistentPerformancePreview();
  }

  function stepPersistentPreview(delta) {
    const frames = state.performancePreview?.frames || [];
    if (!frames.length) return;
    state.previewIndex = Math.max(0, Math.min(frames.length - 1, state.previewIndex + delta));
    state.previewCompleted = false;
    const frame = frames[state.previewIndex];
    if (frame?.card_id) {
      state.selectedCard = state.currentDraft?.cards?.find((card) => card.card_id === frame.card_id) || state.selectedCard;
      renderReview();
      if (state.selectedCard) renderInspector();
    }
    renderPersistentPerformancePreview();
  }

  function openPreviewCard() {
    const frame = state.performancePreview?.frames?.[state.previewIndex];
    if (!frame?.card_id) return;
    $("#performancePreviewDialog").close();
    state.selectedCard = state.currentDraft?.cards?.find((card) => card.card_id === frame.card_id) || null;
    showStage("review", { force: true });
    renderReview();
    $("[data-card-id='" + CSS.escape(frame.card_id) + "']")?.focus();
  }

  const directiveOptions = [
    ["wait", "停顿", "填写毫秒，例如 800"],
    ["trans", "背景过渡", "例如：淡入淡出"],
    ["bgfx", "背景效果", "例如：雨、集中线"],
    ["popup", "插图/弹窗", "填写已登记的插图名称"],
    ["bgm", "背景音乐", "填写 BGM 数字 ID，999 为静音"],
    ["place", "地点名称卡", "例如：千年科技学园"],
    ["enter", "角色入场", "角色名，可加位置和左右"],
    ["exit", "角色退场", "角色名，可加 左 或 右"],
    ["move", "角色走位", "角色名 位置，例如：爱丽丝 3"],
    ["stage", "固定舞台站位", "角色@位置，例如：爱丽丝@3"],
    ["auto", "恢复自动站位", "不需要参数"],
    ["camera", "单行镜头", "角色名列表；- 表示这一行空镜"],
    ["camera_hold", "持续镜头", "角色名列表；- 持续空镜；auto 恢复"],
    ["fx", "角色立绘效果", "角色名 效果，例如：爱丽丝 特写"],
    ["hl", "高亮角色", "角色名列表；- 表示都不高亮"],
    ["bgshake", "背景抖动", "不需要参数"],
    ["clearst", "清除屏幕文字", "不需要参数"],
    ["hidemenu", "隐藏菜单", "不需要参数"],
    ["showmenu", "显示菜单", "不需要参数"],
    ["shot", "射击效果", "角色名或位置数字"],
    ["aronatouch", "ARONA 指纹效果", "不需要参数"],
    ["st", "左对齐屏幕文字", "AA 原生参数"],
    ["stm", "居中屏幕文字", "AA 原生参数"],
    ["zoom", "背景缩放/平移", "AA 原生参数"],
    ["raw", "原样 AA 指令", "保留为 AA 的额外指令"],
  ];
  const directiveHelp = Object.fromEntries(directiveOptions.map(([cmd, label, hint]) => [cmd, { label, hint }]));
  const resourceDirectiveHelp = {
    bg: { label: "背景", hint: "从当前任务的背景素材中选择，不能直接输入。" },
    se: { label: "音效", hint: "从当前任务的音效素材中选择，不能直接输入。" },
    sound: { label: "音效", hint: "从当前任务的音效素材中选择，不能直接输入。" },
  };

  function directiveOptionMarkup(selected) {
    const resourceOptions = [["bg", "背景（从素材选择）"], ["se", "音效（从素材选择）"]];
    const rows = [...resourceOptions, ...directiveOptions.map(([cmd, label]) => [cmd, label])];
    return rows.map(([cmd, label]) => `<option value="${cmd}" ${cmd === selected ? "selected" : ""}>${esc(label)}</option>`).join("");
  }

  function directiveEditor(card) {
    const current = card.current || {};
    const cmd = String(current.cmd || "").toLowerCase();
    const resource = resourceDirectiveHelp[cmd];
    if (resource) {
      const primary = cmd === "bg" ? "chooseBackground" : "chooseSound";
      const primaryLabel = cmd === "bg" ? "为这张卡选择背景" : "为这张卡选择音效";
      const secondary = cmd === "bg" ? '<button id="blackBackground">改为黑屏</button>' : '<button id="removeSound">移除这条声音</button>';
      return `<p class="field-summary">当前${resource.label}：<b>${esc(current.arg || "未设置")}</b></p><p class="inspector-note">${resource.hint}</p><div class="inspector-actions"><button class="primary" id="${primary}">${primaryLabel}</button>${secondary}<button id="approveCard">确认这张卡</button></div>`;
    }
    const help = directiveHelp[cmd] || { label: "演出指令", hint: "选择指令类型并填写参数。" };
    return `<section class="directive-editor"><label>演出类型<select id="editDirectiveCmd">${directiveOptionMarkup(cmd)}</select></label><label>参数<input id="editDirectiveArg" value="${esc(current.arg || "")}" placeholder="${esc(help.hint)}"></label><p id="directiveHelp" class="inspector-note"><b>${esc(help.label)}</b>：${esc(help.hint)} 保存后，这张以及后面的卡片都会回到待审。</p></section><div class="inspector-actions"><button class="primary" id="saveDirectiveEdit">保存演出指令</button><button id="approveCard">确认这张卡</button></div>`;
  }

  function linePerformanceEditor(card) {
    const current = card.current || {};
    const speaker = String(current.who || "").trim();
    const mapping = mappingFor(speaker);
    if (mapping.kind !== "portrait") {
      const reason = mapping.kind === "narrator"
        ? `“${speaker || "这句"}”目前按旁白处理，不显示角色立绘。`
        : mapping.kind === "voice"
          ? `“${speaker || "这句"}”目前是无立绘角色，不显示角色骨骼。`
          : `“${speaker || "这句"}”还没有映射角色，暂时不能选择表情。`;
      return `<section class="line-performance-editor"><header><small>本句演出设置</small><h4>决定这一句怎么演</h4><p>角色映射决定“用哪套骨骼”；这里仅调整这一句的表情、情绪、动作和画面效果。</p></header><div class="performance-unavailable"><strong>本句不能设置表情</strong><p>${esc(reason)}</p><button type="button" id="editLineMapping">去角色映射处理</button></div></section>`;
    }
    return `<section class="line-performance-editor"><header><small>本句演出设置</small><h4>决定这一句怎么演</h4><p>角色映射决定“用哪套骨骼”；这里仅调整这一句的表情、情绪、动作和画面效果。</p></header><div id="linePerformanceFields" class="performance-loading"><strong>正在读取可选表情</strong><p>只会读取当前任务冻结的“${esc(mapping.name || mapping.id || speaker)}”角色素材。</p></div></section>`;
  }

  function faceOptionValue(face) {
    return String(face.id || face.raw || face.label || "").trim();
  }

  function faceDisplayLabel(face) {
    const label = String(face.semantic_cn || face.cn || face.label || face.raw || face.id || "未命名表情");
    return label.split(/[｜|]/, 1)[0].trim() || label;
  }

  function faceAnnotationMarkup(face) {
    if (!face) return '<p class="annotation-empty">未指定表情：本句不切换，沿用角色此前状态；尚无状态时使用 AA 默认表情。不会自动套用推荐。</p>';
    const holdLabels = { hold: "可持续保持", short: "短暂反应", flash: "瞬间强调" };
    const families = { neutral: "平静", joy: "喜悦", surprise_fear: "惊讶 / 害怕", embarrassment: "害羞", irritation_anger: "烦躁 / 生气", sadness_hurt: "悲伤 / 受伤", confusion_resignation: "困惑 / 无奈", determination: "坚定 / 专注" };
    const beats = { reaction: "反应", tension: "紧张", comfort: "安慰", setback: "受挫", climax: "高潮", conflict: "冲突", dialogue: "日常对话", hesitation: "犹豫", celebration: "庆祝", embarrassment: "害羞", idle: "待机", comedy: "喜剧", reveal: "揭示", teasing: "打趣", exposition: "说明", resolution: "化解", transition: "过渡", greeting: "问候", question: "疑问", listening: "倾听", denial: "否认", action: "行动" };
    const rows = [
      ["表情含义", face.semantic_cn || face.cn || face.label ? faceDisplayLabel(face) : ""],
      ["情绪类别", families[face.emotion_family] || face.emotion_family],
      ["情绪强度", Number.isInteger(face.intensity) ? `${face.intensity} / 3` : ""],
      ["适用语境", face.usage_hint_cn],
      ["适合节拍", Array.isArray(face.beat_fit) ? face.beat_fit.map((beat) => beats[beat] || beat).join("、") : face.beat_fit],
      ["持续方式", holdLabels[face.hold_policy] || face.hold_policy],
      ["不适用", face.avoid_when_cn],
    ].filter(([, value]) => value !== undefined && value !== null && String(value).trim());
    return rows.length ? `<dl class="annotation-facts">${rows.map(([label, value]) => `<div class="${label === "不适用" ? "annotation-caution" : ""}"><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl><p class="annotation-empty">来自本任务冻结标记；选择后仍需保存本句，不会自动更换表情。</p>` : '<p class="annotation-empty">这个表情尚无语义标记，不猜测其含义。</p>';
  }

  async function hydrateLinePerformanceEditor(card) {
    const target = $("#linePerformanceFields");
    if (!target || !state.currentRun || state.selectedCard?.card_id !== card.card_id) return;
    const current = card.current || {};
    const speaker = String(current.who || "").trim();
    const mapping = mappingFor(speaker);
    const runId = state.currentRun.run_id;
    try {
      const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/resources/characters/${encodeURIComponent(mapping.id)}`);
      if (state.currentRun?.run_id !== runId || state.selectedCard?.card_id !== card.card_id || !target.isConnected) return;
      const character = result.character || {};
      const faces = character.faces || [];
      const selected = String(current.face || "");
      const options = [`<option value="">不切换表情（延续此前状态）</option>`, ...faces.map((face) => {
        const value = faceOptionValue(face);
        const label = faceDisplayLabel(face);
        return `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(label)}${face.id && face.id !== label ? ` · ${esc(face.id)}` : ""}</option>`;
      })].join("");
      target.className = "performance-fields";
      target.innerHTML = `<p class="performance-character"><b>${esc(character.name || mapping.name || mapping.id)}</b><span>本任务冻结角色 · ${faces.length} 个可选表情</span></p><label>表情<select id="editLineFace">${options}</select><small>这里只列出这套骨骼实际拥有的表情；留空不代表恢复平静，会延续此前表情。要收回强烈反应，请明确选择合适的基础表情。</small></label><section class="face-annotation-panel" aria-label="当前表情使用标记"><h5>表情使用标记</h5><div id="faceAnnotationContent" aria-live="polite"></div></section><div class="performance-option-grid"><label>情绪气泡<input id="editLineEmo" value="${esc(current.emo || "")}" placeholder="例如：惊讶（可留空）"><small>显示在对话气泡上的情绪标记。</small></label><label>角色动作<input id="editLineAct" value="${esc(current.act || "")}" placeholder="例如：挥手（可留空）"><small>这句台词触发的角色动作。</small></label></div><label>画面效果<input id="editLineFx" value="${esc(current.fx || "")}" placeholder="例如：特写（可留空）"><small>用于这一句的立绘表现，例如特写或剪影。</small></label><p class="inspector-note">保存后本卡会回到待审；如果标注不被 AA 支持，编译诊断会告诉你具体原因。</p>`;
      const select = target.querySelector("#editLineFace");
      const updateAnnotation = () => {
        target.querySelector("#faceAnnotationContent").innerHTML = faceAnnotationMarkup(faces.find((face) => faceOptionValue(face) === select.value));
      };
      select.addEventListener("change", updateAnnotation);
      updateAnnotation();
    } catch (error) {
      if (state.currentRun?.run_id !== runId || state.selectedCard?.card_id !== card.card_id || !target.isConnected) return;
      target.className = "performance-unavailable";
      target.innerHTML = `<strong>无法读取本句可选表情</strong><p>${esc(error.message)} 请回到角色映射确认该角色，或刷新任务后再试。</p>`;
    }
  }

  function linePerformancePatch() {
    return {
      text: $("#editCardText")?.value || "",
      face: $("#editLineFace")?.value || "",
      emo: $("#editLineEmo")?.value || "",
      act: $("#editLineAct")?.value || "",
      fx: $("#editLineFx")?.value || "",
    };
  }

  function renderInspector() {
    const card = state.selectedCard;
    if (!card) return;
    const current = card.current || {};
    $("#inspectorTitle").textContent = `正在编辑：第 ${card.line_no || "-"} 张 · ${cardKindLabel(card)}`;
    let body = `<p class="inspector-note">${esc(card.raw || "")}</p>`;
    if (card.cg) {
      body += `<section class="cg-inspector"><small>所属 CG 段落</small><strong>${esc(card.cg.label)}</strong><p>背景：${esc(card.cg.background_key)} · 具名无立绘</p><button id="deleteCgSegment">删除此 CG 段落</button></section>`;
    }
    body += `<div class="inspector-context"><small>当前选中对象</small><strong>第 ${card.line_no || "-"} 张 · ${esc(cardKindLabel(card))}</strong><span>下面的保存、审查和素材操作只会影响这一张卡片。</span></div>`;
    if (card.kind === "line") {
      body += `<label>台词<textarea id="editCardText">${esc(current.text || "")}</textarea><small>保存只会修改这一句，后面的台词不会被改写。</small></label>${linePerformanceEditor(card)}<div class="inspector-actions"><button class="primary" id="saveCardEdit">保存本句演出设置</button><button id="approveCard">标记本句已审</button></div>`;
    } else if (card.kind === "unknown") {
      body += `<section class="unknown-card-editor"><small>未识别文本 · 需要转为台词</small><h4>补全说话者后转换为普通台词卡</h4><p>这行原文没有可编译的 AA 结构。转换会保留卡片位置、版本记录和审查状态，但会把它明确改写为“说话者：台词”。</p><label>说话者<input id="editUnknownWho" placeholder="例如：旁白、爱丽丝"></label><label>台词<textarea id="editUnknownText">${esc(card.raw || current.text || "")}</textarea></label><div class="inspector-actions"><button class="primary" id="saveCardEdit">转换为台词卡</button></div></section>`;
    } else if (card.kind === "dir") {
      body += directiveEditor(card);
    } else if (card.kind === "background_request") {
      body += `<section class="request-card-editor"><small>背景素材请求</small><h4>为这一处画面选择背景</h4><p>${esc(current.description || "系统未能读取背景描述。")}</p><p class="inspector-note">背景请求不能靠删除跳过。请从当前任务的冻结素材清单选择背景，或明确改为黑屏。</p><div class="inspector-actions"><button class="primary" id="resolveRequestedBackground">选择背景</button><button id="resolveRequestedBlack">改为黑屏</button></div></section>`;
    } else {
      const field = card.kind === "scene" || card.kind === "title" ? "title" : "text";
      const label = field === "title" ? "标题" : "文本备注";
      body += `<label>${label}<input id="editCardGeneric" value="${esc(current[field] || "")}"></label><div class="inspector-actions"><button class="primary" id="saveCardEdit">保存这张卡</button><button id="approveCard">确认这张卡</button></div>`;
      if (card.kind === "scene") { const sceneBackground = sceneBackgroundCard(card); const backgroundText = sceneBackground ? `当前背景：${esc(sceneBackground.current?.arg || "未命名背景")}（修改将直接替换第 ${sceneBackground.line_no || "-"} 张背景卡）` : "当前场景还没有显式背景。选择后会紧接场景标题插入一张可审查的 @bg 卡。"; body += `<section class="scene-background-studio"><small>场景背景制作 · 第四步</small><h4>${sceneBackground ? "更换当前场景背景" : "为当前场景建立画面"}</h4><p>${backgroundText}</p><p class="inspector-note">AA 资源快照、本任务导入和历史素材都会保留来源；不会额外叠加同场景的重复背景切换。</p><div class="inspector-actions"><button class="primary" id="sceneChooseOfficialBackground">${sceneBackground ? "更换为AA / 本任务背景" : "AA / 本任务背景"}</button><button id="sceneChooseLibraryBackground">导入历史素材</button><button id="sceneImportBackground">添加自定义背景</button><button id="sceneUseBlackBackground">${sceneBackground ? "改为黑屏" : "保持黑屏"}</button></div></section>`; }
    }
    const mustResolve = card.kind === "background_request";
    body += `<div class="card-actions"><small>结构调整</small><button id="insertAfterCard">在这张卡后插入</button><button id="moveCardEarlier" ${card.line_no === 1 ? "disabled" : ""}>移到上一张前</button><button id="moveCardLater" ${card.line_no === (state.currentDraft.cards || []).length ? "disabled" : ""}>移到下一张后</button>${mustResolve ? '<p class="card-action-note">这是一项必处理的背景请求，不能删除；请先选择背景或改为黑屏。</p>' : '<button class="danger-button" id="deleteSelectedCard">删除这张卡</button>'}</div>`;
    $("#inspectorBody").innerHTML = body;
    $("#saveCardEdit")?.addEventListener("click", () => patchCard(card, card.kind === "line" ? linePerformancePatch() : card.kind === "unknown" ? { who: $("#editUnknownWho").value.trim(), text: $("#editUnknownText").value } : { [card.kind === "scene" || card.kind === "title" ? "title" : "text"]: $("#editCardGeneric").value }));
    $("#saveDirectiveEdit")?.addEventListener("click", () => patchCard(card, { cmd: $("#editDirectiveCmd").value, arg: $("#editDirectiveArg").value }));
    $("#editDirectiveCmd")?.addEventListener("change", (event) => {
      const selected = event.target.value;
      const resource = resourceDirectiveHelp[selected];
      if (resource) {
        toast(`“${resource.label}”需要从素材选择器中选取，已保留当前卡片。`, "warning");
        event.target.value = String(current.cmd || "");
        return;
      }
      const help = directiveHelp[selected] || { label: "演出指令", hint: "选择指令类型并填写参数。" };
      $("#editDirectiveArg").placeholder = help.hint;
      $("#directiveHelp").innerHTML = `<b>${esc(help.label)}</b>：${esc(help.hint)} 保存后，这张以及后面的卡片都会回到待审。`;
      if (["auto", "bgshake", "clearst", "hidemenu", "showmenu", "aronatouch"].includes(selected)) $("#editDirectiveArg").value = "";
    });
    $("#approveCard")?.addEventListener("click", () => approveCards([card.card_id]));
    $("#resolveRequestedBackground")?.addEventListener("click", () => chooseResource("backgrounds", "背景", (item) => resolveCard("background-resolution", { action: "select", background_key: item.key })));
    $("#resolveRequestedBlack")?.addEventListener("click", () => resolveCard("background-resolution", { action: "black" }));
    $("#chooseBackground")?.addEventListener("click", () => chooseResource("backgrounds", "背景", (item) => resolveCard("background-resolution", { action: "select", background_key: item.key })));
    $("#blackBackground")?.addEventListener("click", () => resolveCard("background-resolution", { action: "black" }));
    $("#sceneChooseOfficialBackground")?.addEventListener("click", () => chooseResource("backgrounds", "场景背景", (item) => insertSceneBackground(card, item), {
      sceneCardId: card.card_id, eyebrow: "场景背景制作", title: "选择 AA 或本任务背景", status: "只显示当前任务冻结快照与已登记的任务背景。", selectionNote: "选中后会紧接当前场景标题插入一张可审查的背景指令卡。", actionLabel: "设为本场景背景",
    }));
    $("#sceneChooseLibraryBackground")?.addEventListener("click", () => chooseSceneLibraryBackground(card));
    $("#sceneImportBackground")?.addEventListener("click", () => openSceneBackgroundImport(card));
    $("#sceneUseBlackBackground")?.addEventListener("click", () => insertSceneBackground(card, { key: "BG_Black", name: "黑屏", source: "task_snapshot" }));
    $("#chooseSound")?.addEventListener("click", () => chooseResource("sounds", "音效", (item) => resolveCard("sound-resolution", { action: "select", sound_key: item.key })));
    $("#removeSound")?.addEventListener("click", () => resolveCard("sound-resolution", { action: "remove" }));
    $("#deleteCgSegment")?.addEventListener("click", () => deleteCgSegment(card.cg));
    $("#insertAfterCard")?.addEventListener("click", () => openInsertCard(card));
    $("#moveCardEarlier")?.addEventListener("click", () => moveSelectedCard(card, "earlier"));
    $("#moveCardLater")?.addEventListener("click", () => moveSelectedCard(card, "later"));
    $("#deleteSelectedCard")?.addEventListener("click", () => deleteSelectedCard(card));
    $("#editLineMapping")?.addEventListener("click", () => {
      showStage("mapping", { force: true });
      const row = Array.from($$(".mapping-edit")).find((button) => button.dataset.speaker === String(current.who || ""));
      row?.focus();
    });
    if (card.kind === "line" && mappingFor(String(current.who || "")).kind === "portrait") hydrateLinePerformanceEditor(card);
  }

  function openInsertCard(card, initialKind = "line") {
    state.insertAfterCardId = card.card_id;
    $("#insertCardHint").textContent = `新卡片会插入到“第 ${card.line_no || "-"} 张 · ${card.kind}”之后，并标记为待审。`;
    $("#insertCardStatus").textContent = "先选择类型，再填写内容；插入后可以继续修改。";
    $("#insertCardKind").value = initialKind;
    updateInsertFields();
    $("#insertCardDialog").showModal();
  }

  function updateInsertFields() {
    const kind = $("#insertCardKind").value;
    ["line", "dir", "scene", "meta"].forEach((name) => $("#insert" + name[0].toUpperCase() + name.slice(1) + "Fields")?.classList.toggle("hidden", name !== kind));
  }

  function sceneBackgroundCard(sceneCard) {
    const cards = state.currentDraft?.cards || [];
    const start = cards.findIndex((card) => card.card_id === sceneCard?.card_id);
    if (start < 0) return null;
    for (let index = start + 1; index < cards.length; index += 1) {
      const card = cards[index];
      if (card.kind === "scene") break;
      if (card.kind === "dir" && card.current?.cmd === "bg") return card;
    }
    return null;
  }

  async function insertSceneBackground(sceneCard, item) {
    if (!state.currentRun || !state.currentDraft || !sceneCard || !item?.key) return;
    const existing = sceneBackgroundCard(sceneCard);
    try {
      const result = existing
        ? await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/cards/${encodeURIComponent(existing.card_id)}/background-resolution`, { method: "POST", body: JSON.stringify({ action: "select", background_key: item.key, expected_draft_version: state.currentDraft.draft_version }) })
        : await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/cards`, { method: "POST", body: JSON.stringify({ after_card_id: sceneCard.card_id, kind: "dir", fields: { cmd: "bg", arg: item.key }, expected_draft_version: state.currentDraft.draft_version }) });
      const selected = existing
        ? (result.draft?.cards || []).find((candidate) => candidate.card_id === existing.card_id)
        : (result.draft?.cards || []).find((candidate) => candidate.card_id !== sceneCard.card_id && candidate.kind === "dir" && candidate.current?.cmd === "bg" && candidate.current?.arg === item.key);
      applyRun(result);
      state.selectedCard = selected || state.currentDraft?.cards?.find((candidate) => candidate.card_id === sceneCard.card_id) || null;
      renderReview();
      requestAnimationFrame(() => $("[data-card-id='" + CSS.escape(state.selectedCard?.card_id || "") + "']")?.focus());
      toast(`${existing ? "已更换" : "已插入"}“${item.name || item.key}”（${resourceSourceLabel(item)}）；请确认这张背景卡。`);
    } catch (error) { handleError(error); }
  }

  async function chooseSceneLibraryBackground(sceneCard) {
    await chooseResource("backgrounds", "历史背景", async (item) => {
      try {
        const attached = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/library-assets/${encodeURIComponent(item.asset_id)}`, {
          method: "POST", body: JSON.stringify({ expected_draft_version: state.currentDraft.draft_version }),
        });
        applyRun(attached);
        await insertSceneBackground(sceneCard, { ...item, source: "custom_library" });
      } catch (error) { handleError(error); }
    }, {
      source: "library", eyebrow: "历史背景素材", title: "从历史素材库导入背景", status: "选中后会先冻结到当前任务，再插入可审查的背景指令卡。", selectionNote: "将导入当前任务并紧接场景标题插入背景卡。", actionLabel: "导入并使用", emptyText: "历史素材库里还没有背景图片；可先添加自定义背景。",
    });
  }

  function openSceneBackgroundImport(sceneCard) {
    state.sceneBackgroundTarget = { card_id: sceneCard.card_id };
    openAssetImport();
    const background = document.querySelector('input[name="assetImportKind"][value="background"]');
    if (background) { background.checked = true; background.dispatchEvent(new Event("change")); }
    $("#assetImportDialog h3").textContent = "添加自定义场景背景";
    $("#assetImportStatus").textContent = "检查并登记后，HaloCue 会自动为当前场景插入背景卡。";
  }
  async function insertCard() {
    if (!state.currentRun || !state.currentDraft || !state.insertAfterCardId) return;
    const kind = $("#insertCardKind").value;
    let fields;
    if (kind === "line") fields = { who: $("#insertWho").value.trim(), text: $("#insertText").value };
    if (kind === "dir") fields = { cmd: $("#insertCmd").value.trim(), arg: $("#insertArg").value.trim() };
    if (kind === "scene") fields = { title: $("#insertTitle").value.trim() };
    if (kind === "meta") fields = { text: $("#insertMetaText").value };
    if (!fields || (kind === "line" && !fields.text.trim()) || (kind === "dir" && !fields.cmd) || (kind === "scene" && !fields.title.trim()) || (kind === "meta" && !fields.text.trim())) {
      $("#insertCardStatus").textContent = "请先填写这张卡片的必要内容。";
      return;
    }
    try {
      const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/cards`, { method: "POST", body: JSON.stringify({ after_card_id: state.insertAfterCardId, kind, fields, expected_draft_version: state.currentDraft.draft_version }) });
      $("#insertCardDialog").close(); applyRun(result); toast("新卡片已插入，并标记为待审。", "normal");
    } catch (error) { handleError(error); }
  }

  async function moveSelectedCard(card, direction) {
    const cards = state.currentDraft?.cards || [];
    const index = cards.findIndex((item) => item.card_id === card.card_id);
    const beforeCardId = direction === "earlier"
      ? cards[index - 1]?.card_id || null
      : cards[index + 2]?.card_id || null;
    if (direction === "later" && index >= cards.length - 1) return;
    try {
      const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/cards/move`, { method: "POST", body: JSON.stringify({ card_id: card.card_id, before_card_id: beforeCardId, expected_draft_version: state.currentDraft.draft_version }) });
      applyRun(result); toast(direction === "earlier" ? "卡片已移到上一张前面。" : "卡片已移到下一张后面。", "normal");
    } catch (error) { handleError(error); }
  }

  async function deleteSelectedCard(card) {
    if (!await askConfirmation({ title: `删除第 ${card.line_no || "-"} 张卡片？`, body: "删除后需要重新审查，其他卡片不会被改写。", confirmLabel: "删除卡片", danger: true })) return;
    try {
      const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/cards/${encodeURIComponent(card.card_id)}`, { method: "DELETE", body: JSON.stringify({ expected_draft_version: state.currentDraft.draft_version }) });
      state.selectedCard = null; applyRun(result); toast("卡片已删除，草稿已回到待审状态。", "warning");
    } catch (error) { handleError(error); }
  }

  function cardOption(card) {
    const current = card.current || {};
    const summary = card.kind === "line"
      ? `${current.who || "未映射"}: ${current.text || ""}`
      : `${current.cmd || card.kind} ${current.arg || ""}`;
    return `第 ${card.line_no || "-"} 行 · ${summary}`.slice(0, 100);
  }

  async function openCgDialog() {
    const cards = state.currentDraft?.cards || [];
    if (!state.currentRun || !cards.length) {
      toast("先建立并载入一份演出草稿。", "warning");
      return;
    }
    const options = cards.map((card) => `<option value="${esc(card.card_id)}">${esc(cardOption(card))}</option>`).join("");
    $("#cgStartCard").innerHTML = options;
    $("#cgEndCard").innerHTML = options;
    const selectedIndex = Math.max(0, cards.findIndex((card) => card.card_id === state.selectedCard?.card_id));
    $("#cgStartCard").selectedIndex = selectedIndex;
    $("#cgEndCard").selectedIndex = selectedIndex;
    $("#cgLabel").value = "";
    $("#cgSearch").value = "";
    $("#cgAdvice").className = "cg-advice hidden";
    $("#cgAdvice").innerHTML = "";
    state.cgBackgroundKey = null;
    renderCgSelection();
    $("#cgDialog").showModal();
    await searchCgResources("");
  }

  function renderCgSelection() {
    $("#cgSelectedMaterial").textContent = state.cgBackgroundKey || "尚未选择";
    $("#createCgSegment").disabled = !state.cgBackgroundKey;
  }

  function renderCgAdvice(result) {
    const target = $("#cgAdvice");
    const advice = result.advice || {};
    const recommended = !!advice.recommended;
    const notes = (advice.continuity_notes || []).concat(advice.generation_notes || []);
    target.className = `cg-advice ${recommended ? "" : "not-recommended"}`;
    target.innerHTML = `<header><div><small>${recommended ? "AI 制作意见 · 仅供作者决定" : "AI 制作意见 · 建议暂不制作 CG"}</small><h4>${esc(advice.story_beat || "selected_range")}</h4></div><b>${recommended ? "可作为 CG 候选" : "普通台词即可"}</b></header><p>${esc(advice.reason || "没有收到可用建议。")}</p>${recommended ? `<label><small>GPT Image 提示词草案</small><textarea readonly aria-label="GPT Image 提示词草案">${esc(advice.image_prompt || "")}</textarea></label><p>${esc(advice.reference_note || "")}</p>` : ""}${notes.length ? `<ul>${notes.map((note) => `<li>${esc(note)}</li>`).join("")}</ul>` : ""}`;
  }

  async function askCgAdvice() {
    if (!state.currentRun || !state.currentDraft) return;
    const target = $("#cgAdvice");
    target.className = "cg-advice";
    target.innerHTML = "<small>AI 制作意见</small><p>正在只读分析你选中的起止卡，不会修改草稿或创建 CG。</p>";
    try {
      const accepted = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/cg-advice`, {
        method: "POST",
        body: JSON.stringify({
          start_card_id: $("#cgStartCard").value,
          end_card_id: $("#cgEndCard").value,
          expected_draft_version: state.currentDraft.draft_version,
        }),
      });
      const job = await pollJob(accepted.job.job_id, "CG 制作意见");
      renderCgAdvice(job.result || {});
    } catch (error) {
      target.className = "cg-advice not-recommended";
      target.innerHTML = `<small>无法获取制作意见</small><p>${esc(error.message)}</p>`;
    }
  }

  async function searchCgResources(query) {
    if (!state.currentRun) return;
    const status = $("#cgDialogStatus");
    try {
      const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/resources/cg-backgrounds?q=${encodeURIComponent(query)}&limit=120`);
      const items = result.items || [];
      $("#cgResults").innerHTML = items.length ? items.map((item) => `<button type="button" class="character-row resource-row cg-material-row ${item.key === state.cgBackgroundKey ? "selected" : ""}" data-cg-key="${esc(item.key)}" aria-pressed="${item.key === state.cgBackgroundKey}">
        ${previewImage("backgrounds", item.key, item.name || item.key, "resource-thumb cg-thumb", item.preview_available === true)}<span><strong>${esc(item.name || item.key)}</strong><small>${esc(item.key)} · ${item.cg_source === "official_cg" ? "官方 CG" : "自定义背景"}</small><small>进入所选范围时切换为这张图，并强制隐藏全部角色立绘。</small></span><b>${item.key === state.cgBackgroundKey ? "已选中" : "选择"}</b></button>`).join("") : '<p class="empty">没有匹配的自定义背景或官方 CG。</p>';
      $$("[data-cg-key]").forEach((button) => button.addEventListener("click", () => {
        state.cgBackgroundKey = button.dataset.cgKey;
        renderCgSelection();
        searchCgResources($("#cgSearch").value);
      }));
      status.textContent = items.length ? `找到 ${result.total} 个可用 CG 画面；普通场景背景已隐藏。` : "当前任务没有匹配的自定义背景或官方 CG。";
    } catch (error) { status.textContent = error.message; }
  }

  async function createCgSegment() {
    if (!state.currentRun || !state.currentDraft || !state.cgBackgroundKey) return;
    const payload = {
      start_card_id: $("#cgStartCard").value,
      end_card_id: $("#cgEndCard").value,
      background_key: state.cgBackgroundKey,
      label: $("#cgLabel").value.trim(),
      expected_draft_version: state.currentDraft.draft_version,
    };
    setBusy(true);
    try {
      const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/cg-segments`, { method: "POST", body: JSON.stringify(payload) });
      $("#cgDialog").close();
      applyRun(result);
      toast("CG 段落已插入。进入范围时会切换背景并隐藏全部角色立绘。");
    } catch (error) { handleError(error); } finally { setBusy(false); }
  }

  async function deleteCgSegment(segment) {
    if (!state.currentRun || !state.currentDraft || !segment) return;
    if (!await askConfirmation({ title: `删除 CG 段落“${segment.label}”？`, body: "范围内卡片会重新变为待审，原有台词和背景引用不会被删除。", confirmLabel: "删除 CG 段落", danger: true })) return;
    try {
      const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/cg-segments/${encodeURIComponent(segment.segment_id)}`, {
        method: "DELETE", body: JSON.stringify({ expected_draft_version: state.currentDraft.draft_version })
      });
      applyRun(result);
      toast("CG 段落已删除。", "warning");
    } catch (error) { handleError(error); }
  }

  async function patchCard(card, patch) {
    try {
      const result = await api(`/production-runs/${state.currentRun.run_id}/cards/${card.card_id}`, { method: "PATCH", body: JSON.stringify({ patch, expected_draft_version: state.currentDraft.draft_version }) });
      applyRun(result); toast("卡片已保存。");
    } catch (error) { handleError(error); }
  }

  async function resolveCard(action, payload, card = state.selectedCard) {
    if (!card) return;
    try {
      const result = await api(`/production-runs/${state.currentRun.run_id}/cards/${card.card_id}/${action}`, { method: "POST", body: JSON.stringify({ ...payload, expected_draft_version: state.currentDraft.draft_version }) });
      applyRun(result); toast("素材请求已处理。");
    } catch (error) { handleError(error); }
  }

  function resourceSourceLabel(item) {
    const source = String(item?.source || "");
    if (source === "task_import") return "本任务导入";
    if (source === "custom_library") return "历史素材库";
    if (source === "task_snapshot") return "任务冻结快照";
    if (source === "background_library") return "完整背景库";
    return "已登记素材";
  }

  function resourceFilterValue(selector) {
    const element = $(selector);
    return element && !element.disabled ? String(element.value || "").trim() : "";
  }

  function resourceMetadataText(item) {
    const values = [item.category || item.main_category_cn || item.subcategory, item.place, item.time || item.time_of_day, item.weather, item.mood, item.indoor_outdoor, item.season]
      .map((value) => String(value || "").trim())
      .filter(Boolean);
    const tags = Array.isArray(item.tags) ? item.tags : String(item.tags || "").split(",");
    values.push(...tags.map((value) => String(value || "").trim()).filter(Boolean).slice(0, 3));
    return [...new Set(values)].slice(0, 5).join(" · ");
  }

  function backgroundQuickTags(item) {
    const labels = { day: "白天", daytime: "白天", night: "夜晚", evening: "傍晚", dusk: "黄昏", dawn: "清晨", morning: "清晨", indoor: "室内", outdoor: "室外" };
    return [...new Set([item.time, item.indoor_outdoor].map(value => {
      const text = String(value || "").trim();
      return labels[text.toLowerCase()] || (hasChinese(text) && text.length <= 8 ? text : "");
    }).filter(Boolean))].join(" · ");
  }

  function resourceAnnotationMarkup(item, query = "") {
    const terms = String(query || "").trim().toLocaleLowerCase();
    const fields = [["名称", item.name], ["资源键", item.key], ["地点", item.place], ["时间", item.time], ["天气", item.weather], ["氛围", item.mood], ["室内外", item.indoor_outdoor], ["季节", item.season], ["用途", item.usage_hint], ["标签", item.tags], ["检索别名", item.search_terms], ["分类", item.category], ["描述", item.description]];
    const hits = terms ? fields.flatMap(([label, raw]) => (Array.isArray(raw) ? raw : [raw]).filter((value) => value && String(value).toLocaleLowerCase().includes(terms)).map((value) => `${label}：${value}`)).slice(0, 3) : [];
    const notes = [];
    const advice = item.scene_match;
    if (advice) {
      const label = { match: "已知条件匹配", unknown: "信息不足 · 待核对", conflict: "条件冲突 · 谨慎使用" }[advice.status] || "待核对";
      notes.push(`<span class="scene-match-state ${advice.status === "conflict" ? "annotation-caution" : "annotation-match"}">${esc(label)}${advice.current ? " · 当前采用" : ""}</span>`);
      for (const value of advice.matches || []) notes.push(`<span>匹配 · ${esc(value)}</span>`);
      for (const value of advice.conflicts || []) notes.push(`<span class="annotation-caution">${esc(value)}</span>`);
      for (const value of advice.unknown || []) notes.push(`<span class="annotation-unknown">${esc(value)}</span>`);
    }
    if (hits.length) notes.push(`<span class="annotation-match">搜索命中 · ${esc(hits.join(" · "))}</span>`);
    if (item.usage_hint) notes.push(`<span>适用 · ${esc(item.usage_hint)}</span>`);
    if (item.avoid_when) notes.push(`<span class="annotation-caution">不适用 · ${esc(item.avoid_when)}</span>`);
    if (item.has_fixed_characters === true && !advice) notes.push('<span class="annotation-caution">含固定人物 · 不宜当作纯环境背景</span>');
    if (item.dialogue_suitable === false && !advice) notes.push('<span class="annotation-caution">已标记为不适合普通对话</span>');
    return notes.length ? `<span class="resource-annotation">${notes.join("")}</span>` : "";
  }

  function prepareResourcePickerFilters() {
    const controls = $("#resourceSearch")?.parentElement;
    if (!controls) return;
    let advanced = controls.querySelector(".resource-picker-advanced");
    if (!advanced) {
      advanced = document.createElement("details");
      advanced.className = "resource-picker-advanced";
      advanced.innerHTML = '<summary>更多筛选条件</summary><div class="resource-picker-advanced-grid"></div>';
      $("#resourceCategoryFilter").before(advanced);
      const grid = advanced.querySelector(".resource-picker-advanced-grid");
      ["#resourceCategoryFilter", "#resourcePlaceFilter", "#resourceTimeFilter", "#resourceWeatherFilter", "#resourceTagFilter"]
        .forEach((selector) => grid.append($(selector)));
    }
    advanced.open = false;
    return advanced;
  }

  async function chooseResource(kind, label, callback, context = {}) {
    state.resourcePicker = { kind, label, callback, ...context, openedDraftVersion: state.currentDraft?.draft_version };
    state.resourceItems = [];
    state.resourceOffset = 0;
    state.resourceTotal = 0;
    state.resourceHasMore = false;
    $("#resourceDialogEyebrow").textContent = context.eyebrow || (kind === "backgrounds" ? "背景请求" : "声音指令");
    $("#resourceDialogTitle").textContent = context.title || `选择已登记${label}`;
    $("#resourceSearch").value = "";
    $("#resourceScenePlace").value = "";
    $("#resourceSceneContext").classList.toggle("hidden", !context.sceneCardId);
    $("#resourceSceneSummary").textContent = context.sceneCardId ? "正在读取场景标题和冻结背景标记…" : "";
    ["#resourceGroupFilter", "#resourceSourceFilter", "#resourceCategoryFilter", "#resourcePlaceFilter", "#resourceTimeFilter", "#resourceWeatherFilter", "#resourceTagFilter"].forEach((selector) => { const element = $(selector); if (element) element.value = ""; });
    $("#resourceReadyFilter").checked = kind === "backgrounds";
    const backgroundControls = ["#resourceGroupFilter", "#resourceSourceFilter", "#resourceCategoryFilter", "#resourcePlaceFilter", "#resourceTimeFilter", "#resourceWeatherFilter", "#resourceTagFilter", ".resource-ready-filter"];
    backgroundControls.forEach((selector) => $(selector)?.classList.toggle("hidden", kind !== "backgrounds" || context.source === "library"));
    const advanced = prepareResourcePickerFilters();
    if (advanced) advanced.hidden = kind !== "backgrounds" || context.source === "library";
    $("#resourceDialogStatus").textContent = context.status || (kind === "backgrounds" ? "浏览完整背景库；选择后只将该背景加入当前任务。" : "只显示当前制作任务冻结的资源索引。");
    $("#resourcePickerCount").textContent = "正在读取候选";
    $("#resourceResults").innerHTML = '<p class="empty">正在读取素材。</p>';
    $("#resourceDialog").showModal();
    await searchResources("", { reset: true });
  }

  function observeResourcePageEnd() {
    resourcePageObserver?.disconnect();
    if (state.resourcePicker?.kind !== "backgrounds" || !state.resourceHasMore || state.resourceLoading || !$("#resourceDialog").open || typeof IntersectionObserver === "undefined") return;
    const sentinel = document.createElement("div");
    sentinel.className = "resource-page-end";
    sentinel.textContent = "继续下滑加载更多";
    sentinel.setAttribute("role", "status");
    $("#resourceResults").append(sentinel);
    const scrollRoot = $("#resourceDialog .resource-picker-shell");
    resourcePageObserver = new IntersectionObserver((entries) => {
      if (entries.some(entry => entry.isIntersecting) && !state.resourceLoading && $("#resourceDialog").open) {
        resourcePageObserver.disconnect();
        searchResources(null, { reset: false });
      }
    }, { root: scrollRoot, rootMargin: "180px 0px", threshold: 0 });
    resourcePageObserver.observe(sentinel);
  }

  async function searchResources(query = null, options = {}) {
    clearTimeout(resourceSearchTimer);
    const picker = state.resourcePicker;
    const reset = options.reset !== false;
    if (!picker || (state.resourceLoading && !reset)) return;
    resourceSearchController?.abort();
    const searchController = new AbortController();
    resourceSearchController = searchController;
    resourcePageObserver?.disconnect();
    $("#resourceResults .resource-page-end")?.remove();
    let succeeded = false;
    const requestId = (state.resourceSearchEpoch || 0) + 1;
    state.resourceSearchEpoch = requestId;
    const runId = state.currentRun?.run_id;
    const isCurrent = () => state.resourcePicker === picker && state.resourceSearchEpoch === requestId && state.currentRun?.run_id === runId;
    const search = query === null ? $("#resourceSearch").value : query;
    if (reset) {
      state.resourceItems = [];
      state.resourceOffset = 0;
      state.resourceHasMore = false;
      $("#resourceResults").scrollTop = 0;
      $("#resourceResults").innerHTML = '<p class="empty">正在匹配素材标记…</p>';
      $("#resourcePickerCount").textContent = "正在读取候选";
    }
    state.resourceLoading = true;
    $("#resourceLoadMore").disabled = true;
    $("#resourceLoadMore").textContent = "加载更多";
    if (!reset) $("#resourceDialogStatus").textContent = "正在加载更多背景…";
    try {
      const isLibrary = picker.source === "library";
      const params = new URLSearchParams({
        q: search,
        offset: String(state.resourceOffset),
        limit: "80",
      });
      if (!isLibrary && picker.kind === "backgrounds") {
        params.set("scope", "library");
        const filters = {
          group: resourceFilterValue("#resourceGroupFilter"),
          source: resourceFilterValue("#resourceSourceFilter"),
          category: resourceFilterValue("#resourceCategoryFilter"),
          place: resourceFilterValue("#resourcePlaceFilter"),
          time: resourceFilterValue("#resourceTimeFilter"),
          weather: resourceFilterValue("#resourceWeatherFilter"),
          tags: resourceFilterValue("#resourceTagFilter"),
          ready: $("#resourceReadyFilter").checked ? "1" : "0",
        };
        if (picker.sceneCardId) {
          params.set("scene_card_id", picker.sceneCardId);
          params.set("scene_place", $("#resourceScenePlace").value.trim());
          params.set("scene_space", filters.place);
          params.set("scene_time", filters.time);
          params.set("scene_weather", filters.weather);
          delete filters.place; delete filters.time; delete filters.weather;
        }
        Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
      }
      const path = isLibrary
        ? `/custom-assets?kind=background&${params.toString()}`
        : state.currentRun
          ? `/production-runs/${encodeURIComponent(state.currentRun.run_id)}/resources/${picker.kind}?${params.toString()}`
          : `/resources/${picker.kind}?${params.toString()}`;
      const result = await api(path, { signal: searchController.signal });
      if (!isCurrent()) return;
      if (result.scene_context) {
        const context = result.scene_context;
        const requirements = Object.entries(context.requirements || {}).map(([key, value]) => `${{ place: "地点", time: "时间", space: "室内外", weather: "天气" }[key] || key}：${value}（${context.sources?.[key] || "待核对"}）`);
        const counts = context.counts || {};
        $("#resourceSceneSummary").textContent = `“${context.title}” · ${requirements.join(" · ") || "标题未明确地点/时间等条件，可补充后核对"}。匹配 ${counts.match || 0} · 信息不足 ${counts.unknown || 0} · 冲突 ${counts.conflict || 0}。${(context.notes || []).join("；")}${context.current_background ? `当前背景 ${context.current_background} 保持不变，选择其他素材才会替换。` : "尚未指定背景。"}`;
      }
      const page = result.items || [];
      state.resourceItems = reset ? page : [...state.resourceItems, ...page];
      state.resourceOffset = Number(result.offset || 0) + page.length;
      state.resourceTotal = Number(result.total || state.resourceItems.length);
      state.resourceHasMore = page.length > 0 && (result.has_more === true || state.resourceOffset < state.resourceTotal);
      const note = picker.selectionNote || (picker.kind === "backgrounds" ? "选择后会替换当前卡片的背景指令。" : "选择后会替换当前卡片的声音指令。");
      $("#resourceResults").innerHTML = state.resourceItems.length ? state.resourceItems.map((item) => {
        const rowId = isLibrary ? item.asset_id : item.key;
        const preview = isLibrary
          ? `<span class="resource-thumb media-frame"><img class="resource-thumb background-thumb" src="${API_ROOT}/custom-assets/${encodeURIComponent(item.asset_id)}/preview" alt="" loading="lazy" decoding="async"><span class="preview-placeholder" aria-hidden="true">预览</span></span>`
          : picker.kind === "backgrounds"
            ? previewImage("backgrounds", item.key, resourceDisplayName(item, picker), "resource-thumb background-thumb", item.preview_available === false ? false : null)
            : '<span class="resource-thumb sound-thumb" aria-hidden="true">SE</span>';
        const metadata = resourceMetadataText(item) || note;
        const displayName = resourceDisplayName(item, picker);
        if (picker.kind === "backgrounds") {
          const tags = backgroundQuickTags(item);
          const current = item.scene_match?.current === true;
          return `<article class="background-gallery-item${current ? " is-current" : ""}"><button type="button" class="resource-tile background-gallery-select" data-resource-key="${esc(rowId)}" aria-label="选择 ${esc(picker.label)} ${esc(displayName)}">${preview}${current ? '<span class="resource-tile-source">当前使用</span>' : ""}<span class="resource-tile-copy"><strong title="${esc(displayName)}">${esc(displayName)}</strong>${tags ? `<small>${esc(tags)}</small>` : ""}</span></button><details class="background-gallery-details"><summary aria-label="查看 ${esc(displayName)} 的素材详情">素材详情</summary><div class="background-gallery-detail-body"><span>${esc(resourceSourceLabel(item))}</span><code>${esc(item.key || item.asset_id || "")}</code>${item.description ? `<p>${esc(item.description)}</p>` : ""}${resourceAnnotationMarkup(item, search)}</div></details></article>`;
        }
        return `<button type="button" class="resource-tile" data-resource-key="${esc(rowId)}" aria-label="选择 ${esc(picker.label)} ${esc(displayName)}">${preview}<span class="resource-tile-source">${esc(resourceSourceLabel(item))}</span><span class="resource-tile-copy"><strong>${esc(displayName)}</strong><small>${esc(item.key || item.asset_id || "")}</small><small>${esc(metadata)}</small>${picker.kind === "backgrounds" ? resourceAnnotationMarkup(item, search) : ""}</span></button>`;
      }).join("") : `<p class="empty">${esc(picker.emptyText || (picker.kind === "backgrounds" ? "当前 AA 工作区没有符合筛选的背景。可调整筛选，或先到“制作素材”导入 AA 本地资源。" : "没有匹配的已登记素材。"))}</p>`;
      $$('[data-resource-key]').forEach((button) => button.addEventListener("click", async () => {
        const selected = isLibrary
          ? state.resourceItems.find((item) => item.asset_id === button.dataset.resourceKey)
          : state.resourceItems.find((item) => item.key === button.dataset.resourceKey);
        if (!selected || !isCurrent() || state.resourceSelecting) return;
        if (selected.scene_match?.conflicts?.length) {
          state.resourceSelecting = true;
          let accepted;
          try {
            accepted = await askConfirmation({ title: "这个背景与场景条件有冲突", body: `${selected.scene_match.conflicts.join("\n")}\n\n仍要替换当前场景背景吗？正文不会改变。`, confirmLabel: "仍然采用", danger: true });
          } finally { state.resourceSelecting = false; }
          if (!accepted || !isCurrent()) return;
        }
        if (picker.sceneCardId && picker.openedDraftVersion !== state.currentDraft?.draft_version) {
          $("#resourceDialogStatus").textContent = "草稿已变化，请关闭并重新打开背景选择后再采用。";
          return;
        }
        $("#resourceDialog").close();
        await picker.callback(selected);
      }));
      $("#resourcePickerCount").textContent = state.resourceItems.length ? `已显示 ${state.resourceItems.length} / ${state.resourceTotal} 个候选` : "没有匹配候选";
      $("#resourceDialogStatus").textContent = state.resourceItems.length ? `找到 ${state.resourceTotal} 个${picker.label}。${note}` : "";
      $("#resourceLoadMore").hidden = !state.resourceHasMore || (picker.kind === "backgrounds" && typeof IntersectionObserver !== "undefined");
      succeeded = true;
    } catch (error) {
      if (searchController.signal.aborted) return;
      if (isCurrent()) {
        $("#resourceDialogStatus").textContent = error.message;
        if (reset) $("#resourceResults").innerHTML = '<p class="empty">读取失败，请重新搜索或调整筛选后重试。</p>';
        $("#resourceLoadMore").hidden = false;
        $("#resourceLoadMore").textContent = "重试加载";
        $("#resourceLoadMore").dataset.retryReset = reset ? "true" : "false";
      }
    } finally {
      if (isCurrent()) {
        state.resourceLoading = false;
        $("#resourceLoadMore").disabled = false;
        if (succeeded) {
          delete $("#resourceLoadMore").dataset.retryReset;
          observeResourcePageEnd();
        }
      }
    }
  }

  function assetLibraryItem(item, kind) {
    const key = item.key || item.identifier || "";
    const name = resourceDisplayName(item, { kind });
    const preview = kind === "characters" || kind === "backgrounds" || kind === "cg"
      ? previewImage(kind, key, name, `resource-thumb ${kind === "characters" ? "avatar-thumb" : kind === "cg" ? "cg-thumb" : "background-thumb"}`, item.preview_available === false ? false : null)
      : '<span class="resource-thumb sound-thumb" aria-hidden="true">SE</span>';
    const usage = state.assetUsage[`${kind}:${key}`] || [];
    const usageText = usage.length ? `本任务已使用 ${usage.length} 处` : "本任务尚未使用";
    const detail = kind === "characters"
      ? `${item.club || "未标注社团"} · ${item.face_count || 0} 个表情`
      : kind === "backgrounds" ? (resourceMetadataText(item) || "场景与 CG 背景") : kind === "sounds" ? "音效指令资源" : "@popup 插图资源";
    const imported = item.source === "task_import";
    const source = imported ? "本任务导入" : isCustomCharacterResource(item) ? "AA 本机自定义" : "任务冻结快照";
    const selected = String(state.selectedAssetKey || "") === String(key);
    return `<article class="asset-library-item ${selected ? "is-selected" : ""}" data-asset-key="${esc(key)}" tabindex="0" role="button" aria-pressed="${selected}">${preview}<div><strong>${esc(name)}</strong><small class="asset-technical-key" aria-hidden="true">${esc(key)}</small><small>${esc(detail)}</small><small class="asset-usage ${usage.length ? "used" : "unused"}">${esc(usageText)}</small></div><div class="asset-item-actions"><span class="asset-source ${imported ? "imported" : ""}">${source}</span></div></article>`;
  }

  function renderAssetWorkbenchDetail(item = null) {
    const target = $("#assetWorkbenchDetail");
    if (!target) return;
    if (!item) {
      target.innerHTML = '<div class="asset-detail-empty"><strong>选择一项素材</strong><p>右侧会显示来源、预览、表情数量和当前任务使用位置。</p></div>';
      return;
    }
    const kind = state.assetLibraryKind;
    const key = item.key || item.identifier || "";
    const name = item.name || key;
    const preview = kind === "characters" || kind === "backgrounds" || kind === "cg"
      ? previewImage(kind, key, name, `asset-detail-preview ${kind === "characters" ? "avatar-thumb" : "background-thumb"}`, item.preview_available === true)
      : '<span class="asset-detail-preview asset-detail-sound">SE</span>';
    const usage = state.assetUsage[`${kind}:${key}`] || [];
    const imported = item.source === "task_import";
    const source = imported ? "本任务导入" : kind === "characters" && isCustomCharacterResource(item) ? "AA 本机自定义" : resourceSourceLabel(item);
    const metadata = kind === "characters"
      ? [`社团：${item.club || "未标注"}`, `Identifier：${key}`, `服装：${item.outfit_key || "未标注"}`, `${item.face_count || 0} 个已登记表情`]
      : [resourceMetadataText(item) || "尚未补充语义标签", `素材键：${key}`];
    const remove = imported ? `<button type="button" class="asset-remove" data-remove-asset-id="${esc(item.asset_id || "")}" data-remove-asset-name="${esc(name)}" ${usage.length ? "disabled title=\"已被当前任务使用，请先替换引用\"" : ""}>${usage.length ? "正在使用" : "移除导入素材"}</button>` : "";
    target.innerHTML = `<header><small>${esc(kind === "characters" ? "骨骼角色" : kind === "backgrounds" ? "背景" : kind === "sounds" ? "音效" : "插图")}</small><h4>${esc(name)}</h4><span>${esc(source)}</span></header><div class="asset-detail-media">${preview}</div>${kind === "backgrounds" ? resourceAnnotationMarkup(item) : ""}<div class="asset-detail-tags">${metadata.map((value) => `<span>${esc(value)}</span>`).join("")}</div><p>${usage.length ? `当前任务使用位置：${esc(usage.slice(0, 6).map((row) => row.line_no ? `第 ${row.line_no} 张` : row.label).join("、"))}` : "当前任务尚未使用；选择素材不会自动写入场景。"}</p>${kind === "characters" ? '<section class="asset-detail-note"><strong>表情标注</strong><p>可继续使用已登记的编号表情。AI 视觉标注从导入素材流程启动，不会修改 AA manifest。</p></section>' : ""}<footer>${remove}<button type="button" class="primary" data-close-dialog="assetLibraryDialog">返回任务使用</button></footer>`;
    $$('[data-remove-asset-id]').forEach((button) => button.addEventListener("click", () => removeTaskAsset(button.dataset.removeAssetId, button.dataset.removeAssetName)));
  }

  function bindAssetLibraryItems() {
    $$(".asset-library-item").forEach((row) => {
      const select = () => {
        state.selectedAssetKey = row.dataset.assetKey;
        $$(".asset-library-item").forEach((item) => item.classList.toggle("is-selected", item === row));
        const selected = state.assetLibraryItems.find((item) => String(item.key || item.identifier || "") === String(row.dataset.assetKey));
        renderAssetWorkbenchDetail(selected || null);
      };
      row.addEventListener("click", select);
      row.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); select(); } });
    });
  }

  async function loadAssetLibrary({ reset = false } = {}) {
    if (reset) { state.assetLibraryOffset = 0; state.assetLibraryItems = []; state.selectedAssetKey = null; renderAssetWorkbenchDetail(); }
    const query = $("#assetLibrarySearch").value.trim();
    const kind = state.assetLibraryKind;
    try {
      const path = state.currentRun
        ? `/production-runs/${encodeURIComponent(state.currentRun.run_id)}/resources/${kind}?q=${encodeURIComponent(query)}&offset=${state.assetLibraryOffset}&limit=36${kind === "backgrounds" ? "&scope=library" : ""}`
        : `/resources/${kind}?q=${encodeURIComponent(query)}&offset=${state.assetLibraryOffset}&limit=36${kind === "backgrounds" ? "&scope=library" : ""}`;
      const result = await api(path);
      const incoming = result.items || [];
      state.assetLibraryItems = reset || state.assetLibraryOffset === 0 ? incoming : [...state.assetLibraryItems, ...incoming];
      const sort = $("#assetLibrarySort")?.value || "recent";
      const sorted = [...state.assetLibraryItems].sort((a, b) => {
        if (sort === "name") return String(a.name || a.key || a.identifier || "").localeCompare(String(b.name || b.key || b.identifier || ""), "zh-CN");
        if (sort === "usage") return (state.assetUsage[`${kind}:${b.key || b.identifier || ""}`]?.length || 0) - (state.assetUsage[`${kind}:${a.key || a.identifier || ""}`]?.length || 0);
        return Number(b.source === "task_import") - Number(a.source === "task_import");
      });
      $("#assetLibraryResults").innerHTML = sorted.length ? sorted.map((item) => assetLibraryItem(item, kind)).join("") : '<p class="empty">没有匹配的已登记素材。</p>';
      state.assetLibraryTotal = result.total || 0;
      state.assetLibraryOffset += incoming.length;
      bindAssetLibraryItems();
      const label = kind === "characters" ? "角色骨骼" : kind === "backgrounds" ? "背景" : kind === "sounds" ? "音效" : "插图";
      $("#assetWorkbenchReadState").textContent = state.assetWorkbenchContext
        ? `${state.assetWorkbenchContext} 已读取 ${state.assetLibraryItems.length} / ${state.assetLibraryTotal} 个${label}。`
        : `已读取 ${state.assetLibraryItems.length} / ${state.assetLibraryTotal} 个${label}；这里只管理本任务可见素材。`;
      $("#assetLibraryStatus").textContent = result.total ? `找到 ${result.total} 个${label}。选择左侧条目查看详情。` : "没有匹配的已登记素材。";
      $("#assetLibraryMore").disabled = !result.has_more;
    } catch (error) { $("#assetLibraryStatus").textContent = error.message; }
  }

  function openAssetLibrary({ preserveContext = false } = {}) {
    if (!preserveContext) state.assetWorkbenchContext = "";
    $("#assetLibrarySearch").value = "";
    $("#assetLibrarySort").value = "recent";
    state.selectedAssetKey = null;
    renderAssetWorkbenchDetail();
    $("#assetLibraryDialog").showModal();
    const usageRequest = state.currentRun ? api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/resource-usage`).then((result) => { state.assetUsage = result.usage || {}; }).catch(() => { state.assetUsage = {}; }) : Promise.resolve();
    usageRequest.then(() => loadAssetLibrary({ reset: true }));
  }

  async function removeTaskAsset(assetId, name) {
    if (!assetId || !state.currentRun || !state.currentDraft) return;
    if (!await askConfirmation({ title: `移除“${name}”？`, body: "它会从当前任务的可用素材中删除，不会写入 AA 工作区。", confirmLabel: "移除素材", danger: true })) return;
    try {
      setBusy(true);
      $("#assetLibraryStatus").textContent = `正在移除“${name}”…`;
      const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/assets/${encodeURIComponent(assetId)}`, {
        method: "DELETE", body: JSON.stringify({ expected_draft_version: state.currentDraft.draft_version }),
      });
      applyRun(result);
      const usage = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/resource-usage`);
      state.assetUsage = usage.usage || {};
      await loadAssetLibrary({ reset: true });
      toast(`已移除“${name}”。相关卡片已回到待审，请在审查页确认。`, "warning");
    } catch (error) { handleError(error); $("#assetLibraryStatus").textContent = error.message || "移除素材失败。"; } finally { setBusy(false); }
  }

  function selectedAssetImportKind() {
    return document.querySelector('input[name="assetImportKind"]:checked')?.value || "background";
  }

  function ensureSpineRenderControl() {
    const host = $("#assetCharacterFields");
    if (!host || $("#renderSpinePreview")) return;
    const label = document.createElement("label");
    label.id = "assetSpineFields";
    label.className = "spine-render-option";
    label.innerHTML = '<span><input id="renderSpinePreview" type="checkbox">先渲染编号表情，再让模型查看</span><small>只生成临时视觉证据，不修改原始 ZIP；需要本机配置 Spine CLI。</small>';
    host.appendChild(label);
  }

  function updateAssetImportFileName() {
    const file = $("#assetImportFile").files?.[0];
    $("#assetImportFileName").textContent = file?.name || "尚未选择文件";
  }

  function updateAssetImportForm() {
    ensureSpineRenderControl();
    const kind = selectedAssetImportKind();
    const file = $("#assetImportFile");
    file.value = "";
    file.accept = ["background", "cg"].includes(kind) ? ".png,.jpg,.jpeg" : kind === "sound" ? ".wav" : ".zip";
    updateAssetImportFileName();
    $("#assetCharacterFields").classList.toggle("hidden", kind !== "character");
    $("#assetSpineFields")?.classList.toggle("hidden", kind !== "character");
    $("#assetBackgroundFields").classList.toggle("hidden", !["background", "cg"].includes(kind));
    $("#assetValidationResult").className = "asset-validation empty";
    $("#assetValidationResult").textContent = "选择文件后，点击“上传并检查”。";
    $("#assetRecognitionResult").className = "asset-recognition empty";
    $("#assetRecognitionResult").innerHTML = "<strong>可选的图片识别</strong><p>检查通过后，可以让已配置的视觉模型查看预览并提出标签或表情建议；不接受也可以直接手工登记。</p>";
    $("#assetImportStatus").textContent = kind === "character" ? "角色 ZIP 必须含 skel、atlas、贴图和头像。" : kind === "cg" ? "插图会在构建时写入 PopupOverrides，可在高级指令中用 @popup 调用。" : "尚未选择文件。";
    $("#registerAssetImport").disabled = true;
    $("#recognizeAssetImport").disabled = true;
    state.assetImport = null;
  }

  function setImportStep(step) {
    $$('[data-import-step]').forEach((item) => item.classList.toggle("active", Number(item.dataset.importStep) <= step));
  }

  function openAssetImport() {
    if (!state.currentRun || !state.currentDraft) {
      toast("先打开一个制作任务，素材会登记到这个任务中。", "warning");
      return;
    }
    $("#assetImportFile").value = "";
    $("#assetLabel").value = "";
    $("#assetIdentifier").value = "";
    $("#assetDisplayName").value = "";
    $("#assetNickname").value = "";
    $("#renderSpinePreview") && ($("#renderSpinePreview").checked = false);
    setImportStep(1);
    updateAssetImportForm();
    $("#assetImportDialog").showModal();
  }

  function importPayload() {
    const kind = selectedAssetImportKind();
    const payload = { kind, upload_token: state.assetImport?.upload_token };
    if (kind === "character") {
      payload.identifier = $("#assetIdentifier").value.trim();
      payload.display_name = $("#assetDisplayName").value.trim();
      payload.nickname = $("#assetNickname").value.trim();
      payload.render_spine_preview = $("#renderSpinePreview")?.checked === true;
    }
    if (["background", "cg"].includes(kind)) payload.labels = { label: $("#assetLabel").value.trim() };
    const recognition = state.assetImport?.recognition;
    if (recognition?.digest) {
      payload.recognition_digest = recognition.digest;
      payload.accept_recognition = state.assetImport.recognitionAccepted === true;
    }
    return payload;
  }

  function renderAssetValidation(validation) {
    const target = $("#assetValidationResult");
    const issues = validation.issues || [];
    const meta = validation.metadata || {};
    const summary = ["background", "cg"].includes(validation.kind)
      ? `${meta.width || "-"} × ${meta.height || "-"} · ${meta.format || "未知格式"}`
      : validation.kind === "sound"
        ? `${meta.codec || "-"} · ${meta.sample_rate || "-"} Hz · ${meta.duration || "-"} 秒`
        : `${meta.spine_version || "未知版本"} · ${meta.faces?.length || 0} 个表情线索`;
    target.className = `asset-validation ${validation.ok ? "valid" : "invalid"}`;
    target.innerHTML = `<strong>${validation.ok ? "检查通过，可以登记" : "检查未通过"}</strong><p>${esc(summary)}</p>${issues.length ? `<ul>${issues.map((issue) => `<li>${esc(issue.message)}</li>`).join("")}</ul>` : "<p>没有阻断问题。登记后会加入当前任务的冻结素材清单。</p>"}`;
  }

  function renderAssetRecognition(recognition) {
    const target = $("#assetRecognitionResult");
    if (!target) return;
    if (!recognition?.candidate) {
      target.className = "asset-recognition empty";
      target.innerHTML = "<strong>可选的图片识别</strong><p>不接受识别也可以直接手工登记。角色骨骼只会根据静态头像、贴图和已验证的表情 ID 提出保守建议。</p>";
      return;
    }
    const candidate = recognition.candidate;
    const expressions = Array.isArray(candidate.expression_suggestions) ? candidate.expression_suggestions : [];
    const accepted = state.assetImport?.recognitionAccepted === true;
    target.className = `asset-recognition ${accepted ? "accepted" : "proposal"}`;
    const evidence = recognition.evidence || {};
    const calibrationCount = Array.isArray(evidence.calibration) ? evidence.calibration.length : 0;
    const evidenceLabel = selectedAssetImportKind() === "character"
      ? Number(evidence.rendered_animation_count || 0) > 0
        ? `已渲染 ${Number(evidence.rendered_animation_count || 0)} 个 Spine 表情预览；仅作为视觉证据${calibrationCount ? `；${calibrationCount} 项需要人工校准` : ""}`
        : `静态头像/贴图 + ${Number(evidence.validated_face_ids?.length || 0)} 个已验证表情 ID；未渲染 Spine 动画`
      : "只基于本次上传内容";
    target.innerHTML = `<header><strong>${accepted ? "已选择采用识别建议" : "识别建议待确认"}</strong><span>${esc(evidenceLabel)}</span></header><p>${esc(candidate.summary || "模型没有提供摘要；可以继续手工填写。")}</p>${candidate.title ? `<dl><div><dt>建议名称</dt><dd>${esc(candidate.title)}</dd></div><div><dt>标签</dt><dd>${esc((candidate.tags || []).join("、") || "未提供")}</dd></div>${candidate.mood ? `<div><dt>氛围</dt><dd>${esc(candidate.mood)}</dd></div>` : ""}</dl>` : ""}${expressions.length ? `<section><b>表情建议</b><ul>${expressions.map(item => `<li><span>${esc(item.face_id)}</span>${esc(item.label)}</li>`).join("")}</ul></section>` : ""}<button type="button" class="quiet" id="acceptAssetRecognition">${accepted ? "取消采用，改用手工信息" : "采用这些建议"}</button>`;
    $("#assetImportStatus").textContent = accepted ? "识别建议已加入登记内容；仍会先写入当前任务。" : "识别建议仅供查看；点击“采用这些建议”后才会随登记保存。";
  }

  async function recognizeAssetImport() {
    if (!state.assetImport?.validation?.ok || !state.currentRun) return;
    try {
      setBusy(true);
      $("#recognizeAssetImport").disabled = true;
      $("#assetImportStatus").textContent = "正在读取图片预览并生成识别建议…";
      const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/assets/recognize`, {
        method: "POST", body: JSON.stringify(importPayload()),
      });
      state.assetImport.recognition = result.recognition;
      state.assetImport.recognitionAccepted = false;
      renderAssetRecognition(result.recognition);
    } catch (error) {
      const message = error.code === "asset_recognition_not_configured"
        ? "当前没有配置视觉模型；可以跳过识别，继续手工登记。"
        : ["asset_spine_render_not_configured", "asset_spine_render_failed", "asset_spine_render_empty"].includes(error.code)
          ? (error.message || "Spine 表情预览没有生成；可以关闭渲染并继续静态识别。")
        : error.message || "识别建议生成失败；可以跳过识别后手工登记。";
      $("#assetRecognitionResult").className = "asset-recognition unavailable";
      $("#assetRecognitionResult").innerHTML = `<strong>没有生成识别建议</strong><p>${esc(message)}</p>`;
      $("#assetImportStatus").textContent = "识别未完成；登记不会被阻断。";
    } finally {
      $("#recognizeAssetImport").disabled = false;
      setBusy(false);
    }
  }

  async function validateAssetImport() {
    const file = $("#assetImportFile").files?.[0];
    const kind = selectedAssetImportKind();
    if (!file) { $("#assetImportStatus").textContent = "请先选择要导入的文件。"; return; }
    if (kind === "character" && (!$("#assetIdentifier").value.trim() || !$("#assetDisplayName").value.trim())) {
      $("#assetImportStatus").textContent = "角色骨骼需要填写角色标识和显示名称。"; return;
    }
    try {
      setBusy(true); setImportStep(2);
      $("#assetImportStatus").textContent = "正在上传并检查格式…";
      const upload = await fetch(`${API_ROOT}/production-runs/${encodeURIComponent(state.currentRun.run_id)}/assets`, {
        method: "POST", headers: { "Content-Type": "application/octet-stream", "X-HaloCue-Filename": encodeURIComponent(file.name) }, body: file,
      });
      const uploadResult = await upload.json();
      if (!upload.ok || uploadResult.ok === false) throw Object.assign(new Error(uploadResult.error?.message || "上传失败"), { code: uploadResult.error?.code });
      state.assetImport = uploadResult;
      const validationResult = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/assets/validate`, { method: "POST", body: JSON.stringify(importPayload()) });
      state.assetImport.validation = validationResult.validation;
      renderAssetValidation(validationResult.validation);
      $("#registerAssetImport").disabled = !validationResult.validation.ok;
      $("#recognizeAssetImport").disabled = !validationResult.validation.ok || kind === "sound";
      $("#assetImportStatus").textContent = validationResult.validation.ok ? "检查完成。确认无误后，登记到当前任务。" : "请根据检查结果更换文件或修改角色信息。";
    } catch (error) { handleError(error); $("#assetImportStatus").textContent = error.message || "上传或检查失败。"; } finally { setBusy(false); }
  }

  async function registerAssetImport() {
    if (!state.assetImport?.validation?.ok) return;
    try {
      setBusy(true); setImportStep(3);
      $("#assetImportStatus").textContent = "正在登记到当前任务…";
      const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/assets`, {
        method: "PUT", body: JSON.stringify({ ...importPayload(), expected_draft_version: state.currentDraft.draft_version }),
      });
      applyRun(result);
      $("#assetImportDialog").close();
      if ($("#assetLibraryDialog").open) loadAssetLibrary({ reset: true });
      const sceneTarget = state.sceneBackgroundTarget;
      state.sceneBackgroundTarget = null;
      if (sceneTarget && selectedAssetImportKind() === "background" && result.asset?.key) {
        const sceneCard = state.currentDraft?.cards?.find((card) => card.card_id === sceneTarget.card_id);
        if (sceneCard) await insertSceneBackground(sceneCard, { ...result.asset, source: "task_import" });
        else toast("背景已登记到任务；原场景已变化，请从背景选择器手动使用。", "warning");
      } else {
        toast(`已登记“${result.asset?.name || result.asset?.key || "素材"}”。现在可在当前任务中选择使用。`);
      }
    } catch (error) { handleError(error); $("#assetImportStatus").textContent = error.message || "登记失败。"; } finally { setBusy(false); }
  }

  async function approveCards(cardIds = null) {
    try {
      const result = await api(`/production-runs/${state.currentRun.run_id}/review/approve`, { method: "POST", body: JSON.stringify({ card_ids: cardIds, expected_draft_version: state.currentDraft.draft_version }) });
      applyRun(result); toast(cardIds ? "卡片已标记为已审。" : "全部卡片已标记为已审。");
    } catch (error) { handleError(error); }
  }

  async function validateDraft() {
    try {
      const result = await api(`/production-runs/${state.currentRun.run_id}/validate`, { method: "POST", body: "{}" });
      await refreshCurrentRun(); toast(result.review_ready ? "检查通过。" : "检查完成：仍有需要处理的问题。", result.review_ready ? "normal" : "warning");
    } catch (error) { handleError(error); }
  }

  async function pollJob(jobId, label) {
    if (jobPolls.has(jobId)) return jobPolls.get(jobId);
    const polling = (async () => {
      let offlineDelay = 1000;
      while (true) {
        let job;
        try {
          const result = await api(`/jobs/${encodeURIComponent(jobId)}`, {
            timeoutMs: JOB_POLL_TIMEOUT_MS,
          });
          job = result.job;
          offlineDelay = 1000;
        } catch (error) {
          if (
            error.code === "job_not_found"
            || (error.status && !TRANSIENT_JOB_POLL_STATUSES.has(error.status))
          ) throw error;
          if (state.currentJob?.job_id === jobId) {
            state.currentJob.progress = { ...(state.currentJob.progress || {}), detail: "连接暂时中断，正在继续获取后台状态。" };
            renderGeneration();
          }
          await new Promise((resolve) => setTimeout(resolve, offlineDelay));
          offlineDelay = Math.min(5000, offlineDelay + 1000);
          continue;
        }
        if (job.run_id === state.currentRun?.run_id && ["direction_generation", "compile"].includes(job.kind)) {
          state.currentJob = job;
          renderGeneration();
          renderReview();
        }
        if (terminalJobStates.has(job.state)) {
          if (job.run_id === state.currentRun?.run_id) await refreshCurrentRun();
          if (job.state === "succeeded") toast(`${label}已完成。`);
          else if (job.state === "paused") toast(`${label}已暂停，检查点已保留。`, "warning");
          else if (job.state === "cancelled") toast(`${label}已结束，未完成内容没有写入草稿。`, "warning");
          else if (job.state === "superseded") toast(`${label}的旧结果已丢弃。`, "warning");
          if (["failed", "interrupted"].includes(job.state)) {
            throw Object.assign(new Error(job.error?.message || `${label}未完成`), {
              code: job.error?.code || "job_failed",
              details: job.error?.details || {},
            });
          }
          return job;
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    })();
    jobPolls.set(jobId, polling);
    try { return await polling; } finally { jobPolls.delete(jobId); }
  }

  async function compileRun() {
    if (!state.currentRun || !state.currentDraft) return;
    const button = $("#compileButton");
    button.disabled = true;
    try {
      const result = await api(`/production-runs/${state.currentRun.run_id}/compile`, { method: "POST", body: JSON.stringify({ expected_draft_version: state.currentDraft.draft_version }) });
      state.currentJob = result.job;
      await refreshCurrentRun();
      await pollJob(result.job.job_id, "AA 编译");
    } catch (error) { handleError(error); } finally {
      // renderReview() replaces the inspector. Reattach the install controls afterwards.
      renderReview();
      renderInstallPanel();
    }
  }

  function renderInstallPanel() {
    const compiled = Boolean(state.currentRun && ["compiled", "installed"].includes(state.currentRun.state));
    const button = $("#openInstallDialog");
    if (button) {
      button.hidden = !compiled;
      button.classList.toggle("hidden", !compiled);
      button.textContent = state.currentRun?.state === "installed" ? "查看安装结果" : "安装到 AA";
    }
  }

  function installNamePreview() {
    const category = String($("#installCategory")?.value || "").trim();
    const story = String($("#installStoryName")?.value || state.installOptions?.source_project || "").trim();
    return [category, story].filter(Boolean).join("-") || "—";
  }

  function updateInstallNamePreview() {
    const preview = $("#installProjectPreview");
    if (preview) preview.textContent = installNamePreview();
  }

  async function loadInstallOptions() {
    if (!state.currentRun?.last_build_id) return;
    $("#installBuildName").textContent = state.currentRun.last_build_id;
    $("#installBuildState").textContent = state.currentRun.state === "installed" ? "已经安装" : "编译完成";
    $("#installDialogStatus").textContent = "正在读取安装选项。";
    const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/install-options?build_id=${encodeURIComponent(state.currentRun.last_build_id)}`);
    state.installOptions = result;
    $("#installCategory").value = result.default_category || "";
    $("#installStoryName").value = result.default_story_name || state.currentRun.project || "";
    $("#installCategoryOptions").innerHTML = (result.categories || []).map((item) => `<option value="${esc(item)}"></option>`).join("");
    updateInstallNamePreview();
    if (result.existing_install?.project) {
      $("#installTargetStatus").textContent = `检测到现有安装：${result.existing_install.project}。使用同名目标会更新该工程。`;
    } else {
      $("#installTargetStatus").textContent = "尚未检测目标冲突。";
    }
    await checkInstallTarget();
  }

  async function openInstallDialog() {
    if (!state.currentRun || !["compiled", "installed"].includes(state.currentRun.state)) {
      toast("请先完成编译。", "warning");
      return;
    }
    $("#installDialog").showModal();
    $("#installRun").disabled = true;
    try {
      await loadInstallOptions();
    } catch (error) {
      $("#installDialogStatus").textContent = error.message;
      handleError(error);
    }
  }

  function scheduleInstallCheck() {
    updateInstallNamePreview();
    if (state.installCheckTimer) clearTimeout(state.installCheckTimer);
    state.installCheckTimer = setTimeout(checkInstallTarget, 280);
  }

  async function checkInstallTarget() {
    if (!state.currentRun?.last_build_id || !$("#installDialog")?.open) return;
    const targetPanel = $(".install-target-preview");
    $("#installRun").disabled = true;
    $("#installTargetStatus").textContent = "正在检查目标名称与现有工程。";
    try {
      const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/install-check`, {
        method: "POST",
        body: JSON.stringify({
          build_id: state.currentRun.last_build_id,
          category: $("#installCategory").value,
          story_name: $("#installStoryName").value,
        }),
      });
      const target = result.target || {};
      $("#installProjectPreview").textContent = target.project || installNamePreview();
      targetPanel.classList.toggle("is-conflict", target.conflict === true);
      if (target.conflict) {
        $("#installTargetStatus").textContent = `目标“${target.project}”已被其他工程占用，请更换分类或剧情名。`;
        $("#installDialogStatus").textContent = "存在名称冲突，暂不能安装。";
      } else {
        $("#installTargetStatus").textContent = target.mode === "update_source"
          ? `将更新当前源工程“${target.project}”。`
          : `将创建重命名副本“${target.project}”。`;
        $("#installDialogStatus").textContent = "目标可用；确认后写入本机 AA 工作区。";
        $("#installRun").disabled = false;
      }
      return result;
    } catch (error) {
      targetPanel.classList.add("is-conflict");
      $("#installTargetStatus").textContent = error.message;
      $("#installDialogStatus").textContent = "安装预检失败。";
      return null;
    }
  }

  async function installCurrentRun() {
    const checked = await checkInstallTarget();
    if (!checked?.target || checked.target.conflict) return;
    if (!await askConfirmation({ title: `安装“${checked.target.project}”到 AA？`, body: "这会在已配置的本机 AA 工作区创建或更新工程；写作正文、ScriptRelease 和 AA 最近项目不会被修改。", confirmLabel: "确认安装" })) return;
    $("#installRun").disabled = true;
    $("#installDialogStatus").textContent = "正在安装并核对落盘结果。";
    try {
      const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/install`, {
        method: "POST",
        body: JSON.stringify({
          build_id: state.currentRun.last_build_id,
          category: $("#installCategory").value,
          story_name: $("#installStoryName").value,
        }),
      });
      applyRun(result);
      const install = result.install || {};
      $("#installBuildState").textContent = "安装完成";
      $("#installAapPath").textContent = install.aap_path || "已写入 AA projects";
      $("#installAssetPath").textContent = install.project_dir || install.asset_path || "已同步工程素材";
      $("#installSavePath").textContent = install.save_dir || install.save_path || "已同步存档镜像";
      $("#installDialogStatus").textContent = `已安装到 ${install.project || checked.target.project}。`;
      toast(`已安装到 ${install.project || checked.target.project}`);
    } catch (error) {
      $("#installDialogStatus").textContent = error.message;
      handleError(error);
    }
  }

  function applyRun(result) {
    adoptRunResult(result);
    loadTaskPreflight();
    updateShell(); renderMapping(); renderGeneration(); renderReview(); renderInstallPanel();
  }

  async function loadModelSettings() {
    try { const result = await api("/settings/direction-model"); state.model = result.model; $("#modelProvider").value = result.model.provider || "openai"; $("#modelBaseUrl").value = result.model.base_url || ""; $("#modelName").value = result.model.model || ""; $("#modelStatus").textContent = result.model.configured ? `已配置 · ${result.model.secret_source}` : "尚未配置"; } catch (error) { handleError(error); }
  }

  function renderSpineCliSettings(result) {
    state.spineCli = result.spine_cli || {};
    const info = state.spineCli;
    const capability = result.capability || {};
    const status = $("#spineCliStatus");
    const capabilityText = $("#spineCliCapability");
    if (!status) return;
    const configured = info.configured === true && info.valid === true && Boolean(info.effective_path);
    const invalidSaved = info.reason === "saved_spine_cli_unavailable"
      || (info.source === "settings" && info.valid === false);
    const invalid = invalidSaved || (Boolean(info.path) && info.valid === false);
    status.className = `environment-status ${configured ? "ready" : "needs-work"}`;
    status.innerHTML = configured
      ? "<strong>Spine 预览已启用</strong><p>导入角色时可以选择先渲染编号表情。渲染结果只作为待确认的视觉证据。</p>"
      : invalid
        ? "<strong>配置路径不可用</strong><p>找不到该程序；请重新选择 Spine.com、Spine.exe 或对应启动脚本。</p>"
        : "<strong>未启用 Spine 预览</strong><p>仍可使用静态头像、贴图和已验证表情 ID；需要动画证据时再配置。</p>";
    const sourceLabels = { settings: "应用设置", environment: "环境变量", legacy_config: "旧版配置", data_config: "数据目录配置", discovered: "自动发现", none: "未选择" };
    const source = info.source || "none";
    status.innerHTML += `<p>当前生效路径：${esc(configured ? info.effective_path : "无")}</p><p>来源：${esc(sourceLabels[source] || source)} (${esc(source)})</p>`;
    if (info.path && !configured) status.innerHTML += `<p>所选路径：${esc(info.path)}</p>`;
    if (info.persisted_path) status.innerHTML += `<p>已保存路径：${esc(info.persisted_path)}</p>`;
    if (invalidSaved) status.innerHTML += "<small>已保存路径不可用，未回退到环境变量或其他配置。请重新选择，或清除已保存路径以使用回退配置。</small>";
    if (capabilityText) {
      capabilityText.textContent = configured && capability.state === "available"
        ? "当前机器可以调用 Spine CLI。渲染仅写入临时 Production 数据目录，识别结果仍需人工确认。"
        : "当前机器没有可用的 Spine CLI。配置后可在角色导入步骤启用临时表情预览。";
    }
    const input = $("#spineCliPath");
    if (input && document.activeElement !== input) input.value = info.path || "";
  }

  async function loadSpineCliSettings() {
    try {
      const result = await api("/settings/spine-cli");
      renderSpineCliSettings(result);
    } catch (error) {
      const status = $("#spineCliStatus");
      if (status) status.innerHTML = `<strong>读取设置失败</strong><p>${esc(error.message || "请稍后重试")}</p>`;
      handleError(error);
    }
  }

  async function saveSpineCli(event) {
    event?.preventDefault();
    const input = $("#spineCliPath");
    const save = $("#saveSpineCli");
    const status = $("#spineCliStatus");
    const path = input?.value.trim() || "";
    if (!path) {
      if (status) status.innerHTML = "<strong>请先填写路径</strong><p>选择 Spine.com、Spine.exe 或对应启动脚本后再保存。</p>";
      input?.focus();
      return;
    }
    if (save) save.disabled = true;
    if (status) status.innerHTML = "<strong>正在检查</strong><p>验证程序路径，不会启动 Spine 或修改素材。</p>";
    try {
      const result = await api("/settings/spine-cli", { method: "POST", body: JSON.stringify({ path }) });
      renderSpineCliSettings(result);
      await refreshCapabilities();
      const info = result.spine_cli || {};
      if (info.valid === true && info.configured === true && info.effective_path) toast("Spine 表情预览设置已保存。", "normal");
      else toast("Spine 配置路径不可用，未启用预览；请重新选择或清除已保存路径。", "error");
    } catch (error) {
      if (status) status.innerHTML = `<strong>保存失败</strong><p>${esc(error.message || "请检查路径后重试")}</p>`;
      handleError(error);
    } finally {
      if (save) save.disabled = false;
    }
  }

  async function clearSpineCli() {
    const clear = $("#clearSpineCli");
    const status = $("#spineCliStatus");
    if (clear) clear.disabled = true;
    if (status) status.innerHTML = "<strong>正在清除</strong><p>之后仍可使用静态识别，不会删除任何素材。</p>";
    try {
      const result = await api("/settings/spine-cli", { method: "POST", body: JSON.stringify({ clear: true }) });
      const input = $("#spineCliPath");
      if (input) input.value = "";
      renderSpineCliSettings(result);
      await refreshCapabilities();
      const info = result.spine_cli || {};
      toast(info.valid === true && info.configured === true && info.effective_path
        ? `已清除保存的 Spine 路径；当前仍可按需预览，来源 ${info.source}：${info.effective_path}`
        : "已清除保存的 Spine 路径；当前没有可用的 Spine CLI，未启用预览。", "normal");
    } catch (error) {
      if (status) status.innerHTML = `<strong>清除失败</strong><p>${esc(error.message || "请稍后重试")}</p>`;
      handleError(error);
    } finally {
      if (clear) clear.disabled = false;
    }
  }

  function showSettingsPane(name) {
    $$('[data-settings-pane]').forEach((button) => button.classList.toggle("active", button.dataset.settingsPane === name));
    $("#settingsWorkspacePane").classList.toggle("hidden", name !== "workspace");
    $("#modelForm").classList.toggle("hidden", name !== "model");
    $("#spineForm").classList.toggle("hidden", name !== "spine");
  }

  async function openSettingsDialog(pane = "workspace") {
    showSettingsPane(pane);
    const dialog = $("#settingsDialog");
    if (!dialog.open) dialog.showModal();
    if (pane === "model") await loadModelSettings();
    else if (pane === "spine") await loadSpineCliSettings();
    else await inspectAaEnvironment(false, true);
  }

  function renderAaEnvironment(result) {
    state.aaEnvironment = result.environment;
    const environment = result.environment || {};
    const workspace = environment.workspace || {};
    const aaResources = environment.aa_resources || {};
    const status = $("#aaEnvironmentStatus");
    const path = workspace.path || "未找到工作区";
    const issue = environment.issues?.[0];
    const active = result.aa_workspace;
    const ready = active?.valid === true;
    const headline = active
      ? (ready ? "当前 AA 制作环境可用" : "当前 AA 制作环境不可用")
      : (workspace.valid ? "检测到可用的 AA 工作区（尚未确认当前生效环境）" : "未检测到可用的 AA 工作区");
    status.className = `environment-status ${ready ? "ready" : "needs-work"}`;
    status.innerHTML = `<strong>${headline}</strong><p>检测路径（${workspace.valid ? "可用" : "不可用"}）：${esc(path)}</p><div><span>工程目录 ${workspace.directories?.projects ? "可用" : "缺失"}</span><span>存档目录 ${workspace.directories?.saves ? "可用" : "缺失"}</span><span>AA 素材目录 ${aaResources.overrides_available || workspace.directories?.overrides ? "可用" : "待选择"}</span></div>${issue ? `<small>${esc(issue.code)} · ${esc(issue.message)}</small>` : ""}`;
    const adopted = result.adopted === true && active?.valid === true;
    if (active) {
      const sourceLabels = { startup: "启动配置", settings: "应用设置", settings_session_override: "本次会话设置", none: "未配置" };
      const source = active.source || "none";
      status.innerHTML += `<p>当前生效路径：${esc(active.valid ? active.path : "无（当前配置不可用）")}</p><p>来源：${esc(sourceLabels[source] || source)} (${esc(source)})</p><p>已保存路径：${esc(active.persisted_path || "无")}</p><p>重启后路径：${esc(active.restart_path || "无")}</p>`;
      if (!active.valid && active.path) status.innerHTML += `<p>当前配置路径不可用：${esc(active.path)}</p>`;
      if (active.session_override) status.innerHTML += "<small>当前采用仅本次会话生效；重启时启动配置优先。</small>";
      else if (active.startup_overrides_saved) status.innerHTML += "<small>启动配置优先，已保存路径未覆盖当前或重启后的工作区。</small>";
    }
    if (!$("#aaSelection").value.trim() && workspace.path) $("#aaSelection").value = workspace.path;
    $("#adoptAaEnvironment").disabled = !workspace.valid || adopted;
    if (adopted) $("#adoptAaEnvironment").textContent = "已采用";
    else $("#adoptAaEnvironment").textContent = "采用此工作区";
  }

  async function rebuildResourceIndex() {
    const button = $("#rebuildResourceIndex");
    if (button) { button.disabled = true; button.textContent = "正在导入资源…"; }
    const importStatus = $("#resourceImportStatus");
    if (importStatus) { importStatus.hidden = false; importStatus.textContent = "正在扫描背景与核验图片，首次生成预览可能需要一些时间。"; }
    try {
      const result = await api("/settings/resource-index:rebuild", { method: "POST", body: "{}", timeoutMs: 300000 });
      const index = result.resource_index || {};
      const media = index.background_media;
      const summary = media ? `背景 ${media.ready || 0} / ${media.total || 0} 项预览就绪` : `${index.backgrounds || 0} 个背景`;
      const report = $("#resourceImportStatus");
      if (report) {
        report.hidden = false;
        report.innerHTML = `<strong>资源导入完成 · ${esc(summary)}</strong><p>已同步背景索引、本地图片和预览；现有任务不会被覆盖。</p>${(index.warnings || []).length ? `<details><summary>查看待检查项</summary><ul>${index.warnings.map(item => `<li>${esc(item)}</li>`).join("")}</ul></details>` : ""}`;
      }
      toast(`资源已导入：${summary}，${index.characters || 0} 个角色。`);
      await refreshCapabilities();
      await inspectAaEnvironment(false, true);
    } catch (error) {
      if (importStatus) importStatus.textContent = error.message;
      handleError(error);
    } finally { if (button) { button.disabled = false; button.textContent = "导入 / 更新 AA 资源"; } }
  }
  async function inspectAaEnvironment(adopt = false, automatic = false) {
    const selection = $("#aaSelection").value.trim();
    $("#aaEnvironmentStatus").innerHTML = "<strong>正在检测</strong><p>读取 AA 程序和工作区配置。</p>";
    try {
      const result = automatic && !selection
        ? await api("/settings/aa-environment")
        : await api("/settings/aa-environment", { method: "POST", body: JSON.stringify({ selection, adopt }) });
      renderAaEnvironment(result);
      if (adopt) {
        await refreshCapabilities();
        const active = result.aa_workspace;
        if (!result.adopted || active?.valid !== true) toast("AA 工作区采用未确认或当前配置不可用，请重新检测。", "error");
        else toast(active.session_override || active.startup_overrides_saved
          ? `AA 制作环境已采用；当前路径：${active.path}。重启时启动配置优先，将使用：${active.restart_path || "无"}。`
          : "AA 制作环境已采用。");
      }
    } catch (error) { handleError(error); }
  }

  async function saveModel(event) {
    event.preventDefault();
    const payload = { provider: $("#modelProvider").value, base_url: $("#modelBaseUrl").value.trim(), model: $("#modelName").value.trim() };
    const key = $("#modelApiKey").value.trim(); if (key) payload.api_key = key;
    try { const result = await api("/settings/direction-model", { method: "POST", body: JSON.stringify(payload) }); state.model = result.model; $("#settingsDialog").close(); await refreshCapabilities(); toast("演出模型设置已保存。"); } catch (error) { handleError(error); }
  }

  async function testModel() {
    try { const result = await api("/settings/direction-model/test", { method: "POST", body: "{}" }); $("#modelStatus").textContent = "连接测试已提交到后台任务。"; await pollJob(result.job.job_id, "模型连接测试"); $("#modelStatus").textContent = "连接测试完成。"; } catch (error) { handleError(error); }
  }

  function taskProgressMarkup(job) {
    const progress = job.progress || {};
    const { percent, indeterminate } = jobProgressDisplay(job);
    if (!jobIsActive(job) && !progress.total && !percent) return "";
    const count = progress.total
      ? `当前块 ${numberLabel(progress.current)} / ${numberLabel(progress.total)}`
      : jobIsActive(job) ? "处理中" : `${Math.round(percent)}%`;
    return `<div class="task-progress-row"><progress max="100" ${indeterminate ? 'aria-label="正在处理，完成比例尚未确定"' : `value="${Math.round(percent)}"`}></progress><span>${esc(count)}</span></div>`;
  }

  function taskMetricsMarkup(job, metrics) {
    if (job.kind !== "direction_generation") return "";
    return `<dl class="task-metrics"><div><dt>请求</dt><dd>${esc(numberLabel(metrics.requests))}</dd></div><div><dt>重试 / 细分</dt><dd>${esc(numberLabel(metrics.retries))}（传输 ${esc(numberLabel(metrics.transport_retries))}） / ${esc(numberLabel(metrics.subdivisions))}</dd></div><div><dt>Token</dt><dd>${esc(numberLabel(metrics.input_tokens))} / ${esc(numberLabel(metrics.output_tokens))}</dd></div><div><dt>缓存</dt><dd>${esc(cacheLabel(metrics))}</dd></div><div><dt>暖缓存</dt><dd>${esc(warmCacheLabel(metrics))}</dd></div><div><dt>失败消耗</dt><dd>${esc(failedCostLabel(metrics))}</dd></div><div><dt>单位产出</dt><dd>${esc(unitCostLabel(metrics))}</dd></div><div><dt>输入裁剪</dt><dd>${esc(promptOptimizationLabel(metrics))}</dd></div></dl>`;
  }

  async function runTaskJobAction(button) {
    if (button.disabled) return;
    const jobId = button.dataset.taskJobId;
    const action = button.dataset.taskJobAction;
    const stateBefore = button.dataset.taskJobState;
    if (["resume", "retry"].includes(action)
      && button.dataset.taskOwnerRun === state.currentRun?.run_id
      && button.dataset.taskDirectionProfile
      && button.dataset.taskDirectionProfile !== state.directionProfile) {
      $("#tasksDialog").close();
      showStage("generation", { force: true });
      toast("当前演出策略已变更，请确认新建生成任务，或选回旧策略继续。", "warning");
      return;
    }
    if (action === "cancel" && stateBefore !== "queued") {
      const confirmed = await askConfirmation({
        title: "结束这个后台任务？",
        body: "已完成的检查点会保留；未完成结果不会写回当前草稿。",
        confirmLabel: "结束任务",
        danger: true,
      });
      if (!confirmed) return;
    }
    button.disabled = true;
    try {
      const result = await api(`/jobs/${encodeURIComponent(jobId)}?action=${encodeURIComponent(action)}`, {
        method: "POST",
        body: "{}",
      });
      const job = result.job;
      if (job?.run_id === state.currentRun?.run_id) {
        state.currentJob = job;
        await refreshCurrentRun();
      }
      await renderTasks();
      if (job && jobIsActive(job)) {
        pollJob(job.job_id, job.label || "后台任务").catch(handleError);
      }
      const messages = {
        pause: "已请求暂停，正在中止当前模型连接并保存检查点。",
        cancel: stateBefore === "queued" ? "排队任务已取消。" : "已请求结束任务。",
        resume: "已从已保存的检查点继续。",
        retry: "已重新提交该阶段，旧任务记录仍会保留。",
      };
      toast(messages[action] || "任务状态已更新。", action === "pause" || action === "cancel" ? "warning" : "normal");
    } catch (error) {
      button.disabled = false;
      handleError(error);
    }
  }

  async function renderTasks() {
    const refresh = $("#refreshTasks");
    refresh.disabled = true;
    try {
      const result = await api("/jobs");
      $("#taskList").innerHTML = result.items?.length ? result.items.slice(0, 30).map((job) => {
        const metrics = generationMetrics(job);
        const failed = ["failed", "interrupted"].includes(job.state);
        const detail = failed ? (job.error?.message || "任务未完成，请查看关联制作任务。") : (job.next_action?.detail || "等待状态更新。");
        const actions = [];
        if (job.can_pause) {
          actions.push(`<button type="button" data-task-job-id="${esc(job.job_id)}" data-task-job-action="pause" data-task-job-state="${esc(job.state)}">暂停</button>`);
        }
        if (job.can_cancel) {
          actions.push(`<button type="button" class="danger-button" data-task-job-id="${esc(job.job_id)}" data-task-job-action="cancel" data-task-job-state="${esc(job.state)}">${job.state === "queued" ? "取消排队" : "结束"}</button>`);
        }
        if (job.resumable) {
          const profileChanged = job.kind === "direction_generation" && job.run_id === state.currentRun?.run_id
            && directionJobProfile(job) !== state.directionProfile;
          actions.push(`<button type="button" class="primary" data-task-job-id="${esc(job.job_id)}" data-task-job-action="resume" data-task-job-state="${esc(job.state)}" data-task-owner-run="${esc(job.run_id)}" data-task-direction-profile="${job.kind === "direction_generation" ? directionJobProfile(job) : ""}">${esc(profileChanged ? "查看生成策略" : job.retry_label || "继续生成")}</button>`);
        } else if (job.retryable) {
          actions.push(`<button type="button" class="primary" data-task-job-id="${esc(job.job_id)}" data-task-job-action="retry" data-task-job-state="${esc(job.state)}">${esc(job.retry_label || "重试此阶段")}</button>`);
        }
        if (job.run_id && job.next_action?.stage) {
          actions.push(`<button type="button" class="task-open-run" data-task-run-id="${esc(job.run_id)}" data-task-stage="${esc(job.next_action.stage)}">打开关联任务</button>`);
        }
        const action = actions.length ? `<div class="task-row-actions">${actions.join("")}</div>` : "";
        const association = job.run_id ? "关联当前制作任务" : "后台任务";
        const rows = jobLogRows(job, metrics);
        const diagnostics = rows.length
          ? `<details class="task-diagnostics"><summary>运行与错误记录（${rows.length}）</summary><div class="task-log-rows">${rows.join("")}</div></details>`
          : "";
        return `<article class="task-row task-${esc(job.state)}"><div><div class="task-row-top"><strong>${esc(job.label || job.kind)}</strong><b>${esc(jobStateLabels[job.state] || job.state)}</b></div><small>${association}</small><p>${esc(detail)}</p>${taskProgressMarkup(job)}${taskMetricsMarkup(job, metrics)}${diagnostics}</div>${action}</article>`;
      }).join("") : '<p class="empty">暂无后台任务。</p>';
      $$("[data-task-run-id]").forEach((button) => button.addEventListener("click", () => openRunFromTask(button.dataset.taskRunId, button.dataset.taskStage)));
      $$('[data-task-job-action]').forEach((button) => button.addEventListener("click", () => runTaskJobAction(button)));
    } catch (error) {
      $("#taskList").innerHTML = `<p class="empty">后台任务读取失败：${esc(error.message || "请稍后重试")}</p>`;
      handleError(error);
    } finally {
      refresh.disabled = false;
    }
  }

  async function openRunFromTask(runId, stage) {
    try {
      const result = await api(`/production-runs/${encodeURIComponent(runId)}`);
      adoptRunResult(result, { replaceJob: true });
      await loadTaskPreflight();
      $("#tasksDialog").close();
      updateShell();
      showStage(stage || "review", { force: true });
      trackActiveRunJob(result);
      toast("已打开关联制作任务，请按当前提示继续处理。", "warning");
    } catch (error) { handleError(error); }
  }

  document.addEventListener("load", (event) => {
    const image = event.target;
    if (image instanceof HTMLImageElement && image.naturalWidth > 0) settleSceneBackgroundPreview(image, true);
  }, true);
  document.addEventListener("error", (event) => {
    const image = event.target;
    if (!(image instanceof HTMLImageElement) || !image.closest(".media-frame")) return;
    settleSceneBackgroundPreview(image, false);
    image.hidden = true;
    const frame = image.closest(".media-frame");
    frame?.classList.add("preview-unavailable");
    const placeholder = frame?.querySelector(".preview-placeholder");
    if (placeholder) {
      placeholder.textContent = "图片暂不可用";
      placeholder.classList.add("is-visible");
    }
    frame.title = "预览图片读取失败；资源索引记录不代表本机图片可用。";
  }, true);
  document.addEventListener("click", (event) => {
    const reviewNext = event.target.closest("[data-review-next]");
    if (reviewNext) { event.preventDefault(); focusReviewNext(reviewNext.dataset.reviewNext); return; }
    const stage = event.target.closest("[data-stage]"); if (stage) showStage(stage.dataset.stage);
    const filter = event.target.closest("[data-filter]"); if (filter) { state.filter = filter.dataset.filter; $$("[data-filter]").forEach((item) => item.classList.toggle("active", item === filter)); renderReview(); }
    const close = event.target.closest("[data-close-dialog]"); if (close) { event.preventDefault(); event.stopPropagation(); const dialog = $(`#${close.dataset.closeDialog}`); if (dialog?.open) dialog.close(); return; }
  });
  $("#actionConfirmDialog").addEventListener("close", (event) => {
    const resolver = pendingConfirmation;
    pendingConfirmation = null;
    if (resolver) resolver(event.currentTarget.returnValue === "default");
    const opener = confirmationOpener;
    confirmationOpener = null;
    requestAnimationFrame(() => opener?.isConnected && opener.focus());
  });
  document.addEventListener("keydown", (event) => {
    const confirmation = $("#actionConfirmDialog");
    if (confirmation?.open && event.key === "Escape") {
      event.preventDefault();
      confirmation.close("cancel");
      return;
    }
    const stage = event.target.closest(".stage-list [data-stage]");
    if (!stage || !["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    showStage(stage.dataset.stage);
  });
  $("#sourceForm").addEventListener("submit", createRun);
  [$("#projectName"), $("#scriptText")].forEach((input) => input?.addEventListener("input", () => invalidateSourcePreflight()));
  $$('#sourceForm input[name="generationMode"]').forEach((input) => input.addEventListener("change", updateGenerationModeUi));
  $("#configureGenerationModel").addEventListener("click", () => openSettingsDialog("model"));
  $("#preflightSource").addEventListener("click", preflightSource);
  $("#reloadRuns").addEventListener("click", loadRuns);
  $("#refreshRun").addEventListener("click", () => refreshCurrentRun().catch(handleError));
  $("#mappingContinue").addEventListener("click", () => showStage("generation"));
  $("#generateOrReview").addEventListener("click", startGeneration);
  $("#regenerateDirection").addEventListener("click", () => startGeneration({ restart: true }));
  $("#directionProfile").addEventListener("change", (event) => {
    state.directionProfile = event.target.value === "conservative" ? "conservative" : "standard";
    renderGeneration();
  });
  $("#pauseGeneration").addEventListener("click", pauseGenerationJob);
  $("#resumeGeneration").addEventListener("click", resumeGenerationJob);
  $("#cancelGeneration").addEventListener("click", cancelGenerationJob);
  $$('#layoutModeFieldset input[name="layoutMode"]').forEach((input) => input.addEventListener("change", rememberLayoutMode));
  $("#validateDraft").addEventListener("click", validateDraft);
  $("#approveAll").addEventListener("click", () => approveCards(null));
  $("#compileButton").addEventListener("click", compileRun);
  $("#openPerformancePreview").addEventListener("click", openPerformancePreview);
  $("#openDirectionProposals").addEventListener("click", openDirectionProposals);
  $("#previewPrevious").addEventListener("click", () => stepPerformancePreview(-1));
  $("#previewNext").addEventListener("click", () => stepPerformancePreview(1));
  $("#previewOpenCard").addEventListener("click", openPreviewCard);
  $("#openCgDialog").addEventListener("click", openCgDialog);
  $("#askCgAdvice").addEventListener("click", askCgAdvice);
  $("#createCgSegment").addEventListener("click", createCgSegment);
  $("#cgSearch").addEventListener("input", (event) => searchCgResources(event.target.value));
  $("#characterSearch").addEventListener("input", (event) => searchCharacters(event.target.value));
  $("#saveMappingAlias").addEventListener("click", saveLocalCharacterAlias);
  $("#chooseTeacherIdentity").addEventListener("click", () => showTeacherIdentity(true));
  $("#cancelTeacherIdentity").addEventListener("click", () => showTeacherIdentity(false));
  $("#teacherPreset").addEventListener("change", updateTeacherPreset);
  $("#teacherIdentityForm").addEventListener("submit", saveTeacherIdentity);
  $("#teacherDisplayName").addEventListener("input", (event) => event.target.setCustomValidity(""));
  $("#resourceScenePlace").addEventListener("input", () => searchResources(null, { reset: true }));
  function queueResourceSearch(event) {
    if (event.isComposing) return;
    clearTimeout(resourceSearchTimer);
    resourceSearchController?.abort();
    resourcePageObserver?.disconnect();
    state.resourceSearchEpoch = (state.resourceSearchEpoch || 0) + 1;
    state.resourceLoading = false;
    $("#resourcePickerCount").textContent = "正在搜索…";
    const query = event.target.value;
    resourceSearchTimer = setTimeout(() => searchResources(query, { reset: true }), 180);
  }
  $("#resourceSearch").addEventListener("input", queueResourceSearch);
  $("#resourceSearch").addEventListener("compositionend", queueResourceSearch);
  $("#resourceSearch").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); searchResources(event.target.value, { reset: true }); }
  });
  ["#resourceGroupFilter", "#resourceSourceFilter", "#resourceCategoryFilter", "#resourcePlaceFilter", "#resourceTimeFilter", "#resourceWeatherFilter", "#resourceTagFilter", "#resourceReadyFilter"].forEach((selector) => $(selector)?.addEventListener(selector === "#resourceTagFilter" ? "input" : "change", () => searchResources(null, { reset: true })));
  $("#resourceLoadMore").addEventListener("click", () => searchResources(null, { reset: $("#resourceLoadMore").dataset.retryReset === "true" }));
  $("#resourceDialog").addEventListener("close", () => {
    clearTimeout(resourceSearchTimer);
    resourceSearchController?.abort();
    resourcePageObserver?.disconnect();
    state.resourceSearchEpoch = (state.resourceSearchEpoch || 0) + 1;
    state.resourceLoading = false;
  });
  $("#toolbarEditCard").addEventListener("click", () => {
    if (!state.selectedCard) return;
    $("#inspectorTitle")?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
    requestAnimationFrame(() => $("#inspectorBody textarea, #inspectorBody input, #inspectorBody select, #inspectorBody button")?.focus());
  });
  $("#toolbarInsertLine").addEventListener("click", () => state.selectedCard && openInsertCard(state.selectedCard, "line"));
  $("#toolbarInsertDirection").addEventListener("click", () => state.selectedCard && openInsertCard(state.selectedCard, "dir"));
  $("#toolbarMoveEarlier").addEventListener("click", () => state.selectedCard && moveSelectedCard(state.selectedCard, "earlier"));
  $("#toolbarMoveLater").addEventListener("click", () => state.selectedCard && moveSelectedCard(state.selectedCard, "later"));
  $("#toolbarDeleteCard").addEventListener("click", () => state.selectedCard && deleteSelectedCard(state.selectedCard));
  $("#toolbarBindCharacter").addEventListener("click", () => {
    const speaker = String(state.selectedCard?.current?.who || "").trim();
    if (speaker) openMapping(speaker);
  });
  $("#reviewPreviewPrevious").addEventListener("click", () => { stopPersistentPreviewPlayback(); stepPersistentPreview(-1); });
  $("#reviewPreviewNext").addEventListener("click", () => { stopPersistentPreviewPlayback(); stepPersistentPreview(1); });
  $("#reviewPreviewPlay").addEventListener("click", togglePersistentPreviewPlayback);
  $("#openInstallDialog").addEventListener("click", openInstallDialog);
  $("#installCategory").addEventListener("input", scheduleInstallCheck);
  $("#installStoryName").addEventListener("input", scheduleInstallCheck);
  $("#checkInstall").addEventListener("click", checkInstallTarget);
  $("#installRun").addEventListener("click", installCurrentRun);
  $("#openAssetLibrary").addEventListener("click", () => openAssetLibrary());
  $("#reviewAssetsRefresh")?.addEventListener("click", () => loadReviewAssets(true));
  $("#reviewAssetsImport")?.addEventListener("click", openAssetImport);
  $("#reviewAssetsManage")?.addEventListener("click", () => openAssetLibrary());
  $("#openAssetImport").addEventListener("click", openAssetImport);
  $$('input[name="assetImportKind"]').forEach((input) => input.addEventListener("change", updateAssetImportForm));
  $("#assetImportFile").addEventListener("change", updateAssetImportFileName);
  $("#validateAssetImport").addEventListener("click", validateAssetImport);
  $("#recognizeAssetImport").addEventListener("click", recognizeAssetImport);
  $("#registerAssetImport").addEventListener("click", registerAssetImport);
  document.addEventListener("click", (event) => {
    const accept = event.target.closest("#acceptAssetRecognition");
    if (!accept || !state.assetImport?.recognition) return;
    event.preventDefault();
    state.assetImport.recognitionAccepted = state.assetImport.recognitionAccepted !== true;
    renderAssetRecognition(state.assetImport.recognition);
  });
  $("#copyBackgroundPrompt").addEventListener("click", copyBackgroundPrompt);
  $("#importGeneratedBackground").addEventListener("click", openGeneratedBackgroundImport);
  $("#assetLibrarySearch").addEventListener("input", () => loadAssetLibrary({ reset: true }));
  $("#assetLibrarySort").addEventListener("change", () => loadAssetLibrary({ reset: true }));
  $("#assetLibraryMore").addEventListener("click", () => loadAssetLibrary());
  $$("[data-asset-kind]").forEach((button) => button.addEventListener("click", () => {
    state.assetLibraryKind = button.dataset.assetKind;
    $$("[data-asset-kind]").forEach((item) => item.classList.toggle("active", item === button));
    loadAssetLibrary({ reset: true });
  }));
  $("#insertCardKind").addEventListener("change", updateInsertFields);
  $("#insertCardForm").addEventListener("submit", (event) => { event.preventDefault(); insertCard(); });
  $$(".mapping-kinds [data-kind]").forEach((button) => button.addEventListener("click", () => saveMapping({ kind: button.dataset.kind })));
  $("#openRunOverview").addEventListener("click", openRunOverview);
  $("#runOverviewContinue").addEventListener("click", (event) => {
    $("#runOverviewDialog").close();
    showStage(event.currentTarget.dataset.stage || "source", { force: true });
  });
  $("#openSettings").addEventListener("click", () => openSettingsDialog("workspace"));
  $$('[data-settings-pane]').forEach((button) => button.addEventListener("click", async () => {
    showSettingsPane(button.dataset.settingsPane);
    if (button.dataset.settingsPane === "model") await loadModelSettings();
    else if (button.dataset.settingsPane === "spine") await loadSpineCliSettings();
    else await inspectAaEnvironment(false, true);
  }));
  $("#inspectAaEnvironment").addEventListener("click", () => inspectAaEnvironment(false));
  $("#adoptAaEnvironment").addEventListener("click", () => inspectAaEnvironment(true));
  $("#rebuildResourceIndex").addEventListener("click", rebuildResourceIndex);
  $("#modelForm").addEventListener("submit", saveModel);
  $("#testModel").addEventListener("click", testModel);
  $("#spineForm").addEventListener("submit", saveSpineCli);
  $("#clearSpineCli").addEventListener("click", clearSpineCli);
  $("#openTasks").addEventListener("click", async () => { await renderTasks(); $("#tasksDialog").showModal(); });
  $("#refreshTasks").addEventListener("click", renderTasks);

  const productionShell = $(".app-shell");
  productionShell.haloCueOpenRun = openRun;
  productionShell.haloCueGetState = () => ({ run: state.currentRun, draft: state.currentDraft, stage: currentRunOpeningStage() });
  productionShell.haloCueShowStage = (stage) => showStage(stage || currentRunOpeningStage(), { force: true });
  productionShell.haloCueShowNewProduction = () => {
    runOpeningEpoch += 1;
    state.currentRun = null;
    state.currentDraft = null;
    state.currentJob = null;
    state.taskPreflight = null;
    state.aiPreflight = null;
    state.selectedCard = null;
    state.sourcePreflight = null;
    state.sourcePreflightSignature = "";
    state.sourcePreflightConfirmed = false;
    state.upstreamRelease = null;
    rememberRun(null);
    $("#sourceForm")?.reset();
    setSourceMode("writing");
    $("#activeSourceBadge")?.classList.add("hidden");
    $("#dropzonePrompt")?.classList.remove("hidden");
    $("#dropzoneFileInfo")?.classList.add("hidden");
    updateShell();
    showStage("source", { force: true });
    productionShell.dispatchEvent(new CustomEvent("halocue:production-new-mode", { bubbles: true, composed: true }));
  };
  productionShell.haloCueReady = (async function boot() {
    setupProfilePickers();
    setupSourceTabs();
    syncSourceReadAction();
    setupModernDropzone();
    try {
      await Promise.all([
        refreshCapabilities(),
        loadModelSettings(),
        loadRuns(),
        loadWritingWorksAndReleases()
      ]);
      // Embedded navigation owns the requested run. Never race it with local storage.
      if (!productionShell.classList.contains("embedded-production-shell")) await restoreSavedRun();
    } catch (error) {
      $("#serviceState").textContent = "后端未连接";
      handleError(error);
    }
  })();
})();
