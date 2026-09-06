"""Teacher presentation controls at the browser/API boundary."""

from __future__ import annotations

import copy
import os
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from PIL import Image, ImageDraw

import test_teacher_identity_ui as identity_ui
from test_teacher_identity_ui import TeacherApiFixture, expect, open_teacher


profile_browser = identity_ui.profile_browser
ui_url = identity_ui.ui_url
PRESENTATION = {
    "state": "available",
    "schema_version": "teacher-presentation/1.0",
    "default_mode": "slot_zero",
    "modes": ["slot_zero", "sel_single"],
}


class TeacherSelApiFixture(TeacherApiFixture):
    def __init__(self, *, presentation_supported=True):
        super().__init__()
        self.presentation_supported = presentation_supported
        self.frames = []

    def handle(self, route):
        request = route.request
        path = urlsplit(request.url).path.removeprefix("/api/v1")
        if path == "/capabilities":
            capabilities = {
                "teacher_identity": {
                    "schema_version": "teacher-identity/1.0",
                    "presentation": "slot_zero",
                    "presets": identity_ui.PRESETS,
                }
            }
            if self.presentation_supported:
                capabilities["teacher_presentation"] = copy.deepcopy(PRESENTATION)
            route.fulfill(json={"capabilities": capabilities})
            return
        if request.method == "POST" and path.endswith("/cast-bindings"):
            presentation = request.post_data_json["mapping"].get("presentation")
            if presentation and not self.fail_save:
                self.result["draft"]["cast"]["teacher_presentation"] = copy.deepcopy(presentation)
        if path.endswith("/performance-preview"):
            route.fulfill(json={"frames": self.frames})
            return
        super().handle(route)


@pytest.fixture
def sel_page(profile_browser, ui_url):
    context = profile_browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def open_page(*, supported=True, stored_mode=None, frames=None):
        api = TeacherSelApiFixture(presentation_supported=supported)
        if stored_mode:
            api.result["draft"]["cast"]["teacher_presentation"] = {
                "schema_version": "teacher-presentation/1.0",
                "mode": stored_mode,
            }
        if frames is not None:
            api.frames = frames
            api.result["run"]["source_summary"]["speakers"] = []
            api.result["run"]["source_summary"]["generation_mode"] = "format_only"
            api.result["draft"]["cast"]["detected_speakers"] = []
        page.route("**/api/v1/**", api.handle)
        page.add_init_script("localStorage.setItem('halocue.currentRunId', 'run-synthetic');")
        page.goto(ui_url, wait_until="networkidle")
        expect(page.locator("#serviceState")).to_contain_text("halocue-production")
        return page, api

    yield open_page
    context.close()
    assert errors == []


def test_teacher_sel_requires_save_and_restores_persisted_mode(sel_page):
    page, api = sel_page()
    open_teacher(page)
    expect(page.get_by_role("radio", name="普通对白（槽 0）", exact=True)).to_be_checked()
    page.get_by_role("radio", name="Sel 回答", exact=True).check()
    assert api.posts == []
    page.get_by_role("button", name="创建并绑定老师", exact=True).click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    assert api.posts[0][2]["mapping"]["presentation"] == {
        "schema_version": "teacher-presentation/1.0",
        "mode": "sel_single",
    }
    assert api.posts[0][2]["expected_draft_version"] == 1
    page.reload(wait_until="networkidle")
    page.locator('.mapping-edit[data-speaker="Sensei"]').click()
    expect(page.get_by_role("radio", name="Sel 回答", exact=True)).to_be_checked()
    assert len(api.posts) == 1


def test_mode_change_confirms_shared_aliases_and_can_switch_back(sel_page):
    page, api = sel_page()
    open_teacher(page)
    page.get_by_role("button", name="创建并绑定老师", exact=True).click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    open_teacher(page, "老师")
    page.get_by_role("button", name="保存老师身份", exact=True).click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    page.locator('.mapping-edit[data-speaker="Sensei"]').click()
    page.get_by_role("radio", name="Sel 回答", exact=True).check()
    page.get_by_role("button", name="保存老师身份", exact=True).click()
    expect(page.locator("#actionConfirmBody")).to_contain_text("Sensei")
    expect(page.locator("#actionConfirmBody")).to_contain_text("老师")
    expect(page.locator("#actionConfirmBody")).to_contain_text("Sel 回答")
    assert len(api.posts) == 2
    page.locator("#actionConfirmDialog").get_by_role("button", name="取消", exact=True).click()
    expect(page.get_by_role("radio", name="Sel 回答", exact=True)).to_be_checked()
    assert len(api.posts) == 2
    page.get_by_role("button", name="保存老师身份", exact=True).click()
    page.locator("#actionConfirmAccept").click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    identity = copy.deepcopy(api.result["draft"]["cast"]["teacher_identity"])
    page.locator('.mapping-edit[data-speaker="老师"]').click()
    expect(page.get_by_role("radio", name="Sel 回答", exact=True)).to_be_checked()
    page.get_by_role("radio", name="普通对白（槽 0）", exact=True).check()
    page.get_by_role("button", name="保存老师身份", exact=True).click()
    expect(page.locator("#actionConfirmBody")).to_contain_text("普通对白（槽 0）")
    page.locator("#actionConfirmAccept").click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    assert api.posts[-1][2]["mapping"]["presentation"]["mode"] == "slot_zero"
    assert api.result["draft"]["cast"]["teacher_identity"] == identity


def test_unchanged_mode_save_needs_no_extra_confirmation(sel_page):
    page, api = sel_page()
    open_teacher(page)
    page.get_by_role("radio", name="Sel 回答", exact=True).check()
    page.get_by_role("button", name="创建并绑定老师", exact=True).click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    page.locator('.mapping-edit[data-speaker="Sensei"]').click()
    page.get_by_role("button", name="保存老师身份", exact=True).click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    expect(page.locator("#actionConfirmDialog")).not_to_be_visible()
    assert len(api.posts) == 2


def test_cas_conflict_keeps_selected_mode_for_user_review(sel_page):
    page, api = sel_page()
    open_teacher(page)
    page.get_by_role("radio", name="Sel 回答", exact=True).check()
    api.fail_save = True
    page.get_by_role("button", name="创建并绑定老师", exact=True).click()
    expect(page.locator("#mappingDialogStatus")).to_contain_text("请关闭后重新确认")
    expect(page.get_by_role("radio", name="Sel 回答", exact=True)).to_be_checked()
    expect(page.get_by_role("button", name="创建并绑定老师", exact=True)).to_be_enabled()
    assert len(api.posts) == 1
    assert "teacher_presentation" not in api.result["draft"]["cast"]


def test_old_capability_hides_mode_and_omits_presentation_from_identity_save(sel_page):
    page, api = sel_page(supported=False)
    open_teacher(page)
    expect(page.get_by_role("group", name="老师台词呈现")).not_to_be_visible()
    page.get_by_role("button", name="创建并绑定老师", exact=True).click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    assert "presentation" not in api.posts[0][2]["mapping"]


def test_unavailable_stored_sel_is_read_only_not_a_silent_slot_zero_default(sel_page):
    page, api = sel_page(supported=False, stored_mode="sel_single")
    open_teacher(page)
    expect(page.get_by_role("group", name="老师台词呈现")).not_to_be_visible()
    expect(page.locator("#teacherIdentityScope")).to_contain_text("Sel 回答")
    expect(page.locator("#teacherIdentityScope")).to_contain_text("不支持")
    expect(page.get_by_role("button", name="创建并绑定老师", exact=True)).to_be_disabled()
    expect(page.get_by_label("老师名称 / 组织")).to_be_disabled()
    assert api.posts == []


def reply_frame(card_id, text, line_no, *, cg=None):
    return {
        "card_id": card_id,
        "line_no": line_no,
        "presentation": "teacher_selection",
        "teacher_reply": {
            "reply_id": f"reply-{card_id}",
            "continuation_id": f"continue-{card_id}",
            "text": text,
            "source_card_id": card_id,
        },
        "title": "老师",
        "text": text,
        "speaker": {"name": "老师", "organization": "夏莱", "role": "teacher"},
        "review_state": "pending",
        "cg": cg,
    }


def test_preview_single_reply_advances_consecutive_answers_and_finishes_without_write(sel_page):
    page, api = sel_page(
        frames=[
            reply_frame("teacher-first", "第一句，先出发。", 1),
            reply_frame("teacher-second", "第二句，走这边。", 2),
            {
                "card_id": "ordinary",
                "line_no": 3,
                "title": "店员",
                "text": "欢迎光临。",
                "presentation": "dialogue",
            },
            reply_frame("teacher-last", "最后一句，谢谢。", 4),
        ]
    )
    page.locator('.stage-list [data-stage="review"]').click()
    page.locator("#openPerformancePreview").click()
    expect(page.locator(".preview-dialogue")).to_have_count(0)
    expect(page.locator(".preview-speaker-organization")).to_have_count(0)
    answer = page.get_by_role("button", name="第一句，先出发。", exact=True)
    expect(answer).to_have_count(1)
    answer.click()
    page.get_by_role("button", name="第二句，走这边。", exact=True).click()
    expect(page.locator(".preview-dialogue > strong")).to_have_text("店员")
    expect(page.locator(".preview-dialogue > p")).to_have_text("欢迎光临。")
    page.locator("#previewNext").click()
    page.get_by_role("button", name="最后一句，谢谢。", exact=True).click()
    expect(page.locator("#performancePreview").get_by_role("status")).to_have_text("本段预览结束")
    expect(page.get_by_role("button", name="最后一句，谢谢。", exact=True)).to_have_count(0)
    expect(page.locator("#previewNext")).to_be_disabled()
    page.locator('[data-preview-index="0"]').click()
    expect(page.get_by_role("button", name="第一句，先出发。", exact=True)).to_be_visible()
    assert api.posts == []


@pytest.mark.parametrize("width", [1280, 390, 320])
def test_teacher_mode_controls_and_cg_reply_fit_viewports(sel_page, tmp_path, width):
    page, api = sel_page()
    page.set_viewport_size({"width": width, "height": 900})
    open_teacher(page)
    page.get_by_role("radio", name="Sel 回答", exact=True).check()
    screenshots = Path(os.environ.get("HALOCUE_TEST_SCREENSHOT_DIR") or tmp_path)
    screenshots.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshots / f"teacher-sel-controls-{width}.png"))
    for selector in ("#teacherPresentationControl", "#saveTeacherIdentity"):
        bounds = page.locator(selector).bounding_box()
        assert bounds and 0 <= bounds["x"] and bounds["x"] + bounds["width"] <= width
        assert page.locator(selector).evaluate("el => el.scrollWidth <= el.clientWidth")
    page.locator('#mappingDialog [data-close-dialog="mappingDialog"]').click()
    api.result["run"]["source_summary"].update(speakers=[], generation_mode="format_only")
    api.result["draft"]["cast"]["detected_speakers"] = []
    frame = reply_frame(
        "cg-teacher",
        "我们一起出发吧。\n无论接下来会遇见什么，我都会和大家一起面对。",
        1,
        cg={"background_key": "BG_CG", "label": "Synthetic CG"},
    )
    frame.update(background_key="BG_CG", background_preview_available=True)
    api.frames = [frame]
    background = Image.new("RGB", (320, 180), "#c9dee1")
    ImageDraw.Draw(background).rectangle((0, 100, 320, 180), fill="#8fac9d")
    image_bytes = BytesIO()
    background.save(image_bytes, format="PNG")
    page.route(
        "**/resources/backgrounds/BG_CG/preview",
        lambda route: route.fulfill(body=image_bytes.getvalue(), content_type="image/png"),
    )
    page.reload(wait_until="networkidle")
    page.locator('.stage-list [data-stage="review"]').click()
    page.locator("#openPerformancePreview").click()
    expect(page.locator(".preview-teacher-reply")).to_have_text(frame["text"])
    expect(page.locator(".preview-stage-image")).to_have_js_property("naturalWidth", 320)
    expect(page.locator(".preview-dialogue")).to_have_count(0)
    page.locator(".preview-teacher-reply").scroll_into_view_if_needed()
    bounds = page.locator(".preview-teacher-reply").bounding_box()
    assert bounds and 0 <= bounds["x"] and bounds["x"] + bounds["width"] <= width
    assert page.locator("#performancePreview").evaluate("el => el.scrollWidth <= el.clientWidth")
    assert page.locator(".preview-teacher-reply").evaluate("el => el.scrollWidth <= el.clientWidth")
    page.screenshot(path=str(screenshots / f"teacher-sel-cg-preview-{width}.png"))
    assert api.posts == []


def test_reply_text_is_literal_not_html(sel_page):
    source_text = '<img src="invalid" onerror="throw Error(123)">老师回答'
    page, api = sel_page(frames=[reply_frame("literal-text", source_text, 1)])
    page.locator('.stage-list [data-stage="review"]').click()
    page.locator("#openPerformancePreview").click()
    expect(page.locator(".preview-teacher-reply")).to_have_text(source_text)
    expect(page.locator(".preview-teacher-reply img")).to_have_count(0)
    page.locator(".preview-teacher-reply").click()
    expect(page.locator("#performancePreview").get_by_role("status")).to_have_text("本段预览结束")
    assert api.posts == []


def test_real_service_sel_restarts_previews_and_switches_back_without_changing_identity(
    profile_browser, settings, tmp_path
):
    from test_http_api import api as production_api

    resource_index = tmp_path / "synthetic-resources.json"
    resource_index.write_text(
        '{"bg":{"BG_Black":1},"characters":[],"sounds":[],"enums":{}}', encoding="utf-8"
    )
    isolated = replace(settings, resource_index=resource_index)
    context = profile_browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.set_default_timeout(30000)
    errors, writes = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "request",
        lambda request: writes.append(request.url)
        if request.method not in {"GET", "HEAD"}
        else None,
    )
    try:
        with production_api(isolated) as base:
            page.goto(base, wait_until="domcontentloaded")
            expect(page.locator("#serviceState")).to_contain_text(
                "halocue-production", timeout=30000
            )
            page.locator('[data-source-tab="manual"]').click()
            page.locator("#projectName").fill("老师呈现浏览器验收")
            page.locator("#scriptText").fill(
                "Sensei: 第一句，先出发。\nSensei: 第二句，走这边。\n店员: 欢迎光临。\nSensei: 最后一句，谢谢。\n"
            )
            page.get_by_role("button", name="建立制作任务", exact=True).click()
            expect(page.locator("#page-mapping")).to_be_visible()
            open_teacher(page)
            page.get_by_role("radio", name="Sel 回答", exact=True).check()
            with page.expect_response(
                lambda response: response.url.endswith("/cast-bindings")
                and response.request.method == "POST"
            ) as binding:
                page.get_by_role("button", name="创建并绑定老师", exact=True).click()
            selected = binding.value.json()
            assert binding.value.status == 200
            identity = selected["draft"]["cast"]["teacher_identity"]
            original_cards = [
                (card["card_id"], card["current"]) for card in selected["draft"]["cards"]
            ]
            expect(page.locator("#mappingDialog")).not_to_be_visible()
            page.locator('.mapping-edit[data-speaker="店员"]').click()
            page.get_by_role("button", name="无立绘角色", exact=True).click()
            expect(page.locator("#mappingDialog")).not_to_be_visible()

        with production_api(isolated) as base:
            page.goto(base, wait_until="domcontentloaded")
            expect(page.locator("#serviceState")).to_contain_text(
                "halocue-production", timeout=30000
            )
            page.locator('.stage-list [data-stage="source"]').click()
            page.locator(f'[data-run-id="{selected["run"]["run_id"]}"]').click()
            expect(page.locator("#page-review")).to_be_visible()
            page.locator('.stage-list [data-stage="mapping"]').click()
            page.locator('.mapping-edit[data-speaker="Sensei"]').click()
            expect(page.get_by_role("radio", name="Sel 回答", exact=True)).to_be_checked()
            page.locator('#mappingDialog [data-close-dialog="mappingDialog"]').click()
            page.locator('.stage-list [data-stage="review"]').click()
            write_count = len(writes)
            page.locator("#openPerformancePreview").click()
            page.get_by_role("button", name="第一句，先出发。", exact=True).click()
            page.get_by_role("button", name="第二句，走这边。", exact=True).click()
            expect(page.locator(".preview-dialogue > strong")).to_have_text("店员")
            page.locator("#previewNext").click()
            page.get_by_role("button", name="最后一句，谢谢。", exact=True).click()
            expect(page.locator("#performancePreview").get_by_role("status")).to_have_text(
                "本段预览结束"
            )
            assert len(writes) == write_count
            page.locator("#performancePreviewDialog [data-close-dialog]").click()
            page.locator('.stage-list [data-stage="mapping"]').click()
            page.locator('.mapping-edit[data-speaker="Sensei"]').click()
            page.get_by_role("radio", name="普通对白（槽 0）", exact=True).check()
            page.get_by_role("button", name="保存老师身份", exact=True).click()
            page.locator("#actionConfirmAccept").click()
            expect(page.locator("#mappingDialog")).not_to_be_visible()
            detail = context.request.get(
                f"{base}/api/v1/production-runs/{selected['run']['run_id']}"
            ).json()
            assert detail["draft"]["cast"]["teacher_identity"] == identity
            assert detail["draft"]["cast"]["teacher_presentation"]["mode"] == "slot_zero"
            assert [
                (card["card_id"], card["current"]) for card in detail["draft"]["cards"]
            ] == original_cards
            page.locator('.stage-list [data-stage="review"]').click()
            page.locator("#openPerformancePreview").click()
            expect(page.locator(".preview-dialogue > strong")).to_have_text("老师")
            expect(page.locator(".preview-dialogue > p")).to_have_text("第一句，先出发。")
            expect(page.locator(".preview-teacher-reply")).to_have_count(0)
    finally:
        context.close()
    assert errors == []
