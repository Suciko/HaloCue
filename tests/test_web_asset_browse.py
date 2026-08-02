from pathlib import Path

import webui


def test_browse_filters_files_for_each_asset_kind(tmp_path):
    (tmp_path / "scene.png").write_bytes(b"png")
    (tmp_path / "scene.txt").write_text("story", encoding="utf-8")
    (tmp_path / "step.wav").write_bytes(b"wav")

    background = webui.browse(tmp_path, kind="background")
    sound = webui.browse(tmp_path, kind="sound")
    script = webui.browse(tmp_path, kind="script")

    assert [row["name"] for row in background["files"]] == ["scene.png"]
    assert [row["name"] for row in sound["files"]] == ["step.wav"]
    assert [row["name"] for row in script["files"]] == ["scene.txt"]


def test_character_browse_allows_selecting_current_spine_directory(tmp_path):
    character = tmp_path / "Kei"
    character.mkdir()
    (character / "kei.skel").write_bytes(b"skel")
    (character / "kei.atlas").write_text("kei.png\n", encoding="utf-8")

    result = webui.browse(character, kind="character")

    assert result["can_choose_directory"] is True
    assert result["selection_hint"] == "选择当前骨骼目录"
