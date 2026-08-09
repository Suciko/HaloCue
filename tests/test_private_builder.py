from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

import pytest

from halocue_meta import PRIVATE_ARCHIVE_NAME, PUBLIC_ARCHIVE_NAME
import release_tools.build_private as private_builder
from release_tools.build_private import build_private_release
from release_tools.scanner import scan_tree


ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _zip_tree(root: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if not path.is_file():
                continue
            relative = path.relative_to(root.parent).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            output.writestr(info, path.read_bytes())


def _public_release(tmp_path: Path) -> Path:
    bundle = tmp_path / "public-input" / "HaloCue"
    (bundle / "data").mkdir(parents=True)
    (bundle / "branding").mkdir()
    (bundle / "js").mkdir()
    (bundle / "css").mkdir()
    (bundle / "HaloCue.exe").write_bytes(b"synthetic public executable")
    (bundle / "LICENSE").write_text("MIT synthetic fixture\n", encoding="utf-8")
    (bundle / "THIRD_PARTY_NOTICES.md").write_text("Synthetic notices\n", encoding="utf-8")
    (bundle / "ui.html").write_text("<title>HaloCue</title>\n", encoding="utf-8")
    (bundle / "js" / "app.js").write_text("window.HaloCue = true;\n", encoding="utf-8")
    (bundle / "css" / "app.css").write_text("body { color: #fff; }\n", encoding="utf-8")
    shutil.copyfile(ROOT / "branding" / "halocue-favicon.png", bundle / "branding" / "halocue-favicon.png")
    shutil.copyfile(ROOT / "data" / "halocue_labels.db", bundle / "data" / "halocue_labels.db")

    files = []
    for path in sorted(bundle.rglob("*"), key=lambda item: item.relative_to(bundle).as_posix()):
        if path.is_file():
            data = path.read_bytes()
            files.append({
                "path": path.relative_to(bundle).as_posix(),
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
    manifest = tmp_path / "public-input" / "HaloCue-build-manifest.json"
    manifest.write_text(json.dumps({"files": files}, indent=2), encoding="utf-8")
    archive = tmp_path / "public-input" / PUBLIC_ARCHIVE_NAME
    _zip_tree(bundle, archive)
    (archive.parent / f"{archive.name}.sha256").write_text(
        f"{_sha(archive)}  {archive.name}\n", encoding="ascii"
    )
    return archive


def _spine_source(tmp_path: Path) -> Path:
    source = tmp_path / "synthetic-spine"
    source.mkdir()
    # A venv launcher requires its adjacent pyvenv.cfg after being copied.
    # The base executable plus its runtime DLL is a self-contained --version
    # stand-in on every supported Python version.
    base_executable = Path(sys.base_prefix) / "python.exe"
    shutil.copyfile(base_executable, source / "Spine.com")
    runtime = Path(sys.base_prefix) / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    if runtime.is_file():
        shutil.copyfile(runtime, source / runtime.name)
    return source


def _attestation(source: Path, path: Path, **updates) -> Path:
    authorized_files = [
        {
            "path": "Spine.com",
            "sha256": _sha(source / "Spine.com"),
            "classification": "vendor_program",
        }
    ]
    for runtime in sorted(source.glob("python*.dll")):
        authorized_files.append({
            "path": runtime.name,
            "sha256": _sha(runtime),
            "classification": "vendor_runtime_library",
        })
    payload = {
        "authorized_to_redistribute": True,
        "authorization_basis": "synthetic written-permission fixture",
        "spine_version": f"synthetic-{sys.version_info.major}.{sys.version_info.minor}",
        "authorized_runtime_files": authorized_files,
    }
    payload.update(updates)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_private_builder_requires_complete_positive_attestation(tmp_path):
    public = _public_release(tmp_path)
    spine = _spine_source(tmp_path)
    for update in (
        {"authorized_to_redistribute": False},
        {"authorization_basis": ""},
        {"spine_version": ""},
        {"authorized_runtime_files": []},
    ):
        attestation = _attestation(spine, tmp_path / "attestation.json", **update)
        with pytest.raises(ValueError, match="attestation"):
            build_private_release(public, spine, attestation, tmp_path / "out")


def test_private_builder_rejects_tampered_public_release(tmp_path):
    public = _public_release(tmp_path)
    spine = _spine_source(tmp_path)
    attestation = _attestation(spine, tmp_path / "attestation.json")
    public.write_bytes(public.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="public archive"):
        build_private_release(public, spine, attestation, tmp_path / "out")


@pytest.mark.parametrize(
    "relative",
    (
        "personal.skel",
        "personal.atlas",
        "project.spine",
        "story.aap",
        "story.aas",
        "audio.ogg",
        "game.assetbundle",
        "activation.dat",
        "credentials.json",
        "crash.log",
        "recent-files.txt",
        "projects/project.json",
    ),
)
def test_private_builder_rejects_personal_or_state_files(tmp_path, relative):
    public = _public_release(tmp_path)
    spine = _spine_source(tmp_path)
    extra = spine / relative
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_text("synthetic forbidden fixture", encoding="utf-8")
    attestation = _attestation(spine, tmp_path / "attestation.json")
    payload = json.loads(attestation.read_text(encoding="utf-8"))
    payload["authorized_runtime_files"].append(
        {"path": relative, "sha256": _sha(extra), "classification": "vendor_runtime_resource"}
    )
    attestation.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden"):
        build_private_release(public, spine, attestation, tmp_path / "out")


def test_private_builder_rejects_unlisted_hash_mismatch_and_unclassified_image(tmp_path):
    public = _public_release(tmp_path)
    spine = _spine_source(tmp_path)
    (spine / "extra.dll").write_bytes(b"vendor library")
    attestation = _attestation(spine, tmp_path / "attestation.json")
    with pytest.raises(ValueError, match="absent from attestation"):
        build_private_release(public, spine, attestation, tmp_path / "out-a")
    (spine / "extra.dll").unlink()

    attestation = _attestation(spine, tmp_path / "attestation.json")
    payload = json.loads(attestation.read_text(encoding="utf-8"))
    payload["authorized_runtime_files"][0]["sha256"] = "0" * 64
    attestation.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        build_private_release(public, spine, attestation, tmp_path / "out-b")

    (spine / "launcher.png").write_bytes((ROOT / "branding" / "halocue-favicon.png").read_bytes())
    (spine / "extra.dll").write_bytes(b"vendor library")
    attestation = _attestation(spine, tmp_path / "attestation.json")
    payload = json.loads(attestation.read_text(encoding="utf-8"))
    payload["authorized_runtime_files"].extend([
        {"path": "launcher.png", "sha256": _sha(spine / "launcher.png"), "classification": "vendor_program"},
        {"path": "extra.dll", "sha256": _sha(spine / "extra.dll"), "classification": "vendor_runtime_library"},
    ])
    attestation.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="image"):
        build_private_release(public, spine, attestation, tmp_path / "out-c")


def test_private_builder_rejects_personal_paths_in_allowlisted_text(tmp_path):
    public = _public_release(tmp_path)
    spine = _spine_source(tmp_path)
    settings = spine / "vendor.txt"
    settings.write_text("/home/" + "operator-leak/private", encoding="utf-8")
    attestation = _attestation(spine, tmp_path / "attestation.json")
    payload = json.loads(attestation.read_text(encoding="utf-8"))
    payload["authorized_runtime_files"].append(
        {"path": "vendor.txt", "sha256": _sha(settings), "classification": "vendor_runtime_resource"}
    )
    attestation.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden"):
        build_private_release(public, spine, attestation, tmp_path / "out")


def test_private_builder_rejects_even_an_empty_project_directory(tmp_path):
    public = _public_release(tmp_path)
    spine = _spine_source(tmp_path)
    (spine / "projects").mkdir()
    attestation = _attestation(spine, tmp_path / "attestation.json")

    with pytest.raises(ValueError, match="forbidden directory"):
        build_private_release(public, spine, attestation, tmp_path / "out")


def test_private_builder_rejects_links(tmp_path):
    public = _public_release(tmp_path)
    spine = _spine_source(tmp_path)
    target = tmp_path / "outside.dll"
    target.write_bytes(b"outside")
    link = spine / "runtime.dll"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable for this Windows user")
    attestation = _attestation(spine, tmp_path / "attestation.json")
    payload = json.loads(attestation.read_text(encoding="utf-8"))
    payload["authorized_runtime_files"].append(
        {"path": "runtime.dll", "sha256": _sha(target), "classification": "vendor_runtime_library"}
    )
    attestation.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="link"):
        build_private_release(public, spine, attestation, tmp_path / "out")


def test_private_builder_creates_exact_local_archive_from_allowlist(tmp_path):
    public = _public_release(tmp_path)
    spine = _spine_source(tmp_path)
    attestation = _attestation(spine, tmp_path / "attestation.json")

    archive = build_private_release(public, spine, attestation, tmp_path / "out")

    assert archive.name == PRIVATE_ARCHIVE_NAME
    assert archive.parent == (tmp_path / "out").resolve()
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        assert "HaloCue/tools/spine/Spine.com" in names
        assert "HaloCue/SPINE-NOTICE.txt" in names
        assert all("attestation" not in name.casefold() for name in names)
        extracted = tmp_path / "private-extracted"
        package.extractall(extracted)
    assert scan_tree(extracted / "HaloCue", mode="private") == ()


def test_private_builder_stages_archive_on_the_output_volume(tmp_path, monkeypatch):
    public = _public_release(tmp_path)
    spine = _spine_source(tmp_path)
    attestation = _attestation(spine, tmp_path / "attestation.json")
    output = tmp_path / "out"
    real_temporary_directory = private_builder.tempfile.TemporaryDirectory
    staging_parents = []

    def observed_temporary_directory(*args, **kwargs):
        staging_parents.append(kwargs.get("dir"))
        return real_temporary_directory(*args, **kwargs)

    monkeypatch.setattr(
        private_builder.tempfile,
        "TemporaryDirectory",
        observed_temporary_directory,
    )

    build_private_release(public, spine, attestation, output)

    assert staging_parents == [output.resolve()]
