"""Render resumable SceneDescriptor frame sequences and silent MP4 files."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Callable

from .scene_frame_renderer import (
    SceneFrameRenderError,
    SceneRenderSession,
    _atomic_write,
    _require_int,
    _validate_dimensions,
    _validate_timeline,
)


SEQUENCE_SCHEMA_VERSION = "render-sequence/1.0"


@dataclass(frozen=True)
class SceneSequenceResult:
    output_dir: Path
    manifest_path: Path
    total_frames: int
    rendered_frames: int
    reused_frames: int
    frame_rate: int
    width: int
    height: int
    renderer: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "manifest_path": str(self.manifest_path),
            "total_frames": self.total_frames,
            "rendered_frames": self.rendered_frames,
            "reused_frames": self.reused_frames,
            "frame_rate": self.frame_rate,
            "width": self.width,
            "height": self.height,
            "renderer": self.renderer,
            "schema_version": SEQUENCE_SCHEMA_VERSION,
        }


@dataclass(frozen=True)
class SceneVideoResult:
    output_path: Path
    total_frames: int
    frame_rate: int
    width: int
    height: int
    codec: str
    sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "output_path": str(self.output_path),
            "total_frames": self.total_frames,
            "frame_rate": self.frame_rate,
            "width": self.width,
            "height": self.height,
            "codec": self.codec,
            "sha256": self.sha256,
        }


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sequence_identity(
    *,
    descriptor: dict[str, Any],
    timeline: dict[str, Any],
    width: int,
    height: int,
    renderer: str,
) -> dict[str, Any]:
    return {
        "descriptor_sha256": _canonical_hash(descriptor),
        "timeline_sha256": _canonical_hash(timeline),
        "scene_id": timeline.get("scene_id"),
        "frame_rate": timeline.get("frame_rate"),
        "total_frames": timeline.get("total_frames"),
        "width": width,
        "height": height,
        "renderer": renderer,
    }


def render_scene_sequence(
    *,
    preview_url: str,
    descriptor: dict[str, Any],
    timeline: dict[str, Any],
    output_dir: str | Path,
    width: int = 1280,
    height: int = 720,
    renderer: str = "realtime",
    timeout_ms: int = 60_000,
    resume: bool = True,
    browser: Any = None,
    cancel_requested: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> SceneSequenceResult:
    """Render an atomic, resumable numbered PNG sequence through one page."""

    resolved_width, resolved_height = _validate_dimensions(width, height)
    frame_rate, _ = _validate_timeline(descriptor, timeline, 0)
    total_frames = timeline["total_frames"]
    target_dir = Path(output_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = target_dir / "sequence-manifest.json"
    identity = _sequence_identity(
        descriptor=descriptor,
        timeline=timeline,
        width=resolved_width,
        height=resolved_height,
        renderer=renderer,
    )
    manifest: dict[str, Any] = {
        "schema_version": SEQUENCE_SCHEMA_VERSION,
        **identity,
        "complete": False,
        "frames": [],
    }
    if resume and manifest_path.is_file():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SceneFrameRenderError("existing sequence manifest is unreadable") from exc
        existing_identity = {key: existing.get(key) for key in identity}
        if existing.get("schema_version") != SEQUENCE_SCHEMA_VERSION or existing_identity != identity:
            raise SceneFrameRenderError("existing sequence manifest belongs to different render inputs")
        if not isinstance(existing.get("frames"), list):
            raise SceneFrameRenderError("existing sequence manifest frames must be an array")
        manifest = existing

    completed = {
        item.get("frame"): item
        for item in manifest["frames"]
        if isinstance(item, dict) and isinstance(item.get("frame"), int)
    }
    rendered_frames = 0
    reused_frames = 0
    reusable_frames: set[int] = set()
    if resume:
        for frame in range(total_frames):
            filename = f"frame-{frame:06d}.png"
            frame_path = target_dir / filename
            previous = completed.get(frame)
            if (
                previous
                and previous.get("file") == filename
                and isinstance(previous.get("sha256"), str)
                and frame_path.is_file()
                and _file_hash(frame_path) == previous["sha256"]
            ):
                reusable_frames.add(frame)

    if len(reusable_frames) == total_frames:
        if manifest.get("complete") is not True:
            manifest["frames"] = [completed[index] for index in range(total_frames)]
            manifest["complete"] = True
            _atomic_write(
                manifest_path,
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
        return SceneSequenceResult(
            output_dir=target_dir,
            manifest_path=manifest_path,
            total_frames=total_frames,
            rendered_frames=0,
            reused_frames=total_frames,
            frame_rate=frame_rate,
            width=resolved_width,
            height=resolved_height,
            renderer=renderer,
        )

    with SceneRenderSession(
        preview_url=preview_url,
        descriptor=descriptor,
        timeline=timeline,
        width=resolved_width,
        height=resolved_height,
        renderer=renderer,
        timeout_ms=timeout_ms,
        browser=browser,
    ) as session:
        for frame in range(total_frames):
            if cancel_requested is not None and cancel_requested():
                raise SceneFrameRenderError(f"scene sequence cancelled before frame {frame}")
            filename = f"frame-{frame:06d}.png"
            frame_path = target_dir / filename
            if frame in reusable_frames:
                reused_frames += 1
            else:
                result = session.render_frame(frame, frame_path)
                completed[frame] = {
                    "frame": frame,
                    "file": filename,
                    "event_id": result.event_id,
                    "sha256": result.sha256,
                }
                rendered_frames += 1
                manifest["frames"] = [completed[index] for index in sorted(completed)]
                manifest["complete"] = len(completed) == total_frames
                _atomic_write(
                    manifest_path,
                    json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                )
            if progress is not None:
                progress(frame + 1, total_frames)

    manifest["frames"] = [completed[index] for index in range(total_frames)]
    manifest["complete"] = True
    _atomic_write(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    return SceneSequenceResult(
        output_dir=target_dir,
        manifest_path=manifest_path,
        total_frames=total_frames,
        rendered_frames=rendered_frames,
        reused_frames=reused_frames,
        frame_rate=frame_rate,
        width=resolved_width,
        height=resolved_height,
        renderer=renderer,
    )


def encode_silent_mp4(
    *,
    sequence_dir: str | Path,
    output_path: str | Path,
    ffmpeg_path: str | Path | None = None,
    crf: int = 18,
    preset: str = "medium",
) -> SceneVideoResult:
    """Encode one complete HaloCue PNG sequence as H.264/yuv420p without audio."""

    source_dir = Path(sequence_dir).expanduser().resolve()
    manifest_path = source_dir / "sequence-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SceneFrameRenderError("sequence manifest is missing or unreadable") from exc
    if manifest.get("schema_version") != SEQUENCE_SCHEMA_VERSION or manifest.get("complete") is not True:
        raise SceneFrameRenderError("sequence must be complete before MP4 encoding")
    total_frames = _require_int(manifest.get("total_frames"), "total_frames", minimum=1)
    frame_rate = _require_int(manifest.get("frame_rate"), "frame_rate", minimum=1)
    width, height = _validate_dimensions(manifest.get("width"), manifest.get("height"))
    frames = manifest.get("frames")
    if not isinstance(frames, list) or len(frames) != total_frames:
        raise SceneFrameRenderError("sequence manifest does not contain every frame")
    for frame in range(total_frames):
        expected = source_dir / f"frame-{frame:06d}.png"
        if not expected.is_file():
            raise SceneFrameRenderError(f"sequence frame {frame} is missing")

    target = Path(output_path).expanduser().resolve()
    if target.suffix.casefold() != ".mp4":
        raise SceneFrameRenderError("scene video output must use an .mp4 extension")
    target.parent.mkdir(parents=True, exist_ok=True)
    executable = str(ffmpeg_path) if ffmpeg_path is not None else shutil.which("ffmpeg")
    if not executable or not Path(executable).is_file():
        raise SceneFrameRenderError("FFmpeg was not found; configure an explicit executable path")
    if isinstance(crf, bool) or not isinstance(crf, int) or not 0 <= crf <= 51:
        raise SceneFrameRenderError("crf must be an integer from 0 to 51")
    if preset not in {
        "ultrafast", "superfast", "veryfast", "faster", "fast", "medium",
        "slow", "slower", "veryslow",
    }:
        raise SceneFrameRenderError("unsupported H.264 preset")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.stem}.",
            suffix=".tmp.mp4",
            dir=target.parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
        command = [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            str(frame_rate),
            "-start_number",
            "0",
            "-i",
            str(source_dir / "frame-%06d.png"),
            "-frames:v",
            str(total_frames),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(temp_path),
        ]
        completed_process = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=max(60, total_frames // max(1, frame_rate) * 8),
        )
        if completed_process.returncode != 0 or not temp_path.is_file() or temp_path.stat().st_size == 0:
            detail = completed_process.stderr.strip() or "FFmpeg did not create an output file"
            raise SceneFrameRenderError("FFmpeg encoding failed: " + detail[-2000:])
        os.replace(temp_path, target)
        temp_path = None
    except SceneFrameRenderError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise SceneFrameRenderError(f"FFmpeg encoding failed: {exc}") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    return SceneVideoResult(
        output_path=target,
        total_frames=total_frames,
        frame_rate=frame_rate,
        width=width,
        height=height,
        codec="h264/yuv420p",
        sha256=_file_hash(target),
    )
