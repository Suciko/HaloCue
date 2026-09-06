import base64
import hashlib
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.build_update_manifest import build_manifest
from update_manager import parse_manifest


def test_build_manifest_is_verifiable(tmp_path, monkeypatch):
    archive = tmp_path / "HaloCue-1.0.1-windows-x64.zip"
    archive.write_bytes(b"release archive")
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes_raw()
    public = private.public_key().public_bytes_raw()
    monkeypatch.setenv("HALOCUE_UPDATE_SIGNING_KEY", base64.b64encode(raw).decode())
    payload = build_manifest(
        archive=archive,
        archive_url="https://cdn.example/HaloCue-1.0.1-windows-x64.zip",
        release_notes_url="https://example/notes",
        version="1.0.1",
        channel="stable",
        key_id="test",
        minimum="1.0.0",
    )
    assert payload["archive"]["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = parse_manifest(
        payload,
        public_keys={"test": base64.b64encode(public).decode()},
    )
    assert manifest.version == "1.0.1"
