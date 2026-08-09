from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest
import prepare_release

from release_tools.manifest import (
    export_public_source,
    is_public_source_path,
    public_source_paths,
)
from tools.verify_clean_source import verify


REQUIRED_ROOT_MODULES = {
    "background_labeler.py",
    "build_bundle.py",
    "diagnostics.py",
    "direction_rules.py",
    "document.py",
    "draft_identity.py",
    "draft_store.py",
    "history_assets.py",
    "install_manager.py",
    "jobs.py",
    "model_capabilities.py",
    "model_router.py",
    "official_staging_corpus.py",
    "picker_token.py",
    "story_file_picker.py",
    "story_workspace.py",
    "annotation_telemetry.py",
}


def _tracked_source(tmp_path: Path, files: dict[str, bytes | str]) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    for relative, payload in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, bytes):
            path.write_bytes(payload)
        else:
            path.write_text(payload, encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(source), "add", "-f", "--", *files], check=True
    )
    return source


def test_public_manifest_includes_runtime_frontend_tests_and_tools(tmp_path):
    safe = {name: "# public\n" for name in REQUIRED_ROOT_MODULES}
    safe.update(
        {
            "css/app.css": "body {}\n",
            "js/app.js": "export {};\n",
            "branding/halocue-icon.png": b"public icon",
            "tests/test_smoke.py": "def test_smoke(): assert True\n",
            "tools/check.py": "# tool\n",
            "release_tools/__init__.py": "",
            "docs/commands.md": "# Commands\n",
            ".github/workflows/ci.yml": "name: ci\n",
            "examples/demo.txt": "demo\n",
            "README.md": "# HaloCue\n",
            "requirements.txt": "pytest\n",
            "LICENSE": "MIT\n",
            "data/halocue_labels.db": b"public seed fixture",
        }
    )
    source = _tracked_source(tmp_path, safe)

    paths = set(public_source_paths(source))

    assert REQUIRED_ROOT_MODULES <= paths
    assert {
        "css/app.css",
        "js/app.js",
        "branding/halocue-icon.png",
        "tests/test_smoke.py",
        "tools/check.py",
        "release_tools/__init__.py",
        "docs/commands.md",
        ".github/workflows/ci.yml",
        "examples/demo.txt",
        "data/halocue_labels.db",
    } <= paths


def test_public_manifest_excludes_private_paths_and_assets(tmp_path):
    files = {
        "safe.py": "# public\n",
        ".superpowers/task.md": "private\n",
        ".playwright-cli/state.json": "{}\n",
        "docs/superpowers/plan.md": "private\n",
        "docs/custom-assets-test-report.md": "private\n",
        "output/story.txt": "private\n",
        "out/cache.txt": "private\n",
        "scripts/story.txt": "private\n",
        "chapters/chapter.txt": "private\n",
        "aa_assets.db": b"private",
        "aa_resources.json": "{}\n",
        "aa_config.json": "{}\n",
        "llm.json": "{}\n",
        "llm_profiles.json": "{}\n",
        "cast.json": "{}\n",
        "cast-personal.json": "{}\n",
        "assets/character.skel": b"private",
        "assets/character.atlas": b"private",
        "voices/line.ogg": b"private",
        "images/BG_room.png": b"private",
        "project/story.aap": b"private",
        "tests/test_spine_semantic_faces.py": "PRIVATE_SKELETON = 'local'\n",
    }
    source = _tracked_source(tmp_path, files)

    assert public_source_paths(source) == ("safe.py",)
    assert not is_public_source_path(".git/config")


def test_export_reads_tracked_files_from_index_and_writes_sorted_hash_manifest(
    tmp_path,
):
    source = _tracked_source(
        tmp_path,
        {
            "app.py": "VALUE = 'indexed'\n",
            "css/app.css": "body {}\n",
        },
    )
    (source / "app.py").write_text("VALUE = 'dirty worktree'\n", encoding="utf-8")
    build_root = tmp_path / "build"
    destination = build_root / "public-source" / "HaloCue"

    manifest_path = export_public_source(
        source, destination, build_root=build_root
    )

    assert (destination / "app.py").read_text(encoding="utf-8") == "VALUE = 'indexed'\n"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [item["path"] for item in payload["files"]] == ["app.py", "css/app.css"]
    assert payload["files"][0] == {
        "path": "app.py",
        "size": len(b"VALUE = 'indexed'\n"),
        "sha256": hashlib.sha256(b"VALUE = 'indexed'\n").hexdigest(),
    }


def test_export_requires_empty_destination_inside_explicit_build_root(tmp_path):
    source = _tracked_source(tmp_path, {"app.py": "# public\n"})
    build_root = tmp_path / "build"
    nonempty = build_root / "nonempty"
    nonempty.mkdir(parents=True)
    (nonempty / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        export_public_source(source, nonempty, build_root=build_root)
    with pytest.raises(ValueError, match="build root"):
        export_public_source(
            source, tmp_path / "outside", build_root=build_root
        )

    assert (nonempty / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_export_removes_only_its_incomplete_staging_tree_on_scan_failure(tmp_path):
    marker = "C:" + "\\" + "Users" + "\\" + "SakuraLeak" + "\\" + "private.txt"
    source = _tracked_source(tmp_path, {"app.py": f"VALUE = {marker!r}\n"})
    build_root = tmp_path / "build"
    destination = build_root / "public-source" / "HaloCue"
    sibling = build_root / "keep"
    sibling.mkdir(parents=True)
    (sibling / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="scan"):
        export_public_source(source, destination, build_root=build_root)

    assert not destination.exists()
    assert (sibling / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_clean_source_verifier_uses_export_manifest_without_git_metadata(tmp_path):
    source = _tracked_source(
        tmp_path,
        {
            "app.py": "VALUE = 'public'\n",
            "tests/test_smoke.py": "def test_smoke(): assert True\n",
        },
    )
    build_root = source / "build"
    destination = build_root / "public-source" / "HaloCue"
    export_public_source(source, destination, build_root=build_root)

    assert verify(destination) == []


def test_prepare_release_check_scans_index_candidate_not_git_metadata(
    tmp_path, monkeypatch, capsys
):
    source = _tracked_source(tmp_path, {"app.py": "VALUE = 'public'\n"})
    marker = "qwertyuiopasdfghjklzxcvbnm123456"
    (source / ".git" / "private-probe.txt").write_text(
        "api_key=" + repr(marker), encoding="utf-8"
    )
    monkeypatch.setattr(prepare_release, "HERE", source)

    result = prepare_release.main(["--check"])
    output = capsys.readouterr().out

    assert result == 0
    assert "zero findings" in output
    assert marker not in output
    assert str(source) not in output
