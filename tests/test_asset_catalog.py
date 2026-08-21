import json

import pytest
from PIL import Image

import assetdb
from asset_catalog import (
    _face_capabilities, export_model_constraints,
    merge_face_capabilities, merge_scene_capabilities,
    merge_model_constraints,
    migrate,
    set_asset_status,
    upsert_candidate,
)
from spine_face_labeler import persist_visual_face_labels
from asset_validation import validate_background
from asset_models import AssetCandidate
from annotate import is_face_allowed


def test_connect_readonly_does_not_create_or_mutate_database(tmp_path):
    database = tmp_path / "readonly.db"
    con = assetdb.connect(database)
    con.execute("INSERT INTO bg(name,hash,label) VALUES(?,?,?)", ("BG_A", 1, "A"))
    con.commit()
    con.close()

    read_only = assetdb.connect_readonly(database)
    assert read_only.execute("SELECT label FROM bg WHERE name='BG_A'").fetchone()[0] == "A"
    with pytest.raises(Exception):
        read_only.execute("INSERT INTO bg(name,hash,label) VALUES(?,?,?)", ("BG_B", 2, "B"))
    read_only.close()


def test_migration_preserves_legacy_rows(tmp_path):
    con = assetdb.connect(tmp_path / "legacy.db")
    con.execute(
        "INSERT INTO bg(name,hash,label) VALUES(?,?,?)",
        ("BG_Black", 1047754314, "黑屏"),
    )
    con.commit()

    migrate(con)

    row = con.execute("SELECT name,hash,label FROM bg").fetchone()
    assert tuple(row) == ("BG_Black", 1047754314, "黑屏")
    assert con.execute(
        "SELECT value FROM meta WHERE key='asset_schema_version'"
    ).fetchone()[0] == "2"


def test_only_registered_custom_assets_are_exported(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    source = tmp_path / "夜景.png"
    Image.new("RGB", (16, 9), "navy").save(source)
    candidate = validate_background(source).candidate

    upsert_candidate(con, candidate, scope="library", status="validated")
    before = export_model_constraints(con)
    set_asset_status(
        con,
        kind="background",
        aa_key=candidate.aa_key,
        scope="library",
        status="registered",
        install_path=str(tmp_path / "project" / "bgs" / source.name),
    )
    after = export_model_constraints(con)

    assert before["backgrounds"] == {}
    assert after["backgrounds"] == {
        "夜景": {
            "aa_key": candidate.aa_key,
            "install_path": str(tmp_path / "project" / "bgs" / source.name),
            "status": "registered",
        }
    }


def test_character_identifier_is_stored_verbatim(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    con.execute(
        """
        INSERT INTO asset_install
          (kind,aa_key,display_name,source_path,sha256,scope,status,metadata_json)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            "character",
            "用户填写-ID_01",
            "凯伊",
            "D:/source",
            "abc",
            "library",
            "verified",
            json.dumps({"faces": ["00", "03"]}),
        ),
    )
    con.commit()

    out = export_model_constraints(con)

    assert out["characters"][0]["identifier"] == "用户填写-ID_01"
    assert out["characters"][0]["faces"] == ["00", "03"]


def test_import_index_preserves_official_avatar_key(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    assetdb.import_index(con, {"characters": [{
        "identifier": "hifumi",
        "name": "日步美",
        "club": "补课部",
        "spine": "UIs/03_Scenario/02_Character/CharacterSpine_hihumi",
        "avatar": "UIs/01_Common/01_Character/Student_Portrait_Hifumi",
        "faces": [],
    }]})

    row = con.execute(
        "SELECT avatar FROM character WHERE ident='hifumi'"
    ).fetchone()

    assert row["avatar"].endswith("Student_Portrait_Hifumi")
    exported = assetdb.export_json(con, tmp_path / "export.json")
    assert exported["characters"][0]["avatar"].endswith(
        "Student_Portrait_Hifumi"
    )


def test_connect_migrates_old_character_table_with_existing_rows(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.execute(
        "CREATE TABLE character (ident TEXT PRIMARY KEY, name TEXT, "
        "club TEXT, spine TEXT, source TEXT)"
    )
    raw.execute(
        "INSERT INTO character VALUES (?,?,?,?,?)",
        ("legacy", "旧角色", "社团", "old-spine", "legacy"),
    )
    raw.commit()
    raw.close()

    con = assetdb.connect(path)

    columns = {
        row["name"] for row in con.execute("PRAGMA table_info(character)")
    }
    row = con.execute(
        "SELECT ident,name,avatar FROM character WHERE ident='legacy'"
    ).fetchone()
    assert "avatar" in columns
    assert tuple(row) == ("legacy", "旧角色", "")


def test_import_bg_files_computes_custom_background_hash(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    bgs = tmp_path / "bgs"
    bgs.mkdir()
    Image.new("RGB", (8, 8)).save(
        bgs / "ChatGPT Image 2026年7月19日 01_00_25.png"
    )

    assetdb.import_bg_files(con, bgs)

    value = con.execute(
        "SELECT hash FROM bg WHERE name=?",
        ("ChatGPT Image 2026年7月19日 01_00_25",),
    ).fetchone()[0]
    assert value == 3077983933


def test_empty_face_allowlist_rejects_model_face():
    assert not is_face_allowed(set(), "03")
    assert is_face_allowed({"00", "03"}, "03")


def test_semantic_parts_are_exported_but_do_not_become_face_ids(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    candidate = AssetCandidate(
        kind="character",
        source_path=tmp_path,
        stem="Kei_Date_Outfit",
        aa_key="626652156",
        sha256="x",
        metadata={
            "spine_signature": "date-sha",
            "outfit_key": "Kei_Date_Outfit",
            "expression_mode": "semantic_modular",
            "expression_parts": [{
                "kind": "eyes",
                "raw_name": "圆睁高光眼（惊讶）",
                "labels": ["惊讶"],
                "source": "atlas_semantic",
            }],
            "faces": [],
        },
    )

    upsert_candidate(con, candidate, scope="sample", status="registered")
    out = export_model_constraints(con, scope="sample")["characters"][0]

    assert out["expression_mode"] == "semantic_modular"
    assert out["expression_parts"] == [{
        "kind": "eyes",
        "raw_name": "圆睁高光眼（惊讶）",
        "labels": ["惊讶"],
        "source": "atlas_semantic",
    }]
    assert out["faces"] == []
    assert out["face_capabilities"] == []


def test_semantic_modes_are_exposed_to_runtime_face_capabilities(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    modes = [{
        "label_cn": "认真说明", "beat_fit": ["exposition"],
        "delivery_fit": ["normal_speech"], "intensity": 1,
        "semantic_tags": ["serious"], "avoid_when_cn": "激烈喊叫",
    }]
    persist_visual_face_labels(
        con,
        ident="hero",
        spine_signature="sig",
        outfit_key="school",
        model="face-label-v4",
        labels=[{
            "face_id": "05", "primary_emotion": "认真", "usage_hint_cn": "正式说明",
            "eyes": "睁眼", "brows": "平直", "mouth": "微张",
            "blush": False, "tears": False, "confidence": 0.9,
            "semantic_modes": modes,
        }],
    )

    face = _face_capabilities(con)["hero"][0]["faces"][0]
    assert face["semantic_modes"] == modes


def test_expression_parts_do_not_cross_skeleton_variants(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    assetdb.replace_expression_parts(
        con,
        ident="626652156",
        spine_signature="winter",
        outfit_key="winter",
        parts=[{
            "kind": "mouth",
            "raw_name": "冬装笑嘴（微笑）",
            "labels": ["微笑"],
            "source": "atlas_semantic",
        }],
    )
    assetdb.replace_expression_parts(
        con,
        ident="626652156",
        spine_signature="date",
        outfit_key="date",
        parts=[{
            "kind": "eyes",
            "raw_name": "约会服眼（惊讶）",
            "labels": ["惊讶"],
            "source": "atlas_semantic",
        }],
    )

    rows = assetdb.expression_parts_by_variant(con)

    assert rows[("626652156", "winter", "winter")][0]["kind"] == "mouth"
    assert rows[("626652156", "date", "date")][0]["kind"] == "eyes"


def test_model_constraints_are_limited_to_target_project(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    for scope, name, key in (
        ("project-A", "A背景", "101"),
        ("project-B", "B背景", "202"),
    ):
        con.execute(
            """
            INSERT INTO asset_install
              (kind,aa_key,display_name,source_path,sha256,scope,
               install_path,status,metadata_json)
            VALUES ('background',?,?,?,?,?,?, 'registered','{}')
            """,
            (key, name, f"{name}.png", key * 8, scope, f"{scope}/{name}.png"),
        )
    con.commit()

    out = export_model_constraints(con, scope="project-A")

    assert set(out["backgrounds"]) == {"A背景"}


def test_registered_constraints_merge_into_generator_index(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    con.execute(
        """
        INSERT INTO asset_install
          (kind,aa_key,display_name,source_path,sha256,scope,
           install_path,status,metadata_json)
        VALUES ('sound','custom-bell','门铃','bell.wav','abc','project-A',
                'sounds/bell.wav','verified',
                '{"labels":{"label":"门铃声","tags":"门口,提示"}}')
        """
    )
    con.commit()
    index = {"bg": {"BG_Black": 1}, "sounds": ["SE_Click"], "characters": []}

    merged = merge_model_constraints(index, con, scope="project-A")

    assert merged["sounds"] == ["SE_Click", "custom-bell"]
    assert merged["sound_label"]["custom-bell"]["label"] == "门铃声"
    assert index["sounds"] == ["SE_Click"]


def test_merge_records_custom_background_provenance(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    con.execute(
        """
        INSERT INTO asset_install
          (kind,aa_key,display_name,source_path,sha256,scope,
           install_path,status,metadata_json)
        VALUES ('background','202','章节夜景','night.png','abc','project-A',
                'bgs/night.png','registered',
                '{"labels":{"label":"夜景"}}')
        """
    )
    con.commit()

    merged = merge_model_constraints(
        {"bg": {"BG_Black": 1}, "sounds": [], "characters": []},
        con,
        scope="project-A",
    )

    assert merged["custom_asset_keys"]["backgrounds"] == ["章节夜景"]
    assert "BG_Black" not in merged["custom_asset_keys"]["backgrounds"]


def test_merge_enriches_official_character_with_variant_face_evidence(tmp_path):
    """Adding an outfit must extend an existing identifier, never discard the official row."""
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    con.executemany(
        "INSERT INTO character_variant VALUES (?,?,?,?)",
        [("1516544", "sig-winter", "winter", "winter.skel"),
         ("1516544", "sig-summer", "summer", "summer.skel")],
    )
    con.executemany(
        """
        INSERT INTO face_evidence
          (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        [
            ("1516544", "sig-winter", "winter", "00", "atlas_candidate", "default", "default", "", 0),
            ("1516544", "sig-winter", "winter", "99", "aap_observed", "99", "", "", 1),
            ("1516544", "sig-summer", "summer", "01", "aa_verified", "normal", "normal", "", 0),
        ],
    )
    con.commit()
    official = {
        "bg": {}, "sounds": [],
        "characters": [{
            "identifier": "1516544", "name": "Official Kei", "club": "", "spine": "",
            "faces": [{"id": "00", "raw": "default", "label": "default", "cn": ""}],
        }],
    }

    merged = merge_model_constraints(official, con, scope="project-A")

    character = merged["characters"][0]
    assert character["name"] == "Official Kei"
    assert [face["id"] for face in character["faces"]] == ["00", "01", "99"]
    assert [(variant["spine_signature"], variant["outfit_key"])
            for variant in character["face_capabilities"]] == [
        ("sig-summer", "summer"), ("sig-winter", "winter"),
    ]
    winter_faces = character["face_capabilities"][1]["faces"]
    assert winter_faces[1]["sources"] == ["aap_observed"]
    assert winter_faces[1]["verified"] is False
    assert character["face_capabilities"][0]["faces"][0]["verified"] is True


def test_merge_attaches_registered_variant_to_existing_official_character(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    con.execute(
        """
        INSERT INTO asset_install
          (kind,aa_key,display_name,source_path,sha256,scope,status,metadata_json)
        VALUES ('character','1516544','Winter Kei','source','digest','project-A','registered',?)
        """,
        (json.dumps({
            "faces": ["99"], "spine_signature": "sig-winter", "outfit_key": "winter",
        }),),
    )
    con.commit()
    official = {"bg": {}, "sounds": [], "characters": [{
        "identifier": "1516544", "name": "Official Kei", "club": "", "spine": "",
        "faces": [{"id": "00", "raw": "00", "label": "", "cn": ""}],
    }]}

    merged = merge_model_constraints(official, con, scope="project-A")

    assert [face["id"] for face in merged["characters"][0]["faces"]] == ["00", "99"]
    assert merged["face_capabilities"]["1516544"][0]["faces"][0]["sources"] == ["atlas_candidate"]


def test_merge_face_capabilities_overlays_new_database_semantics_on_stale_index(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    con.execute(
        "INSERT INTO character(ident,name,club,spine,source) VALUES(?,?,?,?,?)",
        ("aris", "爱丽丝", "", "CharacterSpine_aris", "official"),
    )
    con.execute(
        "INSERT INTO character_variant(ident,spine_signature,outfit_key,spine) "
        "VALUES(?,?,?,?)",
        ("aris", "sig", "CharacterSpine_aris", "CharacterSpine_aris"),
    )
    con.execute(
        "INSERT INTO face_evidence "
        "(ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        ("aris", "sig", "CharacterSpine_aris", "03", "vision:model", "{}", "", "欣喜开朗", 0),
    )
    con.execute(
        "INSERT INTO face_visual_label "
        "(ident,spine_signature,outfit_key,face_id,model,primary_emotion,confidence,"
        "description_cn,semantic_json) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "aris", "sig", "CharacterSpine_aris", "03", "model", "欣喜开朗", 0.96,
            "适合由衷高兴或主动参与时使用。",
            json.dumps({
                "emotion_family": "joy", "intensity": 2,
                "expression_class": "accent", "beat_fit": ["reaction"],
                "hold_policy": "short", "search_terms_cn": ["开心", "参与"],
            }, ensure_ascii=False),
        ),
    )
    assetdb.set_active_face_label_model(con, "model")
    con.commit()
    stale = {
        "characters": [{
            "identifier": "aris", "name": "爱丽丝", "club": "", "spine": "CharacterSpine_aris",
            "faces": [{"id": "03", "raw": "03", "label": "", "cn": ""}],
        }],
        "face_capabilities": {"aris": []},
    }

    merged = merge_face_capabilities(stale, con)

    face = merged["face_capabilities"]["aris"][0]["faces"][0]
    assert face["id"] == "03"
    assert face["semantic_cn"].startswith("欣喜开朗")
    assert merged["characters"][0]["face_capabilities"][0]["faces"][0] == face


def test_merge_face_capabilities_adds_missing_official_character_from_overlay(tmp_path):
    con = assetdb.connect(tmp_path / "overlay.db")
    con.execute(
        "INSERT INTO character(ident,name,club,spine,source) VALUES(?,?,?,?,?)",
        ("아리스N", "愛麗絲", "遊戲開發部", "CharacterSpine_aris_noweapon", "official"),
    )
    con.execute(
        "INSERT INTO face(ident,face_id,raw,label,label_cn,source) "
        "VALUES(?,?,?,?,?,?)",
        ("아리스N", "01", "normal", "normal", "平常", "atlas"),
    )
    con.commit()

    merged = merge_face_capabilities({"characters": []}, con)

    row = next(item for item in merged["characters"] if item["identifier"] == "아리스N")
    assert row["spine"] == "CharacterSpine_aris_noweapon"
    assert row["faces"] == [{
        "id": "01", "raw": "normal", "label": "normal", "cn": "平常",
    }]
    con.close()


def test_merge_face_capabilities_reads_legacy_database_without_new_provenance_columns(
    tmp_path,
):
    database = tmp_path / "legacy-labels.db"
    con = assetdb.connect(database)
    con.execute(
        "INSERT INTO character(ident,name,club,spine,source) VALUES(?,?,?,?,?)",
        ("aris", "爱丽丝", "", "CharacterSpine_aris", "official"),
    )
    con.execute(
        "INSERT INTO character_variant(ident,spine_signature,outfit_key,spine) "
        "VALUES(?,?,?,?)",
        ("aris", "sig", "CharacterSpine_aris", "CharacterSpine_aris"),
    )
    con.execute(
        "INSERT INTO face_evidence "
        "(ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        ("aris", "sig", "CharacterSpine_aris", "03", "vision:legacy-model", "{}", "", "开心", 0),
    )
    con.execute(
        "INSERT INTO face_visual_label "
        "(ident,spine_signature,outfit_key,face_id,model,primary_emotion,confidence,"
        "description_cn,semantic_json) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "aris", "sig", "CharacterSpine_aris", "03", "legacy-model", "开心", 0.9,
            "旧数据库中仍然有效的表情语义。",
            json.dumps({"emotion_family": "joy"}, ensure_ascii=False),
        ),
    )
    assetdb.set_active_face_label_model(con, "legacy-model")
    con.commit()
    con.execute("ALTER TABLE face_visual_label DROP COLUMN backend_json")
    con.execute("ALTER TABLE face_visual_label DROP COLUMN observation_json")
    con.commit()
    con.close()

    read_only = assetdb.connect_readonly(database)
    try:
        merged = merge_face_capabilities({
            "characters": [{
                "identifier": "aris", "name": "爱丽丝", "club": "",
                "spine": "CharacterSpine_aris", "faces": [],
            }],
            "face_capabilities": {},
        }, read_only)
    finally:
        read_only.close()

    face = merged["face_capabilities"]["aris"][0]["faces"][0]
    assert face["id"] == "03"
    assert face["semantic_cn"] == "开心"


def test_merge_scene_capabilities_adds_labelled_backgrounds_without_overwriting_index(tmp_path):
    con = assetdb.connect(tmp_path / "scene.db")
    con.execute("INSERT INTO bg(name,hash,label) VALUES(?,?,?)", ("BG_New", 22, "新背景"))
    con.execute(
        """INSERT INTO scene_visual_label
        (resource_channel,asset_key,content_sha256,source_kind,model,visual_kind,
         label_json,evidence_json,confidence,status)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            "background", "BG_New", "digest", "official_base", "scene-model",
            "background",
            json.dumps({
                "label": "新背景", "description": "有标注的校园空间",
                "main_category": "campus", "subcategory": "教学楼",
                "dialogue_suitable": True, "search_terms_cn": ["教学楼", "校园"],
            }, ensure_ascii=False),
            json.dumps({"source_category": "official"}, ensure_ascii=False),
            0.95, "ready",
        ),
    )
    con.commit()
    stale = {"bg": {"BG_Existing": 1, "BG_New": 22}, "bg_label": {}, "scene_labels": {}}
    merged = merge_scene_capabilities(stale, con)
    assert merged["bg"]["BG_New"] == 22
    assert merged["scene_labels"]["background"]["BG_New"]["subcategory"] == "教学楼"
    assert merged["bg"]["BG_Existing"] == 1
    assert "BG_Unknown" not in merged["bg"]
    con.close()
def test_character_export_includes_variant_metadata(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    con.execute(
        """
        INSERT INTO asset_install
          (kind,aa_key,display_name,source_path,sha256,scope,status,metadata_json)
        VALUES ('character','1516544','Kei','source','digest','project-A','registered',?)
        """,
        (json.dumps({
            "faces": ["00"], "spine_signature": "sig-winter", "outfit_key": "winter",
        }),),
    )
    con.commit()

    character = export_model_constraints(con, scope="project-A")["characters"][0]

    assert character["spine_signature"] == "sig-winter"
    assert character["outfit_key"] == "winter"
    assert character["face_capabilities"] == [{
        "spine_signature": "sig-winter", "outfit_key": "winter", "spine": "",
        "faces": [{
            "id": "00", "raw": "00", "label": "", "cn": "",
            "sources": ["atlas_candidate"], "observed_count": 0, "verified": False,
            "visual_evidence": "unknown",
        }],
    }]
