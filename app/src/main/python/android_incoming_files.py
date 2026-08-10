from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Iterable


_TOKEN = re.compile(r"^[a-f0-9]{32}$")
_MAX_INCOMING_BYTES = 10 * 1024 * 1024


class IncomingFileError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _files_root() -> Path:
    value = os.environ.get("HALOCUE_ANDROID_FILES_DIR", "").strip()
    if not value:
        raise IncomingFileError(
            "android_files_unavailable", "Android private files directory is not configured"
        )
    return Path(value).resolve()


def claim_incoming(token: str, allowed_suffixes: Iterable[str]) -> Path:
    safe_token = str(token or "")
    if not _TOKEN.fullmatch(safe_token):
        raise IncomingFileError("invalid_incoming_token", "Incoming token is invalid")

    root = _files_root()
    incoming = root / "incoming"
    payload = incoming / f"{safe_token}.bin"
    metadata_path = incoming / f"{safe_token}.json"
    if (
        not payload.is_file()
        or payload.is_symlink()
        or not metadata_path.is_file()
        or metadata_path.is_symlink()
    ):
        raise IncomingFileError("invalid_incoming_token", "Incoming token is missing or used")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncomingFileError("invalid_incoming_metadata", "Incoming metadata is invalid") from exc

    name = str(metadata.get("name") or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."}:
        raise IncomingFileError("invalid_incoming_metadata", "Incoming name is invalid")
    suffixes = {
        value if value.startswith(".") else "." + value
        for value in (str(item).strip().casefold() for item in allowed_suffixes)
        if value
    }
    if Path(name).suffix.casefold() not in suffixes:
        raise IncomingFileError("unsupported_incoming_type", "Incoming type is not allowed")
    try:
        expected_size = int(metadata.get("size"))
        actual_size = payload.stat().st_size
    except (OSError, TypeError, ValueError) as exc:
        raise IncomingFileError("invalid_incoming_metadata", "Incoming size is invalid") from exc
    if expected_size != actual_size or actual_size > _MAX_INCOMING_BYTES:
        raise IncomingFileError("incoming_file_changed", "Incoming file changed after staging")

    target_dir = root / "workspace" / "imports" / safe_token
    target = target_dir / name
    try:
        target_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise IncomingFileError(
            "invalid_incoming_token", "Incoming token is already used"
        ) from exc
    try:
        os.replace(payload, target)
        metadata_path.unlink()
    except OSError as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise IncomingFileError("incoming_claim_failed", "Unable to claim incoming file") from exc
    return target
