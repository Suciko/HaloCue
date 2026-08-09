"""Content-identity checks for approved HaloCue branding assets."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MANIFEST = Path(__file__).with_name("branding") / "excluded-reference-sha256.txt"
_EXCLUDED_DIRECTORIES = frozenset({
    ".git",
    ".pytest_cache",
    ".superpowers",
    "__pycache__",
    "build",
})


def is_sha256(value: str) -> bool:
    return _HASH.fullmatch(value) is not None


def _load_reference_hashes() -> frozenset[str]:
    values = _MANIFEST.read_text(encoding="ascii").splitlines()
    if not values or any(not is_sha256(value) for value in values):
        raise ValueError("branding exclusion manifest must contain SHA-256 values")
    if len(values) != len(set(values)):
        raise ValueError("branding exclusion manifest must not contain duplicates")
    return frozenset(values)


EXTERNAL_REFERENCE_SHA256 = _load_reference_hashes()


def sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def external_reference_matches(root: Path) -> list[Path]:
    """Return included files whose bytes match the external-reference manifest."""
    matches = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _EXCLUDED_DIRECTORIES.intersection(relative.parts):
            continue
        if sha256_file(path) in EXTERNAL_REFERENCE_SHA256:
            matches.append(path)
    return sorted(matches)
