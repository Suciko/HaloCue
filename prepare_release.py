"""Compatibility entry point for public-source checking and export."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

from release_tools.manifest import export_public_source


HERE = Path(__file__).resolve().parent


def _check_index_candidate(root: Path) -> bool:
    try:
        with tempfile.TemporaryDirectory(prefix="halocue-public-check-") as temporary:
            build_root = Path(temporary)
            export_public_source(
                root,
                build_root / "candidate",
                build_root=build_root,
            )
    except ValueError as exc:
        print(f"release scan failed: {exc}")
        return False
    else:
        print("release scan passed: zero findings")
        return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--out", type=Path, help="public source output directory")
    parser.add_argument("--check", action="store_true", help="scan without exporting")
    args = parser.parse_args(argv)

    if args.check:
        return 0 if _check_index_candidate(HERE) else 1
    if args.out is None:
        parser.error("provide --check or -o/--out")
    output = args.out.resolve()
    try:
        manifest = export_public_source(HERE, output, build_root=output.parent)
    except ValueError as exc:
        print(f"public source export failed: {exc}", file=sys.stderr)
        return 1
    print(f"public source exported: {manifest.parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
