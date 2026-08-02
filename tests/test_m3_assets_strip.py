# -*- coding: utf-8 -*-
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
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
