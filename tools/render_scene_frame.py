"""Repository CLI for one deterministic scene-frame capture."""

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

from halocue_production.scene_frame_renderer import render_scene_frame  # noqa: E402
from render_timeline import build_render_timeline  # noqa: E402
from scene_performance import build_scene_performance  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render one deterministic SceneDescriptor frame")
    parser.add_argument("descriptor", type=Path, help="scene-descriptor/1.0 JSON file")
    parser.add_argument("output", type=Path, help="destination PNG outside the source tree")
    parser.add_argument(
        "--preview-url",
        default="http://127.0.0.1:8898/scene-preview/index.html",
        help="localhost scene preview URL",
    )
    frame_group = parser.add_mutually_exclusive_group(required=True)
    frame_group.add_argument("--frame", type=int, help="explicit zero-based timeline frame")
    frame_group.add_argument(
        "--reference",
        action="store_true",
        help="use presentation.reference_frame.resolved_frame",
    )
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--renderer", choices=("realtime", "static"), default="realtime")
    parser.add_argument("--timeout-ms", type=int, default=60_000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    descriptor = json.loads(args.descriptor.read_text(encoding="utf-8"))
    frame_rate = descriptor.get("presentation", {}).get("frame_rate", 30)
    timeline = build_render_timeline(descriptor, frame_rate=frame_rate)
    performance = build_scene_performance(descriptor, timeline)
    if args.reference:
        try:
            frame = descriptor["presentation"]["reference_frame"]["resolved_frame"]
        except (KeyError, TypeError) as exc:
            raise SystemExit("descriptor has no presentation.reference_frame.resolved_frame") from exc
    else:
        frame = args.frame
    result = render_scene_frame(
        preview_url=args.preview_url,
        descriptor=descriptor,
        timeline=timeline,
        performance=performance,
        frame=frame,
        output_path=args.output,
        width=args.width,
        height=args.height,
        renderer=args.renderer,
        timeout_ms=args.timeout_ms,
    )
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
