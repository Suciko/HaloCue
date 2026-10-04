"""Materialize the lossless, path-free research seed into a writable cache."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from contextlib import closing


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def materialize_bundled_metadata(resources: Path, cache: Path) -> Path:
    base = resources / "data/halocue_labels.db"
    receipt_path = resources / "data/reference-pack/research-seed.json"
    if not receipt_path.is_file():
        return base
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload = resources / "data/reference-pack/research/metadata.jsonl.gz"
    digest = receipt["payload_sha256"]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("invalid bundled research digest")
    directory = cache / digest
    target = directory / "halocue_labels.db"
    if target.is_file():
        return target
    if file_digest(base) != receipt["base_sha256"] or file_digest(payload) != digest:
        raise ValueError("bundled research integrity mismatch")
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="research-", suffix=".db", dir=directory)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copyfile(base, temporary)
        with closing(sqlite3.connect(temporary)) as connection:
            connection.execute("PRAGMA cache_size=-32768")
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            columns = {
                table: [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
                for table in tables
            }
            statements = {
                table: f'INSERT OR REPLACE INTO "{table}" VALUES({",".join("?" for _ in names)})'
                for table, names in columns.items()
            }
            pending_table = None
            pending_values = []
            with gzip.open(payload, "rt", encoding="utf-8") as stream:
                for line in stream:
                    record = json.loads(line)
                    table, values = record["table"], record["values"]
                    if table not in tables or len(values) != len(columns[table]):
                        raise ValueError("invalid bundled research row")
                    if pending_values and table != pending_table:
                        connection.executemany(statements[pending_table], pending_values)
                        pending_values = []
                    pending_table = table
                    pending_values.append(values)
                    if len(pending_values) == 512:
                        connection.executemany(statements[pending_table], pending_values)
                        pending_values = []
            if pending_values:
                connection.executemany(statements[pending_table], pending_values)
            for table, expected in receipt["counts"].items():
                if (
                    table not in tables
                    or connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                    != expected
                ):
                    raise ValueError("bundled research count mismatch")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("invalid bundled research database")
            connection.commit()
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def copy_research_metadata(seed: Path, destination: Path) -> None:
    """Publish a fresh user database with its completed research marker."""
    fd, name = tempfile.mkstemp(prefix="research-user-", suffix=".db", dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copyfile(seed, temporary)
        with closing(sqlite3.connect(temporary)) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('bundled_research_sha256',?)",
                (file_digest(seed),),
            )
            connection.commit()
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def merge_research_metadata(seed: Path, destination: Path) -> None:
    """Add missing research rows to an existing legacy user catalog atomically."""
    if seed.resolve() == destination.resolve():
        return
    digest = file_digest(seed)
    with closing(sqlite3.connect(seed)) as source, closing(sqlite3.connect(destination)) as target:
        marker = target.execute(
            "SELECT value FROM meta WHERE key='bundled_research_sha256'"
        ).fetchone()
        if marker and marker[0] == digest:
            return
        backup = destination.with_name(destination.name + ".before-research.db")
        if not backup.exists():
            with closing(sqlite3.connect(backup)) as saved:
                target.backup(saved)
        target.execute("BEGIN IMMEDIATE")
        for table in (
            "bg",
            "popup",
            "character",
            "character_variant",
            "face",
            "face_evidence",
            "face_visual_label",
            "expression_part",
            "scene_visual_label",
            "face_official_usage",
        ):
            schema = source.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not schema:
                continue
            existing = target.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not existing:
                target.execute(schema[0])
            if table == "face_visual_label":
                columns = {
                    row[1] for row in target.execute('PRAGMA table_info("face_visual_label")')
                }
                for column in ("observation_json", "backend_json"):
                    if column not in columns:
                        target.execute(
                            f"ALTER TABLE face_visual_label ADD COLUMN {column} TEXT NOT NULL DEFAULT '{{}}'"
                        )
            source_columns = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
            target_columns = {row[1] for row in target.execute(f'PRAGMA table_info("{table}")')}
            columns = [column for column in source_columns if column in target_columns]
            names = ",".join(f'"{column}"' for column in columns)
            parameters = ",".join("?" for _ in columns)
            target.executemany(
                f'INSERT OR IGNORE INTO "{table}" ({names}) VALUES({parameters})',
                source.execute(f'SELECT {names} FROM "{table}"'),
            )
        target.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('bundled_research_sha256',?)", (digest,)
        )
        target.commit()
