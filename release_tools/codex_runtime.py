"""Ship the pinned official Windows Codex runtime, without any account state."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request


VERSION = "0.153.4"
PACKAGE_URL = f"https://registry.npmjs.org/@openai/codex/-/codex-{VERSION}-win32-x64.tgz"
PACKAGE_INTEGRITY = (
    "sha512-lMkB43kJZH0VFr+hoXc11qqR7QtQIbkr07ALgj4urKL1osNyUyuy1iXd3Vzz2iCY"
    "vBUCSw7I0l/W1cEPGx9euQ=="
)
VENDOR = "vendor/x86_64-pc-windows-msvc"
PACKAGE_FILES = (
    f"{VENDOR}/bin/codex.exe",
    f"{VENDOR}/bin/codex-code-mode-host.exe",
    f"{VENDOR}/codex-resources/codex-command-runner.exe",
    f"{VENDOR}/codex-resources/codex-windows-sandbox-setup.exe",
    f"{VENDOR}/codex-path/rg.exe",
    f"{VENDOR}/codex-package.json",
    "package.json",
    "README.md",
)
DOCUMENT_HASHES = {
    "LICENSE": "d17f227e4df5da1600391338865ce0f3055211760a36688f816941d58232d8dc",
    "NOTICE": "9d71575ecfd9a843fc1677b0efb08053c6ba9fd686a0de1a6f5382fd3c220915",
}
_MAX_BYTES = 512 * 1024 * 1024


def _sha(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, path: Path) -> None:
    # Only the build downloads dependencies; application startup stays offline.
    temporary = path.with_suffix(path.suffix + ".partial")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
            size = 0
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                size += len(chunk)
                if size > _MAX_BYTES:
                    raise ValueError("Codex dependency exceeds the download limit")
                output.write(chunk)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _unpack_verified(archive: Path, target: Path) -> None:
    expected = base64.b64decode(PACKAGE_INTEGRITY.split("-", 1)[1]).hex()
    if _sha(archive, "sha512") != expected:
        raise ValueError("Official Codex package integrity mismatch")
    # No extractall, symlinks, arbitrary archive paths, or incidental user files.
    with tarfile.open(archive, "r:gz") as package:
        files = package.getmembers()
        if {member.name for member in files} != {f"package/{name}" for name in PACKAGE_FILES}:
            raise ValueError("Unexpected official Codex package contents")
        if len(files) != len(PACKAGE_FILES) or any(not member.isfile() for member in files):
            raise ValueError("Invalid official Codex package entries")
        if sum(member.size for member in files) > _MAX_BYTES:
            raise ValueError("Codex package exceeds the unpacked limit")
        for member in files:
            output = target / member.name.removeprefix("package/")
            output.parent.mkdir(parents=True, exist_ok=True)
            with package.extractfile(member) as source, output.open("wb") as destination:
                shutil.copyfileobj(source, destination)
    metadata = json.loads((target / "package.json").read_text(encoding="utf-8"))
    if metadata.get("name") != "@openai/codex" or metadata.get("version") != VERSION + "-win32-x64":
        raise ValueError("Unexpected official Codex package version")


def bundle_codex_runtime(bundle: Path, cache: Path) -> Path:
    """Build-time dependency; a missing/invalid runtime fails the release build."""
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"codex-{VERSION}-win32-x64.tgz"
    if not archive.is_file():
        _download(PACKAGE_URL, archive)
    target = bundle / "tools/codex"
    target.mkdir(parents=True, exist_ok=False)
    _unpack_verified(archive, target)
    for name, expected in DOCUMENT_HASHES.items():
        document = cache / name
        if not document.is_file():
            _download(
                f"https://raw.githubusercontent.com/openai/codex/rust-v{VERSION}/{name}", document
            )
        if _sha(document) != expected:
            raise ValueError(f"Official Codex {name} integrity mismatch")
        shutil.copy2(document, target / name)
    cli = target / VENDOR / "bin/codex.exe"
    result = subprocess.run(
        [str(cli), "--version"], capture_output=True, text=True, timeout=30, check=True
    )
    if result.stdout.strip() != f"codex-cli {VERSION}":
        raise ValueError("Bundled Codex version self-check failed")
    records = {name: _sha(target / name) for name in (*PACKAGE_FILES, *DOCUMENT_HASHES)}
    (target / "provenance.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "package_url": PACKAGE_URL,
                "integrity": PACKAGE_INTEGRITY,
                "files": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def audit_codex_runtime(bundle: Path) -> None:
    target = bundle / "tools/codex"
    expected = {*PACKAGE_FILES, *DOCUMENT_HASHES, "provenance.json"}
    actual = {path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()}
    if actual != expected or any(path.is_symlink() for path in target.rglob("*")):
        raise ValueError("Bundled Codex files are missing or unexpected")
    provenance = json.loads((target / "provenance.json").read_text(encoding="utf-8"))
    if (
        provenance.get("version") != VERSION
        or provenance.get("integrity") != PACKAGE_INTEGRITY
        or provenance.get("package_url") != PACKAGE_URL
    ):
        raise ValueError("Bundled Codex provenance mismatch")
    if provenance.get("files") != {
        name: _sha(target / name) for name in (*PACKAGE_FILES, *DOCUMENT_HASHES)
    }:
        raise ValueError("Bundled Codex file hash mismatch")
    for name, expected_hash in DOCUMENT_HASHES.items():
        if _sha(target / name) != expected_hash:
            raise ValueError(f"Bundled Codex {name} mismatch")
