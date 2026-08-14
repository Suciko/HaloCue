from pathlib import Path

from spine_face_web_renderer import (
    RUNTIME_38,
    RUNTIME_42,
    detect_spine_version,
    runtime_for_spine_version,
)


def test_detect_spine_version_reads_embedded_editor_version(tmp_path):
    skeleton = tmp_path / "character.skel"
    skeleton.write_bytes(b"\x00hash\x00spine 4.2.33\x00payload")

    assert detect_spine_version(skeleton) == "4.2.33"


def test_detect_spine_version_returns_empty_for_unknown_binary(tmp_path):
    skeleton = tmp_path / "character.skel"
    skeleton.write_bytes(b"not a spine skeleton")

    assert detect_spine_version(skeleton) == ""


def test_runtime_selection_matches_installed_spine_data_version():
    assert runtime_for_spine_version("3.8.76") == RUNTIME_38
    assert runtime_for_spine_version("3.8965") == RUNTIME_38
    assert runtime_for_spine_version("4.2.33") == RUNTIME_42
