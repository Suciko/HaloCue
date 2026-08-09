"""Build HaloCue's audited standalone public Windows release."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release_tools.build_public import (  # noqa: E402
    build_public_release,
    finalize_existing_bundle,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--finalize-existing",
        action="store_true",
        help="finalize OUTPUT/HaloCue without invoking PyInstaller",
    )
    parser.add_argument(
        "--python-executable",
        type=Path,
        default=Path(sys.executable),
    )
    args = parser.parse_args(argv)
    try:
        if args.finalize_existing:
            result = finalize_existing_bundle(
                args.source,
                args.output / "HaloCue",
                args.output,
            )
        else:
            result = build_public_release(
                args.source,
                args.output,
                python_executable=args.python_executable,
            )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"public build failed: {exc}", file=sys.stderr)
        return 1
    print(f"bundle: {result.bundle_dir}")
    print(f"archive: {result.archive_path}")
    print(f"archive sha256: {result.archive_sha256}")
    print(f"manifest: {result.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
