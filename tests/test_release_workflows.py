from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from halocue_meta import PUBLIC_ARCHIVE_NAME, VERSION


ROOT = Path(__file__).resolve().parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def _job_block(workflow: str, job_name: str) -> str:
    lines = workflow.splitlines()
    start = lines.index(f"  {job_name}:")
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("  ")
            and not lines[index].startswith("    ")
            and lines[index].endswith(":")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_ci_workflow_has_windows_matrix_and_complete_public_gates():
    workflow = _workflow("ci.yml")

    assert "actions/checkout@v4" in workflow
    assert "actions/setup-python@v5" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "runs-on: windows-latest" in workflow
    for version in ("3.10", "3.12", "3.13"):
        assert version in workflow
    assert "requirements-dev.txt" in workflow
    assert "playwright install chromium" in workflow
    assert "python -m pytest -q" in workflow
    assert workflow.count("release_tools.public_db") >= 2
    assert "Compare-Object" in workflow
    assert "tools/export_public_source.py" in workflow
    assert "tools/scan_release.py" in workflow
    assert "tools/build_public_release.py" in workflow
    assert "tools/verify_release.py" in workflow
    assert "needs: test" in workflow
    assert PUBLIC_ARCHIVE_NAME in workflow


def test_ci_package_job_installs_browser_before_release_verification():
    package_job = _job_block(_workflow("ci.yml"), "package")

    browser_install = "python -m playwright install chromium"
    release_verification = "python tools/verify_release.py"
    assert browser_install in package_job
    assert package_job.index(browser_install) < package_job.index(release_verification)


def test_release_workflow_is_exact_tag_gated_and_public_only():
    workflow = _workflow("release.yml")
    combined = workflow + "\n" + _workflow("ci.yml")
    lowered = combined.casefold()

    assert "tags:" in workflow and "'v*'" in workflow
    assert "contents: write" in workflow
    assert "actions/checkout@v4" in workflow
    assert "actions/setup-python@v5" in workflow
    assert "tools/check_release_version.py --tag" in workflow
    assert "GITHUB_REF_NAME" in workflow
    assert "gh release create" in workflow
    assert "--draft" in workflow and "--prerelease" in workflow
    assert PUBLIC_ARCHIVE_NAME in workflow
    assert PUBLIC_ARCHIVE_NAME + ".sha256" in workflow
    assert "github.token" in workflow
    assert "build_private" not in lowered
    assert "spine_source" not in lowered
    assert "private-windows" not in lowered
    assert "secrets." not in lowered


def test_version_gate_accepts_only_exact_beta_tag_and_metadata():
    from tools.check_release_version import ReleaseVersionError, check_release_version

    # Public-source exports intentionally have no .git directory. Keep tag and
    # metadata validation hermetic; Git cleanliness is covered separately below.
    check_release_version(f"v{VERSION}", ROOT, verify_database=False)
    for tag in (VERSION, "v0.9.0", "v0.9.0-beta.2", "release-0.9.0-beta.1"):
        with pytest.raises(ReleaseVersionError):
            check_release_version(tag, ROOT, verify_database=False)


def test_version_gate_rejects_dirty_generated_public_database(tmp_path):
    from tools.check_release_version import (
        ReleaseVersionError,
        require_clean_public_database,
    )

    repository = tmp_path / "repository"
    seed = repository / "data" / "halocue_labels.db"
    seed.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "data" / "halocue_labels.db", seed)
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "add", "data/halocue_labels.db"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=HaloCue Tests",
            "-c",
            "user.email=tests@example.invalid",
            "commit",
            "-qm",
            "seed",
        ],
        check=True,
    )
    seed.write_bytes(seed.read_bytes() + b"dirty")

    with pytest.raises(ReleaseVersionError, match="dirty"):
        require_clean_public_database(repository)
