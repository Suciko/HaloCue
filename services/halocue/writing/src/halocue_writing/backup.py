from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .errors import DomainError


BACKUP_FORMAT = "halocue-writing-backup/1.0"
MAX_COMPRESSED_BYTES = 96 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_FILE_COUNT = 20_000
USER_CONTENT_ROOTS = (
    "agent-runs",
    "artifacts",
    "attachments",
    "imports",
    "references",
    "releases",
)
REQUIRED_TABLES = {
    "works",
    "artifacts",
    "revisions",
    "conversation_threads",
    "conversation_messages",
    "script_releases",
}
CONTENT_REFERENCES = (
    ("revisions", "content_uri"),
    ("proposals", "candidate_uri"),
    ("script_releases", "manifest_uri"),
    ("script_releases", "content_uri"),
    ("conversation_attachments", "content_uri"),
    ("reference_files", "content_uri"),
    ("agent_runs", "input_snapshot_uri"),
)


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


class WritingBackupManager:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).resolve()

    def export(self) -> tuple[str, bytes, dict]:
        created_at = datetime.now(timezone.utc).isoformat()
        entries: dict[str, bytes] = {"data/writing.db": self._database_snapshot()}
        for root_name in USER_CONTENT_ROOTS:
            root = self.data_dir / root_name
            if not root.is_dir():
                continue
            for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
                relative = path.relative_to(self.data_dir).as_posix()
                entries[f"data/{relative}"] = path.read_bytes()

        db_summary = self._inspect_database(entries["data/writing.db"], set(entries))
        files = [
            {"path": path, "byte_size": len(content), "sha256": _digest(content)}
            for path, content in sorted(entries.items())
        ]
        manifest = {
            "format": BACKUP_FORMAT,
            "created_at": created_at,
            "work_count": db_summary["work_count"],
            "work_titles": db_summary["work_titles"],
            "file_count": len(files),
            "uncompressed_bytes": sum(item["byte_size"] for item in files),
            "includes": ["作品数据库", "正文与版本", "资料与附件", "Agent 运行记录", "定稿"],
            "excludes": ["API Key", "模型设置", "AA 制作工作区设置"],
            "files": files,
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            for path, content in entries.items():
                archive.writestr(path, content)
        payload = output.getvalue()
        if len(payload) > MAX_COMPRESSED_BYTES:
            raise DomainError("backup_too_large", "作品备份超过当前版本支持的 96 MB。", status=413)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        summary = self.inspect_bytes(payload)
        return f"halocue-writing-{stamp}.halocue", payload, summary

    def inspect_payload(self, payload: dict) -> tuple[bytes, dict]:
        encoded = str(payload.get("content_base64") or "")
        if not encoded:
            raise DomainError("backup_content_required", "请选择 HaloCue 写作备份文件。")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise DomainError("backup_invalid", "备份文件编码无效。") from exc
        return content, self.inspect_bytes(content)

    def inspect_bytes(self, content: bytes) -> dict:
        if not content or len(content) > MAX_COMPRESSED_BYTES:
            raise DomainError("backup_too_large", "备份文件为空或超过 96 MB。", status=413)
        try:
            archive = zipfile.ZipFile(io.BytesIO(content), "r")
        except (zipfile.BadZipFile, OSError) as exc:
            raise DomainError("backup_invalid", "这不是有效的 HaloCue 写作备份。") from exc

        with archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILE_COUNT:
                raise DomainError("backup_invalid", "备份包含过多文件，已拒绝读取。")
            total_size = sum(item.file_size for item in infos)
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise DomainError("backup_too_large", "备份解压后超过 256 MB。", status=413)
            names = {item.filename for item in infos if not item.is_dir()}
            for info in infos:
                self._validate_archive_path(info.filename)
            if "manifest.json" not in names or "data/writing.db" not in names:
                raise DomainError("backup_invalid", "备份缺少清单或作品数据库。")
            try:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
                raise DomainError("backup_invalid", "备份清单无法读取。") from exc
            if manifest.get("format") != BACKUP_FORMAT:
                raise DomainError("backup_version_unsupported", "备份版本与当前写作系统不兼容。", status=409)
            listed = manifest.get("files")
            if not isinstance(listed, list) or not listed:
                raise DomainError("backup_invalid", "备份清单没有文件索引。")
            listed_names: set[str] = set()
            for item in listed:
                if not isinstance(item, dict):
                    raise DomainError("backup_invalid", "备份文件索引格式无效。")
                path = str(item.get("path") or "")
                self._validate_archive_path(path)
                if path in listed_names or path not in names:
                    raise DomainError("backup_invalid", "备份文件索引不完整或包含重复项。")
                data = archive.read(path)
                if int(item.get("byte_size", -1)) != len(data) or item.get("sha256") != _digest(data):
                    raise DomainError("backup_hash_mismatch", f"备份内容校验失败：{path}", status=409)
                listed_names.add(path)
            if listed_names != names - {"manifest.json"}:
                raise DomainError("backup_invalid", "备份清单与实际文件不一致。")
            db_summary = self._inspect_database(archive.read("data/writing.db"), names)
            if int(manifest.get("work_count", -1)) != db_summary["work_count"]:
                raise DomainError("backup_invalid", "备份清单中的作品数量与数据库不一致。")
            return {
                "format": BACKUP_FORMAT,
                "backup_hash": _digest(content),
                "created_at": str(manifest.get("created_at") or ""),
                "work_count": db_summary["work_count"],
                "work_titles": db_summary["work_titles"],
                "file_count": len(listed_names),
                "compressed_bytes": len(content),
                "uncompressed_bytes": total_size,
                "includes": manifest.get("includes") or [],
                "excludes": manifest.get("excludes") or [],
                "can_restore": True,
            }

    def restore(self, content: bytes, expected_hash: str) -> dict:
        summary = self.inspect_bytes(content)
        if not expected_hash or expected_hash != summary["backup_hash"]:
            raise DomainError("backup_changed", "备份内容与刚才预检的文件不一致，请重新选择。", status=409)

        stage = Path(tempfile.mkdtemp(prefix="halocue-restore-stage-", dir=self.data_dir.parent))
        rollback = Path(tempfile.mkdtemp(prefix="halocue-restore-rollback-", dir=self.data_dir.parent))
        moved_roots: list[str] = []
        database_replaced = False
        try:
            with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
                for info in archive.infolist():
                    if info.is_dir() or info.filename == "manifest.json":
                        continue
                    target = stage / PurePosixPath(info.filename)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(info.filename))

            safety_name, safety_content, _ = self.export()
            safety_dir = self.data_dir / "backups"
            safety_dir.mkdir(parents=True, exist_ok=True)
            safety_path = safety_dir / f"before-restore-{safety_name}"
            temporary_safety = safety_path.with_suffix(safety_path.suffix + ".tmp")
            temporary_safety.write_bytes(safety_content)
            os.replace(temporary_safety, safety_path)

            incoming_data = stage / "data"
            for root_name in USER_CONTENT_ROOTS:
                current = self.data_dir / root_name
                previous = rollback / root_name
                incoming = incoming_data / root_name
                incoming.mkdir(parents=True, exist_ok=True)
                if current.exists():
                    os.replace(current, previous)
                    moved_roots.append(root_name)
                os.replace(incoming, current)

            current_db = self.data_dir / "writing.db"
            previous_db = rollback / "writing.db"
            previous_db.write_bytes(self._database_snapshot())
            self._restore_database(incoming_data / "writing.db", current_db)
            database_replaced = True
            return {**summary, "restored": True, "safety_backup": safety_path.name}
        except Exception:
            for root_name in USER_CONTENT_ROOTS:
                current = self.data_dir / root_name
                previous = rollback / root_name
                if current.exists():
                    shutil.rmtree(current, ignore_errors=True)
                if previous.exists():
                    os.replace(previous, current)
            current_db = self.data_dir / "writing.db"
            previous_db = rollback / "writing.db"
            if database_replaced and previous_db.exists():
                self._restore_database(previous_db, current_db)
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)
            shutil.rmtree(rollback, ignore_errors=True)

    def _database_snapshot(self) -> bytes:
        descriptor, temporary_name = tempfile.mkstemp(prefix="halocue-writing-", suffix=".db")
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            source = sqlite3.connect(self.data_dir / "writing.db")
            destination = sqlite3.connect(temporary)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            return temporary.read_bytes()
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _restore_database(source_path: Path, destination_path: Path) -> None:
        source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
        destination = sqlite3.connect(destination_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()

    def _inspect_database(self, content: bytes, archive_names: set[str]) -> dict:
        descriptor, temporary_name = tempfile.mkstemp(prefix="halocue-backup-check-", suffix=".db")
        os.close(descriptor)
        temporary = Path(temporary_name)
        temporary.write_bytes(content)
        try:
            connection = sqlite3.connect(f"file:{temporary.as_posix()}?mode=ro", uri=True)
            try:
                integrity = connection.execute("PRAGMA quick_check").fetchone()
                if not integrity or integrity[0] != "ok":
                    raise DomainError("backup_database_invalid", "备份中的作品数据库未通过完整性检查。", status=409)
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not REQUIRED_TABLES.issubset(tables):
                    raise DomainError("backup_database_invalid", "备份中的作品数据库结构不完整。", status=409)
                work_count = int(connection.execute("SELECT COUNT(*) FROM works").fetchone()[0])
                titles = [row[0] for row in connection.execute("SELECT title FROM works ORDER BY updated_at DESC LIMIT 5")]
                for table, column in CONTENT_REFERENCES:
                    if table not in tables:
                        continue
                    for (uri,) in connection.execute(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL AND {column}!=''"):
                        path = "data/" + str(uri).replace("\\", "/").lstrip("/")
                        self._validate_archive_path(path)
                        if path not in archive_names:
                            raise DomainError("backup_reference_missing", f"备份缺少数据库引用的内容：{uri}", status=409)
                return {"work_count": work_count, "work_titles": titles}
            finally:
                connection.close()
        except sqlite3.DatabaseError as exc:
            raise DomainError("backup_database_invalid", "备份中的作品数据库无法读取。", status=409) from exc
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _validate_archive_path(value: str) -> None:
        if not value or "\\" in value:
            raise DomainError("backup_invalid", "备份包含无效文件路径。")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise DomainError("backup_invalid", "备份包含越界文件路径。")
        if value != "manifest.json" and not value.startswith("data/"):
            raise DomainError("backup_invalid", "备份包含未知顶层内容。")
        if value.startswith("data/"):
            relative = path.parts[1:]
            if relative == ("writing.db",):
                return
            if not relative or relative[0] not in USER_CONTENT_ROOTS:
                raise DomainError("backup_invalid", "备份试图覆盖非作品设置文件。")
