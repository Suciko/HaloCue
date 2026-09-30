"""Reference cards expose their preserved full profile without pretending provenance is verified."""

from pathlib import Path
import json
import pytest
from playwright.sync_api import expect

WEB = Path(__file__).resolve().parents[1] / "web"


@pytest.mark.parametrize("width,theme", [(1280, "light"), (1280, "dark"), (390, "dark")])
def test_full_reference_profile_is_readable_and_escaped(width, theme):
    source = (WEB / "app.js").read_text(encoding="utf8")
    helper = source[
        source.index("function characterProfileValueMarkup(") : source.index(
            "function decorateLibrary("
        )
    ]
    card = {
        "source_refs": ["本地整理，非官方发行人物卡"],
        "validation_report": {"status": "PASS"},
        "ba_profile": {
            "note": "样本仅覆盖部分剧情",
            "core": "<img src=x onerror=alert(1)>",
            "speech": {
                "voice_examples": [
                    {
                        "line": "原文示例",
                        "source_id": "123",
                        "source_title": "合成测试章节",
                        "evidence_status": "external_unverified",
                    }
                ]
            },
        },
    }
    with pytest.importorskip("playwright.sync_api").sync_playwright() as d:
        browser = d.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": 844})
            page.set_content(
                f'<html data-theme="{theme}"><div id="app" class="hc-redesign" data-surface="references"><main></main></div></html>'
            )
            for name in ["tokens.css", "theme.css", "authoring-ui.css"]:
                page.add_style_tag(content=(WEB / name).read_text(encoding="utf8"))
            page.add_script_tag(
                content="const esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('\"','&quot;');"
                + helper
                + 'document.querySelector("main").innerHTML=characterReferenceDetailsMarkup('
                + json.dumps(card, ensure_ascii=False)
                + ");"
            )
            expect(page.get_by_text("完整参考档案", exact=True)).to_be_visible()
            expect(page.locator("img")).to_have_count(0)
            page.locator("summary").filter(has_text="来源与校验说明").click()
            expect(page.get_by_text("本地整理，非官方发行人物卡", exact=True)).to_be_visible()
            page.locator("summary").filter(has_text="说话方式与原文样本").click()
            expect(page.get_by_text("原文示例", exact=True)).to_be_visible()
            expect(page.get_by_text("external_unverified", exact=True)).to_be_visible()
            assert not page.evaluate("document.documentElement.scrollWidth>innerWidth")
        finally:
            browser.close()
