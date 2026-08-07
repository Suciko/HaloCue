# -*- coding: utf-8 -*-
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from diagnostics import (
    DIAGNOSTIC_CODES,
    create_diagnostic,
    validate_script_diagnostics,
)
from document import DocNode, compile_document


def test_diagnostic_codes_registry():
    expected_codes = {
        "actor.unbound",
        "line.unparsable",
        "dir.unknown",
        "dir.argument_error",
        "face.invalid",
        "bg.unregistered",
        "sound.unregistered",
        "actor.portrait_fields_ignored",
        "move.position_invalid",
        "bg.request_unresolved",
        "cast.overflow_warning",
        "shot.target_offscreen",
    }
    assert expected_codes.issubset(set(DIAGNOSTIC_CODES.keys()))


def test_blank_node_is_reported_but_separator_is_not():
    nodes = [
        DocNode(kind="blank", raw="\n", line_no=2, fields={}),
        DocNode(
            kind="separator",
            raw="---\n",
            line_no=3,
            fields={"marker": "---"},
        ),
    ]

    diagnostics = validate_script_diagnostics(
        nodes, {"旁白": {"narrator": True}}, {}
    )

    assert any(
        item["code"] == "draft.blank_node" and item["line_no"] == 2
        for item in diagnostics
    )
    assert not any(item["line_no"] == 3 for item in diagnostics)


def test_all_diagnostic_codes_triggered():
    cast = {"凯伊": {"id": "kei"}}
    assets = {
        "bg": {"BG_Room": 1},
        "sounds": ["SE_Door"],
    }

    # 1. actor.unbound & line.unparsable & bg.request_unresolved
    nodes = [
        DocNode(kind="line", raw="未知人: 你好", line_no=1, fields={"who": "未知人", "text": "你好"}),
        DocNode(kind="unknown", raw="???无法解析???", line_no=2, fields={}),
        DocNode(kind="background_request", raw="# 待生成自定义背景：海滩", line_no=3, fields={"description": "海滩"}),
    ]
    _, diags = compile_document(nodes, cast, assets)
    codes = [d["code"] for d in diags]
    assert "actor.unbound" in codes
    assert "line.unparsable" in codes
    assert "bg.request_unresolved" in codes

    # 检查 severities
    for d in diags:
        assert d["severity"] == "error"

    # 2. validate_script_diagnostics 校验高级指令
    test_cases = [
        (DocNode(kind="dir", raw="@bg 未知背景", line_no=4, fields={"cmd": "bg", "arg": "未知背景"}), "bg.unregistered", "error"),
        (DocNode(kind="dir", raw="@se 未知音效", line_no=5, fields={"cmd": "se", "arg": "未知音效"}), "sound.unregistered", "error"),
        (DocNode(kind="dir", raw="@move 凯伊 99", line_no=6, fields={"cmd": "move", "arg": "凯伊 99"}), "move.position_invalid", "error"),
        (DocNode(kind="dir", raw="@unknowncmd 123", line_no=7, fields={"cmd": "unknowncmd", "arg": "123"}), "dir.unknown", "error"),
        (DocNode(kind="dir", raw="@wait ABC", line_no=8, fields={"cmd": "wait", "arg": "ABC"}), "dir.argument_error", "error"),
        (DocNode(kind="line", raw="旁白(99): 说话", line_no=9, fields={"who": "旁白", "text": "说话", "face": "99"}), "actor.portrait_fields_ignored", "error"),
        (DocNode(kind="line", raw="凯伊(非法表情ID): 说话", line_no=10, fields={"who": "凯伊", "text": "说话", "face": "非法表情ID"}), "face.invalid", "error"),
    ]

    for node, expected_code, expected_severity in test_cases:
        cast_with_narrator = {"凯伊": {"id": "kei"}, "旁白": {"id": "旁白", "narrator": True}}
        d_list = validate_script_diagnostics([node], cast_with_narrator, assets)
        found = [d for d in d_list if d["code"] == expected_code]
        assert len(found) > 0, f"Expected code {expected_code} for node {node.raw}"
        assert found[0]["severity"] == expected_severity


def test_warning_diagnostics():
    cast = {f"角色{i}": {"id": f"c{i}"} for i in range(1, 7)}
    nodes = [
        DocNode(kind="dir", raw="@stage 角色1@1 角色2@2 角色3@3 角色4@4 角色5@5 角色6@6", line_no=1, fields={"cmd": "stage", "arg": "角色1@1 角色2@2 角色3@3 角色4@4 角色5@5 角色6@6"}),
        DocNode(kind="dir", raw="@shot 场外角色", line_no=2, fields={"cmd": "shot", "arg": "场外角色"}),
    ]
    diags = validate_script_diagnostics(nodes, cast, {}, active_on_stage={"角色1"})
    codes = [d["code"] for d in diags]
    assert "cast.overflow_warning" in codes
    assert "shot.target_offscreen" in codes
    for d in diags:
        if d["code"] in ("cast.overflow_warning", "shot.target_offscreen"):
            assert d["severity"] == "warning"
