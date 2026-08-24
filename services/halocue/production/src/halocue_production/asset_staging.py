from __future__ import annotations

import json
import mimetypes
import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .errors import ProductionError
from .models import new_id, utc_now


MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_FILES = 160
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".wav", ".zip"}


class AssetStaging:
    """Own browser uploads in 1.0 storage; the browser never submits a path."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _filename(value: str) -> str:
        name = PureWindowsPath(PurePosixPath(str(value)).name).name.strip()
        if not name or name in {".", ".."} or "\x00" in name:
            raise ProductionError("invalid_upload_name", "上传文件名无效")
        if Path(name).suffix.casefold() not in _ALLOWED_SUFFIXES:
            raise ProductionError(
                "unsupported_upload_type",
                "支持 PNG、JPG、WAV 或包含角色骨骼的 ZIP 文件",
            )
        return name

    @staticmethod
    def _safe_zip_member(name: str) -> Path:
        posix = PurePosixPath(name.replace("\\", "/"))
        windows = PureWindowsPath(name.replace("/", "\\"))
        if (
            not name
            or posix.is_absolute()
            or windows.is_absolute()
            or windows.drive
            or any(part in {"", ".", ".."} or ":" in part for part in posix.parts)
        ):
            raise ProductionError("unsafe_archive", "角色压缩包包含不安全的文件路径")
        return Path(*posix.parts)

    def upload(self, *, filename: str, content: bytes) -> dict[str, Any]:
        name = self._filename(filename)
        if not content:
            raise ProductionError("upload_empty", "上传文件不能为空")
        if len(content) > MAX_UPLOAD_BYTES:
            raise ProductionError("upload_too_large", "单个素材不能超过 64 MiB", status=413)
        token = new_id("upload")
        directory = self.root / token
        directory.mkdir(mode=0o700)
        stored = directory / name
        stored.write_bytes(content)
        payload = {
            "upload_token": token,
            "filename": name,
            "size": len(content),
            "created_at": utc_now(),
            "kind_hint": "character" if stored.suffix.casefold() == ".zip" else None,
        }
        self._write(directory, payload)
        return {"ok": True, **payload}

    def _write(self, directory: Path, payload: dict[str, Any]) -> None:
        temporary = directory / "upload.json.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, directory / "upload.json")

    def _record(self, token: str) -> tuple[Path, dict[str, Any]]:
        if not isinstance(token, str) or not token.startswith("upload-") or len(token) != 19:
            raise ProductionError("invalid_upload_token", "上传凭证无效", status=404)
        directory = (self.root / token).resolve()
        try:
            directory.relative_to(self.root.resolve())
        except ValueError as exc:
            raise ProductionError("invalid_upload_token", "上传凭证无效", status=404) from exc
        try:
            payload = json.loads((directory / "upload.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProductionError("upload_not_found", "上传素材不存在或已损坏", status=404) from exc
        if not isinstance(payload, dict) or payload.get("upload_token") != token:
            raise ProductionError("upload_not_found", "上传素材不存在或已损坏", status=404)
        return directory, payload

    def source_for(self, token: str, kind: str) -> Path:
        directory, payload = self._record(token)
        filename = str(payload.get("filename") or "")
        source = (directory / filename).resolve()
        if not source.is_file():
            raise ProductionError("upload_not_found", "上传素材不存在或已损坏", status=404)
        if kind in {"background", "cg", "sound"}:
            allowed = {
                "background": {".png", ".jpg", ".jpeg"},
                "cg": {".png", ".jpg", ".jpeg"},
                "sound": {".wav"},
            }[kind]
            if source.suffix.casefold() not in allowed:
                raise ProductionError("upload_kind_mismatch", "上传文件类型与素材类型不匹配")
            return source
        if kind != "character" or source.suffix.casefold() != ".zip":
            raise ProductionError("upload_kind_mismatch", "角色素材必须上传 ZIP 压缩包")
        content = directory / "character-bundle"
        if content.is_dir():
            return content
        try:
            with zipfile.ZipFile(source) as archive:
                entries = [item for item in archive.infolist() if not item.is_dir()]
                total = sum(item.file_size for item in entries)
                if len(entries) > MAX_ARCHIVE_FILES or total > MAX_ARCHIVE_BYTES:
                    raise ProductionError("archive_too_large", "角色压缩包解压后超出安全限制")
                for item in entries:
                    relative = self._safe_zip_member(item.filename)
                    target = content / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as source_file, target.open("wb") as target_file:
                        shutil.copyfileobj(source_file, target_file)
        except zipfile.BadZipFile as exc:
            raise ProductionError("invalid_character_archive", "角色压缩包无法读取") from exc
        return content

    def filename_for(self, token: str) -> str:
        _, payload = self._record(token)
        return str(payload.get("filename") or "")

    def save_recognition(self, token: str, recognition: dict[str, Any]) -> None:
        directory, payload = self._record(token)
        payload["recognition"] = recognition
        self._write(directory, payload)

    def recognition_for(self, token: str, digest: str) -> dict[str, Any] | None:
        _, payload = self._record(token)
        value = payload.get("recognition")
        if not isinstance(value, dict) or value.get("digest") != digest:
            return None
        return value

    def media_type(self, source: Path) -> str:
        return mimetypes.guess_type(source.name)[0] or "application/octet-stream"
