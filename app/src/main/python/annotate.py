# -*- coding: utf-8 -*-
"""
演出标注器：给纯台词剧本自动加上 表情 / 气泡 / 动作 / 背景 / 音效 / 停顿。

模型只输出标注，绝不改台词。产物是同格式的剧本文件，可以人工审改后再喂给
script2aap.py。任何超出资源表的标注都会被丢弃并告警——模型放不上不存在的东西。

用法:
  python annotate.py 剧本.txt -o 剧本.annotated.txt [--cast cast.json] [--provider openai]
  python annotate.py 剧本.txt --range 1-80          只标注前 80 行（先试水）
"""
import argparse, hashlib, json, os, re, sys, uuid
from typing import Any, Dict, List

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from llm import make_provider, LLMError                       # noqa: E402
from script2aap import HEAD_RE, split_head, load_cast          # noqa: E402
from build_index import faces_of                               # noqa: E402
from asset_validation import extract_expression_capabilities   # noqa: E402
from dialogue_pacing import split_strong_dialogue_items         # noqa: E402
from annotation_chunks import assign_annotation_ids             # noqa: E402
from annotation_memory import (                                 # noqa: E402
    AnnotationCheckpointStore,
    build_run_fingerprint,
)
from annotation_agent import run_annotation_agent               # noqa: E402
from direction_rules import (                                  # noqa: E402
    apply_model_directions,
    mark_explicit_directions,
    normalize_direction_density,
    normalize_emoticon_density as _normalize_emoticon_density,
    supplement_directions,
)
import prompt as PROMPT                                        # noqa: E402
import tables                                                  # noqa: E402


def is_face_allowed(allow, face):
    """表情表未知时拒绝模型猜测；只有明确存在的 faceId 才能写入。"""
    return bool(allow) and face in allow


_FX_PARTS = frozenset({"通讯", "黑屏剪影", "特写"})


def is_fx_allowed(value):
    """Only accept one or more documented, non-duplicated shape bit names."""
    parts = [part.strip() for part in re.split(r"[+＋、,，/]", str(value)) if part.strip()]
    return bool(parts) and len(parts) == len(set(parts)) and set(parts) <= _FX_PARTS


def _selected_variants(capabilities, identifier, spine_signature="", outfit_key=""):
    variants = capabilities.get(identifier, [])
    if spine_signature or outfit_key:
        selected = [
            variant for variant in variants
            if (not spine_signature or variant.get("spine_signature") == spine_signature)
            and (not outfit_key or variant.get("outfit_key") == outfit_key)
        ]
        if selected:
            return selected
        return []
    return [
        variant for variant in variants
        if not variant.get("spine_signature") and not variant.get("outfit_key")
    ]


def face_allowlist(capabilities, identifier, *, spine_signature="", outfit_key=""):
    """Return only observed or verified faces for the chosen safe scope."""
    allow = set()
    for variant in _selected_variants(capabilities, identifier, spine_signature, outfit_key):
        for face in variant.get("faces", []):
            if {"aap_observed", "aa_verified"} & set(face.get("sources", [])):
                allow.add(face["id"])
    return allow


def official_basic_face_allowlist(
    capabilities, identifier, *, spine_signature="", outfit_key=""
):
    """Return official atlas candidates plus observed/verified faces."""
    allow = face_allowlist(
        capabilities, identifier,
        spine_signature=spine_signature,
        outfit_key=outfit_key,
    )
    for variant in _selected_variants(capabilities, identifier, spine_signature, outfit_key):
        for face in variant.get("faces", []):
            if "atlas_candidate" in set(face.get("sources", [])):
                allow.add(face["id"])
    return allow


def semantic_face_allowlist(capabilities, identifier, *, spine_signature="", outfit_key=""):
    """Return parsed, non-special face animations for a semantic modular bone."""
    allow = set()
    for variant in _selected_variants(capabilities, identifier, spine_signature, outfit_key):
        for face in variant.get("faces", []):
            if "spine_semantic" in set(face.get("sources", [])):
                allow.add(face["id"])
    return allow


def _allowed_face_records(
    capabilities, identifier, *, spine_signature="", outfit_key="", semantic=False,
    official_basic=False
):
    selector = {"spine_signature": spine_signature, "outfit_key": outfit_key}
    allowed = (
        semantic_face_allowlist(capabilities, identifier, **selector)
        if semantic else (
            official_basic_face_allowlist(capabilities, identifier, **selector)
            if official_basic else face_allowlist(capabilities, identifier, **selector)
        )
    )
    records = {}
    for variant in _selected_variants(capabilities, identifier, spine_signature, outfit_key):
        for face in variant.get("faces", []):
            if face.get("id") in allowed:
                records.setdefault(face["id"], face)
    result = [records[key] for key in sorted(records)]
    # A verified but semantically unknown number remains legal to the compiler,
    # but must not be offered to the model as something it can safely choose.
    return [
        face for face in result
        if face.get("semantic_cn") or face.get("cn") or face.get("label")
    ]


def annotation_constraints(idx, cast, *, usage_chain=None):
    """Build the complete allowlist used to filter one model response.

    The result is plain data so it can be tested independently from an LLM call.
    Semantic atlas parts intentionally never enter ``faces_by_id``.
    """
    capabilities = idx.get("face_capabilities") or {}
    semantic_modular = {
        record.get("identifier")
        for record in idx.get("characters", [])
        if record.get("expression_mode") == "semantic_modular"
    }
    semantic_modular |= {
        character.get("id")
        for character in cast.values()
        if character.get("_expression_mode") == "semantic_modular"
    }
    faces_by_id = {}
    if capabilities:
        for character in cast.values():
            ident = character.get("id")
            if ident:
                selector = {
                    "spine_signature": character.get("spine_signature", ""),
                    "outfit_key": character.get("outfit_key", ""),
                }
                official = ident in {
                    record.get("identifier")
                    for record in idx.get("characters", [])
                } and not character.get("custom")
                faces_by_id[ident] = (
                    semantic_face_allowlist(capabilities, ident, **selector)
                    if ident in semantic_modular
                    else official_basic_face_allowlist(capabilities, ident, **selector)
                    if official
                    else face_allowlist(capabilities, ident, **selector)
                )
    else:
        faces_by_id = {
            character["identifier"]: {face["id"] for face in character["faces"]}
            for character in idx.get("characters", []) if character.get("faces")
        }
        for ident, faces in (idx.get("faces_used") or {}).items():
            faces_by_id.setdefault(ident, {face["id"] for face in faces})
    sym2cn = {
        value["sym"]: value["cn"]
        for value in idx["enums"]["emoticon"].values()
        if value.get("cn")
    }
    confirmed_backgrounds = {
        str(need.get("aa_key") or "").strip()
        for entry in (usage_chain or [])
        if isinstance(entry, dict)
        for need in (entry.get("needs") or [])
        if isinstance(need, dict)
        and str(need.get("kind") or "").strip().lower() in {"background", "bg"}
        and str(need.get("status") or "").strip().lower() in {"registered", "builtin"}
        and str(need.get("aa_key") or "").strip()
    }
    return {
        "faces_by_id": faces_by_id,
        "sym2cn": sym2cn,
        "ok_emo": set(sym2cn) | set(sym2cn.values()),
        "ok_act": {value["verb"] for value in idx["enums"]["action"].values()},
        "ok_fx": _FX_PARTS,
        "ok_se": set(idx.get("sounds", [])),
        "ok_bg": set(idx.get("bg", {})) | confirmed_backgrounds,
        "confirmed_bg": confirmed_backgrounds,
        "ok_shot": {
            name for name, character in cast.items()
            if character.get("portrait") and not character.get("narrator")
        },
    }


def filter_annotation_row(row, item, character, constraints, *, include_details=False):
    """Return legal model fields and exact reasons for every rejected field."""
    clean, dropped, rejected_details = {}, [], []
    who = item["who"]
    portrait = character.get("portrait") and not character.get("narrator")
    for field in ("face", "emo", "act", "fx"):
        value = row.get(field)
        if not value:
            continue
        if not portrait:
            msg = f"{who}无立绘，不能使用 {field}"
            dropped.append(msg)
            rejected_details.append({"field": field, "value": value, "reason": msg})
            continue
        if field == "face":
            allowed = constraints["faces_by_id"].get(character.get("id"), set())
            if is_face_allowed(allowed, value):
                clean[field] = value
            else:
                msg = f"{who} 没有已验证表情 {value}"
                dropped.append(msg)
                rejected_details.append({"field": field, "value": value, "reason": msg})
        elif field == "emo":
            if value in constraints["ok_emo"]:
                clean[field] = constraints["sym2cn"].get(value, value)
            else:
                msg = f"未知气泡 {value}"
                dropped.append(msg)
                rejected_details.append({"field": field, "value": value, "reason": msg})
        elif field == "act":
            if value in constraints["ok_act"]:
                clean[field] = value
            else:
                msg = f"未知动作 {value}"
                dropped.append(msg)
                rejected_details.append({"field": field, "value": value, "reason": msg})
        elif field == "fx" and is_fx_allowed(value):
            clean[field] = value
        else:
            msg = f"未知效果 {value}"
            dropped.append(msg)
            rejected_details.append({"field": field, "value": value, "reason": msg})
    for field, message in (("se", "未知音效"), ("bg", "未知背景")):
        value = row.get(field)
        if not value:
            continue
        if value in constraints[f"ok_{field}"]:
            clean[field] = value
        else:
            msg = f"{message} {value}"
            dropped.append(msg)
            rejected_details.append({"field": field, "value": value, "reason": msg})
    bg_request = str(row.get("bg_request") or "").strip()
    if bg_request:
        confirmed_bg = set(constraints.get("confirmed_bg") or set())
        if clean.get("bg") and clean["bg"] in confirmed_bg:
            dropped.append("已确认背景不再生成背景请求")
        else:
            clean.pop("bg", None)
            clean["bg_request"] = bg_request[:320]
    shot = row.get("shot")
    if shot:
        if shot in constraints["ok_shot"]:
            clean["shot"] = shot
        else:
            msg = f"射击目标‘{shot}’不是可显示角色"
            dropped.append(msg)
            rejected_details.append({"field": "shot", "value": shot, "reason": msg})
    if include_details:
        return clean, dropped, rejected_details
    return clean, dropped


def annotation_rows(response):
    """Accept the documented ``{"lines": [...]}`` response and one safe proxy variant."""
    if isinstance(response, dict):
        rows = response.get("lines")
    elif isinstance(response, list):
        rows = response
    else:
        raise LLMError("模型标注响应顶层必须是对象或标注数组")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise LLMError("模型标注响应顶层 lines 必须是对象数组")
    return rows


_TRANSIENT_BGFX_IDS = {
    tables.BGEFFECT["BG_FocusLine"],
    tables.BGEFFECT["BG_Flash"],
    tables.BGEFFECT["BG_Flash_Sound"],
    tables.BGEFFECT["BG_Teleport"],
}


def normalize_bgfx_lifetime(items):
    """Insert the mandatory reset after a one-shot background effect.

    Rain, snow and mist are intentionally absent from the transient set: they
    remain active until the model or the source script writes ``无``.
    """
    reset_next_line = False
    for item in items:
        if item.get("kind") != "line":
            continue
        current = item.get("bgfx")
        if reset_next_line and not current:
            item["bgfx"] = "无"
            current = "无"
        reset_next_line = False
        if not current:
            continue
        value, error = tables.resolve_bgeffect(current)
        if error or not value:
            continue
        if value in _TRANSIENT_BGFX_IDS:
            reset_next_line = True


def normalize_emoticon_density(items):
    """Keep emoticons sparse: never consecutive, and do not repeat them rapidly."""
    _normalize_emoticon_density(items)


def normalize_contextual_sounds(items, idx):
    """Add only high-confidence sounds that exist in the registered index."""
    sounds = set(idx.get("sounds", []))
    footstep = "SE_FootStep_01"
    opening_context = []
    first_spoken = None
    for item in items:
        if item.get("kind") != "line":
            continue
        if item.get("who") == "旁白" and first_spoken is None:
            opening_context.append(item.get("text", ""))
            continue
        first_spoken = item
        break
    if first_spoken and not first_spoken.get("se") and footstep in sounds:
        context = "".join(opening_context)
        speech = first_spoken.get("text", "")
        waiting = any(token in context for token in ("站在那里", "集合点", "入口", "等候"))
        arrival = any(token in speech for token in ("这么早", "久等", "到了", "已经来了"))
        if waiting and arrival:
            first_spoken["se"] = footstep

    rules = [
        (
            "SE_BoxShake_01",
            ("纸箱里传出", "纸箱中传出", "窸窸窣窣", "悉悉索索", "纸箱晃动"),
        ),
        (
            "SE_BoxCover_01",
            ("掀开纸箱", "打开纸箱", "纸箱盖", "箱盖"),
        ),
        (
            "SE_BoxMove_01",
            ("搬起纸箱", "拖动纸箱", "纸箱移动", "挪动纸箱"),
        ),
    ]
    for item in items:
        if item.get("kind") != "line" or item.get("se"):
            continue
        text = str(item.get("text") or "")
        assigned = False
        for sound, phrases in rules:
            if sound in sounds and any(phrase in text for phrase in phrases):
                item["se"] = sound
                assigned = True
                break
        if assigned:
            continue
        reveal = (
            "桃井" in text
            and any(
                phrase in text
                for phrase in ("跳出来", "钻出来", "露出", "被发现", "现身", "探出头")
            )
        )
        if reveal and "SE_Appear_01a" in sounds:
            item["se"] = "SE_Appear_01a"


def build_batch_context(items, indices):
    """Show prior choices so chunked annotation does not forget recent faces."""
    if not indices:
        return ""
    from collections import Counter, defaultdict

    usage = defaultdict(Counter)
    lines = []
    for index in indices:
        item = items[index]
        detail = []
        if item.get("face"):
            detail.append(f"face={item['face']}")
            usage[item["who"]][item["face"]] += 1
        if item.get("emo"):
            detail.append(f"emo={item['emo']}")
        if item.get("act"):
            detail.append(f"act={item['act']}")
        suffix = f"（{', '.join(detail)}）" if detail else ""
        lines.append(f"  {item['who']}: {item['text']}{suffix}")
    for who, counts in usage.items():
        values = "、".join(f"{face}×{count}" for face, count in sorted(counts.items()))
        lines.append(f"  {who}近期 face 使用：{values}")
    return "\n".join(lines)


def build_face_usage_summary(items, indices):
    """Compact chapter-wide face counts for cross-chunk diversity."""
    from collections import Counter, defaultdict

    usage = defaultdict(Counter)
    for index in indices:
        item = items[index]
        if item.get("face"):
            usage[item["who"]][item["face"]] += 1
    lines = []
    for who, counts in usage.items():
        values = "、".join(
            f"{face}×{count}"
            for face, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
        )
        lines.append(f"  {who}本章已用 face：{values}")
    return "\n".join(lines)


def annotation_directives(item):
    """Translate only constrained model fields into safe script directives."""
    directives = []
    if item.get("bg_request"):
        directives.append(f"# 待生成自定义背景：{item['bg_request']}")
    if item.get("shot"):
        directives.append(f"@shot {item['shot']}")
    return directives


def bind_registered_custom_variants(cast, idx):
    """Bind a custom asset to exactly one indexed Spine variant, never by guesswork."""
    capabilities = idx.get("face_capabilities") or {}
    for character in cast.values():
        custom = character.get("custom") or {}
        ident = str(character.get("id") or "")
        asset = str(custom.get("asset") or "")
        if not ident or not asset:
            continue
        if character.get("spine_signature") or character.get("outfit_key"):
            continue
        matches = [
            variant for variant in capabilities.get(ident, [])
            if variant.get("outfit_key") == asset and variant.get("spine_signature")
        ]
        if len(matches) == 1:
            character["spine_signature"] = matches[0]["spine_signature"]
            character["outfit_key"] = matches[0]["outfit_key"]


def load_custom_faces(cast, story_root, idx=None):
    """自定义骨骼不在全局素材库里，直接读它自己的 .atlas 拿表情表。"""
    for c in cast.values():
        cu = c.get("custom")
        if not cu or c.get("_faces"):
            continue
        src = cu["src"].replace("/", os.sep)
        if not os.path.isabs(src):
            src = os.path.join(story_root, src)
        atlas = os.path.join(src, cu["asset"] + ".atlas")
        c["_faces"] = faces_of(atlas)
        if os.path.isfile(atlas):
            with open(atlas, encoding="utf-8", errors="replace") as fh:
                expression = extract_expression_capabilities(fh.read().splitlines())
            c["_expression_mode"] = expression["mode"]
            c["_expression_parts"] = expression["parts"]
        else:
            c["_expression_mode"] = "opaque_custom"
            c["_expression_parts"] = []
        if not c["_faces"]:
            if os.path.isfile(atlas):
                print(f"  · 自定义骨骼未发现编号表情，按语义部件约束: {atlas}")
            else:
                print(f"  ! 读不到自定义骨骼表情表: {atlas}")
    if idx is not None:
        bind_registered_custom_variants(cast, idx)

SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer", "description": "段落内的行号"},
                    "face": {"type": "string", "description": "faceId，两位数字；无立绘或不改则空串"},
                    "emo": {"type": "string", "description": "头顶的瞬时心理反应气泡，填符号或中文名；不加则空串"},
                    "act": {"type": "string", "description": "原地身体反应的动作 verb；不加则空串"},
                    "fx": {"type": "string",
                           "description": "立绘效果：通讯 / 黑屏剪影 / 特写，可用 + 组合；不加则空串"},
                    "se": {"type": "string", "description": "音效名；不加则空串"},
                    "bg": {"type": "string", "description": "从本行起换背景；不换则空串"},
                    "bg_request": {"type": "string",
                                   "description": "没有准确可用背景时，填写可直接用于图片生成的中文提示词；否则空串"},
                    "place": {"type": "string",
                              "description": "地点名称卡，只在换场景时写；不写则空串"},
                    "shake": {"type": "boolean", "description": "本行是否抖一下背景"},
                    "bgfx": {"type": "string", "description": "背景效果中文名；不加则空串"},
                    "trans": {"type": "string", "description": "过渡，只在换背景那行填；不加则空串"},
                    "move": {"type": "integer",
                             "description": "文本明确发生真实位置变化时，让说话者走到位置 1-5；不走则填 0"},
                    "shot": {"type": "string",
                             "description": "仅当画面中该角色实际遭受攻击时，填受击角色的精确名字；否则空串"},
                },
                "required": ["i", "face", "emo", "act", "fx", "se",
                             "bg", "bg_request", "place", "shake", "bgfx", "trans", "move", "shot"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}

def build_static(idx, cast, cast_names):
    """跨请求不变的系统提示词 —— 这部分会被缓存。规则正文在 prompt.py。"""
    capabilities = idx.get("face_capabilities") or {}
    if capabilities:
        character_records = {
            record.get("identifier"): record
            for record in idx.get("characters", [])
            if record.get("identifier")
        }
        faces_by_id = {}
        for who in cast_names:
            character = cast[who]
            ident = character.get("id")
            if not ident:
                continue
            record = character_records.get(ident, {})
            expression_mode = character.get(
                "_expression_mode", record.get("expression_mode", "opaque_custom")
            )
            faces_by_id[ident] = {
                "faces": _allowed_face_records(
                    capabilities,
                    ident,
                    spine_signature=character.get("spine_signature", ""),
                    outfit_key=character.get("outfit_key", ""),
                    semantic=expression_mode == "semantic_modular",
                    official_basic=ident in character_records and not character.get("custom"),
                ),
                "expression_mode": expression_mode,
                "expression_parts": character.get(
                    "_expression_parts", record.get("expression_parts", [])
                ),
            }
        return PROMPT.build_system(idx, cast, cast_names, faces_by_id)
    faces_by_id = {c["identifier"]: c["faces"] for c in idx["characters"] if c["faces"]}
    for ident, fs in (idx.get("faces_used") or {}).items():
        faces_by_id.setdefault(ident, fs)
    return PROMPT.build_system(idx, cast, cast_names, faces_by_id)


def build_annotation_static_system(static_rules, source_text, *, source_context_strategy="preserve"):
    if source_context_strategy == "window":
        return static_rules
    return f"{static_rules}\n\nSOURCE_SCRIPT\n{source_text}"


def parse_lines(path, cast):
    """保留原文行，同时标出哪些是台词行。"""
    out = []
    for line_no, raw in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("@"):
            out.append({"raw": raw, "kind": "other"})
            continue
        m = HEAD_RE.match(s)
        if not m:
            out.append({"raw": raw, "kind": "other"})
            continue
        who, face, emo, act, fx = split_head(m.group("head"), cast)
        if who not in cast:
            out.append({"raw": raw, "kind": "other"})
            continue
        item = {"raw": raw, "kind": "line", "line_no": line_no, "split_index": 0, "who": who,
                "text": m.group("text").strip(),
                "face": face, "emo": emo, "act": act, "fx": fx}
        mark_explicit_directions(item)
        out.append(item)
    return out


def should_trigger_retry(total_lines: int, rejected_count: int, parse_error: bool = False) -> bool:
    """两类重试触发条件判定：A 结构失败 / B rejection 比例 >= 10%"""
    if parse_error:
        return True
    if total_lines <= 0:
        return False
    rejection_rate = rejected_count / total_lines
    return rejection_rate >= 0.10


def render(item):
    """把标注写回剧本行。"""
    anno = ""
    if item.get("face"):
        anno += f"({item['face']})"
    if item.get("emo"):
        anno += f"[{item['emo']}]"
    if item.get("act"):
        anno += "{" + item["act"] + "}"
    if item.get("fx"):
        anno += f"<{item['fx']}>"
    return f"{item['who']}{anno}: {item['text']}"


def render_annotated_items(items):
    """Render annotated items while avoiding redundant background switches."""
    out_lines = []
    last_bg = None
    has_background = False
    for item in items:
        if item["kind"] != "line":
            out_lines.append(item["raw"])
            continue

        background = item.get("bg")
        background_changed = bool(background and background != last_bg)
        if background_changed:
            out_lines.append(f"@bg {background}")
            last_bg = background
        if item.get("trans") and (not background or (background_changed and has_background)):
            out_lines.append(f"@trans {item['trans']}")
        if background_changed:
            has_background = True
        if item.get("bgfx"):
            out_lines.append(f"@bgfx {item['bgfx']}")
        if item.get("place"):
            out_lines.append(f"@place {item['place']}")
        if item.get("move"):
            out_lines.append(f"@move {item['who']} {item['move']}")
        if item.get("shake"):
            out_lines.append("@bgshake")
        if item.get("se"):
            out_lines.append(f"@se {item['se']}")
        if item.get("wait_ms"):
            out_lines.append(f"@wait {item['wait_ms']}")
        out_lines.extend(annotation_directives(item))
        out_lines.append(render(item))

    return "\n".join(out_lines) + "\n"


def insert_annotation_beats(items, beats):
    """Insert validated dialogue-free reaction nodes around source anchors."""
    before, after = {}, {}
    for beat in beats or []:
        target = before if beat.get("position") == "before" else after
        target.setdefault(str(beat.get("anchor_id") or ""), []).append(beat)
    result = []
    for item in items:
        anchor_id = str(item.get("annotation_id") or "")
        for beat in before.get(anchor_id, []):
            result.append(_beat_item(beat))
        result.append(item)
        for beat in after.get(anchor_id, []):
            result.append(_beat_item(beat))
    return result


def _beat_item(beat):
    return {
        "kind": "line", "raw": "", "who": beat["who"], "text": "",
        "face": beat.get("face", ""), "emo": beat.get("emo", ""),
        "act": beat.get("act", ""), "fx": "", "wait_ms": beat.get("wait_ms", 0),
        "_annotation_beat": True,
    }


def build_proposal(
    card_id: str,
    p_type: str,
    origin: str,
    rule: str,
    field_name: str,
    before: Any,
    after: Any,
    based_on_content_revision: int = 1,
    expected_card_version: int = 1,
) -> Dict[str, Any]:
    return {
        "proposal_id": f"prop-{uuid.uuid4().hex[:12]}",
        "origin": origin,
        "type": p_type,
        "rule": rule,
        "card_id": card_id,
        "field": field_name,
        "before": before,
        "after": after,
        "based_on_content_revision": based_on_content_revision,
        "expected_card_version": expected_card_version,
        "state": "pending",
    }


def apply_annotation_response_row(item, row, cast, constraints, proposals, dropped):
    """Apply one validated model row through the existing resource guards."""
    character = cast[item["who"]]
    portrait = character.get("portrait") and not character.get("narrator")
    clean, rejected, rejected_details = filter_annotation_row(
        row, item, character, constraints, include_details=True
    )
    card_id = item.get("card_id") or str(uuid.uuid4())
    applied_clean = apply_model_directions(item, clean)
    for field_name, field_value in applied_clean.items():
        proposals.append(build_proposal(
            card_id=card_id, p_type="applied_pending", origin="model",
            rule="llm_annotation", field_name=field_name,
            before=item.get(field_name), after=field_value,
        ))
    for rejected_item in rejected_details:
        proposals.append(build_proposal(
            card_id=card_id, p_type="suggested_fix", origin="model",
            rule="llm_rejected_annotation", field_name=rejected_item["field"],
            before=None, after=rejected_item["value"],
        ))
    dropped.extend(rejected)
    if row.get("place"):
        item["place"] = str(row["place"])[:40]
    if row.get("shake"):
        item["shake"] = True
    if row.get("bgfx"):
        _value, error = tables.resolve_bgeffect(row["bgfx"])
        if error is None:
            item["bgfx"] = row["bgfx"]
        else:
            dropped.append(error or f"未知背景效果 {row['bgfx']}")
    if row.get("trans"):
        value, error = tables.resolve_transition(row["trans"])
        if value:
            item["trans"] = row["trans"]
        else:
            dropped.append(error or f"未知过渡 {row['trans']}")
    if portrait and isinstance(row.get("move"), int) and 1 <= row["move"] <= 5:
        item["move"] = row["move"]
    return True


def build_postprocessor_proposals(items: List[Dict[str, Any]], rule: str = "emoticon_density") -> List[Dict[str, Any]]:
    proposals = []
    for it in items:
        card_id = it.get("card_id") or str(uuid.uuid4())
        if rule == "emoticon_density" and it.get("emo"):
            proposals.append(
                build_proposal(
                    card_id=card_id,
                    p_type="applied_pending",
                    origin="deterministic_postprocessor",
                    rule=rule,
                    field_name="emo",
                    before=None,
                    after=it["emo"],
                )
            )
    return proposals


def apply_direction_supplements(items, cast):
    """Run optional deterministic direction without blocking draft generation."""
    try:
        return supplement_directions(items, cast), []
    except Exception as exc:
        return [], [{
            "code": "direction_supplement_failed",
            "level": "warning",
            "message": f"自动演出补全已跳过：{exc}",
        }]


def annotate_script(options: dict, provider_instance=None) -> dict:
    """演出标注纯函数接口（剥离 sys.argv 与全局状态）"""
    script_path = options["script"]
    out_path = options.get("out") or re.sub(r"(\.[^.]+)$", r".annotated\1", script_path)
    cast_path = options.get("cast") or os.path.join(HERE, "cast.json")
    index_path = options.get("index") or os.path.join(HERE, "aa_resources.json")
    llm_path = options.get("llm") or os.path.join(HERE, "llm.json")
    provider_name = options.get("provider")
    range_str = options.get("range")
    dry_run = options.get("dry_run", False)
    raw_usage_chain = options.get("usage_chain")
    usage_chain = raw_usage_chain[:80] if isinstance(raw_usage_chain, list) else []
    usage_chain_context = ""
    if usage_chain:
        usage_chain_context = (
            "已确认的场景演出规划（优先遵守其中已确认的背景和音效，不要重新换成其他素材；"
            "BGM 仅作上下文，本阶段不写入）：\n"
            + json.dumps(usage_chain, ensure_ascii=False, separators=(",", ":"))[:16000]
        )

    cfg, cast, _ = load_cast(cast_path)
    idx = json.load(open(index_path, encoding="utf-8"))
    # Android model profiles provide the provider directly.  The legacy
    # desktop config is optional there because it is intentionally not
    # packaged (it may contain API credentials).
    llmcfg = {}
    if os.path.isfile(llm_path):
        llmcfg = json.load(open(llm_path, encoding="utf-8"))
    load_custom_faces(cast, os.path.dirname(os.path.dirname(HERE)), idx)
    items = assign_annotation_ids(
        split_strong_dialogue_items(parse_lines(script_path, cast), cast)
    )

    dialog = [i for i, it in enumerate(items) if it["kind"] == "line"]
    lo, hi = 0, len(dialog)
    if range_str:
        m = re.match(r"^(\d+)-(\d+)$", range_str)
        if not m:
            raise ValueError("--range 格式应为 1-80")
        lo, hi = int(m.group(1)) - 1, int(m.group(2))
    todo = dialog[lo:hi]

    used, seen_id = [], set()
    for w in sorted({items[i]["who"] for i in todo},
                    key=lambda w: -sum(1 for i in todo if items[i]["who"] == w)):
        key = cast[w].get("id") or "旁白"
        if key in seen_id:
            continue
        seen_id.add(key)
        used.append(w)
    constraints = annotation_constraints(idx, cast, usage_chain=usage_chain)
    prompt_idx = dict(idx)
    prompt_idx["bg"] = dict(idx.get("bg", {}))
    for background in constraints.get("confirmed_bg") or set():
        prompt_idx["bg"].setdefault(background, 0)
    static = build_static(prompt_idx, cast, used)

    print(f"剧本      {script_path}")
    print(f"待标注    {len(todo)} 行台词（全文 {len(dialog)} 行）")
    print(f"出场      {'、'.join(used)}")
    print(f"资源表    约 {len(static)//3:,} tokens（会被缓存）")

    if dry_run:
        print("\n" + "=" * 60)
        print(static[:3000])
        print("…（截断）")
        return {"text": "", "proposals": [], "diagnostics": [], "out": out_path}

    prov = provider_instance or make_provider(llm_path, provider_name)
    print(f"模型      {prov.name} / {prov.model}\n")

    n = llmcfg.get("chunk_lines", 40)
    ctx = llmcfg.get("context_lines", 10)
    dropped, applied = [], 0
    diagnostics = []
    proposals = []
    agent_enabled = bool(options.get("agent_enabled", llmcfg.get("agent_enabled", False))) and not range_str
    agent_meta = {}
    annotation_beats = []
    if agent_enabled:
        script_text = open(script_path, encoding="utf-8").read()
        agent_static = build_annotation_static_system(
            static,
            script_text,
            source_context_strategy=str(getattr(prov, "cfg", {}).get("source_context_strategy") or "preserve"),
        )
        model_config = {
            "provider": getattr(prov, "name", provider_name or llmcfg.get("provider") or ""),
            "model": getattr(prov, "model", ""),
            "max_tokens": int(getattr(prov, "cfg", {}).get("max_tokens", 16000)),
            "annotation_max_tokens": int(getattr(prov, "cfg", {}).get("annotation_max_tokens") or getattr(prov, "cfg", {}).get("max_tokens", 16000)),
            "reasoning_mode": str(getattr(prov, "cfg", {}).get("reasoning_mode") or "balanced"),
            "reasoning_wire_protocol": str(getattr(prov, "cfg", {}).get("reasoning_wire_protocol") or ""),
            "context_window_tokens": int(getattr(prov, "cfg", {}).get("context_window_tokens") or 0) or None,
            "compact_annotation": bool(getattr(prov, "supports_compact_annotation", False)),
        }
        fingerprint = build_run_fingerprint(
            script_text, cast, idx,
            hashlib.sha256(static.encode("utf-8")).hexdigest()[:16], 2, "scene-v2",
            model_config,
        )
        checkpoint_dir = options.get("checkpoint_dir") or os.path.join(HERE, "out", "annotation-checkpoints")
        agent_result = run_annotation_agent(
            items, provider=prov, static_system=agent_static, cast=cast,
            constraints=constraints, usage_chain=usage_chain,
            checkpoint_store=AnnotationCheckpointStore(checkpoint_dir),
            run_fingerprint=fingerprint, progress=options.get("progress"),
            model_activity=options.get("model_activity"),
            cancelled=options.get("cancelled"),
            target=None,
            soft_limit=None,
            hard_limit=None,
            before=int(llmcfg.get("agent_context_before", 15)),
            after=int(llmcfg.get("agent_context_after", 10)),
            reasoning_mode=str(getattr(prov, "cfg", {}).get("reasoning_mode") or "balanced"),
            annotation_max_tokens=int(getattr(prov, "cfg", {}).get("annotation_max_tokens") or getattr(prov, "cfg", {}).get("max_tokens", 16000)),
            context_window_tokens=int(getattr(prov, "cfg", {}).get("context_window_tokens") or 0) or None,
        )
        diagnostics.extend(agent_result.get("diagnostics") or [])
        agent_meta = {
            "enabled": True,
            "completed_chunks": agent_result.get("completed_chunks", 0),
            "resumed_chunks": agent_result.get("resumed_chunks", 0),
            "cancelled": bool(agent_result.get("cancelled")),
            "timed_out": bool(agent_result.get("timed_out")),
            "metrics": agent_result.get("metrics") or {},
        }
        if agent_meta["cancelled"]:
            return {"text": "", "proposals": [], "diagnostics": diagnostics,
                    "out": out_path, "agent": agent_meta, "cancelled": True}
        rows_by_id = agent_result["rows_by_id"]
        annotation_beats = agent_result.get("beats") or []
        for item_index in todo:
            item = items[item_index]
            row = rows_by_id.get(item.get("annotation_id"))
            if row and apply_annotation_response_row(item, row, cast, constraints, proposals, dropped):
                applied += 1
        print(f"  已标注 {applied}/{len(todo)} 行（Agent）")
    else:
        for start in range(0, len(todo), n):
            batch = todo[start:start + n]
            head = todo[max(0, start - ctx):start]
            vol = ""
            if head:
                vol = (
                    "前文（只作上下文，不要标注；括号是已采用演出，请避免机械重复）：\n"
                    + build_batch_context(items, head)
                )
                cumulative = build_face_usage_summary(items, todo[:start])
                if cumulative:
                    vol += "\n本章截至此处的 face 分布（语义正确优先，并避免少数编号霸占）：\n" + cumulative
            if usage_chain_context:
                vol += ("\n\n" if vol else "") + usage_chain_context
            body = "需要标注的段落：\n" + "\n".join(
                f"[{k}] {items[i]['who']}: {items[i]['text']}" for k, i in enumerate(batch))
            try:
                response = prov.complete_json(static, vol, body, SCHEMA)
            except LLMError as error:
                raise RuntimeError(f"调用失败: {error}")
            for row in annotation_rows(response):
                row_index = row.get("i")
                if not isinstance(row_index, int) or not 0 <= row_index < len(batch):
                    continue
                if apply_annotation_response_row(items[batch[row_index]], row, cast, constraints, proposals, dropped):
                    applied += 1
            done = min(start + n, len(todo))
            print(f"  已标注 {done}/{len(todo)} 行")

    normalize_contextual_sounds(items, idx)
    supplements, supplement_diagnostics = apply_direction_supplements(items, cast)
    diagnostics.extend(supplement_diagnostics)
    for change in supplements:
        item = items[change["item_index"]]
        proposals.append(
            build_proposal(
                card_id=item.get("card_id") or str(uuid.uuid4()),
                p_type="applied_pending",
                origin="deterministic_supplement",
                rule=change["rule"],
                field_name=change["field"],
                before=change["before"],
                after=change["after"],
            )
        )
    normalize_direction_density(items)
    normalize_bgfx_lifetime(items)

    final_text = render_annotated_items(insert_annotation_beats(items, annotation_beats))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(final_text)

    tag = {"face": 0, "emo": 0, "act": 0, "fx": 0, "se": 0, "bg": 0, "trans": 0,
           "bgfx": 0, "bg_request": 0, "place": 0, "shake": 0, "move": 0, "shot": 0}
    for it in items:
        for k in tag:
            if it.get(k):
                tag[k] += 1
    print(f"\n{prov.report()}")
    print("标注统计  " + "  ".join(f"{k}:{v}" for k, v in tag.items()))
    if dropped:
        uniq = sorted(set(dropped))
        print(f"越界丢弃  {len(dropped)} 处（{len(uniq)} 种）")
        for d in uniq[:8]:
            print("    " + d)
    print(f"\n已写出  {out_path}")

    return {
        "text": final_text,
        "proposals": proposals,
        "diagnostics": diagnostics,
        "out": out_path,
        "agent": agent_meta,
    }


def main(provider_instance=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("-o", "--out")
    ap.add_argument("--cast", default=os.path.join(HERE, "cast.json"))
    ap.add_argument("--index", default=os.path.join(HERE, "aa_resources.json"))
    ap.add_argument("--llm", default=os.path.join(HERE, "llm.json"))
    ap.add_argument("--provider", help="覆盖 llm.json 里的 provider")
    ap.add_argument("--range", help="只处理这些台词行，如 1-80")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要发送的提示词，不调 API")
    a = ap.parse_args()

    opts = {
        "script": a.script,
        "out": a.out,
        "cast": a.cast,
        "index": a.index,
        "llm": a.llm,
        "provider": a.provider,
        "range": a.range,
        "dry_run": a.dry_run,
    }
    try:
        res = annotate_script(opts, provider_instance=provider_instance)
        print(f"改完之后:  python script2aap.py \"{res['out']}\" -o 工程名 --install")
    except Exception as e:
        sys.exit(f"\n标注错误: {e}")


if __name__ == "__main__":
    main()
