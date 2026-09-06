"""Teacher mapping controls through the production page and HTTP contract."""

from __future__ import annotations

import copy
import os
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import test_direction_profile_ui as shared_ui

from test_direction_profile_ui import (
    ProductionApiFixture,
    expect,
    run_reply,
)


profile_browser = shared_ui.profile_browser
ui_url = shared_ui.ui_url
PRESETS = [
    {"id": "sensei_shale", "display_name": "sensei", "organization": "沙勒"},
    {"id": "sensei_xialai", "display_name": "sensei", "organization": "夏莱"},
    {"id": "teacher_shale", "display_name": "老师", "organization": "沙勒"},
    {"id": "teacher_xialai", "display_name": "老师", "organization": "夏莱"},
    {"id": "custom", "display_name": None, "organization": None},
]
CHARACTER_ID = "hc-teacher-00000000000000000000000000000001"


def teacher_run():
    result = run_reply()
    result["run"]["source_summary"]["speakers"] = ["Sensei", "老师", "店员"]
    result["draft"]["cast"]["detected_speakers"] = ["Sensei", "老师", "店员"]
    return result


class TeacherApiFixture(ProductionApiFixture):
    def __init__(self, *, supported=True):
        super().__init__(teacher_run())
        self.supported = supported
        self.fail_save = False
        self.characters = []

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path.removeprefix("/api/v1")
        if request.method == "GET" and path.endswith("/resources/characters"):
            route.fulfill(json={"items": self.characters})
            return
        if path == "/capabilities":
            capability = {}
            if self.supported:
                capability["teacher_identity"] = {
                    "schema_version": "teacher-identity/1.0",
                    "presentation": "slot_zero",
                    "presets": PRESETS,
                }
            route.fulfill(json={"capabilities": capability})
            return
        if request.method == "POST" and path.endswith("/cast-bindings"):
            payload = request.post_data_json
            self.posts.append((path, parsed.query, payload))
            if self.fail_save:
                route.fulfill(
                    status=409,
                    json={"error": {"code": "revision_conflict", "message": "草稿已更新"}},
                )
                return
            selection = payload["mapping"]
            cast = self.result["draft"]["cast"]
            if selection["kind"] == "teacher":
                preset = next(item for item in PRESETS if item["id"] == selection["preset_id"])
                identity = {
                    "schema_version": "teacher-identity/1.0",
                    "character_id": CHARACTER_ID,
                    "preset_id": preset["id"],
                    "display_name": selection.get("display_name", preset["display_name"]),
                    "organization": selection.get("organization", preset["organization"]),
                }
                cast["teacher_identity"] = identity
                aliases = {
                    key for key, value in cast["cast"].items() if value.get("role") == "teacher"
                } | {payload["speaker"]}
                for speaker in aliases:
                    cast["cast"][speaker] = {
                        "kind": "voice",
                        "role": "teacher",
                        "id": CHARACTER_ID,
                        "name": identity["display_name"],
                        "club": identity["organization"],
                        "portrait": False,
                    }
            else:
                cast["cast"][payload["speaker"]] = copy.deepcopy(selection)
            self.result["draft"]["draft_version"] += 1
            route.fulfill(json=self.result)
            return
        super().handle(route)


@pytest.fixture
def teacher_page(profile_browser, ui_url):
    context = profile_browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def open_page(*, supported=True):
        api = TeacherApiFixture(supported=supported)
        page.route("**/api/v1/**", api.handle)
        page.add_init_script("localStorage.setItem('halocue.currentRunId', 'run-synthetic');")
        page.goto(ui_url, wait_until="networkidle")
        expect(page.locator("#page-mapping")).to_be_visible()
        return page, api

    yield open_page
    context.close()
    assert errors == []


def open_teacher(page, speaker="Sensei"):
    page.locator(f'.mapping-edit[data-speaker="{speaker}"]').click()
    page.get_by_role("button", name="老师身份", exact=True).click()


def test_teacher_preset_requires_explicit_save_and_restores_from_draft(teacher_page):
    page, api = teacher_page()
    open_teacher(page)
    selector = page.get_by_label("老师名称 / 组织")
    expect(selector.locator("option")).to_have_text(
        ["sensei / 沙勒", "sensei / 夏莱", "老师 / 沙勒", "老师 / 夏莱", "自定义"]
    )
    selector.select_option("teacher_xialai")
    assert api.posts == []
    page.get_by_role("button", name="创建并绑定老师", exact=True).click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    assert api.posts == [
        (
            "/production-runs/run-synthetic/cast-bindings",
            "",
            {
                "speaker": "Sensei",
                "expected_draft_version": 1,
                "mapping": {
                    "kind": "teacher",
                    "schema_version": "teacher-identity/1.0",
                    "preset_id": "teacher_xialai",
                },
            },
        )
    ]
    expect(page.locator("#mappingList")).to_contain_text("老师 / 夏莱")
    page.reload(wait_until="networkidle")
    page.locator('.mapping-edit[data-speaker="Sensei"]').click()
    expect(selector).to_have_value("teacher_xialai")
    expect(page.get_by_role("button", name="保存老师身份", exact=True)).to_be_visible()


def test_custom_identity_change_confirms_all_bound_aliases_and_keeps_empty_org(teacher_page):
    page, api = teacher_page()
    open_teacher(page)
    page.get_by_role("button", name="创建并绑定老师", exact=True).click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    open_teacher(page, "老师")
    page.get_by_role("button", name="保存老师身份", exact=True).click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    assert len(api.posts) == 2
    page.locator('.mapping-edit[data-speaker="Sensei"]').click()
    page.get_by_label("老师名称 / 组织").select_option("custom")
    page.get_by_label("自定义名称").fill("定制老师")
    page.get_by_label("自定义组织").fill("")
    page.get_by_role("button", name="保存老师身份", exact=True).click()
    expect(page.locator("#actionConfirmDialog")).to_be_visible()
    expect(page.locator("#actionConfirmBody")).to_contain_text("Sensei")
    expect(page.locator("#actionConfirmBody")).to_contain_text("老师")
    assert len(api.posts) == 2
    page.locator("#actionConfirmDialog").get_by_role("button", name="取消", exact=True).click()
    assert len(api.posts) == 2
    expect(page.get_by_label("自定义名称")).to_have_value("定制老师")
    page.get_by_role("button", name="保存老师身份", exact=True).click()
    page.locator("#actionConfirmAccept").click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    assert api.posts[-1][2] == {
        "speaker": "Sensei",
        "expected_draft_version": 3,
        "mapping": {
            "kind": "teacher",
            "schema_version": "teacher-identity/1.0",
            "preset_id": "custom",
            "display_name": "定制老师",
            "organization": "",
        },
    }
    page.reload(wait_until="networkidle")
    page.locator('.mapping-edit[data-speaker="老师"]').click()
    expect(page.get_by_label("老师名称 / 组织")).to_have_value("custom")
    expect(page.get_by_label("自定义名称")).to_have_value("定制老师")
    expect(page.get_by_label("自定义组织")).to_have_value("")


@pytest.mark.parametrize("preset", PRESETS[:4], ids=lambda preset: preset["id"])
def test_each_preset_submits_identity_selection_without_display_override(teacher_page, preset):
    page, api = teacher_page()
    open_teacher(page)
    page.get_by_label("老师名称 / 组织").select_option(preset["id"])
    page.get_by_role("button", name="创建并绑定老师", exact=True).click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    assert api.posts[0][2]["mapping"] == {
        "kind": "teacher",
        "schema_version": "teacher-identity/1.0",
        "preset_id": preset["id"],
    }


def test_unsupported_teacher_capability_preserves_plain_voice_mapping(teacher_page):
    page, api = teacher_page(supported=False)
    page.locator('.mapping-edit[data-speaker="店员"]').click()
    expect(page.get_by_role("button", name="老师身份", exact=True)).not_to_be_visible()
    page.get_by_role("button", name="无立绘角色", exact=True).click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    assert api.posts[0][2]["mapping"] == {"kind": "voice"}


def test_blank_custom_name_is_rejected_and_server_conflict_preserves_form(teacher_page):
    page, api = teacher_page()
    open_teacher(page)
    page.get_by_label("老师名称 / 组织").select_option("custom")
    page.get_by_label("自定义名称").fill("   ")
    page.get_by_role("button", name="创建并绑定老师", exact=True).click()
    assert api.posts == []
    expect(page.locator("#mappingDialog")).to_be_visible()
    page.get_by_label("自定义名称").fill("本地老师")
    api.fail_save = True
    page.get_by_role("button", name="创建并绑定老师", exact=True).click()
    expect(page.locator("#mappingDialogStatus")).to_contain_text("请关闭后重新确认")
    expect(page.get_by_label("自定义名称")).to_have_value("本地老师")
    expect(page.get_by_role("button", name="创建并绑定老师", exact=True)).to_be_enabled()
    assert len(api.posts) == 1

    api.fail_save = False
    page.get_by_role("button", name="创建并绑定老师", exact=True).click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    page.locator('.mapping-edit[data-speaker="Sensei"]').click()
    page.get_by_label("自定义名称").fill("   ")
    page.get_by_role("button", name="保存老师身份", exact=True).click()
    page.locator('#mappingDialog [data-close-dialog="mappingDialog"]').click()
    page.locator('.mapping-edit[data-speaker="Sensei"]').click()
    expect(page.get_by_label("自定义名称")).to_have_value("本地老师")
    page.get_by_role("button", name="保存老师身份", exact=True).click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()


def test_teacher_resource_is_not_offered_as_a_visible_portrait(teacher_page):
    page, api = teacher_page()
    api.characters = [
        {"identifier": CHARACTER_ID, "name": "登记老师", "role": "teacher"},
        {"identifier": "portrait-actor", "name": "演示角色", "face_count": 2},
    ]
    page.locator('.mapping-edit[data-speaker="店员"]').click()
    expect(page.locator("#characterResults")).to_contain_text("演示角色")
    expect(page.locator(f'[data-character-id="{CHARACTER_ID}"]')).to_have_count(0)
    page.locator('[data-character-id="portrait-actor"]').click()
    expect(page.locator("#mappingDialog")).not_to_be_visible()
    assert api.posts[0][2]["mapping"]["kind"] == "portrait"
    assert "role" not in api.posts[0][2]["mapping"]


@pytest.mark.parametrize("width", [1280, 390, 320])
def test_teacher_custom_fields_fit_desktop_and_mobile(teacher_page, tmp_path, width):
    page, api = teacher_page()
    page.set_viewport_size({"width": width, "height": 900})
    open_teacher(page)
    page.get_by_label("老师名称 / 组织").select_option("custom")
    page.get_by_label("自定义名称").fill("老师")
    page.get_by_label("自定义组织").fill("夏莱")
    for selector in (
        "#mappingDialog",
        "#teacherPreset",
        "#teacherDisplayName",
        "#teacherOrganization",
        "#saveTeacherIdentity",
    ):
        bounds = page.locator(selector).bounding_box()
        assert bounds and 0 <= bounds["x"] and bounds["x"] + bounds["width"] <= width
    assert page.locator("#mappingDialog").evaluate("el => el.scrollWidth <= el.clientWidth")
    assert page.locator("#saveTeacherIdentity").bounding_box()["height"] <= 64
    screenshots = Path(os.environ.get("HALOCUE_TEST_SCREENSHOT_DIR") or tmp_path)
    screenshots.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshots / f"teacher-custom-{width}.png"))
    assert api.posts == []


def test_real_service_teacher_creation_reopen_and_preview(profile_browser, settings, tmp_path):
    from test_http_api import api as production_api

    resource_index = tmp_path / "synthetic-resources.json"
    resource_index.write_text(
        '{"bg":{"BG_Black":1},"characters":[],"sounds":[],"enums":{}}',
        encoding="utf-8",
    )
    isolated = replace(settings, resource_index=resource_index)
    context = profile_browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.set_default_timeout(30000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        with production_api(isolated) as base:
            page.goto(base, wait_until="domcontentloaded")
            expect(page.locator("#serviceState")).to_contain_text(
                "halocue-production", timeout=30000
            )
            page.locator('[data-source-tab="manual"]').click()
            page.locator("#projectName").fill("老师身份浏览器验收")
            page.locator("#scriptText").fill("Sensei: 一起出发吧。\n店员: 欢迎光临。\n")
            page.get_by_role("button", name="建立制作任务", exact=True).click()
            expect(page.locator("#page-mapping")).to_be_visible()
            open_teacher(page)
            page.get_by_label("老师名称 / 组织").select_option("teacher_xialai")
            with page.expect_response(
                lambda response: response.url.endswith("/cast-bindings")
                and response.request.method == "POST"
            ) as binding_response:
                page.get_by_role("button", name="创建并绑定老师", exact=True).click()
            selected = binding_response.value.json()
            assert binding_response.value.status == 200
            identity = selected["draft"]["cast"]["teacher_identity"]
            assert identity["character_id"].startswith("hc-teacher-")
            expect(page.locator("#mappingDialog")).not_to_be_visible()
            page.locator('.mapping-edit[data-speaker="店员"]').click()
            page.get_by_role("button", name="无立绘角色", exact=True).click()
            expect(page.locator("#mappingDialog")).not_to_be_visible()

        # A fresh service instance reads persisted draft data, not a route double.
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
            expect(page.get_by_label("老师名称 / 组织")).to_have_value("teacher_xialai")
            details = context.request.get(
                f"{base}/api/v1/production-runs/{selected['run']['run_id']}"
            ).json()
            assert details["draft"]["cast"]["teacher_identity"] == identity
            page.locator("#mappingDialog").get_by_role("button", name="关闭", exact=True).click()
            page.locator('.stage-list [data-stage="review"]').click()
            page.locator("#openPerformancePreview").click()
            expect(page.locator(".preview-dialogue > strong")).to_have_text("老师")
            expect(page.locator(".preview-speaker-organization")).to_have_text("夏莱")
            expect(page.locator(".preview-dialogue > p")).to_have_text("一起出发吧。")
            screenshots = Path(os.environ.get("HALOCUE_TEST_SCREENSHOT_DIR") or tmp_path)
            screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshots / "teacher-real-service-preview.png"))
            page.locator("#previewNext").click()
            expect(page.locator(".preview-dialogue > strong")).to_have_text("店员")
            expect(page.locator(".preview-speaker-organization")).to_have_count(0)
            page.locator("#performancePreviewDialog").get_by_role(
                "button", name="关闭", exact=True
            ).click()
            page.locator('.stage-list [data-stage="mapping"]').click()
            page.locator('.mapping-edit[data-speaker="Sensei"]').click()
            page.get_by_label("老师名称 / 组织").select_option("custom")
            page.get_by_label("自定义组织").fill("")
            page.get_by_role("button", name="保存老师身份", exact=True).click()
            page.locator("#actionConfirmAccept").click()
            expect(page.locator("#mappingDialog")).not_to_be_visible()
            page.locator('.stage-list [data-stage="review"]').click()
            page.locator("#openPerformancePreview").click()
            expect(page.locator(".preview-dialogue > strong")).to_have_text("老师")
            expect(page.locator(".preview-speaker-organization")).to_have_count(0)
            page.set_viewport_size({"width": 390, "height": 900})
            page.screenshot(path=str(screenshots / "teacher-real-service-empty-org-390.png"))
    finally:
        context.close()
    assert errors == []
