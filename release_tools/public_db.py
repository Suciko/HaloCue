"""Build the deterministic, path-free public annotation database."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Mapping

import asset_catalog
import assetdb


@dataclass(frozen=True)
class PublicDatabaseReport:
    source_rows: Mapping[str, int]
    output_rows: Mapping[str, int]
    output_sha256: str


_TABLE_COLUMNS = {
    "bg": ("name", "hash", "label", "place", "time", "mood", "tags", "labeled_by"),
    "popup": ("name", "label", "descr", "chars", "tags", "labeled_by"),
    "sound": ("name", "label", "tags", "labeled_by"),
    "character": ("ident", "name", "club", "spine", "avatar", "source"),
    "face": ("ident", "face_id", "raw", "label", "label_cn", "source"),
    "character_variant": ("ident", "spine_signature", "outfit_key", "spine"),
    "face_evidence": (
        "ident", "spine_signature", "outfit_key", "face_id", "source", "raw",
        "label", "label_cn", "observed_count",
    ),
    "face_visual_label": (
        "ident", "spine_signature", "outfit_key", "face_id", "model",
        "primary_emotion", "secondary_json", "valence", "arousal", "eyes",
        "brows", "mouth", "blush", "tears", "confidence", "description_cn",
        "semantic_json", "head_path", "reviewed", "manual_json", "version",
        "updated_at",
    ),
    "expression_part": (
        "ident", "spine_signature", "outfit_key", "kind", "raw_name",
        "labels_json", "source",
    ),
    "enum": ("kind", "value", "verb", "label_cn"),
    "meta": ("key", "value"),
    "name_alias": ("script_name", "ident", "kind", "uses"),
    "asset_install": (
        "kind", "aa_key", "display_name", "source_path", "sha256", "scope",
        "install_path", "status", "error", "metadata_json", "registered_at",
    ),
    "asset_library_profile": (
        "kind", "aa_key", "sha256", "asset_role", "series_name",
    ),
}

_COPIED_TABLES = (
    "bg", "popup", "sound", "character", "face", "character_variant",
    "face_evidence", "face_visual_label", "expression_part", "enum", "meta",
)
_EMPTY_TABLES = ("asset_install", "asset_library_profile", "name_alias")
_META_KEYS = ("asset_schema_version", "assetdb_schema_version", "schema_version")
_JSON_DEFAULTS = {
    ("face_visual_label", "secondary_json"): [],
    ("face_visual_label", "semantic_json"): {},
    ("face_visual_label", "manual_json"): {},
    ("expression_part", "labels_json"): [],
}
_OPPORTUNISTIC_JSON = {("face", "raw"), ("face_evidence", "raw")}
_FORBIDDEN_KEY_CONCEPTS = {
    "cache", "credential", "directory", "file", "filename", "folder", "home",
    "install", "key", "password", "path", "project", "secret", "source",
    "token", "user", "username",
}
_KEY_METADATA_AFFIXES = {
    "data", "dir", "directory", "file", "id", "key", "location", "name",
    "path", "root", "table", "timestamp", "url",
}
_FORBIDDEN_KEY_FORMS = _FORBIDDEN_KEY_CONCEPTS | {
    concept + "s" for concept in _FORBIDDEN_KEY_CONCEPTS
}
_KEY_METADATA_AFFIX_FORMS = _KEY_METADATA_AFFIXES | {
    affix + "s" for affix in _KEY_METADATA_AFFIXES
}
_WINDOWS_PATH = re.compile(r"(?i)(?:^|[\s\"'=])(?:[a-z]:[\\/]|\\\\)")
_POSIX_PATH = re.compile(
    r"(?:^|[\s\"'=:(])(?:file:///|~[/\\]|/(?!/|\s)(?=\S))"
)
_DECODED_POSIX_PATH = re.compile(
    r'''[\"']/(?!/)(?:[A-Za-z0-9._~%+-]+/){2,}[A-Za-z0-9._~%+-]*'''
)
_SECRET_VALUE = re.compile(
    r"(?i)(?:\bbearer\s+\S+|\b(?:api[_-]?key|password|token)\s*[:=]\s*\S+|"
    r"\bsk-[a-z0-9_-]{8,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
_PRIVATE_FILENAME = re.compile(
    r"(?i)^[^/\\]+\.(?:atlas|db|gif|jpe?g|json|mp3|ogg|png|skel|wav|webp)$"
)
_DROP = object()


def _component_is_private_key(component: str) -> bool:
    reachable = {(0, False)}
    for start in range(len(component)):
        for has_concept in (False, True):
            if (start, has_concept) not in reachable:
                continue
            for affix in _KEY_METADATA_AFFIX_FORMS:
                if component.startswith(affix, start):
                    reachable.add((start + len(affix), has_concept))
            for concept in _FORBIDDEN_KEY_FORMS:
                if component.startswith(concept, start):
                    reachable.add((start + len(concept), True))
    return (len(component), True) in reachable


def _forbidden_json_key(key: object) -> bool:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key))
    components = [
        part.casefold() for part in re.split(r"[^A-Za-z0-9]+", text) if part
    ]
    return any(_component_is_private_key(part) for part in components)


def _sensitive_text(value: str) -> bool:
    text = str(value).strip()
    return bool(
        _WINDOWS_PATH.search(text)
        or _POSIX_PATH.search(text)
        or _SECRET_VALUE.search(text)
        or _PRIVATE_FILENAME.fullmatch(text)
    )


def _sanitize_json_value(value):
    if isinstance(value, dict):
        return {
            str(key): cleaned
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not _forbidden_json_key(key)
            and (cleaned := _sanitize_json_value(item)) is not _DROP
        }
    if isinstance(value, list):
        return [
            cleaned
            for item in value
            if (cleaned := _sanitize_json_value(item)) is not _DROP
        ]
    if isinstance(value, str) and _sensitive_text(value):
        return _DROP
    return value


def _canonical_json(value, *, default, preserve_non_json: bool = False) -> str:
    try:
        parsed = json.loads(value if value is not None else "")
    except (TypeError, ValueError):
        if preserve_non_json:
            return _sanitize_text(value)
        parsed = default
    cleaned = _sanitize_json_value(parsed)
    if cleaned is _DROP:
        cleaned = default
    return json.dumps(
        cleaned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sanitize_text(value):
    if value is None or not isinstance(value, str):
        return value
    return "" if _sensitive_text(value) else value


def _primary_key_columns(con: sqlite3.Connection, table: str) -> tuple[str, ...]:
    keyed = sorted(
        ((int(row[5]), str(row[1])) for row in con.execute(f'PRAGMA table_info("{table}")') if row[5]),
        key=lambda item: item[0],
    )
    return tuple(name for _, name in keyed)


def _table_count(con: sqlite3.Connection, table: str) -> int:
    return int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _source_rows(con: sqlite3.Connection) -> dict[str, int]:
    return {table: _table_count(con, table) for table in _TABLE_COLUMNS}


def _copy_table(source: sqlite3.Connection, output: sqlite3.Connection, table: str) -> None:
    columns = _TABLE_COLUMNS[table]
    if table == "meta":
        placeholders = ",".join("?" for _ in _META_KEYS)
        where = f" WHERE key IN ({placeholders})"
        parameters = _META_KEYS
        order = " ORDER BY key"
    else:
        where = ""
        parameters = ()
        primary_key = _primary_key_columns(output, table)
        order = " ORDER BY " + ",".join(f'"{name}"' for name in primary_key)
    column_sql = ",".join(f'"{name}"' for name in columns)
    rows = source.execute(
        f'SELECT {column_sql} FROM "{table}"{where}{order}', parameters
    )
    records = []
    for row in rows:
        values = []
        for column, value in zip(columns, row):
            if (table, column) in _JSON_DEFAULTS:
                value = _canonical_json(value, default=_JSON_DEFAULTS[(table, column)])
            elif (table, column) in _OPPORTUNISTIC_JSON:
                value = _canonical_json(value, default={}, preserve_non_json=True)
            else:
                value = _sanitize_text(value)
            if table == "character" and column in {"spine", "avatar"}:
                value = ""
            elif table == "character_variant" and column == "spine":
                value = ""
            elif table == "face_visual_label" and column == "head_path":
                value = None
            elif table == "face_visual_label" and column == "updated_at":
                value = ""
            values.append(value)
        records.append(tuple(values))
    if records:
        placeholders = ",".join("?" for _ in columns)
        output.executemany(
            f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})', records
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _scan_public_file(path: Path) -> None:
    decoded = path.read_bytes().decode("utf-8", errors="ignore")
    findings = []
    if _WINDOWS_PATH.search(decoded):
        findings.append("Windows absolute path")
    if _DECODED_POSIX_PATH.search(decoded):
        findings.append("absolute user/source path")
    if _SECRET_VALUE.search(decoded):
        findings.append("credential-like value")
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        con.execute("PRAGMA query_only=ON")
        for table, columns in _TABLE_COLUMNS.items():
            column_sql = ",".join(f'"{column}"' for column in columns)
            for row in con.execute(f'SELECT {column_sql} FROM "{table}"'):
                for value in row:
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", errors="ignore")
                    if isinstance(value, str) and (
                        _WINDOWS_PATH.search(value)
                        or _POSIX_PATH.search(value)
                        or _SECRET_VALUE.search(value)
                        or _PRIVATE_FILENAME.fullmatch(value.strip())
                    ):
                        findings.append("private stored value")
                        break
                if findings and findings[-1] == "private stored value":
                    break
    finally:
        con.close()
    if findings:
        raise ValueError(
            "public database scan rejected: " + ", ".join(dict.fromkeys(findings))
        )


def build_public_database(source: Path, destination: Path) -> PublicDatabaseReport:
    """Create a sanitized public database and atomically replace ``destination``."""
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if not source.is_file():
        raise FileNotFoundError("source database does not exist")
    if source == destination:
        raise ValueError("source and destination must be different files")
    destination.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    source_con = None
    output_con = None
    try:
        source_con = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
        source_con.execute("PRAGMA query_only=ON")
        source_counts = _source_rows(source_con)

        output_con = sqlite3.connect(temporary)
        output_con.execute("PRAGMA page_size=4096")
        output_con.execute("PRAGMA auto_vacuum=NONE")
        output_con.execute("PRAGMA foreign_keys=ON")
        output_con.executescript(assetdb.SCHEMA)
        output_con.executescript(asset_catalog.ASSET_SCHEMA)
        output_con.execute("BEGIN IMMEDIATE")
        for table in _COPIED_TABLES:
            _copy_table(source_con, output_con, table)
        output_con.commit()

        if output_con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("public database integrity check failed")
        if output_con.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("public database foreign key check failed")
        output_counts = {
            table: _table_count(output_con, table) for table in _TABLE_COLUMNS
        }
        for table in _EMPTY_TABLES:
            if output_counts[table]:
                raise ValueError(f"public database policy violation in {table}")
        output_con.execute("VACUUM")
        output_con.close()
        output_con = None
        source_con.close()
        source_con = None

        _scan_public_file(temporary)
        digest = _sha256(temporary)
        os.replace(temporary, destination)
        return PublicDatabaseReport(source_counts, output_counts, digest)
    finally:
        if output_con is not None:
            output_con.close()
        if source_con is not None:
            source_con.close()
        temporary.unlink(missing_ok=True)


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = build_public_database(args.source, args.output)
    print(json.dumps({
        "source_rows": report.source_rows,
        "output_rows": report.output_rows,
        "output_sha256": report.output_sha256,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
