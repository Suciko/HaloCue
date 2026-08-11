from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Iterable


_TOKEN = re.compile(r"^[a-f0-9]{32}$")
_MAX_INCOMING_BYTES = 10 * 1024 * 1024
_MAX_TREE_FILES = 1024
_MAX_TREE_FILE_BYTES = 64 * 1024 * 1024
_MAX_TREE_BYTES = 512 * 1024 * 1024


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


def claim_incoming(
    token: str,
    allowed_suffixes: Iterable[str],
    *,
    max_bytes: int = _MAX_INCOMING_BYTES,
) -> Path:
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
    if expected_size != actual_size or actual_size > max_bytes:
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


def claim_incoming_tree(token: str) -> Path:
    safe_token = str(token or "")
    if not _TOKEN.fullmatch(safe_token):
        raise IncomingFileError("invalid_incoming_token", "Incoming token is invalid")

    root = _files_root()
    incoming = root / "incoming"
    payload = incoming / f"{safe_token}.tree"
    metadata_path = incoming / f"{safe_token}.tree.json"
    if (
        not payload.is_dir()
        or payload.is_symlink()
        or not metadata_path.is_file()
        or metadata_path.is_symlink()
    ):
        raise IncomingFileError("invalid_incoming_token", "Incoming token is missing or used")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncomingFileError("invalid_incoming_metadata", "Incoming metadata is invalid") from exc

    raw_name = str(metadata.get("name") or "").strip()
    name = raw_name.replace("\\", "/").rsplit("/", 1)[-1]
    if (
        not name
        or name in {".", ".."}
        or raw_name != name
        or len(name) > 180
        or "\x00" in name
    ):
        raise IncomingFileError("invalid_incoming_metadata", "Incoming name is invalid")
    try:
        expected_size = int(metadata.get("size"))
        expected_count = int(metadata.get("fileCount"))
    except (TypeError, ValueError) as exc:
        raise IncomingFileError("invalid_incoming_metadata", "Incoming tree totals are invalid") from exc
    if expected_size < 0 or expected_count < 0:
        raise IncomingFileError("invalid_incoming_metadata", "Incoming tree totals are invalid")

    actual_count = 0
    actual_size = 0
    pending = [payload]
    try:
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as children:
                for child in children:
                    if child.is_symlink():
                        raise IncomingFileError(
                            "incoming_tree_changed", "Incoming directory contains a link"
                        )
                    if child.is_dir(follow_symlinks=False):
                        pending.append(Path(child.path))
                        continue
                    if not child.is_file(follow_symlinks=False):
                        raise IncomingFileError(
                            "incoming_tree_changed", "Incoming directory contains an invalid entry"
                        )
                    file_size = child.stat(follow_symlinks=False).st_size
                    actual_count += 1
                    actual_size += file_size
                    if (
                        actual_count > _MAX_TREE_FILES
                        or file_size > _MAX_TREE_FILE_BYTES
                        or actual_size > _MAX_TREE_BYTES
                    ):
                        raise IncomingFileError(
                            "incoming_tree_changed", "Incoming directory exceeds safe limits"
                        )
    except OSError as exc:
        raise IncomingFileError("incoming_tree_changed", "Unable to inspect incoming directory") from exc
    if actual_count != expected_count or actual_size != expected_size:
        raise IncomingFileError("incoming_tree_changed", "Incoming directory changed after staging")

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
        raise IncomingFileError("incoming_claim_failed", "Unable to claim incoming directory") from exc
    return target
