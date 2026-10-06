"""Real embedded AA list paging, selection and dialog hit areas at 16:9."""

import json
import pytest


@pytest.mark.parametrize("size", [(1280, 720), (1600, 900), (1920, 1080)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_material_workbench_has_one_paged_list_and_clickable_header(runtime, tmp_path, size, theme):
    pw = pytest.importorskip("playwright.sync_api")
    index = {
        "bg": {f"BG_Test{i:03}": f"hash{i}" for i in range(85)},
        "scene_labels": {
            "background": {
                f"bg_test{i:03}": {
                    "label": f"测试背景{i:03}",
                    "place": f"房间{i:03}",
                    "category_path_cn": "室内 / 房间",
                }
                for i in range(85)
            }
        },
        "characters": [
            {"identifier": "ako", "name": "亞子", "spine": "CharacterSpine_ako", "faces": ["00"]}
        ],
        "sounds": ["test-sound"],
        "popups": ["test-popup"],
    }
    index["bg"].update({f"BG_CS_Test{i:03}": f"cg-hash{i}" for i in range(85)})
    index["bg_label"] = {f"BG_CS_Test{i:03}": f"CG测试画面{i:03}" for i in range(85)}
    runtime.production_service.settings.resource_index.write_text(
        json.dumps(index), encoding="utf-8"
    )
    result = runtime.production_service.create_run(
        {
            "project": "素材回归",
            "auto_match_resources": True,
            "source": {"kind": "inline", "text": "## 房间000\n亚子：你好。"},
        }
    )
    assert result["draft"]["cast"]["cast"]["亚子"]["id"] == "ako"
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": size[0], "height": size[1]})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(f"localStorage.setItem('halocue.ui.theme','{theme}')")
            page.goto(
                f"http://127.0.0.1:{runtime.port}/?section=production&run_id={result['run']['run_id']}",
                wait_until="networkidle",
            )
            page.get_by_role("button", name="角色与素材，已完成，点击进入", exact=True).click()
            pw.expect(page.locator("#mappingScenePlan")).to_contain_text("测试背景000")
            page.reload(wait_until="networkidle")
            page.get_by_role("button", name="角色与素材，已完成，点击进入", exact=True).click()
            pw.expect(page.locator("#mappingScenePlan")).to_contain_text("测试背景000")
            page.get_by_role("button", name="制作素材", exact=True).click()
            page.get_by_role("button", name="背景", exact=True).click()
            active_color = page.locator(".asset-tabs button.active").evaluate(
                "el => getComputedStyle(el).backgroundColor"
            )
            other_color = page.locator(".asset-tabs button:not(.active)").first.evaluate(
                "el => getComputedStyle(el).backgroundColor"
            )
            assert active_color != other_color, (theme, active_color, other_color)
            items = page.locator("#assetLibraryResults .asset-library-item")
            pw.expect(items).to_have_count(36)
            pw.expect(page.locator("#assetLibraryResults")).to_contain_text("测试背景000")
            items.first.click()
            pw.expect(page.locator("#assetWorkbenchDetail")).to_contain_text("测试背景000")
            header = page.locator("#assetWorkbenchDetail > header").evaluate("""el => {
                const title = el.querySelector('h4').getBoundingClientRect();
                const source = el.querySelector('span').getBoundingClientRect();
                return {titleTop:title.top,sourceBottom:source.bottom};
            }""")
            assert header["titleTop"] >= header["sourceBottom"], header
            items.first.press("End")
            pw.expect(items).to_have_count(72)
            page.locator('[data-asset-key="BG_Test060"]').click()
            pw.expect(page.locator("#assetWorkbenchDetail")).to_contain_text("测试背景060")
            boxes = page.locator("#assetLibraryDialog").evaluate("""el => {
                const rect = el.getBoundingClientRect();
                const list = el.querySelector('#assetLibraryResults');
                const button = el.querySelector('header [data-close-dialog]');
                const hit = button.getBoundingClientRect();
                const target = el.getRootNode().elementFromPoint(hit.x+hit.width/2, hit.y+hit.height/2);
                return {x:rect.x,y:rect.y,right:rect.right,bottom:rect.bottom,
                    overflow:el.scrollHeight-el.clientHeight, listWidth:list.clientWidth,
                    buttonY:hit.y,hit:button.contains(target)};
            }""")
            assert boxes["x"] >= 0 and boxes["right"] <= size[0] + 1, boxes
            assert boxes["bottom"] <= size[1] - 16 and boxes["overflow"] <= 1, boxes
            assert boxes["buttonY"] > 56 and boxes["hit"] and boxes["listWidth"] > 300, boxes
            search = page.locator("#assetLibrarySearch")
            search.fill("测试背景084")
            pw.expect(items).to_have_count(1)
            pw.expect(items).to_contain_text("测试背景084")
            # The header action must open the actual importer, not the image behind it.
            page.get_by_role("button", name="导入素材", exact=True).click()
            pw.expect(page.locator("#assetImportDialog")).to_be_visible()
            page.locator("#assetImportDialog [data-close-dialog]").click()
            pw.expect(page.locator("#assetLibraryDialog")).to_be_visible()
            page.get_by_role("button", name="音效", exact=True).click()
            page.get_by_role("button", name="角色骨骼", exact=True).click()
            search.fill("亚子")
            pw.expect(items).to_have_count(1)
            pw.expect(items).to_contain_text("亞子")
            page.get_by_role("button", name="返回任务", exact=True).click()
            pw.expect(page.locator("#assetLibraryDialog")).not_to_be_visible()
            page.get_by_role("button", name="审查与安装，可进入，点击进入", exact=True).click()
            page.get_by_role("button", name="插入演出", exact=True).click()
            page.locator("#insertCmd").select_option("wait")
            page.locator("#insertArg").fill("800")
            page.get_by_role("button", name="插入卡片", exact=True).click()
            pw.expect(page.locator("#selectedCardToolbar")).to_contain_text("停顿")
            pw.expect(page.locator("#backgroundTimelineTrack")).to_contain_text("测试背景000")
            page.get_by_text("更多工具", exact=True).click()
            page.get_by_role("button", name="插入 CG 段落", exact=True).click()
            cg_items = page.locator("#cgResults [data-cg-key]")
            pw.expect(cg_items).to_have_count(36)
            cg_items.first.press("End")
            pw.expect(cg_items).to_have_count(72)
            page.locator("#cgSearch").fill("CG测试画面084")
            pw.expect(cg_items).to_have_count(1)
            cg_items.click()
            pw.expect(page.locator("#cgSelectedMaterial")).to_have_text("CG测试画面084")
            line_id = next(
                card["card_id"] for card in result["draft"]["cards"] if card["kind"] == "line"
            )
            page.locator("#cgStartCard").select_option(line_id)
            page.locator("#cgEndCard").select_option(line_id)
            page.locator("#cgLabel").fill("CG 昼夜主题验收")
            page.locator("#createCgSegment").click()
            page.locator(f'[data-card-id="{line_id}"]').click()
            pw.expect(page.locator(".cg-inspector")).to_contain_text("CG 昼夜主题验收")
            # Fixed pale CG surfaces used white host text in dark mode.
            for selector in (".cg-badge", ".cg-inspector"):
                colors = page.locator(selector).evaluate("""el => {
                    const style = getComputedStyle(el);
                    const channel = value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
                    const luminance = color => color.match(/[\\d.]+/g).slice(0, 3).map(Number)
                        .map(value => channel(value/255)).reduce((sum,value,index) => sum+value*[.2126,.7152,.0722][index],0);
                    const a=luminance(style.color), b=luminance(style.backgroundColor);
                    return {ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05),background:style.backgroundColor};
                }""")
                assert colors["ratio"] >= 4.5, (theme, selector, colors)
            assert not errors
        finally:
            browser.close()
