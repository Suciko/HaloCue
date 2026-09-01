from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import update_manager
from update_manager import UpdateError, parse_manifest, safe_extract_archive, swap_installation


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _signed_payload(private: Ed25519PrivateKey, archive: bytes) -> dict:
    public = private.public_key().public_bytes_raw()
    payload = {
        "schema_version": "halocue-update/1",
        "product": "HaloCue",
        "channel": "stable",
        "version": "1.0.1",
        "min_supported_version": "1.0.0",
        "platform": "windows-x64",
        "archive": {
            "url": "https://updates.example.invalid/HaloCue-1.0.1.zip",
            "size": len(archive),
            "sha256": hashlib.sha256(archive).hexdigest(),
        },
        "release_notes_url": "https://example.invalid/notes",
        "signature": {"algorithm": "ed25519", "key_id": "test", "value": ""},
    }
    payload["signature"]["value"] = base64.b64encode(
        private.sign(update_manager._canonical_payload(payload))
    ).decode("ascii")
    return payload, base64.b64encode(public).decode("ascii")


def test_manifest_signature_and_version_are_verified():
    private = Ed25519PrivateKey.generate()
    payload, public = _signed_payload(private, b"zip")
    manifest = parse_manifest(payload, public_keys={"test": public})
    assert manifest.version == "1.0.1"
    assert manifest.is_newer is True


def test_manifest_rejects_unsigned_or_http_archive():
    private = Ed25519PrivateKey.generate()
    payload, public = _signed_payload(private, b"zip")
    payload["archive"]["url"] = "http://updates.example.invalid/a.zip"
    with pytest.raises(UpdateError, match="HTTPS"):
        parse_manifest(payload, public_keys={"test": public})


def test_download_archive_checks_size_and_hash(tmp_path: Path):
    archive = b"signed archive bytes"
    private = Ed25519PrivateKey.generate()
    payload, public = _signed_payload(private, archive)
    manifest = parse_manifest(payload, public_keys={"test": public})
    result = update_manager.download_archive(
        manifest,
        tmp_path / "updates" / "release.zip",
        opener=lambda *_args, **_kwargs: _Response(archive),
    )
    assert result.read_bytes() == archive


def test_safe_extract_rejects_zip_traversal(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as source:
        source.writestr("HaloCue/../../escape.txt", "no")
    with pytest.raises(UpdateError, match="unsafe path"):
        safe_extract_archive(archive, tmp_path / "extract")


def test_swap_installation_restores_on_invalid_staging(tmp_path: Path):
    install = tmp_path / "HaloCue"
    install.mkdir()
    (install / "old.txt").write_text("old", encoding="utf-8")
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "new.txt").write_text("new", encoding="utf-8")
    rollback = swap_installation(install, staged)
    assert (install / "new.txt").read_text(encoding="utf-8") == "new"
    assert (rollback / "old.txt").read_text(encoding="utf-8") == "old"
