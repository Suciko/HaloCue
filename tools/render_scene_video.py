"""Render one SceneDescriptor to a resumable PNG sequence and silent MP4."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = REPO_ROOT / "packages" / "project-model"
PRODUCTION_ROOT = REPO_ROOT / "services" / "halocue" / "production" / "src"
for source_root in (MODEL_ROOT, PRODUCTION_ROOT):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from halocue_production.scene_video_renderer import (  # noqa: E402
    encode_silent_mp4,
    render_scene_sequence,
)
from render_timeline import build_render_timeline  # noqa: E402
from scene_performance import build_scene_performance  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render one deterministic SceneDescriptor as a silent MP4"
    )
    parser.add_argument("descriptor", type=Path, help="scene-descriptor/1.0 JSON file")
    parser.add_argument("output", type=Path, help="destination .mp4 path")
    parser.add_argument(
        "--frames-dir",
        type=Path,
        help="resumable sequence directory (default: <output>.frames)",
    )
    parser.add_argument(
        "--preview-url",
        default="http://127.0.0.1:8898/scene-preview/index.html",
        help="localhost scene preview URL",
    )
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--renderer", choices=("realtime", "static"), default="realtime")
    parser.add_argument("--timeout-ms", type=int, default=60_000)
    parser.add_argument("--ffmpeg", type=Path, help="explicit FFmpeg executable")
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument(
        "--preset",
        choices=(
            "ultrafast", "superfast", "veryfast", "faster", "fast", "medium",
            "slow", "slower", "veryslow",
        ),
        default="medium",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="render every frame even when a matching sequence manifest exists",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    descriptor = json.loads(args.descriptor.read_text(encoding="utf-8"))
    frame_rate = descriptor.get("presentation", {}).get("frame_rate", 30)
    timeline = build_render_timeline(descriptor, frame_rate=frame_rate)
    performance = build_scene_performance(descriptor, timeline)
    frames_dir = args.frames_dir or args.output.with_suffix(args.output.suffix + ".frames")

    def report(completed: int, total: int) -> None:
        print(f"\rRendering frames: {completed}/{total}", end="", flush=True)

    sequence = render_scene_sequence(
        preview_url=args.preview_url,
        descriptor=descriptor,
        timeline=timeline,
        performance=performance,
        output_dir=frames_dir,
        width=args.width,
        height=args.height,
        renderer=args.renderer,
        timeout_ms=args.timeout_ms,
        resume=not args.no_resume,
        progress=report,
    )
    print()
    video = encode_silent_mp4(
        sequence_dir=frames_dir,
        output_path=args.output,
        ffmpeg_path=args.ffmpeg,
        crf=args.crf,
        preset=args.preset,
    )
    print(json.dumps({"sequence": sequence.as_dict(), "video": video.as_dict()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
