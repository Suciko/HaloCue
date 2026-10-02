"""Production source workspace layout under actual CSS and synthetic UI state."""

import os
import re
from pathlib import Path

import pytest


@pytest.mark.parametrize("width,height", [(1440, 960), (430, 932)])
def test_production_workspace_polish(width, height):
    pw = pytest.importorskip("playwright.sync_api")
    ui = Path(__file__).resolve().parents[1] / "ui"
    html = (ui / "index.html").read_text(encoding="utf-8")
    links = re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<link\b[^>]*>", "", html, flags=re.I)
    css = "\n".join((ui / name.split("?")[0]).read_text(encoding="utf-8") for name in links)
    with pw.sync_playwright() as p:
        if Path(p.chromium.executable_path).exists():
            browser = p.chromium.launch(headless=True)
        elif Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe").exists():
            browser = p.chromium.launch(channel="msedge", headless=True)
        else:
            pytest.skip("Chromium or Edge required")
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.route("**/*", lambda route: route.abort())
            page.set_content(html)
            page.add_style_tag(content=css)
            page.evaluate("""() => {
              document.getElementById('serviceState').textContent='示例工作区';
              document.getElementById('writingReleasesGrid').innerHTML='<p class="empty">还没有制作定稿。你可以先写一个故事，或从本机导入已有剧本。</p>';
            }""")
            overflow = page.evaluate("document.documentElement.scrollWidth - innerWidth")
            assert overflow <= 2
            assert page.locator("#page-source").is_visible()
            assert page.locator("#pageTitle").is_visible()
            if os.environ.get("HALOCUE_UI_SHOTS"):
                directory = Path(os.environ["HALOCUE_UI_SHOTS"])
                directory.mkdir(exist_ok=True, parents=True)
                page.screenshot(path=str(directory / f"production-{width}.png"))
        finally:
            browser.close()
