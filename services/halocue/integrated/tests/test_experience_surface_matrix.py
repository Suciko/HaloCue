"""Deterministic cross-surface layouts with temporary works and production runs."""

import re

import pytest


SIZES = [(1440, 900), (1280, 800), (1024, 768), (820, 520), (390, 844)]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_support_surfaces_settings_and_populated_production_fit(runtime, tmp_path, theme):
    pw = pytest.importorskip("playwright.sync_api")
    work = runtime.writing_service.create_work({"title": "布局回归 · 一个比较长的作品标题"})
    ready = runtime.production_service.create_run({
        "project": "审查布局 · 合成旁白稿",
        "source": {"kind": "inline", "text": "旁白: 灯光落在桌面上。\n旁白: 门外传来脚步声。\n"},
    })
    ready = runtime.production_service.update_cast(ready["run"]["run_id"], {
        "speaker": "旁白", "mapping": {"kind": "narrator"},
        "expected_draft_version": ready["draft"]["draft_version"],
    })
    mapping = runtime.production_service.create_run({
        "project": "素材缺口 · 未映射人物",
        "source": {"kind": "inline", "text": "角色甲: 这是一段没有立绘映射的合成对白。\n"},
    })
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        origin = f"http://127.0.0.1:{runtime.port}"
        page.goto(origin, wait_until="networkidle")
        page.locator("#openSettingsButton").click()
        page.get_by_role("tab", name="外观", exact=True).click()
        page.locator(f'[data-theme-choice="{theme}"]').click()
        page.keyboard.press("Escape")
        scenarios = [
            ("activity", f"/?section=tasks&work_id={work['id']}", ".activity-toolbar"),
            ("assets", f"/?section=assets&work_id={work['id']}", ".asset-catalog"),
            ("mapping", f"/?section=production&run_id={mapping['run']['run_id']}", "#page-mapping.active"),
            ("review", f"/?section=production&run_id={ready['run']['run_id']}", "#page-review.active"),
        ]
        try:
            for name, url, selector in scenarios:
                page.goto(origin + url, wait_until="networkidle")
                if name == "assets":
                    pw.expect(page.get_by_role("heading", name="素材库", exact=True)).to_be_visible()
                else:
                    pw.expect(page.locator(selector)).to_be_visible(timeout=15000)
                if name == "review":
                    page.locator(".production-release-checklist summary").click()
                    pw.expect(page.locator(".production-gate-columns")).to_contain_text("仍有卡片等待审查")
                    pw.expect(page.locator(".production-gate-columns")).to_contain_text("尚未生成可安装构建")
                    pw.expect(page.locator(".production-gate-columns")).to_contain_text("AA 工作区尚未配置")
                    page.locator('.production-review-next [data-review-next="pending"]').click()
                    pw.expect(page.locator("#cardList .selected")).to_be_focused()
                    pw.expect(page.locator(".production-release-checklist")).to_have_attribute("open", "")
                    page.locator('[data-review-next="environment"]').first.click()
                    pw.expect(page.locator('#productionModule #settingsDialog')).to_be_visible()
                    page.keyboard.press("Escape")
                for width, height in SIZES:
                    page.set_viewport_size({"width": width, "height": height})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (name, width, theme)
                    if name in {"mapping", "review"}:
                        assert page.locator("#productionModule").bounding_box()["width"] >= width - 80
                        target = "#mappingContinue" if name == "mapping" else "#compileButton"
                        page.locator(target).scroll_into_view_if_needed()
                        bounds = page.locator(target).bounding_box()
                        assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width + 1, (name, width, bounds)
                        if name == "mapping":
                            pw.expect(page.locator(target)).to_be_disabled()
                        else:
                            pw.expect(page.locator(target)).to_be_disabled()
                    page.screenshot(path=str(tmp_path / f"{name}-{theme}-{width}.png"))
                    if name == "review":
                        page.locator(".production-review-next").scroll_into_view_if_needed()
                        page.screenshot(path=str(tmp_path / f"review-checks-{theme}-{width}.png"))
            page.goto(origin + "/?section=projects", wait_until="networkidle")
            page.set_viewport_size({"width": 1440, "height": 900})
            page.locator("#openSettingsButton").click()
            for width, height in SIZES:
                page.set_viewport_size({"width": width, "height": height})
                for label in ["外观", "模型服务", "AA 制作环境", "备份管理", "关于"]:
                    page.get_by_role("tab", name=label, exact=False).click()
                    dialog = page.get_by_role("dialog", name="设置中心")
                    bounds = dialog.bounding_box()
                    assert bounds and bounds["x"] >= -1 and bounds["y"] >= -1
                    assert bounds["x"] + bounds["width"] <= width + 1
                    assert bounds["y"] + bounds["height"] <= height + 1
                    assert dialog.evaluate("el=>el.scrollWidth <= el.clientWidth + 1"), (label, width)
                    page.screenshot(path=str(tmp_path / f"settings-{label}-{theme}-{width}.png"))
            page.keyboard.press("Escape")
            page.set_viewport_size({"width": 1440, "height": 900})
            page.locator("#openHelpButton").click()
            pw.expect(page.locator("#helpFrame")).to_be_visible(timeout=12000)
            help_page = page.frame_locator("#helpFrame")
            if theme == "dark":
                pw.expect(help_page.locator("body")).to_have_class(re.compile(r".*dark.*"))
                colors = page.locator("#helpDialog .help-dialog-header").evaluate("el=>({bg:getComputedStyle(el).backgroundColor,fg:getComputedStyle(el.querySelector('h2')).color})")
                def rgb(value):
                    return [float(n) for n in re.findall(r"[\d.]+", value)[:3]]
                assert max(rgb(colors["bg"])) < 100, colors
                assert min(rgb(colors["fg"])) > 160, colors
            help_page.get_by_role("button", name="正文修订和 Diff", exact=True).click()
            pw.expect(help_page.locator("#docsMain")).to_contain_text("应用 N 项修改")
            pw.expect(help_page.locator("#docsMain")).not_to_contain_text("1.0 不会自动拆分")
            help_page.get_by_role("button", name="人物与设定资料", exact=True).click()
            pw.expect(help_page.locator("#docsMain")).to_contain_text("跨作品复制保留来源和完整档案")
            help_page.get_by_role("button", name="活动与待处理事项", exact=True).click()
            pw.expect(help_page.locator("#docsMain")).to_contain_text("离开或隐藏后停止该页刷新")
            for width, height in SIZES:
                page.set_viewport_size({"width": width, "height": height})
                dialog = page.get_by_role("dialog", name="帮助中心")
                bounds = dialog.bounding_box()
                assert bounds and bounds["x"] >= -1 and bounds["y"] >= -1
                assert bounds["x"] + bounds["width"] <= width + 1
                assert bounds["y"] + bounds["height"] <= height + 1
                page.screenshot(path=str(tmp_path / f"help-{theme}-{width}.png"))
            assert not errors
        except Exception:
            print("LAYOUT DOM:", page.locator("body").inner_text()[-7000:])
            page.screenshot(path=str(tmp_path / "layout-failure.png"))
            raise
        finally:
            browser.close()
