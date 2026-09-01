from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VISIBLE_LEGACY_HEADING = "AA 自动写剧本"


def test_public_entrypoints_do_not_show_the_legacy_product_heading():
    for filename in ("launcher.py", "webui.py", "ui.html"):
        source = (ROOT / filename).read_text(encoding="utf-8")
        assert VISIBLE_LEGACY_HEADING not in source


def test_ui_shows_the_halocue_release_name_and_chinese_subtitle():
    source = (ROOT / "ui.html").read_text(encoding="utf-8")

    assert "<title>HaloCue 1.0.0</title>" in source
    assert "<h1 id=\"viewTitle\">剧情工作台</h1>" in source
    assert "HaloCue 1.0.0" in source
