"""A recoverable, fixed-file transaction for preparing a draft's teacher identity."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from teacher_identity import TeacherIdentityError


FILES = ("cast.json", "resources.json", "identity.json", "diagnostics.json", "session.json")
JOURNAL = ".teacher-identity-transaction.json"
SCHEMA = "teacher-identity-transaction/1.0"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _target(directory: Path, name: str) -> Path:
    target = directory / name
    if target.is_symlink() or target.resolve().parent != directory.resolve():
        raise TeacherIdentityError("teacher_identity_corrupt", "老师身份文件位置无效", status=409)
    return target


def _sync_directory(directory: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _replace(directory: Path, name: str, data: bytes) -> None:
    target = _target(directory, name)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".teacher-identity-", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        _sync_directory(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _read_journal(directory: Path) -> dict[str, bytes | None]:
    try:
        envelope = json.loads(_target(directory, JOURNAL).read_bytes())
        if not isinstance(envelope, dict) or set(envelope) != {"payload", "sha256"}:
            raise ValueError
        payload = envelope["payload"]
        if hashlib.sha256(_canonical(payload)).hexdigest() != envelope["sha256"]:
            raise ValueError
        if not isinstance(payload, dict) or set(payload) != {"schema_version", "before"}:
            raise ValueError
        before = payload["before"]
        if (
            payload["schema_version"] != SCHEMA
            or not isinstance(before, dict)
            or set(before) != set(FILES)
        ):
            raise ValueError
        restored = {}
        for name in FILES:
            _target(directory, name)
            entry = before[name]
            if entry is None:
                restored[name] = None
            else:
                if not isinstance(entry, dict) or set(entry) != {"base64", "sha256"}:
                    raise ValueError
                data = base64.b64decode(entry["base64"], validate=True)
                if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    raise ValueError
                restored[name] = data
        return restored
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise TeacherIdentityError(
            "teacher_identity_journal_corrupt", "老师身份恢复记录损坏，已停止写入", status=409
        ) from exc


def recover_teacher_transaction(directory: Path) -> None:
    """A surviving journal means no success response was committed; restore before-images."""
    if not _target(directory, JOURNAL).exists():
        return
    try:
        before = _read_journal(directory)
        for name in FILES:
            data = before[name]
            if data is None:
                _target(directory, name).unlink(missing_ok=True)
            else:
                _replace(directory, name, data)
        _target(directory, JOURNAL).unlink()
        _sync_directory(directory)
    except OSError as exc:
        raise TeacherIdentityError(
            "teacher_identity_recovery_failed", "老师身份恢复失败，请检查工作区后重试", status=500
        ) from exc


def commit_teacher_transaction(directory: Path, values: dict[str, Any]) -> None:
    """Commit all five JSON records, with session last and journal removal as commit point."""
    if set(values) != set(FILES):
        raise ValueError("Teacher transaction requires its fixed file set")
    recover_teacher_transaction(directory)
    committed = False
    try:
        encoded = {
            name: json.dumps(values[name], ensure_ascii=False, indent=2).encode("utf-8")
            for name in FILES
        }
        before = {}
        for name in FILES:
            target = _target(directory, name)
            data = target.read_bytes() if target.exists() else None
            before[name] = (
                None
                if data is None
                else {
                    "base64": base64.b64encode(data).decode("ascii"),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        payload = {"schema_version": SCHEMA, "before": before}
        _replace(
            directory,
            JOURNAL,
            _canonical(
                {
                    "payload": payload,
                    "sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
                }
            ),
        )
        for name in FILES:
            _replace(directory, name, encoded[name])
        _target(directory, JOURNAL).unlink()
        committed = True
        _sync_directory(directory)
    except OSError as exc:
        if committed:
            raise TeacherIdentityError(
                "teacher_identity_durability_uncertain",
                "老师身份已保存，但持久化确认失败，请重新读取草稿",
                status=500,
            ) from exc
        recover_teacher_transaction(directory)
        raise TeacherIdentityError(
            "teacher_identity_write_failed", "老师身份保存失败，原有内容已保留", status=500
        ) from exc
