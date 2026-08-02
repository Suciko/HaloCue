# -*- coding: utf-8 -*-
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from document import (
    parse_document_lossless,
    serialize_document,
    compile_document,
    DocNode,
)
from script2aap import parse_script, load_cast


def test_background_request_parsing():
    sample = (
        "# 待生成自定义背景：雨夜车站\n"
        "# 待生成自定义背景 : 阳光海滩\n"
        " # 待生成自定义背景: 商店街  \n"
        "# 普通标题\n"
    )
    nodes = parse_document_lossless(sample)
    assert len(nodes) == 4
    assert nodes[0].kind == "background_request"
    assert nodes[0].fields["description"] == "雨夜车站"
    assert nodes[1].kind == "background_request"
    assert nodes[1].fields["description"] == "阳光海滩"
    assert nodes[2].kind == "background_request"
    assert nodes[2].fields["description"] == "商店街"
    assert nodes[3].kind == "title"
    assert nodes[3].fields["title"] == "普通标题"


def test_golden_roundtrip_bytes():
    files = [
        HERE / "out" / "AA_Kei_Date_Semantic_20260730_v4.annotated.txt",
        HERE / "out" / "AA_本日行程_凯伊约会服_20260728.annotated.txt",
    ]
    for filepath in files:
        if not filepath.is_file():
            continue
        original_text = filepath.read_text(encoding="utf-8")
        nodes = parse_document_lossless(original_text)
        serialized = serialize_document(nodes)
        assert serialized == original_text, f"Roundtrip bytes mismatch for {filepath.name}"


def test_raw_directive_is_dir_node():
    sample = "@raw #任意指令 参数"
    nodes = parse_document_lossless(sample)
    assert len(nodes) == 1
    assert nodes[0].kind == "dir"
    assert nodes[0].fields["cmd"] == "raw"
    assert nodes[0].fields["arg"] == "#任意指令 参数"


def test_unbound_actor_line_preserved_with_error_diagnostic():
    sample = (
        "## 场景1\n"
        "未注册演员: 你好世界\n"
    )
    cast = {"凯伊": {"id": "kei"}}
    nodes = parse_document_lossless(sample)
    assert len(nodes) == 2
    assert nodes[1].kind == "line"
    assert nodes[1].fields["who"] == "未注册演员"

    events, diagnostics = compile_document(nodes, cast, {})
    assert any(d["code"] == "actor.unbound" and d["severity"] == "error" for d in diagnostics)
    # 未绑定演员的台词在 compile_document 中不产生 line 事件
    line_events = [e for e in events if e.get("k") == "line"]
    assert len(line_events) == 0


def test_parse_script_equivalence():
    sample_path = HERE / "out" / "AA_Kei_Date_Semantic_20260730_v4.annotated.txt"
    if not sample_path.is_file():
        pytest.skip("Sample file missing")
    cast_path = HERE / "cast.json"
    if not cast_path.is_file():
        pytest.skip("cast.json missing")
    _, cast, _ = load_cast(str(cast_path))
    events = parse_script(str(sample_path), cast)
    assert isinstance(events, list)
    assert len(events) > 0
