"""Secure, transport-agnostic update primitives for the Windows bundle.

The module intentionally contains no UI code.  It is used by the launcher and
the standalone updater process, and is easy to exercise against a local HTTP
fixture without touching the network or the user's installation.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from halocue_meta import (
    DEFAULT_UPDATE_MANIFEST_URL,
    PRODUCT_NAME,
    UPDATE_CHANNEL,
    VERSION,
)


UPDATE_SCHEMA = "halocue-update/1"
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?$")
_HEX = re.compile(r"^[0-9a-fA-F]{64}$")


class UpdateError(RuntimeError):
    """Raised when an update is malformed, unverifiable, or unsafe."""


@dataclass(frozen=True)
class UpdateManifest:
    product: str
    channel: str
    version: str
    min_supported_version: str
    platform: str
    archive_url: str
    archive_size: int
    archive_sha256: str
    signature_key_id: str
    signature: str
    release_notes_url: str = ""
    published_at: str = ""

    @property
    def is_newer(self) -> bool:
        return compare_versions(self.version, VERSION) > 0


def _version_parts(value: str) -> tuple[int, int, int, str | None]:
    match = _SEMVER.fullmatch(str(value).strip())
    if not match:
        raise UpdateError(f"invalid semantic version: {value!r}")
    major, minor, patch, prerelease = match.groups()
    return int(major), int(minor), int(patch), prerelease


def compare_versions(left: str, right: str) -> int:
    """Compare the supported SemVer subset without third-party dependencies."""
    a = _version_parts(left)
    b = _version_parts(right)
    if a[:3] != b[:3]:
        return (a[:3] > b[:3]) - (a[:3] < b[:3])
    if a[3] == b[3]:
        return 0
    if a[3] is None:
        return 1
    if b[3] is None:
        return -1
    return (a[3] > b[3]) - (a[3] < b[3])


def _canonical_payload(payload: Mapping[str, object]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _decode_key(value: str, *, label: str) -> bytes:
    raw = value.strip()
    for decoder in (base64.b64decode, bytes.fromhex):
        try:
            decoded = decoder(raw)
        except (ValueError, TypeError):
            continue
        if len(decoded) == 32:
            return decoded
    raise UpdateError(f"{label} is not a valid Ed25519 key")


def verify_manifest_signature(payload: Mapping[str, object], public_keys: Mapping[str, str]) -> None:
    signature = payload.get("signature")
    if not isinstance(signature, Mapping):
        raise UpdateError("update manifest signature is missing")
    if signature.get("algorithm") != "ed25519":
        raise UpdateError("unsupported update signature algorithm")
    key_id = signature.get("key_id")
    value = signature.get("value")
    if not isinstance(key_id, str) or not isinstance(value, str):
        raise UpdateError("update manifest signature is incomplete")
    key = public_keys.get(key_id)
    if not key:
        raise UpdateError(f"unknown update signing key: {key_id}")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError as exc:  # pragma: no cover - packaging failure path
        raise UpdateError("Ed25519 verification support is unavailable") from exc
    try:
        signature_bytes = base64.b64decode(value, validate=True)
        Ed25519PublicKey.from_public_bytes(_decode_key(key, label="public key")).verify(
            signature_bytes,
            _canonical_payload(payload),
        )
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise UpdateError("update manifest signature is invalid") from exc


def parse_manifest(
    payload: Mapping[str, object],
    *,
    current_version: str = VERSION,
    platform: str = "windows-x64",
    channel: str = UPDATE_CHANNEL,
    public_keys: Mapping[str, str],
) -> UpdateManifest:
    if payload.get("schema_version") != UPDATE_SCHEMA:
        raise UpdateError("unsupported update manifest schema")
    if payload.get("product") != PRODUCT_NAME:
        raise UpdateError("update manifest belongs to another product")
    if payload.get("channel") != channel or payload.get("platform") != platform:
        raise UpdateError("update manifest does not match this channel or platform")
    version = payload.get("version")
    minimum = payload.get("min_supported_version")
    _version_parts(str(version))
    _version_parts(str(minimum))
    if compare_versions(str(version), str(minimum)) < 0:
        raise UpdateError("manifest minimum version is newer than the release")
    archive = payload.get("archive")
    if not isinstance(archive, Mapping):
        raise UpdateError("update archive metadata is missing")
    url = archive.get("url")
    size = archive.get("size")
    digest = archive.get("sha256")
    if not isinstance(url, str) or not url.lower().startswith("https://"):
        raise UpdateError("update archive must use HTTPS")
    if not isinstance(size, int) or size <= 0 or size > MAX_ARCHIVE_BYTES:
        raise UpdateError("update archive size is outside the safety limit")
    if not isinstance(digest, str) or not _HEX.fullmatch(digest):
        raise UpdateError("update archive SHA-256 is invalid")
    verify_manifest_signature(payload, public_keys)
    return UpdateManifest(
        product=PRODUCT_NAME,
        channel=str(payload["channel"]),
        version=str(version),
        min_supported_version=str(minimum),
        platform=str(payload["platform"]),
        archive_url=url,
        archive_size=size,
        archive_sha256=digest.lower(),
        signature_key_id=str(payload["signature"]["key_id"]),
        signature=str(payload["signature"]["value"]),
        release_notes_url=str(payload.get("release_notes_url") or ""),
        published_at=str(payload.get("published_at") or ""),
    )


def fetch_manifest(
    url: str = DEFAULT_UPDATE_MANIFEST_URL,
    *,
    public_keys: Mapping[str, str],
    timeout: float = 3.0,
    opener: Callable[..., object] = urllib.request.urlopen,
    allow_insecure: bool = False,
) -> UpdateManifest:
    if not allow_insecure and not url.lower().startswith("https://"):
        raise UpdateError("update manifest must use HTTPS")
    try:
        with opener(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError, UnicodeDecodeError) as exc:
        raise UpdateError("unable to fetch update manifest") from exc
    if not isinstance(payload, Mapping):
        raise UpdateError("update manifest must be a JSON object")
    return parse_manifest(payload, public_keys=public_keys)


def download_archive(
    manifest: UpdateManifest,
    destination: Path,
    *,
    timeout: float = 30.0,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> Path:
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    digest = hashlib.sha256()
    total = 0
    try:
        with opener(manifest.archive_url, timeout=timeout) as response, temporary.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES or total > manifest.archive_size:
                    raise UpdateError("downloaded update exceeds its declared size")
                digest.update(chunk)
                handle.write(chunk)
        if total != manifest.archive_size or digest.hexdigest() != manifest.archive_sha256:
            raise UpdateError("downloaded update failed size or SHA-256 verification")
        os.replace(temporary, destination)
        return destination
    except UpdateError:
        temporary.unlink(missing_ok=True)
        raise
    except (OSError, urllib.error.URLError) as exc:
        temporary.unlink(missing_ok=True)
        raise UpdateError("unable to download update archive") from exc


def safe_extract_archive(archive: Path, destination: Path) -> Path:
    """Extract a release ZIP and reject traversal, links, and odd roots."""
    archive = Path(archive).resolve(strict=True)
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as source:
            members = source.infolist()
            if not members:
                raise UpdateError("update archive is empty")
            roots: set[str] = set()
            for member in members:
                name = member.filename.replace("\\", "/")
                path = Path(name)
                if not name or path.is_absolute() or ".." in path.parts:
                    raise UpdateError("update archive contains an unsafe path")
                if member.create_system == 3 and ((member.external_attr >> 16) & 0o170000) == 0o120000:
                    raise UpdateError("update archive contains a symbolic link")
                roots.add(path.parts[0])
            if len(roots) != 1:
                raise UpdateError("update archive must contain one top-level directory")
            root_name = next(iter(roots))
            for member in members:
                target = (destination / member.filename).resolve()
                if destination not in target.parents and target != destination:
                    raise UpdateError("update archive escapes its staging directory")
                source.extract(member, destination)
            extracted = destination / root_name
            if not extracted.is_dir():
                raise UpdateError("update archive top-level entry is not a directory")
            return extracted
    except zipfile.BadZipFile as exc:
        raise UpdateError("update archive is not a valid ZIP") from exc


def swap_installation(install_root: Path, staged_root: Path) -> Path:
    """Move a staged bundle into place and return the rollback directory."""
    install = Path(install_root).resolve(strict=True)
    staged = Path(staged_root).resolve(strict=True)
    if install == staged or not staged.is_dir():
        raise UpdateError("invalid update installation paths")
    if install.parent != staged.parent:
        raise UpdateError("staged update must be on the same volume")
    if len(install.parts) < 2:
        raise UpdateError("refusing to replace a filesystem root")
    rollback = install.with_name(f"{install.name}.previous-{int(time.time())}")
    try:
        os.replace(install, rollback)
        os.replace(staged, install)
    except OSError as exc:
        if rollback.exists() and not install.exists():
            os.replace(rollback, install)
        raise UpdateError("unable to replace the installed bundle") from exc
    return rollback


def stage_update(manifest: UpdateManifest, staging_root: Path) -> tuple[Path, Path]:
    staging = Path(staging_root).resolve()
    staging.mkdir(parents=True, exist_ok=True)
    archive = staging / f"HaloCue-{manifest.version}.zip"
    extracted_parent = Path(tempfile.mkdtemp(prefix="extract-", dir=staging))
    try:
        download_archive(manifest, archive)
        extracted = safe_extract_archive(archive, extracted_parent)
        return archive, extracted
    except Exception:
        shutil.rmtree(extracted_parent, ignore_errors=True)
        raise
