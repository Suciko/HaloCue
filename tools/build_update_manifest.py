"""Create a signed HaloCue update manifest for a release archive.

The signing key is supplied only through ``HALOCUE_UPDATE_SIGNING_KEY``.  It
may be a base64/hex encoded 32-byte Ed25519 seed or a PEM private key.  The
script never writes or prints the private key.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from halocue_meta import PRODUCT_NAME, UPDATE_CHANNEL, VERSION
from update_manager import UPDATE_SCHEMA, _canonical_payload


def _private_key(value: str):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    raw = value.strip()
    if raw.startswith("-----BEGIN"):
        return serialization.load_pem_private_key(raw.encode("utf-8"), password=None)
    for decoder in (base64.b64decode, bytes.fromhex):
        try:
            decoded = decoder(raw)
        except (ValueError, TypeError):
            continue
        if len(decoded) == 32:
            return Ed25519PrivateKey.from_private_bytes(decoded)
    raise ValueError("HALOCUE_UPDATE_SIGNING_KEY is not a valid Ed25519 private key")


def build_manifest(*, archive: Path, archive_url: str, release_notes_url: str,
                   version: str, channel: str, key_id: str, minimum: str) -> dict:
    private = _private_key(os.environ["HALOCUE_UPDATE_SIGNING_KEY"])
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    payload = {
        "schema_version": UPDATE_SCHEMA,
        "product": PRODUCT_NAME,
        "channel": channel,
        "version": version,
        "min_supported_version": minimum,
        "platform": "windows-x64",
        "archive": {"url": archive_url, "size": archive.stat().st_size, "sha256": digest},
        "release_notes_url": release_notes_url,
        "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "signature": {"algorithm": "ed25519", "key_id": key_id, "value": ""},
    }
    signature = private.sign(_canonical_payload(payload))
    payload["signature"]["value"] = base64.b64encode(signature).decode("ascii")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-notes-url", default="")
    parser.add_argument("--version", default=VERSION)
    parser.add_argument("--minimum", default="1.0.0")
    parser.add_argument("--channel", default=UPDATE_CHANNEL)
    parser.add_argument("--key-id", default="stable-2026")
    args = parser.parse_args()
    if not os.getenv("HALOCUE_UPDATE_SIGNING_KEY"):
        parser.error("HALOCUE_UPDATE_SIGNING_KEY is required")
    manifest = build_manifest(
        archive=args.archive,
        archive_url=args.archive_url,
        release_notes_url=args.release_notes_url,
        version=args.version,
        channel=args.channel,
        key_id=args.key_id,
        minimum=args.minimum,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
