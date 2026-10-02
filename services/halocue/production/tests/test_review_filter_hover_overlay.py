"""Regression coverage for review-filter hover obscuring nearby review content."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

pytest_plugins = ["test_embedded_workbench_ui"]


@pytest.mark.parametrize("filter_name", ["all", "pending"])
def test_review_filter_hover_keeps_help_disclosure_compact_and_in_flow(embedded_page, filter_name):
    page, api = embedded_page("format_only", width=1398, height=786, review_cards=18, theme="dark")
    page.locator('.embedded-production-shell [data-stage="review"]').click()

    filter_button = page.locator(f'.filterbar [data-filter="{filter_name}"]')
    guide = page.locator("#reviewCommandGuide")
    timeline = page.locator("#backgroundTimeline")
    expect(filter_button).to_be_visible()
    assert guide.get_attribute("open") is None

    filter_button.hover()
    page.wait_for_timeout(100)

    guide_box = guide.bounding_box()
    timeline_box = timeline.bounding_box()
    assert guide_box is not None and timeline_box is not None
    assert guide_box["height"] <= 34, guide_box
    assert timeline_box["y"] >= guide_box["y"] + guide_box["height"], (guide_box, timeline_box)

    page.locator("#reviewCommandGuide > summary").click()
    expect(guide).to_have_attribute("open", "")
    expect(guide.locator("p")).to_be_visible()
    guide_box = guide.bounding_box()
    timeline_box = timeline.bounding_box()
    assert guide_box is not None and timeline_box is not None
    assert timeline_box["y"] >= guide_box["y"] + guide_box["height"], (guide_box, timeline_box)
    assert api.posts == []


@pytest.mark.parametrize(
    ("theme", "expected"),
    [
        (
            "dark",
            {
                "background": "rgb(37, 45, 57)",
                "color": "rgb(201, 212, 223)",
                "border": "rgb(57, 70, 86)",
            },
        ),
        (
            "light",
            {
                "background": "rgb(247, 250, 248)",
                "color": "rgb(64, 91, 78)",
                "border": "rgb(215, 226, 220)",
            },
        ),
    ],
)
def test_background_picker_empty_state_matches_theme(embedded_page, theme, expected):
    page, api = embedded_page("format_only", width=1398, height=786, theme=theme)
    page.route(
        "**/resources/backgrounds?*",
        lambda route: route.fulfill(
            json={
                "items": [],
                "total": 0,
                "offset": 0,
                "has_more": False,
                "scene_context": {
                    "title": "测试场景 · 午后",
                    "requirements": {},
                    "sources": {"place": "场景标题"},
                    "counts": {"match": 0, "unknown": 0, "conflict": 0},
                    "read_only": True,
                },
            }
        ),
    )
    page.locator('.embedded-production-shell [data-stage="review"]').click()
    page.locator('[data-card-id="scene-1"]').click()
    page.locator("#sceneChooseOfficialBackground").click()

    empty_state = page.locator("#resourceResults > .empty")
    expect(empty_state).to_be_visible()
    expect(page.locator("#resourceSceneSummary")).to_contain_text("测试场景 · 午后")
    styles = empty_state.evaluate(
        "el => ({background: getComputedStyle(el).backgroundColor, "
        "color: getComputedStyle(el).color, border: getComputedStyle(el).borderColor})"
    )
    assert styles == expected
    screenshot_dir = os.environ.get("HALOCUE_TEST_SCREENSHOT_DIR")
    if theme == "dark" and screenshot_dir:
        screenshot_path = Path(screenshot_dir) / "aa-background-picker-empty-dark-2026-09-29.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot_path))
    assert api.posts == []
