(() => {
  "use strict";

  const params = new URLSearchParams(location.search);
  const isProduction = location.pathname.startsWith("/production/");
  const sleep = (delay) => new Promise(resolve => setTimeout(resolve, delay));
  let initialProductionNavigationCancelled = false;

  function installDiagnostics() {
    const documentReference = document;
    const initialNavigationEntryCount = performance.getEntriesByType("navigation").length;
    let shellReference = null;
    let productionOpen = false;
    let transitionCount = 0;
    let sampleCount = 0;
    let blankSampleCount = 0;
    let minimumSurfaceArea = null;
    let lastSample = null;

    const isTransparent = color => !color || color === "transparent" || color === "rgba(0, 0, 0, 0)";

    function surfaceBackground(element) {
      let current = element;
      while (current) {
        const color = getComputedStyle(current).backgroundColor;
        if (!isTransparent(color)) return color;
        current = current.parentElement || current.getRootNode?.().host || null;
      }
      return "transparent";
    }

    function publishDiagnostics() {
      const shell = document.querySelector("#app");
      if (!shell || !lastSample) return;
      const navigationEntryCount = performance.getEntriesByType("navigation").length;
      const productionWarmup = window.HaloCueProductionEmbed?.status?.() || { state: "cold", latencyMs: 0 };
      shell.dataset.integrationSchema = "integration-diagnostics/1.0";
      shell.dataset.integrationPathUnified = String(location.pathname === "/");
      shell.dataset.integrationDocumentStable = String(document === documentReference);
      shell.dataset.integrationShellStable = String(Boolean(shellReference && shell === shellReference));
      shell.dataset.integrationNavigationStable = String(navigationEntryCount === initialNavigationEntryCount);
      shell.dataset.integrationTransitionCount = String(transitionCount);
      shell.dataset.integrationProductionOpen = String(shell.classList.contains("production-mode"));
      shell.dataset.integrationShadowRoot = String(Boolean(document.querySelector("#productionModule")?.shadowRoot));
      shell.dataset.integrationSurfaceVisible = String(lastSample.visible);
      shell.dataset.integrationSurfaceBlank = String(lastSample.blank);
      shell.dataset.integrationBlankSamples = String(blankSampleCount);
      shell.dataset.integrationMinimumArea = String(minimumSurfaceArea || 0);
      shell.dataset.integrationProductionWarmState = productionWarmup.state;
      shell.dataset.integrationProductionWarmLatency = String(productionWarmup.latencyMs);
    }

    function inspectSurface(reason = "snapshot") {
      const shell = document.querySelector("#app");
      const open = Boolean(shell?.classList.contains("production-mode"));
      const element = open
        ? document.querySelector("#productionModule")
        : document.querySelector("#workspace");
      const rect = element?.getBoundingClientRect();
      const style = element ? getComputedStyle(element) : null;
      const width = Math.round(rect?.width || 0);
      const height = Math.round(rect?.height || 0);
      const area = width * height;
      const backgroundColor = element ? surfaceBackground(element) : "transparent";
      const visible = Boolean(
        element
        && !element.hidden
        && width > 0
        && height > 0
        && style?.display !== "none"
        && style?.visibility !== "hidden"
        && Number(style?.opacity ?? 1) > 0
      );
      const blank = !visible || isTransparent(backgroundColor);
      sampleCount += 1;
      if (reason === "transition" && blank) blankSampleCount += 1;
      if (visible) minimumSurfaceArea = minimumSurfaceArea === null ? area : Math.min(minimumSurfaceArea, area);
      lastSample = {
        reason,
        kind: open ? "production" : "writing",
        visible,
        width,
        height,
        backgroundColor,
        blank,
      };
      publishDiagnostics();
      return lastSample;
    }

    function sampleBurst(reason = "transition") {
      const startedAt = performance.now();
      const frame = () => {
        inspectSurface(reason);
        if (performance.now() - startedAt < 600) requestAnimationFrame(frame);
      };
      requestAnimationFrame(frame);
    }

    function installObserver() {
      shellReference = document.querySelector("#app");
      productionOpen = Boolean(shellReference?.classList.contains("production-mode"));
      inspectSurface("initial");
      sampleBurst("readiness");
      if (!shellReference) return;
      new MutationObserver(() => {
        const nextOpen = shellReference.classList.contains("production-mode");
        if (nextOpen !== productionOpen) {
          productionOpen = nextOpen;
          transitionCount += 1;
          sampleBurst();
        }
        inspectSurface("mutation");
      }).observe(shellReference, { attributes: true, attributeFilter: ["class"], childList: true });
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", installObserver, { once: true });
    } else {
      installObserver();
    }

    window.HaloCueIntegrationDiagnostics = Object.freeze({
      snapshot() {
        const surface = inspectSurface();
        const shell = document.querySelector("#app");
        const productionHost = document.querySelector("#productionModule");
        const navigationEntryCount = performance.getEntriesByType("navigation").length;
        const productionWarmup = window.HaloCueProductionEmbed?.status?.() || { state: "cold", latencyMs: 0 };
        return {
          schema: "integration-diagnostics/1.0",
          entrypoint: location.pathname,
          pathIsUnified: location.pathname === "/",
          documentIdentityStable: document === documentReference,
          shellIdentityStable: Boolean(shellReference && shell === shellReference),
          initialNavigationEntryCount,
          navigationEntryCount,
          navigationEntryCountStable: navigationEntryCount === initialNavigationEntryCount,
          transitionCount,
          productionOpen: Boolean(shell?.classList.contains("production-mode")),
          productionHostPresent: Boolean(productionHost),
          productionUsesShadowRoot: Boolean(productionHost?.shadowRoot),
          productionWarmup,
          surface: {
            ...surface,
            sampleCount,
            blankSampleCount,
            noBlankSamples: blankSampleCount === 0,
            minimumArea: minimumSurfaceArea || 0,
          },
        };
      },
    });
  }

  installDiagnostics();

  async function waitFor(find, attempts = 60) {
    for (let index = 0; index < attempts; index += 1) {
      const value = find();
      if (value) return value;
      await sleep(100);
    }
    return null;
  }

  async function warmProductionSurface() {
    const preload = await waitFor(() => window.HaloCueProductionEmbed?.preload, 30);
    if (!preload) return;
    try {
      await preload();
    } catch (_) {
      // Opening the production surface remains the visible retry boundary.
    }
  }

  function scheduleProductionWarmup() {
    const warm = () => { void warmProductionSurface(); };
    if ("requestIdleCallback" in window) window.requestIdleCallback(warm, { timeout: 2500 });
    else window.setTimeout(warm, 800);
  }

  function productionUrl(runId, workId, releaseId) {
    const url = new URL("/production/", location.origin);
    if (runId) url.searchParams.set("run_id", runId);
    if (workId) url.searchParams.set("work_id", workId);
    if (releaseId) url.searchParams.set("release_id", releaseId);
    return url;
  }

  if (!isProduction) {
    for (const eventName of ["pointerover", "focusin"]) {
      document.addEventListener(eventName, event => {
        if (event.target.closest('[data-section="production"]')) void warmProductionSurface();
      }, true);
    }

    document.addEventListener("click", async event => {
      const leavingSection = event.target.closest('[data-section]:not([data-section="production"])')?.dataset.section;
      const leavingMobile = event.target.closest("[data-mobile]")?.dataset.mobile;
      if (leavingSection || leavingMobile) initialProductionNavigationCancelled = true;
      const productionModeVisible = document.querySelector("#app")?.classList.contains("production-mode");
      if ((productionModeVisible || window.HaloCueProductionEmbed?.isOpen?.()) && (leavingSection || leavingMobile)) {
        const destination = leavingSection || (leavingMobile === "works" || leavingMobile === "references" || leavingMobile === "tasks" ? leavingMobile : "writing");
        window.HaloCueProductionEmbed?.close?.({ section: destination });
        if (destination === "writing" && params.get("release_id")) {
          setTimeout(() => document.querySelector('[data-stage="release"]:not([disabled])')?.click(), 0);
        }
      }
      const productionNav = event.target.closest('[data-section="production"]');
      if (productionNav) {
        if (productionNav.matches('.locked-nav,[aria-disabled="true"]')) {
          event.preventDefault();
          event.stopImmediatePropagation();
          return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        const linkedProduction = document.querySelector("[data-open-production]");
        const openProduction = await waitFor(() => window.HaloCueProductionEmbed?.open, 30);
        if (!openProduction) {
          window.alert("AA 制作工作面没有载入，请刷新当前页面后重试。");
          return;
        }
        openProduction({
          trigger: linkedProduction || productionNav,
          runId: linkedProduction?.dataset.openProduction || params.get("run_id") || "",
          workId: linkedProduction?.dataset.workId || params.get("work_id") || "",
          releaseId: linkedProduction?.dataset.releaseId || params.get("release_id") || "",
        });
        return;
      }

      const existing = event.target.closest("[data-open-production]");
      if (existing) {
        event.preventDefault();
        event.stopImmediatePropagation();
        const openProduction = await waitFor(() => window.HaloCueProductionEmbed?.open, 30);
        if (openProduction) openProduction({
          trigger: existing,
          runId: existing.dataset.openProduction,
          workId: existing.dataset.workId,
          releaseId: existing.dataset.releaseId,
        });
        return;
      }

      const handoff = event.target.closest("[data-handoff]");
      if (!handoff || handoff.disabled) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const releaseId = handoff.dataset.handoff;
      handoff.disabled = true;
      handoff.textContent = "正在建立制作任务...";
      try {
        const response = await fetch(`/api/v1/releases/${encodeURIComponent(releaseId)}/handoff`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        const payload = await response.json();
        if (!response.ok || payload.ok === false) throw new Error(payload.error?.message || "交接失败");
        const result = payload.data || payload;
        const openProduction = await waitFor(() => window.HaloCueProductionEmbed?.open, 30);
        if (!openProduction) throw new Error("AA 制作工作面没有载入");
        openProduction({
          runId: result.production_run_id,
          workId: handoff.dataset.workId,
          releaseId,
        });
      } catch (error) {
        handoff.disabled = false;
        handoff.textContent = "交给 AA 制作";
        window.alert(error.message || "AA 制作后端当前不可用，发布版本仍安全保留。");
      }
    }, true);

    window.addEventListener("DOMContentLoaded", async () => {
      await waitFor(() => !document.body.classList.contains("app-loading"), 120);
      scheduleProductionWarmup();
      const workId = params.get("work_id");
      if (workId) {
        const workButton = await waitFor(() => [...document.querySelectorAll("[data-select-work]")].find(button => button.dataset.selectWork === workId));
        workButton?.click();
        await waitFor(() => [...document.querySelectorAll("[data-select-work]")].find(button => button.dataset.selectWork === workId && button.classList.contains("active")));
      }
      const section = params.get("section");
      if (section === "production" && !initialProductionNavigationCancelled) {
        const openProduction = await waitFor(() => window.HaloCueProductionEmbed?.open, 40);
        if (openProduction) {
          openProduction({
            runId: params.get("run_id") || "",
            workId: params.get("work_id") || "",
            releaseId: params.get("release_id") || "",
          });
        }
      } else if (section && !["works", "writing", "references", "tasks"].includes(section)) {
        // The writing workbench owns its deep-link route, including chapter,
        // scene and stage. Do not replay a top-level nav click here: it can
        // overwrite a restored draft target after the writing router applies.
        const sectionButton = await waitFor(() => document.querySelector(`[data-section="${section}"]:not([disabled])`));
        sectionButton?.click();
      }
    });
    return;
  }

  async function initializeProductionShell() {
    document.body.classList.add("halocue-integrated-production");
    const appShell = document.querySelector(".app-shell");
    const rail = document.querySelector(".app-rail");
    const workspace = document.querySelector(".workspace");
    const topbar = document.querySelector(".topbar");
    const assetLibrary = document.querySelector("#openAssetLibrary");
    const tasks = document.querySelector("#openTasks");
    const settings = document.querySelector("#openSettings");
    if (rail && tasks && settings) {
      const linkedWorkId = params.get("work_id");
      const linkedReleaseId = params.get("release_id");
      const writingSectionUrl = (section) => {
        const url = new URL("/", location.origin);
        url.searchParams.set("section", section);
        if (linkedWorkId) url.searchParams.set("work_id", linkedWorkId);
        if (section === "writing" && linkedReleaseId) {
          url.searchParams.set("stage", "release");
          url.searchParams.set("release_id", linkedReleaseId);
        }
        return `${url.pathname}${url.search}`;
      };
      const navLink = (label, mark, href, extra = "") => `<a class="integrated-nav-item ${extra}" href="${href}" title="${label}"><span class="integrated-nav-mark">${mark}</span><span>${label}</span></a>`;
      rail.innerHTML = `<a class="integrated-brand" href="/" title="HaloCue">HC</a>${navLink("作品", "作", writingSectionUrl("works"))}${navLink("写作", "写", writingSectionUrl("writing"))}${navLink("AA 制作", "制", `${location.pathname}${location.search}`, "active")}${navLink("资料", "资", writingSectionUrl("references"), "integrated-reference-link")}<span class="integrated-nav-task"></span><span class="integrated-nav-spacer"></span><button type="button" class="integrated-nav-item" id="openFeedbackInProduction" title="反馈使用体验或问题"><span class="integrated-nav-mark">馈</span><span>反馈</span></button><span class="integrated-nav-settings"></span>`;
      tasks.className = "integrated-nav-item";
      tasks.innerHTML = '<span class="integrated-nav-mark">任</span><span>任务</span>';
      tasks.title = "制作任务";
      settings.className = "integrated-nav-item";
      settings.innerHTML = '<span class="integrated-nav-mark">设</span><span>设置</span>';
      rail.querySelector(".integrated-nav-task")?.replaceWith(tasks);
      rail.querySelector(".integrated-nav-settings")?.replaceWith(settings);

      document.querySelector("#openFeedbackInProduction")?.addEventListener("click", () => {
        location.href = writingSectionUrl("writing") + "&open_feedback=1";
      });
    }
    if (appShell && workspace && topbar) {
      appShell.prepend(topbar);
      const brand = rail?.querySelector(".integrated-brand");
      if (brand) topbar.prepend(brand);
    }
    if (assetLibrary) {
      assetLibrary.className = "integrated-top-action";
      assetLibrary.textContent = "制作素材";
      assetLibrary.title = "打开当前制作任务可用素材";
      document.querySelector(".top-actions")?.prepend(assetLibrary);
    }
    const runId = params.get("run_id");
    if (!runId) return;
    const runButton = await waitFor(() => [...document.querySelectorAll("[data-run-id]")].find(button => button.dataset.runId === runId));
    runButton?.click();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeProductionShell, { once: true });
  } else {
    initializeProductionShell();
  }
})();
