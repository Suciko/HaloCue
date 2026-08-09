"""Build a local, authorization-gated HaloCue package with a Spine overlay."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

from halocue_meta import PRIVATE_ARCHIVE_NAME, PUBLIC_ARCHIVE_NAME
from release_tools.scanner import scan_tree


_BUILD_MANIFEST = "HaloCue-build-manifest.json"
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_ALLOWED_CLASSIFICATIONS = {
    "vendor_program",
    "vendor_runtime_library",
    "vendor_runtime_resource",
    "vendor_notice",
}
_IMAGE_SUFFIXES = {".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".webp"}
_FORBIDDEN_SUFFIXES = {
    ".aap",
    ".aas",
    ".atlas",
    ".assetbundle",
    ".bundle",
    ".flac",
    ".key",
    ".lic",
    ".license",
    ".log",
    ".m4a",
    ".mp3",
    ".ogg",
    ".skel",
    ".spine",
    ".unity3d",
    ".wav",
}
_FORBIDDEN_NAME_PARTS = {
    "activation",
    "credential",
    "crash",
    "password",
    "recent-file",
    "recent_files",
    "user-token",
}
_FORBIDDEN_DIRECTORY_PARTS = {
    ".cache",
    ".config",
    "crash",
    "home",
    "logs",
    "project",
    "projects",
    "userdata",
    "users",
}
_NOTICE = """Spine is separate proprietary software

The Spine files under tools/spine are not covered by HaloCue's MIT License.
They may be included only when the distributor has specific authorization from
Esoteric Software LLC and every recipient is legally entitled to use them.
No HaloCue package grants, transfers, or sublicenses a Spine Editor license.

Official license: https://esotericsoftware.com/spine-editor-license
Copyright Esoteric Software LLC. All rights reserved.
"""


@dataclass(frozen=True)
class SpineRedistributionAttestation:
    authorized_to_redistribute: bool
    authorization_basis: str
    spine_version: str
    authorized_runtime_files: tuple[dict[str, str], ...]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse(path: Path) -> bool:
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _normalized_relative(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("attestation file path is invalid")
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    normalized = path.as_posix()
    if (
        path.is_absolute()
        or normalized != value
        or ".." in path.parts
        or re.match(r"(?i)^[a-z]:", value)
    ):
        raise ValueError("attestation file path is invalid")
    return normalized


def _read_attestation(path: Path) -> SpineRedistributionAttestation:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("valid redistribution attestation is required") from exc
    if not isinstance(payload, dict):
        raise ValueError("valid redistribution attestation is required")
    authorized = payload.get("authorized_to_redistribute")
    basis = payload.get("authorization_basis")
    version = payload.get("spine_version")
    entries = payload.get("authorized_runtime_files")
    if (
        authorized is not True
        or not isinstance(basis, str)
        or not basis.strip()
        or not isinstance(version, str)
        or not version.strip()
        or not isinstance(entries, list)
        or not entries
    ):
        raise ValueError("complete positive redistribution attestation is required")
    normalized_entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("attestation runtime file entry is invalid")
        relative = _normalized_relative(entry.get("path"))
        sha256 = entry.get("sha256")
        classification = entry.get("classification")
        if (
            relative in seen
            or not isinstance(sha256, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", sha256) is None
            or classification not in _ALLOWED_CLASSIFICATIONS
        ):
            raise ValueError("attestation runtime file entry is invalid")
        seen.add(relative)
        normalized_entries.append({
            "path": relative,
            "sha256": sha256.casefold(),
            "classification": classification,
        })
    return SpineRedistributionAttestation(
        authorized_to_redistribute=True,
        authorization_basis=basis.strip(),
        spine_version=version.strip(),
        authorized_runtime_files=tuple(normalized_entries),
    )


def _safe_zip_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > 20_000 or sum(item.file_size for item in members) > 1024 * 1024 * 1024:
        raise ValueError("public archive exceeds safety limits")
    seen: set[str] = set()
    for member in members:
        name = member.filename.replace("\\", "/")
        path = PurePosixPath(name)
        unix_mode = (member.external_attr >> 16) & 0xFFFF
        if (
            not name.startswith("HaloCue/")
            or path.is_absolute()
            or ".." in path.parts
            or re.match(r"(?i)^[a-z]:", name)
            or name in seen
            or stat.S_ISLNK(unix_mode)
        ):
            raise ValueError("public archive contains an unsafe member")
        if member.flag_bits & 0x1 or member.compress_type not in {
            zipfile.ZIP_STORED,
            zipfile.ZIP_DEFLATED,
        }:
            raise ValueError("public archive contains an unsupported member")
        ratio = member.file_size / max(1, member.compress_size)
        if member.file_size and ratio > 200:
            raise ValueError("public archive exceeds safety limits")
        seen.add(name)
    return members


def _verify_public_archive(public_archive: Path, extract_root: Path) -> Path:
    public_archive = public_archive.resolve(strict=True)
    if public_archive.name != PUBLIC_ARCHIVE_NAME:
        raise ValueError("public archive has the wrong name")
    sidecar = public_archive.with_name(public_archive.name + ".sha256")
    manifest_path = public_archive.with_name(_BUILD_MANIFEST)
    try:
        sidecar_parts = sidecar.read_text(encoding="ascii").strip().split()
        expected_hash, expected_name = sidecar_parts[0].casefold(), sidecar_parts[-1]
    except (OSError, IndexError, UnicodeError) as exc:
        raise ValueError("public archive checksum is missing or invalid") from exc
    if expected_name != public_archive.name or expected_hash != _sha256_file(public_archive):
        raise ValueError("public archive checksum mismatch")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest["files"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("public archive manifest is missing or invalid") from exc
    if not isinstance(entries, list):
        raise ValueError("public archive manifest is missing or invalid")
    try:
        with zipfile.ZipFile(public_archive) as archive:
            members = _safe_zip_members(archive)
            for member in members:
                if member.is_dir():
                    continue
                relative = PurePosixPath(member.filename).relative_to("HaloCue")
                target = extract_root / Path(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError("public archive could not be verified") from exc
    actual = {
        path.relative_to(extract_root).as_posix(): path
        for path in extract_root.rglob("*")
        if path.is_file()
    }
    expected_paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("public archive manifest is invalid")
        relative = _normalized_relative(entry.get("path"))
        path = actual.get(relative)
        if path is None:
            raise ValueError("public archive manifest mismatch")
        data = path.read_bytes()
        if entry.get("size") != len(data) or entry.get("sha256") != _sha256_bytes(data):
            raise ValueError("public archive manifest mismatch")
        expected_paths.append(relative)
    if expected_paths != sorted(set(expected_paths)) or set(expected_paths) != set(actual):
        raise ValueError("public archive manifest mismatch")
    for required in ("HaloCue.exe", "LICENSE", "THIRD_PARTY_NOTICES.md", "data/halocue_labels.db"):
        if required not in actual:
            raise ValueError("public archive is missing required public files")
    findings = scan_tree(extract_root, mode="public")
    if findings:
        raise ValueError("public archive scan failed")
    return extract_root


def _source_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or _is_reparse(path):
            raise ValueError(f"unsafe link in Spine source: {relative}")
        lowered_parts = tuple(part.casefold() for part in PurePosixPath(relative).parts)
        if path.is_dir() and any(
            part in _FORBIDDEN_DIRECTORY_PARTS or "project" in part
            for part in lowered_parts
        ):
            raise ValueError(f"forbidden directory in Spine source: {relative}")
        if path.is_file():
            files[relative] = path
    return files


def _validate_spine_entry(relative: str, classification: str) -> None:
    path = PurePosixPath(relative)
    lowered_parts = tuple(part.casefold() for part in path.parts)
    name = path.name.casefold()
    suffix = path.suffix.casefold()
    if (
        suffix in _FORBIDDEN_SUFFIXES
        or any(part in _FORBIDDEN_DIRECTORY_PARTS for part in lowered_parts[:-1])
        or any(token in name for token in _FORBIDDEN_NAME_PARTS)
    ):
        raise ValueError(f"forbidden file in Spine source: {relative}")
    if suffix in _IMAGE_SUFFIXES and classification != "vendor_runtime_resource":
        raise ValueError(f"image lacks vendor runtime resource classification: {relative}")


def _copy_authorized_spine(
    source_root: Path,
    destination: Path,
    attestation: SpineRedistributionAttestation,
) -> None:
    actual = _source_files(source_root)
    entries = {item["path"]: item for item in attestation.authorized_runtime_files}
    missing_from_attestation = sorted(set(actual) - set(entries))
    missing_from_source = sorted(set(entries) - set(actual))
    if missing_from_attestation:
        raise ValueError("Spine source file is absent from attestation")
    if missing_from_source:
        raise ValueError("attestation names a missing Spine source file")
    if "Spine.com" not in entries or entries["Spine.com"]["classification"] != "vendor_program":
        raise ValueError("attestation must authorize Spine.com as vendor_program")
    for relative in sorted(entries):
        entry = entries[relative]
        _validate_spine_entry(relative, entry["classification"])
        source = actual[relative]
        if _sha256_file(source) != entry["sha256"]:
            raise ValueError(f"Spine source hash mismatch: {relative}")
        target = destination / Path(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _run_spine_version(spine_root: Path) -> None:
    executable = spine_root / "Spine.com"
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            cwd=spine_root,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("authorized Spine.com --version failed") from exc
    if result.returncode != 0 or not (result.stdout.strip() or result.stderr.strip()):
        raise ValueError("authorized Spine.com --version failed")


def _write_archive(bundle: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for path in sorted(bundle.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if not path.is_file():
                continue
            relative = "HaloCue/" + path.relative_to(bundle).as_posix()
            info = zipfile.ZipInfo(relative, date_time=_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            output.writestr(info, path.read_bytes())


def build_private_release(
    public_archive: Path,
    spine_source: Path,
    attestation_path: Path,
    output_root: Path,
) -> Path:
    """Build the exact local private archive; this function has no publish path."""

    spine_source = Path(spine_source).resolve(strict=True)
    if not spine_source.is_dir() or spine_source.is_symlink() or _is_reparse(spine_source):
        raise ValueError("Spine source must be a regular local directory")
    attestation = _read_attestation(Path(attestation_path).resolve(strict=True))
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    archive_path = output_root / PRIVATE_ARCHIVE_NAME
    with tempfile.TemporaryDirectory(
        prefix=".halocue-private-",
        dir=output_root,
    ) as temporary:
        bundle = Path(temporary) / "HaloCue"
        _verify_public_archive(Path(public_archive), bundle)
        spine_destination = bundle / "tools" / "spine"
        _copy_authorized_spine(spine_source, spine_destination, attestation)
        (bundle / "SPINE-NOTICE.txt").write_text(_NOTICE, encoding="utf-8", newline="\n")
        _run_spine_version(spine_destination)
        findings = scan_tree(bundle, mode="private")
        if findings:
            summary = ", ".join(f"{item.code}:{item.relative_path}" for item in findings[:8])
            raise ValueError(f"forbidden content in private package: {summary}")
        temporary_archive = Path(temporary) / PRIVATE_ARCHIVE_NAME
        _write_archive(bundle, temporary_archive)
        if archive_path.exists():
            archive_path.unlink()
        os.replace(temporary_archive, archive_path)
    return archive_path
