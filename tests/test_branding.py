from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VISIBLE_LEGACY_HEADING = "AA 自动写剧本"


def test_public_entrypoints_do_not_show_the_legacy_product_heading():
    for filename in ("launcher.py", "webui.py", "ui.html"):
        source = (ROOT / filename).read_text(encoding="utf-8")
        assert VISIBLE_LEGACY_HEADING not in source


def test_ui_shows_the_halocue_release_name_and_chinese_subtitle():
    source = (ROOT / "ui.html").read_text(encoding="utf-8")

    assert "<title>HaloCue 0.9 Beta</title>" in source
    assert "<h1 id=\"viewTitle\">HaloCue 0.9 Beta</h1>" in source
    assert "AzureArchive 剧情演出工具" in source
