from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

import launcher
from halocue_meta import PUBLIC_ARCHIVE_NAME
import release_tools.build_public as public_builder
from release_tools.build_public import build_public_release
from release_tools.build_public import finalize_existing_bundle
from release_tools.manifest import public_source_paths
from release_tools.scanner import scan_tree
from runtime_paths import resolve_runtime_layout


ROOT = Path(__file__).resolve().parents[1]


def test_public_source_export_includes_pyinstaller_spec(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    (source / "HaloCue.spec").write_text("# public build spec\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(source), "add", "--", "HaloCue.spec"],
        check=True,
    )

    assert "HaloCue.spec" in public_source_paths(source)


def test_pyinstaller_policy_uses_minimal_hidden_imports_and_excludes_global_stacks():
    policy = public_builder.pyinstaller_policy()

    assert policy["hidden_imports"] == ("anthropic", "UnityPy")
    assert {
        "_pytest",
        "_tkinter",
        "archspec",
        "bcrypt",
        "cv2",
        "invoke",
        "matplotlib",
        "nacl",
        "numpy",
        "onnxruntime",
        "pandas",
        "paramiko",
        "pkg_resources",
        "pytest",
        "scipy",
        "setuptools",
        "sklearn",
        "tkinter",
        "torch",
        "torchvision",
        "transformers",
        "trio",
        "yt_dlp",
    } <= set(policy["excludes"])
    assert policy["metadata_recursive"] is False
    assert policy["version_file_environment"] == "HALOCUE_VERSION_FILE"
    assert {"MarkupSafe", "tqdm", "tzdata"} <= set(
        policy["metadata_distributions"]
    )


def _write_public_source(root: Path) -> None:
    files: dict[str, bytes] = {
        "HaloCue.spec": b"# fixture spec\n",
        "README.md": b"# HaloCue\n",
        "LICENSE": b"MIT License\n",
        "THIRD_PARTY_NOTICES.md": (
            b"# Third-party notices\n- `CPython`\n- `PyInstaller`\n"
        ),
        "halocue_meta.py": (
            b"PRODUCT_NAME = 'HaloCue'\n"
            b"VERSION = '0.9.0-beta.1'\n"
        ),
        "ui.html": b"<!doctype html><title>HaloCue</title>\n",
        "js/app.js": b"window.HaloCue = true;\n",
        "css/app.css": b"body { color: #111; }\n",
        "branding/halocue-icon.png": b"public icon fixture",
        "branding/halocue-favicon.png": b"public favicon fixture",
        "branding/halocue.ico": b"public ico fixture",
    }
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    seed = root / "data" / "halocue_labels.db"
    seed.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "data" / "halocue_labels.db", seed)
    files["data/halocue_labels.db"] = seed.read_bytes()
    manifest = [
        {
            "path": relative,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for relative, data in sorted(files.items())
    ]
    (root / "PUBLIC_MANIFEST.json").write_text(
        json.dumps({"files": manifest}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _fake_pyinstaller(source_root: Path, work_root: Path, python_executable: Path) -> None:
    assert source_root.is_dir()
    assert python_executable.is_file()
    bundle = work_root / "dist" / "HaloCue"
    internal = bundle / "_internal"
    internal.mkdir(parents=True)
    (bundle / "HaloCue.exe").write_bytes(b"MZ HaloCue fixture")
    (internal / "python312.dll").write_bytes(b"MZ Python runtime fixture")


def test_pyinstaller_runs_from_isolated_context_with_deterministic_version_file(
    tmp_path, monkeypatch
):
    source = tmp_path / "public-source" / "HaloCue"
    source.mkdir(parents=True)
    _write_public_source(source)
    work = tmp_path / "releases" / "build" / "pyinstaller"
    work.mkdir(parents=True)
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(public_builder.subprocess, "run", fake_run)

    public_builder._run_pyinstaller(source, work, Path(sys.executable))

    assert captured["cwd"] == work
    assert captured["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert captured["command"][-1] == str(source / "HaloCue.spec")
    version_path = Path(captured["env"]["HALOCUE_VERSION_FILE"])
    assert version_path.parent == work
    version_text = version_path.read_text(encoding="utf-8")
    for expected in (
        "filevers=(0, 9, 0, 1)",
        "prodvers=(0, 9, 0, 1)",
        "StringStruct('ProductName', 'HaloCue')",
        "StringStruct('FileDescription', 'HaloCue')",
        "StringStruct('FileVersion', '0.9.0-beta.1')",
        "StringStruct('ProductVersion', '0.9.0-beta.1')",
        "StringStruct('CompanyName', 'Suciko')",
        "StringStruct('OriginalFilename', 'HaloCue.exe')",
        "StringStruct('LegalCopyright', 'Copyright (c) 2026 Suciko')",
    ):
        assert expected in version_text
    assert not list(source.rglob("*.pyc"))
    assert not list(source.rglob("__pycache__"))


def test_version_file_accepts_stable_public_versions(tmp_path):
    source = tmp_path / "public-source" / "HaloCue"
    source.mkdir(parents=True)
    _write_public_source(source)
    (source / "halocue_meta.py").write_text(
        "PRODUCT_NAME = 'HaloCue'\nVERSION = '0.9.3'\n",
        encoding="utf-8",
    )
    work = tmp_path / "releases" / "build"
    work.mkdir(parents=True)

    version_text = public_builder._write_version_file(source, work).read_text(encoding="utf-8")

    assert "filevers=(0, 9, 3, 0)" in version_text
    assert "StringStruct('FileVersion', '0.9.3')" in version_text


def test_public_spec_uses_only_the_desensitized_database_seed():
    spec = (ROOT / "HaloCue.spec").read_text(encoding="utf-8")

    assert "data\" / \"halocue_labels.db" in spec
    assert "HALOCUE_BUILD_SEED_DIR" not in spec
    assert "aa_assets.db" not in spec
    assert "aa_resources.json" not in spec
    assert '"anthropic"' in spec and '"UnityPy"' in spec
    assert '"torch"' in spec and '"transformers"' in spec


def test_public_builder_revalidates_source_manifest_after_build(tmp_path, monkeypatch):
    source = tmp_path / "public-source" / "HaloCue"
    source.mkdir(parents=True)
    _write_public_source(source)

    def mutating_runner(source_root, work_root, python_executable):
        _fake_pyinstaller(source_root, work_root, python_executable)
        cache = source_root / "__pycache__"
        cache.mkdir()
        (cache / "leak.pyc").write_bytes(b"host bytecode")

    monkeypatch.setattr(public_builder, "_run_pyinstaller", mutating_runner)

    with pytest.raises(ValueError, match="PUBLIC_MANIFEST"):
        build_public_release(
            source,
            tmp_path / "releases",
            python_executable=Path(sys.executable),
        )


def test_dependency_notice_audit_requires_shipped_metadata_and_native_components(
    tmp_path,
):
    bundle = tmp_path / "HaloCue"
    metadata = bundle / "_internal" / "sample_dep-1.0.dist-info" / "METADATA"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("Name: sample-dep\nVersion: 1.0\n", encoding="utf-8")
    (bundle / "_internal" / "python313.dll").write_bytes(b"runtime")
    notices = bundle / "THIRD_PARTY_NOTICES.md"
    notices.write_text("# Notices\n- `CPython`\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sample-dep"):
        public_builder.audit_third_party_notices(bundle)

    notices.write_text(
        "# Notices\n- `CPython`\n- `sample-dep`\n",
        encoding="utf-8",
    )
    assert public_builder.audit_third_party_notices(bundle) == (
        "CPython",
        "sample-dep",
    )


def test_finalize_existing_bundle_replaces_only_notice_and_writes_artifacts(
    tmp_path,
):
    source = tmp_path / "public-source" / "HaloCue"
    source.mkdir(parents=True)
    _write_public_source(source)
    corrected_notice = b"# Notices\n- `CPython`\n- `PyInstaller`\n"
    notice_path = source / "THIRD_PARTY_NOTICES.md"
    notice_path.write_bytes(corrected_notice)
    payload = json.loads((source / "PUBLIC_MANIFEST.json").read_text(encoding="utf-8"))
    for entry in payload["files"]:
        if entry["path"] == "THIRD_PARTY_NOTICES.md":
            entry["size"] = len(corrected_notice)
            entry["sha256"] = hashlib.sha256(corrected_notice).hexdigest()
    (source / "PUBLIC_MANIFEST.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "releases"
    bundle = output / "HaloCue"
    internal = bundle / "_internal"
    internal.mkdir(parents=True)
    (bundle / "HaloCue.exe").write_bytes(b"MZ existing lean bundle")
    (bundle / "THIRD_PARTY_NOTICES.md").write_text(
        "# stale notice\n- `CPython`\n- `PyInstaller`\n",
        encoding="utf-8",
    )
    for relative in public_builder._PUBLIC_RESOURCES:
        if relative == "THIRD_PARTY_NOTICES.md":
            continue
        source_path = source / relative
        destination = bundle / relative
        if source_path.is_dir():
            shutil.copytree(source_path, destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
    (internal / "python313.dll").write_bytes(b"runtime")
    before = {
        path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "THIRD_PARTY_NOTICES.md"
    }

    result = finalize_existing_bundle(source, bundle, output)

    after = {
        path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "THIRD_PARTY_NOTICES.md"
    }
    assert after == before
    assert (bundle / "THIRD_PARTY_NOTICES.md").read_bytes() == corrected_notice
    assert result.archive_path.is_file()
    assert result.manifest_path.is_file()


def _polluted_pyinstaller(
    source_root: Path, work_root: Path, python_executable: Path
) -> None:
    _fake_pyinstaller(source_root, work_root, python_executable)
    internal = work_root / "dist" / "HaloCue" / "_internal"
    gif = internal / "_tk_data" / "images" / "logo.gif"
    gif.parent.mkdir(parents=True)
    gif.write_bytes(b"GIF89a")
    metadata = internal / "archspec-0.2.5.dist-info" / "direct_url.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(
        json.dumps({"url": "file:///C:/Users/Private/conda-build/archspec"}),
        encoding="utf-8",
    )
    optional = internal / "torch" / "testing.py"
    optional.parent.mkdir(parents=True)
    optional.write_text("# optional global package\n", encoding="utf-8")


def test_public_builder_creates_exact_audited_archive_layout(tmp_path, monkeypatch):
    source = tmp_path / "public-source" / "HaloCue"
    source.mkdir(parents=True)
    _write_public_source(source)
    monkeypatch.setattr(
        "release_tools.build_public._run_pyinstaller",
        _fake_pyinstaller,
    )

    result = build_public_release(
        source,
        tmp_path / "releases",
        python_executable=Path(sys.executable),
    )

    assert result.bundle_dir.name == "HaloCue"
    assert result.archive_path.name == PUBLIC_ARCHIVE_NAME
    assert result.archive_sha256 == hashlib.sha256(
        result.archive_path.read_bytes()
    ).hexdigest()
    required = {
        "HaloCue/HaloCue.exe",
        "HaloCue/ui.html",
        "HaloCue/js/app.js",
        "HaloCue/css/app.css",
        "HaloCue/branding/halocue-icon.png",
        "HaloCue/branding/halocue-favicon.png",
        "HaloCue/data/halocue_labels.db",
        "HaloCue/_internal/ui.html",
        "HaloCue/_internal/branding/halocue-icon.png",
        "HaloCue/_internal/data/halocue_labels.db",
        "HaloCue/LICENSE",
        "HaloCue/THIRD_PARTY_NOTICES.md",
    }
    with zipfile.ZipFile(result.archive_path) as archive:
        names = {name.rstrip("/") for name in archive.namelist()}
        assert required <= names
        assert {name.split("/", 1)[0] for name in names} == {"HaloCue"}
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
    lowered = {name.casefold() for name in names}
    assert not any(name.endswith("python.exe") for name in lowered)
    assert not any(
        forbidden in name
        for name in lowered
        for forbidden in (
            "aa_config.json",
            "aa_assets.db",
            "aa_resources.json",
            "llm.json",
            "llm_profiles.json",
            "/tests/",
            "/build/",
            "spine.exe",
            "spine.com",
            ".skel",
            ".atlas",
        )
    )
    assert scan_tree(result.bundle_dir, mode="public") == ()


def test_public_manifest_hashes_every_shipped_file(tmp_path, monkeypatch):
    source = tmp_path / "public-source" / "HaloCue"
    source.mkdir(parents=True)
    _write_public_source(source)
    monkeypatch.setattr(
        "release_tools.build_public._run_pyinstaller",
        _fake_pyinstaller,
    )

    result = build_public_release(
        source,
        tmp_path / "releases",
        python_executable=Path(sys.executable),
    )

    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    entries = payload["files"]
    assert [entry["path"] for entry in entries] == sorted(
        entry["path"] for entry in entries
    )
    shipped = {
        path.relative_to(result.bundle_dir).as_posix(): path
        for path in result.bundle_dir.rglob("*")
        if path.is_file()
    }
    assert {entry["path"] for entry in entries} == set(shipped)
    for entry in entries:
        data = shipped[entry["path"]].read_bytes()
        assert entry == {
            "path": entry["path"],
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    checksum = result.archive_path.with_suffix(result.archive_path.suffix + ".sha256")
    assert checksum.read_text(encoding="ascii") == (
        f"{result.archive_sha256}  {result.archive_path.name}\n"
    )


def test_public_builder_removes_environment_only_pyinstaller_payloads(
    tmp_path, monkeypatch
):
    source = tmp_path / "public-source" / "HaloCue"
    source.mkdir(parents=True)
    _write_public_source(source)
    monkeypatch.setattr(
        "release_tools.build_public._run_pyinstaller",
        _polluted_pyinstaller,
    )

    result = build_public_release(
        source,
        tmp_path / "releases",
        python_executable=Path(sys.executable),
    )

    assert not (result.bundle_dir / "_internal" / "_tk_data" / "images" / "logo.gif").exists()
    assert not list(result.bundle_dir.rglob("direct_url.json"))
    assert not (result.bundle_dir / "_internal" / "torch").exists()
    assert scan_tree(result.bundle_dir, mode="public") == ()


def test_public_builder_rejects_source_not_matching_export_manifest(tmp_path, monkeypatch):
    source = tmp_path / "public-source" / "HaloCue"
    source.mkdir(parents=True)
    _write_public_source(source)
    (source / "private.txt").write_text("not in export manifest", encoding="utf-8")
    called = False

    def fail_if_called(*_args):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "release_tools.build_public._run_pyinstaller",
        fail_if_called,
    )

    with pytest.raises(ValueError, match="PUBLIC_MANIFEST"):
        build_public_release(
            source,
            tmp_path / "releases",
            python_executable=Path(sys.executable),
        )

    assert called is False


@pytest.mark.skip(reason="0.9.2 frozen builds launch the embedded WebView2 desktop shell.")
def test_frozen_launcher_calls_webui_directly_and_forwards_server_options(
    tmp_path, monkeypatch
):
    calls: list[list[str]] = []
    fake_webui = SimpleNamespace(main=lambda argv: calls.append(argv) or 23)
    monkeypatch.setitem(sys.modules, "webui", fake_webui)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(launcher, "is_existing_server", lambda _url: False)
    monkeypatch.setattr(
        launcher.subprocess,
        "call",
        lambda *_args, **_kwargs: pytest.fail("frozen launcher used a subprocess"),
    )
    data = tmp_path / "AA data"

    result = launcher._start_application(data, port=9123, no_browser=True)

    assert result == 23
    assert calls == [["--aa-data", str(data), "--port", "9123", "--no-browser"]]


def test_frozen_runtime_reads_resources_beside_executable_and_writes_localappdata(
    tmp_path, monkeypatch
):
    bundle = tmp_path / "portable" / "HaloCue"
    internal = bundle / "_internal"
    executable = bundle / "HaloCue.exe"
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)

    layout = resolve_runtime_layout(
        module_file=internal / "runtime_paths.py",
        executable=executable,
        environ={"LOCALAPPDATA": str(local_app_data)},
    )

    assert layout.resource_root == bundle.resolve()
    assert layout.database_seed_path == bundle.resolve() / "data" / "halocue_labels.db"
    assert layout.user_data_root == (local_app_data / "HaloCue").resolve()
