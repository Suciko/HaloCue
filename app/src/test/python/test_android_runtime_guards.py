import pytest

from android_runtime_guard import AndroidCapabilityUnavailable
from install_manager import InstallManager
from spine_face_analysis import analyze_character_faces, resolve_spine_cli
from spine_face_renderer import render_face_variations


def test_direct_aa_install_is_disabled():
    manager = InstallManager()
    with pytest.raises(AndroidCapabilityUnavailable, match="direct_aa_install"):
        manager.install_options(token="draft", build_id="build")
    with pytest.raises(AndroidCapabilityUnavailable, match="direct_aa_install"):
        manager.install_build(token="draft", build_id="build")


def test_spine_cli_and_rendering_are_disabled():
    assert resolve_spine_cli("Spine.com") is None
    with pytest.raises(AndroidCapabilityUnavailable, match="spine_rendering"):
        analyze_character_faces()
    with pytest.raises(AndroidCapabilityUnavailable, match="spine_rendering"):
        render_face_variations()
