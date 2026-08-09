"""Fail-closed content scanner for HaloCue release trees."""

from __future__ import annotations

from dataclasses import dataclass
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
from typing import Literal
import zipfile

from release_tools.public_db import _EMPTY_TABLES, _TABLE_COLUMNS


ScanMode = Literal["source", "public", "private"]


@dataclass(frozen=True)
class ScanFinding:
    code: str
    relative_path: str
    detail: str


@dataclass
class _ArchiveBudget:
    member_limit: int
    byte_limit: int
    members: int = 0
    declared_bytes: int = 0
    streamed_bytes: int = 0
    exhausted: bool = False

    def reserve(self, *, members: int, declared_bytes: int) -> bool:
        if (
            self.exhausted
            or self.members + members > self.member_limit
            or self.declared_bytes + declared_bytes > self.byte_limit
        ):
            self.exhausted = True
            return False
        self.members += members
        self.declared_bytes += declared_bytes
        return True

    def charge_streamed(self, size: int) -> bool:
        if self.exhausted or self.streamed_bytes + size > self.byte_limit:
            self.exhausted = True
            return False
        self.streamed_bytes += size
        return True


_FORBIDDEN_DIRECTORY_NAMES = {
    ".git",
    ".playwright-cli",
    ".superpowers",
    ".thumbs",
    "__pycache__",
    "chapters",
    "out",
    "output",
    "scripts",
}
_FORBIDDEN_FILE_NAMES = {
    ".env",
    "aa_assets.db",
    "aa_config.json",
    "aa_resources.json",
    "llm.json",
    "llm_profiles.json",
    "secrets.json",
}
_FORBIDDEN_EXTENSIONS = {
    ".aap",
    ".aas",
    ".atlas",
    ".bundle",
    ".gif",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".ogg",
    ".skel",
    ".spine",
    ".unity3d",
    ".wav",
    ".webp",
}
_EXECUTABLE_EXTENSIONS = {".com", ".dll", ".dylib", ".exe", ".pyd", ".so"}
_ARCHIVE_EXTENSIONS = {".whl", ".zip"}
_FORBIDDEN_NONEMPTY_TABLES = set(_EMPTY_TABLES)
_SQLITE_MAGIC = b"SQLite format 3\x00"
_SQLITE_SIDECAR_SUFFIXES = ("-journal", "-shm", "-wal", ".db-journal", ".db-shm", ".db-wal")
_PUBLIC_META = {
    "asset_schema_version": "2",
    "assetdb_schema_version": "2",
    "schema_version": "1",
}
_MAX_ARCHIVE_MEMBERS = 2048
_MAX_ARCHIVE_MEMBER_BYTES = 32 * 1024 * 1024
_MAX_ARCHIVE_TOTAL_BYTES = 256 * 1024 * 1024
_MAX_ARCHIVE_COMPRESSION_RATIO = 100.0
_ARCHIVE_CHUNK_BYTES = 64 * 1024
_TEXT_EXTENSIONS = {
    "",
    ".cfg",
    ".cmd",
    ".css",
    ".gitignore",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".spec",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

_WINDOWS_USER_PATH = re.compile(
    r"(?i)(?:[a-z]:[\\/]+(?:users|用户)[\\/]+)([^\\/\s\"']+)[\\/]"
)
_WINDOWS_DESKTOP_PATH = re.compile(r"(?i)[a-z]:[\\/]+(?:桌面|desktop)[\\/]+")
_UNIX_USER_PATH = re.compile(r"(?i)/(?:users|home)/([^/\s\"']+)/")
_PLACEHOLDER_USERS = {"alice", "example", "private", "test", "user", "username"}
_SECRET_PATTERNS = (
    re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{24,}"),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
)
_ASSIGNED_CREDENTIAL = re.compile(
    r"(?i)\b(?:api[_-]?key|apikey|access[_-]?token|secret|password)\b"
    r"\s*[:=]\s*([\"'])([^\"'\r\n]{16,})\1"
)
_PLACEHOLDER_CREDENTIAL_PARTS = {
    "dummy",
    "example",
    "fake",
    "placeholder",
    "private",
    "replace",
    "sample",
    "secret",
    "test",
    "token",
    "your",
}
_CREDENTIAL_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "credentials",
    "password",
    "private_key",
    "secret",
    "token",
}
_PATH_COLUMN_PARTS = ("cache", "directory", "file", "install", "path", "root")


def _finding(code: str, relative_path: str, detail: str) -> ScanFinding:
    return ScanFinding(code=code, relative_path=relative_path, detail=detail)


def _has_personal_path(text: str) -> bool:
    if _WINDOWS_DESKTOP_PATH.search(text):
        return True
    for pattern in (_WINDOWS_USER_PATH, _UNIX_USER_PATH):
        for match in pattern.finditer(text):
            if match.group(1).casefold() not in _PLACEHOLDER_USERS:
                return True
    return False


def _has_credential(text: str) -> bool:
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        return True
    for match in _ASSIGNED_CREDENTIAL.finditer(text):
        value = match.group(2).strip()
        lexical_parts = set(re.findall(r"[a-z0-9]+", value.casefold()))
        if lexical_parts & _PLACEHOLDER_CREDENTIAL_PARTS:
            continue
        if re.fullmatch(r"[A-Za-z0-9._~+/=-]{16,}", value):
            return True
    return False


def _unsafe_scalar(value: object) -> bool:
    if not isinstance(value, str):
        return False
    return _has_personal_path(value) or _has_credential(value)


def _unsafe_json(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
            if normalized in _CREDENTIAL_KEYS and item not in (None, "", [], {}):
                return True
            if _unsafe_scalar(item) or _unsafe_json(item):
                return True
        return False
    if isinstance(value, list):
        return any(_unsafe_scalar(item) or _unsafe_json(item) for item in value)
    return _unsafe_scalar(value)


def _decode_text(data: bytes, suffix: str) -> str | None:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeError:
            return None
    sample = data[:512]
    if sample and sample[1::2].count(0) > max(2, len(sample) // 8):
        try:
            return data.decode("utf-16le")
        except UnicodeError:
            return None
    if suffix not in _TEXT_EXTENSIONS:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeError:
        return None


def _path_findings(relative: str, *, mode: ScanMode) -> list[ScanFinding]:
    findings: list[ScanFinding] = []
    path = PurePosixPath(relative)
    lowered_parts = tuple(part.casefold() for part in path.parts)
    name = path.name.casefold()
    suffix = path.suffix.casefold()
    private_spine = mode == "private" and relative.casefold().startswith("tools/spine/")
    if any(part in _FORBIDDEN_DIRECTORY_NAMES for part in lowered_parts[:-1]):
        findings.append(_finding("forbidden-name", relative, "forbidden directory name"))
    if name in _FORBIDDEN_FILE_NAMES or (
        name.startswith("cast-") and name.endswith(".json") and name != "cast.example.json"
    ) or name == "cast.json":
        findings.append(_finding("forbidden-name", relative, "forbidden local filename"))
    if name.endswith(_SQLITE_SIDECAR_SUFFIXES) or name.startswith("aa_assets.db-"):
        findings.append(_finding("forbidden-name", relative, "SQLite sidecar is forbidden"))
    if suffix == ".db" and relative != "data/halocue_labels.db":
        findings.append(_finding("forbidden-name", relative, "database is not the public seed"))
    if suffix in _FORBIDDEN_EXTENSIONS:
        findings.append(_finding("forbidden-extension", relative, "forbidden asset extension"))
    if suffix == ".png" and not relative.startswith("branding/") and not private_spine:
        findings.append(_finding("forbidden-extension", relative, "non-brand image is forbidden"))
    if name.endswith("-avatar.png") or name.startswith(("bg_", "event", "ui_fx_")):
        findings.append(_finding("forbidden-extension", relative, "game or personal image name"))

    spine_name = name == "spine.com" or ("spine" in name and suffix in {".dll", ".exe"})
    if spine_name and mode in {"source", "public"}:
        findings.append(_finding("spine-runtime", relative, "Spine runtime is not public"))
    if suffix in _EXECUTABLE_EXTENSIONS:
        allowed = False
        if mode == "public":
            allowed = relative == "HaloCue.exe" or (
                relative.startswith("_internal/") and suffix in {".dll", ".pyd"}
            )
        elif mode == "private":
            allowed = (
                relative == "HaloCue.exe"
                or (relative.startswith("_internal/") and suffix in {".dll", ".pyd"})
                or private_spine
            )
        if not allowed:
            findings.append(
                _finding("unexpected-executable", relative, "executable is outside the mode allowlist")
            )
    return findings


def _payload_findings(relative: str, data: bytes) -> list[ScanFinding]:
    suffix = PurePosixPath(relative).suffix.casefold()
    text = _decode_text(data, suffix)
    if text is None:
        return []
    findings: list[ScanFinding] = []
    if _has_personal_path(text):
        findings.append(_finding("personal-path", relative, "personal absolute path detected"))
    if _has_credential(text):
        findings.append(_finding("credential", relative, "credential-like value detected"))
    if suffix == ".json":
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, UnicodeError):
            findings.append(_finding("json-invalid", relative, "JSON could not be parsed"))
        else:
            if _unsafe_json(payload):
                findings.append(_finding("unsafe-json", relative, "unsafe nested JSON value"))
    return findings


def _archive_findings(
    relative: str,
    data: bytes,
    *,
    depth: int = 0,
    budget: _ArchiveBudget | None = None,
) -> list[ScanFinding]:
    if depth >= 3:
        return [_finding("archive-invalid", relative, "archive nesting limit exceeded")]
    if budget is None:
        budget = _ArchiveBudget(
            member_limit=_MAX_ARCHIVE_MEMBERS,
            byte_limit=_MAX_ARCHIVE_TOTAL_BYTES,
        )
    elif budget.exhausted:
        return [_finding("archive-limit", relative, "archive tree limit exceeded")]
    findings: list[ScanFinding] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        members = archive.infolist()
    except (OSError, zipfile.BadZipFile):
        return [_finding("archive-invalid", relative, "archive could not be parsed")]
    with archive:
        declared_total = sum(member.file_size for member in members if not member.is_dir())
        if not budget.reserve(members=len(members), declared_bytes=declared_total):
            return [_finding("archive-limit", relative, "archive tree limit exceeded")]
        for member in members:
            member_name = member.filename.replace("\\", "/")
            member_path = PurePosixPath(member_name)
            virtual = f"{relative}!/{member_name}"
            if (
                member_path.is_absolute()
                or ".." in member_path.parts
                or re.match(r"(?i)^[a-z]:", member_name)
            ):
                findings.append(
                    _finding("archive-path-traversal", virtual, "unsafe archive member path")
                )
                continue
            unix_mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(unix_mode):
                findings.append(_finding("unsafe-link", virtual, "archive symlink is forbidden"))
                continue
            if member.is_dir():
                continue
            if member.flag_bits & 0x1:
                findings.append(
                    _finding("archive-unsupported", virtual, "encrypted archive member")
                )
                continue
            if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                findings.append(
                    _finding("archive-unsupported", virtual, "unsupported compression method")
                )
                continue
            ratio = (
                float("inf")
                if member.file_size and not member.compress_size
                else member.file_size / max(1, member.compress_size)
            )
            if (
                member.file_size > _MAX_ARCHIVE_MEMBER_BYTES
                or ratio > _MAX_ARCHIVE_COMPRESSION_RATIO
            ):
                findings.append(
                    _finding("archive-limit", virtual, "archive member limit exceeded")
                )
                continue
            try:
                chunks: list[bytes] = []
                member_total = 0
                with archive.open(member, "r") as stream:
                    while True:
                        chunk = stream.read(_ARCHIVE_CHUNK_BYTES)
                        if not chunk:
                            break
                        member_total += len(chunk)
                        if (
                            member_total > _MAX_ARCHIVE_MEMBER_BYTES
                            or member_total > member.file_size
                            or not budget.charge_streamed(len(chunk))
                        ):
                            raise OverflowError
                        chunks.append(chunk)
                payload = b"".join(chunks)
            except OverflowError:
                findings.append(
                    _finding("archive-limit", virtual, "streamed archive limit exceeded")
                )
                continue
            except (OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError):
                findings.append(_finding("archive-invalid", virtual, "archive member could not be read"))
                continue
            nested_findings = _path_findings(member_name, mode="source")
            nested_findings.extend(_payload_findings(virtual, payload))
            if PurePosixPath(member_name).suffix.casefold() in _ARCHIVE_EXTENSIONS:
                nested_findings.extend(
                    _archive_findings(
                        virtual,
                        payload,
                        depth=depth + 1,
                        budget=budget,
                    )
                )
            for finding in nested_findings:
                findings.append(
                    _finding("archive-content", finding.relative_path, "unsafe archive content")
                )
            if budget.exhausted:
                break
    return findings


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sqlite_findings(path: Path, relative: str) -> list[ScanFinding]:
    findings: list[ScanFinding] = []
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        integrity = connection.execute("PRAGMA quick_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise sqlite3.DatabaseError("quick_check failed")
        table_names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            if not row[0].startswith("sqlite_")
        ]
        if relative == "data/halocue_labels.db":
            expected_tables = set(_TABLE_COLUMNS)
            if set(table_names) != expected_tables:
                findings.append(
                    _finding("sqlite-schema", relative, "public seed table policy mismatch")
                )
            for table, expected_columns in _TABLE_COLUMNS.items():
                if table not in table_names:
                    continue
                quoted_table = _quote_identifier(table)
                actual_columns = tuple(
                    row[1]
                    for row in connection.execute(f"PRAGMA table_info({quoted_table})")
                )
                if actual_columns != tuple(expected_columns):
                    findings.append(
                        _finding("sqlite-schema", relative, "public seed column policy mismatch")
                    )
            if "meta" in table_names:
                actual_meta = dict(connection.execute("SELECT key, value FROM meta"))
                if actual_meta != _PUBLIC_META:
                    findings.append(
                        _finding("sqlite-schema", relative, "public seed metadata policy mismatch")
                    )
            for table, column in (
                ("character", "spine"),
                ("character", "avatar"),
                ("character_variant", "spine"),
                ("face_visual_label", "head_path"),
            ):
                if table not in table_names:
                    continue
                quoted_table = _quote_identifier(table)
                quoted_column = _quote_identifier(column)
                private_count = connection.execute(
                    f"SELECT COUNT(*) FROM {quoted_table} "
                    f"WHERE {quoted_column} IS NOT NULL AND {quoted_column} != ''"
                ).fetchone()[0]
                if private_count:
                    findings.append(
                        _finding("sqlite-path", relative, "public seed storage field is not blank")
                    )
        for table in table_names:
            quoted_table = _quote_identifier(table)
            count = connection.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()[0]
            if table.casefold() in _FORBIDDEN_NONEMPTY_TABLES and count:
                findings.append(
                    _finding("sqlite-forbidden-table", relative, "forbidden table is non-empty")
                )
            columns = [
                row[1]
                for row in connection.execute(f"PRAGMA table_info({quoted_table})")
            ]
            path_indexes = {
                index
                for index, column in enumerate(columns)
                if any(part in column.casefold() for part in _PATH_COLUMN_PARTS)
            }
            for row in connection.execute(f"SELECT * FROM {quoted_table}"):
                for index, value in enumerate(row):
                    if value in (None, "", b""):
                        continue
                    if index in path_indexes:
                        findings.append(
                            _finding("sqlite-path", relative, "path-bearing SQLite value")
                        )
                        path_indexes.remove(index)
                    if isinstance(value, str):
                        if _unsafe_scalar(value):
                            findings.append(
                                _finding("sqlite-path", relative, "unsafe SQLite text value")
                            )
                        stripped = value.lstrip()
                        if stripped.startswith(("{", "[")):
                            try:
                                payload = json.loads(value)
                            except json.JSONDecodeError:
                                continue
                            if _unsafe_json(payload):
                                findings.append(
                                    _finding("unsafe-json", relative, "unsafe SQLite JSON value")
                                )
        connection.close()
    except (OSError, sqlite3.DatabaseError):
        findings.append(_finding("sqlite-invalid", relative, "SQLite database could not be audited"))
    return findings


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def scan_tree(root: Path, *, mode: ScanMode) -> tuple[ScanFinding, ...]:
    """Scan *root* without following links and return sorted, redacted findings."""

    if mode not in {"source", "public", "private"}:
        raise ValueError(f"unsupported scan mode: {mode}")
    root = Path(root).resolve()
    if not root.is_dir():
        return (_finding("root-invalid", ".", "scan root is not a directory"),)

    findings: list[ScanFinding] = []

    def visit(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.casefold())
        except OSError:
            relative = directory.relative_to(root).as_posix() or "."
            findings.append(_finding("unreadable", relative, "directory could not be read"))
            return
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            try:
                is_link = entry.is_symlink() or _is_reparse_point(path)
            except OSError:
                findings.append(_finding("unreadable", relative, "entry metadata could not be read"))
                continue
            if is_link:
                try:
                    target = path.resolve(strict=False)
                    target.relative_to(root)
                except (OSError, ValueError):
                    findings.append(_finding("unsafe-link", relative, "link escapes scan root"))
                else:
                    findings.append(_finding("unsafe-link", relative, "links are not release inputs"))
                continue
            if entry.is_dir(follow_symlinks=False):
                if entry.name.casefold() in _FORBIDDEN_DIRECTORY_NAMES:
                    findings.append(
                        _finding("forbidden-name", relative, "forbidden directory name")
                    )
                    continue
                visit(path)
                continue
            if not entry.is_file(follow_symlinks=False):
                findings.append(_finding("unreadable", relative, "entry is not a regular file"))
                continue
            findings.extend(_path_findings(relative, mode=mode))
            try:
                data = path.read_bytes()
            except OSError:
                findings.append(_finding("unreadable", relative, "file could not be read"))
                continue
            suffix = path.suffix.casefold()
            if data.startswith(_SQLITE_MAGIC):
                if relative != "data/halocue_labels.db":
                    findings.append(
                        _finding("sqlite-unapproved", relative, "SQLite file is not the public seed")
                    )
                findings.extend(_sqlite_findings(path, relative))
            elif suffix == ".db":
                findings.extend(_sqlite_findings(path, relative))
            elif suffix in _ARCHIVE_EXTENSIONS:
                findings.extend(_archive_findings(relative, data))
            else:
                findings.extend(_payload_findings(relative, data))

    visit(root)
    return tuple(
        sorted(
            set(findings),
            key=lambda finding: (finding.relative_path, finding.code, finding.detail),
        )
    )
