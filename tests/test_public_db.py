import hashlib
import json
import sqlite3

import pytest

import asset_catalog
import assetdb
from release_tools.public_db import build_public_database


PUBLIC_TABLES = {
    "asset_install",
    "asset_library_profile",
    "bg",
    "character",
    "character_variant",
    "enum",
    "expression_part",
    "face",
    "face_evidence",
    "face_visual_label",
    "meta",
    "name_alias",
    "popup",
    "sound",
}


def _synthetic_private_database(path):
    con = sqlite3.connect(path)
    con.executescript(assetdb.SCHEMA)
    con.executescript(asset_catalog.ASSET_SCHEMA)
    con.executescript(
        """
        ALTER TABLE bg ADD COLUMN private_path TEXT;
        CREATE TABLE private_note(value TEXT);

        INSERT INTO meta(key,value) VALUES
          ('schema_version','7'),
          ('asset_schema_version','2'),
          ('assetdb_schema_version','2'),
          ('source','C:\\Users\\Alice\\private-project\\aa_resources.json');

        INSERT INTO bg
          (name,hash,label,place,time,mood,tags,labeled_by,private_path)
        VALUES
          ('BG_TestRoom',42,'测试教室','室内','白天','平静','教室,日常','manual',
           'C:\\Users\\Alice\\private-project\\BG_TestRoom.png');
        INSERT INTO popup(name,label,descr,chars,tags,labeled_by)
        VALUES ('Event_Test','提示','公共说明','测试角色','提示','manual');
        INSERT INTO sound(name,label,tags,labeled_by)
        VALUES ('SE_TestBell','铃声','提示','manual');
        INSERT INTO enum(kind,value,verb,label_cn)
        VALUES ('action',3,'jump','跳跃');

        INSERT INTO character(ident,name,club,spine,avatar,source)
        VALUES ('1001','测试角色','测试部','C:\\Users\\Alice\\private\\hero.skel',
                'D:\\cache\\hero-avatar.png','observed');
        INSERT INTO character_variant(ident,spine_signature,outfit_key,spine)
        VALUES ('1001','skeleton-signature-abc','winter-uniform',
                'C:\\Users\\Alice\\private\\hero.skel');
        INSERT INTO face(ident,face_id,raw,label,label_cn,source)
        VALUES ('1001','03',
                '{"labels":["smile","C:\\\\Users\\\\Alice\\\\face.png"],"source_path":"D:\\\\private\\\\face.atlas","nested":{"cache":"C:\\\\cache","note":"public"}}',
                'smile','微笑','atlas');
        INSERT INTO face_evidence
          (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count)
        VALUES
          ('1001','skeleton-signature-abc','winter-uniform','03','spine_semantic',
           '{"emotion_family":"joy","project":{"name":"private","path":"C:\\\\Users\\\\Alice"},"credential":"Bearer sk-private-token"}',
           'smile','微笑',4);
        INSERT INTO expression_part
          (ident,spine_signature,outfit_key,kind,raw_name,labels_json,source)
        VALUES
          ('1001','skeleton-signature-abc','winter-uniform','mouth','mouth_smile',
           '["mouth_smile","C:\\\\Users\\\\Alice\\\\private-mouth.png"]','atlas_semantic');
        INSERT INTO face_visual_label
          (ident,spine_signature,outfit_key,face_id,model,primary_emotion,
           secondary_json,valence,arousal,eyes,brows,mouth,blush,tears,confidence,
           description_cn,semantic_json,head_path,reviewed,manual_json,version,updated_at)
        VALUES
          ('1001','skeleton-signature-abc','winter-uniform','03','vision-public',
           'joy','["gentle",{"note":"safe","install_path":"D:\\\\cache\\\\head.png"}]',
           'positive','medium','soft','raised','smile',1,0,0.95,'温和的微笑',
           '{"usage":"dialogue","nested":{"project_root":"C:\\\\Users\\\\Alice\\\\private-project","safe":"kept"}}',
           'C:\\Users\\Alice\\private-project\\head.png',1,
           '{"reviewer_note":"approved","cache_file":"private-head.png","token":"sk-private-token"}',
           3,'2026-08-08 12:34:56');

        INSERT INTO name_alias(script_name,ident,kind,uses)
        VALUES ('Alice的私有别名','1001','portrait',9);
        INSERT INTO asset_install
          (kind,aa_key,display_name,source_path,sha256,scope,install_path,status,
           error,metadata_json,registered_at)
        VALUES
          ('character','1001','私有角色','C:\\Users\\Alice\\source.skel','digest',
           'C:\\Users\\Alice\\private-project','D:\\installed\\hero.skel','registered',
           NULL,'{"project":"private-project"}','2026-08-08T12:34:56Z');
        INSERT INTO asset_library_profile(kind,aa_key,sha256,asset_role,series_name)
        VALUES ('character','1001','digest','series_shared','Alice private series');
        INSERT INTO private_note(value)
        VALUES ('C:\\Users\\Alice\\private-project\\do-not-publish.txt');
        """
    )
    con.commit()
    con.close()


def _logical_dump(path):
    con = sqlite3.connect(path)
    try:
        return "\n".join(con.iterdump())
    finally:
        con.close()


def test_build_public_database_keeps_annotations_and_removes_private_state(tmp_path):
    source = tmp_path / "private.db"
    first = tmp_path / "public-one.db"
    second = tmp_path / "public-two.db"
    _synthetic_private_database(source)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    first_report = build_public_database(source, first)
    second_report = build_public_database(source, second)

    assert source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    assert first_report.source_rows["asset_install"] == 1
    assert first_report.output_rows["asset_install"] == 0
    assert first_report.output_sha256 == hashlib.sha256(first.read_bytes()).hexdigest()
    assert first_report.output_sha256 == second_report.output_sha256
    assert first.read_bytes() == second.read_bytes()
    assert _logical_dump(first) == _logical_dump(second)

    con = sqlite3.connect(first)
    con.row_factory = sqlite3.Row
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    tables = {
        row[0]
        for row in con.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert tables == PUBLIC_TABLES
    assert "private_path" not in {
        row[1] for row in con.execute("PRAGMA table_info(bg)")
    }

    assert tuple(con.execute(
        "SELECT label,place,time,mood,tags,labeled_by FROM bg"
    ).fetchone()) == ("测试教室", "室内", "白天", "平静", "教室,日常", "manual")
    assert con.execute("SELECT label FROM popup").fetchone()[0] == "提示"
    assert con.execute("SELECT label FROM sound").fetchone()[0] == "铃声"
    assert tuple(con.execute("SELECT verb,label_cn FROM enum").fetchone()) == ("jump", "跳跃")
    assert tuple(con.execute(
        "SELECT ident,name,club,source,spine,avatar FROM character"
    ).fetchone()) == ("1001", "测试角色", "测试部", "observed", "", "")
    assert tuple(con.execute(
        "SELECT spine_signature,outfit_key,spine FROM character_variant"
    ).fetchone()) == ("skeleton-signature-abc", "winter-uniform", "")
    assert tuple(con.execute(
        "SELECT label,label_cn,source FROM face"
    ).fetchone()) == ("smile", "微笑", "atlas")
    assert tuple(con.execute(
        "SELECT spine_signature,outfit_key,label,label_cn,observed_count "
        "FROM face_evidence"
    ).fetchone()) == (
        "skeleton-signature-abc", "winter-uniform", "smile", "微笑", 4
    )
    assert tuple(con.execute(
        "SELECT kind,raw_name,source FROM expression_part"
    ).fetchone()) == ("mouth", "mouth_smile", "atlas_semantic")
    assert json.loads(con.execute("SELECT raw FROM face").fetchone()[0]) == {
        "labels": ["smile"], "nested": {"note": "public"}
    }
    assert json.loads(con.execute("SELECT raw FROM face_evidence").fetchone()[0]) == {
        "emotion_family": "joy"
    }
    assert json.loads(con.execute(
        "SELECT labels_json FROM expression_part"
    ).fetchone()[0]) == ["mouth_smile"]

    visual = con.execute(
        "SELECT * FROM face_visual_label"
    ).fetchone()
    assert visual["primary_emotion"] == "joy"
    assert visual["reviewed"] == 1
    assert visual["head_path"] is None
    assert visual["updated_at"] == ""
    assert json.loads(visual["secondary_json"]) == ["gentle", {"note": "safe"}]
    assert json.loads(visual["semantic_json"]) == {
        "nested": {"safe": "kept"}, "usage": "dialogue"
    }
    assert json.loads(visual["manual_json"]) == {"reviewer_note": "approved"}

    assert {
        row[0] for row in con.execute("SELECT key FROM meta ORDER BY key")
    } == {"schema_version", "asset_schema_version", "assetdb_schema_version"}
    for table in ("asset_install", "asset_library_profile", "name_alias"):
        assert con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    con.close()

    decoded = first.read_bytes().decode("utf-8", errors="ignore")
    for forbidden in (
        "Alice", "private-project", "private-head.png", "sk-private-token",
        "C:\\Users", "D:\\cache", "D:\\installed", "do-not-publish.txt",
    ):
        assert forbidden not in decoded


def test_scrubs_generic_absolute_posix_paths_but_keeps_semantic_slashes(tmp_path):
    source = tmp_path / "private.db"
    destination = tmp_path / "public.db"
    _synthetic_private_database(source)
    con = sqlite3.connect(source)
    con.execute(
        "UPDATE face_evidence SET raw=?",
        (json.dumps({
            "references": [
                "/opt/alice/private/head.png",
                "/srv/secret/cache.db",
                "/workspace/user/project.json",
            ],
            "semantic_slashes": ["indoor/outdoor", "input / output"],
        }),),
    )
    con.commit()
    con.close()

    build_public_database(source, destination)

    con = sqlite3.connect(destination)
    payload = json.loads(con.execute("SELECT raw FROM face_evidence").fetchone()[0])
    con.close()
    assert payload == {
        "references": [],
        "semantic_slashes": ["indoor/outdoor", "input / output"],
    }


def test_scrubs_compact_and_separated_private_json_keys_recursively(tmp_path):
    source = tmp_path / "private.db"
    destination = tmp_path / "public.db"
    _synthetic_private_database(source)
    con = sqlite3.connect(source)
    con.execute(
        "UPDATE face_evidence SET raw=?",
        (json.dumps({
            "nested": {
                "filepath": "relative-file",
                "sourcepath": "relative-source-compact",
                "sourcePath": "relative-source",
                "cachedir": "relative-cache-compact",
                "cache_dir": "relative-cache",
                "credentials": "relative-credential-compact",
                "credential.info": "relative-credential",
                "projectroot": "relative-project",
                "installpath": "relative-install-compact",
                "install-path": "relative-install",
                "resource": "public semantic resource",
                "safe_label": "smile",
            }
        }),),
    )
    con.commit()
    con.close()

    build_public_database(source, destination)

    con = sqlite3.connect(destination)
    payload = json.loads(con.execute("SELECT raw FROM face_evidence").fetchone()[0])
    con.close()
    assert payload == {
        "nested": {
            "resource": "public semantic resource",
            "safe_label": "smile",
        }
    }


def test_scrubs_bounded_concept_compounds_without_lexical_false_positives(tmp_path):
    source = tmp_path / "private.db"
    destination = tmp_path / "public.db"
    _synthetic_private_database(source)
    con = sqlite3.connect(source)
    con.execute(
        "UPDATE face_evidence SET raw=?",
        (json.dumps({
            "nested": {
                "sourceid": "private",
                "projectid": "private",
                "installid": "private",
                "cachekey": "private",
                "cachetimestamp": "private",
                "cachetable": "private",
                "credentialdata": "private",
                "datasource": "private",
                "resource": "safe",
                "profile": "safe",
                "monkey": "safe",
                "keyboard": "safe",
                "homework": "safe",
                "projectile": "safe",
                "cachet": "safe",
                "keyframe": "safe",
                "keypoint": "safe",
                "projection": "safe",
                "projector": "safe",
                "homeroom": "safe",
                "homepage": "safe",
            }
        }),),
    )
    con.commit()
    con.close()

    build_public_database(source, destination)

    con = sqlite3.connect(destination)
    payload = json.loads(con.execute("SELECT raw FROM face_evidence").fetchone()[0])
    con.close()
    assert payload == {
        "nested": {
            "resource": "safe",
            "profile": "safe",
            "monkey": "safe",
            "keyboard": "safe",
            "homework": "safe",
            "projectile": "safe",
            "cachet": "safe",
            "keyframe": "safe",
            "keypoint": "safe",
            "projection": "safe",
            "projector": "safe",
            "homeroom": "safe",
            "homepage": "safe",
        }
    }


def test_scrubs_bounded_key_sequences_without_lexical_false_positives(tmp_path):
    source = tmp_path / "private.db"
    destination = tmp_path / "public.db"
    _synthetic_private_database(source)
    con = sqlite3.connect(source)
    con.execute(
        "UPDATE face_evidence SET raw=?",
        (json.dumps({
            "nested": {
                "sources": "private",
                "projects": "private",
                "paths": "private",
                "caches": "private",
                "installs": "private",
                "sourceurl": "private",
                "projectname": "private",
                "installlocation": "private",
                "cachefileid": "private",
                "sourcepaths": "private",
                "sourceurls": "private",
                "projectnames": "private",
                "installlocations": "private",
                "cachefileids": "private",
                "sourcepathids": "private",
                "cachedirectory": "private",
                "urlsource": "private",
                "fileidcache": "private",
                "userpassword": "private",
                "passwordtoken": "private",
                "projectsource": "private",
                "sourceproject": "private",
                "filesourcepath": "private",
                "keyframe": "safe",
                "keypoint": "safe",
                "projection": "safe",
                "projector": "safe",
                "homeroom": "safe",
                "homepage": "safe",
                "resource": "safe",
                "profile": "safe",
                "monkey": "safe",
                "keyboard": "safe",
                "homework": "safe",
                "projectile": "safe",
                "cachet": "safe",
            }
        }),),
    )
    con.commit()
    con.close()

    build_public_database(source, destination)

    con = sqlite3.connect(destination)
    payload = json.loads(con.execute("SELECT raw FROM face_evidence").fetchone()[0])
    con.close()
    assert payload == {
        "nested": {
            "keyframe": "safe",
            "keypoint": "safe",
            "projection": "safe",
            "projector": "safe",
            "homeroom": "safe",
            "homepage": "safe",
            "resource": "safe",
            "profile": "safe",
            "monkey": "safe",
            "keyboard": "safe",
            "homework": "safe",
            "projectile": "safe",
            "cachet": "safe",
        }
    }


def test_scan_failure_preserves_preexisting_destination_bytes(tmp_path):
    source = tmp_path / "private.db"
    destination = tmp_path / "existing-public.db"
    _synthetic_private_database(source)
    con = sqlite3.connect(source)
    con.execute(
        "UPDATE bg SET label=?",
        (sqlite3.Binary(b"Bearer sk-final-scan-secret"),),
    )
    con.commit()
    con.close()
    original = b"pre-existing-public-database"
    destination.write_bytes(original)

    with pytest.raises(ValueError, match="credential-like value"):
        build_public_database(source, destination)

    assert destination.read_bytes() == original


def test_binary_scan_does_not_mistake_sqlite_page_bytes_for_posix_paths(tmp_path):
    source = tmp_path / "private.db"
    destination = tmp_path / "public.db"
    _synthetic_private_database(source)
    con = sqlite3.connect(source)
    con.executemany(
        "INSERT INTO bg(name,label) VALUES (?,?)",
        [
            (f"BG_Public_{index:05d}", "indoor/outdoor " + "semantic" * 120)
            for index in range(2500)
        ],
    )
    con.commit()
    con.close()

    build_public_database(source, destination)

    con = sqlite3.connect(destination)
    assert con.execute("SELECT COUNT(*) FROM bg").fetchone()[0] == 2501
    con.close()
