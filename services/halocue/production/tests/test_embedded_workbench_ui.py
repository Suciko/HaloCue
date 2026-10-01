"""Real embedded production assets with synthetic API replies; no live services."""

from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import test_direction_profile_ui as fixtures
from test_direction_profile_ui import ProductionApiFixture, run_reply
from services.halocue.writing.src.halocue_writing.app import WritingRequestHandler

profile_browser = fixtures.profile_browser
PRODUCTION = Path(__file__).resolve().parents[1] / "ui"
WRITING = PRODUCTION.parents[1] / "writing" / "web"


@pytest.fixture
def embedded_page(profile_browser):
    contexts = []
    errors = []

    def open_page(
        mode="ai_direction",
        width=1280,
        background="BG_Black",
        height=1000,
        review_cards=0,
        theme="light",
        task_assets=None,
        asset_failure=False,
        playback=False,
        job_state=None,
        job_details=None,
        speakers=None,
        stage="generation",
    ):
        result = run_reply("conservative", job_state=job_state)
        if job_details:
            result["last_job"].update(job_details)
        result["run"]["source_summary"]["generation_mode"] = mode
        if speakers is not None:
            result["run"]["source_summary"]["speakers"] = speakers
            result["run"]["source_summary"]["speaker_details"] = [
                {"speaker": speaker, "count": 2, "sample": "测试用台词摘要"}
                for speaker in speakers
            ]
        result["draft"]["cards"] = [
            {
                "card_id": "scene-1",
                "kind": "scene",
                "line_no": 1,
                "current": {"title": "测试场景 · 午后"},
                "review_state": "approved",
            },
            {
                "card_id": "bg-1",
                "kind": "dir",
                "line_no": 2,
                "current": {"cmd": "bg", "arg": background},
                "review_state": "approved",
            },
        ]
        result["draft"]["cards"].extend(
            {
                "card_id": f"review-{i}",
                "kind": "scene",
                "line_no": i + 3,
                "current": {"title": f"审查内容 {i + 1}"},
                "review_state": "approved",
            }
            for i in range(review_cards)
        )
        api = ProductionApiFixture(result)
        api.asset_failure = asset_failure
        api.task_assets = task_assets or []
        api.asset_reads = 0
        context = profile_browser.new_context(viewport={"width": width, "height": height})
        contexts.append(context)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route_request(route):
            path = urlsplit(route.request.url).path
            if path.endswith("/preview"):
                if "/BG_Available/" in path:
                    route.fulfill(
                        content_type="image/png",
                        body=base64.b64decode(
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
                        ),
                    )
                else:
                    route.fulfill(
                        status=404, json={"error": {"code": "resource_preview_not_found"}}
                    )
            elif path.endswith("/assets") and route.request.method == "GET":
                api.asset_reads += 1
                if api.asset_failure:
                    route.fulfill(status=503, json={"error": {"message": "测试素材服务不可用"}})
                else:
                    route.fulfill(json={"items": api.task_assets})
            elif path.endswith("/performance-preview") and playback:
                route.fulfill(
                    json={
                        "frames": [
                            {
                                "card_id": c["card_id"],
                                "title": c["current"].get("title", "背景指令"),
                                "text": "预览内容",
                                "card_kind": c["kind"],
                                "annotations": [],
                                "background_key": "BG_Black",
                                "background_preview_available": False,
                            }
                            for c in result["draft"]["cards"]
                        ]
                    }
                )
            elif "/api/v1/" in path:
                api.handle(route)
            elif path == "/":
                route.fulfill(
                    content_type="text/html",
                    body="""<!doctype html>
                    <html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
                    <link rel="stylesheet" href="/production-embed.css">
                    <style>body{margin:0}#app{display:block;height:100vh}
                    #productionModule{height:100%;width:100%;outline:none;box-sizing:border-box}</style></head>
                    <body><div id="app" class="app-shell"></div>
                    <script src="/production-embed.js"></script></body></html>""",
                )
            elif path == "/production/app-embedded.js":
                body = WritingRequestHandler._embedded_production_script(
                    (PRODUCTION / "app.js").read_bytes()
                )
                route.fulfill(content_type="text/javascript", body=body)
            else:
                asset = (
                    PRODUCTION / (path.removeprefix("/production/") or "index.html")
                    if path.startswith("/production/")
                    else WRITING / path.lstrip("/")
                )
                if asset.is_file():
                    route.fulfill(
                        content_type=mimetypes.guess_type(asset.name)[0] or "text/plain",
                        body=asset.read_bytes(),
                    )
                else:
                    route.fulfill(status=404, body="not found")

        page.route("**/*", route_request)
        page.goto("http://embedded.test/")
        page.evaluate("theme => document.documentElement.dataset.theme=theme", theme)
        page.evaluate("window.HaloCueProductionEmbed.open({runId:'run-synthetic'})")
        expect(page.locator("#productionModule")).to_have_attribute("aria-busy", "false")
        page.locator('.embedded-production-shell [data-stage="mapping"]').click()
        if stage == "generation":
            page.locator("#mappingContinue").click()
            expect(page.locator("#scenePlan .scene-plan-card")).to_have_count(1 + review_cards)
        elif stage != "mapping":
            raise ValueError(f"Unsupported embedded test stage: {stage}")
        return page, api

    yield open_page
    for context in contexts:
        context.close()
    assert errors == []


@pytest.mark.parametrize("width", [390, 1280])
def test_failed_logs_are_readable_in_dark_mode_and_show_reported_usage(embedded_page, width):
    page, api = embedded_page(width=width, theme="dark", job_state="failed", job_details={
        "error": {"code": "direction_generation_failed", "message": "structured_output_invalid"},
        "events": [{"kind": "model_activity", "state": "waiting"}],
        "result": {"metrics": {"requests": 2, "input_tokens": 30845, "output_tokens": 1278,
                               "failed_request_count": 2, "failed_request_input_tokens": 30845,
                               "failed_request_output_tokens": 1278}},
    })
    page.locator(".generation-diagnostics > summary").click()
    expect(page.locator("#generationMetrics")).to_contain_text("30,845")
    expect(page.locator("#generationMetrics")).not_to_contain_text("暂无用量")
    page.locator(".generation-log > summary").click()
    expect(page.locator("#generationLog")).to_contain_text("等待模型响应")
    for row in page.locator(".job-log-row").all():
        colors = row.evaluate("e => [getComputedStyle(e).backgroundColor, getComputedStyle(e).color].map(c => c.match(/[\\d.]+/g).slice(0,3).map(Number))")
        assert max(colors[0]) < 150
        def luminance(rgb):
            values = [v / 255 for v in rgb]
            linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
            return sum(v * w for v, w in zip(linear, [0.2126, 0.7152, 0.0722]))
        light, dark = sorted([luminance(c) for c in colors], reverse=True)
        assert (light + 0.05) / (dark + 0.05) >= 4.5
    assert api.posts == []


@pytest.mark.parametrize("width", [390, 1280])
def test_generation_scope_is_read_only_and_links_back_to_materials(embedded_page, width):
    page, api = embedded_page(width=width)
    expect(page.locator("#page-generation [data-scene-plan-official]")).to_have_count(0)
    expect(page.locator("#page-generation .production-scene-tools")).to_have_count(0)
    expect(page.locator("#scenePlan [data-scene-plan-card]")).to_have_count(1)
    page.locator("#returnToMapping").click()
    expect(page.locator("#page-mapping")).to_be_visible()
    expect(page.locator("#mappingScenePlan [data-mapping-scene-official]")).to_be_visible()
    assert api.posts == []


def test_embedded_speaker_mapping_wraps_names_and_keeps_role_chip_compact(embedded_page):
    speaker = "阿拜多斯对策委员会·砂狼白子验收用长名字"
    page, api = embedded_page("format_only", width=1600, speakers=[speaker], stage="mapping")
    row = page.locator(".embedded-production-shell .mapping-row").first
    expect(row.locator(".mapping-speaker-cell strong")).to_have_text(speaker)

    bounds = row.evaluate(
        """row => {
          const name = row.querySelector('.mapping-speaker-cell strong');
          const value = row.querySelector('.mapping-value');
          const chip = row.querySelector('.mapping-role-chip');
          const rect = element => {
            const box = element.getBoundingClientRect();
            return {left: box.left, right: box.right, width: box.width};
          };
          return {
            row: rect(row),
            name: rect(name),
            value: rect(value),
            chip: rect(chip),
            nameWhiteSpace: getComputedStyle(name).whiteSpace,
            rowClientWidth: row.clientWidth,
            rowScrollWidth: row.scrollWidth,
          };
        }"""
    )
    assert bounds["nameWhiteSpace"] == "normal", bounds
    assert bounds["name"]["right"] <= bounds["row"]["right"] + 1, bounds
    assert bounds["chip"]["width"] < bounds["value"]["width"] - 20, bounds
    assert bounds["rowScrollWidth"] <= bounds["rowClientWidth"] + 1, bounds
    assert api.posts == []


@pytest.mark.parametrize("width", [390, 1280, 1600])
@pytest.mark.parametrize("mode", ["format_only", "ai_direction"])
def test_embedded_settings_are_distinct_and_fit_viewport(embedded_page, width, mode):
    page, api = embedded_page(mode, width)
    if mode == "ai_direction":
        expect(page.locator("#directionProfileControl")).to_be_visible()
        expect(page.locator("#layoutModeFieldset")).to_be_visible()
        expect(page.locator(".production-format-note")).to_be_hidden()
        expect(page.locator("#directionProfile")).to_have_value("conservative")
        expect(page.locator("#directionProfileControl .profile-boundary-note")).to_contain_text("不会立即改写")
        page.locator('input[name="directionProfileChoice"][value="standard"]').check()
        expect(page.locator('input[name="layoutMode"]:checked')).to_have_value("ai")
    else:
        expect(page.locator("#directionProfileControl")).to_be_hidden()
        expect(page.locator("#layoutModeFieldset")).to_be_hidden()
        expect(page.locator(".production-format-note")).to_be_visible()
    for selector in ["#page-generation", ".production-generation-flow", ".scene-plan-card"]:
        bounds = page.locator(selector).evaluate(
            'e => ({client: e.clientWidth, scroll: e.scrollWidth, children: [...e.querySelectorAll("*")].filter(c=>c.scrollWidth>c.clientWidth+1).map(c=>[c.className,c.clientWidth,c.scrollWidth,getComputedStyle(c).display,getComputedStyle(c).gridTemplateColumns])})'
        )
        assert bounds["scroll"] <= bounds["client"] + 1, (selector, bounds)
    assert api.posts == []


@pytest.mark.parametrize(
    "stage,card,official,expected_direct_buttons",
    [
                ("mapping", "#mappingScenePlan .mapping-scene-card", "data-mapping-scene-official", 1),
    ],
)
def test_material_disclosure_retains_actions_after_rerender(embedded_page, stage, card, official, expected_direct_buttons):
    page, api = embedded_page()
    page.locator(f'.embedded-production-shell [data-stage="{stage}"]').click()
    row = page.locator(card)
    expect(row.locator(".production-scene-tools")).to_have_count(1)
    expect(row.locator("footer > button")).to_have_count(expected_direct_buttons)
    if stage == "mapping":
        expect(row.locator("[data-mapping-scene-review]")).to_have_count(0)
        expect(row.locator(".mapping-stage-note")).to_contain_text("第 4 步统一进行")
    expect(row.locator(".production-scene-tools-content button")).to_have_count(5)
    summary = row.locator(".production-scene-tools > summary")
    summary.focus()
    page.keyboard.press("Enter")
    expect(row.locator(".production-scene-tools")).to_have_attribute("open", "")
    row.locator("[data-scene-plan-prompt], [data-mapping-scene-prompt]").click()
    expect(page.locator("#backgroundPromptDialog")).to_be_visible()
    expect(page.locator("#backgroundPromptScene")).to_contain_text("测试场景")
    page.keyboard.press("Escape")
    # Native actions still open the resource picker after the reorganization.
    row.locator(f"[{official}]").click()
    expect(page.locator("#resourceDialog")).to_be_visible()
    page.keyboard.press("Escape")
    page.evaluate(
        "document.querySelector('#productionModule').shadowRoot.querySelector('#refreshRun').click()"
    )
    expect(row.locator(".production-scene-tools")).to_have_count(1)
    expect(row.locator(".production-scene-tools-content button")).to_have_count(5)
    assert api.posts == []


@pytest.mark.parametrize("background", ["BG_Available", "BG_Missing"])
def test_embedded_previews_show_image_or_explicit_missing_state(embedded_page, background):
    page, api = embedded_page(background=background)
    thumb = page.locator("#scenePlan .scene-plan-thumb")
    thumb.scroll_into_view_if_needed()
    if background == "BG_Available":
        expect(thumb.locator("img")).to_be_visible()
        expect(thumb.locator("img")).to_have_js_property("naturalWidth", 1)
    else:
        expect(thumb.locator(".preview-placeholder")).to_have_text("图片暂不可用")
        expect(thumb.locator(".preview-placeholder")).to_be_visible()
        expect(thumb.locator("img")).to_be_hidden()
    assert api.posts == []


@pytest.mark.parametrize("width,height", [(1100, 740), (1280, 720), (1600, 1000), (390, 844)])
def test_review_cards_are_reachable_by_normal_page_scrolling(embedded_page, width, height):
    page, api = embedded_page("format_only", width, height=height, review_cards=18)
    page.locator('.embedded-production-shell [data-stage="review"]').click()
    cards = page.locator("#cardList .draft-card")
    expect(cards).to_have_count(20)
    # Card content must stay in the page flow, not a second scrollbox located
    # below an overflow:hidden parent (the reported desktop/zoom regression).
    expect(page.locator("#cardList")).to_have_css("overflow-y", "visible")
    expect(page.locator(".review-column")).to_have_css("overflow-y", "visible")
    page.locator("#backgroundTimeline").hover()
    for _ in range(7):
        page.mouse.wheel(0, 550)
        page.wait_for_timeout(60)
    last = cards.last
    last.scroll_into_view_if_needed()
    expect(last).to_be_in_viewport()
    last.click()
    expect(page.locator("#inspectorTitle")).to_contain_text("第 20 张")
    page.locator("#compileButton").scroll_into_view_if_needed()
    expect(page.locator("#compileButton")).to_be_in_viewport()
    assert page.locator("#cardList").evaluate("e=>e.scrollTop") == 0
    inspector = page.locator("#page-review .inspector")
    assert inspector.evaluate("e => e.scrollHeight <= e.clientHeight + 1")
    assert page.locator(".review-column").evaluate(
        "e => [...e.children].map(c => c.id || c.className)"
    ) == [
        "filterbar",
        "selectedCardToolbar",
        "reviewCommandGuide",
        "backgroundTimeline",
        "cardList",
    ]
    assert api.posts == []


@pytest.mark.parametrize(
    "stage,selectors",
    [
        ("source", [".source-document-block", ".modern-dropzone", ".dropzone-file-info", "#projectName", "#preflightSource"]),
        ("mapping", [".mapping-focus", ".mapping-scene-list", ".mapping-scene-issues"]),
        ("generation", [".production-generation-step", ".profile-choice-body", ".mode-choice"]),
        (
            "review",
            [
                ".production-review-commandbar",
                "#approveAll",
                ".filterbar",
                "#cardList .draft-card",
                "#page-review .inspector",
                ".persistent-preview-panel",
            ],
        ),
    ],
)
def test_dark_theme_covers_embedded_surfaces_and_resets_to_light(embedded_page, stage, selectors):
    page, api = embedded_page("format_only" if stage == "review" else "ai_direction")
    page.locator(f'.embedded-production-shell [data-stage="{stage}"]').click()
    targets = [page.locator(selector).first for selector in selectors]

    def colors():
        return [
            target.evaluate("e=>[getComputedStyle(e).backgroundColor,getComputedStyle(e).color]")
            for target in targets
        ]

    light = colors()
    page.evaluate("document.documentElement.dataset.theme='dark'")
    page.wait_for_timeout(250)
    for target in targets:
        rgb = target.evaluate(
            "e=>getComputedStyle(e).backgroundColor.match(/[\\d.]+/g).map(Number)"
        )
        assert max(rgb[:3]) < 150, (target, rgb)
        contrast = target.evaluate("""e => {
          const rgb = s => (s.match(/[\\d.]+/g) || []).map(Number);
          const lum = c => c.slice(0,3).map(v => {v/=255; return v<=.04045 ? v/12.92 : ((v+.055)/1.055)**2.4;})
            .reduce((a,v,i) => a+v*[.2126,.7152,.0722][i],0);
          const style = getComputedStyle(e), fg = lum(rgb(style.color)), bg = lum(rgb(style.backgroundColor));
          return (Math.max(fg,bg)+.05)/(Math.min(fg,bg)+.05);
        }""")
        assert contrast >= 4.5, (target, contrast)
    page.evaluate("document.documentElement.dataset.theme='light'")
    page.wait_for_timeout(250)
    assert colors() == light
    assert api.posts == []


@pytest.mark.parametrize("initial_dark", [True, False])
def test_dark_dialog_and_media_survive_live_theme_switch(embedded_page, initial_dark):
    page, api = embedded_page(background="BG_Available", theme="dark" if initial_dark else "light", stage="mapping")
    image = page.locator("#mappingScenePlan img").first
    expect(image).to_have_js_property("naturalWidth", 1)
    source = image.get_attribute("src")
    page.locator("[data-mapping-scene-official]").first.click()
    dialog = page.locator("#resourceDialog")
    expect(dialog).to_be_visible()
    page.evaluate("document.documentElement.dataset.theme='dark'")
    expect(dialog).to_have_css("background-color", "rgb(32, 38, 49)")
    page.keyboard.press("Escape")
    page.locator("#mappingScenePlan .production-scene-tools > summary").first.click()
    page.locator("[data-mapping-scene-prompt]").first.click()
    expect(page.locator("#backgroundPromptText")).to_have_css("color", "rgb(225, 231, 238)")
    expect(page.locator("#backgroundPromptText")).to_have_css("background-color", "rgb(25, 30, 39)")
    page.keyboard.press("Escape")
    page.evaluate("document.documentElement.dataset.theme='light'")
    assert image.get_attribute("src") == source
    expect(image).to_have_css("filter", "none")
    expect(image).to_have_js_property("naturalWidth", 1)
    assert api.posts == []


@pytest.mark.parametrize("width", [390, 1440])
def test_writing_dark_reading_and_agent_use_same_palette(profile_browser, width):
    context = profile_browser.new_context(viewport={"width": width, "height": 900})
    try:
        page = context.new_page()
        # Real writing styles, with representative read-only manuscript/agent DOM.
        page.route("**/*", lambda route: route.abort())
        page.set_content("""<!doctype html><html data-theme="light"><body>
          <div id="app" class="app-shell hc-redesign writing-workbench-stage">
            <div class="chapter-inline-manuscript"><article class="manuscript-block">
              <button class="manuscript-reading"><span class="manuscript-reading-speaker">爱丽丝</span>
                <span class="manuscript-reading-text">老师，存档已经恢复了。</span></button>
            </article></div>
            <section class="scene-agent-panel scene-harness"><h3>本章 Agent</h3>
              <form class="scene-conversation-composer"><textarea>讨论正文</textarea></form>
            </section><section class="next-command"><strong>检查完成</strong></section>
            <button class="writing-scene active">当前场景</button>
          </div></body></html>""")
        for name in [
            "styles.css",
            "tokens.css",
            "shell.css",
            "writing-workbench.css",
            "redesign.css",
            "theme.css",
        ]:
            page.add_style_tag(content=(WRITING / name).read_text(encoding="utf-8"))
        text = page.locator(".manuscript-reading-text")
        light_color = text.evaluate("e=>getComputedStyle(e).color")
        page.evaluate("document.documentElement.dataset.theme='dark'")
        expect(text).to_have_css("color", "rgb(225, 231, 238)")
        expect(page.locator(".manuscript-block")).to_have_css("background-color", "rgb(29, 35, 45)")
        expect(page.locator(".scene-agent-panel")).to_have_css(
            "background-color", "rgb(29, 35, 45)"
        )
        expect(page.locator(".scene-conversation-composer")).to_have_css(
            "background-color", "rgb(29, 35, 45)"
        )
        page.evaluate("document.documentElement.dataset.theme='light'")
        expect(text).to_have_css("color", light_color)
    finally:
        context.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_review_restores_explanations_and_actual_task_assets(embedded_page, theme):
    page, api = embedded_page(
        "format_only",
        theme=theme,
        task_assets=[
            {
                "asset_id": "asset-012345678901",
                "kind": "background",
                "name": "测试社团室",
                "key": "BG_Test",
                "library_asset_id": "library-test",
            }
        ],
    )
    page.locator('.embedded-production-shell [data-stage="review"]').click()
    expect(page.locator("#cardList .draft-card").first).to_contain_text("测试场景 · 午后")
    expect(page.locator("#cardList .draft-card").nth(1)).to_contain_text("切换背景")
    page.locator("#reviewCommandGuide summary").click()
    expect(page.locator("#reviewCommandGuide")).to_contain_text("不会回写已冻结")
    expect(page.locator("#reviewTaskAssets")).to_contain_text("测试社团室")
    expect(page.locator("#reviewTaskAssets")).to_contain_text("历史素材副本")
    expect(page.locator("#reviewTaskAssetCount")).to_have_text("1 项")
    assert page.locator(".review-side-rail").evaluate(
        "e => [...e.children].map(c => c.className)"
    ) == ["persistent-preview-panel", "inspector", "review-task-assets"]
    page.locator("#reviewAssetsImport").click()
    expect(page.locator("#assetImportDialog")).to_be_visible()
    page.keyboard.press("Escape")
    page.locator("#reviewAssetsManage").click()
    expect(page.locator("#assetLibraryDialog")).to_be_visible()
    assert api.posts == []


def test_failed_asset_read_is_not_presented_as_empty_and_retry_recovers(embedded_page):
    page, api = embedded_page("format_only", asset_failure=True)
    page.locator('.embedded-production-shell [data-stage="review"]').click()
    expect(page.locator("#reviewTaskAssets")).to_contain_text("素材读取失败")
    expect(page.locator("#reviewTaskAssetCount")).to_have_text("读取失败")
    reads = api.asset_reads
    page.locator("#cardList .draft-card").nth(1).click()
    assert api.asset_reads == reads
    api.asset_failure = False
    page.locator("#reviewAssetsRefresh").click()
    expect(page.locator("#reviewTaskAssets")).to_contain_text("尚未登记自定义素材")
    expect(page.locator("#reviewTaskAssetCount")).to_have_text("0 项")
    assert api.posts == []


def test_playback_keeps_inspector_and_selected_card_in_sync(embedded_page):
    page, api = embedded_page("format_only", playback=True)
    page.locator('.embedded-production-shell [data-stage="review"]').click()
    expect(page.locator("#reviewPreviewPlay")).to_be_enabled()
    page.locator("#reviewPreviewPlay").click()
    expect(page.locator("#persistentPreviewCounter")).to_have_text("2 / 2", timeout=7000)
    expect(page.locator("#cardList [data-card-id='bg-1']")).to_have_class(
        re.compile(r"\bdraft-card\s+approved\s+selected\b")
    )
    expect(page.locator("#inspectorTitle")).to_contain_text("演出指令")
    expect(page.locator("#selectedCardToolbarLabel")).to_contain_text("切换背景")
    assert api.posts == []


@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_new_and_locked_profile_cards_in_embedded_ui(embedded_page, tmp_path, width, theme):
    import os
    page, api = embedded_page(width=width, theme=theme, job_state="running")
    root = page.locator('#directionProfileControl')
    root.scroll_into_view_if_needed()
    expect(page.locator('#directionProfileLock')).to_have_text('本次策略已锁定')
    for value in ('conservative', 'standard'):
        expect(page.locator(f'input[name="directionProfileChoice"][value="{value}"]')).to_be_disabled()
    out = Path(os.environ.get('HALOCUE_TEST_SCREENSHOT_DIR') or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    root.screenshot(path=str(out / f'fixture-{theme}-{width}-locked-detail.png'))
    page.screenshot(path=str(out / f'fixture-{theme}-{width}-locked.png'))
    assert api.posts == []
    # Source configuration is independent of the running job's frozen strategy,
    # but entering it is explicit so the current task is not replaced accidentally.
    page.locator('.stage-list [data-stage="source"]').click()
    expect(page.locator('.production-current-task-boundary')).to_be_visible()
    page.locator('[data-current-task-new]').click()
    page.locator('[data-source-tab="manual"]').click()
    page.locator('#projectName').fill('Synthetic new task')
    page.locator('#scriptText').fill('Narrator: A synthetic scene.')
    page.locator('#preflightSource').click()
    page.locator('#confirmSceneJudgement').click()
    page.locator('input[name="generationMode"][value="ai_direction"]').check()
    source = page.locator('#sourceDirectionProfileControl')
    source.scroll_into_view_if_needed()
    expect(page.locator('input[name="sourceDirectionProfileChoice"][value="conservative"]')).to_be_checked()
    page.locator('input[name="sourceDirectionProfileChoice"][value="standard"]').check()
    expect(page.locator('#sourceDirectionProfileStatus')).to_contain_text('标准')
    expect(page.locator('#directionProfile')).to_have_value('conservative')
    source.screenshot(path=str(out / f'fixture-{theme}-{width}-source-detail.png'))
    page.screenshot(path=str(out / f'fixture-{theme}-{width}-source.png'))
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert api.posts == []


@pytest.mark.parametrize("width", [390, 1280])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_background_gallery_is_compact_and_details_do_not_select(embedded_page, width, theme):
    page, api = embedded_page(width=width, theme=theme)
    page.route("**/resources/backgrounds?*", lambda route: route.fulfill(json={
        "items": [{"key": "BG_Available", "name": "测试活动室", "time": "day", "indoor_outdoor": "indoor", "preview_available": True,
                   "usage_hint": "很长的使用建议，不应默认挤占图片位置。", "scene_match": {"status": "match", "matches": ["时间：白天"], "conflicts": [], "unknown": []}}],
        "total": 1, "offset": 0, "has_more": False,
    }))
    page.locator('.embedded-production-shell [data-stage="mapping"]').click()
    page.locator("[data-mapping-scene-official]").click()
    tile = page.locator(".background-gallery-select")
    expect(tile.locator("strong")).to_have_text("测试活动室")
    expect(tile.locator("small")).to_have_text("白天 · 室内")
    expect(tile).not_to_contain_text("已知条件匹配")
    expect(page.locator(".background-gallery-details .resource-annotation")).not_to_be_visible()
    expect(tile.locator("img")).to_have_js_property("naturalWidth", 1)
    assert page.locator("#resourceDialog").evaluate("e => e.scrollWidth <= e.clientWidth + 1")
    assert page.locator(".background-gallery-item").evaluate("e => e.getBoundingClientRect().height") < 300
    before = list(api.posts)
    page.locator(".background-gallery-details summary").focus()
    page.locator(".background-gallery-details summary").press("Enter")
    expect(page.locator(".background-gallery-details code")).to_have_text("BG_Available")
    expect(page.locator(".background-gallery-details .resource-annotation")).to_be_visible()
    assert api.posts == before
