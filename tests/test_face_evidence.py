import sqlite3
import hashlib
import json

import assetdb
from asset_catalog import _face_capabilities, migrate
from build_index import harvest_face_capabilities
from annotate import face_allowlist, is_face_allowed


def make_legacy_database(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE character (
            ident TEXT PRIMARY KEY, name TEXT, club TEXT, spine TEXT, source TEXT
        );
        CREATE TABLE face (
            ident TEXT, face_id TEXT, raw TEXT, label TEXT, label_cn TEXT, source TEXT,
            PRIMARY KEY (ident, face_id)
        );
        """
    )
    con.execute(
        "INSERT INTO character VALUES ('1516544', 'Kei', '', 'old/spine', 'overrides')"
    )
    con.execute(
        "INSERT INTO face VALUES ('1516544', '99', '99', '', '', 'atlas')"
    )
    con.commit()
    con.close()


def test_face_evidence_migration_keeps_legacy_rows_and_distinct_sources(tmp_path):
    """A source-specific proof must not overwrite another proof for the same face."""
    path = tmp_path / "legacy.db"
    make_legacy_database(path)
    con = assetdb.connect(path)

    migrate(con)
    con.executemany(
        """
        INSERT INTO face_evidence
          (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        [
            ("1516544", "sig-a", "winter", "99", "atlas_candidate", "99", "", "", 0),
            ("1516544", "sig-a", "winter", "99", "aap_observed", "99", "", "", 1),
            ("1516544", "sig-a", "winter", "99", "aa_verified", "99", "", "", 0),
        ],
    )
    con.commit()

    assert con.execute("SELECT face_id,source FROM face").fetchone()["source"] == "atlas"
    assert [tuple(row) for row in con.execute(
        "SELECT source,observed_count FROM face_evidence "
        "WHERE ident='1516544' AND spine_signature='sig-a' AND face_id='99' ORDER BY source"
    )] == [
        ("aa_verified", 0),
        ("aap_observed", 1),
        ("atlas_candidate", 0),
    ]
    assert [tuple(row) for row in con.execute(
        "SELECT spine_signature,outfit_key FROM character_variant WHERE ident='1516544'"
    )] == [("", "")]
    assert [tuple(row) for row in con.execute(
        "SELECT source FROM face_evidence "
        "WHERE ident='1516544' AND spine_signature='' AND outfit_key='' AND face_id='99'"
    )] == [("atlas_candidate",)]


def test_harvest_keeps_single_observed_face_99_without_atlas_region(tmp_path):
    """A recorded bone face is evidence even when its atlas has no numeric region."""
    data = tmp_path / "synthetic-aa"
    bundle = data / "overrides" / "characters" / "1516544"
    bundle.mkdir(parents=True)
    skel_bytes = b"synthetic skeleton"
    (bundle / "winter.skel").write_bytes(skel_bytes)
    (bundle / "winter.atlas").write_text(
        "winter.png\nsize: 8,8\n00_default\n  bounds:0,0,1,1\n01_normal\n  bounds:1,1,1,1\n",
        encoding="utf-8",
    )
    (data / "overrides" / "manifest.json").write_text(
        json.dumps({"CharacterOverrides": [{
            "Identifier": "1516544", "Name": "Kei", "Nickname": "",
            "SpinePortraitPath": "characters/1516544/winter",
        }]}),
        encoding="utf-8",
    )
    aap = data / "projects" / "sample" / "scene.aap"
    aap.parent.mkdir(parents=True)
    aap.write_text(json.dumps({"records": [{
        "$type": "ScriptData+CharacterRecordData, Assembly-CSharp",
        "name": "1516544", "faceId": "99",
    }]}), encoding="utf-8")

    capabilities = harvest_face_capabilities(data)

    assert capabilities["1516544"][0]["spine_signature"] == hashlib.sha256(skel_bytes).hexdigest()
    assert [face["id"] for face in capabilities["1516544"][0]["faces"]] == ["00", "01"]
    observed = capabilities["1516544"][1]
    assert observed["spine_signature"] == ""
    assert observed["outfit_key"] == ""
    assert observed["faces"] == [{
        "id": "99", "raw": "99", "label": "", "cn": "",
        "sources": ["aap_observed"], "observed_count": 1, "verified": False,
    }]


def test_harvest_scopes_project_face_observation_to_matching_skeleton(tmp_path):
    """A project manifest lets a historical face use prove one exact skeleton."""
    data = tmp_path / "synthetic-aa"
    project = data / "projects" / "sample"
    spine = project / "characters" / "1516544"
    spine.mkdir(parents=True)
    skel_bytes = b"same custom skeleton"
    (spine / "winter.skel").write_bytes(skel_bytes)
    (project / "manifest.json").write_text(json.dumps({"CharacterOverrides": [{
        "Identifier": "1516544", "SpinePortraitPath": "characters/1516544/winter",
    }]}), encoding="utf-8")
    (project / "scene.aap").write_text(json.dumps({"records": [{
        "$type": "ScriptData+CharacterRecordData, Assembly-CSharp",
        "name": "1516544", "faceId": "99",
    }]}), encoding="utf-8")

    capabilities = harvest_face_capabilities(data)

    observed = next(variant for variant in capabilities["1516544"]
                    if any(face["id"] == "99" for face in variant["faces"]))
    assert observed["spine_signature"] == hashlib.sha256(skel_bytes).hexdigest()
    assert observed["outfit_key"] == "winter"
    assert observed["faces"] == [{
        "id": "99", "raw": "99", "label": "", "cn": "",
        "sources": ["aap_observed"], "observed_count": 1, "verified": False,
    }]


def test_annotation_uses_observed_or_verified_variant_evidence_only():
    """Model guesses must not turn an atlas candidate into verified evidence."""
    capabilities = {
        "1516544": [
            {
                "spine_signature": "sig-winter", "outfit_key": "winter", "spine": "",
                "faces": [
                    {"id": "00", "sources": ["atlas_candidate"], "verified": False},
                    {"id": "99", "sources": ["aap_observed"], "verified": False},
                ],
            },
            {
                "spine_signature": "", "outfit_key": "", "spine": "",
                "faces": [
                    {"id": "01", "sources": ["aap_observed"], "verified": False},
                    {"id": "02", "sources": ["aa_verified"], "verified": True},
                ],
            },
        ]
    }

    selected = face_allowlist(
        capabilities, "1516544", spine_signature="sig-winter", outfit_key="winter"
    )
    identifier_level = face_allowlist(capabilities, "1516544")

    assert is_face_allowed(selected, "99")
    assert not is_face_allowed(selected, "00")
    assert not is_face_allowed(selected, "01")
    assert identifier_level == {"01", "02"}
    assert not is_face_allowed(identifier_level, "99")
    assert not is_face_allowed(face_allowlist(capabilities, "missing"), "99")


def test_import_index_persists_variant_evidence_without_upgrading_sources(tmp_path):
    """Index import must preserve source classes instead of treating candidates as verified."""
    con = assetdb.connect(tmp_path / "assets.db")
    assetdb.import_index(con, {
        "characters": [],
        "face_capabilities": {
            "1516544": [{
                "spine_signature": "sig-winter", "outfit_key": "winter", "spine": "winter.skel",
                "faces": [
                    {"id": "00", "raw": "default", "label": "default", "cn": "",
                     "sources": ["atlas_candidate"], "observed_count": 0, "verified": False},
                    {"id": "99", "raw": "99", "label": "", "cn": "",
                     "sources": ["aap_observed"], "observed_count": 1, "verified": False},
                ],
            }],
        },
        "enums": {},
    })

    assert [tuple(row) for row in con.execute(
        "SELECT face_id,source,observed_count FROM face_evidence ORDER BY face_id"
    )] == [("00", "atlas_candidate", 0), ("99", "aap_observed", 1)]


def test_legacy_index_keeps_atlas_and_observed_99_as_separate_evidence(tmp_path):
    """A legacy `face` upsert must not erase a same-id AAP observation."""
    con = assetdb.connect(tmp_path / "assets.db")
    assetdb.import_index(con, {
        "characters": [{
            "identifier": "1516544", "name": "Kei", "club": "", "spine": "",
            "faces": [{"id": "99", "raw": "atlas-99", "label": "candidate"}],
        }],
        "faces_used": {"1516544": [{"id": "99", "raw": "99", "label": ""}]},
        "enums": {},
    })
    migrate(con)

    capabilities = _face_capabilities(con)

    assert [tuple(row) for row in con.execute(
        "SELECT source FROM face_evidence WHERE ident='1516544' AND face_id='99' ORDER BY source"
    )] == [("aap_observed",), ("atlas_candidate",)]
    assert is_face_allowed(face_allowlist(capabilities, "1516544"), "99")


def test_selector_miss_rejects_identifier_level_observed_face():
    """Supplying any nonmatching variant selector must not fall back to identifier evidence."""
    capabilities = {"1516544": [{
        "spine_signature": "", "outfit_key": "", "spine": "",
        "faces": [{"id": "99", "sources": ["aap_observed"], "verified": False}],
    }]}

    assert face_allowlist(capabilities, "1516544", spine_signature="wrong") == set()
    assert face_allowlist(capabilities, "1516544", outfit_key="wrong") == set()


def test_atlas_source_remains_unverified_even_when_boolean_is_inconsistent(tmp_path):
    """Only sources may grant verification; a stale boolean cannot create aa_verified evidence."""
    capabilities = {"1516544": [{
        "spine_signature": "sig", "outfit_key": "winter", "spine": "",
        "faces": [{"id": "99", "sources": ["atlas_candidate"], "verified": True}],
    }]}
    con = assetdb.connect(tmp_path / "assets.db")
    assetdb.import_index(con, {"characters": [], "face_capabilities": capabilities, "enums": {}})

    assert face_allowlist(capabilities, "1516544", spine_signature="sig") == set()
    assert [tuple(row) for row in con.execute(
        "SELECT source FROM face_evidence WHERE ident='1516544'"
    )] == [("atlas_candidate",)]


def test_face_display_prefers_verified_metadata_over_observed_and_atlas(tmp_path):
    """The human-facing raw/label must be deterministic when sources disagree."""
    con = assetdb.connect(tmp_path / "assets.db")
    con.executemany(
        """
        INSERT INTO face_evidence
          (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        [
            ("1516544", "sig", "winter", "99", "atlas_candidate", "atlas", "candidate", "", 0),
            ("1516544", "sig", "winter", "99", "aap_observed", "observed", "observed", "", 1),
            ("1516544", "sig", "winter", "99", "aa_verified", "verified", "verified", "", 0),
        ],
    )
    con.commit()

    face = _face_capabilities(con)["1516544"][0]["faces"][0]

    assert (face["raw"], face["label"], face["sources"]) == (
        "verified", "verified", ["aa_verified", "aap_observed", "atlas_candidate"]
    )


def test_face_capabilities_expose_strongest_visual_evidence_per_variant(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    con.executemany(
        """
        INSERT INTO face_evidence
          (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        [
            ("kai", "sig", "winter", "00", "vision:model-a", "{}", "", "平静", 0),
            ("kai", "sig", "winter", "01", "spine_semantic", "smile", "smile", "微笑", 0),
            ("kai", "sig", "winter", "02", "aap_observed", "02", "", "", 3),
            ("kai", "sig", "winter", "03", "atlas_candidate", "03", "", "", 0),
            ("kai", "sig", "winter", "04", "atlas_candidate", "smile", "smile", "微笑", 0),
            ("kai", "sig", "winter", "04", "aap_observed", "04", "", "", 1),
            ("kai", "sig", "winter", "05", "aa_verified", "smile", "smile", "微笑", 0),
            ("kai", "sig", "winter", "06", "aa_verified", "06", "", "", 0),
        ],
    )
    con.commit()

    faces = _face_capabilities(con)["kai"][0]["faces"]

    assert {face["id"]: face["visual_evidence"] for face in faces} == {
        "00": "visual_confirmed",
        "01": "asset_semantic",
        "02": "context_inferred",
        "03": "unknown",
        "04": "asset_semantic",
        "05": "asset_semantic",
        "06": "context_inferred",
    }
