"""Local-only CLI for the authorization-gated HaloCue private package."""

from __future__ import annotations

import argparse
from pathlib import Path

from release_tools.build_private import build_private_release


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-archive", type=Path, required=True)
    parser.add_argument("--spine-source", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    archive = build_private_release(
        args.public_archive,
        args.spine_source,
        args.attestation,
        args.output,
    )
    print(f"private archive built locally: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
