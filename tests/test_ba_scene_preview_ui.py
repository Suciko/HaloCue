from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PREVIEW_ROOT = REPO_ROOT / "apps" / "desktop-client" / "scene-preview"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        return


def _serve_preview():
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(QuietHandler, directory=str(PREVIEW_ROOT)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_synthetic_descriptor_fixture_has_versioned_five_slot_shape():
    descriptor = json.loads(
        (PREVIEW_ROOT / "example.scene-descriptor.json").read_text(encoding="utf-8")
    )

    assert descriptor["schema_version"] == "scene-descriptor/1.0"
    assert descriptor["background"]["preview_uri"] == "./assets/demo-conference-room.png"
    assert descriptor["background"]["focus_x"] == 0.42
    assert descriptor["background"]["focus_y"] == 0.68
    assert not descriptor["background"]["preview_uri"].startswith("/")
    assert [actor["slot"] for actor in descriptor["actors"]] == [1, 2, 3, 4, 5]
    assert all(
        actor["resource_id"] is None or actor["resource_id"].startswith("synthetic/")
        for actor in descriptor["actors"]
    )


def test_official_p69_descriptor_locks_reference_frame_and_stage_media():
    descriptor = json.loads(
        (PREVIEW_ROOT / "official-p69.scene-descriptor.json").read_text(
            encoding="utf-8"
        )
    )

    assert descriptor["schema_version"] == "scene-descriptor/1.0"
    reference = descriptor["presentation"]["reference_frame"]
    assert reference["id"] == "official-p69-final-v9"
    assert reference["viewport"] == {"width": 1280, "height": 720}
    assert reference["design_canvas"] == {"width": 2560, "height": 1440}
    assert reference["target_event_index"] == 0
    assert reference["dialogue_complete"] is True
    assert reference["overlay_controls_visible"] is True
    assert reference["anchors"]["auto_button"] == {
        "x": 0.79375,
        "y": 0.025,
        "width": 0.09375,
        "height": 0.0625,
    }
    assert [actor["slot"] for actor in descriptor["actors"]] == [1, 2, 3, 4, 5]
    assert descriptor["actors"][0]["stage_media"]["animation"] == "06"
    assert descriptor["actors"][0]["stage_media"]["scale"] == 1.55
    assert descriptor["actors"][0]["stage_media"]["offset_y"] == 812
    assert descriptor["actors"][4]["stage_media"]["animation"] == "00"
    assert descriptor["actors"][4]["stage_media"]["scale"] == 1.62
    assert descriptor["actors"][4]["stage_media"]["offset_y"] == 216
    assert descriptor["events"][0]["kind"] == "dialogue"


@pytest.mark.browser
@pytest.mark.parametrize("viewport", [(640, 360), (1280, 720), (1920, 1080)])
def test_official_p69_reference_frame_keeps_normalized_geometry(
    viewport,
):
    playwright = pytest.importorskip("playwright.sync_api")
    server, thread = _serve_preview()
    descriptor = json.loads(
        (PREVIEW_ROOT / "official-p69.scene-descriptor.json").read_text(
            encoding="utf-8"
        )
    )
    # The public test uses synthetic raster stand-ins while preserving the
    # official descriptor's event, typography, overlay, and stage-media shape.
    descriptor["background"]["preview_uri"] = "./assets/demo-conference-room.jpg"
    for actor in descriptor["actors"]:
        media = actor.get("stage_media")
        if media:
            media["kind"] = "spine-frame"
            media["preview_uri"] = "./assets/demo-conference-room.png"
            media.pop("bundle_key", None)
            media.pop("animation", None)
    try:
        with playwright.sync_playwright() as runtime:
            try:
                browser = runtime.chromium.launch(headless=True)
            except Exception as exc:  # pragma: no cover - depends on local browser install
                if "Executable doesn't exist" in str(exc):
                    pytest.skip("Playwright Chromium is not installed")
                raise
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            page.add_init_script(
                "window.HALO_CUE_SCENE_DESCRIPTOR = "
                + json.dumps(descriptor, ensure_ascii=False)
                + ";"
            )
            page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
            page.wait_for_selector(".actor-slot")
            page.wait_for_selector("#preview-stage.has-background-image")
            page.wait_for_function(
                "() => document.querySelector('#preview-stage').dataset.mediaReady === 'ready'"
            )

            # One advance starts typewriter playback; the next commits the
            # same event to its deterministic completed frame.
            page.locator("#preview-stage").click(position={"x": viewport[0] / 2, "y": viewport[1] / 4})
            page.wait_for_timeout(55)
            assert page.locator("#dialogue-copy").inner_text() != ""
            assert page.locator("#dialogue-caret").is_visible()
            assert page.locator(".dialogue-panel").is_visible()
            assert page.locator(".actor-slot.is-active").get_attribute("data-slot") == "1"
            page.locator("#preview-stage").click(position={"x": viewport[0] / 2, "y": viewport[1] / 4})
            page.wait_for_function(
                "() => document.querySelector('#dialogue-copy').innerText === '哈？你们这是什么反应？'"
            )
            # The completed dialogue frame is measured after the spatial
            # entrance bridge, not during its 220ms translateY transition.
            page.wait_for_timeout(300)

            metrics = page.locator("#preview-stage").evaluate(
                """stage => {
                    const sr = stage.getBoundingClientRect();
                    const box = selector => {
                        const element = document.querySelector(selector);
                        const rect = element.getBoundingClientRect();
                        return {
                            x: (rect.x - sr.x) / sr.width,
                            y: (rect.y - sr.y) / sr.height,
                            width: rect.width / sr.width,
                            height: rect.height / sr.height,
                        };
                    };
                    const center = selector => {
                        const rect = document.querySelector(selector).getBoundingClientRect();
                        return (rect.x + rect.width / 2 - sr.x) / sr.width;
                    };
                    return {
                        scale: Number.parseFloat(getComputedStyle(stage).getPropertyValue('--stage-scale')),
                        panel: box('.dialogue-panel'),
                        speaker: box('#speaker-name'),
                        secondary: box('#club-name'),
                        text: box('#dialogue-text'),
                        shade: box('.dialogue-shade'),
                        slot1: center('.actor-slot[data-slot="1"]'),
                        slot5: center('.actor-slot[data-slot="5"]'),
                        auto: box('#auto-button'),
                        menu: box('#menu-button'),
                        locationHidden: document.querySelector('#location-label').hidden,
                        caretHidden: document.querySelector('#dialogue-caret').hidden,
                        activeSlot: document.querySelector('.actor-slot.is-active')?.dataset.slot || null,
                    };
                }"""
            )
            expected = descriptor["presentation"]["reference_frame"]["anchors"]
            x_tolerance = 1.1 / viewport[0]
            y_tolerance = 1.1 / viewport[1]
            assert abs(metrics["scale"] - viewport[0] / 2560) < 0.002
            assert abs(metrics["panel"]["x"] - expected["dialogue_panel"]["x"]) < x_tolerance
            assert abs(metrics["panel"]["y"] - expected["dialogue_panel"]["top"]) < y_tolerance
            assert abs(metrics["speaker"]["x"] - expected["speaker_name"]["x"]) < x_tolerance
            assert abs(metrics["speaker"]["y"] - expected["speaker_name"]["top"]) < y_tolerance
            assert abs(metrics["secondary"]["x"] - expected["secondary_identity"]["x"]) < x_tolerance
            assert abs(metrics["text"]["x"] - expected["dialogue_text"]["x"]) < x_tolerance
            assert abs(metrics["text"]["y"] - expected["dialogue_text"]["top"]) < y_tolerance
            assert abs(metrics["shade"]["y"] - expected["dialogue_shade"]["top"]) < y_tolerance
            assert abs(metrics["slot1"] - expected["slot_1_center"]["x"]) < x_tolerance
            assert abs(metrics["slot5"] - expected["slot_5_center"]["x"]) < x_tolerance
            for key in ("auto", "menu"):
                for field in ("x", "width"):
                    assert abs(metrics[key][field] - expected[f"{key}_button"][field]) < x_tolerance
                for field in ("y", "height"):
                    assert abs(metrics[key][field] - expected[f"{key}_button"][field]) < y_tolerance
            assert metrics["locationHidden"] is True
            assert metrics["caretHidden"] is True
            assert metrics["activeSlot"] == "1"
            assert page.locator(".render-options").evaluate(
                "element => getComputedStyle(element).opacity"
            ) == "0"
            assert page.locator("#speaker-name").inner_text() == "优香"
            assert page.locator("#club-name").inner_text() == "研讨会"
            assert page.locator("#auto-button").is_visible()
            assert page.locator("#menu-button").is_visible()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.browser
def test_preview_renders_five_slots_advances_dialogue_and_switches_font(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    server, thread = _serve_preview()
    try:
        with playwright.sync_playwright() as runtime:
            try:
                browser = runtime.chromium.launch(headless=True)
            except Exception as exc:  # pragma: no cover - depends on local browser install
                if "Executable doesn't exist" in str(exc):
                    pytest.skip("Playwright Chromium is not installed")
                raise
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
            page.wait_for_selector(".actor-slot")
            page.wait_for_selector("#preview-stage.has-background-image")

            assert page.locator(".actor-slot").count() == 5
            assert page.locator(".actor-slot.is-visible").count() == 0
            assert page.locator("#auto-button").is_hidden() is True
            assert page.locator("#menu-button").is_hidden() is True
            assert page.locator(".render-options").evaluate(
                "element => getComputedStyle(element).opacity"
            ) == "0"
            page.locator("#auto-toggle").check()
            assert page.locator("#auto-button").is_hidden() is False
            page.locator("#auto-toggle").uncheck()
            page.locator("#menu-toggle").check()
            assert page.locator("#menu-button").is_hidden() is False
            page.locator("#menu-toggle").uncheck()
            stage_box = page.locator("#preview-stage").bounding_box()
            actor_slots = page.locator(".actor-slot").all()
            slot_centers = [
                (slot.bounding_box()["x"] + slot.bounding_box()["width"] / 2 - stage_box["x"])
                / stage_box["width"]
                for slot in actor_slots
            ]
            expected_slot_centers = [0.1875, 0.353, 0.5, 0.647, 0.8125]
            assert all(
                abs(actual - expected) < 0.003
                for actual, expected in zip(slot_centers, expected_slot_centers)
            )
            scale_probe = page.locator("#preview-stage").evaluate(
                "element => ({ scale: Number.parseFloat(getComputedStyle(element).getPropertyValue('--stage-scale')), name: parseFloat(getComputedStyle(document.querySelector('#speaker-name')).fontSize), club: parseFloat(getComputedStyle(document.querySelector('#club-name')).fontSize), text: parseFloat(getComputedStyle(document.querySelector('#dialogue-text')).fontSize) })"
            )
            assert abs(scale_probe["scale"] - stage_box["width"] / 2560) < 0.002
            assert abs(scale_probe["name"] - 68 * scale_probe["scale"]) < 0.2
            assert abs(scale_probe["club"] - 48 * scale_probe["scale"]) < 0.2
            assert abs(scale_probe["text"] - 56 * scale_probe["scale"]) < 0.2
            assert page.locator("#location-label").bounding_box()["x"] < 32
            location_box = page.locator("#location-label").bounding_box()
            assert 0.16 < location_box["y"] / stage_box["height"] < 0.19
            assert page.locator("#event-progress").is_hidden() is True
            assert page.locator("#preview-stage").get_attribute("data-font") == "noto"
            assert round(stage_box["width"] / stage_box["height"], 3) == 1.778
            assert page.locator("#stage-background").evaluate(
                "element => element.style.backgroundPosition"
            ) == "42% 68%"

            page.select_option("#font-select", "nowar")
            assert page.locator("#preview-stage").get_attribute("data-font") == "nowar"

            for _ in range(3):
                page.locator("#preview-stage").click(position={"x": 640, "y": 160})
            page.wait_for_function(
                "() => document.querySelector('#dialogue-text').innerText.includes('欢迎来到 StoryForge')"
            )
            assert page.locator("#speaker-name").inner_text() == "领航员"
            assert "欢迎来到 StoryForge" in page.locator("#dialogue-text").inner_text()
            assert page.locator('.actor-slot.is-active[data-slot="3"]').count() == 1
            dialogue_box = page.locator(".dialogue-panel").bounding_box()
            # Calibrated against the official 16:9 AA dialogue baseline.
            assert 0.707 < dialogue_box["y"] / stage_box["height"] < 0.715
            assert page.locator("#speaker-name").evaluate(
                "element => getComputedStyle(element).fontWeight"
            ) in {"600", "700"}
            assert page.locator("#club-name").evaluate(
                "element => getComputedStyle(element).color"
            ) == "rgb(112, 212, 255)"

            for _ in range(2):
                page.locator("#preview-stage").click(position={"x": 640, "y": 160})
            assert page.locator("#speaker-name").inner_text() == "成员四"
            assert page.locator('.actor-slot.is-active[data-slot="4"]').count() == 1

            # A later enter event must inherit the catalog actor metadata even
            # when the target slot previously contained another character.
            for _ in range(3):
                page.locator("#preview-stage").click(position={"x": 640, "y": 160})
            assert page.locator('.actor-slot[data-slot="5"] .actor-name').inner_text() == "成员四"

            # Background events are part of the same deterministic event
            # stream and must update the image without reloading the page.
            page.locator("#preview-stage").click(position={"x": 640, "y": 160})
            page.wait_for_function(
                """() => document.querySelector('#stage-background').style.backgroundImage.includes('demo-conference-room.jpg')"""
            )
            assert page.locator(".dialogue-panel").is_hidden() is True

            output_dir = REPO_ROOT / "acceptance-output"
            output_dir.mkdir(exist_ok=True)
            page.screenshot(path=str(output_dir / "synthetic-ba-scene-preview.png"), full_page=True)

            avatar_only = {
                "schema_version": "scene-descriptor/1.0",
                "scene_id": "scene/avatar-is-thumbnail",
                "actors": [
                    {"slot": 1, "character_id": "character/avatar", "display_name": "头像角色", "preview_uri": "./assets/demo-conference-room.png", "state": "hidden"},
                    *[{"slot": slot, "character_id": None, "display_name": "", "state": "hidden"} for slot in range(2, 6)],
                ],
                "events": [{"event_id": "event/enter", "kind": "enter", "character_id": "character/avatar", "slot": 1}],
            }
            page.evaluate("descriptor => window.HaloCueScenePreview.mount(descriptor)", avatar_only)
            page.locator("#preview-stage").click(position={"x": 640, "y": 160})
            assert page.locator('.actor-slot[data-slot="1"] .actor-image').get_attribute("src") in {"", None}

            stage_media = {
                **avatar_only,
                "scene_id": "scene/stage-media",
                "actors": [
                    {**avatar_only["actors"][0], "stage_media": {"kind": "spine-frame", "preview_uri": "./assets/demo-conference-room.png"}},
                    *avatar_only["actors"][1:],
                ],
            }
            page.evaluate("descriptor => window.HaloCueScenePreview.mount(descriptor)", stage_media)
            page.locator("#preview-stage").click(position={"x": 640, "y": 160})
            page.wait_for_function(
                "() => document.querySelector('.actor-slot[data-slot=\"1\"] .actor-image').complete"
            )
            assert page.locator('.actor-slot[data-slot="1"]').get_attribute("data-stage-media-kind") == "spine-frame"
            assert page.locator('.actor-slot[data-slot="1"] .actor-image').get_attribute("src").endswith("demo-conference-room.png")
            assert page.locator('.actor-slot[data-slot="1"]').evaluate(
                "element => getComputedStyle(element).getPropertyValue('--actor-media-scale').trim()"
            ) == "1.6"

            alias_descriptor = {
                **stage_media,
                "actors": [
                    {**stage_media["actors"][0], "dialogue_name": "爱丽丝", "alias": "勇者爱丽丝"},
                    *stage_media["actors"][1:],
                ],
                "events": [
                    {"event_id": "event/enter-alias", "kind": "enter", "character_id": "character/avatar", "slot": 1},
                    {"event_id": "event/alias-line", "kind": "dialogue", "character_id": "character/avatar", "text": "别名层级已就绪。"},
                ],
            }
            page.evaluate("descriptor => window.HaloCueScenePreview.mount(descriptor)", alias_descriptor)
            page.locator("#preview-stage").click(position={"x": 640, "y": 160})
            page.locator("#preview-stage").click(position={"x": 640, "y": 160})
            assert page.locator("#club-name").inner_text() == "勇者爱丽丝"
            assert page.locator("#club-name").get_attribute("data-kind") == "alias"
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)
