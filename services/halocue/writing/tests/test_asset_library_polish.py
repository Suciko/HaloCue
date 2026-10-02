from pathlib import Path
import pytest
from playwright.sync_api import expect

WEB = Path(__file__).resolve().parents[1] / "web"


@pytest.mark.parametrize(
    "width,theme", [(1280, "light"), (1280, "dark"), (390, "light"), (390, "dark")]
)
def test_asset_cards_have_truthful_preview_and_explicit_use_target(width, theme):
    source = (WEB / "app.js").read_text(encoding="utf8")
    helpers = source[
        source.index("const ASSET_CATALOG_KINDS=") : source.index(
            "document.addEventListener('error',event=>{", source.index("function assetCatalogCard(")
        )
    ]
    with pytest.importorskip("playwright.sync_api").sync_playwright() as d:
        browser = d.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": 844})
            page.route(
                "**/production/**", lambda route: route.fulfill(status=404, body="Unavailable")
            )
            page.set_content(
                f'<html data-theme="{theme}"><div id="app" class="hc-redesign" data-surface="assets"><main class="asset-catalog-workbench"><div class="asset-catalog-grid"></div></main></div></html>'
            )
            for name in [
                "styles.css",
                "tokens.css",
                "shell.css",
                "redesign.css",
                "theme.css",
                "authoring-ui.css",
            ]:
                page.add_style_tag(content=(WEB / name).read_text(encoding="utf8"))
            page.add_style_tag(
                content="#app#app{display:block!important;width:100%!important;height:auto!important}"
            )
            page.add_script_tag(
                content="""
                const esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
            """
                + helpers
                + """
                document.querySelector('.asset-catalog-grid').innerHTML=
                  assetCatalogCard({name:'本机角色包',source:'custom_library',asset_id:'library-asset-111111111111',metadata:{faces:[],semantic_face_count:44,spine_version:'3.8.76'}},'characters')+
                  assetCatalogCard({name:'未安装的背景',source:'resource_index',key:'bg-key',preview_available:false},'backgrounds')+
                  assetCatalogCard({name:'已有背景',source:'resource_index',key:'bg-ready',preview_available:true},'backgrounds')+
                  assetCatalogCard({name:'手工标注背景',source:'custom_library',asset_id:'library-asset-222222222222',labels:{place:'手工地点',time:'夜晚',scene_type:'AI 场景',time_of_day:'黄昏'}},'backgrounds');
            """
            )
            cards = page.locator(".asset-catalog-card")
            expect(cards.nth(0).get_by_text("包内图片 · 非动画预览")).to_be_visible()
            expect(cards.nth(0).get_by_role("button", name="查看包内图片")).to_be_visible()
            expect(cards.nth(0).get_by_role("button", name="用于制作…")).to_be_visible()
            expect(cards.nth(0)).to_contain_text("44 个可解析表情组合（未渲染）")
            expect(cards.nth(1).locator("[data-asset-preview]")).to_have_count(0)
            expect(cards.nth(1).get_by_text("暂无本地预览")).to_be_visible()
            expect(cards.nth(2).get_by_role("button", name="预览")).to_be_visible()
            expect(cards.nth(2).locator(".asset-card-visual img")).to_have_attribute(
                "src", "/production/api/v1/resources/backgrounds/bg-ready/preview"
            )
            expect(cards.nth(3)).to_contain_text("手工地点 · 夜晚")
            assert not page.evaluate("document.documentElement.scrollWidth>innerWidth")
        finally:
            browser.close()


@pytest.mark.parametrize("width", [1280, 390])
def test_asset_upload_dialog_uses_dark_theme_in_header_and_review(width):
    source = (WEB / "app.js").read_text(encoding="utf8")
    helper = source[
        source.index("function ensureCustomAssetUploadDialog(") : source.index(
            "function customAssetValidationMeta("
        )
    ]
    with pytest.importorskip("playwright.sync_api").sync_playwright() as driver:
        browser = driver.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": 844})
            page.set_content('<html data-theme="dark"><body></body></html>')
            for name in ["styles.css", "tokens.css", "shell.css", "theme.css", "authoring-ui.css"]:
                page.add_style_tag(content=(WEB / name).read_text(encoding="utf8"))
            page.add_script_tag(
                content="const $=q=>document.querySelector(q);"
                + helper
                + "const dialog=ensureCustomAssetUploadDialog();dialog.showModal();"
                + "const review=dialog.querySelector('.custom-asset-review');"
                + "review.hidden=false;review.innerHTML='<header><div><h3>格式检查通过</h3></div></header>';"
            )
            colors = page.locator("#customAssetUploadDialog").evaluate(
                """e=>({
                  headerBg:getComputedStyle(e.querySelector('.dialog-head')).backgroundColor,
                  headerText:getComputedStyle(e.querySelector('.dialog-head h2')).color,
                  reviewBg:getComputedStyle(e.querySelector('.custom-asset-review')).backgroundColor,
                  reviewText:getComputedStyle(e.querySelector('.custom-asset-review h3')).color,
                })"""
            )
            values = {key: [int(n) for n in value[4:-1].split(",")[:3]] for key, value in colors.items()}
            assert max(values["headerBg"]) < 90 and max(values["reviewBg"]) < 90
            assert min(values["headerText"]) > 150 and min(values["reviewText"]) > 150
            assert not page.evaluate("document.documentElement.scrollWidth>innerWidth")
        finally:
            browser.close()


def test_upload_dialog_restores_submit_button_for_second_asset():
    source = (WEB / "app.js").read_text(encoding="utf8")
    helper = source[
        source.index("function ensureCustomAssetUploadDialog(") : source.index(
            "function ensureCustomAssetEditDialog("
        )
    ]
    with pytest.importorskip("playwright.sync_api").sync_playwright() as driver:
        browser = driver.chromium.launch()
        try:
            page = browser.new_page()
            page.add_script_tag(
                content="""
                const $=s=>document.querySelector(s),esc=x=>x;
                const state={assetUpload:null,assetCatalog:{kind:'characters'}};
                const ASSET_CATALOG_KINDS={characters:{customKind:'character'}};
                """
                + helper
                + "openCustomAssetUpload();"
            )
            submit = page.get_by_role("button", name="上传并检查")
            expect(submit).to_be_visible()
            expect(page.get_by_label("显示名称")).to_be_hidden()
            expect(page.get_by_label("学院 / 社团")).to_be_hidden()
            page.evaluate("document.querySelector('#customAssetUploadDialog button[type=submit]').hidden=true")
            page.evaluate("document.querySelector('#customAssetUploadDialog').close()")
            page.evaluate("openCustomAssetUpload()")
            expect(submit).to_be_visible()
            page.evaluate("state.assetUpload={validation:{ok:true}};syncCustomAssetFields(document.querySelector('[data-custom-asset-upload-form]'))")
            expect(page.locator(".custom-asset-meta-details")).to_be_visible()
            page.locator(".custom-asset-meta-details > summary").click()
            expect(page.get_by_label("学院 / 社团")).to_be_visible()
            expect(page.get_by_label("素材备注")).to_be_visible()
        finally:
            browser.close()


def test_attach_dialog_requires_explicit_project_choice():
    source = (WEB / "app.js").read_text(encoding="utf8")
    helper = source[
        source.index("function ensureCustomAssetAttachDialog(") : source.index(
            "/* Root rendering is owned", source.index("function ensureCustomAssetAttachDialog(")
        )
    ]
    with pytest.importorskip("playwright.sync_api").sync_playwright() as d:
        browser = d.chromium.launch()
        try:
            page = browser.new_page()
            page.add_script_tag(
                content="""
              const $=s=>document.querySelector(s),esc=x=>x;
              const productionJson=async()=>({items:[{run_id:'run-1',project:'第一部作品',state:'draft'},{run_id:'run-2',project:'第二部作品',state:'draft'}]});
            """
                + helper
                + "openCustomAssetAttach('asset-1');"
            )
            select = page.get_by_role("combobox", name="制作项目")
            expect(select).to_have_value("")
            assert select.evaluate("e=>e.validity.valueMissing")
            select.select_option("run-2")
            assert select.evaluate("e=>e.checkValidity()")
            expect(
                page.get_by_text("确认后将素材复制到所选制作项目；素材库原件保持不变。")
            ).to_be_visible()
        finally:
            browser.close()
