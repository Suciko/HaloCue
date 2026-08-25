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
            assert page.locator("#menu-button").count() == 0
            stage_box = page.locator("#preview-stage").bounding_box()
            scale_probe = page.locator("#preview-stage").evaluate(
                "element => ({ scale: Number.parseFloat(getComputedStyle(element).getPropertyValue('--stage-scale')), name: parseFloat(getComputedStyle(document.querySelector('#speaker-name')).fontSize), club: parseFloat(getComputedStyle(document.querySelector('#club-name')).fontSize), text: parseFloat(getComputedStyle(document.querySelector('#dialogue-text')).fontSize) })"
            )
            assert abs(scale_probe["scale"] - stage_box["width"] / 2560) < 0.002
            assert abs(scale_probe["name"] - 48 * scale_probe["scale"]) < 0.2
            assert abs(scale_probe["club"] - 36 * scale_probe["scale"]) < 0.2
            assert abs(scale_probe["text"] - 44 * scale_probe["scale"]) < 0.2
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
            assert page.locator("#speaker-name").inner_text() == "领航员"
            assert "欢迎来到 StoryForge" in page.locator("#dialogue-text").inner_text()
            assert page.locator('.actor-slot.is-active[data-slot="3"]').count() == 1

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
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)
