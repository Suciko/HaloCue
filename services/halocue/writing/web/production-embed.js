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

  const sleep = (delay) => new Promise(resolve => setTimeout(resolve, delay));
  const app = () => document.querySelector("#app");
  const host = () => document.querySelector(`#${hostId}`);

  function linkedContext(trigger = null) {
    const linked = trigger?.matches?.("[data-open-production]")
      ? trigger
      : document.querySelector("[data-open-production]");
    const params = new URLSearchParams(location.search);
    return {
      runId: linked?.dataset.openProduction || params.get("run_id") || "",
      workId: linked?.dataset.workId || params.get("work_id") || "",
      releaseId: linked?.dataset.releaseId || params.get("release_id") || "",
    };
  }

  function updateUrl(context, replace = false) {
    const url = new URL(location.href);
    url.pathname = "/";
    url.search = "";
    url.searchParams.set("section", "production");
    if (context.runId) url.searchParams.set("run_id", context.runId);
    if (context.workId) url.searchParams.set("work_id", context.workId);
    if (context.releaseId) url.searchParams.set("release_id", context.releaseId);
    history[replace ? "replaceState" : "pushState"]({ section: "production", ...context }, "", url);
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
    if (crumb) crumb.textContent = "AA 制作";
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
    topActions.querySelector(".production-top-actions")?.remove();
    const controls = document.createElement("span");
    controls.className = "production-top-actions";
    controls.innerHTML = `
      <button type="button" class="quiet production-assets" data-production-proxy="openAssetLibrary">制作素材</button>
      <button type="button" class="quiet production-overview" data-production-proxy="openRunOverview">任务总览</button>
      <details class="production-more-actions">
        <summary>更多</summary>
        <div role="menu">
          <button type="button" data-production-proxy="openTasks" role="menuitem">后台任务</button>
          <button type="button" data-production-proxy="openSettings" role="menuitem">设置</button>
          <button type="button" data-production-proxy="refreshRun" role="menuitem" aria-label="刷新制作任务">刷新制作任务</button>
        </div>
      </details>`;
    controls.addEventListener("click", event => {
      const button = event.target.closest("[data-production-proxy]");
      if (!button) return;
      root.querySelector(`#${button.dataset.productionProxy}`)?.click();
      button.closest("details")?.removeAttribute("open");
    });
    topActions.prepend(controls);
    const syncAvailability = () => {
      const assetButton = controls.querySelector(".production-assets");
      const hasRun = !root.querySelector("#openRunOverview")?.disabled;
      if (!assetButton) return;
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
      const description = sideHeader.querySelector("p");
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

  const backgroundGroupLabels = {
    scene: { label: "场景背景", source: "普通场景背景" },
    cg: { label: "官方 CG", source: "官方剧情画面" },
    custom: { label: "自定义背景", source: "你的自定义画面" },
  };

  function backgroundKeyClass(key) {
    const value = String(key || "").trim().toLowerCase();
    if (/^bg_cs[_-]/i.test(value)) return "cg";
    if (/^(chatgpt image|comfyui[_ -]|gemini_generated_image_|img[_-])/i.test(value)) return "custom";
    if (/^\d{3,}(?:-\d+)?$/.test(value)) return "custom";
    if (value.length >= 20 && /^[0-9a-f]+$/.test(value)) return "custom";
    return "scene";
  }

  function currentProductionRunId(root) {
    return linkedContext().runId
      || root.querySelector("[data-run-id].active")?.dataset.runId
      || root.querySelector("[data-run-id]")?.dataset.runId
      || "";
  }

  function productionResourceUrl(runId, kind, key, suffix = "") {
    return `/production/api/v1/production-runs/${encodeURIComponent(runId)}/resources/${kind}/${encodeURIComponent(key)}${suffix}`;
  }

  async function fetchProductionResources(root, kind, query, offset = 0, limit = 24, options = {}) {
    const runId = currentProductionRunId(root);
    if (!runId) return { items: [], total: 0, has_more: false };
    const cache = root.__haloCueResourceCache || (root.__haloCueResourceCache = new Map());
    const pending = root.__haloCueResourcePending || (root.__haloCueResourcePending = new Map());
    const cacheKey = `${runId}|${kind}|${query}|${offset}|${limit}`;
    if (cache.has(cacheKey)) return cache.get(cacheKey);
    if (pending.has(cacheKey)) return pending.get(cacheKey);
    const request = fetch(`/production/api/v1/production-runs/${encodeURIComponent(runId)}/resources/${kind}?q=${encodeURIComponent(query)}&offset=${offset}&limit=${limit}`, { signal: options.signal })
      .then(response => {
        if (!response.ok) throw new Error(`素材读取失败（${response.status}）`);
        return response.json();
      })
      .then(payload => {
        cache.set(cacheKey, payload);
        return payload;
      })
      .finally(() => pending.delete(cacheKey));
    pending.set(cacheKey, request);
    return request;
  }

  async function fetchWritingBackgroundMetadata(root, keys = [], query = "") {
    const params = new URLSearchParams({ kind: "backgrounds" });
    if (keys.length) params.set("keys", keys.join(","));
    if (query) params.set("q", query);
    const response = await fetch(`/api/v1/resources/search?${params.toString()}`);
    if (!response.ok) throw new Error(`背景标注读取失败（${response.status}）`);
    const payload = await response.json();
    const data = payload?.data || payload;
    return Array.isArray(data?.items) ? data.items : [];
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
        return label === "其他地点" ? "" : `<button type="button" data-background-category="${escapeHtml(label)}" aria-pressed="false">${escapeHtml(label)}<small>${escapeHtml(category.count)}</small></button>`;
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
    const search = dialog.querySelector(".asset-search-label");
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
    const search = dialog.querySelector(".asset-search-label");
    if (search) {
      const label = search.childNodes[0];
      if (label && label.textContent !== selected.search) label.textContent = selected.search;
      const input = search.querySelector("input");
      if (input && input.placeholder !== selected.placeholder) input.placeholder = selected.placeholder;
    }
  }

  function backgroundMetadataMap(items = []) {
    return new Map(items.map(item => {
      const key = String(item.requested_key || item.technical?.key || item.key || "");
      return [key.toLowerCase(), item];
    }));
  }

  function backgroundUserLabel(item, metadata, group) {
    const configured = backgroundGroupLabels[group] || backgroundGroupLabels.scene;
    const values = [metadata?.display_name, metadata?.place, metadata?.category_path, metadata?.main_category, metadata?.label];
    const readable = values.find(value => /[\u3400-\u9fff]/.test(String(value || "")));
    if (readable) return String(readable);
    return configured.source;
  }

  function backgroundCategoryInfo(metadata, group) {
    const configured = backgroundGroupLabels[group] || backgroundGroupLabels.scene;
    const path = String(metadata?.category_path || "")
      .split("/")
      .map(value => value.trim())
      .filter(Boolean);
    const subcategory = metadata?.annotation?.subcategory || metadata?.annotation?.category || path.at(-1) || "";
    const main = metadata?.main_category || path.at(-2) || "";
    const visible = backgroundCategoryLabel(subcategory || main) === "其他地点"
      ? (backgroundCategoryLabel(main) === "其他地点" ? configured.source : backgroundCategoryLabel(main))
      : backgroundCategoryLabel(subcategory);
    const filterValues = [...new Set([main, subcategory, ...path].map(backgroundCategoryLabel).filter(value => value !== "其他地点"))];
    return { visible, filterValues };
  }

  function embeddedBackgroundItem(item, group, root, metadata, index = 0) {
    const runId = currentProductionRunId(root);
    const key = item.key || "";
    const configured = backgroundGroupLabels[group] || backgroundGroupLabels.scene;
    const name = backgroundUserLabel(item, metadata, group);
    const categoryInfo = backgroundCategoryInfo(metadata, group);
    const preview = runId && key && item.preview_available === true
      ? `<span class="resource-thumb background-thumb"><span class="background-preview-placeholder" aria-hidden="true">预览</span><img ${index < 6 ? `src="${productionResourceUrl(runId, "backgrounds", key, "/preview")}"` : `data-preview-src="${productionResourceUrl(runId, "backgrounds", key, "/preview")}"`} loading="lazy" decoding="async" alt=""></span>`
      : `<span class="resource-thumb background-thumb preview-unavailable" aria-hidden="true">无预览</span>`;
    return `<article class="asset-library-item embedded-background-item" data-embedded-background-key="${escapeHtml(key)}" data-background-category="${escapeHtml(categoryInfo.filterValues.join("|"))}"><div class="embedded-background-preview">${preview}</div><div><strong>${escapeHtml(name)}</strong><small>${escapeHtml(categoryInfo.visible)}</small></div></article>`;
  }

  function installBackgroundPreviewObserver(root) {
    const results = root.querySelector("#assetLibraryResults");
    if (!results) return;
    root.__haloCueBackgroundPreviewObserver?.disconnect();
    const load = image => {
      const source = image.dataset.previewSrc;
      if (!source || image.src) return;
      image.src = source;
      image.removeAttribute("data-preview-src");
    };
    const allImages = [...results.querySelectorAll("img")];
    allImages.forEach(image => {
      image.addEventListener("load", () => image.classList.add("is-loaded"), { once: true });
      image.addEventListener("error", () => image.classList.add("is-failed"), { once: true });
      if (image.complete && image.naturalWidth > 0) image.classList.add("is-loaded");
    });
    const images = allImages.filter(image => image.dataset.previewSrc);
    if (!images.length) return;
    if (typeof IntersectionObserver === "undefined") {
      images.slice(0, 10).forEach(load);
      return;
    }
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) {
        load(entry.target);
        observer.unobserve(entry.target);
      }
    }), { root: results, rootMargin: "180px 0px" });
    images.forEach(image => observer.observe(image));
    root.__haloCueBackgroundPreviewObserver = observer;
  }

  async function loadEmbeddedBackgroundLibrary(root, { reset = true } = {}) {
    const dialog = root.querySelector("#assetLibraryDialog");
    const controls = backgroundGroupControls(root);
    if (!dialog || !controls || dialog.hidden) return;
    const group = controls.dataset.backgroundGroup || "scene";
    const search = dialog.querySelector("#assetLibrarySearch")?.value?.trim() || "";
    const offset = reset ? 0 : Number(controls.dataset.backgroundOffset || 0);
    const status = dialog.querySelector("#assetLibraryStatus");
    const results = dialog.querySelector("#assetLibraryResults");
    const more = dialog.querySelector("#assetLibraryMore");
    if (!results || !status) return;
    status.textContent = "正在按用途整理背景…";
    controls.dataset.backgroundLoading = "true";
    root.__haloCueBackgroundRequest?.abort();
    const request = new AbortController();
    const requestId = String((Number(root.__haloCueBackgroundRequestId) || 0) + 1);
    root.__haloCueBackgroundRequest = request;
    root.__haloCueBackgroundRequestId = requestId;
    try {
      const endpoint = group === "scene" ? "backgrounds" : "cg-backgrounds";
      const payload = await fetchProductionResources(root, endpoint, search, offset, 24, { signal: request.signal });
      if (root.__haloCueBackgroundRequestId !== requestId) return;
      let items = Array.isArray(payload.items) ? payload.items : [];
      items = items.filter(item => group === "scene"
        ? backgroundKeyClass(item.key) === "scene"
        : group === "cg"
          ? item.cg_source === "official_cg"
          : item.cg_source === "custom_background");
      const metadata = group === "scene"
        ? backgroundMetadataMap(await fetchWritingBackgroundMetadata(root, items.map(item => item.key), search).catch(() => []))
        : new Map();
      if (root.__haloCueBackgroundRequestId !== requestId) return;
      const html = items.map((item, index) => embeddedBackgroundItem(item, group, root, metadata.get(String(item.key || "").toLowerCase()), index)).join("");
      results.innerHTML = reset || offset === 0 ? html : results.innerHTML + html;
      controls.dataset.backgroundOffset = String(offset + (payload.items || []).length);
      controls.dataset.backgroundRenderedGroup = group;
      more.disabled = !payload.has_more;
      status.textContent = items.length
        ? `已显示 ${results.querySelectorAll(".embedded-background-item").length} 项`
        : `没有匹配的${backgroundGroupLabels[group].label}。`;
      applyBackgroundCategory(root);
      installBackgroundPreviewObserver(root);
    } catch (error) {
      if (error?.name === "AbortError") return;
      status.textContent = error.message || "背景素材暂时无法读取。";
      results.replaceChildren();
      more.disabled = true;
    } finally {
      if (root.__haloCueBackgroundRequestId === requestId) controls.dataset.backgroundLoading = "false";
    }
  }

  function applyBackgroundCategory(root) {
    const controls = backgroundGroupControls(root);
    if (!controls) return;
    const category = controls.dataset.backgroundCategory || "";
    controls.querySelectorAll(".embedded-background-category-list [data-background-category]").forEach(button => {
      const active = button.dataset.backgroundCategory === category;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    root.querySelectorAll("#assetLibraryResults .embedded-background-item").forEach(item => {
      item.hidden = Boolean(category && !(item.dataset.backgroundCategory || "").includes(category));
    });
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
      if (dialog?.open && kind === "backgrounds" && !controls.dataset.backgroundLoaded) {
        controls.dataset.backgroundLoaded = "true";
        setBackgroundGroup(root, "scene");
        loadEmbeddedBackgroundLibrary(root);
      }
      if (dialog?.open && kind === "backgrounds" && !controls.hidden && controls.dataset.backgroundLoading !== "true") {
        const results = dialog.querySelector("#assetLibraryResults");
        const replacedByOriginalLibrary = results?.querySelector(".asset-library-item:not(.embedded-background-item)");
        if (replacedByOriginalLibrary) {
          controls.dataset.backgroundRenderedGroup = "";
          loadEmbeddedBackgroundLibrary(root);
        }
      }
    };
    const observer = new MutationObserver(() => {
      syncLibrary();
      const resourceDialog = root.querySelector("#resourceDialog");
      if (resourceDialog?.open && /背景请求/.test(resourceDialog.querySelector("#resourceDialogEyebrow")?.textContent || "")) {
        root.querySelectorAll("#resourceResults [data-resource-key]").forEach(button => {
          button.hidden = backgroundKeyClass(button.dataset.resourceKey) !== "scene";
        });
        const status = resourceDialog.querySelector("#resourceDialogStatus");
        const message = "只显示普通场景背景；CG 与自定义背景请从“插入 CG 段落”中选择。";
        if (status && status.textContent !== message) status.textContent = message;
      }
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

  function restructureProductionSurface(sidebar, workspace) {
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
      [...review.querySelectorAll(".review-actions > button:not(#openPerformancePreview)")].forEach(button => toolList.append(button));
      review.querySelector(".review-actions")?.replaceChildren(tools);

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
    installReviewWorkbench(root);
    root.addEventListener("click", event => {
      if (event.target.closest?.("#openAssetLibrary, #assetLibraryDialog [data-asset-kind], #assetLibraryMore")) {
        window.setTimeout(() => simplifyAssetWorkbench(root), 0);
      }
    }, true);
    root.__haloCueProductionWorkbench = true;
    simplifyAssetWorkbench(root);
  }

  function setProductionSurfaceState(root, stateName, options = {}) {
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
      ? `<button type="button" class="production-embed-retry">${esc(options.actionLabel || "重试")}</button>`
      : "";
    panel.setAttribute("role", panelState === "loading" ? "status" : "alert");
    panel.innerHTML = `<div class="production-surface-state-card"><span class="production-surface-state-mark" aria-hidden="true">${panelState === "loading" ? "…" : "!"}</span><div><strong>${esc(title)}</strong><p>${esc(detail)}</p>${retry}</div></div>`;
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
      "/production/previews.css",
      "/production/preflight.css",
      "/production/cg-responsive.css",
      "/production/workspace-migration.css",
      "/production/direction-profile.css",
      "/production-embed.css",
    ];
    const styleLoads = styleUrls.map(stylesheet);
    const links = styleLoads.map(load => load.link);
    const shell = document.createElement("div");
    shell.className = "app-shell embedded-production-shell";
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
      script.src = "/production/app-embedded.js";
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
    if (!runId) return true;
    for (let attempt = 0; attempt < 80; attempt += 1) {
      const button = [...root.querySelectorAll("[data-run-id]")].find(item => item.dataset.runId === runId);
      if (button) {
        button.click();
        return true;
      }
      await sleep(100);
    }
    return false;
  }

  async function open(options = {}) {
    const context = linkedContext(options.trigger);
    for (const key of ["runId", "workId", "releaseId"]) {
      if (options[key]) context[key] = options[key];
    }
    const element = ensureHost();
    element.hidden = false;
    element.focus({ preventScroll: true });
    app()?.classList.add("production-mode");
    setOuterChrome(context);
    updateUrl(context, Boolean(options.replaceHistory));
    try {
      const root = await ensureProductionSurface();
      installFocusRecovery(root, element);
      installProductionLabelSanitizer(root);
      installBackgroundClassification(root);
      installOuterActions(root);
      setProductionSurfaceState(root, "ready");
      const selected = await selectRun(root, context.runId);
      if (context.runId && !selected) {
        setProductionSurfaceState(root, "missing-run", {
          title: "没有找到这项制作任务",
          detail: "任务列表可能还在同步，或这条链接已经失效。",
          actionLabel: "重新读取任务",
          onRetry: () => open({ ...context, replaceHistory: true }),
        });
      } else {
        setProductionSurfaceState(root, "ready");
      }
      // Loading the embedded production surface and selecting a run can move focus
      // back to document.body; restore the outer work-surface focus after async work.
      element.focus({ preventScroll: true });
    } catch (error) {
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
    const params = new URLSearchParams(location.search);
    if (params.get("section") === "production") {
      open({ ...linkedContext(), replaceHistory: true });
    } else {
      close();
    }
  });

  window.HaloCueProductionEmbed = { open, close, preload, status, isOpen: () => app()?.classList.contains("production-mode") };
})();
