from pathlib import Path

import pytest

import script2aap
from background_requests import (
    UnresolvedBackgroundError,
    background_generation_prompt,
    collect_background_requests,
)


def test_background_request_parser_deduplicates_in_story_order():
    text = """
# 待生成自定义背景：傍晚的商店街可丽饼摊
凯伊：第一句
# 待生成自定义背景：纸箱堆放的游戏开发部角落
# 待生成自定义背景：傍晚的商店街可丽饼摊
"""

    assert collect_background_requests(text) == [
        "傍晚的商店街可丽饼摊",
        "纸箱堆放的游戏开发部角落",
    ]


def test_background_prompt_is_directly_usable_and_keeps_scene_description():
    prompt = background_generation_prompt("傍晚的商店街可丽饼摊，老师与凯伊约会")

    assert "傍晚的商店街可丽饼摊" in prompt
    assert "16:9" in prompt
    assert "不要出现人物" in prompt
    assert "文字" in prompt
    assert "视觉小说" in prompt


def test_install_is_blocked_before_aa_paths_when_background_is_unresolved(tmp_path):
    script = tmp_path / "story.txt"
    script.write_text(
        "# 待生成自定义背景：傍晚的商店街可丽饼摊\n凯伊：测试",
        encoding="utf-8",
    )

    with pytest.raises(UnresolvedBackgroundError, match="傍晚的商店街可丽饼摊"):
        script2aap.main(
            [
                str(script),
                "--install",
                "--aa-data",
                str(tmp_path / "missing-aa-data"),
            ]
        )

    assert not (tmp_path / "missing-aa-data").exists()
