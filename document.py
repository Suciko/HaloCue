# -*- coding: utf-8 -*-
"""
AA 剧本编译器 - 无损文档模型 (document.py)
实现两层解析：
1. parse_document_lossless: 逐行建节点，无损保存原始文本与 BOM/CRLF
2. compile_document: 可编译节点转事件，产生结构化诊断 (diagnostics)
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from diagnostics import validate_script_diagnostics

HEAD_RE = re.compile(r"^(?P<head>[^:：]{1,40}?)\s*[:：]\s*(?P<text>.*)$")
ANNO_RE = re.compile(
    r"^(?P<who>.*?)"
    r"(?:[（(](?P<face>[^）)]*)[）)])?"
    r"(?:\[(?P<emo>[^\]]*)\])?"
    r"(?:\{(?P<act>[^}]*)\})?"
    r"(?:<(?P<fx>[^>]*)>)?$"
)
BG_REQ_RE = re.compile(r"^\s*#\s*待生成自定义背景\s*[:：]\s*(?P<desc>.+?)\s*$")
DIR_RE = re.compile(r"^@(?P<cmd>\w+)\s*(?P<arg>.*)$")


def split_head(head: str, cast: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]:
    """冒号前的部分 -> 角色 + 演出标注。
    先整体匹配演员表（支持「凯伊（消息）」这类变体名），失败再剥标注。
    复用 script2aap.py 的同名实现逻辑。
    """
    head = head.strip()
    if head in cast:
        return head, None, None, None, None
    m = ANNO_RE.match(head)
    if not m:
        return head, None, None, None, None
    who, face = m.group("who").strip(), m.group("face")
    if face and not re.fullmatch(r"[A-Za-z0-9_]+", face.strip()):
        face = None
    return who, face, m.group("emo"), m.group("act"), m.group("fx")


@dataclass
class DocNode:
    kind: str  # background_request | scene | title | dir | line | meta | blank | unknown
    raw: str  # 整行原文（含 BOM, 缩进, 冒号格式, eol）
    line_no: int
    fields: Dict[str, Any] = field(default_factory=dict)
    dirty: bool = False
    eol: str = "\n"


def parse_document_lossless(text: str) -> List[DocNode]:
    """逐行建节点，保留原文、缩进、全角冒号及换行符，实现无损解析。"""
    nodes = []
    # 使用 splitlines(keepends=True) 保留原始换行符
    lines = text.splitlines(keepends=True)

    for idx, raw_line in enumerate(lines, 1):
        # 剥离换行符，保留在 node.eol 中
        if raw_line.endswith("\r\n"):
            line_body = raw_line[:-2]
            eol = "\r\n"
        elif raw_line.endswith("\n"):
            line_body = raw_line[:-1]
            eol = "\n"
        elif raw_line.endswith("\r"):
            line_body = raw_line[:-1]
            eol = "\r"
        else:
            line_body = raw_line
            eol = ""

        # 去除 BOM 后做正则判断，但 raw 依然保留完整的 raw_line
        stripped_body = line_body.lstrip("﻿")
        s = stripped_body.strip()

        # 1. background_request (必须在 title 之前判定)
        m_bg = BG_REQ_RE.match(stripped_body)
        if m_bg:
            nodes.append(
                DocNode(
                    kind="background_request",
                    raw=raw_line,
                    line_no=idx,
                    fields={"description": m_bg.group("desc").strip()},
                    eol=eol,
                )
            )
            continue

        # 2. scene (## 开头)
        if stripped_body.startswith("##"):
            scene_title = stripped_body[2:].strip()
            nodes.append(
                DocNode(
                    kind="scene",
                    raw=raw_line,
                    line_no=idx,
                    fields={"title": scene_title},
                    eol=eol,
                )
            )
            continue

        # 3. title (# 开头)
        if stripped_body.startswith("#"):
            title_text = stripped_body[1:].strip()
            nodes.append(
                DocNode(
                    kind="title",
                    raw=raw_line,
                    line_no=idx,
                    fields={"title": title_text},
                    eol=eol,
                )
            )
            continue

        # 4. dir (@cmd arg，包括 @raw)
        if stripped_body.startswith("@"):
            m_dir = DIR_RE.match(stripped_body)
            if m_dir:
                cmd = m_dir.group("cmd").lower()
                arg = m_dir.group("arg").strip()
                nodes.append(
                    DocNode(
                        kind="dir",
                        raw=raw_line,
                        line_no=idx,
                        fields={"cmd": cmd, "arg": arg},
                        eol=eol,
                    )
                )
            else:
                nodes.append(
                    DocNode(
                        kind="unknown",
                        raw=raw_line,
                        line_no=idx,
                        fields={"raw_dir": stripped_body},
                        eol=eol,
                    )
                )
            continue

        # 5. meta (> 开头)
        if stripped_body.startswith(">"):
            nodes.append(
                DocNode(
                    kind="meta",
                    raw=raw_line,
                    line_no=idx,
                    fields={"text": stripped_body[1:].strip()},
                    eol=eol,
                )
            )
            continue

        # 6. blank
        if not s:
            nodes.append(
                DocNode(
                    kind="blank",
                    raw=raw_line,
                    line_no=idx,
                    fields={},
                    eol=eol,
                )
            )
            continue

        # 7. line (说话人(face)[emo]{act}<fx>: 台词)
        m_head = HEAD_RE.match(stripped_body)
        if m_head:
            who, face, emo, act, fx = split_head(m_head.group("head"), {})
            nodes.append(
                DocNode(
                    kind="line",
                    raw=raw_line,
                    line_no=idx,
                    fields={
                        "who": who,
                        "text": m_head.group("text").strip(),
                        "face": face,
                        "emo": emo,
                        "act": act,
                        "fx": fx,
                    },
                    eol=eol,
                )
            )
            continue

        # 8. unknown
        nodes.append(
            DocNode(
                kind="unknown",
                raw=raw_line,
                line_no=idx,
                fields={},
                eol=eol,
            )
        )

    return nodes


def serialize_document(nodes: List[DocNode]) -> str:
    """序列化文档节点。未编辑节点 (dirty=False) 原样输出 raw，保留逐字节一致性。"""
    out_parts = []
    for node in nodes:
        if not node.dirty:
            out_parts.append(node.raw)
        else:
            # dirty 节点重新构建
            k = node.kind
            f = node.fields
            eol = node.eol
            if k == "background_request":
                out_parts.append(f"# 待生成自定义背景：{f.get('description', '')}{eol}")
            elif k == "scene":
                out_parts.append(f"## {f.get('title', '')}{eol}")
            elif k == "title":
                out_parts.append(f"# {f.get('title', '')}{eol}")
            elif k == "dir":
                cmd = f.get("cmd", "")
                arg = f.get("arg", "")
                out_parts.append(f"@{cmd} {arg}".strip() + eol)
            elif k == "line":
                who = f.get("who", "")
                face = f"({f['face']})" if f.get("face") else ""
                emo = f"[{f['emo']}]" if f.get("emo") else ""
                act = f"{{{f['act']}}}" if f.get("act") else ""
                fx = f"<{f['fx']}>" if f.get("fx") else ""
                text = f.get("text", "")
                out_parts.append(f"{who}{face}{emo}{act}{fx}: {text}{eol}")
            elif k == "meta":
                out_parts.append(f"> {f.get('text', '')}{eol}")
            elif k == "blank":
                out_parts.append(eol)
            else:
                out_parts.append(node.raw)
    return "".join(out_parts)


def compile_document(
    nodes: List[DocNode], cast: Dict[str, Any], assets: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """将 DocNode 转换为编译事件 events 以及结构化诊断 diagnostics。
    未绑定演员、无法解析的行、未解决的背景请求产生诊断，但不从节点列表中删除。
    """
    events = []
    diagnostics = validate_script_diagnostics(nodes, cast, assets)

    for node in nodes:
        k = node.kind
        f = node.fields
        no = node.line_no

        if k == "scene":
            events.append({"k": "scene", "title": f.get("title", ""), "no": no})
        elif k == "title":
            events.append({"k": "title", "title": f.get("title", ""), "no": no})
        elif k == "dir":
            events.append({"k": "dir", "cmd": f.get("cmd", ""), "arg": f.get("arg", ""), "no": no})
        elif k == "line":
            who = f.get("who", "")
            real_who, face, emo, act, fx = split_head(who, cast)
            if not real_who:
                real_who = who
            if face is None:
                face = f.get("face")
            if emo is None:
                emo = f.get("emo")
            if act is None:
                act = f.get("act")
            if fx is None:
                fx = f.get("fx")

            if not cast or real_who in cast:
                events.append(
                    {
                        "k": "line",
                        "who": real_who,
                        "text": f.get("text", ""),
                        "face": face,
                        "emo": emo,
                        "act": act,
                        "fx": fx,
                        "no": no,
                    }
                )

    return events, diagnostics
