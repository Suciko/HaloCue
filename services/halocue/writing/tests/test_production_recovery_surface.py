"""The recovery view must work before upstream styles or scripts can load."""

from pathlib import Path
import pytest
from playwright.sync_api import expect

WEB = Path(__file__).resolve().parents[1] / "web"


@pytest.mark.parametrize("width", [1280, 390])
def test_missing_production_service_has_styled_recovery_and_working_exits(width):
    source = (WEB / "production-embed.js").read_text(encoding="utf8")
    helpers = source[
        source.index("  function ensureProductionRecoveryStyle(") : source.index(
            "  async function loadProductionSurface("
        )
    ]
    with pytest.importorskip("playwright.sync_api").sync_playwright() as driver:
        browser = driver.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": 844})
            page.set_content(
                '<div id="productionModule"></div><button id="openSettingsButton">设置</button><button id="settingsTab-aa">环境</button>'
            )
            page.add_script_tag(
                content="""
              const host=()=>document.querySelector('#productionModule'),root=host().attachShadow({mode:'open'});
              const escapeHtml=x=>String(x).replaceAll('&','&amp;').replaceAll('<','&lt;');
              let retries=0,settings=0,environment=0,routes=[];
              window.HaloCueRouter={navigate:x=>routes.push(x)};
              document.querySelector('#openSettingsButton').onclick=()=>settings++;
              document.querySelector('#settingsTab-aa').onclick=()=>environment++;
            """
                + helpers
                + "setProductionSurfaceState(root,'error',{detail:'服务响应 503 <img src=x>',onRetry:()=>retries++});"
            )
            expect(page.get_by_text("作品和正文仍保留", exact=False)).to_be_visible()
            expect(page.locator(".production-surface-state img")).to_have_count(0)
            assert (
                page.locator(".production-surface-state-card").evaluate(
                    "e=>getComputedStyle(e).borderRadius"
                )
                == "14px"
            )
            page.get_by_role("button", name="检查制作环境").click()
            assert page.evaluate("[settings,environment]") == [1, 1]
            page.get_by_role("button", name="返回写作").click()
            assert page.evaluate("routes[0].section") == "writing"
            page.get_by_role("button", name="重试", exact=True).click()
            assert page.evaluate("retries") == 1
            page.evaluate(
                "setProductionSurfaceState(root,'loading');setProductionSurfaceState(root,'ready');"
            )
            expect(page.locator(".production-surface-state")).to_be_hidden()
            expect(page.locator("[data-production-recovery-style]")).to_have_count(1)
            assert not page.evaluate("document.documentElement.scrollWidth>innerWidth")
        finally:
            browser.close()
