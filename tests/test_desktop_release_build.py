import json
import sqlite3
import subprocess

from build_desktop_release import copy_private_spine_runtime, prepare_release_seed


def test_release_seed_is_path_free_and_removes_personal_state(tmp_path):
    source_db = tmp_path / "source.db"
    con = sqlite3.connect(source_db)
    con.executescript(
        """
        CREATE TABLE asset_install(kind TEXT, source_path TEXT, metadata_json TEXT);
        CREATE TABLE name_alias(script_name TEXT, ident TEXT, kind TEXT, uses INTEGER);
        CREATE TABLE face_visual_label(face_id TEXT, head_path TEXT, manual_json TEXT);
        CREATE TABLE bg(name TEXT, label TEXT);
        INSERT INTO asset_install VALUES('background', 'C:\\FixtureUser\\BG.png', '{"path":"C:\\\\FixtureUser\\\\BG.png"}');
        INSERT INTO name_alias VALUES('我的角色', '1', 'portrait', 3);
        INSERT INTO face_visual_label VALUES('01', 'C:\\FixtureUser\\head.png', '{"note":"保留", "cache":"C:\\\\FixtureUser\\\\cache.png"}');
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
    assert "FixtureUser" not in con.execute("SELECT manual_json FROM face_visual_label").fetchone()[0]
    assert con.execute("SELECT * FROM bg").fetchone() == ("BG_Black", "黑屏")
    con.close()
    assert json.loads((seed_dir / "aa_resources.json").read_text(encoding="utf-8"))["_source"] == ""


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
