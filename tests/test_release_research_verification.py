import gzip
import hashlib
import json
import shutil
import sqlite3

import pytest

from tools.verify_release import VerificationError, _assert_first_run_database


@pytest.fixture
def fresh_research(tmp_path):
    bundle = tmp_path / "HaloCue"
    resources = bundle / "_internal"
    pack = resources / "data/reference-pack"
    (pack / "research").mkdir(parents=True)
    base = resources / "data/halocue_labels.db"
    with sqlite3.connect(base) as connection:
        connection.executescript(
            "CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);"
            "CREATE TABLE bg(name TEXT PRIMARY KEY,label TEXT);"
            "INSERT INTO bg VALUES('BG_Classroom','教室');"
        )
    (bundle / "data").mkdir()
    shutil.copyfile(base, bundle / "data/halocue_labels.db")
    rows = [
        {"table": "bg", "values": ["BG_Classroom", "夜间研究标注"]},
        {"table": "bg", "values": ["BG_Station", "车站"]},
    ]
    payload = pack / "research/metadata.jsonl.gz"
    with gzip.open(payload, "wt", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    receipt = {
        "base_sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
        "payload_sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
        "counts": {"bg": 2, "meta": 0},
    }
    (pack / "research-seed.json").write_text(json.dumps(receipt), encoding="utf-8")
    state = tmp_path / "user"
    cache = state / ".halocue/reference-cache" / receipt["payload_sha256"] / "halocue_labels.db"
    cache.parent.mkdir(parents=True)
    shutil.copyfile(base, cache)
    with sqlite3.connect(cache) as connection:
        connection.execute("UPDATE bg SET label='夜间研究标注'")
        connection.execute("INSERT INTO bg VALUES('BG_Station','车站')")
    database = state / "aa_assets.db"
    shutil.copyfile(cache, database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO meta VALUES('bundled_research_sha256',?)",
            (hashlib.sha256(cache.read_bytes()).hexdigest(),),
        )
    return bundle, database


def test_fresh_release_checks_lossless_research_instead_of_base_bytes(fresh_research):
    bundle, database = fresh_research
    assert database.read_bytes() != (bundle / "data/halocue_labels.db").read_bytes()
    assert _assert_first_run_database(bundle, database) == {
        "kind": "lossless_research",
        "all_rows_verified": True,
        "counts": {"bg": 2, "meta": 0},
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE bg SET label='错误内容' WHERE name='BG_Classroom'",
        "DELETE FROM bg WHERE name='BG_Station'",
        "UPDATE meta SET value='incorrect-marker'",
        "INSERT INTO meta VALUES('unexpected','private')",
    ],
)
def test_release_rejects_changed_missing_or_unexpected_research(fresh_research, mutation):
    bundle, database = fresh_research
    with sqlite3.connect(database) as connection:
        connection.execute(mutation)
    with pytest.raises(VerificationError, match="first-run research rows differ"):
        _assert_first_run_database(bundle, database)


def test_legacy_release_still_requires_exact_seed_bytes(tmp_path):
    bundle = tmp_path / "HaloCue"
    (bundle / "data").mkdir(parents=True)
    seed = bundle / "data/halocue_labels.db"
    seed.write_bytes(b"legacy-seed")
    database = tmp_path / "user.db"
    database.write_bytes(seed.read_bytes())
    assert _assert_first_run_database(bundle, database)["byte_identical"]
    database.write_bytes(b"changed")
    with pytest.raises(VerificationError, match="differs from packaged seed"):
        _assert_first_run_database(bundle, database)
