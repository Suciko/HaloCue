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


def test_background_picker_returns_a_bounded_unique_first_page(monkeypatch, tmp_path):
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
    labels = [item["label"] for item in backgrounds]
    assert len(backgrounds) == 80
    assert len(labels) == len(set(label.casefold() for label in labels))
    assert sum(label == "Room 010" for label in labels) == 1
