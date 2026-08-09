"""Export HaloCue's indexed public source into a fresh build directory."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release_tools.manifest import export_public_source  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--build-root",
        type=Path,
        help="explicit containment root (default: SOURCE/build)",
    )
    args = parser.parse_args(argv)
    source = args.source.resolve()
    build_root = (args.build_root or (source / "build")).resolve()
    try:
        manifest = export_public_source(
            source,
            args.output,
            build_root=build_root,
        )
    except ValueError as exc:
        print(f"public source export failed: {exc}", file=sys.stderr)
        return 1
    print(f"public source exported: {manifest.parent}")
    print(f"manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
