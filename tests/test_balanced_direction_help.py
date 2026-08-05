from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_help_drawer_shows_the_ai_friendly_screenplay_example_and_guidance():
    html = (ROOT / "ui.html").read_text(encoding="utf-8")
    start = html.index("<h3>推荐剧本写法</h3>")
    end = html.index("<h3>自定义素材怎么导入</h3>", start)
    section = html[start:end]

    assert html.count('id="helpDrawer"') == 1
    for phrase in (
        "## 场景一：商店街，午后",
        "一行一个角色",
        "真实动作和位置变化",
        "不要为了触发演出",
        "无需手工填写 Steam",
        "审查草稿",
    ):
        assert phrase in section


def test_help_example_wraps_on_narrow_viewports():
    html = (ROOT / "ui.html").read_text(encoding="utf-8")
    css = (ROOT / "css" / "layout.css").read_text(encoding="utf-8")

    assert 'class="help-example"' in html
    assert ".help-example" in css
    assert "white-space:pre-wrap" in css
    assert "overflow-wrap:anywhere" in css


def test_markdown_guides_explain_the_same_screenplay_evidence():
    guides = [
        (ROOT / "使用说明-从这里开始.md").read_text(encoding="utf-8"),
        (ROOT / "README.md").read_text(encoding="utf-8"),
    ]

    for guide in guides:
        for phrase in (
            "## 场景一：商店街，午后",
            "一行一个角色",
            "真实动作",
            "位置变化",
            "不要为了触发演出",
            "审查草稿",
        ):
            assert phrase in guide
