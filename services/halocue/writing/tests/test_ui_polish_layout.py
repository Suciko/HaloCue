"""Visual/layout regression with production CSS and synthetic controller state."""

import os
import re
from pathlib import Path

import pytest


@pytest.mark.parametrize("viewport", [(1440, 960), (430, 932), (375, 812)])
def test_settings_polish_layout(viewport):
    pw = pytest.importorskip("playwright.sync_api")
    web = Path(__file__).resolve().parents[1] / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<link\b[^>]*>", "", html, flags=re.I)
    source = (web / "app.js").read_text(encoding="utf-8")
    start = source.index("const SettingsController =")
    script = source[start : source.index("\n};", start) + 3]
    styles = "\n".join(
        (web / f).read_text(encoding="utf-8")
        for f in [
            "styles.css",
            "tokens.css",
            "shell.css",
            "writing-workbench.css",
            "production-embed.css",
        ]
    )
    with pw.sync_playwright() as p:
        if Path(p.chromium.executable_path).exists():
            browser = p.chromium.launch(headless=True)
        elif Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe").exists():
            browser = p.chromium.launch(channel="msedge", headless=True)
        else:
            pytest.skip("Chromium or Edge required")
        try:
            page = browser.new_page(
                viewport={"width": viewport[0], "height": viewport[1]}, reduced_motion="reduce"
            )
            page.route("**/*", lambda route: route.abort())
            page.set_content(html)
            page.add_style_tag(content=styles)
            page.add_script_tag(
                content="""
              window.api = async () => ({}); window.toast = () => {}; window.state = {};
              window.esc = s => { const n = document.createElement('span'); n.textContent = String(s ?? ''); return n.innerHTML; };
            """
                + script
                + "\nwindow.c = SettingsController;"
            )
            page.evaluate("""() => {
              document.body.classList.remove('app-loading'); document.getElementById('bootScreen')?.remove();
              const writing = {configured: true, provider:'openai', model:'我的写作模型', base_url:'https://writer.example.invalid/v1', activation_status:'active', secret_source:'dpapi'};
              const direction = {configured:true, provider:'openai', model:'本地演出模型', base_url:'http://localhost:11434/v1', activation_status:'saved_unverified', secret_source:'none'};
              c.init(); c.renderModelSettings({model:writing, presets:[]}); c.renderModelRoles({model:writing}, {model:direction}); c.dialog.showModal();
            }""")
            contrast = page.evaluate(r"""() => {
              const luminance = color => {
                const rgb = color.match(/[\d.]+/g).slice(0,3).map(Number).map(c => c/255);
                const [r,g,b] = rgb.map(c => c <= .04045 ? c/12.92 : ((c+.055)/1.055)**2.4);
                return .2126*r+.7152*g+.0722*b;
              };
              return ['writingModelRoleState','directionModelRoleState','writingModelRoleEndpoint','directionModelRoleEndpoint'].map(id => {
                const node = document.getElementById(id);
                const fg = luminance(getComputedStyle(node).color);
                const bg = luminance(getComputedStyle(node.closest('.model-role-card')).backgroundColor);
                return (Math.max(fg,bg)+.05)/(Math.min(fg,bg)+.05);
              });
            }""")
            assert min(contrast) >= 4.5, contrast
            if viewport[0] <= 760:
                assert page.locator(".settings-nav").bounding_box()["height"] <= 72
            for view in ["roles", "form", "aa", "preferences"]:
                if view == "form":
                    page.locator("#modelConfigDetails > summary").click()
                elif view == "aa":
                    page.locator('[data-tab="aa"]').click()
                elif view == "preferences":
                    page.locator('[data-tab="preferences"]').click()
                    assert page.locator("#savePreferencesBtn").is_disabled()
                page.evaluate("document.querySelector('.settings-content').scrollTop = 0")
                result = page.locator("#settingsDialog").evaluate("""node => ({
                  overflow: node.scrollWidth - node.clientWidth,
                  left:node.getBoundingClientRect().left, right:node.getBoundingClientRect().right,
                  contentOverflow:node.querySelector('.settings-content').scrollWidth - node.querySelector('.settings-content').clientWidth
                })""")
                assert result["overflow"] <= 2 and result["contentOverflow"] <= 2, (
                    viewport,
                    view,
                    result,
                )
                assert result["left"] >= 0 and result["right"] <= viewport[0], (
                    viewport,
                    view,
                    result,
                )
                if os.environ.get("HALOCUE_UI_SHOTS"):
                    directory = Path(os.environ["HALOCUE_UI_SHOTS"])
                    directory.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(directory / f"settings-{viewport[0]}-{view}.png"))
        finally:
            browser.close()
