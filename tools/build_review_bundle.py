"""Export a sanitized WORKTREE review snapshot, never a replacement for Git sync."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from release_tools.manifest import is_public_source_path  # noqa: E402
from release_tools.scanner import scan_tree  # noqa: E402
from halocue_meta import DISPLAY_NAME, PRODUCT_NAME, VERSION  # noqa: E402

EXTRA_ROOT = {
    "AGENTS.md",
    "CONTEXT-MAP.md",
    "CONTRIBUTING.md",
    ".python-version",
    ".nvmrc",
    "rust-toolchain.toml",
    "migration-status.json",
    "portrait_layout_hints.json",
    "START_REVIEW.md",
    "开始验收.cmd",
    "requirements-review.txt",
}
TEXT = {
    ".py",
    ".md",
    ".json",
    ".html",
    ".css",
    ".js",
    ".cjs",
    ".mjs",
    ".toml",
    ".ini",
    ".txt",
    ".yml",
    ".yaml",
    ".ts",
    ".tsx",
    ".rs",
    ".cmd",
    ".ps1",
    ".svg",
    ".lock",
}


def selected_path(relative: str) -> bool:
    path = PurePosixPath(relative)
    if relative in {
        "PUBLIC_MANIFEST.json",
        "REVIEW_MANIFEST.json",
        "migration-status.json",
        "services/halocue/writing/docs/six-goal-evidence-audit.md",
    }:
        return False
    if any(
        "backup" in part.lower()
        or part.lower()
        in {
            "__pycache__",
            "node_modules",
            "target",
            ".tmp",
            ".scratch",
            ".review-data",
            ".review-venv",
        }
        for part in path.parts[:-1]
    ):
        return False
    if relative.startswith(("docs/handoffs/", "docs/superpowers/", "docs/agents/skill-proposals/")):
        return False
    if path.parts[0] == "docs":
        return relative.startswith(
            ("docs/review/", "docs/adr/", "docs/architecture/", "docs/agents/")
        ) or path.name in {
            "product-direction-1.x.md",
            "用户手册-1.0.md",
            "1.0-complete-package.md",
            "version-lineage.md",
            "private-release.md",
            "commands.md",
        }
    if path.parts[0] == "services":
        return path.suffix in TEXT
    if path.parts[0] in {"contexts", "packages", "apps", ".agents", "legacy", "legacy_help"}:
        return path.suffix in TEXT
    return relative in EXTRA_ROOT or is_public_source_path(relative)


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args]).decode("utf-8").strip()


def build(destination: Path, name: str) -> dict:
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    stage = destination / name
    if stage.exists():
        raise ValueError(
            "Use a new destination/name; existing review snapshots are never overwritten"
        )
    paths = sorted(
        set(git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0"))
    )
    selected = [
        relative
        for relative in paths
        if relative and selected_path(relative) and (ROOT / relative).is_file()
    ]
    stage.mkdir()
    manifest = []
    for relative in selected:
        source = ROOT / relative
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT):
            raise ValueError("Refusing linked or external input: " + relative)
        data = source.read_bytes()
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest.append(
            {"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        )
    findings = scan_tree(stage, mode="source")
    report = {
        "schema_version": "review-bundle/1.0",
        "product": PRODUCT_NAME,
        "product_version": VERSION,
        "display_name": DISPLAY_NAME,
        "package_kind": "collaborator_source_review",
        "entrypoint": "开始验收.cmd",
        "source_state": "working_tree_snapshot_not_pushed",
        "base_commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "files": manifest,
        "scan_findings": [{"code": f.code, "path": f.relative_path} for f in findings],
    }
    (destination / (name + "-scan.json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if findings:
        raise ValueError("Review archive NOT created; inspect " + name + "-scan.json")
    (stage / "REVIEW_MANIFEST.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    archive = destination / (name + ".zip")
    if archive.exists():
        raise ValueError("Archive already exists")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for item in sorted(stage.rglob("*")):
            if item.is_file():
                output.write(item, arcname=name + "/" + item.relative_to(stage).as_posix())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / (archive.name + ".sha256")).write_text(
        digest + "  " + archive.name + "\n", encoding="utf-8"
    )
    return {
        "archive": str(archive),
        "source_directory": str(stage),
        "files": len(manifest),
        "bytes": archive.stat().st_size,
        "sha256": digest,
        "scan_findings": 0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--name", default="HaloCue-review-source-20260926")
    args = parser.parse_args()
    if not args.name or Path(args.name).name != args.name or args.name in {".", ".."}:
        parser.error("name must be a single directory name")
    print(json.dumps(build(args.output_dir, args.name), ensure_ascii=False, indent=2))
