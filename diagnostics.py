# -*- coding: utf-8 -*-
"""
AA 剧本编译器 - 严重度诊断 (diagnostics.py)
定义稳定 code 表与严重度级别 (info | warning | error)
"""

import re
from typing import Any, Dict, List, Optional

DIAGNOSTIC_CODES = {
    "draft.blank_node": {"severity": "error", "message_tmpl": "草稿包含无意义的空白卡片"},
    "actor.unbound": {"severity": "error", "message_tmpl": "演员表里没有「{who}」，此行跳过"},
    "line.unparsable": {"severity": "error", "message_tmpl": "无法解析的行: {text}"},
    "dir.unknown": {"severity": "error", "message_tmpl": "未知指令: {cmd}"},
    "dir.argument_error": {"severity": "error", "message_tmpl": "指令参数格式错误: @{cmd} {arg}"},
    "face.invalid": {"severity": "error", "message_tmpl": "非法表情标识: {face}"},
    "bg.unregistered": {"severity": "error", "message_tmpl": "未登记背景: {bg}"},
    "sound.unregistered": {"severity": "error", "message_tmpl": "未登记音效: {sound}"},
    "actor.portrait_fields_ignored": {"severity": "error", "message_tmpl": "无立绘角色/旁白「{who}」不得包含立绘或表情字段"},
    "move.position_invalid": {"severity": "error", "message_tmpl": "@move 位置无效: {pos} (应为 1-5)"},
    "bg.request_unresolved": {"severity": "error", "message_tmpl": "未解决的背景请求: {description}"},
    "cast.overflow_warning": {"severity": "warning", "message_tmpl": "舞台角色数量超过 5 人，自动挤掉边缘角色"},
    "shot.target_offscreen": {"severity": "warning", "message_tmpl": "@shot 目标「{target}」不在画面中"},
}

# These findings mean that the compiler cannot faithfully represent the
# authored document or would silently omit a resource. They remain hard
# blockers even when the user accepts non-fatal quality warnings.
HARD_DIAGNOSTIC_CODES = frozenset({
    "draft.blank_node",
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
})


def classify_diagnostic(diagnostic: Dict[str, Any]) -> Dict[str, Any]:
    """Attach the review owner without changing the original diagnostic."""
    result = dict(diagnostic or {})
    code = str(result.get("code") or "")
    severity = str(result.get("severity") or result.get("level") or "").lower()
    result["resolution"] = (
        "block" if code in HARD_DIAGNOSTIC_CODES or severity == "error"
        else "advisory"
    )
    result["override_allowed"] = result["resolution"] != "block"
    return result


def classify_diagnostics(diagnostics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [classify_diagnostic(item) for item in diagnostics if isinstance(item, dict)]

KNOWN_COMMANDS = {
    "bg",
    "trans",
    "bgfx",
    "popup",
    "bgm",
    "music",
    "se",
    "sound",
    "place",
    "wait",
    "nodialog",
    "react",
    "reveal",
    "enter",
    "exit",
    "move",
    "stage",
    "auto",
    "layout",
    "camera",
    "camera_hold",
    "camera_cut",
    "fx",
    "hl",
    "bgshake",
    "clearst",
    "hidemenu",
    "showmenu",
    "shot",
    "aronatouch",
    "st",
    "stm",
    "zoom",
    "raw",
}

THEMATIC_BREAK_RE = re.compile(r"^(?P<mark>[-*_])(?:\s*(?P=mark)){2,}$")


def create_diagnostic(
    code: str,
    line_no: int,
    card_id: Optional[str] = None,
    message_override: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    info = DIAGNOSTIC_CODES.get(code, {"severity": "error", "message_tmpl": "未知诊断: {code}"})
    severity = info["severity"]
    if message_override:
        message = message_override
    else:
        try:
            message = info["message_tmpl"].format(**kwargs)
        except Exception:
            message = info["message_tmpl"]
    return {
        "code": code,
        "severity": severity,
        "line_no": line_no,
        "card_id": card_id,
        "message": message,
    }


def validate_script_diagnostics(
    nodes: List[Any],
    cast: Dict[str, Any],
    assets: Optional[Dict[str, Any]] = None,
    active_on_stage: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    diagnostics = []
    assets = assets or {}

    bgs_val = assets.get("bg", {})
    known_bgs = set(bgs_val.keys()) if isinstance(bgs_val, dict) else set(bgs_val)
    sounds_val = assets.get("sounds", [])
    known_sounds = set(sounds_val.keys()) if isinstance(sounds_val, dict) else set(sounds_val)

    for node in nodes:
        kind = getattr(node, "kind", "")
        fields = getattr(node, "fields", {})
        line_no = getattr(node, "line_no", 0)

        if kind == "background_request":
            diagnostics.append(
                create_diagnostic(
                    "bg.request_unresolved",
                    line_no=line_no,
                    description=fields.get("description", ""),
                )
            )
        elif kind == "blank":
            diagnostics.append(
                create_diagnostic("draft.blank_node", line_no=line_no)
            )
        elif kind == "separator":
            continue
        elif kind == "unknown":
            raw_text = getattr(node, "raw", "").strip()
            if THEMATIC_BREAK_RE.fullmatch(raw_text):
                continue
            diagnostics.append(
                create_diagnostic(
                    "line.unparsable",
                    line_no=line_no,
                    text=raw_text[:40],
                )
            )
        elif kind == "line":
            who = fields.get("who", "")
            if who not in cast:
                diagnostics.append(
                    create_diagnostic("actor.unbound", line_no=line_no, who=who)
                )
            else:
                char_info = cast[who]
                if char_info.get("narrator"):
                    if any(fields.get(k) for k in ("face", "emo", "act", "fx")):
                        diagnostics.append(
                            create_diagnostic("actor.portrait_fields_ignored", line_no=line_no, who=who)
                        )
                face = fields.get("face")
                if face and not re.fullmatch(r"[A-Za-z0-9_]+", face.strip()):
                    diagnostics.append(
                        create_diagnostic("face.invalid", line_no=line_no, face=face)
                    )

        elif kind == "dir":
            cmd = fields.get("cmd", "").lower()
            arg = fields.get("arg", "")

            if cmd not in KNOWN_COMMANDS:
                diagnostics.append(
                    create_diagnostic("dir.unknown", line_no=line_no, cmd=cmd)
                )
            else:
                if cmd == "bg" and arg:
                    bg_name = arg.strip()
                    if known_bgs and bg_name not in known_bgs:
                        diagnostics.append(
                            create_diagnostic("bg.unregistered", line_no=line_no, bg=bg_name)
                        )
                elif cmd == "se" and arg:
                    sound_name = arg.strip()
                    if known_sounds and sound_name not in known_sounds:
                        diagnostics.append(
                            create_diagnostic("sound.unregistered", line_no=line_no, sound=sound_name)
                        )
                elif cmd == "move":
                    parts = arg.split()
                    if len(parts) >= 2:
                        pos = parts[1]
                        if pos not in ("1", "2", "3", "4", "5"):
                            diagnostics.append(
                                create_diagnostic("move.position_invalid", line_no=line_no, pos=pos)
                            )
                    else:
                        diagnostics.append(
                            create_diagnostic("dir.argument_error", line_no=line_no, cmd=cmd, arg=arg)
                        )
                elif cmd == "wait":
                    if not arg.isdigit():
                        diagnostics.append(
                            create_diagnostic("dir.argument_error", line_no=line_no, cmd=cmd, arg=arg)
                        )
                elif cmd == "stage":
                    slots = arg.split()
                    if len(slots) > 5:
                        diagnostics.append(
                            create_diagnostic("cast.overflow_warning", line_no=line_no)
                        )
                elif cmd == "shot":
                    target = arg.strip()
                    if active_on_stage is not None and target not in active_on_stage and target not in ("1", "2", "3", "4", "5"):
                        diagnostics.append(
                            create_diagnostic("shot.target_offscreen", line_no=line_no, target=target)
                        )

    return diagnostics
