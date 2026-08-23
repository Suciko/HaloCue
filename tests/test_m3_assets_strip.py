# -*- coding: utf-8 -*-
import sys
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
import assetdb
import webui
from webui import list_backgrounds, list_characters, search_sounds


def test_asset_strip_api_endpoints(monkeypatch, tmp_path):
    monkeypatch.setitem(webui.CFG, "overrides", str(tmp_path))
    chars = list_characters(q="凯")
    assert isinstance(chars, list)

    bgs = list_backgrounds(q="BG", only_ready=False)
    assert isinstance(bgs, list)

    sounds = search_sounds(q="SE")
    assert isinstance(sounds, list)


def test_background_picker_returns_a_bounded_first_page_with_distinct_variants(monkeypatch, tmp_path):
    database = tmp_path / "assets.db"
    monkeypatch.setattr(webui, "DB", str(database))
    con = assetdb.connect(database)
    rows = [
        (f"BG_Room_{index:03d}", index + 1, f"Room {index:03d}", "room")
        for index in range(100)
    ]
    rows.append(("BG_Room_010_Variant", 9999, "Room 010", "room"))
    con.executemany(
        "INSERT INTO bg(name,hash,label,tags) VALUES(?,?,?,?)",
        rows,
    )
    con.commit()
    con.close()

    backgrounds = list_backgrounds(only_ready=True)

    names = [item["name"] for item in backgrounds]
    assert len(backgrounds) == 80
    assert len(names) == len(set(names))
    room_variants = [item for item in backgrounds if item["label"] == "Room 010"]
    assert {item["name"] for item in room_variants} == {
        "BG_Room_010", "BG_Room_010_Variant",
    }
    assert all(item["disambiguate"] for item in room_variants)


def test_background_picker_supports_non_overlapping_pages_with_total(monkeypatch, tmp_path):
    database = tmp_path / "assets.db"
    monkeypatch.setattr(webui, "DB", str(database))
    con = assetdb.connect(database)
    con.executemany(
        "INSERT INTO bg(name,hash,label,tags) VALUES(?,?,?,?)",
        [
            (f"BG_Place_{index:03d}", index + 1, f"Place {index:03d}", "place")
            for index in range(125)
        ],
    )
    con.commit()
    con.close()

    first = list_backgrounds(only_ready=True, limit=80, with_total=True)
    second = list_backgrounds(only_ready=True, limit=80, offset=80, with_total=True)

    assert first["total"] == 125
    assert first["offset"] == 0
    assert first["limit"] == 80
    assert first["has_more"] is True
    assert len(first["items"]) == 80
    assert second["total"] == 125
    assert second["offset"] == 80
    assert second["has_more"] is False
    assert len(second["items"]) == 45
    assert {item["name"] for item in first["items"]}.isdisjoint(
        item["name"] for item in second["items"]
    )


@pytest.mark.parametrize(
    ("query", "expected"),
    [("天台", "BG_Rooftop"), ("黄昏", "BG_Rooftop"), ("宁静", "BG_Rooftop")],
)
def test_background_picker_searches_scene_metadata(monkeypatch, tmp_path, query, expected):
    database = tmp_path / "assets.db"
    monkeypatch.setattr(webui, "DB", str(database))
    con = assetdb.connect(database)
    con.execute(
        """INSERT INTO bg(name,hash,label,place,time,mood,tags)
        VALUES(?,?,?,?,?,?,?)""",
        ("BG_Rooftop", 101, "School Roof", "天台", "黄昏", "宁静", "school"),
    )
    con.commit()
    con.close()

    rows = list_backgrounds(q=query, only_ready=True)

    assert [row["name"] for row in rows] == [expected]


def test_background_picker_uses_new_categories_and_hides_confirmed_cg(monkeypatch, tmp_path):
    database = tmp_path / "assets.db"
    monkeypatch.setattr(webui, "DB", str(database))
    con = assetdb.connect(database)
    import asset_catalog
    asset_catalog.migrate(con)
    con.executemany(
        "INSERT INTO bg(name,hash,label) VALUES(?,?,?)",
        [
            ("BG_Classroom", 1, "旧教室名"),
            ("BG_CS_Event", 2, "事件图"),
        ],
    )
    rows = [
        ("BG_Classroom", "background", {
            "visual_kind": "background", "label": "清晨教室",
            "description": "带课桌的空教室", "main_category": "campus",
            "subcategory": "教室", "dialogue_suitable": True,
            "staging_capacity": "group", "tags": ["课桌"],
        }),
        ("BG_CS_Event", "cg", {
            "visual_kind": "cg", "label": "争执特写",
            "description": "两人争执的固定构图", "main_category": "event",
            "subcategory": "争执场面", "dialogue_suitable": False,
            "tags": ["争执"],
        }),
    ]
    for key, visual_kind, labels in rows:
        con.execute(
            """
            INSERT INTO scene_visual_label
              (resource_channel,asset_key,content_sha256,source_kind,model,
               visual_kind,label_json,confidence,status)
            VALUES ('background',?,?,'extra_pack','current',?,?,.9,'ready')
            """,
            (key, key, visual_kind, json.dumps(labels, ensure_ascii=False)),
        )
    con.commit()
    con.close()

    campus = list_backgrounds(q="校园", only_ready=True)
    all_rows = list_backgrounds(only_ready=True)

    assert [row["name"] for row in campus] == ["BG_Classroom"]
    assert campus[0]["subcategory"] == "教室"
    assert [row["name"] for row in all_rows] == ["BG_Classroom"]


def test_background_picker_searches_every_scene_label_field(monkeypatch, tmp_path):
    database = tmp_path / "assets.db"
    monkeypatch.setattr(webui, "DB", str(database))
    con = assetdb.connect(database)
    con.execute(
        "INSERT INTO bg(name,hash,label) VALUES(?,?,?)",
        ("BG_Labelled", 77, "普通名称"),
    )
    labels = {
        "visual_kind": "background", "label": "普通名称",
        "description": "可持续对白的空间", "main_category": "interior",
        "subcategory": "资料室", "dialogue_suitable": True,
        "staging_capacity": "pair", "tags": ["静谧"],
        "search_terms_cn": ["档案室", "书库"],
        "affiliation_keys": ["millennium"],
        "affiliation_names_cn": ["千年"],
        "category_path_cn": "千年 / 室内 / 资料室",
    }
    con.execute(
        """INSERT INTO scene_visual_label
          (resource_channel,asset_key,content_sha256,source_kind,model,
           visual_kind,label_json,confidence,status)
          VALUES ('background',?,?,?,?,?,?,.9,'ready')""",
        ("BG_Labelled", "hash", "extra_pack", "current", "background",
         json.dumps(labels, ensure_ascii=False)),
    )
    con.commit()
    con.close()

    assert [row["name"] for row in list_backgrounds(q="书库", only_ready=True)] == ["BG_Labelled"]
    assert [row["name"] for row in list_backgrounds(q="千年", only_ready=True)] == ["BG_Labelled"]


def test_background_picker_filters_source_and_scene_facets(monkeypatch, tmp_path):
    database = tmp_path / "assets.db"
    monkeypatch.setattr(webui, "DB", str(database))
    con = assetdb.connect(database)
    import asset_catalog
    asset_catalog.migrate(con)
    con.executemany(
        "INSERT INTO bg(name,hash,label) VALUES(?,?,?)",
        [("BG_Official", 1001, "校园教室"), ("BG_Custom", 1002, "校园教室")],
    )
    con.execute(
        """INSERT INTO asset_install
           (scope,kind,aa_key,display_name,source_path,sha256,status,install_path,metadata_json)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (str(tmp_path / "project"), "background", "1002", "校园教室",
         str(tmp_path / "custom.png"), "digest", "registered",
         str(tmp_path / "custom.png"), "{}"),
    )
    labels = {
        "visual_kind": "background", "label": "校园教室",
        "main_category": "campus", "subcategory": "教室",
        "indoor_outdoor": "indoor", "time": "dawn", "weather": "sunny",
        "dialogue_suitable": True,
    }
    for key in ("BG_Official", "BG_Custom"):
        con.execute(
            """INSERT INTO scene_visual_label
              (resource_channel,asset_key,content_sha256,source_kind,model,
               visual_kind,label_json,confidence,status)
              VALUES ('background',?,?,?,?,?,?,.9,'ready')""",
            (key, key, "extra_pack", "current", "background", json.dumps(labels, ensure_ascii=False)),
        )
    con.commit()
    con.close()

    official = list_backgrounds(only_ready=True, source_filter="official", category="教室", space="indoor")
    custom = list_backgrounds(only_ready=True, source_filter="custom", time_filter="dawn", weather="sunny")

    assert [row["name"] for row in official] == ["BG_Official"]
    assert [row["name"] for row in custom] == ["BG_Custom"]
    assert custom[0]["source"] == "custom"
