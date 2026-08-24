from __future__ import annotations

import re
from pathlib import Path


RUNTIME = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "desktop-client"
    / "scene-preview"
    / "aa-runtime.js"
)


def _runtime_source() -> str:
    return RUNTIME.read_text(encoding="utf-8")


def test_runtime_keeps_authorized_aa_five_slot_coordinates_and_layout_evidence():
    source = _runtime_source()

    assert "[-925, -435, 0, 435, 925]" in source
    assert "container: Object.freeze({ x: 0, y: -832 })" in source
    assert "name: Object.freeze({ x: -1189.9999, y: 426 })" in source
    assert "text: Object.freeze({ x: -1184, y: 321 })" in source
    assert "textBackground: Object.freeze({ x: 0, y: 272, rotation: -90 })" in source


def test_runtime_exposes_aa_character_operations_without_decompiled_csharp():
    source = _runtime_source()

    for name in (
        "setPos",
        "setLuminance",
        "setOnTop",
        "setCloseup",
        "moveAnimation",
        "fadeAnimation",
        "hideAnimation",
        "queueTypewriter",
    ):
        assert re.search(rf"\b{name}\s*\(", source)
    assert "global.HaloCueAARuntime" in source
    assert "public class Character" not in source


def test_runtime_records_observed_aa_defaults():
    source = _runtime_source()

    assert "const MOVE_DURATION_MS = 500;" in source
    assert "const STANDBY_LUMINANCE_MULTIPLIER = 0.6;" in source
    assert 'easing: "ease-in-out-cubic"' in source
    assert "TYPEWRITER_PUNCTUATION_PAUSE_FRAMES = 3" in source
    assert "TYPEWRITER_NEWLINE_PAUSE_FRAMES = 6" in source
