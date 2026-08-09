"""Scan a HaloCue source or release tree and print redacted findings."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release_tools.scanner import scan_tree  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--mode", choices=("source", "public", "private"), required=True)
    args = parser.parse_args(argv)
    findings = scan_tree(args.root, mode=args.mode)
    if findings:
        print(f"release scan failed: {len(findings)} finding(s)")
        for finding in findings:
            print(f"- {finding.code}: {finding.relative_path}")
        return 1
    print("release scan passed: zero findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
