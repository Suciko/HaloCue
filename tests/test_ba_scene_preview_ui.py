from __future__ import annotations

import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PREVIEW_ROOT = REPO_ROOT / "apps" / "desktop-client" / "scene-preview"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def do_GET(self):  # noqa: N802 - inherited HTTP handler API
        if self.path.startswith("/slow-background.png"):
            time.sleep(0.45)
            self.path = "/assets/demo-conference-room.jpg"
        return super().do_GET()


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
    assert reference["timeline_schema_version"] == "render-timeline/1.0"
    assert reference["viewport"] == {"width": 1280, "height": 720}
    assert reference["design_canvas"] == {"width": 2560, "height": 1440}
    assert reference["target_event_index"] == 0
    assert reference["resolved_frame"] == 35
    assert reference["spine_time_ms"] == 1166.667
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
    assert descriptor["actors"][0]["stage_media"]["scale"] == 1.704
    assert descriptor["actors"][0]["stage_media"]["offset_y"] == 1038
    assert descriptor["actors"][4]["stage_media"]["animation"] == "00"
    assert descriptor["actors"][4]["stage_media"]["scale"] == 2.266
    assert descriptor["actors"][4]["stage_media"]["offset_y"] == 766
    assert descriptor["events"][0]["kind"] == "dialogue"
    assert descriptor["background"]["zoom"] == 1.068
    assert descriptor["presentation"]["overlay_controls"]["auto_label"] == "自动"
    assert descriptor["presentation"]["overlay_controls"]["menu_label"] == "菜单"
    assert descriptor["presentation"]["frame_rate"] == 30


def test_realtime_spine_measures_the_selected_animation_pose():
    source = (PREVIEW_ROOT / "spine-preview.js").read_text(encoding="utf-8")
    select_start = source.index("    selectAnimation() {")
    measure_start = source.index("    resizeAndMeasure() {")
    resolution_start = source.index("    applyCanvasResolution(")
    render_start = source.index("    render() {")
    dispose_start = source.index("    dispose() {")

    select_body = source[select_start:measure_start]
    measure_body = source[measure_start:resolution_start]
    render_body = source[render_start:dispose_start]

    assert "state.setAnimation(0, name, true);" in select_body
    assert "state.update(0);" in select_body
    assert "state.apply(skeleton);" in select_body
    assert "setToSetupPose" not in measure_body
    assert "const pad = 1;" in render_body
    assert "setPaused(paused)" in source
    assert "seek(seconds)" in source
    assert 'document.addEventListener("visibilitychange"' in source


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
            page.wait_for_function(
                "() => document.querySelector('#dialogue-copy').innerText !== ''"
            )
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
                    const speakerLine = document.querySelector('.speaker-line');
                    const speakerLineRect = speakerLine.getBoundingClientRect();
                    const speakerLineStyle = getComputedStyle(speakerLine, '::after');
                    return {
                        scale: Number.parseFloat(getComputedStyle(stage).getPropertyValue('--stage-scale')),
                        panel: box('.dialogue-panel'),
                        speaker: box('#speaker-name'),
                        secondary: box('#club-name'),
                        text: box('#dialogue-text'),
                        shade: box('.dialogue-shade'),
                        shadeBackground: getComputedStyle(document.querySelector('.dialogue-shade')).backgroundImage,
                        slot1: center('.actor-slot[data-slot="1"]'),
                        slot5: center('.actor-slot[data-slot="5"]'),
                        auto: box('#auto-button'),
                        menu: box('#menu-button'),
                        speakerLineBefore: getComputedStyle(document.querySelector('.speaker-line'), '::before').content,
                        speakerLineAfter: getComputedStyle(document.querySelector('.speaker-line'), '::after').content,
                        speakerDivider: {
                            x: (speakerLineRect.x + Number.parseFloat(speakerLineStyle.left) - sr.x) / sr.width,
                            y: (speakerLineRect.y + Number.parseFloat(speakerLineStyle.top) - sr.y) / sr.height,
                            right: (speakerLineRect.right - Number.parseFloat(speakerLineStyle.right) - sr.x) / sr.width,
                            height: Number.parseFloat(speakerLineStyle.height) / sr.height,
                            color: speakerLineStyle.backgroundColor,
                        },
                        overlayLabelFilter: getComputedStyle(document.querySelector('#auto-button .stage-overlay-label')).filter,
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
            assert metrics["speakerLineBefore"] == '\"\"'
            assert metrics["speakerLineAfter"] == '\"\"'
            assert abs(metrics["speakerDivider"]["x"] - 0.1) < x_tolerance
            assert abs(metrics["speakerDivider"]["y"] - 376 / 478) < y_tolerance
            assert abs(metrics["speakerDivider"]["right"] - 2335 / 2560) < x_tolerance
            assert abs(metrics["speakerDivider"]["height"] - 3 / 1440) < y_tolerance
            assert metrics["speakerDivider"]["color"] == "rgba(217, 232, 245, 0.2)"
            assert metrics["overlayLabelFilter"] == "none"
            assert metrics["shadeBackground"].count("linear-gradient") == 1
            assert "0.84" in metrics["shadeBackground"]
            assert page.locator(".render-options").evaluate(
                "element => getComputedStyle(element).opacity"
            ) == "0"
            assert page.locator("#speaker-name").inner_text() == "优香"
            assert page.locator("#club-name").inner_text() == "研讨会"
            assert page.locator("#auto-button .stage-overlay-label").inner_text() == "自动"
            assert page.locator("#menu-button .stage-overlay-label").inner_text() == "菜单"
            assert page.locator("#dialogue-copy").evaluate(
                "element => getComputedStyle(element).filter"
            ).startswith("blur(")
            assert page.locator("#auto-button").is_visible()
            assert page.locator("#menu-button").is_visible()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.browser
def test_reference_query_seeks_the_completed_p69_frame_without_clicks():
    playwright = pytest.importorskip("playwright.sync_api")
    server, thread = _serve_preview()
    descriptor = json.loads(
        (PREVIEW_ROOT / "official-p69.scene-descriptor.json").read_text(
            encoding="utf-8"
        )
    )
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
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.add_init_script(
                "window.HALO_CUE_SCENE_DESCRIPTOR = "
                + json.dumps(descriptor, ensure_ascii=False)
                + ";"
            )
            page.goto(
                f"http://127.0.0.1:{server.server_port}/index.html"
                "?renderer=static&reference=1"
            )
            page.wait_for_function(
                "() => document.querySelector('#preview-stage').dataset.currentEvent === 'event/yuuka-line'"
            )

            metrics = page.evaluate(
                """() => {
                    const controller = window.HaloCueScenePreview.controller;
                    const item = controller.timeline.events[0];
                    return {
                        frame: controller.state.frame,
                        expectedFrame: item.end_frame - 1,
                        schema: controller.timeline.schema_version,
                        playback: document.querySelector('#preview-stage').dataset.playback,
                    };
                }"""
            )
            assert metrics == {
                "frame": metrics["expectedFrame"],
                "expectedFrame": metrics["expectedFrame"],
                "schema": "render-timeline/1.0",
                "playback": "paused",
            }
            assert page.locator("#dialogue-copy").inner_text() == "哈？你们这是什么反应？"
            assert page.locator("#dialogue-caret").is_hidden()
            assert page.locator('.actor-slot.is-active[data-slot="1"]').count() == 1
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.browser
def test_controller_seeks_plays_and_pauses_the_multi_event_timeline():
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
            page.goto(
                f"http://127.0.0.1:{server.server_port}/index.html?renderer=static"
            )
            page.wait_for_function("() => Boolean(window.HaloCueScenePreview.controller)")

            page.evaluate("() => window.HaloCueScenePreview.controller.seekEvent(4)")
            assert page.locator("#dialogue-copy").inner_text().startswith(
                "The synthetic preview is ready."
            )
            assert page.locator('.actor-slot.is-active[data-slot="4"]').count() == 1
            assert page.locator('.actor-slot.is-visible[data-slot="3"]').count() == 1

            page.evaluate(
                "() => window.HaloCueScenePreview.controller.seekEvent(2, {complete: false})"
            )
            assert page.locator("#dialogue-copy").inner_text() == ""
            assert page.locator("#dialogue-caret").is_visible()
            assert page.locator('.actor-slot.is-active[data-slot="3"]').count() == 1
            start_frame = int(page.locator("#preview-stage").get_attribute("data-current-frame"))

            page.evaluate(
                "frame => window.HaloCueScenePreview.controller.play({fromFrame: frame})",
                start_frame,
            )
            page.wait_for_function(
                "start => Number(document.querySelector('#preview-stage').dataset.currentFrame) > start",
                arg=start_frame,
            )
            page.evaluate("() => window.HaloCueScenePreview.controller.pause()")
            paused_frame = page.locator("#preview-stage").get_attribute("data-current-frame")
            page.wait_for_timeout(100)
            assert page.locator("#preview-stage").get_attribute("data-current-frame") == paused_frame
            assert page.locator("#preview-stage").get_attribute("data-playback") == "paused"
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.browser
def test_preview_session_rejects_stale_controllers_and_delayed_media_callbacks():
    playwright = pytest.importorskip("playwright.sync_api")
    server, thread = _serve_preview()
    stale_descriptor = json.loads(
        (PREVIEW_ROOT / "example.scene-descriptor.json").read_text(encoding="utf-8")
    )
    current_descriptor = json.loads(json.dumps(stale_descriptor))
    stale_descriptor["scene_id"] = "scene/stale"
    current_descriptor["scene_id"] = "scene/current"
    for prefix, descriptor in (("stale", stale_descriptor), ("current", current_descriptor)):
        for index, event in enumerate(descriptor["events"]):
            event["event_id"] = f"event/{prefix}/{index}"
    stale_background = {
        **stale_descriptor["background"],
        "preview_uri": "./slow-background.png",
    }
    stale_descriptor["background"] = stale_background
    stale_descriptor["initial_background"] = dict(stale_background)
    current_background = {
        **current_descriptor["background"],
        "preview_uri": "./assets/demo-conference-room.png",
    }
    current_descriptor["background"] = current_background
    current_descriptor["initial_background"] = dict(current_background)

    try:
        with playwright.sync_playwright() as runtime:
            try:
                browser = runtime.chromium.launch(headless=True)
            except Exception as exc:  # pragma: no cover - depends on local browser install
                if "Executable doesn't exist" in str(exc):
                    pytest.skip("Playwright Chromium is not installed")
                raise
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(
                f"http://127.0.0.1:{server.server_port}/index.html?renderer=static"
            )
            page.wait_for_function("() => Boolean(window.HaloCueScenePreview.controller)")

            mounted = page.evaluate(
                """payload => {
                    const stale = window.HaloCueScenePreview.mount(payload.stale);
                    const current = window.HaloCueScenePreview.mount(payload.current);
                    current.seekFrame(0);
                    window.__stalePreviewController = stale;
                    window.__currentPreviewController = current;
                    return {
                        staleGeneration: stale.generation,
                        currentGeneration: current.generation,
                        staleCurrent: stale.isCurrent(),
                        currentCurrent: current.isCurrent(),
                    };
                }""",
                {"stale": stale_descriptor, "current": current_descriptor},
            )
            assert mounted["currentGeneration"] > mounted["staleGeneration"]
            assert mounted["staleCurrent"] is False
            assert mounted["currentCurrent"] is True
            page.wait_for_function(
                """() => document.querySelector('#stage-background')
                    .style.backgroundImage.includes('demo-conference-room.png')"""
            )

            stale_call = page.evaluate(
                """() => {
                    const stage = document.querySelector('#preview-stage');
                    const before = stage.dataset.currentEvent;
                    const result = window.__stalePreviewController.seekFrame(0);
                    return {before, after: stage.dataset.currentEvent, rejected: result === null};
                }"""
            )
            assert stale_call["rejected"] is True
            assert stale_call["after"] == stale_call["before"]

            page.wait_for_timeout(650)
            assert "demo-conference-room.png" in page.locator(
                "#stage-background"
            ).evaluate("element => element.style.backgroundImage")

            preserved = page.evaluate(
                """descriptor => {
                    const stage = document.querySelector('#preview-stage');
                    const generation = stage.dataset.previewGeneration;
                    let rejected = false;
                    try {
                        window.HaloCueScenePreview.mount(descriptor, undefined, {
                            performance: {schema_version: 'scene-performance/0.0'},
                        });
                    }
                    catch (_) { rejected = true; }
                    return {
                        rejected,
                        generationUnchanged: stage.dataset.previewGeneration === generation,
                        currentStillActive: window.__currentPreviewController.isCurrent(),
                    };
                }""",
                current_descriptor,
            )
            assert preserved == {
                "rejected": True,
                "generationUnchanged": True,
                "currentStillActive": True,
            }
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.browser
def test_capability_motion_and_emoticon_are_independent_preview_layers():
    playwright = pytest.importorskip("playwright.sync_api")
    server, thread = _serve_preview()
    descriptor = {
        "schema_version": "scene-descriptor/1.0",
        "scene_id": "scene/capability-layers",
        "actors": [
            {
                "slot": 1,
                "character_id": "character/alice",
                "display_name": "爱丽丝",
                "dialogue_name": "爱丽丝",
                "state": "hidden",
            },
            *[
                {"slot": slot, "character_id": None, "display_name": "", "state": "hidden"}
                for slot in range(2, 6)
            ],
        ],
        "events": [
            {
                "event_id": "event/alice-enter",
                "kind": "enter",
                "character_id": "character/alice",
                "slot": 1,
                "motion_id": "motion/nod",
            },
            {
                "event_id": "event/alice-line",
                "kind": "dialogue",
                "character_id": "character/alice",
                "text": "动作和表情符号是独立层。",
                "emoticon_id": "emoticon/bulb",
            },
            {
                "event_id": "event/screen-text",
                "kind": "halocue.ba:screen-text",
                "text": "统一事件模型",
                "duration_ms": 500,
            },
        ],
    }
    try:
        with playwright.sync_playwright() as runtime:
            try:
                browser = runtime.chromium.launch(headless=True)
            except Exception as exc:  # pragma: no cover - depends on local browser install
                if "Executable doesn't exist" in str(exc):
                    pytest.skip("Playwright Chromium is not installed")
                raise
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.add_init_script(
                "window.HALO_CUE_SCENE_DESCRIPTOR = "
                + json.dumps(descriptor, ensure_ascii=False)
                + ";"
            )
            page.goto(f"http://127.0.0.1:{server.server_port}/index.html?renderer=static")
            page.wait_for_selector(".actor-slot")

            page.locator("#preview-stage").click(position={"x": 640, "y": 160})
            actor = page.locator('.actor-slot[data-slot="1"]')
            assert actor.get_attribute("data-motion") == "motion/nod"
            assert actor.get_attribute("data-emoticon") == ""
            assert actor.locator(".actor-emoticon").is_hidden()

            page.locator("#preview-stage").click(position={"x": 640, "y": 160})
            assert actor.get_attribute("data-motion") == "motion/nod"
            assert actor.get_attribute("data-emoticon") == "emoticon/bulb"
            emoticon = actor.locator(".actor-emoticon")
            assert not emoticon.is_hidden()
            assert emoticon.get_attribute("data-state") == "emoticon/bulb"
            assert emoticon.locator(".actor-emoticon-symbol").inner_text() == "✦"

            # Advance once to finish the typewriter, then once to enter the
            # following visual-only event.
            page.locator("#preview-stage").click(position={"x": 640, "y": 160})
            page.locator("#preview-stage").click(position={"x": 640, "y": 160})
            assert page.locator("#screen-text-layer").is_visible()
            assert page.locator("#screen-text").inner_text() == "统一事件模型"
            assert page.locator(".dialogue-panel").is_hidden()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.browser
def test_editor_mode_exposes_resource_locator_and_calibration_guides():
    playwright = pytest.importorskip("playwright.sync_api")
    server, thread = _serve_preview()
    descriptor = json.loads(
        (PREVIEW_ROOT / "official-p69.scene-descriptor.json").read_text(
            encoding="utf-8"
        )
    )
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
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.add_init_script(
                "window.HALO_CUE_SCENE_DESCRIPTOR = "
                + json.dumps(descriptor, ensure_ascii=False)
                + ";"
            )
            page.goto(f"http://127.0.0.1:{server.server_port}/index.html?editor=1")
            page.wait_for_selector("#asset-inspector")
            page.wait_for_selector("#preview-stage.has-background-image")

            inspector = page.locator("#asset-inspector")
            assert inspector.evaluate("element => getComputedStyle(element).opacity") == "1"
            transport = page.locator("#timeline-transport")
            assert transport.evaluate("element => getComputedStyle(element).opacity") == "1"
            assert page.locator("#timeline-scrubber").get_attribute("max") == "35"
            page.locator("#timeline-reference").click()
            assert page.locator("#preview-stage").get_attribute("data-current-frame") == "35"
            assert page.locator("#timeline-position").inner_text() == "35 / 35"
            layout = page.evaluate(
                """() => {
                    const box = selector => document.querySelector(selector).getBoundingClientRect();
                    const overlaps = (left, right) => !(
                        left.right <= right.left || right.right <= left.left
                        || left.bottom <= right.top || right.bottom <= left.top
                    );
                    const stage = box('#preview-stage');
                    const inspector = box('#asset-inspector');
                    const timeline = box('#timeline-transport');
                    const options = box('.render-options');
                    return {
                        stageInspector: overlaps(stage, inspector),
                        stageTimeline: overlaps(stage, timeline),
                        timelineOptions: overlaps(timeline, options),
                    };
                }"""
            )
            assert layout == {
                "stageInspector": False,
                "stageTimeline": False,
                "timelineOptions": False,
            }
            page.locator("#timeline-play").click()
            page.wait_for_function(
                "() => document.querySelector('#preview-stage').dataset.playback === 'playing'"
            )
            page.locator("#timeline-play").click()
            assert page.locator("#preview-stage").get_attribute("data-playback") == "paused"
            rows = inspector.locator(".asset-resource-row")
            assert rows.count() == 2
            assert "character/yuuka" in rows.filter(has_text="优香").inner_text()
            assert "SPINE-FRAME" in rows.filter(has_text="优香").inner_text()
            assert "character/alice" in rows.filter(has_text="爱丽丝").inner_text()

            page.locator("#guides-toggle").check()
            assert page.locator("#calibration-guides").get_attribute("aria-hidden") == "false"
            assert page.locator(".calibration-slot-guide").count() == 5

            page.locator('.actor-slot[data-slot="5"]').click()
            assert page.locator("#inspector-selection").inner_text() == "已选 SLOT 5 · 爱丽丝"
            assert rows.filter(has_text="爱丽丝").get_attribute("class").find("is-selected") >= 0
            assert page.locator("#event-progress").inner_text() == "1 / 1"
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
            assert page.locator("#asset-inspector").evaluate(
                "element => getComputedStyle(element).opacity"
            ) == "0"
            assert page.locator("#timeline-transport").evaluate(
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
