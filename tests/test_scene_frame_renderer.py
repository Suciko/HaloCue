from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import shutil
import sys
import threading

import pytest
from PIL import Image, ImageChops, ImageStat
from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = REPO_ROOT / "packages" / "project-model"
PRODUCTION_ROOT = REPO_ROOT / "services" / "halocue" / "production" / "src"
PREVIEW_ROOT = REPO_ROOT / "apps" / "desktop-client" / "scene-preview"
for source_root in (MODEL_ROOT, PRODUCTION_ROOT):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from halocue_production.scene_frame_renderer import (  # noqa: E402
    SceneFrameRenderError,
    render_scene_frame,
)
from halocue_production.scene_video_renderer import (  # noqa: E402
    encode_silent_mp4,
    render_scene_sequence,
)
from render_timeline import build_render_timeline  # noqa: E402
from scene_performance import build_scene_performance  # noqa: E402


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        return


@pytest.fixture
def preview_url():
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(QuietHandler, directory=str(PREVIEW_ROOT)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/index.html"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _descriptor(name: str) -> dict:
    return json.loads(
        (PREVIEW_ROOT / f"{name}.scene-descriptor.json").read_text(encoding="utf-8")
    )


def _synthetic_p69() -> dict:
    descriptor = _descriptor("official-p69")
    descriptor["background"]["preview_uri"] = "./assets/demo-conference-room.jpg"
    for actor in descriptor["actors"]:
        media = actor.get("stage_media")
        if not media:
            continue
        media["kind"] = "spine-frame"
        media["preview_uri"] = "./assets/demo-conference-room.png"
        media.pop("bundle_key", None)
        media.pop("animation", None)
    return descriptor


def test_renderer_rejects_remote_urls_mismatched_timelines_and_non_video_frames(tmp_path):
    descriptor = _descriptor("example")
    timeline = build_render_timeline(descriptor)
    performance = build_scene_performance(descriptor, timeline)
    output = tmp_path / "frame.png"

    with pytest.raises(SceneFrameRenderError, match="localhost"):
        render_scene_frame(
            preview_url="https://example.com/index.html",
            descriptor=descriptor,
            timeline=timeline,
            performance=performance,
            frame=0,
            output_path=output,
        )

    mismatched = json.loads(json.dumps(timeline))
    mismatched["scene_id"] = "scene/other"
    with pytest.raises(SceneFrameRenderError, match="scene_id"):
        render_scene_frame(
            preview_url="http://127.0.0.1:8898/index.html",
            descriptor=descriptor,
            timeline=mismatched,
            performance=performance,
            frame=0,
            output_path=output,
        )

    with pytest.raises(SceneFrameRenderError, match="16:9"):
        render_scene_frame(
            preview_url="http://127.0.0.1:8898/index.html",
            descriptor=descriptor,
            timeline=timeline,
            performance=performance,
            frame=0,
            output_path=output,
            width=1280,
            height=800,
        )

    broken_mapping = json.loads(json.dumps(performance))
    broken_mapping["source_map"][0]["operation_ids"] = ["operation/missing"]
    with pytest.raises(SceneFrameRenderError, match="operation mapping"):
        render_scene_frame(
            preview_url="http://127.0.0.1:8898/index.html",
            descriptor=descriptor,
            timeline=timeline,
            performance=broken_mapping,
            frame=0,
            output_path=output,
        )


@pytest.mark.browser
def test_offline_renderer_repeats_one_frame_and_handles_a_second_scene(
    browser,
    preview_url,
    tmp_path,
):
    descriptor = _descriptor("example")
    timeline = build_render_timeline(descriptor)
    performance = build_scene_performance(descriptor, timeline)
    reordered_timeline = json.loads(json.dumps(timeline, sort_keys=True))
    alice_frame = timeline["events"][2]["end_frame"] - 1
    bob_frame = timeline["events"][4]["end_frame"] - 1

    first = render_scene_frame(
        preview_url=preview_url,
        descriptor=descriptor,
        timeline=reordered_timeline,
        performance=performance,
        frame=alice_frame,
        output_path=tmp_path / "alice-a.png",
        renderer="static",
        browser=browser,
    )
    repeated = render_scene_frame(
        preview_url=preview_url,
        descriptor=descriptor,
        timeline=timeline,
        performance=performance,
        frame=alice_frame,
        output_path=tmp_path / "alice-b.png",
        renderer="static",
        browser=browser,
    )
    second_event = render_scene_frame(
        preview_url=preview_url,
        descriptor=descriptor,
        timeline=timeline,
        performance=performance,
        frame=bob_frame,
        output_path=tmp_path / "bob.png",
        renderer="static",
        browser=browser,
    )

    assert first.event_id == "event/alice-line"
    assert repeated.sha256 == first.sha256
    assert first.output_path.read_bytes() == repeated.output_path.read_bytes()
    assert second_event.event_id == "event/bob-line"
    assert second_event.sha256 != first.sha256
    assert (first.width, first.height, first.frame_rate) == (1280, 720, 30)
    assert list(tmp_path.glob(".*.tmp")) == []


@pytest.mark.browser
def test_offline_renderer_accepts_overlapping_timeline_and_uses_latest_active_event(
    browser,
    preview_url,
    tmp_path,
):
    descriptor = _descriptor("example")
    descriptor["events"].insert(
        2,
        {
            "event_id": "event/alice-nod",
            "kind": "character-motion",
            "character_id": "character/alice",
            "slot": 3,
            "motion_id": "motion/nod",
            "duration_ms": 500,
            "wait_for_completion": False,
        },
    )
    timeline = build_render_timeline(descriptor)
    performance = build_scene_performance(descriptor, timeline)

    result = render_scene_frame(
        preview_url=preview_url,
        descriptor=descriptor,
        timeline=timeline,
        performance=performance,
        frame=timeline["events"][2]["start_frame"],
        output_path=tmp_path / "overlap.png",
        renderer="static",
        browser=browser,
    )

    assert result.event_id == "event/alice-line"


@pytest.mark.browser
def test_reused_page_renders_resumable_sequence_and_silent_mp4(
    browser,
    preview_url,
    tmp_path,
):
    descriptor = _descriptor("example")
    descriptor["events"] = descriptor["events"][:2]
    for event in descriptor["events"]:
        event["duration_ms"] = 34
    timeline = build_render_timeline(descriptor)
    performance = build_scene_performance(descriptor, timeline)
    sequence_dir = tmp_path / "frames"

    first = render_scene_sequence(
        preview_url=preview_url,
        descriptor=descriptor,
        timeline=timeline,
        performance=performance,
        output_dir=sequence_dir,
        width=640,
        height=360,
        renderer="static",
        browser=browser,
    )
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (REPO_ROOT / "packages" / "contracts" / "render-sequence" / "1.1.schema.json")
        .read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(manifest)

    assert first.total_frames == 4
    assert first.rendered_frames == 4
    assert first.reused_frames == 0
    assert manifest["complete"] is True
    assert [item["frame"] for item in manifest["frames"]] == [0, 1, 2, 3]
    assert len(list(sequence_dir.glob("frame-*.png"))) == 4

    resumed = render_scene_sequence(
        preview_url=preview_url,
        descriptor=descriptor,
        timeline=timeline,
        performance=performance,
        output_dir=sequence_dir,
        width=640,
        height=360,
        renderer="static",
        browser=browser,
    )
    assert resumed.rendered_frames == 0
    assert resumed.reused_frames == 4

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("FFmpeg is not installed")
    video = encode_silent_mp4(
        sequence_dir=sequence_dir,
        output_path=tmp_path / "silent.mp4",
        ffmpeg_path=ffmpeg,
        preset="ultrafast",
    )
    assert video.output_path.is_file()
    assert video.output_path.stat().st_size > 0
    assert video.total_frames == 4
    assert video.codec == "h264/yuv420p"


@pytest.mark.browser
def test_resume_rejects_sequence_from_different_render_inputs(browser, preview_url, tmp_path):
    descriptor = _descriptor("example")
    descriptor["events"] = descriptor["events"][:1]
    descriptor["events"][0]["duration_ms"] = 34
    timeline = build_render_timeline(descriptor)
    performance = build_scene_performance(descriptor, timeline)
    sequence_dir = tmp_path / "frames"
    render_scene_sequence(
        preview_url=preview_url,
        descriptor=descriptor,
        timeline=timeline,
        performance=performance,
        output_dir=sequence_dir,
        width=640,
        height=360,
        renderer="static",
        browser=browser,
    )

    changed = json.loads(json.dumps(descriptor))
    changed["scene_id"] = "scene/changed"
    changed_timeline = build_render_timeline(changed)
    changed_performance = build_scene_performance(changed, changed_timeline)
    with pytest.raises(SceneFrameRenderError, match="different render inputs"):
        render_scene_sequence(
            preview_url=preview_url,
            descriptor=changed,
            timeline=changed_timeline,
            performance=changed_performance,
            output_dir=sequence_dir,
            width=640,
            height=360,
            renderer="static",
            browser=browser,
        )


@pytest.mark.browser
def test_offline_p69_frame_35_is_pixel_equivalent_to_the_browser_derived_timeline(
    browser,
    preview_url,
    tmp_path,
):
    descriptor = _synthetic_p69()
    frame = descriptor["presentation"]["reference_frame"]["resolved_frame"]
    timeline = build_render_timeline(
        descriptor,
        frame_rate=descriptor["presentation"]["frame_rate"],
    )
    performance = build_scene_performance(descriptor, timeline)
    result = render_scene_frame(
        preview_url=preview_url,
        descriptor=descriptor,
        timeline=timeline,
        performance=performance,
        frame=frame,
        output_path=tmp_path / "offline-p69-frame-35.png",
        renderer="static",
        browser=browser,
    )

    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        device_scale_factor=1,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.add_init_script(
        script=(
            "window.HALO_CUE_SCENE_DESCRIPTOR="
            + json.dumps(descriptor, ensure_ascii=True, separators=(",", ":"))
            + ";"
        )
    )
    page.goto(
        f"{preview_url}?capture=1&frame={frame}&renderer=static",
        wait_until="domcontentloaded",
    )
    page.wait_for_function(
        """expected => {
            const stage = document.querySelector('#preview-stage');
            return stage?.dataset.timelineSource === 'derived'
                && Number(stage.dataset.currentFrame) === expected
                && stage.dataset.mediaReady === 'ready';
        }""",
        arg=frame,
    )
    page.evaluate("() => document.fonts?.ready || Promise.resolve()")
    browser_png = page.locator("#preview-stage").screenshot(
        type="png",
        animations="disabled",
        scale="css",
    )
    (tmp_path / "browser-p69-frame-35.png").write_bytes(browser_png)
    context.close()

    assert result.frame == 35
    assert result.event_id == "event/yuuka-line"
    offline = Image.open(BytesIO(result.output_path.read_bytes())).convert("RGB")
    derived = Image.open(BytesIO(browser_png)).convert("RGB")
    difference = ImageChops.difference(offline, derived)
    changed_pixels = sum(
        1 for pixel in difference.get_flattened_data() if pixel != (0, 0, 0)
    )
    statistics = ImageStat.Stat(difference)
    assert changed_pixels / (result.width * result.height) < 0.002
    assert max(statistics.mean) < 0.003
    assert max(statistics.rms) < 0.2


@pytest.mark.browser
def test_compiled_screen_shake_has_deterministic_exported_intermediate_frames(
    browser,
    preview_url,
    tmp_path,
):
    descriptor = _descriptor("example")
    descriptor["events"] = [{
        "event_id": "event/shake",
        "kind": "halocue.ba:screen-shake",
        "duration_ms": 360,
        "intensity": 0.35,
    }]
    timeline = build_render_timeline(descriptor)
    performance = build_scene_performance(descriptor, timeline)
    start = timeline["events"][0]["start_frame"]
    middle = start + 2
    end = timeline["events"][0]["end_frame"] - 1

    results = [
        render_scene_frame(
            preview_url=preview_url,
            descriptor=descriptor,
            timeline=timeline,
            performance=performance,
            frame=frame,
            output_path=tmp_path / f"shake-{frame}.png",
            renderer="static",
            browser=browser,
        )
        for frame in (start, middle, end)
    ]

    assert performance["source_map"][0]["source_event_id"] == "event/shake"
    assert results[0].performance_schema_version == "scene-performance/1.4"
    assert results[0].sha256 == results[2].sha256
    assert results[1].sha256 != results[0].sha256


@pytest.mark.browser
def test_compiled_character_enter_exports_sampled_opacity_layout_and_scale(
    browser,
    preview_url,
    tmp_path,
):
    descriptor = _descriptor("example")
    alice = next(
        actor for actor in descriptor["actors"]
        if actor["character_id"] == "character/alice"
    )
    alice["stage_media"] = {
        "kind": "portrait",
        "preview_uri": "./assets/demo-conference-room.png",
        "anchor_x": 0.5,
        "anchor_y": 1,
        "scale": 1.6,
        "offset_x": 0,
        "offset_y": 0,
    }
    descriptor["events"] = [{
        "event_id": "event/alice-enter",
        "kind": "enter",
        "character_id": "character/alice",
        "slot": 3,
        "duration_ms": 500,
    }]
    timeline = build_render_timeline(descriptor)
    performance = build_scene_performance(descriptor, timeline)
    start = timeline["events"][0]["start_frame"]
    middle = start + 4
    end = timeline["events"][0]["end_frame"] - 1

    results = [
        render_scene_frame(
            preview_url=preview_url,
            descriptor=descriptor,
            timeline=timeline,
            performance=performance,
            frame=frame,
            output_path=tmp_path / f"enter-{frame}.png",
            renderer="static",
            browser=browser,
        )
        for frame in (start, middle, end)
    ]

    source = performance["source_map"][0]
    assert source["source_event_id"] == "event/alice-enter"
    assert len(source["operation_ids"]) == 3
    assert len({result.sha256 for result in results}) == 3
