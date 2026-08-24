(() => {
  "use strict";

  const state = {
    currentRun: null,
    currentDraft: null,
    gates: null,
    capabilities: null,
    selectedCard: null,
    selectedSpeaker: null,
    currentStage: "source",
    filter: "all",
    model: null,
    resourcePicker: null,
    cgBackgroundKey: null,
    insertAfterCardId: null,
    assetLibraryKind: "characters",
    assetLibraryOffset: 0,
    assetLibraryTotal: 0,
    assetUsage: {},
    assetImport: null,
    taskPreflight: null,
    aiPreflight: null,
    performancePreview: null,
    previewIndex: 0,
    busy: false,
    sourceMode: "writing",
    sourceFileName: null,
    upstreamRelease: null,
    aaEnvironment: null,
  };
  const API_ROOT = location.port === "8891"
    ? "http://127.0.0.1:8892/api/v1"
    : "/api/v1";

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const esc = (value) => String(value ?? "").replace(/[&<>\"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '\"': "&quot;"
  }[char]));
  const text = (value, fallback = "") => String(value ?? fallback);
  const previewUrl = (kind, key) => state.currentRun
    ? `${API_ROOT}/production-runs/${encodeURIComponent(state.currentRun.run_id)}/resources/${kind}/${encodeURIComponent(key)}/preview`
    : `${API_ROOT}/resources/${kind}/${encodeURIComponent(key)}/preview`;
  const previewImage = (kind, key, label, className) => `<span class="resource-thumb media-frame"><img class="${className}" src="${previewUrl(kind, key)}" alt="" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='grid'"><span class="preview-placeholder" aria-hidden="true">预览</span></span>`;

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

  function toast(message, tone = "normal") {
    const element = $("#toast");
    element.textContent = message;
    element.dataset.tone = tone;
    element.classList.add("visible");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => element.classList.remove("visible"), 3600);
  }

  async function api(path, options = {}) {
    const response = await fetch(`${API_ROOT}${path}`, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
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
  }

  function setBusy(value) {
    state.busy = value;
    document.body.classList.toggle("is-busy", value);
    $$('button[type="submit"], button.primary').forEach((button) => {
      if (button.id !== "compileButton" || !value) button.disabled = value || button.dataset.locked === "true";
    });
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
    const labels = { source: "选择剧本", mapping: "剧本初审", generation: "生成准备", review: "审查与安装" };
    $("#breadcrumb").textContent = `制作 / ${labels[stage]}`;
    $("#pageTitle").textContent = stage === "source" ? "把已有剧本转换为 AA 工程" : labels[stage];
    document.querySelector(".workspace").scrollTo({ top: 0, behavior: "instant" });
    if (stage === "mapping") renderMapping();
    if (stage === "generation") renderGeneration();
    if (stage === "review") renderReview();
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
    const generationDone = mappingDone && !!draft
      && !["generating_direction", "direction_failed"].includes(run.state);
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
      recommendedLabel = run.state === "generating_direction" ? "查看演出生成状态" : "完成生成准备";
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
    if (stage === "review" && !state.currentDraft) {
      return { allowed: false, reason: "草稿还没有载入，请先完成生成准备。" };
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
    $("#runTitle").textContent = run ? `${run.project} · ${run.run_id}` : "尚未建立制作任务";
    const labels = {
      waiting_for_review: "等待审查", ready_to_compile: "可以编译", compiling: "正在编译",
      compiled: "编译完成", installed: "已安装", generating_direction: "正在生成演出",
      direction_failed: "演出生成失败", compile_failed: "编译失败"
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
    compile_not_configured: "编译环境尚未配置",
    build_missing: "尚未生成可安装构建",
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
      ready_to_compile: "可以编译",
      compiling: "正在编译",
      compiled: "等待安装",
      installed: "已经安装",
      generating_direction: "正在生成演出",
      direction_failed: "演出生成失败",
      compile_failed: "编译失败",
    };
    const sourceOrigin = origin
      ? `<section class="overview-origin from-writing" aria-label="写作端交接信息">
          <header><span>来源</span><b>来自写作工作台</b><em>正文已按 SHA-256 校验</em></header>
          <dl>
            <div><dt>定稿版本</dt><dd>${esc(origin.display_version)}</dd></div>
            <div><dt>发布标识</dt><dd class="mono" title="${esc(origin.release_id)}">${esc(origin.release_id)}</dd></div>
            ${origin.work_id ? `<div><dt>作品标识</dt><dd class="mono" title="${esc(origin.work_id)}">${esc(origin.work_id)}</dd></div>` : ""}
            ${origin.writing_pack_version ? `<div><dt>写作包</dt><dd>${esc(origin.writing_pack_version)}</dd></div>` : ""}
          </dl>
        </section>`
      : `<section class="overview-origin direct-import" aria-label="剧本来源">
          <header><span>来源</span><b>直接导入剧本</b><em>此任务未关联写作端定稿</em></header>
        </section>`;
    body.innerHTML = `<section class="overview-title"><div><small>${esc(run.run_id)}</small><h4>${esc(run.project)}</h4><p>${esc(mode)} · ${esc(statusLabels[run.state] || run.state)}</p></div><b>${snapshot.completed}/4</b></section>
      ${sourceOrigin}
      <section class="overview-metrics" aria-label="任务数据"><article><small>剧本文本</small><strong>${esc(run.source_summary?.line_count || 0)} 行</strong></article><article><small>演出草稿</small><strong>${esc(draft?.cards?.length || run.source_summary?.card_count || 0)} 张</strong></article><article><small>待审卡片</small><strong>${esc(counts.pending || 0)} 张</strong></article><article><small>阻断问题</small><strong>${esc(counts.blocking_errors || 0)} 项</strong></article></section>
      <ol class="overview-stage-list">${stageOrder.map((stage, index) => { const names = { source: "剧本已冻结", mapping: "角色映射", generation: "演出草稿", review: "审查与安装" }; const done = snapshot.done[stage]; const current = stage === state.currentStage; return `<li class="${done ? "done" : current ? "current" : ""}"><b>${done ? "完" : index + 1}</b><span><strong>${names[stage]}</strong><small>${done ? "已完成" : current ? "正在处理" : "尚未完成"}</small></span></li>`; }).join("")}</ol>
      <section class="overview-blockers ${blockers.length ? "has-blockers" : "ready"}"><small>${blockers.length ? "当前阻断" : "当前状态"}</small><strong>${blockers.length ? blockers.map((item) => blockerLabels[item] || item).join("；") : run.state === "installed" ? "工程已经安装到 AA" : "没有发现新的阻断项"}</strong>${run.last_build_id ? `<p>最近构建：${esc(run.last_build_id)}${run.last_installed_project ? ` · 已安装为 ${esc(run.last_installed_project)}` : ""}</p>` : ""}</section>`;
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

  async function refreshCurrentRun() {
    if (!state.currentRun?.run_id) return;
    const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}`);
    state.currentRun = result.run;
    state.currentDraft = result.draft;
    state.gates = result.gates;
    state.selectedCard = state.currentDraft?.cards?.find((card) => card.card_id === state.selectedCard?.card_id) || null;
    await loadTaskPreflight();
    updateShell();
    renderMapping();
    renderGeneration();
    renderReview();
  }

  async function loadRuns() {
    try {
      const result = await api("/production-runs");
      const list = $("#runList");
      if (!result.items?.length) { list.innerHTML = '<p class="empty">暂无制作任务</p>'; return; }
      list.innerHTML = result.items.slice(0, 8).map((run) => `<button class="run-row" data-run-id="${esc(run.run_id)}">
        <span><strong>${esc(run.project)}</strong><small>${esc(run.run_id)} · ${esc(run.state)}</small></span><b>打开</b></button>`).join("");
      $$("[data-run-id]").forEach((button) => button.addEventListener("click", () => openRun(button.dataset.runId)));
    } catch (error) { handleError(error); }
  }

  async function openRun(runId) {
    try {
      const result = await api(`/production-runs/${encodeURIComponent(runId)}`);
      state.currentRun = result.run; state.currentDraft = result.draft; state.gates = result.gates;
      await loadTaskPreflight();
      updateShell();
      const next = result.draft?.review_ready ? "review" : "mapping";
      showStage(next, { force: true });
      toast(`已打开 ${result.run.project}`);
    } catch (error) { handleError(error); }
  }

  async function createRun(event) {
    event.preventDefault();
    if (state.busy) return;
    const form = event.currentTarget;
    let payload;
    try {
      payload = {
        project: $("#projectName").value.trim(),
        source: sourcePayload(),
        generation_mode: $('input[name="generationMode"]:checked')?.value || "format_only",
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
      state.currentRun = result.run; state.currentDraft = result.draft; state.gates = result.gates;
      await loadTaskPreflight();
      updateShell(); await loadRuns(); showStage("mapping", { force: true });
      toast("制作任务已建立，开始确认角色映射。");
      form.reset();
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

  function normalizeReleaseHash(value) {
    const match = String(value || "").trim().match(/^(?:sha256:)?([a-f0-9]{64})$/i);
    if (!match) throw new Error("写作定稿缺少有效的 SHA-256，已停止交接。");
    return match[1].toLowerCase();
  }

  async function loadWritingWorksAndReleases() {
    const grid = $("#writingReleasesGrid");
    if (!grid) return;
    try {
      grid.innerHTML = '<p class="empty">正在获取写作工作台作品与定稿...</p>';
      const response = await fetch("/api/v1/works", { headers: { "Accept": "application/json" } });
      if (!response.ok) {
        grid.innerHTML = '<div class="writing-releases-empty"><p>当前处于独立 AA 制作模式，可通过上方“从本机文件导入”直接载入剧本。</p></div>';
        return;
      }
      const json = await response.json();
      const works = json.data || json.works || [];
      if (!works.length) {
        grid.innerHTML = '<div class="writing-releases-empty"><p>写作工作台暂无保存作品。可在“写作”中创作剧本后生成定稿，或在此直接导入文件。</p></div>';
        return;
      }

      const releaseItems = [];
      for (const work of works) {
        try {
          const wResp = await fetch(`/api/v1/works/${encodeURIComponent(work.id)}`, { headers: { "Accept": "application/json" } });
          if (!wResp.ok) continue;
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
        } catch (_) {}
      }

      if (!releaseItems.length) {
        grid.innerHTML = '<div class="writing-releases-empty"><p>已连接写作工作台，但暂无可用的发布定稿。</p></div>';
        return;
      }

      grid.innerHTML = releaseItems.map(item => `
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

      $("#scriptText").value = scriptText;
      $("#projectName").value = `${workTitle} - ${version || '第一章'}`;
      state.upstreamRelease = upstream;
      state.sourceMode = "writing";
      state.sourceFileName = null;
      $("#scriptText").readOnly = true;

      const badge = $("#activeSourceBadge");
      if (badge) {
        badge.classList.remove("hidden");
        $("#activeSourceTitle").textContent = `${workTitle} (${version || '写作端'})`;
      }
      toast(`已成功载入《${workTitle}》剧本！`);
      $("#sourceForm")?.scrollIntoView({ behavior: "smooth", block: "center" });
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
        toast(`已成功读取 ${file.name}`);
      } catch (err) {
        toast("读取文件失败", "danger");
      }
    }
  }

  function setSourceMode(target) {
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

    $("#clearActiveSource")?.addEventListener("click", () => {
      state.upstreamRelease = null;
      $("#activeSourceBadge")?.classList.add("hidden");
      setSourceMode("manual");
      toast("已解除定稿绑定，可继续手动编辑");
    });
  }

  function updateGenerationModeUi() {
    const selected = $('input[name="generationMode"]:checked')?.value || "format_only";
    const aiReady = state.capabilities?.generation_modes?.ai_direction?.state === "available";
    const notice = $("#generationModeNotice");
    const button = $("#configureGenerationModel");
    if (!notice || !button) return;
    notice.querySelector("span").textContent = selected === "ai_direction"
      ? aiReady ? "模型已就绪；映射完成后会生成演出草稿。" : "已选择 AI 安排演出，建立任务前需要配置模型。"
      : "当前将保留已有演出指令，并进入映射与审查。";
    button.classList.toggle("hidden", selected !== "ai_direction" || aiReady);
  }

  function preflightTone(confidence) {
    return confidence === "high" ? "pass" : confidence === "medium" ? "notice" : "warning";
  }

  function renderSourcePreflight(result) {
    const panel = $("#sourcePreflight");
    const format = result.format || {};
    const speakers = result.speakers || [];
    const scenes = result.scenes || [];
    const directives = result.directives || {};
    const issues = directives.issues || [];
    const actions = result.actions || [];
    panel.classList.remove("hidden");
    panel.innerHTML = `<header class="preflight-head"><div><small>不调用 AI · 不会建立任务</small><h3>剧本检查结果</h3><p>${esc(format.message || "已完成结构识别。")}</p></div><b class="preflight-status ${preflightTone(format.confidence)}">${esc(format.label || "格式检查")}</b></header>
      <div class="preflight-grid">
        <article><small>说话者</small><strong>${speakers.length} 位</strong><p>${speakers.length ? "建立任务后逐位选择立绘、旁白或无立绘角色。" : "未识别到说话者；请检查“角色: 台词”格式。"}</p>${speakers.length ? `<ul>${speakers.slice(0, 5).map((speaker) => `<li><b>${esc(speaker.name)}</b><span>${esc(speaker.count)} 段 · ${esc(speaker.sample || "无台词样例")}</span></li>`).join("")}${speakers.length > 5 ? `<li><span>另有 ${speakers.length - 5} 位说话者</span></li>` : ""}</ul>` : ""}</article>
        <article><small>场景结构</small><strong>${scenes.length} 个场景</strong><p>${scenes.length ? "场景标题将作为演出草稿的分段依据。" : "没有场景标题；可用“## 场景名称”补充分段。"}</p>${scenes.length ? `<ul>${scenes.slice(0, 4).map((scene) => `<li><b>第 ${esc(scene.line_no)} 行</b><span>${esc(scene.title)}</span></li>`).join("")}${scenes.length > 4 ? `<li><span>另有 ${scenes.length - 4} 个场景</span></li>` : ""}</ul>` : ""}</article>
        <article class="${issues.length ? "has-issues" : ""}"><small>AA 指令</small><strong>${esc(directives.total || 0)} 条</strong><p>${issues.length ? `发现 ${issues.length} 个需要先处理的问题。` : "没有发现明显的指令格式问题。"}</p>${issues.length ? `<ul>${issues.slice(0, 3).map((issue) => `<li><b>第 ${esc(issue.line_no)} 行</b><span>${esc(issue.message)}<em>${esc(issue.action)}</em></span></li>`).join("")}${issues.length > 3 ? `<li><span>另有 ${issues.length - 3} 个问题</span></li>` : ""}</ul>` : ""}</article>
      </div>
      <footer class="preflight-next"><div><small>接下来该做什么</small>${actions.map((action) => `<p><b>${esc(action.label)}</b><span>${esc(action.detail)}</span></p>`).join("")}</div><button type="button" class="primary" id="preflightCreateRun" ${actions.find((action) => action.id === "create_run")?.available ? "" : "disabled"}>确认并建立任务</button></footer>`;
    $("#preflightCreateRun")?.addEventListener("click", () => $("#sourceForm").requestSubmit());
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function preflightSource() {
    const source = $("#scriptText").value;
    if (!source.trim()) { toast("请先输入要检查的剧本文本。", "warning"); $("#scriptText").focus(); return; }
    const button = $("#preflightSource");
    button.disabled = true;
    button.textContent = "正在检查";
    try {
      const result = await api("/script-preflight", { method: "POST", body: JSON.stringify({ source: sourcePayload() }) });
      renderSourcePreflight(result);
      $("#sourceStatus").textContent = "检查完成：结果只说明系统识别到的内容，不会保存剧本。";
    } catch (error) { handleError(error); } finally { button.disabled = false; button.textContent = "先检查剧本"; }
  }

  function mappingFor(speaker) {
    const cast = state.currentDraft?.cast?.cast || {};
    return cast[speaker] || { kind: "unset" };
  }

  function mappingLabel(mapping) {
    if (!mapping || mapping.kind === "unset") return "尚未映射";
    if (mapping.kind === "narrator") return "旁白（不显示角色）";
    if (mapping.kind === "voice") return mapping.display_name || "无立绘角色";
    return `${mapping.name || mapping.display_name || mapping.id || "已选择"}${mapping.spine ? ` · ${mapping.spine}` : ""}`;
  }

  function mappingStatusLabel(mapping) {
    if (!mapping || mapping.kind === "unset") return "尚未映射";
    if (mapping.kind === "narrator") return "旁白";
    if (mapping.kind === "voice") return "无立绘角色";
    return mapping.name || "已选立绘角色";
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
    const action = summary.next_action || {};
    panel.innerHTML = `<header class="task-preflight-head"><div><small>任务初审 · 基于冻结草稿</small><h3>系统已经识别到什么</h3><p>这里显示的是当前草稿的解析和编译诊断，不是 AI 猜测。完成映射后才能进入演出制作。</p></div><button type="button" id="refreshTaskPreflight">刷新摘要</button></header>
      <div class="task-preflight-grid">
        <article><small>说话者映射</small><strong>${speakers.length} 位</strong><p>${speakers.filter((item) => item.mapping?.kind === "unset").length ? "未映射角色会阻止后续生成与编译。" : "每位说话者都已有明确的处理方式。"}</p>${speakers.length ? `<ul>${speakers.slice(0, 4).map((speaker) => `<li><span><b>${esc(speaker.speaker)}</b><em>${esc(speaker.count)} 段 · ${esc(speaker.sample || "无台词样例")}</em></span><strong class="mapping-state ${speaker.mapping?.kind === "unset" ? "missing" : "ready"}">${esc(mappingStatusLabel(speaker.mapping))}</strong></li>`).join("")}${speakers.length > 4 ? `<li><em>另有 ${speakers.length - 4} 位说话者</em></li>` : ""}</ul>` : ""}</article>
        <article class="${requests.length ? "needs-work" : ""}"><small>待处理素材</small><strong>${requests.length} 项</strong><p>${requests.length ? "素材请求会在审查器内从当前任务的冻结素材清单处理。" : "未检测到需要单独处理的背景或音效请求。"}</p>${requests.length ? `<ul>${requests.slice(0, 3).map((request) => `<li><span><b>${esc(preflightRequestLabel(request))}</b><em>第 ${esc(request.line_no || "-")} 行 · ${esc(request.description || "等待处理")}</em></span><button type="button" data-preflight-card="${esc(request.card_id)}">打开处理</button></li>`).join("")}${requests.length > 3 ? `<li><em>另有 ${requests.length - 3} 项素材请求</em></li>` : ""}</ul>` : ""}</article>
        <article class="${errors.length ? "has-errors" : diagnostics.length ? "needs-work" : ""}"><small>编译诊断</small><strong>${errors.length ? `${errors.length} 项阻断` : diagnostics.length ? `${diagnostics.length} 项提示` : "暂无阻断"}</strong><p>${errors.length ? "先处理阻断项，编译门禁才会打开。" : diagnostics.length ? "提示不会自动修改草稿；请在审查时逐项确认。" : "可继续完成逐卡审查。"}</p>${diagnostics.length ? `<ul>${diagnostics.slice(0, 3).map((item) => `<li><b>${esc(item.line_no ? `第 ${item.line_no} 行` : item.code)}</b><em>${esc(item.message)}</em></li>`).join("")}${diagnostics.length > 3 ? `<li><em>另有 ${diagnostics.length - 3} 项诊断</em></li>` : ""}</ul>` : ""}</article>
      </div>
      <footer class="task-preflight-next"><div><small>推荐下一步</small><strong>${esc(action.label || "确认角色映射")}</strong><p>${esc(action.detail || "请继续完成当前步骤。")}</p></div><button type="button" class="primary" id="taskPreflightContinue" data-next-stage="${esc(action.stage || "mapping")}">${action.stage === "review" ? "前往审查处理" : "开始角色映射"}</button></footer>`;
    $("#refreshTaskPreflight")?.addEventListener("click", loadTaskPreflight);
    $$("[data-preflight-card]").forEach((button) => button.addEventListener("click", () => {
      const card = state.currentDraft?.cards?.find((item) => item.card_id === button.dataset.preflightCard);
      if (!card) return;
      state.selectedCard = card;
      showStage("review", { force: true });
    }));
    $("#taskPreflightContinue")?.addEventListener("click", (event) => showStage(event.currentTarget.dataset.nextStage, { force: true }));
  }

  async function loadTaskPreflight() {
    if (!state.currentRun?.run_id) { state.taskPreflight = null; state.aiPreflight = null; renderAiPreflight(); return; }
    try {
      state.taskPreflight = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/preflight-summary`);
    } catch (error) {
      state.taskPreflight = null;
      toast(error.message || "无法读取任务初审摘要。", "warning");
    }
    renderTaskPreflight();
    await loadAiPreflights();
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
    const action = available
      ? `<button type="button" id="runAiPreflight" ${state.busy ? "disabled" : ""}>${state.busy ? "AI 初审处理中" : "运行 AI 初审"}</button>`
      : `<button type="button" id="configureAiPreflight" class="primary">去配置模型</button>`;
    const result = latest
      ? `<div class="ai-preflight-result">
          <div class="ai-preflight-summary"><div><small>最近一次结果 · 冻结源剧本</small><strong>识别 ${scenes.length} 个场景变化，${ambiguities.length} 项待确认</strong><p>初审只给出建议，不会改角色映射、素材清单或演出草稿。结果来自 ${esc(latest.model?.name || "已配置模型")}。</p></div><button type="button" data-ai-preflight-action="rerun">重新运行</button></div>
          <div class="ai-preflight-grid">
            <article class="${speakers.length ? "needs-work" : ""}"><small>可能遗漏的说话者</small><strong>${speakers.length} 位</strong><p>${speakers.length ? "请先确认这些名字是否真的是说话者，再在下方角色映射中处理。" : "没有发现规则解析之外、需要你确认的说话者。"}</p>${speakers.length ? `<ul>${speakers.map((name) => `<li><b>${esc(name)}</b><button type="button" data-ai-preflight-action="mapping">查看角色映射</button></li>`).join("")}</ul>` : ""}</article>
            <article class="${scenes.length ? "needs-work" : ""}"><small>场景与背景建议</small><strong>${scenes.length} 段</strong><p>${scenes.length ? "背景只是建议；确认需要后，再到素材库登记或在审查器中选用。" : "没有识别到明确的地点、时间或室内外变化。"}</p>${scenes.length ? `<ul>${scenes.slice(0, 4).map((scene) => `<li><span><b>第 ${esc(scene.start_line)}-${esc(scene.end_line)} 行</b><em>${esc(scene.location || "地点待确认")}${scene.time ? ` · ${esc(scene.time)}` : ""}</em><em>${esc(scene.background_need || "未给出背景建议")}</em></span></li>`).join("")}${scenes.length > 4 ? `<li><em>另有 ${scenes.length - 4} 段场景建议</em></li>` : ""}</ul><button type="button" data-ai-preflight-action="assets">前往素材处理</button>` : ""}</article>
            <article class="${ambiguities.length ? "has-errors" : ""}"><small>需要人工确认</small><strong>${ambiguities.length} 项</strong><p>${ambiguities.length ? "这些不是系统错误。确认后可直接在映射或逐卡审查中修改。" : "没有发现必须由你决定的场景或角色歧义。"}</p>${ambiguities.length ? `<ul>${ambiguities.slice(0, 4).map((item) => `<li><b>第 ${esc(item.line)} 行</b><em>${esc(item.message)}</em></li>`).join("")}${ambiguities.length > 4 ? `<li><em>另有 ${ambiguities.length - 4} 项待确认</em></li>` : ""}</ul>` : ""}</article>
          </div>
        </div>`
      : `<div class="ai-preflight-empty"><strong>${available ? "还没有 AI 初审结果" : "AI 初审需要先配置模型"}</strong><p>${available ? "它会读取创建任务时冻结的剧本，分析场景、潜在说话者和需要人工确认的信息。不会修改任何草稿或资源。" : "当前没有可用模型，因此不会提交任务，也不会显示模拟结果。请在设置中配置模型后再运行。"}</p></div>`;
    panel.innerHTML = `<header class="ai-preflight-head"><div><small>可选步骤 · 只读建议</small><h3>AI 初审：先看懂剧本，再决定怎么制作</h3><p>适合补充规则检查看不到的场景和叙事线索。它不是自动制作，也不会替你确认角色、骨骼或背景。</p></div>${action}</header>${result}`;
    $("#runAiPreflight")?.addEventListener("click", startAiPreflight);
    $("#configureAiPreflight")?.addEventListener("click", () => openSettingsDialog("model"));
    $$('[data-ai-preflight-action]').forEach((button) => button.addEventListener("click", () => {
      const actionName = button.dataset.aiPreflightAction;
      if (actionName === "rerun") startAiPreflight();
      if (actionName === "mapping") $("#mappingList")?.scrollIntoView({ behavior: "smooth", block: "start" });
      if (actionName === "assets") openAssetLibrary();
    }));
  }

  async function loadAiPreflights() {
    if (!state.currentRun?.run_id) { state.aiPreflight = null; renderAiPreflight(); return; }
    try {
      state.aiPreflight = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/ai-preflights`);
    } catch (error) {
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

  function renderMapping() {
    if (!state.currentDraft || !state.currentRun) return;
    renderTaskPreflight();
    const speakers = state.currentRun.source_summary?.speakers || state.currentDraft.cast?.detected_speakers || [];
    $("#mappingCount").textContent = `${speakers.length} 位说话者`;
    const missing = speakers.filter((speaker) => mappingFor(speaker).kind === "unset").length;
    $("#mappingStatus").textContent = missing ? `${missing} 位说话者尚未映射` : "所有说话者已经有处理方式，可以继续。";
    $("#mappingContinue").disabled = missing > 0;
    $("#mappingList").innerHTML = speakers.length ? speakers.map((speaker) => {
      const mapping = mappingFor(speaker);
      return `<article class="mapping-row"><div><strong>${esc(speaker)}</strong><small>出现在 ${esc(state.currentRun.source_summary?.dialogue_count || 0)} 段台词中</small></div>
        <div class="mapping-value"><b>${esc(mappingLabel(mapping))}</b><small>${mapping.kind === "portrait" ? "骨骼、头像和表情跟随此角色" : "当前行不会带出角色立绘"}</small></div>
        <button class="mapping-edit" data-speaker="${esc(speaker)}">修改映射</button></article>`;
    }).join("") : '<p class="empty">没有检测到说话者，请检查剧本格式。</p>';
    $$(".mapping-edit").forEach((button) => button.addEventListener("click", () => openMapping(button.dataset.speaker)));
  }

  async function openMapping(speaker) {
    state.selectedSpeaker = speaker;
    $("#mappingDialogTitle").textContent = `为“${speaker}”选择映射`;
    $("#characterSearch").value = "";
    $("#mappingDialogStatus").textContent = "下面只显示本任务创建时冻结的角色；选择后只会更新当前说话者。";
    $("#mappingDialog").showModal();
    await searchCharacters("");
  }

  async function searchCharacters(query) {
    try {
      const path = state.currentRun
        ? `/production-runs/${encodeURIComponent(state.currentRun.run_id)}/resources/characters?q=${encodeURIComponent(query)}&limit=30`
        : `/resources/characters?q=${encodeURIComponent(query)}&limit=30`;
      const result = await api(path);
      const rows = result.items || [];
      $("#characterResults").innerHTML = rows.length ? rows.map((item) => `<button type="button" class="character-row resource-row" data-character-id="${esc(item.identifier)}" data-character-name="${esc(item.name)}" aria-label="选择 ${esc(item.name)} 映射给当前说话者">
        ${previewImage("characters", item.identifier, item.name, "resource-thumb avatar-thumb")}<span><strong>${esc(item.name)}</strong><small>${esc(item.identifier)}${item.club ? ` · ${esc(item.club)}` : ""}</small><small>选择后会带入该角色的骨骼、头像和 ${item.face_count || 0} 个表情。</small></span><b>选择角色</b></button>`).join("") : '<p class="empty">没有匹配的角色。</p>';
      $$("[data-character-id]").forEach((button) => button.addEventListener("click", () => saveMapping({
        kind: "portrait", id: button.dataset.characterId, name: button.dataset.characterName
      })));
    } catch (error) { $("#mappingDialogStatus").textContent = error.message; }
  }

  async function saveMapping(mapping) {
    if (!state.selectedSpeaker || !state.currentDraft) return;
    try {
      const result = await api(`/production-runs/${state.currentRun.run_id}/cast-bindings`, {
        method: "POST", body: JSON.stringify({ speaker: state.selectedSpeaker, mapping, expected_draft_version: state.currentDraft.draft_version })
      });
      state.currentRun = result.run; state.currentDraft = result.draft; state.gates = result.gates;
      await loadTaskPreflight();
      $("#mappingDialog").close(); updateShell(); renderMapping(); renderGeneration(); toast(`已更新 ${state.selectedSpeaker} 的映射`);
    } catch (error) { handleError(error); }
  }

  function renderGeneration() {
    if (!state.currentRun || !state.currentDraft) return;
    const mode = state.currentRun.source_summary?.generation_mode || "format_only";
    setLayoutMode(state.currentRun.source_summary?.layout_mode || savedLayoutMode());
    $("#layoutModeFieldset")?.classList.toggle("hidden", mode !== "ai_direction");
    $("#generationModeBadge").textContent = mode === "ai_direction" ? "AI 安排演出" : "仅转换格式";
    $("#generationDescription").textContent = mode === "ai_direction" ? "角色映射完成后，后台模型会在冻结草稿副本上安排演出。" : "格式草稿已经建立，下一步是处理素材请求并逐卡审查。";
    const cards = [
      ["角色映射", state.currentDraft.counts?.blocking_errors ? "检查未映射角色" : "已通过", !state.currentDraft.counts?.blocking_errors],
      ["演出草稿", `${state.currentDraft.counts?.total || 0} 张卡片`, true],
      ["审查门", state.currentDraft.review_ready ? "已通过" : `${state.currentDraft.counts?.pending || 0} 张待审`, !!state.currentDraft.review_ready],
    ];
    $("#generationGates").innerHTML = cards.map(([label, value, pass]) => `<div class="gate-card ${pass ? "pass" : "block"}"><small>${label}</small><b>${esc(value)}</b><small>${pass ? "可以继续" : "需要处理"}</small></div>`).join("");
    const action = $("#generateOrReview");
    if (mode === "ai_direction" && state.currentRun.state === "waiting_for_review") {
      $("#generationActionTitle").textContent = "运行 AI 安排演出";
      $("#generationActionCopy").textContent = "后台任务会保留检查点，完成后回到逐卡审查。";
      action.textContent = "开始安排演出";
    } else {
      $("#generationActionTitle").textContent = "打开草稿审查";
      $("#generationActionCopy").textContent = "逐卡处理未登记背景、音效和待审内容。";
      action.textContent = "进入审查";
    }
    action.disabled = !!state.currentDraft.counts?.blocking_errors || state.currentRun.state === "generating_direction";
  }

  async function startGeneration() {
    if (!state.currentRun || !state.currentDraft) return;
    const mode = state.currentRun.source_summary?.generation_mode;
    if (mode !== "ai_direction") { showStage("review", { force: true }); return; }
    setBusy(true);
    try {
      const result = await api(`/production-runs/${state.currentRun.run_id}/direction-generation`, {
        method: "POST", body: JSON.stringify({
          expected_draft_version: state.currentDraft.draft_version,
          story_type: "auto",
          layout_mode: selectedLayoutMode(),
        })
      });
      state.currentRun.source_summary.layout_mode = result.layout_mode || selectedLayoutMode();
      rememberLayoutMode();
      showStage("review", { force: true }); await pollJob(result.job.job_id, "演出安排");
    } catch (error) { handleError(error); } finally { setBusy(false); }
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

  function renderReview() {
    if (!state.currentDraft) return;
    const cards = state.currentDraft.cards || [];
    const pending = state.currentDraft.counts?.pending || 0;
    $("#reviewSummary").textContent = `${state.currentDraft.draft_version} 版草稿 · ${cards.length} 张卡片 · ${pending} 张待审`;
    $("#reviewSummary").setAttribute("aria-live", "polite");
    const visible = cards.filter((card) => {
      const status = cardStatus(card);
      if (state.filter === "all") return true;
      if (state.filter === "direction") return ["line", "dir", "scene"].includes(card.kind);
      return status === state.filter;
    });
    $("#cardList").innerHTML = visible.length ? visible.map((card) => {
      const status = cardStatus(card);
      const current = card.current || {};
      const headline = card.kind === "line" ? `${current.who || "未映射"}：${current.text || ""}` : `${current.cmd || card.kind} ${current.arg || ""}`;
      const issue = card.issues?.[0]?.message || (card.review_state === "pending" ? "等待确认" : "已审查");
      const cgBadge = card.cg ? `<b class="cg-badge" title="${esc(card.cg.label)}">CG</b>` : "";
      return `<button class="draft-card ${status} ${card.cg ? "in-cg" : ""} ${state.selectedCard?.card_id === card.card_id ? "selected" : ""}" data-card-id="${esc(card.card_id)}"><span>${esc(String(card.line_no || "").padStart(2, "0"))}</span><span><small>${esc(card.kind)} · ${esc(issue)} ${cgBadge}</small><p>${esc(headline)}</p></span><em>${card.review_state === "pending" ? "待审" : ""}</em></button>`;
    }).join("") : '<p class="empty">当前筛选没有卡片。</p>';
    $$("[data-card-id]").forEach((button) => button.addEventListener("click", () => selectCard(button.dataset.cardId)));
    const canCompile = !!state.gates?.compile?.passed;
    const compile = $("#compileButton");
    compile.disabled = !canCompile || state.currentRun?.state === "compiling";
    compile.dataset.locked = compile.disabled ? "true" : "false";
    $("#compileGate").textContent = canCompile ? "可以编译" : "等待审查";
    $("#compileBlockers").textContent = canCompile ? "草稿已通过后端编译门，可以生成 AA 工程。" : (state.gates?.compile?.blockers || []).join("、") || "完成角色映射、处理请求并审查全部卡片。";
    renderReviewWorkflow(pending, canCompile);
    if (state.selectedCard) renderInspector();
  }

  function selectCard(cardId) {
    state.selectedCard = state.currentDraft?.cards?.find((card) => card.card_id === cardId) || null;
    renderReview(); renderInspector();
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
    const isCg = frame.presentation === "cg";
    const background = frame.background_key
      ? `style="background-image:url('${esc(previewResourceUrl("backgrounds", frame.background_key))}')"`
      : "";
    const cg = "";
    const annotations = frame.annotations?.length
      ? `<div class="preview-annotations">${frame.annotations.map((item) => `<span>${esc(item.kind)}：${esc(item.value)}</span>`).join("")}</div>`
      : "";
    const statusLabel = frame.review_state === "approved" ? "已审" : "待审";
    target.className = `performance-preview-frame presentation-${esc(frame.presentation)}`;
    target.innerHTML = `<section class="preview-stage" ${background}><div class="preview-stage-overlay"></div><div class="preview-progress">${state.previewIndex + 1} / ${frames.length} · 第 ${esc(frame.line_no || "-")} 张 · ${esc(statusLabel)}</div>${cg}<div class="preview-dialogue ${isCg ? "is-cg" : ""}"><small>${esc(isCg ? "CG 空镜段落" : frame.presentation === "request" ? "需要处理" : frame.presentation === "direction" ? "演出指令" : "当前台词")}</small><strong>${esc(frame.title || "未命名卡片")}</strong><p>${esc(frame.text || "此卡没有可显示的文本。")}</p>${annotations}</div></section><div class="preview-card-strip" aria-label="草稿卡片定位">${frames.map((item, index) => `<button type="button" class="${index === state.previewIndex ? "active" : ""}" data-preview-index="${index}" aria-label="跳到第 ${esc(item.line_no || "-")} 张卡片">${esc(String(item.line_no || index + 1).padStart(2, "0"))}</button>`).join("")}</div>`;
    status.textContent = `当前展示第 ${frame.line_no || "-"} 张卡片；预览是只读的，修改请回到这张卡。`;
    $("#previewPrevious").disabled = state.previewIndex === 0;
    $("#previewNext").disabled = state.previewIndex >= frames.length - 1;
    $("#previewOpenCard").disabled = !frame.card_id;
    $$('[data-preview-index]').forEach((button) => button.addEventListener("click", () => {
      state.previewIndex = Number(button.dataset.previewIndex) || 0;
      renderPerformancePreview();
    }));
  }

  async function openPerformancePreview() {
    if (!state.currentRun) { toast("先建立并载入一份演出草稿。", "warning"); return; }
    const dialog = $("#performancePreviewDialog");
    state.performancePreview = null;
    state.previewIndex = 0;
    $("#performancePreview").className = "performance-preview-empty";
    $("#performancePreview").innerHTML = "<strong>正在读取当前草稿</strong><p>预览会使用本任务冻结的背景、CG 和角色映射。</p>";
    $("#performancePreviewStatus").textContent = "正在读取，不会修改草稿。";
    dialog.showModal();
    try {
      state.performancePreview = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/performance-preview`);
      const selected = state.selectedCard?.card_id;
      const selectedIndex = (state.performancePreview.frames || []).findIndex((item) => item.card_id === selected);
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
    if (!audit.total) {
      target.className = "direction-proposals-empty";
      target.innerHTML = "<strong>本次 AI 没有留下单独的演出建议</strong><p>这可能表示模型没有增加可审计标注。请直接在逐卡审查器检查台词、素材和演出字段。</p>";
      status.textContent = "建议记录为空，草稿没有被此窗口修改。";
      return;
    }
    target.className = "";
    target.innerHTML = `<section class="proposal-summary"><strong>共 ${audit.total} 条 AI 演出建议</strong><p>“已写入草稿”仍需逐卡审查。只有能唯一对应到当前台词的建议才显示“保留/撤销”；其余建议只读，避免草稿调整后误改内容。</p></section>${generations.map((generation) => `<section class="proposal-generation"><header><div><h4>一次生成记录 · ${esc(generation.proposal_count)} 条建议</h4><small>${esc(generation.model || "未记录模型")} · 剧情类型：${esc(generation.story_type || "auto")} · 写入后草稿版本：${esc(generation.draft_version || "-")}</small></div></header><ul class="proposal-list">${(generation.proposals || []).map((proposal) => { const suggested = proposal.type === "suggested_fix"; const before = proposal.before || "未设置"; const after = proposal.after || "未设置"; const action = proposal.can_apply_safely ? `<div class="proposal-actions"><button type="button" data-proposal-action="approve" data-proposal-id="${esc(proposal.proposal_id)}">保留这项标注</button><button type="button" class="danger" data-proposal-action="reject" data-proposal-id="${esc(proposal.proposal_id)}">撤销并恢复原值</button></div>` : ""; return `<li class="proposal-item ${suggested ? "suggested" : "applied"}"><div><strong>${esc(proposalFieldLabel(proposal.field))}：${esc(after)}</strong><p>${suggested ? "模型提出了这个值，但系统没有把它写入草稿。" : "模型已把这个值写进生成后的草稿，仍需要你在逐卡审查中确认。"}</p><div class="proposal-change"><span>原值：${esc(before)}</span><span>建议值：${esc(after)}</span></div><p>${esc(proposal.apply_reason)}</p>${action}</div><b>${suggested ? "仅供参考" : proposal.can_apply_safely ? "可确认或撤销" : "已写入草稿"}</b></li>`; }).join("")}</ul></section>`).join("")}`;
    status.textContent = `当前草稿为第 ${audit.draft_version || "-"} 版；本窗口不会修改它。`;
    $$('[data-proposal-action]').forEach((button) => button.addEventListener("click", () => decideDirectionProposal(button.dataset.proposalId, button.dataset.proposalAction)));
  }

  async function decideDirectionProposal(proposalId, action) {
    if (!state.currentRun || !state.currentDraft) return;
    const verb = action === "reject" ? "撤销并恢复生成前的值" : "保留这项 AI 标注";
    if (!window.confirm(`${verb}？${action === "reject" ? "这会修改对应台词，并让该卡回到待审。" : "这只记录你的确认，不会改写台词。"}`)) return;
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
    renderPerformancePreview();
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

  async function hydrateLinePerformanceEditor(card) {
    const target = $("#linePerformanceFields");
    if (!target || !state.currentRun || state.selectedCard?.card_id !== card.card_id) return;
    const current = card.current || {};
    const speaker = String(current.who || "").trim();
    const mapping = mappingFor(speaker);
    try {
      const result = await api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/resources/characters/${encodeURIComponent(mapping.id)}`);
      if (state.selectedCard?.card_id !== card.card_id || !$("#linePerformanceFields")) return;
      const character = result.character || {};
      const faces = character.faces || [];
      const selected = String(current.face || "");
      const options = [`<option value="">不指定表情（使用 AA 默认）</option>`, ...faces.map((face) => {
        const value = faceOptionValue(face);
        const label = face.label || face.raw || face.id || "未命名表情";
        return `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(label)}${face.id && face.id !== label ? ` · ${esc(face.id)}` : ""}</option>`;
      })].join("");
      target.className = "performance-fields";
      target.innerHTML = `<p class="performance-character"><b>${esc(character.name || mapping.name || mapping.id)}</b><span>本任务冻结角色 · ${faces.length} 个可选表情</span></p><label>表情<select id="editLineFace">${options}</select><small>这里只列出这套骨骼实际拥有的表情；不指定时交给 AA 默认处理。</small></label><div class="performance-option-grid"><label>情绪气泡<input id="editLineEmo" value="${esc(current.emo || "")}" placeholder="例如：惊讶（可留空）"><small>显示在对话气泡上的情绪标记。</small></label><label>角色动作<input id="editLineAct" value="${esc(current.act || "")}" placeholder="例如：挥手（可留空）"><small>这句台词触发的角色动作。</small></label></div><label>画面效果<input id="editLineFx" value="${esc(current.fx || "")}" placeholder="例如：特写（可留空）"><small>用于这一句的立绘表现，例如特写或剪影。</small></label><p class="inspector-note">保存后本卡会回到待审；如果标注不被 AA 支持，编译诊断会告诉你具体原因。</p>`;
    } catch (error) {
      if (state.selectedCard?.card_id !== card.card_id || !$("#linePerformanceFields")) return;
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
    $("#inspectorTitle").textContent = `正在编辑：第 ${card.line_no || "-"} 张 · ${card.kind}`;
    let body = `<p class="inspector-note">${esc(card.raw || "")}</p>`;
    if (card.cg) {
      body += `<section class="cg-inspector"><small>所属 CG 段落</small><strong>${esc(card.cg.label)}</strong><p>背景：${esc(card.cg.background_key)} · 具名无立绘</p><button id="deleteCgSegment">删除此 CG 段落</button></section>`;
    }
    body += `<div class="inspector-context"><small>当前选中对象</small><strong>第 ${card.line_no || "-"} 张 · ${esc(card.kind)}</strong><span>下面的保存、审查和素材操作只会影响这一张卡片。</span></div>`;
    if (card.kind === "line") {
      body += `<label>台词<textarea id="editCardText">${esc(current.text || "")}</textarea><small>保存只会修改这一句，后面的台词不会被改写。</small></label>${linePerformanceEditor(card)}<div class="inspector-actions"><button class="primary" id="saveCardEdit">保存本句演出设置</button><button id="approveCard">标记本句已审</button></div>`;
    } else if (card.kind === "dir") {
      body += directiveEditor(card);
    } else if (card.kind === "background_request") {
      body += `<section class="request-card-editor"><small>背景素材请求</small><h4>为这一处画面选择背景</h4><p>${esc(current.description || "系统未能读取背景描述。")}</p><p class="inspector-note">背景请求不能靠删除跳过。请从当前任务的冻结素材清单选择背景，或明确改为黑屏。</p><div class="inspector-actions"><button class="primary" id="resolveRequestedBackground">选择背景</button><button id="resolveRequestedBlack">改为黑屏</button></div></section>`;
    } else {
      const field = card.kind === "scene" || card.kind === "title" ? "title" : "text";
      const label = field === "title" ? "标题" : "文本备注";
      body += `<label>${label}<input id="editCardGeneric" value="${esc(current[field] || "")}"></label><div class="inspector-actions"><button class="primary" id="saveCardEdit">保存这张卡</button><button id="approveCard">确认这张卡</button></div>`;
    }
    const mustResolve = card.kind === "background_request";
    body += `<div class="card-actions"><small>结构调整</small><button id="insertAfterCard">在这张卡后插入</button><button id="moveCardEarlier" ${card.line_no === 1 ? "disabled" : ""}>移到上一张前</button><button id="moveCardLater" ${card.line_no === (state.currentDraft.cards || []).length ? "disabled" : ""}>移到下一张后</button>${mustResolve ? '<p class="card-action-note">这是一项必处理的背景请求，不能删除；请先选择背景或改为黑屏。</p>' : '<button class="danger-button" id="deleteSelectedCard">删除这张卡</button>'}</div>`;
    $("#inspectorBody").innerHTML = body;
    $("#saveCardEdit")?.addEventListener("click", () => patchCard(card, card.kind === "line" ? linePerformancePatch() : { [card.kind === "scene" || card.kind === "title" ? "title" : "text"]: $("#editCardGeneric").value }));
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

  function openInsertCard(card) {
    state.insertAfterCardId = card.card_id;
    $("#insertCardHint").textContent = `新卡片会插入到“第 ${card.line_no || "-"} 张 · ${card.kind}”之后，并标记为待审。`;
    $("#insertCardStatus").textContent = "先选择类型，再填写内容；插入后可以继续修改。";
    $("#insertCardKind").value = "line";
    updateInsertFields();
    $("#insertCardDialog").showModal();
  }

  function updateInsertFields() {
    const kind = $("#insertCardKind").value;
    ["line", "dir", "scene", "meta"].forEach((name) => $("#insert" + name[0].toUpperCase() + name.slice(1) + "Fields")?.classList.toggle("hidden", name !== kind));
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
    if (!window.confirm(`删除第 ${card.line_no || "-"} 张卡片？删除后需要重新审查。`)) return;
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
        ${previewImage("backgrounds", item.key, item.name || item.key, "resource-thumb cg-thumb")}<span><strong>${esc(item.name || item.key)}</strong><small>${esc(item.key)} · ${item.cg_source === "official_cg" ? "官方 CG" : "自定义背景"}</small><small>进入所选范围时切换为这张图，并强制隐藏全部角色立绘。</small></span><b>${item.key === state.cgBackgroundKey ? "已选中" : "选择"}</b></button>`).join("") : '<p class="empty">没有匹配的自定义背景或官方 CG。</p>';
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
    if (!window.confirm(`删除 CG 段落“${segment.label}”？范围内卡片会重新变为待审。`)) return;
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

  async function resolveCard(action, payload) {
    if (!state.selectedCard) return;
    try {
      const result = await api(`/production-runs/${state.currentRun.run_id}/cards/${state.selectedCard.card_id}/${action}`, { method: "POST", body: JSON.stringify({ ...payload, expected_draft_version: state.currentDraft.draft_version }) });
      applyRun(result); toast("素材请求已处理。");
    } catch (error) { handleError(error); }
  }

  async function chooseResource(kind, label, callback) {
    state.resourcePicker = { kind, label, callback };
    $("#resourceDialogEyebrow").textContent = kind === "backgrounds" ? "背景请求" : "声音指令";
    $("#resourceDialogTitle").textContent = `选择已登记${label}`;
    $("#resourceSearch").value = "";
    $("#resourceDialogStatus").textContent = "只显示当前制作任务冻结的资源索引。";
    $("#resourceDialog").showModal();
    await searchResources("");
  }

  async function searchResources(query) {
    const picker = state.resourcePicker;
    if (!picker) return;
    try {
      const path = state.currentRun
        ? `/production-runs/${encodeURIComponent(state.currentRun.run_id)}/resources/${picker.kind}?q=${encodeURIComponent(query)}&limit=60`
        : `/resources/${picker.kind}?q=${encodeURIComponent(query)}&limit=60`;
      const result = await api(path);
      const items = result.items || [];
      $("#resourceResults").innerHTML = items.length ? items.map((item) => `<button type="button" class="character-row resource-row" data-resource-key="${esc(item.key)}" aria-label="选择 ${esc(picker.label)} ${esc(item.name || item.key)}">
        ${picker.kind === "backgrounds" ? previewImage("backgrounds", item.key, item.name || item.key, "resource-thumb background-thumb") : '<span class="resource-thumb sound-thumb" aria-hidden="true">SE</span>'}<span><strong>${esc(item.name || item.key)}</strong><small>${esc(item.key)}</small><small>${picker.kind === "backgrounds" ? "选择后会替换当前卡片的背景指令。" : "选择后会替换当前卡片的声音指令。"}</small></span><b>${picker.kind === "backgrounds" ? "使用背景" : "使用声音"}</b></button>`).join("") : '<p class="empty">没有匹配的已登记素材。</p>';
      $$("[data-resource-key]").forEach((button) => button.addEventListener("click", async () => {
        const selected = items.find((item) => item.key === button.dataset.resourceKey);
        if (!selected) return;
        $("#resourceDialog").close();
        await picker.callback(selected);
      }));
      $("#resourceDialogStatus").textContent = items.length ? `找到 ${result.total} 个${picker.label}。` : "没有匹配的已登记素材。";
    } catch (error) { $("#resourceDialogStatus").textContent = error.message; }
  }

  function assetLibraryItem(item, kind) {
    const key = item.key || item.identifier || "";
    const name = item.name || key;
    const preview = kind === "characters" || kind === "backgrounds" || kind === "cg"
      ? previewImage(kind, key, name, `resource-thumb ${kind === "characters" ? "avatar-thumb" : kind === "cg" ? "cg-thumb" : "background-thumb"}`)
      : '<span class="resource-thumb sound-thumb" aria-hidden="true">SE</span>';
    const usage = state.assetUsage[`${kind}:${key}`] || [];
    const usageText = usage.length ? `本任务已使用 ${usage.length} 处：${usage.slice(0, 2).map((item) => item.line_no ? `第 ${item.line_no} 张` : item.label).join("、")}` : "本任务尚未使用";
    const detail = kind === "characters"
      ? `${item.club || "未标注社团"} · ${item.face_count || 0} 个表情`
      : kind === "backgrounds" ? "可用于场景和无立绘 CG 背景" : kind === "sounds" ? "可用于音效指令卡片" : "可用于 @popup 插图指令";
    const imported = item.source === "task_import";
    const source = imported ? "本任务导入" : "初始素材快照";
    const remove = imported ? `<button type="button" class="asset-remove" data-remove-asset-id="${esc(item.asset_id || "")}" data-remove-asset-name="${esc(name)}" ${usage.length ? "disabled title=\"已被当前任务使用，请先在审查器替换引用\"" : ""}>${usage.length ? "正在使用" : "移除导入素材"}</button>` : "";
    return `<article class="asset-library-item">${preview}<div><strong>${esc(name)}</strong><small>${esc(key)}</small><small>${esc(detail)}</small><small class="asset-usage ${usage.length ? "used" : "unused"}">${esc(usageText)}</small></div><div class="asset-item-actions"><span class="asset-source ${imported ? "imported" : ""}">${source}</span>${remove}</div></article>`;
  }

  async function loadAssetLibrary({ reset = false } = {}) {
    if (reset) state.assetLibraryOffset = 0;
    const query = $("#assetLibrarySearch").value.trim();
    const kind = state.assetLibraryKind;
    try {
      const path = state.currentRun
        ? `/production-runs/${encodeURIComponent(state.currentRun.run_id)}/resources/${kind}?q=${encodeURIComponent(query)}&offset=${state.assetLibraryOffset}&limit=36`
        : `/resources/${kind}?q=${encodeURIComponent(query)}&offset=${state.assetLibraryOffset}&limit=36`;
      const result = await api(path);
      const html = (result.items || []).map((item) => assetLibraryItem(item, kind)).join("");
      $("#assetLibraryResults").innerHTML = reset || state.assetLibraryOffset === 0 ? html : $("#assetLibraryResults").innerHTML + html;
      state.assetLibraryTotal = result.total || 0;
      state.assetLibraryOffset += (result.items || []).length;
      $$('[data-remove-asset-id]').forEach((button) => button.addEventListener("click", () => removeTaskAsset(button.dataset.removeAssetId, button.dataset.removeAssetName)));
      $("#assetLibraryStatus").textContent = result.total ? `找到 ${result.total} 个${kind === "characters" ? "角色" : kind === "backgrounds" ? "背景" : kind === "sounds" ? "音效" : "插图"}；可从卡片右侧确认来源和是否能移除。` : "没有匹配的已登记素材。";
      $("#assetLibraryMore").disabled = !result.has_more;
    } catch (error) { $("#assetLibraryStatus").textContent = error.message; }
  }

  function openAssetLibrary() {
    $("#assetLibrarySearch").value = "";
    $("#assetLibraryDialog").showModal();
    const usageRequest = state.currentRun ? api(`/production-runs/${encodeURIComponent(state.currentRun.run_id)}/resource-usage`).then((result) => { state.assetUsage = result.usage || {}; }).catch(() => { state.assetUsage = {}; }) : Promise.resolve();
    usageRequest.then(() => loadAssetLibrary({ reset: true }));
  }

  async function removeTaskAsset(assetId, name) {
    if (!assetId || !state.currentRun || !state.currentDraft) return;
    if (!window.confirm(`移除“${name}”？它会从当前任务的可用素材中删除，且不会写入 AA 工作区。`)) return;
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

  function updateAssetImportForm() {
    const kind = selectedAssetImportKind();
    const file = $("#assetImportFile");
    file.value = "";
    file.accept = ["background", "cg"].includes(kind) ? ".png,.jpg,.jpeg" : kind === "sound" ? ".wav" : ".zip";
    $("#assetCharacterFields").classList.toggle("hidden", kind !== "character");
    $("#assetBackgroundFields").classList.toggle("hidden", !["background", "cg"].includes(kind));
    $("#assetValidationResult").className = "asset-validation empty";
    $("#assetValidationResult").textContent = "选择文件后，点击“上传并检查”。";
    $("#assetImportStatus").textContent = kind === "character" ? "角色 ZIP 必须含 skel、atlas、贴图和头像。" : kind === "cg" ? "插图会在构建时写入 PopupOverrides，可在高级指令中用 @popup 调用。" : "尚未选择文件。";
    $("#registerAssetImport").disabled = true;
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
    }
    if (["background", "cg"].includes(kind)) payload.labels = { label: $("#assetLabel").value.trim() };
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

  async function validateAssetImport() {
    const file = $("#assetImportFile").files?.[0];
    const kind = selectedAssetImportKind();
    if (!file) { $("#assetImportStatus").textContent = "请先选择要导入的文件。"; return; }
    if (kind === "character" && (!$("#assetIdentifier").value.trim() || !$("#assetDisplayName").value.trim())) {
      $("#assetImportStatus").textContent = "角色骨骼需要填写 Identifier 和显示名称。"; return;
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
      toast(`已登记“${result.asset?.name || result.asset?.key || "素材"}”。现在可在当前任务中选择使用。`);
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
      await refreshCurrentRun(); toast(result.valid ? "检查通过。" : "检查完成：仍有需要处理的问题。", result.valid ? "normal" : "warning");
    } catch (error) { handleError(error); }
  }

  async function pollJob(jobId, label) {
    for (let attempt = 0; attempt < 180; attempt += 1) {
      const result = await api(`/jobs/${encodeURIComponent(jobId)}`);
      const job = result.job;
      toast(`${label}：${job.state === "succeeded" ? "已完成" : job.state === "failed" ? "失败" : "后台处理中"}`);
      if (job.state === "succeeded") { await refreshCurrentRun(); return job; }
      if (["failed", "interrupted"].includes(job.state)) throw Object.assign(new Error(job.error?.message || `${label}未完成`), { code: job.error?.code || "job_failed" });
      await new Promise((resolve) => setTimeout(resolve, 700));
    }
    throw Object.assign(new Error(`${label}超时，请在后台任务中查看状态。`), { code: "job_timeout" });
  }

  async function compileRun() {
    if (!state.currentRun || !state.currentDraft) return;
    try {
      const result = await api(`/production-runs/${state.currentRun.run_id}/compile`, { method: "POST", body: JSON.stringify({ expected_draft_version: state.currentDraft.draft_version }) });
      await pollJob(result.job.job_id, "AA 编译");
      renderReview(); renderInstallPanel();
    } catch (error) { handleError(error); }
  }

  function renderInstallPanel() {
    if (!state.currentRun || !["compiled", "installed"].includes(state.currentRun.state)) return;
    const inspector = $("#inspectorBody");
    const panel = document.createElement("section"); panel.className = "install-panel"; panel.innerHTML = '<hr><small>安装到 AA</small><h4>编译已完成，先预检目标</h4><label>分类<input id="installCategory" placeholder="例如：活动剧情"></label><label>剧情名<input id="installStoryName"></label><div class="inspector-actions"><button id="checkInstall">预检安装目标</button><button class="primary" id="installRun" disabled>安装</button></div><p id="installStatus" class="inspector-note"></p>';
    inspector.appendChild(panel);
    api(`/production-runs/${state.currentRun.run_id}/install-options?build_id=${state.currentRun.last_build_id}`).then((result) => { $("#installStoryName").value = result.default_story_name || state.currentRun.project; }).catch(handleError);
    $("#checkInstall").addEventListener("click", async () => {
      try { const result = await api(`/production-runs/${state.currentRun.run_id}/install-check`, { method: "POST", body: JSON.stringify({ build_id: state.currentRun.last_build_id, category: $("#installCategory").value, story_name: $("#installStoryName").value }) }); $("#installStatus").textContent = result.target.conflict ? `目标 ${result.target.project} 已存在，请更换名称。` : `目标 ${result.target.project} 可用。`; $("#installRun").disabled = result.target.conflict; } catch (error) { handleError(error); }
    });
    $("#installRun").addEventListener("click", async () => {
      if (!window.confirm("将把当前构建写入已配置的 AA 工作区，是否继续？")) return;
      try { const result = await api(`/production-runs/${state.currentRun.run_id}/install`, { method: "POST", body: JSON.stringify({ build_id: state.currentRun.last_build_id, category: $("#installCategory").value, story_name: $("#installStoryName").value }) }); applyRun(result); toast(`已安装到 ${result.install.project || "AA"}`); } catch (error) { handleError(error); }
    });
  }

  function applyRun(result) {
    const selectedId = state.selectedCard?.card_id;
    state.currentRun = result.run;
    state.currentDraft = result.draft;
    state.gates = result.gates;
    state.selectedCard = result.draft?.cards?.find((card) => card.card_id === selectedId) || null;
    loadTaskPreflight();
    updateShell(); renderMapping(); renderGeneration(); renderReview();
  }

  async function loadModelSettings() {
    try { const result = await api("/settings/direction-model"); state.model = result.model; $("#modelProvider").value = result.model.provider || "openai"; $("#modelBaseUrl").value = result.model.base_url || ""; $("#modelName").value = result.model.model || ""; $("#modelStatus").textContent = result.model.configured ? `已配置 · ${result.model.secret_source}` : "尚未配置"; } catch (error) { handleError(error); }
  }

  function showSettingsPane(name) {
    $$('[data-settings-pane]').forEach((button) => button.classList.toggle("active", button.dataset.settingsPane === name));
    $("#settingsWorkspacePane").classList.toggle("hidden", name !== "workspace");
    $("#modelForm").classList.toggle("hidden", name !== "model");
  }

  async function openSettingsDialog(pane = "workspace") {
    showSettingsPane(pane);
    const dialog = $("#settingsDialog");
    if (!dialog.open) dialog.showModal();
    if (pane === "model") await loadModelSettings();
    else await inspectAaEnvironment(false, true);
  }

  function renderAaEnvironment(result) {
    state.aaEnvironment = result.environment;
    const environment = result.environment || {};
    const workspace = environment.workspace || {};
    const cache = environment.resource_cache || {};
    const status = $("#aaEnvironmentStatus");
    const path = workspace.path || "未找到工作区";
    const issue = environment.issues?.[0];
    status.className = `environment-status ${workspace.valid ? "ready" : "needs-work"}`;
    status.innerHTML = `<strong>${workspace.valid ? "AA 制作环境可用" : "还不能用于制作"}</strong><p>${esc(path)}</p><div><span>工程目录 ${workspace.directories?.projects ? "可用" : "缺失"}</span><span>存档目录 ${workspace.directories?.saves ? "可用" : "缺失"}</span><span>官方资源 ${cache.available ? "已发现" : "未发现"}</span></div>${issue ? `<small>${esc(issue.code)} · ${esc(issue.message)}</small>` : ""}`;
    if (!$("#aaSelection").value.trim() && workspace.path) $("#aaSelection").value = workspace.path;
    $("#adoptAaEnvironment").disabled = !workspace.valid || result.adopted === true;
    if (result.adopted) $("#adoptAaEnvironment").textContent = "已采用";
    else $("#adoptAaEnvironment").textContent = "采用此工作区";
  }

  async function inspectAaEnvironment(adopt = false, automatic = false) {
    const selection = $("#aaSelection").value.trim();
    $("#aaEnvironmentStatus").innerHTML = "<strong>正在检测</strong><p>读取 AA 程序和工作区配置。</p>";
    try {
      const result = automatic && !selection
        ? await api("/settings/aa-environment")
        : await api("/settings/aa-environment", { method: "POST", body: JSON.stringify({ selection, adopt }) });
      renderAaEnvironment(result);
      if (adopt) { await refreshCapabilities(); toast("AA 制作环境已采用。"); }
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

  async function renderTasks() {
    try {
      const result = await api("/jobs");
      const labels = { queued: "等待执行", running: "正在执行", succeeded: "已完成", failed: "失败", interrupted: "服务重启中断", cancelled: "已取消" };
      $("#taskList").innerHTML = result.items?.length ? result.items.slice(0, 30).map((job) => {
        const failed = ["failed", "interrupted"].includes(job.state);
        const detail = failed ? (job.error?.message || "任务未完成，请查看关联制作任务。") : (job.next_action?.detail || "等待状态更新。");
        const actions = [];
        if (job.state === "queued") {
          actions.push(`<button type="button" data-cancel-job="${esc(job.job_id)}">取消排队</button>`);
        }
        if (job.retryable) {
          actions.push(`<button type="button" class="primary" data-retry-job="${esc(job.job_id)}">${esc(job.retry_label || "重试此阶段")}</button>`);
        }
        if (job.run_id && job.next_action?.stage) {
          actions.push(`<button type="button" class="task-open-run" data-task-run-id="${esc(job.run_id)}" data-task-stage="${esc(job.next_action.stage)}">打开关联任务</button>`);
        }
        const action = actions.length ? `<div class="task-row-actions">${actions.join("")}</div>` : "";
        return `<article class="task-row task-${esc(job.state)}"><div><div class="task-row-top"><strong>${esc(job.label || job.kind)}</strong><b>${esc(labels[job.state] || job.state)}</b></div><small>${esc(job.job_id)}${job.run_id ? ` · ${esc(job.run_id)}` : ""}</small><p>${esc(detail)}</p></div>${action}</article>`;
      }).join("") : '<p class="empty">暂无后台任务。</p>';
      $$("[data-task-run-id]").forEach((button) => button.addEventListener("click", () => openRunFromTask(button.dataset.taskRunId, button.dataset.taskStage)));
      $$('[data-cancel-job]').forEach((button) => button.addEventListener("click", async () => {
        try { await api(`/jobs/${encodeURIComponent(button.dataset.cancelJob)}?action=cancel`, { method: "POST", body: "{}" }); await renderTasks(); toast("排队任务已取消。"); } catch (error) { handleError(error); }
      }));
      $$('[data-retry-job]').forEach((button) => button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await api(`/jobs/${encodeURIComponent(button.dataset.retryJob)}?action=retry`, { method: "POST", body: "{}" });
          await renderTasks();
          toast("已重新提交该阶段，旧任务记录仍会保留。");
        } catch (error) {
          button.disabled = false;
          handleError(error);
        }
      }));
    } catch (error) { handleError(error); }
  }

  async function openRunFromTask(runId, stage) {
    try {
      const result = await api(`/production-runs/${encodeURIComponent(runId)}`);
      state.currentRun = result.run;
      state.currentDraft = result.draft;
      state.gates = result.gates;
      await loadTaskPreflight();
      $("#tasksDialog").close();
      updateShell();
      showStage(stage || "review", { force: true });
      toast("已打开关联制作任务，请按当前提示继续处理。", "warning");
    } catch (error) { handleError(error); }
  }

  document.addEventListener("click", (event) => {
    const stage = event.target.closest("[data-stage]"); if (stage) showStage(stage.dataset.stage);
    const filter = event.target.closest("[data-filter]"); if (filter) { state.filter = filter.dataset.filter; $$("[data-filter]").forEach((item) => item.classList.toggle("active", item === filter)); renderReview(); }
    const close = event.target.closest("[data-close-dialog]"); if (close) { event.preventDefault(); event.stopPropagation(); const dialog = $(`#${close.dataset.closeDialog}`); if (dialog?.open) dialog.close(); return; }
  });
  document.addEventListener("keydown", (event) => {
    const stage = event.target.closest(".stage-list [data-stage]");
    if (!stage || !["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    showStage(stage.dataset.stage);
  });
  $("#sourceForm").addEventListener("submit", createRun);
  $$('#sourceForm input[name="generationMode"]').forEach((input) => input.addEventListener("change", updateGenerationModeUi));
  $("#configureGenerationModel").addEventListener("click", () => openSettingsDialog("model"));
  $("#preflightSource").addEventListener("click", preflightSource);
  $("#reloadRuns").addEventListener("click", loadRuns);
  $("#refreshRun").addEventListener("click", () => refreshCurrentRun().catch(handleError));
  $("#mappingContinue").addEventListener("click", () => showStage("generation"));
  $("#generateOrReview").addEventListener("click", startGeneration);
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
  $("#resourceSearch").addEventListener("input", (event) => searchResources(event.target.value));
  $("#openAssetLibrary").addEventListener("click", openAssetLibrary);
  $("#openAssetImport").addEventListener("click", openAssetImport);
  $$('input[name="assetImportKind"]').forEach((input) => input.addEventListener("change", updateAssetImportForm));
  $("#validateAssetImport").addEventListener("click", validateAssetImport);
  $("#registerAssetImport").addEventListener("click", registerAssetImport);
  $("#assetLibrarySearch").addEventListener("input", () => loadAssetLibrary({ reset: true }));
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
    else await inspectAaEnvironment(false, true);
  }));
  $("#inspectAaEnvironment").addEventListener("click", () => inspectAaEnvironment(false));
  $("#adoptAaEnvironment").addEventListener("click", () => inspectAaEnvironment(true));
  $("#modelForm").addEventListener("submit", saveModel);
  $("#testModel").addEventListener("click", testModel);
  $("#openTasks").addEventListener("click", async () => { await renderTasks(); $("#tasksDialog").showModal(); });
  $("#refreshTasks").addEventListener("click", renderTasks);

  (async function boot() {
    setupSourceTabs();
    setupModernDropzone();
    try {
      await Promise.all([
        refreshCapabilities(),
        loadModelSettings(),
        loadRuns(),
        loadWritingWorksAndReleases()
      ]);
    } catch (error) {
      $("#serviceState").textContent = "后端未连接";
      handleError(error);
    }
  }());
})();
