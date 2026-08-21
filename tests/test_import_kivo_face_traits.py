import sqlite3

from tools.import_kivo_face_traits import (
    extract_visual_traits,
    import_kivo_traits,
    parse_asset_face_key,
)


def test_parse_asset_face_key_supports_official_and_downloaded_names():
    assert parse_asset_face_key("aris_spr_99") == ("aris", "99")
    assert parse_asset_face_key("kirino_spr-00_0_waifu2x_2x_1n_png") == (
        "kirino", "00"
    )
    assert parse_asset_face_key("NP0236_spr_Eye_Close_01") is None


def test_extract_visual_traits_keeps_observation_separate_from_emotion():
    assert extract_visual_traits("闭着眼睛嘴角微扬，看起来很满足") == {
        "eyes": "闭眼",
        "mouth": "嘴角上扬",
    }
    assert extract_visual_traits("眼睛微眯嘴巴微张，看起来有点无奈") == {
        "eyes": "半闭眼",
        "mouth": "微张嘴",
    }


def test_import_kivo_traits_is_dry_run_by_default_and_only_fills_blanks():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE character_variant(
          ident TEXT, spine_signature TEXT, outfit_key TEXT, spine TEXT
        );
        CREATE TABLE face_visual_label(
          ident TEXT, spine_signature TEXT, outfit_key TEXT, face_id TEXT,
          model TEXT, eyes TEXT, mouth TEXT
        );
        INSERT INTO character_variant VALUES(
          'aris','sig','CharacterSpine_aris_noweapon',''
        );
        INSERT INTO face_visual_label VALUES(
          'aris','sig','CharacterSpine_aris_noweapon','99','vision','',''
        );
        """
    )
    source = {
        "1_天童爱丽丝": {
            "初始立绘差分": {
                "aris_spr_99": "闭着眼睛嘴角微扬，看起来很满足"
            }
        }
    }

    dry = import_kivo_traits(con, source)
    untouched = con.execute(
        "SELECT eyes,mouth FROM face_visual_label"
    ).fetchone()
    assert dry["matched_faces"] == 1
    assert dry["updated_rows"] == 0
    assert tuple(untouched) == ("", "")

    applied = import_kivo_traits(con, source, apply=True)
    updated = con.execute("SELECT eyes,mouth FROM face_visual_label").fetchone()
    assert applied["updated_rows"] == 1
    assert tuple(updated) == ("闭眼", "嘴角上扬")
