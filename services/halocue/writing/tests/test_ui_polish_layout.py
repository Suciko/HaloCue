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
                    page.locator('[data-tab="about"]').click()
                    page.locator('[data-settings-pane="preferences"]').click()
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

@pytest.mark.parametrize("viewport", [(1440, 900), (390, 844)])
def test_dark_next_action_has_dark_surface_and_readable_text(viewport):
    """Use every production stylesheet in its real load order."""
    pw = pytest.importorskip("playwright.sync_api")
    web = Path(__file__).resolve().parents[1] / "web"
    source = (web / "index.html").read_text(encoding="utf8")
    styles = "\n".join(
        (web / name.split("?")[0].lstrip("/")).read_text(encoding="utf8")
        for name in re.findall(r'<link rel="stylesheet" href="([^"]+)"', source)
    )
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            page.set_content('''<html data-theme="dark"><body>
              <div id="app" class="hc-redesign work-agent-stage" data-surface="works">
                <section class="work-user-status"><div class="work-user-status-copy">
                  <p class="eyebrow">当前下一步</p><h3>审查正文候选</h3>
                  <p>确认后才会改动作品。</p></div><button class="primary">查看候选</button>
                </section></div></body></html>''')
            page.add_style_tag(content=styles)
            colors = page.locator(".work-user-status").evaluate('''node => {
              const rgb = value => value.match(/[\\d.]+/g).slice(0,3).map(Number);
              return {background:rgb(getComputedStyle(node).backgroundColor),
                title:rgb(getComputedStyle(node.querySelector('h3')).color),
                detail:rgb(getComputedStyle(node.querySelector('.work-user-status-copy > p:last-child')).color)};
            }''')
            def luminance(rgb):
                values = [v / 255 for v in rgb]
                values = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
                return sum(v * weight for v, weight in zip(values, (0.2126, 0.7152, 0.0722)))
            background = luminance(colors["background"])
            assert background < 0.15, colors
            for key in ("title", "detail"):
                foreground = luminance(colors[key])
                assert (max(foreground, background) + 0.05) / (min(foreground, background) + 0.05) >= 4.5, colors
        finally:
            browser.close()

def test_project_home_typography_uses_one_ui_font():
    """The redesigned project home must not leak legacy mono/serif UI typography."""
    pw = pytest.importorskip("playwright.sync_api")
    web = Path(__file__).resolve().parents[1] / "web"
    source = (web / "index.html").read_text(encoding="utf-8")
    styles = "\n".join(
        (web / name.split("?")[0].lstrip("/")).read_text(encoding="utf-8")
        for name in re.findall(r'<link rel="stylesheet" href="([^"]+)"', source)
    )
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.set_content("""
              <html><body>
                <div id="app" class="app-shell hc-redesign" data-surface="projects">
                  <nav class="primary-nav"><button class="nav-item">作品</button></nav>
                  <nav class="crumb">我的作品</nav>
                  <main id="workspace"><section class="project-home">
                    <header class="project-home-heading">
                      <div><p class="eyebrow">创作空间</p><h1>我的作品</h1><p>每个故事都有自己的构思、正文和设定。</p></div>
                      <button class="primary">新建作品</button>
                    </header>
                    <div class="project-home-toolbar"><h2>作品 <span>0</span></h2><button class="quiet">刷新列表</button></div>
                    <div class="project-home-empty"><h2>从你的第一个故事开始</h2><p>可以先整理世界底稿。</p></div>
                  </section></main>
                </div>
              </body></html>
            """)
            page.add_style_tag(content=styles)
            fonts = page.locator(
                "#app .project-home-heading .eyebrow, #app .project-home-heading h1, "
                "#app .project-home-toolbar h2, #app .project-home-empty h2, "
                "#app .project-home button, #app .crumb, #app .nav-item"
            ).evaluate_all("nodes => nodes.map(node => getComputedStyle(node).fontFamily)")
            assert len(set(fonts)) == 1, fonts
            assert "Consolas" not in fonts[0], fonts
            assert "Noto Sans SC" in fonts[0], fonts
        finally:
            browser.close()

def test_redesigned_example_surfaces_use_shared_ui_font():
    """Empty states and sidebar examples must not fall back to legacy typography."""
    pw = pytest.importorskip("playwright.sync_api")
    web = Path(__file__).resolve().parents[1] / "web"
    source = (web / "index.html").read_text(encoding="utf-8")
    styles = "\n".join(
        (web / name.split("?")[0].lstrip("/")).read_text(encoding="utf-8")
        for name in re.findall(r'<link rel="stylesheet" href="([^"]+)"', source)
    )
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.set_content("""
              <html><body>
                <div id="app" class="app-shell hc-redesign" data-surface="works">
                  <aside class="tree-panel">
                    <div class="panel-heading"><p>当前作品</p></div>
                    <section class="work-surface-note"><p>作品栏目</p></section>
                    <ol class="stage-list"><li><button><span>01</span></button></li></ol>
                  </aside>
                  <main id="workspace">
                    <section class="intent-start intent-start-quiet">
                      <div class="intent-start-copy"><p class="eyebrow">构思</p><h2>从一个想法开始</h2><p>可以先说说想写什么。</p></div>
                    </section>
                  </main>
                </div>
              </body></html>
            """)
            page.add_style_tag(content=styles)
            fonts = page.locator(
                "#app .panel-heading p, #app .work-surface-note p, #app .stage-list span, "
                "#app .intent-start .eyebrow, #app .intent-start h2, #app .intent-start p"
            ).evaluate_all("nodes => nodes.map(node => getComputedStyle(node).fontFamily)")
            assert len(set(fonts)) == 1, fonts
            assert "Consolas" not in fonts[0], fonts
            assert "Noto Serif" not in fonts[0], fonts
        finally:
            browser.close()
