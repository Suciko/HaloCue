"""Public runtime dependencies are pinned and portable; no login state is copied."""

import base64
import hashlib
import io
import json
import os
import subprocess
import tarfile

import pytest

from release_tools import codex_runtime as runtime
from release_tools.scanner import scan_tree
from services.halocue import codex_agent as codex


@pytest.fixture
def package(tmp_path, monkeypatch):
    cache = tmp_path / "download"
    cache.mkdir()
    archive = cache / f"codex-{runtime.VERSION}-win32-x64.tgz"
    with tarfile.open(archive, "w:gz") as output:
        for name in runtime.PACKAGE_FILES:
            data = b"MZ synthetic runtime" if name.endswith(".exe") else b"synthetic"
            if name == "package.json":
                data = json.dumps(
                    {"name": "@openai/codex", "version": runtime.VERSION + "-win32-x64"}
                ).encode()
            elif name.endswith(".json"):
                data = b"{}"
            member = tarfile.TarInfo("package/" + name)
            member.size = len(data)
            output.addfile(member, io.BytesIO(data))
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()
    monkeypatch.setattr(runtime, "PACKAGE_INTEGRITY", integrity)
    hashes = {}
    for name in runtime.DOCUMENT_HASHES:
        data = f"synthetic {name}".encode()
        (cache / name).write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(runtime, "DOCUMENT_HASHES", hashes)
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, f"codex-cli {runtime.VERSION}\n", ""
        ),
    )
    monkeypatch.setattr(
        runtime, "_download", lambda *args: pytest.fail("unexpected network download")
    )
    return cache


def test_bundle_keeps_native_dependencies_provenance_and_notices_only(package, tmp_path):
    bundle = tmp_path / "portable package"
    target = runtime.bundle_codex_runtime(bundle, package)
    runtime.audit_codex_runtime(bundle)
    assert scan_tree(bundle, mode="public") == ()
    assert {
        file.relative_to(target).as_posix() for file in target.rglob("*") if file.is_file()
    } == {
        *runtime.PACKAGE_FILES,
        *runtime.DOCUMENT_HASHES,
        "provenance.json",
    }
    assert not (target / "auth.json").exists()


def test_modified_download_is_rejected_before_extraction(package, tmp_path):
    archive = package / f"codex-{runtime.VERSION}-win32-x64.tgz"
    archive.write_bytes(archive.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="integrity mismatch"):
        runtime.bundle_codex_runtime(tmp_path / "bundle", package)
    assert not list((tmp_path / "bundle").rglob("*.exe"))


def test_electron_release_audit_requires_complete_runtime_even_when_tools_directory_absent(
    package, tmp_path
):
    from release_tools.build_public import audit_third_party_notices

    bundle = tmp_path / "electron"
    (bundle / "resources").mkdir(parents=True)
    (bundle / "resources/app.asar").write_bytes(b"synthetic Electron archive")
    for name in ("LICENSE.electron.txt", "LICENSES.chromium.html"):
        (bundle / name).write_text("Synthetic Electron notice", encoding="utf-8")
    (bundle / "THIRD_PARTY_NOTICES.md").write_text(
        "`Electron`\n`Chromium`\n`Node.js`\n`OpenAI Codex`\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="missing or unexpected"):
        audit_third_party_notices(bundle)
    runtime.bundle_codex_runtime(bundle, package)
    assert audit_third_party_notices(bundle) == ("Chromium", "Electron", "Node.js", "OpenAI Codex")


@pytest.mark.parametrize("change", ["missing", "modified", "account"])
def test_runtime_audit_rejects_missing_modified_or_private_files(package, tmp_path, change):
    bundle = tmp_path / "bundle"
    target = runtime.bundle_codex_runtime(bundle, package)
    cli = target / runtime.PACKAGE_FILES[0]
    if change == "missing":
        cli.unlink()
    elif change == "modified":
        cli.write_bytes(b"different")
    else:
        (target / "auth.json").write_text("{}")
    with pytest.raises(ValueError, match="missing or unexpected|hash mismatch"):
        runtime.audit_codex_runtime(bundle)


@pytest.mark.skipif(os.name != "nt", reason="The shipped native runtime is Windows x64")
@pytest.mark.parametrize("frozen", [False, True])
def test_bundle_is_discovered_without_cli_node_or_python_on_path(tmp_path, monkeypatch, frozen):
    root = tmp_path / "中文 portable package"
    cli = root / "tools/codex" / runtime.PACKAGE_FILES[0]
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b"synthetic native executable")
    monkeypatch.setattr(codex.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(codex.sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(codex.sys, "executable", str(root / "HaloCueBackend.exe"))
    monkeypatch.setattr(
        codex, "repository_root", lambda: tmp_path / "unrelated" if frozen else root
    )
    monkeypatch.setattr(codex.shutil, "which", lambda name: pytest.fail("bundle must precede PATH"))
    monkeypatch.setenv("PATH", "")
    assert codex.discover_cli() == cli.resolve()
    override = tmp_path / "explicit.exe"
    override.write_bytes(b"synthetic override")
    assert codex.discover_cli(str(override)) == override.resolve()


def test_scanner_rejects_unrelated_executable_inside_runtime_directory(tmp_path):
    target = tmp_path / "tools/codex/unreviewed.exe"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"MZ synthetic")
    assert any(item.code == "unexpected-executable" for item in scan_tree(tmp_path, mode="public"))
