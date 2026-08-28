"""Deterministically capture one SceneDescriptor frame through Chromium."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TIMELINE_SCHEMA_VERSION = "render-timeline/1.2"
PERFORMANCE_SCHEMA_VERSION = "scene-performance/1.4"
LOCAL_PREVIEW_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class SceneFrameRenderError(RuntimeError):
    """Raised when a requested frame cannot be captured deterministically."""


@dataclass(frozen=True)
class SceneFrameResult:
    output_path: Path
    frame: int
    event_id: str | None
    frame_rate: int
    width: int
    height: int
    sha256: str
    renderer: str
    timeline_schema_version: str = TIMELINE_SCHEMA_VERSION
    performance_schema_version: str = PERFORMANCE_SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "output_path": str(self.output_path),
            "frame": self.frame,
            "event_id": self.event_id,
            "frame_rate": self.frame_rate,
            "width": self.width,
            "height": self.height,
            "sha256": self.sha256,
            "renderer": self.renderer,
            "timeline_schema_version": self.timeline_schema_version,
            "performance_schema_version": self.performance_schema_version,
        }


def _require_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SceneFrameRenderError(f"{name} must be an integer >= {minimum}")
    return value


def _validate_preview_url(preview_url: str) -> str:
    value = str(preview_url or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in LOCAL_PREVIEW_HOSTS:
        raise SceneFrameRenderError("preview_url must use http on localhost")
    if parsed.username or parsed.password or not parsed.path:
        raise SceneFrameRenderError("preview_url must not contain credentials and must have a path")
    return value


def _validate_dimensions(width: Any, height: Any) -> tuple[int, int]:
    resolved_width = _require_int(width, "width", minimum=16)
    resolved_height = _require_int(height, "height", minimum=9)
    if resolved_width * 9 != resolved_height * 16:
        raise SceneFrameRenderError("scene frame dimensions must use an exact 16:9 ratio")
    if resolved_width > 8192 or resolved_height > 8192:
        raise SceneFrameRenderError("scene frame dimensions must not exceed 8192 pixels")
    return resolved_width, resolved_height


def _validate_timeline(
    descriptor: dict[str, Any],
    timeline: dict[str, Any],
    frame: Any,
) -> tuple[int, dict[str, Any]]:
    if not isinstance(descriptor, dict) or descriptor.get("schema_version") != "scene-descriptor/1.0":
        raise SceneFrameRenderError("unsupported scene descriptor schema")
    if not isinstance(timeline, dict) or timeline.get("schema_version") != TIMELINE_SCHEMA_VERSION:
        raise SceneFrameRenderError("unsupported render timeline schema")
    if timeline.get("scene_id") != descriptor.get("scene_id"):
        raise SceneFrameRenderError("render timeline scene_id does not match the descriptor")

    frame_rate = _require_int(timeline.get("frame_rate"), "frame_rate", minimum=1)
    if frame_rate > 240:
        raise SceneFrameRenderError("frame_rate must not exceed 240")
    source_events = descriptor.get("events")
    events = timeline.get("events")
    if not isinstance(source_events, list) or not isinstance(events, list):
        raise SceneFrameRenderError("descriptor and timeline events must be arrays")
    if len(events) != len(source_events):
        raise SceneFrameRenderError("render timeline event count does not match the descriptor")

    cursor = 0
    total_frames = 0
    for index, (item, source) in enumerate(zip(events, source_events)):
        if not isinstance(item, dict) or not isinstance(source, dict):
            raise SceneFrameRenderError(f"render timeline event {index} is invalid")
        start = _require_int(item.get("start_frame"), f"events[{index}].start_frame")
        end = _require_int(item.get("end_frame"), f"events[{index}].end_frame", minimum=1)
        duration = _require_int(
            item.get("duration_frames"), f"events[{index}].duration_frames", minimum=1
        )
        wait_for_completion = item.get("wait_for_completion")
        if not isinstance(wait_for_completion, bool):
            raise SceneFrameRenderError(
                "render timeline wait_for_completion must be a boolean"
            )
        if start != cursor or end <= start or duration != end - start:
            raise SceneFrameRenderError("render timeline frame ranges must be contiguous and end-exclusive")
        if item.get("event_id") != source.get("event_id") or item.get("event") != source:
            raise SceneFrameRenderError("render timeline event payload does not match the descriptor")
        if wait_for_completion:
            cursor = end
        total_frames = max(total_frames, end)

    declared_total_frames = _require_int(timeline.get("total_frames"), "total_frames")
    if declared_total_frames != total_frames or total_frames == 0:
        raise SceneFrameRenderError("render timeline must contain at least one complete frame range")
    resolved_frame = _require_int(frame, "frame")
    if resolved_frame >= declared_total_frames:
        raise SceneFrameRenderError(f"frame must be between 0 and {declared_total_frames - 1}")
    active_items = [
        event
        for event in events
        if event["start_frame"] <= resolved_frame < event["end_frame"]
    ]
    if not active_items:
        raise SceneFrameRenderError("render timeline has no active event at the requested frame")
    item = active_items[-1]
    return frame_rate, item


def _validate_performance(
    descriptor: dict[str, Any],
    timeline: dict[str, Any],
    performance: dict[str, Any],
) -> None:
    if not isinstance(performance, dict) or performance.get("schema_version") != PERFORMANCE_SCHEMA_VERSION:
        raise SceneFrameRenderError("unsupported scene performance schema")
    if performance.get("scene_id") != descriptor.get("scene_id"):
        raise SceneFrameRenderError("scene performance scene_id does not match the descriptor")
    if performance.get("frame_rate") != timeline.get("frame_rate"):
        raise SceneFrameRenderError("scene performance frame_rate does not match the timeline")
    if performance.get("total_frames") != timeline.get("total_frames"):
        raise SceneFrameRenderError("scene performance total_frames does not match the timeline")
    operations = performance.get("operations")
    source_map = performance.get("source_map")
    if not isinstance(operations, list) or not isinstance(source_map, list):
        raise SceneFrameRenderError("scene performance operations and source_map must be arrays")
    source_ids = {
        event.get("event_id")
        for event in descriptor.get("events", [])
        if isinstance(event, dict)
    }
    operation_ids: set[str] = set()
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict) or operation.get("kind") not in {
            "shake", "numeric-tween", "numeric-keyframes"
        }:
            raise SceneFrameRenderError(f"scene performance operation {index} is invalid")
        operation_id = operation.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id or operation_id in operation_ids:
            raise SceneFrameRenderError("scene performance operation IDs must be unique")
        operation_ids.add(operation_id)
        if operation.get("source_event_id") not in source_ids:
            raise SceneFrameRenderError("scene performance operation source event is missing")
        start = _require_int(operation.get("start_frame"), f"operations[{index}].start_frame")
        end = _require_int(operation.get("end_frame"), f"operations[{index}].end_frame", minimum=1)
        if end <= start or end > timeline["total_frames"]:
            raise SceneFrameRenderError("scene performance operation frame range is invalid")
        if operation["kind"] in {"numeric-tween", "numeric-keyframes"}:
            target = operation.get("target")
            if (
                not isinstance(target, dict)
                or target.get("kind") != "character"
                or not isinstance(target.get("character_id"), str)
                or not target["character_id"]
                or not isinstance(target.get("slot"), int)
                or isinstance(target["slot"], bool)
                or not 1 <= target["slot"] <= 5
            ):
                raise SceneFrameRenderError("scene performance character target is invalid")
            channels = {
                "presentation.opacity", "layout.offset-y", "presentation.scale"
            }
            if operation["kind"] == "numeric-keyframes":
                channels.add("presentation.rotation")
            if operation.get("channel") not in channels:
                raise SceneFrameRenderError("scene performance tween channel is invalid")
            if operation["kind"] == "numeric-keyframes":
                keyframes = operation.get("keyframes")
                if (
                    not isinstance(keyframes, list)
                    or len(keyframes) < 2
                    or any(
                        not isinstance(keyframe, dict)
                        or not isinstance(keyframe.get("offset"), (int, float))
                        or isinstance(keyframe.get("offset"), bool)
                        or not 0 <= keyframe["offset"] <= 1
                        or not isinstance(keyframe.get("value"), (int, float))
                        or isinstance(keyframe.get("value"), bool)
                        for keyframe in keyframes
                    )
                    or operation.get("easing")
                    not in {"ease-in-out-strong", "ease-out-emphasized"}
                ):
                    raise SceneFrameRenderError("scene performance keyframes are invalid")

    mapped_operation_ids: set[str] = set()
    mapped_source_ids: set[str] = set()
    for index, source in enumerate(source_map):
        if not isinstance(source, dict):
            raise SceneFrameRenderError(f"scene performance source_map {index} is invalid")
        source_event_id = source.get("source_event_id")
        mapped_ids = source.get("operation_ids")
        primary_id = source.get("primary_operation_id")
        if source_event_id not in source_ids or source_event_id in mapped_source_ids:
            raise SceneFrameRenderError("scene performance source event mapping is invalid")
        if (
            not isinstance(mapped_ids, list)
            or not mapped_ids
            or any(not isinstance(item, str) or item not in operation_ids for item in mapped_ids)
            or len(set(mapped_ids)) != len(mapped_ids)
            or primary_id not in mapped_ids
        ):
            raise SceneFrameRenderError("scene performance operation mapping is invalid")
        if any(item in mapped_operation_ids for item in mapped_ids):
            raise SceneFrameRenderError("scene performance operation mapping is duplicated")
        mapped_source_ids.add(source_event_id)
        mapped_operation_ids.update(mapped_ids)
    if mapped_operation_ids != operation_ids:
        raise SceneFrameRenderError("scene performance operation mapping is incomplete")


def _capture_url(preview_url: str, frame: int, renderer: str) -> str:
    parsed = urlsplit(preview_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key in ("editor", "play", "reference"):
        query.pop(key, None)
    query.update({"capture": "1", "frame": str(frame), "renderer": renderer})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 24 or payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
        raise SceneFrameRenderError("Chromium did not return a valid PNG frame")
    return struct.unpack(">II", payload[16:24])


def _atomic_write(path: Path, payload: bytes) -> Path:
    target = path
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    return target


class SceneRenderSession:
    """Reuse one Chromium page and loaded resource graph across many frames."""

    def __init__(
        self,
        *,
        preview_url: str,
        descriptor: dict[str, Any],
        timeline: dict[str, Any],
        performance: dict[str, Any],
        width: int = 1280,
        height: int = 720,
        renderer: str = "realtime",
        timeout_ms: int = 60_000,
        browser: Any = None,
    ) -> None:
        self.preview_url = _validate_preview_url(preview_url)
        self.width, self.height = _validate_dimensions(width, height)
        self.frame_rate, _ = _validate_timeline(descriptor, timeline, 0)
        _validate_performance(descriptor, timeline, performance)
        self.descriptor = descriptor
        self.timeline = timeline
        self.performance = performance
        self.total_frames = timeline["total_frames"]
        self.renderer = renderer
        self.timeout_ms = _require_int(timeout_ms, "timeout_ms", minimum=1)
        if renderer not in {"realtime", "static"}:
            raise SceneFrameRenderError("renderer must be 'realtime' or 'static'")
        self.browser = browser
        self._owned_browser = browser is None
        self._runtime = None
        self._context = None
        self._page = None
        self._page_errors: list[str] = []

    def __enter__(self) -> SceneRenderSession:
        self.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def start(self) -> SceneRenderSession:
        if self._page is not None:
            return self
        if self._owned_browser:
            try:
                from playwright.sync_api import sync_playwright
            except ModuleNotFoundError as exc:
                raise SceneFrameRenderError(
                    "Playwright is required; install halocue-production[render] and Chromium"
                ) from exc
            self._runtime = sync_playwright().start()
            self.browser = self._runtime.chromium.launch(headless=True)

        injected = json.dumps(
            {
                "descriptor": self.descriptor,
                "timeline": self.timeline,
                "performance": self.performance,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        init_script = (
            f"const payload={injected};"
            "window.HALO_CUE_SCENE_DESCRIPTOR=payload.descriptor;"
            "window.HALO_CUE_RENDER_TIMELINE=payload.timeline;"
            "window.HALO_CUE_SCENE_PERFORMANCE=payload.performance;"
        )
        try:
            self._context = self.browser.new_context(
                viewport={"width": self.width, "height": self.height},
                device_scale_factor=1,
                reduced_motion="reduce",
            )
            self._page = self._context.new_page()
            self._page.on("pageerror", lambda error: self._page_errors.append(str(error)))
            self._page.on(
                "console",
                lambda message: (
                    self._page_errors.append(message.text) if message.type == "error" else None
                ),
            )
            self._page.add_init_script(script=init_script)
            self._page.goto(
                _capture_url(self.preview_url, 0, self.renderer),
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
            self._wait_for_frame(0)
            return self
        except Exception:
            self.close()
            raise

    def _wait_for_frame(self, frame: int) -> None:
        self._page.wait_for_function(
            """expected => {
                const error = document.querySelector('#preview-error');
                if (error && !error.hidden) return true;
                const stage = document.querySelector('#preview-stage');
                const controller = window.HaloCueScenePreview?.controller;
                return Boolean(
                    stage && controller
                    && stage.dataset.capture === 'deterministic'
                    && stage.dataset.timelineSource === 'supplied'
                    && stage.dataset.performanceSource === 'supplied'
                    && Number(stage.dataset.currentFrame) === expected.frame
                    && stage.dataset.mediaReady === 'ready'
                    && controller.timeline.schema_version === expected.schema
                    && controller.performance.schema_version === expected.performanceSchema
                );
            }""",
            arg={
                "frame": frame,
                "schema": TIMELINE_SCHEMA_VERSION,
                "performanceSchema": PERFORMANCE_SCHEMA_VERSION,
            },
            timeout=self.timeout_ms,
        )
        preview_error = self._page.locator("#preview-error")
        if preview_error.is_visible():
            raise SceneFrameRenderError("preview page failed: " + preview_error.inner_text())
        self._page.wait_for_function(
            """() => [...document.querySelectorAll(
                '.actor-slot.is-visible .actor-portrait.has-realtime-media'
            )].every(element => element.classList.contains('realtime-ready'))""",
            timeout=self.timeout_ms,
        )
        self._page.evaluate("() => document.fonts?.ready || Promise.resolve()")
        if self._page_errors:
            raise SceneFrameRenderError("preview page failed: " + "; ".join(self._page_errors))

    def render_frame(self, frame: int, output_path: str | Path) -> SceneFrameResult:
        if self._page is None:
            self.start()
        frame_rate, timeline_item = _validate_timeline(
            self.descriptor,
            self.timeline,
            frame,
        )
        target = Path(output_path).expanduser().resolve()
        if target.suffix.casefold() != ".png":
            raise SceneFrameRenderError("scene frame output must use a .png extension")
        try:
            current = self._page.locator("#preview-stage").get_attribute("data-current-frame")
            if current != str(frame):
                self._page.evaluate(
                    "requested => window.HaloCueScenePreview.controller.seekFrame(requested)",
                    frame,
                )
            self._wait_for_frame(frame)
            png = self._page.locator("#preview-stage").screenshot(
                type="png",
                animations="disabled",
                scale="css",
                timeout=self.timeout_ms,
            )
            png_width, png_height = _png_dimensions(png)
            if (png_width, png_height) != (self.width, self.height):
                raise SceneFrameRenderError(
                    f"captured PNG is {png_width}x{png_height}, expected "
                    f"{self.width}x{self.height}"
                )
            _atomic_write(target, png)
            return SceneFrameResult(
                output_path=target,
                frame=frame,
                event_id=timeline_item.get("event_id"),
                frame_rate=frame_rate,
                width=png_width,
                height=png_height,
                sha256=hashlib.sha256(png).hexdigest(),
                renderer=self.renderer,
            )
        except SceneFrameRenderError:
            raise
        except Exception as exc:
            raise SceneFrameRenderError(f"scene frame capture failed: {exc}") from exc

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
            self._page = None
        if self._owned_browser and self.browser is not None:
            self.browser.close()
            self.browser = None
        if self._runtime is not None:
            self._runtime.stop()
            self._runtime = None


def render_scene_frame(
    *,
    preview_url: str,
    descriptor: dict[str, Any],
    timeline: dict[str, Any],
    performance: dict[str, Any],
    frame: int,
    output_path: str | Path,
    width: int = 1280,
    height: int = 720,
    renderer: str = "realtime",
    timeout_ms: int = 60_000,
    browser: Any = None,
) -> SceneFrameResult:
    """Capture one explicit end-exclusive timeline frame as an atomic PNG.

    ``browser`` may be a caller-owned Playwright Browser so export jobs can
    reuse the Chromium process. When omitted, this function owns the complete
    Playwright lifecycle.
    """

    resolved_url = _validate_preview_url(preview_url)
    resolved_width, resolved_height = _validate_dimensions(width, height)
    frame_rate, timeline_item = _validate_timeline(descriptor, timeline, frame)
    _validate_performance(descriptor, timeline, performance)
    resolved_timeout = _require_int(timeout_ms, "timeout_ms", minimum=1)
    target = Path(output_path).expanduser().resolve()
    if target.suffix.casefold() != ".png":
        raise SceneFrameRenderError("scene frame output must use a .png extension")
    if renderer not in {"realtime", "static"}:
        raise SceneFrameRenderError("renderer must be 'realtime' or 'static'")

    injected = json.dumps(
        {"descriptor": descriptor, "timeline": timeline, "performance": performance},
        ensure_ascii=True,
        separators=(",", ":"),
    )
    init_script = (
        f"const payload={injected};"
        "window.HALO_CUE_SCENE_DESCRIPTOR=payload.descriptor;"
        "window.HALO_CUE_RENDER_TIMELINE=payload.timeline;"
        "window.HALO_CUE_SCENE_PERFORMANCE=payload.performance;"
    )
    capture_url = _capture_url(resolved_url, frame, renderer)
    runtime = None
    owned_browser = browser is None
    context = None
    page_errors: list[str] = []
    try:
        if owned_browser:
            try:
                from playwright.sync_api import sync_playwright
            except ModuleNotFoundError as exc:
                raise SceneFrameRenderError(
                    "Playwright is required; install halocue-production[render] and Chromium"
                ) from exc
            runtime = sync_playwright().start()
            browser = runtime.chromium.launch(headless=True)

        context = browser.new_context(
            viewport={"width": resolved_width, "height": resolved_height},
            device_scale_factor=1,
            reduced_motion="reduce",
        )
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: page_errors.append(message.text) if message.type == "error" else None,
        )
        page.add_init_script(script=init_script)
        page.goto(capture_url, wait_until="domcontentloaded", timeout=resolved_timeout)
        page.wait_for_function(
            """expected => {
                const error = document.querySelector('#preview-error');
                if (error && !error.hidden) return true;
                const stage = document.querySelector('#preview-stage');
                const controller = window.HaloCueScenePreview?.controller;
                return Boolean(
                    stage && controller
                    && stage.dataset.capture === 'deterministic'
                    && stage.dataset.timelineSource === 'supplied'
                    && stage.dataset.performanceSource === 'supplied'
                    && Number(stage.dataset.currentFrame) === expected.frame
                    && controller.timeline.schema_version === expected.schema
                    && controller.performance.schema_version === expected.performanceSchema
                );
            }""",
            arg={
                "frame": frame,
                "schema": TIMELINE_SCHEMA_VERSION,
                "performanceSchema": PERFORMANCE_SCHEMA_VERSION,
            },
            timeout=resolved_timeout,
        )
        preview_error = page.locator("#preview-error")
        if preview_error.is_visible():
            raise SceneFrameRenderError("preview page failed: " + preview_error.inner_text())
        page.wait_for_function(
            """() => {
                const stage = document.querySelector('#preview-stage');
                if (!stage || stage.dataset.mediaReady !== 'ready') return false;
                return [...stage.querySelectorAll(
                    '.actor-slot.is-visible .actor-portrait.has-realtime-media'
                )].every(element => element.classList.contains('realtime-ready'));
            }""",
            timeout=resolved_timeout,
        )
        page.evaluate("() => document.fonts?.ready || Promise.resolve()")
        if page_errors:
            raise SceneFrameRenderError("preview page failed: " + "; ".join(page_errors))
        png = page.locator("#preview-stage").screenshot(
            type="png",
            animations="disabled",
            scale="css",
            timeout=resolved_timeout,
        )
        if page_errors:
            raise SceneFrameRenderError("preview page failed: " + "; ".join(page_errors))
        png_width, png_height = _png_dimensions(png)
        if (png_width, png_height) != (resolved_width, resolved_height):
            raise SceneFrameRenderError(
                f"captured PNG is {png_width}x{png_height}, expected "
                f"{resolved_width}x{resolved_height}"
            )
        target = _atomic_write(target, png)
        return SceneFrameResult(
            output_path=target,
            frame=frame,
            event_id=timeline_item.get("event_id"),
            frame_rate=frame_rate,
            width=png_width,
            height=png_height,
            sha256=hashlib.sha256(png).hexdigest(),
            renderer=renderer,
        )
    except SceneFrameRenderError:
        raise
    except Exception as exc:
        raise SceneFrameRenderError(f"scene frame capture failed: {exc}") from exc
    finally:
        if context is not None:
            context.close()
        if owned_browser and browser is not None:
            browser.close()
        if runtime is not None:
            runtime.stop()
