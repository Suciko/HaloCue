from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import zipfile

import pytest

import release_tools.scanner as scanner
from release_tools.scanner import ScanFinding, scan_tree


ROOT = Path(__file__).resolve().parents[1]


def _codes(findings: tuple[ScanFinding, ...]) -> set[str]:
    return {finding.code for finding in findings}


def _zip_bytes(files: dict[str, bytes | str]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as output:
        for name, payload in files.items():
            output.writestr(name, payload)
    return stream.getvalue()


def test_scanner_rejects_forbidden_names_and_asset_extensions(tmp_path):
    for relative in (
        "llm.json",
        "nested/aa_assets.db",
        "nested/aa_resources.json",
        "assets/character.skel",
        "assets/character.atlas",
        "voices/line.ogg",
        "projects/story.aap",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    findings = scan_tree(tmp_path, mode="source")

    assert "forbidden-name" in _codes(findings)
    assert "forbidden-extension" in _codes(findings)


def test_scanner_finds_personal_paths_in_utf8_and_utf16le(tmp_path):
    windows = "D:" + "\\" + "Users" + "\\" + "SakuraLeak" + "\\" + "story.txt"
    unix = "/" + "home" + "/sakura-leak/story.txt"
    (tmp_path / "utf8.txt").write_text(windows, encoding="utf-8")
    (tmp_path / "utf16.txt").write_bytes((unix + "\n").encode("utf-16le"))

    findings = scan_tree(tmp_path, mode="source")

    assert [finding.code for finding in findings].count("personal-path") == 2


def test_scanner_detects_credentials_without_exposing_values(tmp_path):
    api_key = "sk-" + "A" * 32
    bearer = "Bearer " + "b" * 40
    private_header = "-----BEGIN " + "PRIVATE KEY-----"
    (tmp_path / "secrets.txt").write_text(
        "\n".join((api_key, bearer, private_header)), encoding="utf-8"
    )
    (tmp_path / "credentials.json").write_text(
        json.dumps({"nested": {"api_key": api_key}}), encoding="utf-8"
    )

    findings = scan_tree(tmp_path, mode="source")
    rendered = repr(findings)

    assert "credential" in _codes(findings)
    assert "unsafe-json" in _codes(findings)
    assert api_key not in rendered
    assert bearer not in rendered


def test_scanner_detects_generic_assignment_api_key_and_redacts_it(tmp_path):
    credential_value = "qwertyuiopasdfghjklzxcvbnm" + "123456"
    (tmp_path / "settings.py").write_text(
        "api_" + "key=" + repr(credential_value) + "\n", encoding="utf-8"
    )

    findings = scan_tree(tmp_path, mode="source")

    assert "credential" in _codes(findings)
    assert credential_value not in repr(findings)


def test_scanner_does_not_suppress_placeholder_words_inside_real_api_key(tmp_path):
    credential_value = "qwertysecretuiopasdfghjklzxcvbnm123456"
    (tmp_path / "settings.py").write_text(
        "api_key=" + repr(credential_value) + "\n", encoding="utf-8"
    )

    findings = scan_tree(tmp_path, mode="source")

    assert "credential" in _codes(findings)
    assert credential_value not in repr(findings)


def test_scanner_does_not_treat_domain_identifier_tokens_as_credentials(tmp_path):
    (tmp_path / "workflow.py").write_text(
        "token = 'legacy-resource-layout'\n", encoding="utf-8"
    )

    assert scan_tree(tmp_path, mode="source") == ()


def test_scanner_ignores_obvious_assignment_placeholders(tmp_path):
    (tmp_path / "example.py").write_text(
        "apiKey='replace-with-your-api-key'\n"
        "token='test-token-placeholder-value'\n",
        encoding="utf-8",
    )

    assert scan_tree(tmp_path, mode="source") == ()


def test_scanner_checks_sqlite_path_columns_and_forbidden_nonempty_tables(tmp_path):
    database = tmp_path / "data" / "halocue_labels.db"
    database.parent.mkdir()
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE labels (name TEXT, cache_path TEXT)")
    connection.execute(
        "INSERT INTO labels VALUES (?, ?)",
        ("safe", "C:" + "\\" + "Users" + "\\" + "SakuraLeak" + "\\" + "cache.png"),
    )
    connection.execute("CREATE TABLE asset_install (source_path TEXT)")
    connection.execute("INSERT INTO asset_install VALUES ('relative/private')")
    connection.commit()
    connection.close()

    findings = scan_tree(tmp_path, mode="source")

    assert {"sqlite-path", "sqlite-forbidden-table"} <= _codes(findings)


def test_scanner_recursively_checks_nested_json_values(tmp_path):
    personal = "/" + "Users" + "/sakura-leak/private.json"
    (tmp_path / "metadata.json").write_text(
        json.dumps({"safe": [{"deeper": {"source_path": personal}}]}),
        encoding="utf-8",
    )

    findings = scan_tree(tmp_path, mode="source")

    assert "unsafe-json" in _codes(findings)


def test_scanner_refuses_symlinks_that_escape_root(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / "escape.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available to this test user")

    findings = scan_tree(tmp_path, mode="source")

    assert "unsafe-link" in _codes(findings)


def test_scanner_rejects_unexpected_public_executables_and_all_public_spine(tmp_path):
    (tmp_path / "HaloCue.exe").write_bytes(b"expected launcher")
    (tmp_path / "helper.exe").write_bytes(b"unexpected")
    spine = tmp_path / "vendor" / "Spine.com"
    spine.parent.mkdir()
    spine.write_bytes(b"vendor")
    (spine.parent / "spine-runtime.dll").write_bytes(b"vendor")

    findings = scan_tree(tmp_path, mode="public")

    assert "unexpected-executable" in _codes(findings)
    assert [finding.code for finding in findings].count("spine-runtime") == 2
    assert not any(
        finding.relative_path == "HaloCue.exe"
        and finding.code == "unexpected-executable"
        for finding in findings
    )


def test_scanner_inspects_archives_without_extracting_unsafe_members(tmp_path):
    archive = tmp_path / "payload.zip"
    secret = "sk-" + "Z" * 32
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape.txt", "outside")
        output.writestr("nested/config.json", json.dumps({"token": secret}))

    findings = scan_tree(tmp_path, mode="source")

    assert {"archive-path-traversal", "archive-content"} <= _codes(findings)
    assert secret not in repr(findings)


def test_scanner_rejects_small_high_ratio_zip_bomb(tmp_path):
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr("large.txt", b"0" * (1024 * 1024))

    findings = scan_tree(tmp_path, mode="source")

    assert "archive-limit" in _codes(findings)


def test_scanner_accepts_normal_bounded_archive(tmp_path):
    archive = tmp_path / "normal.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr("docs/readme.txt", "bounded public content\n")

    assert scan_tree(tmp_path, mode="source") == ()


def test_scanner_shares_member_budget_across_nested_archive_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "_MAX_ARCHIVE_MEMBERS", 5)
    inner = _zip_bytes(
        {
            "one.txt": "one\n",
            "two.txt": "two\n",
            "three.txt": "three\n",
        }
    )
    (tmp_path / "nested.zip").write_bytes(
        _zip_bytes({"first.zip": inner, "second.zip": inner})
    )

    findings = scan_tree(tmp_path, mode="source")

    assert any(
        finding.code == "archive-content"
        and "second.zip" in finding.relative_path
        for finding in findings
    )


def test_scanner_shares_byte_budget_across_nested_archive_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "_MAX_ARCHIVE_TOTAL_BYTES", 800)
    inner = _zip_bytes({"payload.txt": b"x" * 500})
    assert len(inner) < 800
    (tmp_path / "nested.zip").write_bytes(_zip_bytes({"inner.zip": inner}))

    findings = scan_tree(tmp_path, mode="source")

    assert any(
        finding.code == "archive-content"
        and "inner.zip" in finding.relative_path
        for finding in findings
    )


def test_scanner_accepts_normal_bounded_nested_archive(tmp_path):
    inner = _zip_bytes({"docs/readme.txt": "bounded nested public content\n"})
    (tmp_path / "normal.zip").write_bytes(_zip_bytes({"nested.zip": inner}))

    assert scan_tree(tmp_path, mode="source") == ()


def test_scanner_fails_closed_on_malformed_sqlite_and_archive(tmp_path):
    database = tmp_path / "data" / "halocue_labels.db"
    database.parent.mkdir()
    database.write_bytes(b"not sqlite")
    (tmp_path / "broken.zip").write_bytes(b"not zip")

    findings = scan_tree(tmp_path, mode="source")

    assert {"sqlite-invalid", "archive-invalid"} <= _codes(findings)


def test_scanner_accepts_audited_public_seed_and_safe_nested_json(tmp_path):
    database = tmp_path / "data" / "halocue_labels.db"
    database.parent.mkdir()
    shutil.copyfile(ROOT / "data" / "halocue_labels.db", database)
    (tmp_path / "metadata.json").write_text(
        '{"labels":[{"name":"smile"}]}', encoding="utf-8"
    )

    assert scan_tree(tmp_path, mode="source") == ()


@pytest.mark.parametrize(
    ("table", "column"),
    (
        ("character", "spine"),
        ("character", "avatar"),
        ("character_variant", "spine"),
        ("face_visual_label", "head_path"),
    ),
)
def test_scanner_rejects_private_relative_values_in_public_seed_storage_fields(
    tmp_path, table, column
):
    database = tmp_path / "data" / "halocue_labels.db"
    database.parent.mkdir()
    shutil.copyfile(ROOT / "data" / "halocue_labels.db", database)
    connection = sqlite3.connect(database)
    connection.execute(
        f'UPDATE "{table}" SET "{column}" = ? '
        f'WHERE rowid = (SELECT rowid FROM "{table}" LIMIT 1)',
        ("private/relative/value",),
    )
    connection.commit()
    connection.close()

    findings = scan_tree(tmp_path, mode="source")

    assert "sqlite-path" in _codes(findings)


def test_scanner_rejects_unexpected_public_seed_table(tmp_path):
    database = tmp_path / "data" / "halocue_labels.db"
    database.parent.mkdir()
    shutil.copyfile(ROOT / "data" / "halocue_labels.db", database)
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE private_records (value TEXT)")
    connection.execute("INSERT INTO private_records VALUES ('private')")
    connection.commit()
    connection.close()

    assert "sqlite-schema" in _codes(scan_tree(tmp_path, mode="source"))


def test_scanner_detects_and_rejects_renamed_sqlite_database(tmp_path):
    shutil.copyfile(ROOT / "data" / "halocue_labels.db", tmp_path / "labels.bin")

    findings = scan_tree(tmp_path, mode="source")

    assert "sqlite-unapproved" in _codes(findings)


@pytest.mark.parametrize(
    "name",
    ("aa_assets.db-wal", "halocue_labels.db-journal", "labels.db-shm"),
)
def test_scanner_rejects_sqlite_sidecar_candidates_by_name(tmp_path, name):
    (tmp_path / name).write_bytes(b"sidecar")

    assert "forbidden-name" in _codes(scan_tree(tmp_path, mode="source"))
