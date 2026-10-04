import gzip
import json
import sqlite3

import pytest

from bundled_metadata import file_digest, materialize_bundled_metadata, merge_research_metadata


def research_fixture(tmp_path):
    resources = tmp_path / "resources"
    pack = resources / "data/reference-pack"
    (pack / "research").mkdir(parents=True)
    base = resources / "data/halocue_labels.db"
    with sqlite3.connect(base) as con:
        con.executescript(
            "CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE bg(name TEXT PRIMARY KEY,label TEXT);"
        )
        con.execute("INSERT INTO bg VALUES('BG_Classroom','教室')")
    payload = pack / "research/metadata.jsonl.gz"
    with gzip.open(payload, "wt", encoding="utf-8") as stream:
        stream.write(
            json.dumps({"table": "bg", "values": ["BG_Classroom", "夜间教室研究标注"]}) + "\n"
        )
        stream.write(json.dumps({"table": "bg", "values": ["BG_Station", "车站"]}) + "\n")
    receipt = {
        "payload_sha256": file_digest(payload),
        "base_sha256": file_digest(base),
        "counts": {"bg": 2, "meta": 0},
    }
    (pack / "research-seed.json").write_text(json.dumps(receipt), encoding="utf-8")
    return resources


def test_materialization_is_lossless_cached_and_does_not_change_program_files(tmp_path):
    resources = research_fixture(tmp_path)
    hashes = {p.name: file_digest(p) for p in resources.rglob("*") if p.is_file()}
    first = materialize_bundled_metadata(resources, tmp_path / "cache")
    assert first == materialize_bundled_metadata(resources, tmp_path / "cache")
    with sqlite3.connect(first) as con:
        assert (
            con.execute("SELECT label FROM bg WHERE name='BG_Classroom'").fetchone()[0]
            == "夜间教室研究标注"
        )
        assert con.execute("SELECT count(*) FROM bg").fetchone()[0] == 2
    assert hashes == {p.name: file_digest(p) for p in resources.rglob("*") if p.is_file()}


def test_invalid_payload_does_not_publish_cache(tmp_path):
    resources = research_fixture(tmp_path)
    payload = resources / "data/reference-pack/research/metadata.jsonl.gz"
    payload.write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        materialize_bundled_metadata(resources, tmp_path / "cache")
    assert not list((tmp_path / "cache").rglob("*.db"))


def test_legacy_upgrade_retains_existing_user_labels_and_adds_research_once(tmp_path):
    resources = research_fixture(tmp_path)
    seed = materialize_bundled_metadata(resources, tmp_path / "cache")
    destination = tmp_path / "user.db"
    with sqlite3.connect(destination) as con:
        con.executescript(
            "CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE bg(name TEXT PRIMARY KEY,label TEXT);"
        )
        con.execute("INSERT INTO bg VALUES('BG_Classroom','作者自定义名称')")
    merge_research_metadata(seed, destination)
    with sqlite3.connect(destination.with_name("user.db.before-research.db")) as saved:
        assert saved.execute("SELECT * FROM bg").fetchall() == [("BG_Classroom", "作者自定义名称")]
        assert saved.execute("SELECT * FROM meta").fetchall() == []
    merged = file_digest(destination)
    merge_research_metadata(seed, destination)
    assert merged == file_digest(destination)
    with sqlite3.connect(destination) as con:
        assert (
            con.execute("SELECT label FROM bg WHERE name='BG_Classroom'").fetchone()[0]
            == "作者自定义名称"
        )
        assert con.execute("SELECT label FROM bg WHERE name='BG_Station'").fetchone()[0] == "车站"
