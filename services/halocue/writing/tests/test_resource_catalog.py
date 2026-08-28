from __future__ import annotations

import sqlite3
import json

from halocue_writing.resource_catalog import ResourceCatalog, SCHEMA_VERSION


def test_legacy_catalog_import_creates_independent_1_0_projection(tmp_path):
    source = tmp_path / "legacy-095.db"
    connection = sqlite3.connect(source)
    connection.executescript(
        """
        CREATE TABLE bg (name TEXT PRIMARY KEY, label TEXT, place TEXT, time TEXT, mood TEXT, tags TEXT);
        CREATE TABLE character (ident TEXT PRIMARY KEY, name TEXT, club TEXT, spine TEXT, avatar TEXT, source TEXT);
        CREATE TABLE character_variant (ident TEXT, spine_signature TEXT, outfit_key TEXT, spine TEXT);
        CREATE TABLE face (ident TEXT, face_id TEXT, raw TEXT, label TEXT, label_cn TEXT, PRIMARY KEY (ident, face_id));
        INSERT INTO bg VALUES ('BG_Classroom', '教室', '千年校舍', 'day', '日常', '室内,校园');
        INSERT INTO character VALUES ('alice', '爱丽丝', '游戏开发部', 'alice-spine', '', 'overrides');
        INSERT INTO character_variant VALUES ('alice', 'sig-1', 'uniform', 'alice-spine');
        INSERT INTO face VALUES ('alice', '03', '03_smile', 'smile', '微笑');
        """
    )
    connection.commit()
    connection.close()

    catalog = ResourceCatalog(tmp_path / "writing-data")
    result = catalog.import_legacy(source)

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["imported"] == {"backgrounds": 1, "characters": 1, "variants": 1, "faces": 1, "expression_parts": 0}
    assert catalog.search("backgrounds", "教室")["items"][0]["display_name"] == "教室"
    assert catalog.search("characters", "爱丽丝")["items"][0]["display_name"] == "爱丽丝"
    assert catalog.descriptor()["counts"] == {
        "backgrounds": 1,
        "characters": 1,
        "variants": 1,
        "faces": 1,
        "expression_parts": 0,
        "user_overrides": 0,
    }

    connection = sqlite3.connect(source)
    assert connection.execute("SELECT label FROM bg WHERE name='BG_Classroom'").fetchone()[0] == "教室"
    connection.close()


def test_empty_1_0_catalog_does_not_claim_ready(tmp_path):
    descriptor = ResourceCatalog(tmp_path).descriptor()
    assert descriptor["schema_version"] == SCHEMA_VERSION
    assert descriptor["ready"] is False


def test_public_background_projection_hides_export_identifiers(tmp_path):
    source = tmp_path / "legacy-095.db"
    with sqlite3.connect(source) as connection:
        connection.executescript(
            """
            CREATE TABLE bg (name TEXT PRIMARY KEY, label TEXT, place TEXT, time TEXT, mood TEXT, tags TEXT);
            INSERT INTO bg VALUES ('00000-123456', '00000-123456', '', '', '', '');
            INSERT INTO bg VALUES ('BG_Roof', '屋顶', '校园屋顶', '', '', '');
            """
        )
    catalog = ResourceCatalog(tmp_path / "writing-data")
    catalog.import_legacy(source)
    named = catalog.search("backgrounds", "屋顶")["items"][0]
    assert catalog.search("backgrounds", "00000-123456")["items"] == []
    assert named["display_name"] == "屋顶"
    assert catalog.search("backgrounds")["items"][0]["display_name"] == "屋顶"
    with sqlite3.connect(catalog.path) as connection:
        assert connection.execute(
            "SELECT visual_kind FROM backgrounds WHERE key='00000-123456'"
        ).fetchone()[0] == "custom_background"


def test_background_search_excludes_cg_effects_and_registered_custom_backgrounds(tmp_path):
    source = tmp_path / "legacy-095.db"
    with sqlite3.connect(source) as connection:
        connection.executescript(
            """
            CREATE TABLE bg (name TEXT PRIMARY KEY, label TEXT, place TEXT, time TEXT, mood TEXT, tags TEXT);
            CREATE TABLE asset_install (kind TEXT, display_name TEXT, status TEXT);
            CREATE TABLE scene_visual_label (resource_channel TEXT, asset_key TEXT, visual_kind TEXT, label_json TEXT, manual_json TEXT, status TEXT, confidence REAL);
            INSERT INTO bg VALUES ('BG_Classroom', '教室', '校园', 'day', '日常', '室内');
            INSERT INTO bg VALUES ('BG_CS_Moment', '剧情特写', '', '', '', '');
            INSERT INTO bg VALUES ('My_Rain_Roof', '我的雨夜屋顶', '', '', '', '');
            INSERT INTO bg VALUES ('ChatGPT Image 2026-08-22', '生成的咖啡馆', '', '', '', '');
            INSERT INTO bg VALUES ('BG_CS_Unlabeled', '剧情镜头', '', '', '', '');
            INSERT INTO bg VALUES ('00013', '00013', '', '', '', '');
            INSERT INTO bg VALUES ('01e31d07035932ab7ddedfeb9f120aea', '01e31d07035932ab7ddedfeb9f120aea', '', '', '', '');
            INSERT INTO asset_install VALUES ('background', 'My_Rain_Roof', 'registered');
            INSERT INTO scene_visual_label VALUES ('background', 'BG_CS_Moment', 'cg', '{"label":"剧情特写","visual_kind":"cg"}', '{}', 'ready', .98);
            """
        )

    catalog = ResourceCatalog(tmp_path / "writing-data")
    result = catalog.import_legacy(source)

    assert result["imported"]["backgrounds"] == 7
    assert [item["technical"]["key"] for item in catalog.search("backgrounds")["items"]] == ["BG_Classroom"]
    assert catalog.search("backgrounds", "剧情特写")["items"] == []
    assert catalog.search("backgrounds", "剧情镜头")["items"] == []
    assert catalog.search("backgrounds", "我的雨夜屋顶")["items"] == []
    assert catalog.search("backgrounds", "生成的咖啡馆")["items"] == []
    assert catalog.descriptor()["counts"]["backgrounds"] == 1
    with sqlite3.connect(catalog.path) as connection:
        kinds = dict(connection.execute("SELECT key,visual_kind FROM backgrounds"))
    assert kinds["BG_CS_Unlabeled"] == "cg"
    assert kinds["00013"] == "custom_background"
    assert kinds["01e31d07035932ab7ddedfeb9f120aea"] == "custom_background"


def test_catalog_merges_visual_labels_face_evidence_and_separate_user_overrides(tmp_path):
    base = tmp_path / "aa_assets.db"
    with sqlite3.connect(base) as connection:
        connection.executescript(
            """
            CREATE TABLE bg (name TEXT PRIMARY KEY, hash INTEGER, label TEXT, place TEXT, time TEXT, mood TEXT, tags TEXT, labeled_by TEXT);
            CREATE TABLE character (ident TEXT PRIMARY KEY, name TEXT, club TEXT, spine TEXT, source TEXT, avatar TEXT);
            CREATE TABLE character_variant (ident TEXT, spine_signature TEXT, outfit_key TEXT, spine TEXT);
            CREATE TABLE name_alias (script_name TEXT, ident TEXT, kind TEXT, uses INTEGER);
            CREATE TABLE face (ident TEXT, face_id TEXT, raw TEXT, label TEXT, label_cn TEXT, source TEXT, PRIMARY KEY (ident, face_id));
            CREATE TABLE face_evidence (ident TEXT, spine_signature TEXT, outfit_key TEXT, face_id TEXT, source TEXT, raw TEXT, label TEXT, label_cn TEXT, observed_count INTEGER);
            CREATE TABLE face_official_usage (ident TEXT, spine_signature TEXT, outfit_key TEXT, face_id TEXT, record_uid TEXT, text_cn TEXT, silent INTEGER, emoticons_json TEXT, actions_json TEXT, closeup INTEGER, source TEXT);
            CREATE TABLE face_visual_label (ident TEXT, spine_signature TEXT, outfit_key TEXT, face_id TEXT, model TEXT, primary_emotion TEXT, secondary_json TEXT, valence TEXT, arousal TEXT, eyes TEXT, brows TEXT, mouth TEXT, blush INTEGER, tears INTEGER, confidence REAL, description_cn TEXT, reviewed INTEGER, manual_json TEXT, semantic_json TEXT);
            CREATE TABLE expression_part (ident TEXT, spine_signature TEXT, outfit_key TEXT, kind TEXT, raw_name TEXT, labels_json TEXT, source TEXT);
            INSERT INTO bg VALUES ('BG_Roof', 1, 'Rooftop', '室外', '白天', '安静', '校园,屋顶', 'name');
            INSERT INTO character VALUES ('alice', '爱丽丝', '游戏开发部', 'alice-spine', 'official', 'alice-avatar.png');
            INSERT INTO character_variant VALUES ('alice', 'sig', '制服', 'alice-spine');
            INSERT INTO name_alias VALUES ('Alice', 'alice', 'portrait', 2);
            INSERT INTO face VALUES ('alice', '03', 'smile', 'smile', '微笑', 'atlas');
            INSERT INTO face_evidence VALUES ('alice', 'sig', '制服', '03', 'official', 'smile', 'smile', '微笑', 4);
            INSERT INTO face_official_usage VALUES ('alice', 'sig', '制服', '03', 'story:1', '你好', 0, '[]', '[]', 0, 'official_corpus');
            INSERT INTO face_visual_label VALUES ('alice', 'sig', '制服', '03', 'vision', 'joy', '["gentle"]', 'positive', 'low', 'open', 'relaxed', 'smile', 0, 0, .91, '轻柔微笑', 1, '{}', '{"tone":"warm"}');
            INSERT INTO expression_part VALUES ('alice', 'sig', '制服', 'eyes', 'eye_open', '["睁眼"]', 'atlas');
            """
        )
    overlay = tmp_path / "overlay.db"
    with sqlite3.connect(overlay) as connection:
        connection.executescript(
            """
            CREATE TABLE scene_visual_label (resource_channel TEXT, asset_key TEXT, content_sha256 TEXT, source_kind TEXT, model TEXT, visual_kind TEXT, label_json TEXT, evidence_json TEXT, confidence REAL, status TEXT, manual_json TEXT, updated_at TEXT);
            INSERT INTO scene_visual_label VALUES ('background','BG_Roof','','official','vision','background','{"label":"千年屋顶","description":"能看到校舍天际线的屋顶","place":"千年校舍屋顶","weather":"晴朗","season":"夏季","mood":"安静","indoor_outdoor":"outdoor","reuse_scope_cn":"通用","affiliation_names_cn":["千年"],"search_terms_cn":["天台","屋顶"],"tags":["校园"],"dialogue_suitable":true}', '{}', .96, 'ready', '{}', '2026-08-22');
            """
        )

    catalog = ResourceCatalog(tmp_path / "writing")
    result = catalog.import_legacy(base, overlay_paths=[overlay])

    assert result["imported"]["expression_parts"] == 1
    background = catalog.search("backgrounds", "天台")["items"][0]
    assert background["display_name"] == "千年屋顶"
    assert background["weather"] == "晴朗"
    assert background["affiliations"] == ["千年"]
    assert catalog.search("backgrounds", "晴朗")["items"][0]["technical"]["key"] == "BG_Roof"
    assert catalog.search("backgrounds", "室外")["items"][0]["technical"]["key"] == "BG_Roof"
    character = catalog.search("characters", "Alice")["items"][0]
    assert character["aliases"] == ["Alice"]
    assert character["outfits"] == [{"name": "制服", "face_count": 1}]
    face = catalog.search("faces", "爱丽丝")["items"][0]
    assert face["semantic"]["primary_emotion"] == "joy"
    assert face["evidence"]["official_usage_count"] == 1

    saved = catalog.save_override("background", background["technical"]["key"], {"display_name": "我常用的屋顶", "weather": "雨后"}, 0)
    assert saved["version"] == 1
    corrected = catalog.search("backgrounds", "天台")["items"][0]
    assert corrected["display_name"] == "我常用的屋顶"
    assert corrected["weather"] == "雨后"
    assert corrected["user_corrected"] is True
    with sqlite3.connect(base) as connection:
        assert connection.execute("SELECT label FROM bg WHERE name='BG_Roof'").fetchone()[0] == "Rooftop"


def test_background_lookup_prefers_chinese_annotation_for_case_variant_key(tmp_path):
    catalog = ResourceCatalog(tmp_path / "writing")
    with sqlite3.connect(catalog.path) as connection:
        connection.execute(
            """INSERT INTO backgrounds(key,display_name,label,visual_kind,source_version,updated_at)
               VALUES(?,?,?,?,?,?)""",
            ("BG_GameDevRoom", "Game Dev Room", "Game Dev Room", "background", "base", "2026-08-23"),
        )
        connection.execute(
            """INSERT INTO backgrounds(
                 key,display_name,label,place,indoor_outdoor,main_category,category_path,
                 annotation_json,visual_kind,source_version,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "bg_gamedevroom", "游戏开发部活动室", "游戏开发部活动室", "游戏开发部活动室",
                "indoor", "校园", "千年 / 校园 / 活动室", '{"subcategory":"活动室"}',
                "background", "annotation", "2026-08-23",
            ),
        )
        connection.commit()

    item = catalog.lookup("backgrounds", ["BG_GameDevRoom"])["items"][0]
    assert item["requested_key"] == "BG_GameDevRoom"
    assert item["display_name"] == "游戏开发部活动室"
    assert item["technical"]["key"] == "bg_gamedevroom"


def test_background_facets_only_expose_chinese_user_categories(tmp_path):
    catalog = ResourceCatalog(tmp_path / "writing")
    with sqlite3.connect(catalog.path) as connection:
        connection.executemany(
            """INSERT INTO backgrounds(
                 key,display_name,label,indoor_outdoor,main_category,category_path,
                 visual_kind,source_version,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            [
                ("BG_Classroom", "教室", "教室", "indoor", "校园", "千年 / 校园 / 教室", "background", "test", "2026-08-23"),
                ("BG_Road", "Road", "Road", "outdoor", "transport", "city / street", "background", "test", "2026-08-23"),
            ],
        )
        connection.commit()

    categories = catalog.facets("backgrounds")["categories"]
    labels = {item["label"] for item in categories}
    assert {"校园", "室内", "室外", "教室"} <= labels
    assert "transport" not in labels
    assert "street" not in labels


def test_095_identity_manifest_and_annotation_layers_are_retained(tmp_path):
    source = tmp_path / "aa_assets.db"
    with sqlite3.connect(source) as connection:
        connection.executescript(
            """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO meta VALUES ('assetdb_schema_version', '5');
            CREATE TABLE bg (name TEXT PRIMARY KEY, label TEXT, place TEXT, time TEXT, mood TEXT, tags TEXT, labeled_by TEXT);
            CREATE TABLE character (ident TEXT PRIMARY KEY, name TEXT, club TEXT, spine TEXT, avatar TEXT, source TEXT);
            CREATE TABLE character_variant (ident TEXT, spine_signature TEXT, outfit_key TEXT, spine TEXT);
            CREATE TABLE face_evidence (ident TEXT, spine_signature TEXT, outfit_key TEXT, face_id TEXT, source TEXT, raw TEXT, label TEXT, label_cn TEXT, observed_count INTEGER);
            CREATE TABLE face_visual_label (ident TEXT, spine_signature TEXT, outfit_key TEXT, face_id TEXT, model TEXT, primary_emotion TEXT, secondary_json TEXT, valence TEXT, arousal TEXT, eyes TEXT, brows TEXT, mouth TEXT, blush INTEGER, tears INTEGER, confidence REAL, description_cn TEXT, reviewed INTEGER, manual_json TEXT, semantic_json TEXT, observation_json TEXT, backend_json TEXT);
            CREATE TABLE scene_visual_label (resource_channel TEXT, asset_key TEXT, content_sha256 TEXT, source_kind TEXT, model TEXT, visual_kind TEXT, label_json TEXT, evidence_json TEXT, confidence REAL, status TEXT, manual_json TEXT, updated_at TEXT);
            INSERT INTO bg VALUES ('BG_Roof', 'Rooftop', '校园屋顶', 'day', '安静', '校园,屋顶', 'name');
            INSERT INTO character VALUES ('alice-db', 'Alice', '游戏开发部', 'characters/alice-spine', '', 'official');
            INSERT INTO character_variant VALUES ('alice-db', 'sig', '制服', 'characters/alice-spine');
            INSERT INTO face_evidence VALUES ('alice-db', 'sig', '制服', '03', 'official', 'smile', 'smile', '微笑', 4);
            INSERT INTO face_visual_label VALUES ('alice-db', 'sig', '制服', '03', 'gemini-3.7-flash', 'joy', '["gentle"]', 'positive', 'low', 'open', 'relaxed', 'smile', 0, 0, .93, '轻柔微笑', 1, '{"description":"人工确认"}', '{"tone":"warm"}', '{"source":"vision"}', '{"trace":"kept"}');
            INSERT INTO scene_visual_label VALUES ('background', 'BG_Roof', '', 'official', 'gemini-3.7-flash-scene-v5', 'background', '{"label":"千年屋顶","place":"千年校舍屋顶","subcategory":"屋顶","shot_type":"wide","search_terms_cn":["天台"]}', '{}', .96, 'ready', '{}', '2026-08-22');
            """
        )
    aliases = tmp_path / "character_aliases.json"
    aliases.write_text(json.dumps({"characters": [{"canonical_name": "爱丽丝", "aliases": ["Alice", "アリス"]}]}), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"CharacterOverrides": [{
        "Identifier": "alice-manifest",
        "Name": "爱丽丝",
        "Nickname": "游戏开发部",
        "SpinePortraitPath": "characters/alice-spine",
    }]}), encoding="utf-8")

    catalog = ResourceCatalog(tmp_path / "writing")
    result = catalog.import_legacy(source, "HaloCue 0.95 r17", character_aliases_path=aliases, manifest_path=manifest)

    assert result["imported"] == {"backgrounds": 1, "characters": 1, "variants": 1, "faces": 1, "expression_parts": 0}
    character = catalog.search("characters", "アリス")["items"][0]
    assert character["technical"]["key"] == "alice-manifest"
    assert character["canonical_name"] == "爱丽丝"
    assert character["manifest_bound"] is True
    assert character["user_custom"] is False
    assert character["outfits"] == [{"name": "制服", "face_count": 1}]

    face = catalog.search("faces", "爱丽丝")["items"][0]
    assert face["semantic"]["observation"] == {"source": "vision"}
    assert face["semantic"]["backend"] == {"trace": "kept"}
    assert face["semantic"]["manual"] == {"description": "人工确认"}
    background = catalog.search("backgrounds", "天台")["items"][0]
    assert background["annotation"]["subcategory"] == "屋顶"
    assert background["annotation"]["shot_type"] == "wide"

    with sqlite3.connect(source) as connection:
        assert connection.execute("SELECT COUNT(*) FROM character").fetchone()[0] == 1
        assert connection.execute("SELECT ident FROM character WHERE ident='alice-db'").fetchone()[0] == "alice-db"
