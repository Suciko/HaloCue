"""Deterministic public-source selection and export."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess

from release_tools.scanner import scan_tree


_PUBLIC_DIRECTORIES = {
    ".github",
    "branding",
    "css",
    "data",
    "docs",
    "examples",
    "js",
    "release_tools",
    "tests",
    "tools",
}
_PUBLIC_ROOT_FILES = {
    ".gitignore",
    "CHANGELOG.md",
    "HaloCue.spec",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "UPLOAD.md",
    "cast.example.json",
    "llm.json.example",
    "pyproject.toml",
    "pytest.ini",
    "requirements-dev.txt",
    "requirements-desktop-build.txt",
    "requirements.txt",
    "ui.html",
    "使用说明-从这里开始.md",
    "启动程序.cmd",
    "检查运行环境.cmd",
}
_EXCLUDED_PREFIXES = {
    ".git",
    ".playwright-cli",
    ".superpowers",
    ".thumbs",
    ".worktrees",
    "__pycache__",
    "assets",
    "chapters",
    "dist",
    "out",
    "output",
    "overrides",
    "release",
    "release-staging",
    "scripts",
    "staging",
    "voices",
}
_EXCLUDED_DOCS = {
    "docs/custom-assets-test-report.md",
}
_EXCLUDED_PRIVATE_TESTS = {
    "tests/test_spine_semantic_faces.py",
}
_BANNED_SUFFIXES = {
    ".aap",
    ".aas",
    ".atlas",
    ".bundle",
    ".db",
    ".gif",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".ogg",
    ".skel",
    ".spine",
    ".unity3d",
    ".wav",
    ".webp",
}
_PRIVATE_NAMES = {
    ".env",
    "aa_assets.db",
    "aa_config.json",
    "aa_resources.json",
    "cast.json",
    "llm.json",
    "llm_profiles.json",
    "secrets.json",
}


def is_public_source_path(relative_path: str) -> bool:
    """Return whether a repository-relative path belongs in public source."""

    normalized = relative_path.replace("\\", "/").strip("/")
    if not normalized or normalized != PurePosixPath(normalized).as_posix():
        return False
    path = PurePosixPath(normalized)
    lowered_parts = tuple(part.casefold() for part in path.parts)
    if any(part in _EXCLUDED_PREFIXES for part in lowered_parts):
        return False
    if (
        normalized.startswith("docs/superpowers/")
        or normalized in _EXCLUDED_DOCS
        or normalized in _EXCLUDED_PRIVATE_TESTS
    ):
        return False
    name = path.name.casefold()
    if name in _PRIVATE_NAMES:
        return False
    if name.startswith("cast-") and name.endswith(".json") and name != "cast.example.json":
        return False
    if name.endswith("-avatar.png") or name.startswith(("bg_", "event", "ui_fx_")):
        return False
    if path.suffix.casefold() in _BANNED_SUFFIXES:
        return normalized == "data/halocue_labels.db"
    if path.suffix.casefold() == ".png" and path.parts[0] != "branding":
        return False
    if len(path.parts) == 1:
        return path.suffix.casefold() == ".py" or path.name in _PUBLIC_ROOT_FILES
    if path.parts[0] not in _PUBLIC_DIRECTORIES:
        return False
    if path.parts[0] == "data":
        return normalized == "data/halocue_labels.db"
    return True


def _git(source_root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(source_root), *arguments],
        check=False,
        capture_output=True,
    )


def _require_repository_root(source_root: Path) -> None:
    result = _git(source_root, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise ValueError("source root must be a Git repository root")
    try:
        repository_root = Path(result.stdout.decode("utf-8").strip()).resolve()
    except UnicodeError as exc:
        raise ValueError("Git repository root is not UTF-8") from exc
    if repository_root != source_root:
        raise ValueError("source root must be the Git repository root")


def public_source_paths(source_root: Path) -> tuple[str, ...]:
    """Select allowlisted regular files from the Git index only."""

    source_root = Path(source_root).resolve()
    _require_repository_root(source_root)
    result = _git(source_root, "ls-files", "-z", "--stage")
    if result.returncode != 0:
        raise ValueError("tracked source manifest unavailable")
    selected: list[str] = []
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        try:
            metadata, encoded_path = record.split(b"\t", 1)
            mode = metadata.split(b" ", 1)[0]
            relative = encoded_path.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise ValueError("invalid Git index entry") from exc
        if mode != b"100644" and mode != b"100755":
            if is_public_source_path(relative):
                raise ValueError(f"public source entry is not a regular file: {relative}")
            continue
        if is_public_source_path(relative):
            selected.append(relative)
    return tuple(sorted(set(selected)))


def _index_bytes(source_root: Path, relative: str) -> bytes:
    result = _git(source_root, "cat-file", "blob", f":{relative}")
    if result.returncode != 0:
        raise ValueError(f"indexed source file unavailable: {relative}")
    return result.stdout


def _validated_destination(destination: Path, build_root: Path) -> tuple[Path, Path]:
    build_root = Path(build_root).resolve()
    destination = Path(destination).resolve()
    try:
        relative = destination.relative_to(build_root)
    except ValueError as exc:
        raise ValueError("destination must be below the explicit build root") from exc
    if not relative.parts:
        raise ValueError("destination must be below the explicit build root")
    if destination.exists():
        if not destination.is_dir() or destination.is_symlink():
            raise ValueError("destination must be an empty directory")
        if next(destination.iterdir(), None) is not None:
            raise ValueError("destination must be empty")
    return destination, build_root


def export_public_source(
    source_root: Path,
    destination: Path,
    *,
    build_root: Path,
) -> Path:
    """Export indexed public files, scan them, and write a hash manifest."""

    source_root = Path(source_root).resolve()
    destination, build_root = _validated_destination(destination, build_root)
    paths = public_source_paths(source_root)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        manifest: list[dict[str, object]] = []
        for relative in paths:
            data = _index_bytes(source_root, relative)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            manifest.append(
                {
                    "path": relative,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        manifest_path = destination / "PUBLIC_MANIFEST.json"
        manifest_path.write_text(
            json.dumps({"files": manifest}, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        findings = scan_tree(destination, mode="source")
        if findings:
            summary = ", ".join(
                f"{finding.code}:{finding.relative_path}" for finding in findings[:12]
            )
            raise ValueError(f"public source scan failed: {summary}")
        return manifest_path
    except Exception:
        # The containment check happened before creation; never broaden this target.
        destination.relative_to(build_root)
        if destination.exists():
            shutil.rmtree(destination)
        raise
