(() => {
  "use strict";

  const hostId = "productionModule";
  const hiddenWritingChromeSelector = [
    "#app > .tree-panel",
    "#app > .workspace",
    "#app > .inspector",
    "#app > .panel-rail",
    "#app > .topbar .panel-controls",
    "#app > .topbar [data-action='new-work']",
  ].join(", ");
  let loadPromise = null;
  let loadState = "cold";
  let loadStartedAt = 0;
  let loadFinishedAt = 0;
  let previousChrome = null;
  let activeContext = null;
  let openEpoch = 0;
  let menuEvents = null;

  const sleep = (delay) => new Promise(resolve => setTimeout(resolve, delay));
  const app = () => document.querySelector("#app");
  const host = () => document.querySelector(`#${hostId}`);

  function linkedContext(trigger = null) {
    const params = new URLSearchParams(location.search);
    const linked = trigger?.matches?.("[data-open-production]") ? trigger
      : params.get("section") === "production" ? null : document.querySelector("[data-open-production]");
    if (linked) return { runId: linked.dataset.openProduction || "", workId: linked.dataset.workId || "", releaseId: linked.dataset.releaseId || "" };
    return { runId: params.get("run_id") || "", workId: params.get("work_id") || "", releaseId: params.get("release_id") || "" };
  }

  function syncChrome() {
    if (!activeContext || !app()?.classList.contains("production-mode")) return;
    let title = document.querySelector(".production-context-name");
    if (!title) {
      title = document.createElement("span");
      title.className = "production-context-name";
      document.querySelector(".hc-work-switch")?.before(title);
    }
    title.textContent = activeContext.title || "正在打开制作任务…";
    title.title = title.textContent;
    const crumb = document.querySelector("#crumb");
    if (crumb) {
      crumb.textContent = "AA 制作";
      crumb.title = `${title.textContent} / AA 制作`;
      crumb.setAttribute("aria-label", crumb.title);
    }
  }

  function updateUrl(context, replace = false) {
    const url = new URL(location.href);
    url.pathname = "/";
    url.search = "";
    url.searchParams.set("section", "production");
    if (context.runId) url.searchParams.set("run_id", context.runId);
    if (context.workId) url.searchParams.set("work_id", context.workId);
    if (context.releaseId) url.searchParams.set("release_id", context.releaseId);
    history[replace ? "replaceState" : "pushState"]({ ...history.state, section: "production", ...context }, "", url);
  }

  function captureNavigationState() {
    return [...document.querySelectorAll("[data-section], [data-mobile]")].map(item => ({
      item,
      active: item.classList.contains("active"),
      ariaCurrent: item.getAttribute("aria-current"),
    }));
  }

  function showProductionNavigation() {
    document.querySelectorAll("[data-mobile].active").forEach(item => item.classList.remove("active"));
    document.querySelectorAll(".primary-nav, .mobile-nav").forEach(navigation => {
      const items = [...navigation.querySelectorAll("[data-section], [data-mobile]")];
      items.forEach(item => {
        item.classList.remove("active");
        item.removeAttribute("aria-current");
      });
      const production = navigation.querySelector('[data-section="production"]');
      production?.classList.add("active");
      production?.setAttribute("aria-current", "page");
    });
  }

  function restoreNavigationState(states = []) {
    states.forEach(({ item, active, ariaCurrent }) => {
      item.classList.toggle("active", active);
      if (ariaCurrent === null) item.removeAttribute("aria-current");
      else item.setAttribute("aria-current", ariaCurrent);
    });
  }

  function captureWritingChromeState() {
    return [...document.querySelectorAll(hiddenWritingChromeSelector)].map(item => ({
      item,
      ariaHidden: item.getAttribute("aria-hidden"),
      inert: item.inert,
    }));
  }

  function hideWritingChromeFromAccessibility(states = []) {
    states.forEach(({ item }) => {
      item.inert = true;
      item.setAttribute("aria-hidden", "true");
    });
  }

  function restoreWritingChromeAccessibility(states = []) {
    states.forEach(({ item, ariaHidden, inert }) => {
      item.inert = inert;
      if (ariaHidden === null) item.removeAttribute("aria-hidden");
      else item.setAttribute("aria-hidden", ariaHidden);
    });
  }

  function setOuterChrome(context) {
    const crumb = document.querySelector("#crumb");
    const save = document.querySelector("#saveStatus");
    if (!previousChrome) {
      previousChrome = {
        crumb: crumb?.textContent || "",
        save: save?.textContent || "",
        saveState: save?.dataset.state || "",
        navigation: captureNavigationState(),
        writingChrome: captureWritingChromeState(),
      };
    }
    syncChrome();
    if (save) {
      save.textContent = context.runId ? "制作任务已打开" : "选择制作任务";
      save.dataset.state = "saved";
    }
    showProductionNavigation();
    hideWritingChromeFromAccessibility(previousChrome.writingChrome);
  }

  function installOuterActions(root) {
    const topActions = document.querySelector("#app > .topbar .top-actions");
    if (!topActions) return;
    menuEvents?.abort();
    menuEvents = new AbortController();
    topActions.querySelector(".production-top-actions")?.remove();
    const controls = document.createElement("span");
    controls.className = "production-top-actions";
    controls.innerHTML = `
      <button type="button" class="quiet production-assets" data-production-proxy="openAssetLibrary">制作素材</button>
      <details class="production-more-actions">
        <summary aria-label="更多制作操作" title="更多制作操作">更多<span aria-hidden="true">⌄</span></summary>
        <div role="menu">
          <button type="button" class="production-overview" data-production-proxy="openRunOverview" role="menuitem">任务总览</button>
          <button type="button" class="production-new" data-production-proxy="startNewProduction" role="menuitem">新建制作</button>
          <button type="button" data-production-proxy="openTasks" role="menuitem">后台任务</button>
          <button type="button" data-production-proxy="refreshRun" role="menuitem" aria-label="刷新制作任务">刷新制作任务</button>
        </div>
      </details>`;
    controls.addEventListener("click", event => {
      const button = event.target.closest("[data-production-proxy]");
      if (!button) return;
      if (button.dataset.productionProxy === "startNewProduction") root.querySelector(".embedded-production-shell")?.haloCueShowNewProduction?.();
      else root.querySelector(`#${button.dataset.productionProxy}`)?.click();
      button.closest("details")?.removeAttribute("open");
    });
    topActions.prepend(controls);
    const menu = controls.querySelector("details");
    controls.addEventListener("keydown", event => {
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        const items = [...menu.querySelectorAll("button:not([hidden]):not(:disabled)")];
        if (!items.length) return;
        event.preventDefault();
        menu.open = true;
        const current = items.indexOf(document.activeElement);
        const index = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
          : event.key === "ArrowDown" ? (current + 1) % items.length
          : (current < 0 ? items.length - 1 : (current + items.length - 1) % items.length);
        items[index].focus();
        return;
      }
      if (event.key !== "Escape" || !menu.open) return;
      event.preventDefault();
      event.stopPropagation();
      menu.open = false;
      menu.querySelector("summary")?.focus();
    });
    document.addEventListener("pointerdown", event => {
      if (!menu.contains(event.target)) menu.open = false;
    }, { signal: menuEvents.signal });
    const syncAvailability = () => {
      const assetButton = controls.querySelector(".production-assets");
      const newButton = controls.querySelector(".production-new");
      const overviewButton = controls.querySelector(".production-overview");
      const hasRun = !root.querySelector("#openRunOverview")?.disabled;
      if (!assetButton) return;
      if (newButton) newButton.hidden = !hasRun;
      if (overviewButton) overviewButton.hidden = !hasRun;
      assetButton.hidden = !hasRun;
      assetButton.disabled = !hasRun;
      assetButton.title = hasRun ? "打开当前任务素材" : "先打开一个制作任务";
      assetButton.setAttribute("aria-disabled", String(!hasRun));
    };
    const overviewButton = root.querySelector("#openRunOverview");
    if (overviewButton) {
      new MutationObserver(syncAvailability).observe(overviewButton, { attributes: true, attributeFilter: ["disabled"] });
    }
    syncAvailability();
  }

  function restoreOuterChrome() {
    menuEvents?.abort();
    menuEvents = null;
    if (!previousChrome) return;
    const crumb = document.querySelector("#crumb");
    const save = document.querySelector("#saveStatus");
    if (crumb) crumb.textContent = previousChrome.crumb;
    if (save) {
      save.textContent = previousChrome.save;
      save.dataset.state = previousChrome.saveState;
    }
    restoreNavigationState(previousChrome.navigation);
    restoreWritingChromeAccessibility(previousChrome.writingChrome);
    document.querySelector(".production-top-actions")?.remove();
    previousChrome = null;
    activeContext = null;
    document.querySelector(".production-context-name")?.remove();
  }

  function ensureHost() {
    let element = host();
    if (element) return element;
    element = document.createElement("section");
    element.id = hostId;
    element.className = "production-module-host";
    element.setAttribute("aria-label", "AA 制作工作面");
    element.setAttribute("aria-busy", "true");
    element.tabIndex = -1;
    element.hidden = true;
    app()?.append(element);
    return element;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  }

  function installCurrentTaskSourceBoundary(root) {
    if (root.__haloCueCurrentTaskBoundary) return;
    const shell = root.querySelector(".embedded-production-shell");
    const source = root.querySelector("#page-source");
    const form = root.querySelector("#sourceForm");
    const recent = root.querySelector(".recent-runs");
    if (!shell || !source || !form) return;
    const lead = source.querySelector(".page-lead");
    const panel = document.createElement("section");
    panel.className = "production-current-task-boundary";
    panel.setAttribute("aria-labelledby", "currentTaskBoundaryTitle");
    panel.hidden = true;
    if (lead) lead.insertAdjacentElement("afterend", panel);
    const render = () => {
      const snapshot = shell.haloCueGetState?.() || {};
      const run = snapshot.run;
      const draft = snapshot.draft;
      const active = Boolean(run);
      panel.hidden = !active;
      form.hidden = active;
      if (recent) recent.hidden = active;
      if (!active) return;
      const summary = run.source_summary || {};
      const scenes = Array.isArray(summary.scenes) ? summary.scenes : [];
      const sourceText = draft?.frozen_source_text || "";
      const upstream = summary.upstream_release && summary.upstream_release.kind === "halocue_writing"
        ? summary.upstream_release : null;
      const sourceLabel = upstream
        ? `写作定稿 ${upstream.display_version || "已确认"}`
        : summary.source_kind === "file_upload"
          ? `本机文件${summary.source_filename ? ` · ${summary.source_filename}` : ""}`
          : "直接导入剧本";
      const buildVersion = Number.isInteger(run.last_build_draft_version)
        ? `构建基于草稿 v${run.last_build_draft_version}`
        : "尚未生成构建";
      const buildState = Number.isInteger(run.last_build_draft_version)
        && Number.isInteger(draft?.draft_version)
        && run.last_build_draft_version !== draft.draft_version
        ? "构建已落后于当前草稿"
        : buildVersion;
      const sceneList = scenes.length
        ? scenes.map(scene => `<li><strong>${escapeHtml(scene.title || "未命名场景")}</strong><span>第 ${escapeHtml(scene.line_no || "-")} 行</span></li>`).join("")
        : "<li><strong>未读取到场景摘要</strong><span>请刷新任务</span></li>";
      panel.innerHTML = `
        <header class="production-current-task-head">
          <div><small>当前制作任务 · 来源已冻结</small><h3 id="currentTaskBoundaryTitle">${escapeHtml(run.project || "未命名工程")}</h3><p>这不是新建表单。当前任务的剧本、场景边界和下游草稿保持独立，不会被下面的“新建制作”覆盖。</p></div>
          <span class="production-current-task-state">${escapeHtml({waiting_for_review:"等待审查",compiled:"已编译",installed:"已安装",generating_direction:"演出生成中",direction_failed:"演出生成失败"}[run.state] || run.state || "处理中")}</span>
        </header>
        <div class="production-current-task-metrics"><span><small>剧本</small><b>${escapeHtml(summary.line_count || 0)} 行</b></span><span><small>场景</small><b>${escapeHtml(summary.scene_count || scenes.length || 0)} 个</b></span><span><small>草稿</small><b>v${escapeHtml(draft?.draft_version || "-")}</b></span><span><small>待审</small><b>${escapeHtml(draft?.counts?.pending || 0)} 张</b></span></div>
        <section class="production-task-provenance" aria-label="当前任务来源与版本"><div><small>来源</small><strong>${escapeHtml(sourceLabel)}</strong></div><div><small>下游版本</small><strong>审查草稿 v${escapeHtml(draft?.draft_version || "-")}</strong></div><div class="${buildState === "构建已落后于当前草稿" ? "is-stale" : ""}"><small>构建状态</small><strong>${escapeHtml(buildState)}</strong></div></section>
        <section class="production-frozen-source"><header><div><small>1A · 当前使用的冻结剧本</small><h4>不会改写写作正文</h4></div><details><summary>展开剧本</summary><pre>${escapeHtml(sourceText || "当前任务未提供可展开的剧本文本")}</pre></details></header></section>
        <section class="production-frozen-scenes"><header><div><small>1B · 已确认的场景判断</small><h4>下游制作沿用这些边界</h4></div><span>只读</span></header><ol>${sceneList}</ol></section>
        <footer class="production-current-task-actions"><span>下一步：${escapeHtml(snapshot.stage === "review" ? "进入逐卡审查" : snapshot.stage === "generation" ? "完成演出生成" : "处理角色与素材")}</span><div><button type="button" class="quiet" data-current-task-continue>继续当前任务</button><button type="button" class="primary" data-current-task-new>新建另一项制作</button></div></footer>`;
      panel.querySelector("[data-current-task-continue]")?.addEventListener("click", () => shell.haloCueShowStage?.(snapshot.stage));
      panel.querySelector("[data-current-task-new]")?.addEventListener("click", () => shell.haloCueShowNewProduction?.());
    };
    shell.addEventListener("halocue:production-run-changed", render);
    shell.addEventListener("halocue:production-new-mode", render);
    root.__haloCueCurrentTaskBoundary = { render };
    render();
  }

  function installFocusRecovery(root, element) {
    if (root.__haloCueFocusRecovery) return;
    const observer = new MutationObserver(() => {
      if (!app()?.classList.contains("production-mode") || element.hidden) return;
      if (document.activeElement !== document.body) return;
      queueMicrotask(() => {
        if (app()?.classList.contains("production-mode") && !element.hidden && document.activeElement === document.body) {
          element.focus({ preventScroll: true });
        }
      });
    });
    observer.observe(root, { childList: true, subtree: true });
    root.__haloCueFocusRecovery = observer;
  }

  function sanitizeProductionUserLabels(root) {
    const sideHeader = root.querySelector(".side-header");
    if (sideHeader) {
      const eyebrow = sideHeader.querySelector("small");
      const title = sideHeader.querySelector("h1");
      const description = sideHeader.querySelector("p:not(#runTitle)");
      if (eyebrow && eyebrow.textContent !== "AA 制作") eyebrow.textContent = "AA 制作";
      if (title && title.textContent !== "AA 制作") title.textContent = "AA 制作";
      if (description && description.textContent !== "把已发布剧本整理成可预览、可安装的 AA 工程") {
        description.textContent = "把已发布剧本整理成可预览、可安装的 AA 工程";
      }
    }
    const modelState = root.querySelector("#aiModeState");
    if (modelState && /已就绪|ready/i.test(modelState.textContent || "") && modelState.textContent !== "可以使用") {
      modelState.textContent = "可以使用";
    }
    root.querySelectorAll('small').forEach(node => {
      const text = node.textContent?.trim() || '';
      const runMatch = text.match(/^run-[a-z0-9]+\s*·\s*(.+)$/i);
      if (runMatch) {
        const status = {
          compiled: '已编译',
          installed: '已安装',
          waiting_for_review: '待审查',
          direction_failed: '需要处理',
        }[runMatch[1]] || '已记录';
        node.textContent = status;
        return;
      }
      if (/^(scene|line)\s*·\s*/i.test(text)) {
        node.textContent = text.replace(/^scene/i, '场景').replace(/^line/i, '对白');
      }
    });
    root.querySelectorAll('.draft-card p').forEach(node => {
      if ((node.textContent || '').trim().toLowerCase() === 'scene') node.textContent = '场景';
    });
    // The production workbench uses the run identity in its task heading for
    // internal navigation. Keep that identity in data attributes and API
    // calls, but remove it from the ordinary heading shown to users.
    root.querySelectorAll('p,small,strong,span,h3').forEach(node => {
      if ([...node.children].length) return;
      const text = node.textContent || '';
      const translated = text
        .replace(/\s*·\s*run-[a-z0-9]+/ig, '')
        .replace(/(^|\s*·\s*)scene(?=\s|$)/ig, '$1场景')
        .replace(/(^|\s*·\s*)line(?=\s|$)/ig, '$1对白')
        .trim();
      if (translated !== text) node.textContent = translated;
    });
  }

  function installProductionLabelSanitizer(root) {
    if (root.__haloCueProductionLabelSanitizer) return;
    const observer = new MutationObserver(() => sanitizeProductionUserLabels(root));
    observer.observe(root, { childList: true, subtree: true, characterData: true });
    root.__haloCueProductionLabelSanitizer = observer;
    sanitizeProductionUserLabels(root);
  }

  function stylesheet(href) {
    const link = document.createElement("link");
    const loaded = new Promise((resolve, reject) => {
      link.rel = "stylesheet";
      link.href = href;
      link.onload = resolve;
      link.onerror = () => reject(new Error(`无法载入制作样式：${href}`));
    });
    loaded.link = link;
    return loaded;
  }

  function stripInlineStyles(element) {
    if (element.hasAttribute("style")) element.removeAttribute("style");
    element.querySelectorAll("[style]").forEach(node => node.removeAttribute("style"));
    return element;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function currentProductionRunId(root) {
    return activeContext?.runId || linkedContext().runId
      || root.querySelector("[data-run-id].active")?.dataset.runId
      || root.querySelector("[data-run-id]")?.dataset.runId
      || "";
  }

  function productionResourceUrl(runId, kind, key, suffix = "") {
    return `/production/api/v1/production-runs/${encodeURIComponent(runId)}/resources/${kind}/${encodeURIComponent(key)}${suffix}`;
  }

  async function fetchBackgroundFacets(root) {
    const response = await fetch("/api/v1/resources/search?kind=backgrounds&facets=1");
    if (!response.ok) throw new Error(`背景分类读取失败（${response.status}）`);
    const payload = await response.json();
    const data = payload?.data || payload;
    return Array.isArray(data?.categories) ? data.categories : [];
  }

  const backgroundCategoryLabels = {
    "校园": "校园",
    "室内": "室内",
    "室外": "室外",
    "自然": "自然",
    "街道": "街道",
    "商业": "商业",
    "商业街": "商业街",
    "交通": "交通",
    "活动": "活动",
    "教室": "教室",
    "走廊": "走廊",
    "校门": "校门",
  };

  function backgroundCategoryLabel(value) {
    const text = String(value || "").trim();
    if (!text || !/[\u3400-\u9fff]/.test(text)) return "其他地点";
    return backgroundCategoryLabels[text] || text;
  }

  function backgroundGroupControls(root) {
    return root.querySelector(".embedded-background-groups");
  }

  function setBackgroundGroup(root, group) {
    const controls = backgroundGroupControls(root);
    if (!controls) return;
    controls.querySelectorAll("[data-background-group]").forEach(button => {
      const active = button.dataset.backgroundGroup === group;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    controls.dataset.backgroundGroup = group;
    controls.dataset.backgroundCategory = "";
    controls.querySelectorAll('[data-background-category]').forEach(button => {
      const active = !button.dataset.backgroundCategory;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
  }

  function ensureBackgroundGroupControls(root) {
    const dialog = root.querySelector("#assetLibraryDialog");
    const tabs = dialog?.querySelector(".asset-tabs");
    if (!dialog || !tabs) return null;
    let controls = backgroundGroupControls(root);
    if (controls) return controls;
    controls = document.createElement("div");
    controls.className = "embedded-background-groups";
    controls.hidden = true;
    controls.innerHTML = `<div class="embedded-background-group-buttons" role="group" aria-label="背景用途"><button type="button" class="active" data-background-group="scene" aria-pressed="true">场景背景</button><button type="button" data-background-group="cg" aria-pressed="false">官方 CG</button><button type="button" data-background-group="custom" aria-pressed="false">自定义背景</button></div><div class="embedded-background-category-list" data-background-categories hidden aria-label="背景分类"></div>`;
    void fetchBackgroundFacets(root).then(categories => {
      const list = controls.querySelector("[data-background-categories]");
      if (!list) return;
      list.innerHTML = `<button type="button" class="active" data-background-category="" aria-pressed="true">全部</button>` + categories.map(category => {
        const label = backgroundCategoryLabel(category.label);
        return label === "其他地点" ? "" : `<button type="button" data-background-category="${escapeHtml(label)}" aria-pressed="false">${escapeHtml(label)}</button>`;
      }).join("");
      list.hidden = false;
    }).catch(() => {});
    tabs.insertAdjacentElement("afterend", controls);
    return controls;
  }

  function simplifyBackgroundDialog(dialog) {
    if (!dialog) return;
    dialog.classList.add("embedded-background-browser");
    const heading = dialog.querySelector("header h3");
    if (heading && heading.textContent !== "选择背景") heading.textContent = "选择背景";
    const intro = dialog.querySelector("header p");
    if (intro) {
      if (!intro.hidden) intro.hidden = true;
      if (intro.textContent) intro.textContent = "";
    }
    const search = dialog.querySelector(".asset-workbench-controls label");
    if (search) {
      const label = search.childNodes[0];
      if (label && label.textContent !== "搜索背景") label.textContent = "搜索背景";
      const input = search.querySelector("input");
      if (input && input.placeholder !== "输入地点、氛围或背景名称") input.placeholder = "输入地点、氛围或背景名称";
    }
  }

  function restoreAssetDialogContext(dialog, kind) {
    if (!dialog || kind === "backgrounds") return;
    dialog.classList.remove("embedded-background-browser");
    const labels = {
      characters: { title: "角色素材", search: "搜索角色", placeholder: "输入角色名、服装或社团" },
      sounds: { title: "音效素材", search: "搜索音效", placeholder: "输入音效名称或用途" },
      cg: { title: "插图素材", search: "搜索插图", placeholder: "输入画面名称或用途" },
    };
    const selected = labels[kind] || labels.characters;
    const heading = dialog.querySelector("header h3");
    if (heading && heading.textContent !== selected.title) heading.textContent = selected.title;
    const search = dialog.querySelector(".asset-workbench-controls label");
    if (search) {
      const label = search.childNodes[0];
      if (label && label.textContent !== selected.search) label.textContent = selected.search;
      const input = search.querySelector("input");
      if (input && input.placeholder !== selected.placeholder) input.placeholder = selected.placeholder;
    }
  }

  function loadEmbeddedBackgroundLibrary(root, { reset = true } = {}) {
    // The production app owns requests, selection, details and paging.
    // The embedding layer only contributes category controls and presentation.
    return root.querySelector('.embedded-production-shell')?.haloCueLoadAssetLibrary?.({ reset });
  }

  function applyBackgroundCategory(root) {
    const controls = backgroundGroupControls(root);
    if (!controls) return;
    const category = controls.dataset.backgroundCategory || '';
    controls.querySelectorAll('[data-background-category]').forEach(button => {
      const active = button.dataset.backgroundCategory === category;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    loadEmbeddedBackgroundLibrary(root);
  }

  function installBackgroundClassification(root) {
    if (root.__haloCueBackgroundClassification) return;
    const syncLibrary = () => {
      const dialog = root.querySelector("#assetLibraryDialog");
      const controls = ensureBackgroundGroupControls(root);
      if (!controls) return;
      const kind = dialog?.querySelector(".asset-tabs button.active")?.dataset.assetKind;
      if (kind === "backgrounds") simplifyBackgroundDialog(dialog);
      else restoreAssetDialogContext(dialog, kind);
      controls.hidden = !dialog?.open || kind !== "backgrounds";

    };
    const observer = new MutationObserver(() => {
      syncLibrary();

    });
    observer.observe(root, { childList: true, subtree: true, characterData: true });
    root.addEventListener("click", event => {
      const groupButton = event.target.closest?.("[data-background-group]");
      if (groupButton) {
        event.preventDefault();
        event.stopImmediatePropagation();
        const group = groupButton.dataset.backgroundGroup || "scene";
        setBackgroundGroup(root, group);
        const controls = backgroundGroupControls(root);
        if (controls) { controls.dataset.backgroundLoaded = "true"; controls.dataset.backgroundOffset = "0"; }
        loadEmbeddedBackgroundLibrary(root);
        return;
      }
      const categoryButton = event.target.closest?.("[data-background-category]");
      if (categoryButton) {
        event.preventDefault();
        event.stopImmediatePropagation();
        const controls = backgroundGroupControls(root);
        if (controls) controls.dataset.backgroundCategory = categoryButton.dataset.backgroundCategory || "";
        applyBackgroundCategory(root);
        return;
      }
      const more = event.target.closest?.("#assetLibraryMore");
      const controls = backgroundGroupControls(root);
      if (more && controls && !controls.hidden) {
        event.preventDefault();
        event.stopImmediatePropagation();
        loadEmbeddedBackgroundLibrary(root, { reset: false });
      }
      window.setTimeout(syncLibrary, 0);
    }, true);
    root.addEventListener("input", event => {
      if (event.target?.id !== "assetLibrarySearch") return;
      const controls = backgroundGroupControls(root);
      if (!controls || controls.hidden) return;
      event.stopImmediatePropagation();
      clearTimeout(root.__haloCueBackgroundSearchTimer);
      root.__haloCueBackgroundSearchTimer = setTimeout(() => loadEmbeddedBackgroundLibrary(root), 160);
    }, true);
    root.__haloCueBackgroundClassification = observer;
    syncLibrary();
  }

  function restructureSourceSurface(workspace) {
    const source = workspace.querySelector("#page-source");
    const form = source?.querySelector("#sourceForm");
    const sourceSelector = source?.querySelector(".source-mode-selector");
    const documentBlock = form?.querySelector(".source-document-block");
    const documentHead = documentBlock?.querySelector(".source-workflow-head");
    if (!source || !form || !sourceSelector || !documentBlock || !documentHead) return;
    if (form.dataset.productionSourceSplit === "true") return;

    // In 0.95 the script itself and the scene judgement are separate
    // decisions. Keep the source picker with 1A, then place 1B/1C in the
    // parallel decision column so the user can see the boundary immediately.
    documentHead.insertAdjacentElement("afterend", sourceSelector);
    source.classList.add("production-source-workbench");
    form.classList.add("production-source-split");
    form.dataset.productionSourceSplit = "true";
  }

  function restructureGenerationSurface(workspace) {
    const generation = workspace.querySelector("#page-generation");
    const lead = generation?.querySelector(":scope > .page-lead");
    const scenePlan = generation?.querySelector(":scope > .scene-plan");
    const directionProfile = generation?.querySelector(":scope > #directionProfileControl");
    const actionPanel = generation?.querySelector(":scope > .action-panel");
    const generationJob = generation?.querySelector(":scope > #generationJob");
    const gates = generation?.querySelector(":scope > #generationGates");
    const layoutMode = generation?.querySelector(":scope > #generationExecutionNote");
    if (!generation || !lead || !scenePlan || !directionProfile || !actionPanel || !generationJob || !gates || !layoutMode) return;
    if (generation.dataset.productionGenerationSplit === "true") return;

    const leadKicker = lead.querySelector("small");
    const leadTitle = lead.querySelector("h3");
    if (leadKicker) leadKicker.textContent = "第三步";
    if (leadTitle) leadTitle.textContent = "演出生成";

    const flow = document.createElement("div");
    flow.className = "production-generation-flow";

    const plan = document.createElement("section");
    plan.className = "production-generation-step production-generation-plan";
    plan.setAttribute("aria-labelledby", "productionGenerationPlanTitle");
    plan.innerHTML = `
      <header class="production-generation-section-head">
        <div>
          <small>演出生成</small>
          <h4 id="productionGenerationPlanTitle">本次演出范围</h4>
          <p>沿用第二步确认的人物与背景。</p>
        </div>
      </header>`;
    plan.querySelector("header").append(scenePlan.querySelector("#returnToMapping"));
    plan.append(scenePlan);

    const decision = document.createElement("section");
    decision.className = "production-generation-step production-generation-decision";
    decision.setAttribute("aria-labelledby", "productionGenerationDecisionTitle");
    decision.innerHTML = `
      <header class="production-generation-section-head">
        <div>
          <small>草稿编排</small>
          <h4 id="productionGenerationDecisionTitle">演出设置</h4>
        </div>
      </header>`;
    const decisionHead = decision.querySelector(".production-generation-section-head");
    const modeBadge = lead.querySelector("#generationModeBadge");
    if (modeBadge) decisionHead?.querySelector("div")?.append(modeBadge);
    // Preserve the strategy controls and the shared execution explanation.
    decision.append(generationJob, actionPanel, layoutMode, directionProfile);
    const formatNote = document.createElement("p");
    formatNote.className = "production-format-note";
    formatNote.textContent = "当前仅转换格式，保留原文与已有 AA 指令，不调用 AI 安排演出。";
    decision.append(formatNote);

    const gateSurface = document.createElement("div");
    gateSurface.className = "production-generation-gates";
    gateSurface.innerHTML = '<div class="production-generation-gates-head"><strong>准备状态</strong><small>进入审查前检查</small></div>';
    gateSurface.append(gates);
    decision.append(gateSurface);

    flow.append(plan, decision);
    generation.append(flow);
    generation.classList.add("production-generation-workbench");
    generation.dataset.productionGenerationSplit = "true";
  }

  function installScenePlanTools(scenePlan) {
    if (!scenePlan) return;
    const organize = () => {
      scenePlan.querySelectorAll(".scene-plan-card > footer:not([data-tools-organized]), .mapping-scene-card > footer:not([data-tools-organized])").forEach(footer => {
        footer.dataset.toolsOrganized = "true";
        const review = footer.querySelector("[data-scene-plan-card], [data-mapping-scene-review]");
        const more = document.createElement("details");
        more.className = "production-scene-tools";
        more.innerHTML = '<summary>更多素材操作</summary><div class="production-scene-tools-content"></div>';
        const content = more.querySelector("div");
        footer.querySelectorAll("button").forEach(button => {
          if (!button.matches("[data-scene-plan-official], [data-mapping-scene-official]") && button !== review) content.append(button);
        });
        // Move, never clone: production's listeners and scene IDs stay intact.
        if (review) footer.insertBefore(review, footer.querySelector(":scope > .scene-plan-evidence"));
        footer.append(more);
      });
    };
    organize();
    new MutationObserver(organize).observe(scenePlan, { childList: true, subtree: true });
  }

  function installReviewCommandParity(sidebar, workspace, review, tools, toolList) {
    if (review.querySelector(".production-review-commandbar")) return;
    const reviewHead = review.querySelector(".review-head");
    if (!reviewHead) return;

    const commandbar = document.createElement("section");
    commandbar.className = "production-review-commandbar";
    commandbar.setAttribute("aria-label", "审查与安装常用操作");
    commandbar.innerHTML = `
      <button type="button" class="production-review-task" data-production-review-proxy="openRunOverview">
        <span><small>当前制作任务</small><strong data-production-review-title>正在读取任务</strong></span>
        <em>任务总览</em>
      </button>
      <div class="production-review-command-actions">
        <button type="button" data-production-review-proxy="refreshRun">刷新</button>
      </div>`;
    const actions = commandbar.querySelector(".production-review-command-actions");
    ["approveAll", "validateDraft", "openInstallDialog"].forEach(id => {
      const button = review.querySelector(`#${id}`);
      if (button) actions.append(button);
    });
    const compileProxy = document.createElement("button");
    compileProxy.type = "button";
    compileProxy.className = "primary production-review-compile";
    compileProxy.dataset.productionReviewProxy = "compileButton";
    compileProxy.textContent = "编译 AA 工程";
    const installButton = actions.querySelector("#openInstallDialog");
    if (installButton) actions.insertBefore(compileProxy, installButton);
    else actions.append(compileProxy);
    reviewHead.insertAdjacentElement("afterend", commandbar);

    // Only secondary review actions stay inside the overflow menu.
    if (!toolList.children.length) tools.hidden = true;

    const runTitle = sidebar.querySelector("#runTitle");
    const runList = workspace.querySelector("#runList");
    const overviewButton = workspace.querySelector("#openRunOverview");
    const compileButton = review.querySelector("#compileButton");
    const commandTitle = commandbar.querySelector("[data-production-review-title]");
    const taskButton = commandbar.querySelector(".production-review-task");
    const syncCommandbar = () => {
      // The loaded run, not the initial URL or a recent-list label, owns this title.
      commandTitle.textContent = runTitle?.textContent?.trim() || "尚未建立制作任务";
      taskButton.disabled = Boolean(overviewButton?.disabled);
      compileProxy.disabled = Boolean(compileButton?.disabled);
      compileProxy.textContent = compileButton?.textContent?.trim() || "编译 AA 工程";
    };
    const observer = new MutationObserver(syncCommandbar);
    if (runTitle) observer.observe(runTitle, { childList: true, subtree: true, characterData: true });
    if (runList) observer.observe(runList, { childList: true, subtree: true, characterData: true });
    if (overviewButton) observer.observe(overviewButton, { attributes: true, attributeFilter: ["disabled"] });
    if (compileButton) observer.observe(compileButton, { attributes: true, attributeFilter: ["disabled"], childList: true, subtree: true });
    commandbar.addEventListener("click", event => {
      const proxy = event.target.closest("[data-production-review-proxy]");
      if (!proxy || proxy.disabled) return;
      workspace.querySelector(`#${proxy.dataset.productionReviewProxy}`)?.click();
    });
    commandbar.__haloCueObserver = observer;
    syncCommandbar();
  }

  function restructureProductionSurface(sidebar, workspace) {
    restructureSourceSurface(workspace);
    restructureGenerationSurface(workspace);
    installScenePlanTools(workspace.querySelector("#mappingScenePlan"));
    sidebar.classList.add("production-flow-strip");
    sidebar.querySelector(".side-header")?.setAttribute("hidden", "");
    sidebar.querySelector(".side-status")?.setAttribute("hidden", "");
    const progress = sidebar.querySelector(".flow-progress, .stage-progress");
    if (progress) progress.setAttribute("hidden", "");
    workspace.querySelector(".topbar")?.insertAdjacentElement("afterend", sidebar);

    const review = workspace.querySelector("#page-review");
    const reviewLayout = review?.querySelector(".review-layout");
    const inspector = reviewLayout?.querySelector(".inspector");
    if (review && reviewLayout && inspector) {
      // The visible workflow explainer is intentionally removed from the
      // ordinary review surface, but the production client still updates its
      // status nodes while cards are selected. Keep the nodes hidden as a
      // compatibility surface instead of deleting them.
      const workflowHint = review.querySelector(".workflow-hint");
      if (workflowHint) workflowHint.hidden = true;
      review.querySelector("#openPerformancePreview")?.setAttribute("hidden", "");

      const tools = document.createElement("details");
      tools.className = "production-review-tools";
      tools.innerHTML = '<summary>更多工具</summary><div class="production-review-tool-list"></div>';
      const toolList = tools.querySelector("div");
      // Keep the original production trigger as a hidden compatibility hook.
      // The embedded workbench provides its own preview drawer, but the
      // production client still binds this element during startup.
      const legacyPreviewTrigger = review.querySelector("#openPerformancePreview");
      if (legacyPreviewTrigger) {
        legacyPreviewTrigger.hidden = true;
        // Keep the production client's startup hook in the review surface,
        // but never place it inside the user-facing tools menu.
        review.append(legacyPreviewTrigger);
      }
      [...review.querySelectorAll(".review-actions > button:not(#openPerformancePreview)")].forEach(button => {
        if (!["approveAll", "validateDraft", "openInstallDialog"].includes(button.id)) toolList.append(button);
      });
      installReviewCommandParity(sidebar, workspace, review, tools, toolList);
      review.querySelector(".review-actions")?.replaceChildren(tools);

      const hasNativeReviewParity = Boolean(
        review.querySelector("#backgroundTimeline")
        && review.querySelector(".persistent-preview-panel")
        && review.querySelector(".review-side-rail"),
      );
      review.classList.toggle("production-native-review-parity", hasNativeReviewParity);

      if (hasNativeReviewParity) {
        // 0.95 keeps the background timeline in the left review column while
        // the live preview remains visible on the right. Production owns the
        // native widgets; the writing shell only composes them for the embedded
        // workbench instead of projecting a second copy.
        const reviewColumn = reviewLayout.querySelector(".review-column");
        const filterbar = reviewColumn?.querySelector(".filterbar");
        const selectedToolbar = review.querySelector("#selectedCardToolbar");
        const backgroundTimeline = review.querySelector("#backgroundTimeline");
        if (reviewColumn && filterbar) {
          // Match 0.95: filters/jump, selected-card actions, timeline, then
          // the complete card sequence. Never put the list behind a scroll clip.
          if (selectedToolbar) filterbar.insertAdjacentElement("afterend", selectedToolbar);
          const commandGuide = review.querySelector("#reviewCommandGuide");
          if (commandGuide) (selectedToolbar || filterbar).insertAdjacentElement("afterend", commandGuide);
          if (backgroundTimeline) (commandGuide || selectedToolbar || filterbar).insertAdjacentElement("afterend", backgroundTimeline);
        }
      }

      // Current Production already owns the 0.95-style background timeline,
      // persistent preview and inspector rail. Older Production builds did not,
      // so retain the adapter fallback without duplicating the native UI.
      if (!hasNativeReviewParity) {
        const timeline = document.createElement("nav");
        timeline.className = "production-background-timeline";
        timeline.setAttribute("aria-label", "背景时间线");
        timeline.innerHTML = '<span>背景时间线</span><div data-production-background-nodes><small>正在读取草稿画面</small></div>';
        const timelineWrap = document.createElement("details");
        timelineWrap.className = "production-background-timeline-wrap";
        timelineWrap.innerHTML = '<summary><span>背景变化</span><small>按切换点查看</small></summary>';
        timelineWrap.open = window.matchMedia("(min-width: 801px)").matches;
        timelineWrap.append(timeline);
        reviewLayout.insertAdjacentElement("beforebegin", timelineWrap);

        const side = document.createElement("aside");
        side.className = "production-review-side";
        const preview = document.createElement("section");
        preview.className = "production-live-preview";
        preview.setAttribute("aria-label", "剧情预览");
        preview.innerHTML = `
          <header><div><small>随卡片同步</small><h3>剧情预览</h3></div><button type="button" class="production-preview-close" aria-label="关闭剧情预览">×</button></header>
          <div class="production-preview-stage" data-production-preview-stage><div class="production-preview-empty"><strong>选择一张卡片</strong><p>这里会显示当前画面和台词。</p></div></div>`;
        side.append(preview, inspector);
        reviewLayout.append(side);

        const previewToggle = document.createElement("button");
        previewToggle.type = "button";
        previewToggle.className = "production-preview-toggle";
        previewToggle.setAttribute("aria-expanded", "false");
        previewToggle.textContent = "查看剧情预览";
        review.querySelector(".review-head")?.append(previewToggle);
        const editToggle = document.createElement("button");
        editToggle.type = "button";
        editToggle.className = "production-edit-toggle";
        editToggle.dataset.productionEditCurrent = "true";
        editToggle.setAttribute("aria-expanded", "false");
        editToggle.textContent = "编辑当前卡";
        review.querySelector(".review-head")?.append(editToggle);
        const backdrop = document.createElement("button");
        backdrop.type = "button";
        backdrop.className = "production-preview-backdrop";
        backdrop.setAttribute("aria-label", "关闭剧情预览");
        review.append(backdrop);
      }
    }
  }

  function installSettingsWorkbench(root) {
    const dialog = root.querySelector("#settingsDialog");
    const tabs = dialog?.querySelector(".settings-tabs");
    const workspacePane = dialog?.querySelector("#settingsWorkspacePane");
    const spinePane = dialog?.querySelector("#spineForm");
    const environment = dialog?.querySelector("#aaEnvironmentStatus");
    if (!dialog || !tabs || !workspacePane || !environment || dialog.__haloCueWorkbench) return;
    dialog.classList.add("production-settings-workbench");
    dialog.querySelector("header small")?.replaceChildren(document.createTextNode("AA 制作"));
    const title = dialog.querySelector("header h3");
    if (title) title.textContent = "设置";

    const renderButton = document.createElement("button");
    renderButton.type = "button";
    renderButton.dataset.settingsPane = "render";
    renderButton.textContent = "渲染状态";
    tabs.append(renderButton);
    const renderPane = document.createElement("section");
    renderPane.id = "settingsRenderPane";
    renderPane.className = "settings-pane hidden";
    renderPane.innerHTML = '<div class="production-render-summary"><small>制作资源</small><strong>正在检查</strong><p>连接工作区后，这里会确认预览与官方资源是否可用。</p></div><details class="production-technical-details"><summary>技术详情</summary></details>';
    renderPane.querySelector("details")?.append(environment);
    dialog.querySelector(".production-settings-shell")?.append(renderPane);

    const syncRenderSummary = () => {
      const text = environment.textContent || "";
      const summary = renderPane.querySelector(".production-render-summary");
      if (!summary) return;
      const ready = /可用|已发现|已采用|就绪/.test(text) && !/缺失|不能|失败/.test(text);
      const blocked = /缺失|不能|失败/.test(text);
      summary.dataset.state = blocked ? "blocked" : ready ? "ready" : "checking";
      summary.querySelector("strong").textContent = blocked ? "需要检查" : ready ? "可以使用" : "正在检查";
      summary.querySelector("p").textContent = blocked ? "有一项制作资源需要处理。" : ready ? "预览和制作资源已经就绪。" : "正在确认预览与官方资源。";
    };
    new MutationObserver(syncRenderSummary).observe(environment, { childList: true, subtree: true, characterData: true });
    syncRenderSummary();

    tabs.addEventListener("click", event => {
      const button = event.target.closest("[data-settings-pane]");
      if (!button) return;
      const pane = button.dataset.settingsPane;
      tabs.querySelectorAll("[data-settings-pane]").forEach(item => item.classList.toggle("active", item === button));
      workspacePane.classList.toggle("hidden", pane !== "workspace");
      dialog.querySelector("#modelForm")?.classList.toggle("hidden", pane !== "model");
      spinePane?.classList.toggle("hidden", pane !== "spine");
      renderPane.classList.toggle("hidden", pane !== "render");
    }, true);
    dialog.__haloCueWorkbench = true;
  }

  function simplifyAssetWorkbench(root) {
    const dialog = root.querySelector("#assetLibraryDialog");
    if (!dialog) return;
    dialog.classList.add("production-asset-workbench");
    const title = dialog.querySelector("header h3");
    if (title) title.textContent = "素材工作台";
    const intro = dialog.querySelector("header p");
    if (intro) intro.hidden = true;
    const eyebrow = dialog.querySelector("header small");
    if (eyebrow) eyebrow.textContent = "AA 制作素材";
    dialog.querySelectorAll(".asset-library-item").forEach(item => {
      const details = item.querySelectorAll(":scope > div > small");
      if (details[0] && !details[0].classList.contains("asset-usage")) details[0].hidden = true;
      item.querySelectorAll(".asset-source").forEach(source => {
        const technicalSnapshotLabel = ["只读", "素材快照"].join("");
        if (/初始素材快照/.test(source.textContent || "") || source.textContent?.includes(technicalSnapshotLabel)) source.hidden = true;
      });
    });
    const status = dialog.querySelector("#assetLibraryStatus");
    if (status) {
      status.textContent = status.textContent
        .replace(/；可从卡片右侧确认来源和是否能移除。/g, "")
        .replace(/当前任务可用/g, "可用");
    }
  }

  function previewFrameMarkup(frame, runId, index, total) {
    if (!frame) return '<div class="production-preview-empty"><strong>没有可预览画面</strong><p>选择其他卡片，或先生成审查草稿。</p></div>';
    const background = frame.background_key && frame.background_preview_available === true
      ? `<img class="production-preview-background" src="${productionResourceUrl(runId, "backgrounds", frame.background_key, "/preview")}" alt="" loading="lazy" decoding="async">`
      : "";
    const label = frame.presentation === "cg" ? "CG 画面" : frame.presentation === "direction" ? "演出指令" : frame.presentation === "scene" ? "场景" : "当前台词";
    return `<div class="production-preview-frame">${background}<span class="production-preview-count">${index + 1} / ${total}</span><div class="production-preview-dialogue"><small>${escapeHtml(label)}</small><strong>${escapeHtml(frame.title || frame.speaker?.name || "未命名")}</strong><p>${escapeHtml(frame.text || "这张卡片没有正文。")}</p></div></div>`;
  }

  function installNativeReviewParity(root) {
    if (root.__haloCueNativeReviewParity) return;
    const review = root.querySelector("#page-review.production-native-review-parity");
    const cardList = review?.querySelector("#cardList");
    const filterbar = review?.querySelector(".filterbar");
    if (!review || !cardList || !filterbar) return;

    const navigation = document.createElement("span");
    navigation.className = "production-review-navigation";
    navigation.innerHTML = `
      <span class="production-review-card-total" data-production-card-total>0 张</span>
      <label>跳到 #<input type="number" min="1" step="1" inputmode="numeric" aria-label="卡片号" placeholder="卡片号"></label>
      <button type="button" data-production-card-jump>跳转</button>`;
    filterbar.append(navigation);
    const totalLabel = navigation.querySelector("[data-production-card-total]");
    const jumpInput = navigation.querySelector("input");
    const jumpButton = navigation.querySelector("[data-production-card-jump]");
    const reviewSummary = review.querySelector("#reviewSummary");
    const syncNavigation = () => {
      const summaryCount = reviewSummary?.textContent?.match(/(\d+)\s*张卡片/)?.[1];
      const count = Number(summaryCount || cardList.querySelectorAll("[data-card-id]").length || 0);
      totalLabel.textContent = `${count} 张`;
      jumpInput.max = String(Math.max(count, 1));
    };
    const jumpToCard = () => {
      const requested = Number.parseInt(jumpInput.value, 10);
      if (!Number.isFinite(requested) || requested < 1) {
        jumpInput.focus();
        return;
      }
      const select = () => {
        const cards = [...cardList.querySelectorAll("[data-card-id]")];
        const card = cards[Math.min(requested, cards.length) - 1];
        if (!card) return;
        card.click();
        window.setTimeout(() => {
          const refreshedCards = [...cardList.querySelectorAll("[data-card-id]")];
          const refreshedCard = refreshedCards[Math.min(requested, refreshedCards.length) - 1];
          refreshedCard?.scrollIntoView({ block: "center", behavior: "smooth" });
        }, 0);
      };
      const allFilter = filterbar.querySelector('[data-filter="all"]');
      if (allFilter && !allFilter.classList.contains("active")) {
        allFilter.click();
        window.setTimeout(select, 0);
      } else {
        select();
      }
    };
    jumpButton.addEventListener("click", jumpToCard);
    jumpInput.addEventListener("keydown", event => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      jumpToCard();
    });

    let syncing = false;
    const syncSelection = () => {
      if (syncing || !review.classList.contains("active")) return;
      syncing = true;
      queueMicrotask(() => {
        const cards = [...cardList.querySelectorAll("[data-card-id]")];
        if (cards.length && !cards.some(card => card.classList.contains("selected"))) {
          (cards.find(card => card.classList.contains("blocking") || card.classList.contains("pending")) || cards[0]).click();
        }
        syncNavigation();
        syncing = false;
      });
    };

    const observer = new MutationObserver(syncSelection);
    observer.observe(cardList, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
    observer.observe(review, { attributes: true, attributeFilter: ["class"] });
    if (reviewSummary) observer.observe(reviewSummary, { childList: true, subtree: true, characterData: true });
    root.__haloCueNativeReviewParity = observer;
    syncSelection();
  }

  function installReviewWorkbench(root) {
    if (root.__haloCueReviewWorkbench) return;
    const review = root.querySelector("#page-review");
    const cardList = root.querySelector("#cardList");
    const stage = root.querySelector("[data-production-preview-stage]");
    const timeline = root.querySelector("[data-production-background-nodes]");
    const side = root.querySelector(".production-review-side");
    const toggle = root.querySelector(".production-preview-toggle");
    const editToggle = root.querySelector("[data-production-edit-current]");
    const close = root.querySelector(".production-preview-close");
    const backdrop = root.querySelector(".production-preview-backdrop");
    if (!review || !cardList || !stage || !timeline) return;

    let drawerAccessibilityState = [];
    let drawerOpener = toggle;
    const setDrawer = (open, mode = "preview") => {
      review.classList.toggle("preview-open", open);
      review.classList.toggle("edit-open", open && mode === "edit");
      toggle?.setAttribute("aria-expanded", String(open));
      editToggle?.setAttribute("aria-expanded", String(open && mode === "edit"));
      const toast = root.querySelector(".toast.visible");
      const shell = root.querySelector(".embedded-production-shell");
      if (open) {
        // A previous task toast can otherwise sit on top of the preview drawer.
        toast?.classList.remove("visible");
        shell?.classList.remove("toast-visible");
        drawerAccessibilityState = [
          review.querySelector(".review-head"),
          review.querySelector(".production-background-timeline"),
          review.querySelector(".review-column"),
          review.querySelector(".buildbar"),
        ].filter(Boolean).map(element => ({
          element,
          ariaHidden: element.getAttribute("aria-hidden"),
          inert: element.inert,
        }));
        drawerAccessibilityState.forEach(({ element }) => {
          element.inert = true;
          element.setAttribute("aria-hidden", "true");
        });
        if (mode === "edit") {
          window.setTimeout(() => side?.querySelector(".inspector input, .inspector textarea, .inspector select, .inspector button:not([disabled])")?.focus({ preventScroll: true }), 60);
        } else {
          close?.focus({ preventScroll: true });
        }
      } else {
        drawerAccessibilityState.forEach(({ element, ariaHidden, inert }) => {
          element.inert = inert;
          if (ariaHidden === null) element.removeAttribute("aria-hidden");
          else element.setAttribute("aria-hidden", ariaHidden);
        });
        drawerAccessibilityState = [];
        review.classList.remove("edit-open");
        editToggle?.setAttribute("aria-expanded", "false");
        drawerOpener?.focus({ preventScroll: true });
        drawerOpener = toggle;
      }
    };
    toggle?.addEventListener("click", () => { drawerOpener = toggle; setDrawer(true); });
    editToggle?.addEventListener("click", () => {
      if (!cardList.querySelector("[data-card-id].selected")) {
        cardList.querySelector("[data-card-id]")?.click();
      }
      drawerOpener = editToggle;
      setDrawer(true, "edit");
    });
    close?.addEventListener("click", () => setDrawer(false));
    backdrop?.addEventListener("click", () => setDrawer(false));

    const selectedCardId = () => cardList.querySelector("[data-card-id].selected")?.dataset.cardId || "";
    const clickCard = cardId => cardList.querySelector(`[data-card-id="${CSS.escape(cardId)}"]`)?.click();
    const syncPrimaryAction = () => {
      const selected = cardList.querySelector("[data-card-id].selected");
      const compile = root.querySelector("#compileButton");
      review.classList.toggle("production-review-ready", Boolean(compile && !compile.disabled && selected?.classList.contains("approved")));
    };
    const renderPreview = async () => {
      const runId = currentProductionRunId(root);
      if (!runId) return;
      const version = root.querySelector("#reviewSummary")?.textContent || "";
      const cacheKey = `${runId}|${version}`;
      const cache = root.__haloCuePreviewCache || (root.__haloCuePreviewCache = new Map());
      const requestId = String((Number(root.__haloCuePreviewRequestId) || 0) + 1);
      root.__haloCuePreviewRequestId = requestId;
      stage.setAttribute("aria-busy", "true");
      try {
        let preview = cache.get(cacheKey);
        if (!preview) {
          const response = await fetch(`/production/api/v1/production-runs/${encodeURIComponent(runId)}/performance-preview`);
          if (!response.ok) throw new Error(`预览读取失败（${response.status}）`);
          preview = await response.json();
          cache.set(cacheKey, preview);
        }
        if (root.__haloCuePreviewRequestId !== requestId) return;
        const frames = Array.isArray(preview.frames) ? preview.frames : [];
        const selected = selectedCardId();
        const index = Math.max(0, frames.findIndex(frame => frame.card_id === selected));
        stage.innerHTML = previewFrameMarkup(frames[index], runId, index, frames.length);
        const changes = frames.filter((frame, frameIndex) => frameIndex === 0 || frame.background_key !== frames[frameIndex - 1]?.background_key);
        timeline.innerHTML = changes.length ? changes.map(frame => `<button type="button" data-production-timeline-card="${escapeHtml(frame.card_id || "")}" class="${frame.card_id === selected ? "active" : ""}"><span>${escapeHtml(frame.background_key === "BG_Black" ? "黑屏" : frame.title || "背景")}</span><small>第 ${escapeHtml(frame.line_no || "-")} 张</small></button>`).join("") : "<small>草稿没有背景切换</small>";
        timeline.querySelectorAll("[data-production-timeline-card]").forEach(button => button.addEventListener("click", () => clickCard(button.dataset.productionTimelineCard)));
      } catch (error) {
        if (root.__haloCuePreviewRequestId !== requestId) return;
        stage.innerHTML = `<div class="production-preview-empty"><strong>暂时无法显示预览</strong><p>${escapeHtml(error.message || "请稍后重试。")}</p><button type="button" data-production-preview-retry>重试</button></div>`;
        stage.querySelector("[data-production-preview-retry]")?.addEventListener("click", renderPreview);
      } finally {
        if (root.__haloCuePreviewRequestId === requestId) stage.removeAttribute("aria-busy");
      }
    };

    let syncing = false;
    const syncReview = () => {
      if (syncing || !review.classList.contains("active")) return;
      syncing = true;
      queueMicrotask(() => {
        const cards = [...cardList.querySelectorAll("[data-card-id]")];
        if (cards.length && !cards.some(card => card.classList.contains("selected"))) {
          (cards.find(card => card.classList.contains("blocking") || card.classList.contains("pending")) || cards[0]).click();
        } else if (cards.length) {
          renderPreview();
          syncPrimaryAction();
        }
        syncing = false;
      });
    };
    const reviewObserver = new MutationObserver(syncReview);
    reviewObserver.observe(cardList, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
    reviewObserver.observe(review, { attributes: true, attributeFilter: ["class"] });
    const compileButton = root.querySelector("#compileButton");
    if (compileButton) reviewObserver.observe(compileButton, { attributes: true, attributeFilter: ["disabled"] });
    root.addEventListener("keydown", event => {
      if (event.key === "Escape" && review.classList.contains("preview-open")) setDrawer(false);
    });
    root.__haloCueReviewWorkbench = true;
    syncReview();
  }

  function installProductionWorkbench(root) {
    if (root.__haloCueProductionWorkbench) return;
    installSettingsWorkbench(root);
    installNativeReviewParity(root);
    installReviewWorkbench(root);
    root.addEventListener("click", event => {
      if (event.target.closest?.("#openAssetLibrary, #assetLibraryDialog [data-asset-kind], #assetLibraryMore")) {
        window.setTimeout(() => simplifyAssetWorkbench(root), 0);
      }
    }, true);
    root.__haloCueProductionWorkbench = true;
    simplifyAssetWorkbench(root);
  }

  function ensureProductionRecoveryStyle(root) {
    if(root.querySelector('[data-production-recovery-style]'))return;
    // This surface must be usable even when the production HTML/styles never arrive.
    const style=document.createElement('style');style.dataset.productionRecoveryStyle='true';
    style.textContent=`
      .production-surface-state{box-sizing:border-box;padding:40px 24px;color:var(--hc-text,#263241);font-family:var(--author-ui-font,sans-serif);}
      .production-surface-state[hidden]{display:none!important}
      .production-surface-state-card{max-width:640px;margin:24px auto;padding:24px;border:1px solid var(--hc-line,#dce1e7);border-radius:14px;background:var(--hc-panel,#fff);display:flex;gap:16px;align-items:flex-start;}
      .production-surface-state-mark{flex:none;display:grid;place-items:center;width:32px;height:32px;border-radius:9px;background:var(--hc-hover,#f3f5f8);color:var(--hc-muted,#637080);}
      .production-surface-state-card>div{min-width:0;flex:1}.production-surface-state-card strong{font-size:17px;line-height:1.6}
      .production-surface-state-card p{font-size:13px;line-height:1.8;color:var(--hc-muted,#637080);overflow-wrap:anywhere}
      .production-recovery-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}.production-recovery-actions button{min-height:38px;padding:8px 12px;border:1px solid var(--hc-line,#dce1e7);border-radius:7px;background:transparent;color:inherit;font:inherit;font-size:12px;cursor:pointer}
      .production-recovery-actions button:focus-visible{outline:2px solid var(--hc-accent,#537fbc);outline-offset:2px}
      .production-surface-state-card details{margin-top:12px;font-size:12px;color:var(--hc-muted,#637080)}
      @media(max-width:760px){.production-surface-state{padding:20px 14px}.production-surface-state-card{margin:0;padding:18px;gap:10px}.production-recovery-actions button{min-height:44px}}
    `;
    root.append(style);
  }

  function setProductionSurfaceState(root, stateName, options = {}) {
    ensureProductionRecoveryStyle(root);
    const panelState = String(stateName || "loading");
    let panel = root.querySelector(".production-surface-state");
    if (!panel) {
      panel = document.createElement("section");
      panel.className = "production-surface-state production-embed-empty";
      panel.setAttribute("aria-live", "polite");
      root.append(panel);
    }
    const shell = root.querySelector(".embedded-production-shell");
    const ready = panelState === "ready";
    panel.hidden = ready;
    panel.dataset.state = panelState;
    if (shell) {
      shell.hidden = !ready;
      shell.inert = !ready;
      if (ready) shell.removeAttribute("aria-hidden");
      else shell.setAttribute("aria-hidden", "true");
    }
    if (ready) {
      panel.replaceChildren();
      host()?.setAttribute("aria-busy", "false");
      return panel;
    }
    const title = options.title || (panelState === "loading" ? "正在打开 AA 制作" : "AA 制作工作面没有打开");
    const detail = options.detail || (panelState === "loading" ? "正在连接制作服务，请稍候。" : "请重新读取制作工作面。");
    const retry = typeof options.onRetry === "function"
      ? `<button type="button" class="production-embed-retry">${escapeHtml(options.actionLabel || "重试")}</button>`
      : "";
    panel.setAttribute("role", panelState === "loading" ? "status" : "alert");
    const failed=panelState==='error';
    const recovery=failed?'<button type="button" data-production-return-writing>返回写作</button><button type="button" data-production-open-settings>检查制作环境</button>':'';
    panel.innerHTML = `<div class="production-surface-state-card"><span class="production-surface-state-mark" aria-hidden="true">${panelState === "loading" ? "…" : "!"}</span><div><strong>${escapeHtml(title)}</strong><p>${failed?'暂时无法连接制作工作面。作品和正文仍保留，你可以继续写作，或检查本机制作服务后重试。':escapeHtml(detail)}</p>${failed?`<details><summary>查看连接详情</summary><p>${escapeHtml(detail)}</p></details>`:''}<div class="production-recovery-actions">${retry}${recovery}</div></div></div>`;
    panel.querySelector('[data-production-return-writing]')?.addEventListener('click',()=>window.HaloCueRouter?.navigate({section:'writing',stage:'draft',pane:'writing'}));
    panel.querySelector('[data-production-open-settings]')?.addEventListener('click',()=>{
      document.querySelector('#openSettingsButton')?.click();
      document.querySelector('#settingsTab-aa')?.click();
    });
    const retryButton = panel.querySelector(".production-embed-retry");
    retryButton?.addEventListener("click", () => options.onRetry(), { once: true });
    host()?.setAttribute("aria-busy", panelState === "loading" ? "true" : "false");
    return panel;
  }

  async function loadProductionSurface() {
    const element = ensureHost();
    const root = element.shadowRoot || element.attachShadow({ mode: "open" });
    root.replaceChildren();
    setProductionSurfaceState(root, "loading", {
      title: "正在打开 AA 制作",
      detail: "正在连接制作服务，请稍候。",
    });

    const response = await fetch("/production/", { headers: { Accept: "text/html" } });
    if (!response.ok) throw new Error(`AA 制作前端不可用（${response.status}）`);
    const markup = (await response.text()).replace(/\sstyle="display:none;"/gi, "");
    const parsed = new DOMParser().parseFromString(markup, "text/html");
    const sidebar = parsed.querySelector(".stage-sidebar");
    const workspace = parsed.querySelector(".workspace");
    if (!sidebar || !workspace) throw new Error("AA 制作前端缺少工作面结构");

    const styleUrls = [
      "/production/app.css",
      "/production/layout-mode.css",
      "/production/previews.css",
      "/production/review-parity.css",
      "/production/preflight.css",
      "/production/cg-responsive.css",
      "/production/workspace-migration.css",
      "/production/direction-profile.css",
      "/production/confirm-dialog.css",
      "/production-embed.css?v=20261006-aa-install-review1",
      "/production-theme.css?v=20261006-aa-install-review1",
      "/production/clarity.css?v=20260927-compact4",
    ];
    const styleLoads = styleUrls.map(stylesheet);
    const links = styleLoads.map(load => load.link);
    const shell = document.createElement("div");
    shell.className = "app-shell embedded-production-shell";
    shell.addEventListener("halocue:production-context", event => {
      if (!app()?.classList.contains("production-mode")) return;
      activeContext = event.detail;
      updateUrl(activeContext, true);
      window.HaloCueRouter?.setProductionContext(activeContext);
      syncChrome();
    });
    const importedSidebar = document.importNode(stripInlineStyles(sidebar), true);
    const importedWorkspace = document.importNode(stripInlineStyles(workspace), true);
    const topActions = importedWorkspace.querySelector(".top-actions");

    [
      ["#openAssetLibrary", "制作素材"],
      ["#openTasks", "后台任务"],
      ["#openSettings", "设置"],
    ].forEach(([selector, label]) => {
      const source = parsed.querySelector(selector);
      if (!source || !topActions) return;
      const action = document.importNode(source, true);
      action.className = "embed-tool-button";
      action.textContent = label;
      // app.js binds this legacy control during startup. Keep its inert DOM
      // hook for compatibility, while settings are owned by the main shell.
      action.hidden = selector === "#openSettings";
      topActions.prepend(action);
    });

    restructureProductionSurface(importedSidebar, importedWorkspace);
    shell.append(importedWorkspace);
    const auxiliary = [...parsed.body.querySelectorAll("dialog, #toast")].map(node => document.importNode(node, true));
    root.replaceChildren(...links, shell, ...auxiliary);
    setProductionSurfaceState(root, "loading", {
      title: "正在准备 AA 制作",
      detail: "工作面即将就绪，正在读取制作能力。",
    });
    await Promise.all(styleLoads);

    await new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "/production/app-embedded.js?v=20260927-compact4";
      script.onload = resolve;
      script.onerror = () => reject(new Error("无法启动 AA 制作工作面"));
      document.head.append(script);
    });
    installProductionWorkbench(root);
    setProductionSurfaceState(root, "ready");
    return root;
  }

  function ensureProductionSurface() {
    if (loadPromise) return loadPromise;
    loadState = "loading";
    loadStartedAt = performance.now();
    loadFinishedAt = 0;
    loadPromise = loadProductionSurface().then(root => {
      loadState = "ready";
      loadFinishedAt = performance.now();
      return root;
    }).catch(error => {
      loadState = "failed";
      loadFinishedAt = performance.now();
      loadPromise = null;
      throw error;
    });
    return loadPromise;
  }

  async function preload() {
    const element = ensureHost();
    // Warmup is best-effort. Once the user has entered AA, or a warmup has
    // already failed, it must not start a second hidden request and replace
    // the visible loading/error boundary owned by open().
    if (app()?.classList.contains("production-mode") || loadState === "failed") {
      return element.shadowRoot;
    }
    if (!app()?.classList.contains("production-mode")) element.hidden = true;
    try {
      return await ensureProductionSurface();
    } finally {
      if (!app()?.classList.contains("production-mode")) element.hidden = true;
    }
  }

  function status() {
    const finishedAt = loadFinishedAt || (loadStartedAt ? performance.now() : 0);
    return {
      state: loadState,
      latencyMs: loadStartedAt ? Math.max(0, Math.round(finishedAt - loadStartedAt)) : 0,
    };
  }

  async function selectRun(root, runId) {
    const shell = root.querySelector(".embedded-production-shell");
    await shell.haloCueReady;
    if (!runId) return true;
    // Open by stable ID, including runs older than the eight recent rows.
    try { return await shell.haloCueOpenRun(runId); }
    catch (error) { if (error.status === 404 || error.code === "run_not_found") return false; throw error; }
  }

  async function open(options = {}) {
    const ticket = ++openEpoch;
    const context = linkedContext(options.trigger);
    for (const key of ["runId", "workId", "releaseId"]) {
      if (Object.prototype.hasOwnProperty.call(options, key)) context[key] = options[key] || "";
    }
    activeContext = { ...context, title: context.runId ? "正在打开制作任务…" : "选择制作任务" };
    const element = ensureHost();
    element.hidden = false;
    element.focus({ preventScroll: true });
    app()?.classList.add("production-mode");
    setOuterChrome(context);
    updateUrl(context, Boolean(options.replaceHistory));
    try {
      const root = await ensureProductionSurface();
      if (ticket !== openEpoch || !app()?.classList.contains("production-mode")) return;
      await root.querySelector(".embedded-production-shell").haloCueReady;
      if (ticket !== openEpoch || !app()?.classList.contains("production-mode")) return;
      installCurrentTaskSourceBoundary(root);
      installFocusRecovery(root, element);
      installProductionLabelSanitizer(root);
      installBackgroundClassification(root);
      installOuterActions(root);
      setProductionSurfaceState(root, "loading", { title: "正在读取制作任务", detail: "正在同步草稿、素材和审查状态。" });
      const selected = await selectRun(root, context.runId);
      if (ticket !== openEpoch || !app()?.classList.contains("production-mode")) return;
      if (context.runId && !selected) {
        setProductionSurfaceState(root, "missing-run", {
          title: "没有找到这项制作任务",
          detail: "任务列表可能还在同步，或这条链接已经失效。",
          actionLabel: "重新读取任务",
          onRetry: () => open({ ...context, replaceHistory: true }),
        });
      } else {
        setProductionSurfaceState(root, "ready");
        root.__haloCueCurrentTaskBoundary?.render();
      }
      // Loading the embedded production surface and selecting a run can move focus
      // back to document.body; restore the outer work-surface focus after async work.
      element.focus({ preventScroll: true });
    } catch (error) {
      if (ticket !== openEpoch || !app()?.classList.contains("production-mode")) return;
      loadPromise = null;
      element.setAttribute("aria-busy", "false");
      const root = element.shadowRoot || element.attachShadow({ mode: "open" });
      setProductionSurfaceState(root, "error", {
        title: "AA 制作工作面没有打开",
        detail: String(error.message || error),
        actionLabel: "重试",
        onRetry: () => open({ ...context, replaceHistory: true }),
      });
    }
  }

  function close(options = {}) {
    openEpoch++;
    app()?.classList.remove("production-mode");
    const element = host();
    if (element) element.hidden = true;
    restoreOuterChrome();
    if (options.section) {
      const url = new URL(location.href);
      url.pathname = "/";
      url.search = "";
      url.searchParams.set("section", options.section);
      const context = linkedContext();
      if (context.workId) url.searchParams.set("work_id", context.workId);
      if (options.section === "writing" && context.releaseId) {
        url.searchParams.set("stage", "release");
        url.searchParams.set("release_id", context.releaseId);
      }
      history.pushState({ section: options.section }, "", url);
    }
  }

  document.addEventListener("click", event => {
    if (!app()?.classList.contains("production-mode")) return;
    const section = event.target.closest("[data-section]")?.dataset.section;
    const mobile = event.target.closest("[data-mobile]")?.dataset.mobile;
    if ((section && section !== "production") || mobile) close();
  }, true);

  window.addEventListener("popstate", () => {
    if (window.HaloCueRouter) return;
    const params = new URLSearchParams(location.search);
    if (params.get("section") === "production") {
      open({ ...linkedContext(), replaceHistory: true });
    } else {
      close();
    }
  });

  window.HaloCueProductionEmbed = { open, close, preload, status, syncChrome, isOpen: () => app()?.classList.contains("production-mode") };
})();
