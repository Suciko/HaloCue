# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from annotate import annotate_script
from llm import MockProvider


def test_annotate_script_generates_model_and_postprocessor_proposals(
    tmp_path, empty_llm_config_path
):
    script = tmp_path / "scene.txt"
    script.write_text("Kai: hello\n", encoding="utf-8")

    cast = tmp_path / "cast.json"
    cast.write_text(
        json.dumps(
            {
                "default_bg": "BG_Black",
                "default_bgm": 0,
                "scene_bg": {},
                "cast": {"Kai": {"id": "kai", "portrait": True}},
                "alias": {},
            }
        ),
        encoding="utf-8",
    )

    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            {
                "bg": {"BG_Black": 1},
                "sounds": ["SE_FootStep_01"],
                "characters": [{"identifier": "kai", "faces": [{"id": "00", "raw": "00", "label": "", "cn": ""}]}],
                "enums": {
                    "emoticon": {"1": {"sym": "[!]", "cn": "惊讶"}},
                    "action": {"6": {"verb": "jump", "cn": "跳跃"}},
                },
            }
        ),
        encoding="utf-8",
    )

    output = tmp_path / "annotated.txt"

    # Mock 模型返回一个合法和一个非法提议
    mock_res = {
        "lines": [
            {
                "i": 0,
                "face": "00",
                "emo": "惊讶",
                "se": "SE_FootStep_01",
                "act": "invalid_action_name",  # 越界非法提议 -> 应触发 suggested_fix
            }
        ]
    }

    opts = {
        "script": str(script),
        "out": str(output),
        "cast": str(cast),
        "index": str(index),
        "llm": str(empty_llm_config_path),
    }

    res = annotate_script(opts, provider_instance=MockProvider(mock_res))
    proposals = res.get("proposals", [])

    # 验证 proposals 管道
    assert isinstance(proposals, list)
    assert len(proposals) > 0

    # 1. 验证包含 applied_pending 类型的合法提案
    applied_props = [p for p in proposals if p["type"] == "applied_pending"]
    assert len(applied_props) > 0
    assert any(p["field"] == "face" for p in applied_props)

    # 2. 验证包含 suggested_fix 类型的越界/拒绝提案
    suggested_props = [p for p in proposals if p["type"] == "suggested_fix"]
    assert len(suggested_props) > 0
    assert any(p["field"] == "act" for p in suggested_props)
