"""Fail closed unless a Git tag and public database match HaloCue metadata."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from halocue_meta import PRODUCT_NAME, PUBLIC_ARCHIVE_NAME, VERSION  # noqa: E402
from release_tools.public_db import build_public_database  # noqa: E402


class ReleaseVersionError(ValueError):
    """Raised when release identity or generated public data is unsafe."""


def require_clean_public_database(root: Path) -> Path:
    """Require the tracked public seed to be present and unchanged from HEAD."""

    root = Path(root).resolve()
    seed = root / "data" / "halocue_labels.db"
    if not seed.is_file():
        raise ReleaseVersionError("public database is missing")
    tracked = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--error-unmatch",
            "--",
            "data/halocue_labels.db",
        ],
        check=False,
        capture_output=True,
    )
    if tracked.returncode != 0:
        raise ReleaseVersionError("public database is not tracked")
    status = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "status",
            "--porcelain=v1",
            "--untracked-files=no",
            "--",
            "data/halocue_labels.db",
        ],
        check=False,
        capture_output=True,
    )
    if status.returncode != 0:
        raise ReleaseVersionError("could not inspect public database state")
    if status.stdout.strip():
        raise ReleaseVersionError("generated public database is dirty")
    return seed


def _verify_deterministic_public_database(seed: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="halocue-release-db-") as temporary:
        root = Path(temporary)
        first = root / "first.db"
        second = root / "second.db"
        first_report = build_public_database(seed, first)
        second_report = build_public_database(seed, second)
        if first_report.output_sha256 != second_report.output_sha256:
            raise ReleaseVersionError("public database rebuild is not deterministic")
        if first.read_bytes() != second.read_bytes():
            raise ReleaseVersionError("public database rebuild bytes differ")


def check_release_version(
    tag: str,
    root: Path = ROOT,
    *,
    verify_database: bool = True,
) -> None:
    """Validate the exact release tag, archive metadata, and public seed."""

    expected_tag = f"v{VERSION}"
    version_pattern = r"\d+\.\d+(?:\.\d+)?"
    if not re.fullmatch(fr"v{version_pattern}", tag or ""):
        raise ReleaseVersionError("release tag must use vX.Y or vX.Y.Z")
    if tag != expected_tag:
        raise ReleaseVersionError(f"release tag must be {expected_tag}")
    if not re.fullmatch(version_pattern, VERSION):
        raise ReleaseVersionError("HaloCue version is not a stable release version")
    expected_archive = f"{PRODUCT_NAME}-{VERSION}-windows-x64.zip"
    if PUBLIC_ARCHIVE_NAME != expected_archive:
        raise ReleaseVersionError("public archive name does not match HaloCue metadata")
    if verify_database:
        seed = require_clean_public_database(root)
        _verify_deterministic_public_database(seed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args(argv)
    try:
        check_release_version(args.tag)
    except (OSError, ReleaseVersionError, subprocess.SubprocessError) as exc:
        print(f"release version check failed: {exc}", file=sys.stderr)
        return 1
    print(f"release version check passed: v{VERSION} -> {PUBLIC_ARCHIVE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
