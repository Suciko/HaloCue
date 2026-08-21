import json
import sqlite3
import subprocess

import pytest

from build_desktop_release import (
    VERSION,
    copy_private_spine_runtime,
    next_available_release_dir,
    prepare_release_seed,
    validate_required_native_runtime_files,
)


def test_release_seed_is_path_free_and_removes_personal_state(tmp_path):
    source_db = tmp_path / "source.db"
    con = sqlite3.connect(source_db)
    con.executescript(
        """
        CREATE TABLE asset_install(kind TEXT, source_path TEXT, metadata_json TEXT);
        CREATE TABLE name_alias(script_name TEXT, ident TEXT, kind TEXT, uses INTEGER);
        CREATE TABLE face_visual_label(face_id TEXT, head_path TEXT, manual_json TEXT);
        CREATE TABLE bg(name TEXT, label TEXT);
        INSERT INTO asset_install VALUES('background', 'E:\\private\\BG.png', '{"path":"E:\\\\private\\\\BG.png"}');
        INSERT INTO name_alias VALUES('我的角色', '1', 'portrait', 3);
        INSERT INTO face_visual_label VALUES('01', 'C:\\Users\\Me\\head.png', '{"note":"保留", "cache":"C:\\\\Users\\\\Me\\\\cache.png"}');
        INSERT INTO bg VALUES('BG_Black', '黑屏');
        """
    )
    con.commit()
    con.close()
    source_index = tmp_path / "aa_resources.json"
    source_index.write_text(
        json.dumps({"_source": r"E:\\AzureArchive\\data", "bg": {"BG_Black": 1}}),
        encoding="utf-8",
    )

    seed_dir = tmp_path / "seed"
    prepare_release_seed(source_db, source_index, seed_dir)

    con = sqlite3.connect(seed_dir / "aa_assets.db")
    assert con.execute("SELECT COUNT(*) FROM asset_install").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM name_alias").fetchone()[0] == 0
    assert con.execute("SELECT head_path FROM face_visual_label").fetchone()[0] == ""
    assert "C:\\Users" not in con.execute("SELECT manual_json FROM face_visual_label").fetchone()[0]
    assert con.execute("SELECT * FROM bg").fetchone() == ("BG_Black", "黑屏")
    con.close()
    assert json.loads((seed_dir / "aa_resources.json").read_text(encoding="utf-8"))["_source"] == ""
    assert json.loads((seed_dir / "aa_config.seed.json").read_text(encoding="utf-8"))["pipeline"] == "0.95"


def test_release_seed_includes_sanitized_read_only_overlay(tmp_path):
    source_db = tmp_path / "source.db"
    overlay_db = tmp_path / "overlay.db"
    for database in (source_db, overlay_db):
        con = sqlite3.connect(database)
        con.executescript(
            """
            CREATE TABLE asset_install(kind TEXT, source_path TEXT, metadata_json TEXT);
            CREATE TABLE bg(name TEXT, label TEXT);
            INSERT INTO asset_install VALUES('background', 'E:\\private\\BG.png', '{}');
            INSERT INTO bg VALUES('BG_Black', '黑屏');
            """
        )
        con.commit()
        con.close()
    source_index = tmp_path / "aa_resources.json"
    source_index.write_text("{}", encoding="utf-8")

    seed_dir = prepare_release_seed(
        source_db,
        source_index,
        tmp_path / "seed",
        overlay_databases=[overlay_db],
    )

    packaged = seed_dir / "databases" / "overlay-1-aa-assets.db"
    con = sqlite3.connect(packaged)
    assert con.execute("SELECT COUNT(*) FROM asset_install").fetchone()[0] == 0
    assert con.execute("SELECT * FROM bg").fetchone() == ("BG_Black", "黑屏")
    con.close()
    config = json.loads((seed_dir / "aa_config.seed.json").read_text(encoding="utf-8"))
    assert config["asset_databases"] == ["databases/overlay-1-aa-assets.db"]
    assert VERSION == "0.95"


def test_private_runtime_copy_keeps_only_required_spine_files(tmp_path, monkeypatch):
    source = tmp_path / "Spine3.8.75"
    (source / "launcher").mkdir(parents=True)
    (source / "Spine").mkdir()
    (source / "examples").mkdir()
    (source / "Spine.com").write_bytes(b"cli")
    (source / "Spine.exe").write_bytes(b"gui")
    (source / "launcher" / "launcher-full").write_bytes(b"launcher")
    (source / "Spine" / "version.txt").write_text("3.8.75", encoding="ascii")
    (source / "examples" / "personal.skel").write_bytes(b"private")
    (source / "spine.reg").write_text("registry", encoding="ascii")
    (source / "license.rtf").write_text("license", encoding="ascii")
    release = tmp_path / "release"
    release.mkdir()
    monkeypatch.setattr(
        "build_desktop_release.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "3.8.75", ""),
    )

    target = copy_private_spine_runtime(source, release)

    assert (target / "Spine.com").is_file()
    assert (target / "Spine.exe").is_file()
    assert (target / "launcher" / "launcher-full").is_file()
    assert (target / "Spine" / "version.txt").is_file()
    assert (target / "license.rtf").is_file()
    assert not (target / "examples").exists()
    assert not (target / "spine.reg").exists()
    assert (release / "SPINE-NOTICE.txt").is_file()


def test_desktop_release_requires_fmod_native_library(tmp_path):
    with pytest.raises(RuntimeError, match="fmod.dll"):
        validate_required_native_runtime_files(tmp_path)

    fmod = tmp_path / "_internal" / "fmod_toolkit" / "libfmod" / "Windows" / "x64" / "fmod.dll"
    fmod.parent.mkdir(parents=True)
    fmod.write_bytes(b"fmod")
    with pytest.raises(RuntimeError, match="microarchitectures.json"):
        validate_required_native_runtime_files(tmp_path)

    archspec = tmp_path / "_internal" / "archspec" / "json" / "cpu" / "microarchitectures.json"
    archspec.parent.mkdir(parents=True)
    archspec.write_text("{}", encoding="ascii")
    validate_required_native_runtime_files(tmp_path)


def test_desktop_release_uses_a_new_revision_instead_of_overwriting(tmp_path):
    first = next_available_release_dir(tmp_path)
    assert first.name == "HaloCue-0.95-windows-x64"
    first.mkdir()
    second = next_available_release_dir(tmp_path)
    assert second.name == "HaloCue-0.95-windows-x64-r1"
