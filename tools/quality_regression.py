"""Run the focused HaloCue 1.0 quality gate against an isolated runtime.

The script intentionally treats the browser as a product surface: a successful
HTTP response is not enough when the page logs CSP errors, overflows, or leaves
the user without a recoverable next action.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright


VIEWPORTS = ((1920, 1080), (1440, 900), (1366, 768), (390, 844))


def root_locator(page, selector: str):
    """Locate an embedded production element through Playwright's shadow DOM piercing."""
    return page.locator(selector)


def get_json(base_url: str, path: str) -> dict:
    request = Request(f"{base_url.rstrip('/')}{path}", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GET {path} failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"GET {path} returned a non-object payload")
    return payload


def assert_health(base_url: str) -> dict[str, dict]:
    writing = get_json(base_url, "/api/v1/health")
    production = get_json(base_url, "/production/api/v1/health")
    manifest = get_json(base_url, "/integration/manifest")
    provider = writing.get("provider") if isinstance(writing.get("provider"), dict) else {}
    skill = writing.get("ba_writing_skill") if isinstance(writing.get("ba_writing_skill"), dict) else {}
    if provider.get("can_call_model") is not True or provider.get("is_simulation") is not False:
        raise RuntimeError("writing provider is not a real, callable provider")
    if skill.get("status") != "ready":
        raise RuntimeError("BA Writing Skill is not ready")
    capabilities = production.get("capabilities") if isinstance(production.get("capabilities"), dict) else {}
    for name in ("compile", "install"):
        if (capabilities.get(name) or {}).get("state") != "available":
            raise RuntimeError(f"production capability {name!r} is unavailable")
    return {"writing": writing, "production": production, "manifest": manifest}


def collect_production_evidence(base_url: str, run_project: str | None) -> dict[str, object]:
    """Collect a redacted, read-only release/run/install receipt for the report."""
    listing = get_json(base_url, "/production/api/v1/production-runs")
    items = listing.get("items") if isinstance(listing.get("items"), list) else []
    candidates = [item for item in items if isinstance(item, dict)]
    selected = next(
        (item for item in candidates if run_project and item.get("project") == run_project),
        candidates[0] if candidates else None,
    )
    if not selected or not selected.get("run_id"):
        raise RuntimeError(f"no production run found for evidence project {run_project!r}")
    run_id = str(selected["run_id"])
    detail = get_json(base_url, f"/production/api/v1/production-runs/{run_id}")
    run = detail.get("run") if isinstance(detail.get("run"), dict) else {}
    draft = detail.get("draft") if isinstance(detail.get("draft"), dict) else {}
    gates = detail.get("gates") if isinstance(detail.get("gates"), dict) else {}
    return {
        "project": run.get("project"),
        "run_id": run.get("run_id"),
        "release_id": run.get("release_id"),
        "state": run.get("state"),
        "current_stage": run.get("current_stage"),
        "draft_version": draft.get("draft_version"),
        "card_count": len(draft.get("cards") or []),
        "gates": gates,
        "last_build_id": run.get("last_build_id"),
        "last_installed_project": run.get("last_installed_project"),
        "install_verified": bool(
            (gates.get("install") or {}).get("passed") is True
            and run.get("state") == "installed"
            and run.get("last_installed_project")
        ),
    }


def browser_boundary_quality(base_url: str, output_dir: Path) -> dict[str, dict]:
    """Exercise recoverable loading, missing-route, and list-failure states."""
    output_dir.mkdir(parents=True, exist_ok=True)
    base = base_url.rstrip("/")
    checks: dict[str, dict] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            delay_used = {"value": False}

            def delay_first_surface(route):
                if not delay_used["value"]:
                    delay_used["value"] = True
                    time.sleep(1.0)
                route.continue_()

            for surface_endpoint in (f"{base}/production/", f"{base}/integration/production-fragment"):
                page.route(surface_endpoint, delay_first_surface)
            page.goto(f"{base}/?section=production", wait_until="domcontentloaded")
            page.wait_for_function(
                """() => {
                  const root = document.querySelector('#productionModule')?.shadowRoot;
                  const panel = root?.querySelector('.production-surface-state[data-state="loading"]');
                  return Boolean(panel && !panel.hidden);
                }""",
                timeout=8_000,
            )
            loading = page.evaluate(
                """() => {
                  const root = document.querySelector('#productionModule')?.shadowRoot;
                  const host = document.querySelector('#productionModule');
                  const panel = root?.querySelector('.production-surface-state');
                  const shell = root?.querySelector('.embedded-production-shell');
                  const box = panel?.getBoundingClientRect();
                  return {
                    state: panel?.dataset.state,
                    visible: Boolean(box && box.width > 0 && box.height > 0),
                    hostVisible: Boolean(host && host.getBoundingClientRect().height > 0),
                    shellPresent: Boolean(shell),
                    shellSuppressed: !shell || shell.hidden === true || getComputedStyle(shell).display === 'none',
                  };
                }"""
            )
            page.locator(".embedded-production-shell").wait_for(timeout=15_000)
            page.screenshot(path=output_dir / "loading-boundary-390x844.png", full_page=False)
            if (
                loading["state"] != "loading"
                or not loading["visible"]
                or not loading["hostVisible"]
                or not loading["shellSuppressed"]
            ):
                raise RuntimeError(f"loading boundary failed: {loading}")
            checks["loading"] = {
                **loading,
                "screenshot": str(output_dir / "loading-boundary-390x844.png"),
            }
            page.close()

            page = browser.new_page(viewport={"width": 390, "height": 844})
            failure_used = {"value": False}
            surface_request_count = {"value": 0}

            def fail_first_surface(route):
                surface_request_count["value"] += 1
                if not failure_used["value"]:
                    failure_used["value"] = True
                    route.fulfill(
                        status=503,
                        content_type="text/plain",
                        body="temporary production surface failure",
                    )
                    return
                route.continue_()

            for surface_endpoint in (f"{base}/production/", f"{base}/integration/production-fragment"):
                page.route(surface_endpoint, fail_first_surface)
            page.goto(f"{base}/?section=production", wait_until="domcontentloaded")
            page.wait_for_function(
                """() => {
                  const root = document.querySelector('#productionModule')?.shadowRoot;
                  const panel = root?.querySelector('.production-surface-state[data-state="error"]');
                  return Boolean(panel && !panel.hidden);
                }""",
                timeout=15_000,
            )
            surface_error = page.evaluate(
                """() => {
                  const root = document.querySelector('#productionModule')?.shadowRoot;
                  const panel = root?.querySelector('.production-surface-state');
                  const shell = root?.querySelector('.embedded-production-shell');
                  const box = panel?.getBoundingClientRect();
                  return {
                    state: panel?.dataset.state,
                    visible: Boolean(box && box.width > 0 && box.height > 0),
                    shellPresent: Boolean(shell),
                    shellSuppressed: !shell || getComputedStyle(shell).display === 'none',
                    retryCount: root?.querySelectorAll('.production-embed-retry').length || 0,
                  };
                }"""
            )
            if (
                surface_error["state"] != "error"
                or not surface_error["visible"]
                or not surface_error["shellSuppressed"]
                or surface_error["retryCount"] != 1
                or surface_request_count["value"] != 1
            ):
                raise RuntimeError(
                    f"production load-error boundary failed: {surface_error}, "
                    f"requests={surface_request_count['value']}"
                )
            page.locator(".production-embed-retry").click()
            page.locator(".embedded-production-shell").wait_for(timeout=15_000)
            page.locator("#runList .run-row").first.wait_for(timeout=15_000)
            recovered_error = page.evaluate(
                """() => {
                  const root = document.querySelector('#productionModule')?.shadowRoot;
                  const panel = root?.querySelector('.production-surface-state');
                  return {
                    panelHidden: panel?.hidden === true,
                    shellDisplay: getComputedStyle(root?.querySelector('.embedded-production-shell')).display,
                    runRows: root?.querySelectorAll('#runList .run-row').length || 0,
                  };
                }"""
            )
            page.screenshot(path=output_dir / "surface-error-recovered-390x844.png", full_page=False)
            if (
                not recovered_error["panelHidden"]
                or recovered_error["shellDisplay"] == "none"
                or recovered_error["runRows"] == 0
            ):
                raise RuntimeError(f"production load-error recovery failed: {recovered_error}")
            checks["surface_error"] = {
                "failed": surface_error,
                "recovered": recovered_error,
                "screenshot": str(output_dir / "surface-error-recovered-390x844.png"),
            }
            page.close()

            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(f"{base}/?section=production&run_id=run-does-not-exist", wait_until="domcontentloaded")
            page.wait_for_function(
                """() => {
                  const root = document.querySelector('#productionModule')?.shadowRoot;
                  const panel = root?.querySelector('.production-surface-state[data-state="missing-run"]');
                  return Boolean(panel && !panel.hidden);
                }""",
                timeout=20_000,
            )
            missing = page.evaluate(
                """() => {
                  const root = document.querySelector('#productionModule')?.shadowRoot;
                  const panel = root?.querySelector('.production-surface-state');
                  const shell = root?.querySelector('.embedded-production-shell');
                  const panelBox = panel?.getBoundingClientRect();
                  const hostBox = document.querySelector('#productionModule')?.getBoundingClientRect();
                  return {
                    state: panel?.dataset.state,
                    panelVisible: Boolean(panelBox && panelBox.width > 0 && panelBox.height > 0),
                    panelInHost: Boolean(panelBox && hostBox && panelBox.top >= hostBox.top && panelBox.bottom <= hostBox.bottom),
                    shellHidden: shell?.hidden === true,
                    shellDisplay: shell ? getComputedStyle(shell).display : null,
                    retryCount: root?.querySelectorAll('.production-embed-retry').length || 0,
                  };
                }"""
            )
            page.screenshot(path=output_dir / "missing-run-390x844.png", full_page=False)
            if (
                missing["state"] != "missing-run"
                or not missing["panelVisible"]
                or not missing["panelInHost"]
                or not missing["shellHidden"]
                or missing["shellDisplay"] != "none"
                or missing["retryCount"] != 1
            ):
                raise RuntimeError(f"missing-run boundary failed: {missing}")
            checks["missing_run"] = {
                **missing,
                "screenshot": str(output_dir / "missing-run-390x844.png"),
            }
            page.close()

            page = browser.new_page(viewport={"width": 1366, "height": 768})
            console: list[dict[str, str]] = []
            pageerrors: list[str] = []
            failed_requests: list[dict[str, str | None]] = []
            page.on(
                "console",
                lambda message: console.append({"type": message.type, "text": message.text})
                if message.type in {"error", "warning"}
                else None,
            )
            page.on("pageerror", lambda error: pageerrors.append(str(error)))
            page.on(
                "requestfailed",
                lambda request: failed_requests.append({"url": request.url, "failure": request.failure}),
            )
            failure_used = {"value": False}

            def fail_first_run_list(route):
                if not failure_used["value"]:
                    failure_used["value"] = True
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body=json.dumps({"ok": False, "error": {"message": "任务服务暂时不可用"}}),
                    )
                    return
                route.continue_()

            page.route(f"{base}/production/api/v1/production-runs", fail_first_run_list)
            page.goto(f"{base}/?section=production", wait_until="networkidle")
            page.locator(".embedded-production-shell").wait_for(timeout=15_000)
            page.locator("#runList .run-list-retry").wait_for(timeout=10_000)
            failed_state = page.evaluate(
                """() => {
                  const root = document.querySelector('#productionModule')?.shadowRoot;
                  const list = root?.querySelector('#runList');
                  const retry = list?.querySelector('.run-list-retry');
                  return {
                    errorVisible: Boolean(list?.querySelector('.run-list-error')),
                    retryCount: list?.querySelectorAll('.run-list-retry').length || 0,
                    retryEnabled: retry?.disabled === false,
                    sourcePageVisible: Boolean(root?.querySelector('#page-source.active')),
                  };
                }"""
            )
            if (
                not failed_state["errorVisible"]
                or failed_state["retryCount"] != 1
                or not failed_state["retryEnabled"]
                or not failed_state["sourcePageVisible"]
            ):
                raise RuntimeError(f"run-list failure boundary failed: {failed_state}")
            page.locator("#runList .run-list-retry").click()
            page.locator("#runList .run-row").first.wait_for(timeout=10_000)
            recovered = page.evaluate(
                """() => {
                  const root = document.querySelector('#productionModule')?.shadowRoot;
                  const list = root?.querySelector('#runList');
                  return {
                    runRows: list?.querySelectorAll('.run-row').length || 0,
                    errorVisible: Boolean(list?.querySelector('.run-list-error')),
                    refreshEnabled: root?.querySelector('#reloadRuns')?.disabled === false,
                  };
                }"""
            )
            if (
                recovered["runRows"] == 0
                or recovered["errorVisible"]
                or not recovered["refreshEnabled"]
                or pageerrors
            ):
                raise RuntimeError(
                    f"run-list recovery failed: state={recovered}, pageerrors={pageerrors}"
                )
            page.screenshot(path=output_dir / "run-list-failure-1366x768.png", full_page=False)
            checks["run_list_failure"] = {
                "failed": failed_state,
                "recovered": recovered,
                "expected_console": console,
                "failed_requests": failed_requests,
                "screenshot": str(output_dir / "run-list-failure-1366x768.png"),
            }
            page.close()

            runs = get_json(base, "/production/api/v1/production-runs").get("items") or []
            valid_run_id = runs[0].get("run_id") if isinstance(runs[0], dict) else None
            if not valid_run_id:
                raise RuntimeError("deep-link boundary requires at least one production run")
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            deep_link = f"{base}/?section=production&run_id={valid_run_id}"
            page.goto(deep_link, wait_until="networkidle")
            page.locator(".embedded-production-shell").wait_for(timeout=15_000)
            first = page.evaluate(
                """() => ({
                  url: location.href,
                  history: history.length,
                  production: document.querySelector('#app')?.classList.contains('production-mode') === true,
                  title: document.querySelector('#productionModule')?.shadowRoot?.querySelector('#runTitle')?.textContent || '',
                })"""
            )
            page.reload(wait_until="networkidle")
            page.locator(".embedded-production-shell").wait_for(timeout=15_000)
            second = page.evaluate(
                """() => ({
                  url: location.href,
                  history: history.length,
                  production: document.querySelector('#app')?.classList.contains('production-mode') === true,
                  title: document.querySelector('#productionModule')?.shadowRoot?.querySelector('#runTitle')?.textContent || '',
                })"""
            )
            page.go_back(wait_until="domcontentloaded")
            page.wait_for_timeout(300)
            back = page.evaluate(
                """() => ({
                  url: location.href,
                  history: history.length,
                  production: document.querySelector('#app')?.classList.contains('production-mode') === true,
                })"""
            )
            if (
                not first["production"]
                or not second["production"]
                or first["history"] != second["history"]
                or back["production"]
                or back["url"] == deep_link
            ):
                raise RuntimeError(
                    f"deep-link refresh/back boundary failed: first={first}, second={second}, back={back}"
                )
            checks["deep_link_navigation"] = {"first": first, "after_refresh": second, "after_back": back}
            page.close()
        finally:
            browser.close()
    return checks


def browser_quality(base_url: str, output_dir: Path, run_project: str | None) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width, height in VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                console: list[dict[str, str]] = []
                failed: list[dict[str, str | None]] = []
                pageerrors: list[str] = []
                page.on(
                    "console",
                    lambda message: console.append({"type": message.type, "text": message.text})
                    if message.type in {"error", "warning"}
                    else None,
                )
                page.on("pageerror", lambda error: pageerrors.append(str(error)))
                page.on(
                    "requestfailed",
                    lambda request: failed.append({"url": request.url, "failure": request.failure}),
                )
                url = f"{base_url.rstrip('/')}/?section=production"
                response = page.goto(url, wait_until="networkidle")
                if response is None or not response.ok:
                    raise RuntimeError(f"browser navigation failed: {url}")
                page.locator(".embedded-production-shell").wait_for(timeout=15_000)
                rows = page.locator("#runList .run-row")
                rows.first.wait_for(timeout=15_000)
                asset_entry = page.locator('.production-top-actions [data-production-proxy="openAssetLibrary"]')
                if asset_entry.count() and not asset_entry.is_disabled():
                    raise RuntimeError(f"asset entry should be disabled before selecting a run at {width}x{height}")
                if any(re.search(r"(?:^|\s)(?:run|job|build)-[a-z0-9-]+", text, re.IGNORECASE) for text in rows.all_inner_texts()):
                    raise RuntimeError(f"production run list exposes internal identifiers at {width}x{height}")
                target = rows.filter(has_text=run_project).first if run_project else rows.first
                if target.count() == 0:
                    raise RuntimeError(f"no production run found for {run_project!r}")
                target.click()
                page.locator("#page-review.active, #page-mapping.active").wait_for(timeout=15_000)
                page.wait_for_timeout(150)
                opening_toast = page.evaluate(
                    """() => {
                      const root = document.querySelector('#productionModule')?.shadowRoot;
                      return Boolean(root?.querySelector('.embedded-production-shell ~ .toast.visible'));
                    }"""
                )
                if opening_toast:
                    raise RuntimeError(f"opening an existing run shows redundant toast at {width}x{height}")
                page.wait_for_function(
                    """() => !document.querySelector('.production-top-actions [data-production-proxy="openAssetLibrary"]')?.disabled""",
                    timeout=4_000,
                )

                mapping = page.locator('.stage-list [data-stage="mapping"]')
                if mapping.count() and mapping.get_attribute("aria-disabled") != "true":
                    mapping.click()
                    page.locator("#page-mapping.active").wait_for(timeout=8_000)
                edit = page.locator("#mappingList .mapping-edit").first
                if edit.count():
                    edit.click()
                    page.locator("#mappingDialog[open]").wait_for(timeout=8_000)
                    page.keyboard.press("Escape")

                metrics = page.evaluate(
                    """() => {
                      const host = document.querySelector('#productionModule');
                      const root = host?.shadowRoot;
                      const scope = root || document;
                      const shell = root?.querySelector('.embedded-production-shell');
                      const activePage = root?.querySelector('.page.active');
                      const isVisible = (element) => {
                        const style = getComputedStyle(element);
                        const box = element.getBoundingClientRect();
                        return style.display !== 'none'
                          && style.visibility !== 'hidden'
                          && box.width > 0
                          && box.height > 0;
                      };
                      const focusable = 'button, input, textarea, select, a, [tabindex]';
                      const isSuppressed = (element) => {
                        const ariaHidden = element.closest('[aria-hidden="true"]');
                        const inert = element.closest('[inert]');
                        return Boolean(ariaHidden) && !inert;
                      };
                      const overlap = (first, second) => {
                        if (!first || !second) return 0;
                        const horizontal = Math.min(first.right, second.right) - Math.max(first.left, second.left);
                        const vertical = Math.min(first.bottom, second.bottom) - Math.max(first.top, second.top);
                        return horizontal > 0 && vertical > 0 ? vertical : 0;
                      };
                      const toast = root?.querySelector('#toast.visible, .toast.visible');
                      const toastBox = toast?.getBoundingClientRect();
                      const toastTargets = root
                        ? [...root.querySelectorAll('.page-lead, .mapping-focus, .mapping-support-panel, .sticky-actions')]
                        : [];
                      return {
                        overflowX: Math.max(
                          0,
                          document.documentElement.scrollWidth - document.documentElement.clientWidth,
                          shell ? shell.scrollWidth - shell.clientWidth : 0,
                        ),
                        inlineHandlers: [...scope.querySelectorAll('[onerror], [onclick], [onload]')].length,
                        visiblePrimaryActions: [...(activePage || scope).querySelectorAll('button.primary')]
                          .filter(isVisible).length,
                        hiddenFocusable: [...document.querySelectorAll(focusable), ...scope.querySelectorAll(focusable)]
                          .filter(element => isVisible(element) && isSuppressed(element)).length,
                        toastOverlap: toastBox
                          ? Math.max(0, ...toastTargets.map(target => overlap(toastBox, target.getBoundingClientRect())))
                          : 0,
                      };
                    }"""
                )
                flow_box = page.locator(".production-flow-strip").bounding_box()
                heading_box = page.locator("#page-mapping h3").first.bounding_box()
                metrics["flowHeadingOverlap"] = (
                    max(0, flow_box["y"] + flow_box["height"] - heading_box["y"])
                    if flow_box and heading_box
                    else 0
                )
                screenshot = output_dir / f"quality-{width}x{height}.png"
                page.screenshot(path=screenshot, full_page=False)
                result = {
                    "viewport": {"width": width, "height": height},
                    "metrics": metrics,
                    "console": console,
                    "pageerrors": pageerrors,
                    "failed_requests": failed,
                    "screenshot": str(screenshot),
                }
                if (
                    metrics["overflowX"] != 0
                    or metrics["inlineHandlers"] != 0
                    or metrics["flowHeadingOverlap"] > 0
                    or metrics["visiblePrimaryActions"] > 1
                    or metrics["hiddenFocusable"] != 0
                    or metrics["toastOverlap"] > 0
                ):
                    raise RuntimeError(f"browser quality gate failed at {width}x{height}: {metrics}")
                if console or pageerrors or failed:
                    raise RuntimeError(f"browser emitted errors at {width}x{height}")

                # Continue the happy path into generation and review. The
                # mapping page is the first gate, but a usable product must
                # keep its single next action reachable on the next screen.
                continue_button = root_locator(page, "#mappingContinue")
                if continue_button.is_disabled():
                    raise RuntimeError(f"mapping unexpectedly blocked at {width}x{height}")
                continue_button.click()
                root_locator(page, "#page-generation.active").wait_for(timeout=8_000)
                generation_button = root_locator(page, "#generateOrReview")
                generation_box = generation_button.bounding_box()
                mobile_nav_box = page.locator(".mobile-nav").bounding_box()
                generation_metrics = {
                    "visiblePrimaryActions": page.evaluate(
                        """() => {
                          const root = document.querySelector('#productionModule')?.shadowRoot;
                          const page = root?.querySelector('#page-generation.active');
                          if (!page) return 0;
                          return [...page.querySelectorAll('button.primary')].filter((element) => {
                            const style = getComputedStyle(element);
                            const box = element.getBoundingClientRect();
                            return style.display !== 'none' && style.visibility !== 'hidden'
                              && box.width > 0 && box.height > 0;
                          }).length;
                        }"""
                    ),
                    "nextActionVisible": bool(generation_box and generation_box["width"] > 0 and generation_box["height"] > 0),
                    "nextActionCoveredByMobileNav": bool(
                        generation_box and mobile_nav_box
                        and generation_box["y"] + generation_box["height"]
                        > mobile_nav_box["y"]
                    ),
                }
                generation_screenshot = output_dir / f"generation-{width}x{height}.png"
                page.screenshot(path=generation_screenshot, full_page=False)
                result["generation"] = {
                    "metrics": generation_metrics,
                    "screenshot": str(generation_screenshot),
                }
                if (
                    generation_metrics["visiblePrimaryActions"] != 1
                    or not generation_metrics["nextActionVisible"]
                    or generation_metrics["nextActionCoveredByMobileNav"]
                ):
                    raise RuntimeError(
                        f"generation quality gate failed at {width}x{height}: {generation_metrics}"
                    )

                generation_button.click()
                root_locator(page, "#page-review.active").wait_for(timeout=8_000)
                review_summary = root_locator(page, "#reviewSummary").inner_text()
                if re.search(r"\d+\s*版草稿|(?:run|job|build)-[a-z0-9-]+", review_summary, re.IGNORECASE):
                    raise RuntimeError(f"review summary exposes internal revision data at {width}x{height}")
                review_screenshot = output_dir / f"review-{width}x{height}.png"
                page.screenshot(path=review_screenshot, full_page=False)
                result["review"] = {"screenshot": str(review_screenshot)}

                review_tools = root_locator(page, ".production-review-tools")
                if review_tools.count():
                    review_tools.locator(":scope > summary").click()
                    review_tool_list = review_tools.locator(":scope > .production-review-tool-list")
                    review_tool_list.wait_for(timeout=4_000)
                    review_menu_metrics = page.evaluate(
                        """() => {
                          const root = document.querySelector('#productionModule')?.shadowRoot;
                          const tools = root?.querySelector('.production-review-tools');
                          const list = tools?.querySelector('.production-review-tool-list');
                          const isVisible = (element) => {
                            if (!element) return false;
                            const style = getComputedStyle(element);
                            const box = element.getBoundingClientRect();
                            return !element.hidden && style.display !== 'none' && style.visibility !== 'hidden'
                              && box.width > 0 && box.height > 0;
                          };
                          const visibleButtons = [...(list?.querySelectorAll('button') || [])]
                            .filter(isVisible)
                            .map((button) => ({ id: button.id, text: button.textContent?.trim() || '' }));
                          const listBox = list?.getBoundingClientRect();
                          const isClipped = (element, box) => {
                            let parent = element?.parentElement;
                            while (parent && parent !== root) {
                              const style = getComputedStyle(parent);
                              if (/(hidden|clip)/.test(`${style.overflow} ${style.overflowX} ${style.overflowY}`)) {
                                const parentBox = parent.getBoundingClientRect();
                                if (box.left < parentBox.left || box.right > parentBox.right
                                  || box.top < parentBox.top || box.bottom > parentBox.bottom) return true;
                              }
                              parent = parent.parentElement;
                            }
                            return false;
                          };
                          return {
                            visibleButtons,
                            legacyInMenu: Boolean(list?.querySelector('#openPerformancePreview')),
                            rightOverflow: listBox ? Math.max(0, listBox.right - window.innerWidth) : 0,
                            leftOverflow: listBox ? Math.max(0, -listBox.left) : 0,
                            clipped: Boolean(listBox && isClipped(list, listBox)),
                          };
                        }"""
                    )
                    result["review"]["tools"] = review_menu_metrics
                    review_tools_screenshot = output_dir / f"review-tools-{width}x{height}.png"
                    page.screenshot(path=review_tools_screenshot, full_page=False)
                    result["review"]["tools"]["screenshot"] = str(review_tools_screenshot)
                    if (
                        len(review_menu_metrics["visibleButtons"]) != 4
                        or review_menu_metrics["legacyInMenu"]
                        or review_menu_metrics["rightOverflow"] > 0
                        or review_menu_metrics["leftOverflow"] > 0
                        or review_menu_metrics["clipped"]
                    ):
                        raise RuntimeError(
                            f"review tools quality gate failed at {width}x{height}: "
                            f"{review_menu_metrics}"
                        )
                    review_tools.locator(":scope > summary").click()

                if width <= 800:
                    page.evaluate(
                        """() => {
                          const host = document.querySelector('#productionModule');
                          const root = host?.shadowRoot;
                          const shell = root?.querySelector('.embedded-production-shell');
                          const cardList = root?.querySelector('#page-review.active #cardList');
                          if (cardList) cardList.scrollTop = cardList.scrollHeight;
                          shell?.scrollTo({ top: shell.scrollHeight, behavior: 'instant' });
                        }"""
                    )
                    page.wait_for_timeout(80)
                    mobile_review_metrics = page.evaluate(
                        """() => {
                          const host = document.querySelector('#productionModule');
                          const root = host?.shadowRoot;
                          const nav = document.querySelector('.mobile-nav');
                          const cardList = root?.querySelector('#page-review.active #cardList');
                          const lastCard = cardList?.querySelector('.draft-card:last-child');
                          const buildbar = root?.querySelector('#page-review.active .buildbar');
                          const navBox = nav?.getBoundingClientRect();
                          const lastBox = lastCard?.getBoundingClientRect();
                          const buildBox = buildbar?.getBoundingClientRect();
                          const overlap = (box) => navBox && box
                            ? Math.max(0, Math.min(navBox.bottom, box.bottom) - Math.max(navBox.top, box.top))
                            : 0;
                          return {
                            lastCardNavOverlap: overlap(lastBox),
                            buildbarNavOverlap: overlap(buildBox),
                            shellAtBottom: root?.querySelector('.embedded-production-shell')
                              ? Math.ceil(root.querySelector('.embedded-production-shell').scrollTop
                                + root.querySelector('.embedded-production-shell').clientHeight)
                                >= root.querySelector('.embedded-production-shell').scrollHeight
                              : false,
                          };
                        }"""
                    )
                    result["review"]["mobileBottom"] = mobile_review_metrics
                    if (
                        mobile_review_metrics["lastCardNavOverlap"] > 0
                        or mobile_review_metrics["buildbarNavOverlap"] > 0
                    ):
                        raise RuntimeError(
                            f"mobile review bottom overlap at {width}x{height}: "
                            f"{mobile_review_metrics}"
                        )

                    # Editing is the high-frequency mobile review action. It
                    # opens the same drawer as the preview, but puts the
                    # inspector first and returns focus to its opener.
                    edit_toggle = root_locator(page, "[data-production-edit-current]")
                    if not edit_toggle.is_visible():
                        raise RuntimeError(f"mobile edit-current action is not visible at {width}x{height}")
                    edit_toggle.click()
                    page.wait_for_timeout(120)
                    edit_drawer_metrics = page.evaluate(
                        """() => {
                          const root = document.querySelector('#productionModule')?.shadowRoot;
                          const review = root?.querySelector('#page-review.active');
                          const drawer = root?.querySelector('.production-review-side');
                          const active = root?.activeElement;
                          const preview = root?.querySelector('.production-live-preview');
                          return {
                            open: review?.classList.contains('preview-open') === true,
                            editMode: review?.classList.contains('edit-open') === true,
                            drawerVisible: Boolean(drawer && drawer.getBoundingClientRect().width > 0),
                            focusInInspector: Boolean(active && drawer?.querySelector('.inspector')?.contains(active)),
                            previewHidden: Boolean(preview && getComputedStyle(preview).display === 'none'),
                          };
                        }"""
                    )
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(80)
                    edit_closed = page.evaluate(
                        """() => {
                          const root = document.querySelector('#productionModule')?.shadowRoot;
                          return {
                            open: root?.querySelector('#page-review.active')?.classList.contains('preview-open') === true,
                            focusReturned: root?.activeElement === root?.querySelector('[data-production-edit-current]'),
                          };
                        }"""
                    )
                    result["review"]["editDrawer"] = {
                        "open": edit_drawer_metrics,
                        "closed": edit_closed,
                    }
                    if (
                        not edit_drawer_metrics["open"]
                        or not edit_drawer_metrics["editMode"]
                        or not edit_drawer_metrics["drawerVisible"]
                        or not edit_drawer_metrics["focusInInspector"]
                        or not edit_drawer_metrics["previewHidden"]
                        or edit_closed["open"]
                        or not edit_closed["focusReturned"]
                    ):
                        raise RuntimeError(
                            f"mobile edit drawer quality gate failed at {width}x{height}: "
                            f"open={edit_drawer_metrics}, closed={edit_closed}"
                        )

                # Low-frequency controls remain reachable without adding
                # several competing buttons to the top bar.
                more = root_locator(page, ".production-more-actions")
                more.locator(":scope > summary").click()
                menu = more.locator('[role="menu"]')
                if not menu.is_visible() or menu.locator('[role="menuitem"]').count() != 3:
                    raise RuntimeError(f"production more menu unavailable at {width}x{height}")
                more.locator('[data-production-proxy="openTasks"]').click()
                root_locator(page, "#tasksDialog[open]").wait_for(timeout=4_000)
                task_text = root_locator(page, "#tasksDialog[open]").inner_text()
                if re.search(r"(?:^|\s)(?:job|run)-[a-z0-9-]+", task_text, re.IGNORECASE):
                    raise RuntimeError(f"task dialog exposes internal identifiers at {width}x{height}")
                page.keyboard.press("Escape")
                page.wait_for_function(
                    """() => {
                      const root = document.querySelector('#productionModule')?.shadowRoot;
                      return !root?.querySelector('#tasksDialog')?.open;
                    }""",
                    timeout=4_000,
                )
                more.locator(":scope > summary").click()
                more.locator('[data-production-proxy="openSettings"]').click()
                root_locator(page, "#settingsDialog[open]").wait_for(timeout=4_000)
                spine_tab = root_locator(page, '#settingsDialog[open] [data-settings-pane="spine"]')
                spine_tab.click()
                spine_form = root_locator(page, "#settingsDialog[open] #spineForm")
                spine_form.wait_for(timeout=4_000)
                spine_save = root_locator(page, "#settingsDialog[open] #saveSpineCli")
                spine_save_box = spine_save.bounding_box()
                spine_save_style = spine_save.evaluate(
                    "element => ({display: getComputedStyle(element).display, background: getComputedStyle(element).backgroundColor, color: getComputedStyle(element).color})"
                )
                if (
                    not spine_form.is_visible()
                    or not root_locator(page, "#settingsDialog[open] #spineCliPath").is_visible()
                    or not spine_save.is_visible()
                    or not spine_save_box
                    or spine_save_style["display"] == "none"
                    or spine_save_style["background"] in {"rgba(0, 0, 0, 0)", "transparent"}
                ):
                    raise RuntimeError(f"Spine settings form is not usable at {width}x{height}")
                page.keyboard.press("Escape")
                page.wait_for_function(
                    """() => {
                      const root = document.querySelector('#productionModule')?.shadowRoot;
                      return !root?.querySelector('#settingsDialog')?.open;
                    }""",
                    timeout=4_000,
                )
                page.locator('[data-production-proxy="openAssetLibrary"]').click()
                root_locator(page, "#assetLibraryDialog[open]").wait_for(timeout=4_000)
                visible_technical = page.evaluate(
                    """() => {
                      const root = document.querySelector('#productionModule')?.shadowRoot;
                      return [...(root?.querySelectorAll('#assetLibraryDialog[open] .asset-technical-key, #assetLibraryDialog[open] .asset-source') || [])]
                        .filter((element) => {
                          const style = getComputedStyle(element);
                          const box = element.getBoundingClientRect();
                          return !element.hidden && style.display !== 'none' && style.visibility !== 'hidden'
                            && box.width > 0 && box.height > 0;
                        }).map((element) => element.textContent?.trim()).filter(Boolean);
                    }"""
                )
                if visible_technical:
                    raise RuntimeError(f"asset dialog exposes technical labels at {width}x{height}: {visible_technical}")
                background_filters_visible = page.evaluate(
                    """() => {
                      const root = document.querySelector('#productionModule')?.shadowRoot;
                      const filters = root?.querySelector('#assetLibraryDialog[open] .embedded-background-groups');
                      if (!filters) return false;
                      const style = getComputedStyle(filters);
                      const box = filters.getBoundingClientRect();
                      return !filters.hidden && style.display !== 'none' && style.visibility !== 'hidden'
                        && box.width > 0 && box.height > 0;
                    }"""
                )
                if background_filters_visible:
                    raise RuntimeError(f"background filters visible outside background tab at {width}x{height}")
                import_asset = root_locator(page, "#openAssetImport")
                if import_asset.count() == 0:
                    raise RuntimeError(f"asset import entry missing at {width}x{height}")
                import_asset.click()
                root_locator(page, "#assetImportDialog[open]").wait_for(timeout=4_000)
                character_kind = root_locator(page, 'input[name="assetImportKind"][value="character"]')
                character_kind.check()
                spine_toggle = root_locator(page, "#assetImportDialog[open] #renderSpinePreview")
                spine_toggle.wait_for(timeout=4_000)
                if not spine_toggle.is_visible() or spine_toggle.is_checked():
                    raise RuntimeError(f"Spine render opt-in is not visible and unchecked at {width}x{height}")
                import_context = page.evaluate(
                    """() => {
                      const root = document.querySelector('#productionModule')?.shadowRoot;
                      const dialog = root?.querySelector('#assetImportDialog[open]');
                      const shell = dialog?.querySelector('.asset-import-shell');
                      const header = shell?.querySelector(':scope > header');
                      const step = shell?.querySelector('.import-steps [data-import-step=\"1\"]');
                      const fileInput = shell?.querySelector('.import-file input');
                      const identifierInput = shell?.querySelector('#assetCharacterFields input');
                      const footer = shell?.querySelector(':scope > .dialog-footer');
                      const visible = (element) => {
                        if (!element) return false;
                        const box = element.getBoundingClientRect();
                        const style = getComputedStyle(element);
                        const viewport = dialog?.getBoundingClientRect();
                        return style.display !== 'none'
                          && style.visibility !== 'hidden'
                          && box.width > 0
                          && box.height > 0
                          && (!viewport || (box.bottom > viewport.top && box.top < viewport.bottom));
                      };
                      const verticalOverlap = (first, second) => {
                        if (!first || !second) return 0;
                        const horizontal = Math.min(first.right, second.right) - Math.max(first.left, second.left);
                        const vertical = Math.min(first.bottom, second.bottom) - Math.max(first.top, second.top);
                        return horizontal > 0 && vertical > 0 ? vertical : 0;
                      };
                      return {
                        headerVisible: visible(header),
                        firstStepVisible: visible(step),
                        fileInputVisible: visible(fileInput),
                        fileFooterOverlap: verticalOverlap(fileInput?.getBoundingClientRect(), footer?.getBoundingClientRect()),
                        identifierVisible: visible(identifierInput),
                        identifierFooterOverlap: verticalOverlap(identifierInput?.getBoundingClientRect(), footer?.getBoundingClientRect()),
                        scrollTop: shell?.scrollTop || 0,
                      };
                    }"""
                )
                if (
                    not import_context["headerVisible"]
                    or not import_context["firstStepVisible"]
                    or not import_context["fileInputVisible"]
                    or import_context["fileFooterOverlap"] > 0
                    or not import_context["identifierVisible"]
                    or import_context["identifierFooterOverlap"] > 0
                ):
                    raise RuntimeError(
                        f"asset import context scrolled out of view at {width}x{height}: {import_context}"
                    )
                result["asset_import"] = {
                    "spine_render_opt_in_visible": spine_toggle.is_visible(),
                    "spine_render_opt_in_default": spine_toggle.is_checked() is False,
                    "context": import_context,
                }
                asset_import_screenshot = output_dir / f"asset-import-{width}x{height}.png"
                page.screenshot(path=asset_import_screenshot, full_page=False)
                result["asset_import"]["screenshot"] = str(asset_import_screenshot)
                page.keyboard.press("Escape")
                page.wait_for_function(
                    """() => {
                      const root = document.querySelector('#productionModule')?.shadowRoot;
                      return !root?.querySelector('#assetImportDialog')?.open;
                    }""",
                    timeout=4_000,
                )
                page.keyboard.press("Escape")
                page.wait_for_function(
                    """() => {
                      const root = document.querySelector('#productionModule')?.shadowRoot;
                      return !root?.querySelector('#assetLibraryDialog')?.open;
                    }""",
                    timeout=4_000,
                )
                page.evaluate(
                    "document.querySelector('#productionModule')?.shadowRoot?.querySelector('#openRunOverview')?.click()"
                )
                root_locator(page, "#runOverviewDialog[open]").wait_for(timeout=4_000)
                overview_text = root_locator(page, "#runOverviewDialog[open]").inner_text()
                if re.search(r"(?:run|job|build)-[a-z0-9-]+|SHA-?256|最近构建|草稿版本", overview_text, re.IGNORECASE):
                    raise RuntimeError(f"run overview exposes internal identifiers at {width}x{height}")
                page.keyboard.press("Escape")
                page.wait_for_function(
                    """() => {
                      const root = document.querySelector('#productionModule')?.shadowRoot;
                      return !root?.querySelector('#runOverviewDialog')?.open;
                    }""",
                    timeout=4_000,
                )
                preview_toggle = root_locator(page, ".production-preview-toggle")
                if width <= 800 and preview_toggle.is_visible():
                    preview_toggle.click()
                    root_locator(page, ".production-review-side").wait_for(timeout=4_000)
                    drawer_state = page.evaluate(
                        """() => {
                          const root = document.querySelector('#productionModule')?.shadowRoot;
                          const drawer = root?.querySelector('.production-review-side');
                          const active = root?.activeElement;
                          const suppressed = [...(root?.querySelectorAll('[aria-hidden="true"], [inert]') || [])]
                            .filter(element => element.matches('.review-head, .production-background-timeline, .review-column, .buildbar'));
                          return {
                            open: root?.querySelector('#page-review.active')?.classList.contains('preview-open') === true,
                            drawerVisible: Boolean(drawer && drawer.getBoundingClientRect().width > 0),
                            focusInDrawer: Boolean(active && drawer?.contains(active)),
                            suppressedCount: suppressed.length,
                          };
                        }"""
                    )
                    page.keyboard.press("Escape")
                    closed_state = page.evaluate(
                        """() => {
                          const root = document.querySelector('#productionModule')?.shadowRoot;
                          const toggle = root?.querySelector('.production-preview-toggle');
                          return {
                            open: root?.querySelector('#page-review.active')?.classList.contains('preview-open') === true,
                            focusReturned: root?.activeElement === toggle,
                          };
                        }"""
                    )
                    result["review"]["drawer"] = {"open": drawer_state, "closed": closed_state}
                    if (
                        not drawer_state["open"]
                        or not drawer_state["drawerVisible"]
                        or not drawer_state["focusInDrawer"]
                        or drawer_state["suppressedCount"] < 3
                        or closed_state["open"]
                        or not closed_state["focusReturned"]
                    ):
                        raise RuntimeError(
                            f"review drawer quality gate failed at {width}x{height}: "
                            f"open={drawer_state}, closed={closed_state}"
                        )
                results.append(result)
                page.close()
        finally:
            browser.close()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8926")
    parser.add_argument("--run-project", default=None)
    parser.add_argument("--output", type=Path, default=Path(".scratch/quality-regression/report"))
    args = parser.parse_args()
    try:
        health = assert_health(args.base_url)
        production_evidence = collect_production_evidence(args.base_url, args.run_project)
        boundaries = browser_boundary_quality(args.base_url, args.output / "browser")
        browser = browser_quality(args.base_url, args.output / "browser", args.run_project)
    except (RuntimeError, OSError) as exc:
        print(f"QUALITY REGRESSION FAILED: {exc}", file=sys.stderr)
        return 1
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "health": health,
        "production_evidence": production_evidence,
        "boundaries": boundaries,
        "browser": browser,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"ok": True, "viewports": len(browser), "boundaries": len(boundaries), "report": str(args.output / 'report.json')}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
