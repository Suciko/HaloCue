# -*- coding: utf-8 -*-
import sys
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
