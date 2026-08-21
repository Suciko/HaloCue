# -*- coding: utf-8 -*-
"""
演出标注器：给纯台词剧本自动加上 表情 / 气泡 / 动作 / 背景 / 音效 / 停顿。

模型只输出标注，绝不改台词。产物是同格式的剧本文件，可以人工审改后再喂给
script2aap.py。任何超出资源表的标注都会被丢弃并告警——模型放不上不存在的东西。

用法:
  python annotate.py 剧本.txt -o 剧本.annotated.txt [--cast cast.json] [--provider openai]
  python annotate.py 剧本.txt --range 1-80          只标注前 80 行（先试水）
"""
import argparse, copy, hashlib, json, os, re, sys, uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from llm import make_provider, LLMError                       # noqa: E402
from script2aap import HEAD_RE, split_head, load_cast          # noqa: E402
from build_index import faces_of                               # noqa: E402
from asset_validation import extract_expression_capabilities   # noqa: E402
import assetdb                                                  # noqa: E402
from asset_catalog import (                                     # noqa: E402
    face_visual_evidence,
    merge_face_capabilities,
    merge_scene_capabilities,
)
from dialogue_pacing import split_strong_dialogue_items         # noqa: E402
from annotation_chunks import assign_annotation_ids             # noqa: E402
from annotation_memory import (                                 # noqa: E402
    AnnotationCheckpointStore,
    build_run_fingerprint,
)
from annotation_agent import AnnotationAgentError, run_annotation_agent  # noqa: E402
from annotation_protocol import (  # noqa: E402
    ANNOTATION_FIELDS, DIRECTION_FIELDS, LINE_REACTION_FIELDS,
)
from annotation_safety import (                                 # noqa: E402
    FX_PARTS as _FX_PARTS,
    filter_annotation_row,
    is_face_allowed,
    is_fx_allowed,
    project_effective_annotation_row,
)
from director_state import normalize_director                   # noqa: E402
from direction_rules import (                                  # noqa: E402
    apply_model_directions,
    mark_explicit_directions,
    normalize_direction_density,
    normalize_emoticon_density as _normalize_emoticon_density,
    supplement_directions,
)
from director_policy import dedupe_exact_beats, normalize_direction_plan  # noqa: E402
from direction_quality import classify_quality_issue                     # noqa: E402
from scene_asset_labeler import generator_background_keys            # noqa: E402
from official_face_examples import load_face_examples               # noqa: E402
import portrait_layout                                               # noqa: E402
from stage import Stage                                              # noqa: E402
import prompt as PROMPT                                        # noqa: E402
import tables                                                  # noqa: E402


PIPELINE_VERSION = "0.95"


_STORY_TYPES = frozenset({"auto", "main", "event", "bond"})
_LAYOUT_MODES = frozenset({"pure_ai", "ai", "rules"})
_IDENTITY_FACE_BLOCKLIST = {
    # These animations use Kei's red-eye / overridden-persona state inside
    # Aris's body. Normal Aris must never receive them by emotion matching.
    "아리스": frozenset({"12", "14", "15", "16", "17", "18", "19"}),
    "아리스N": frozenset({"12", "14", "15", "16", "17", "18", "19"}),
    "아리스NF": frozenset({"12", "14", "15", "16", "17", "18", "19"}),
}
_DIRECTIVE_FIELDS = {
    "bg": "bg", "trans": "trans", "place": "place", "move": "move",
    "bgshake": "shake", "bgfx": "bgfx", "se": "se", "sound": "se",
    "shot": "shot", "fx": "fx", "camera": "camera", "camera_hold": "camera_hold",
}


def normalize_story_type(value):
    normalized = str(value or "auto").strip().lower()
    if normalized not in _STORY_TYPES:
        raise ValueError("invalid_story_type")
    return normalized


def normalize_layout_mode(value):
    normalized = str(value or "ai").strip().lower()
    if normalized not in _LAYOUT_MODES:
        raise ValueError("invalid_layout_mode")
    return normalized


def reclassify_quality_diagnostics(diagnostics):
    """Apply current repair ownership to diagnostics restored from checkpoints."""
    return [
        classify_quality_issue(item)
        if isinstance(item, Mapping)
        and ("resolution" in item or "needs_review" in item)
        else copy.deepcopy(item)
        for item in diagnostics or []
    ]


def reconcile_quality_diagnostics_with_rendered_trace(diagnostics, trace_lines):
    """Retain pre-render findings while marking ones disproved by final trace."""
    camera_cuts = {
        str(row.get("source_id") or "")
        for row in trace_lines or []
        if isinstance(row, Mapping) and row.get("command") == "camera_cut"
    }
    result = []
    for diagnostic in diagnostics or []:
        row = copy.deepcopy(diagnostic)
        if (
            isinstance(row, Mapping)
            and row.get("code") == "closeup_requires_hard_cut"
            and str(row.get("anchor_id") or row.get("source_id") or "") in camera_cuts
        ):
            row["resolution"] = "deterministic"
            row["needs_review"] = False
            row["evidence_status"] = "superseded_by_rendered_trace"
            row["superseded_reason"] = "final_render_contains_camera_cut"
        result.append(row)
    return result


def _identity_safe_faces(identifier, values):
    blocked = _IDENTITY_FACE_BLOCKLIST.get(str(identifier), frozenset())
    return {str(value) for value in values if str(value) not in blocked}


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


def _spine_outfit_aliases(spine):
    base = str(spine or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not base:
        return set()
    aliases = {base}
    if base.endswith("_spr"):
        aliases.add(f"CharacterSpine_{base[:-4]}")
    if base.startswith("CharacterSpine_"):
        aliases.add(f"{base[len('CharacterSpine_'):]}_spr")
    return aliases


def _character_variant_selector(idx, character):
    """Resolve one exact labelled skeleton variant for a cast binding.

    Explicit binding metadata wins.  Older official catalogues only carry a
    Spine path, so its exact AA outfit aliases may recover a variant when the
    match is unique.  Ambiguous matches deliberately expose no scoped labels.
    """
    explicit = {
        "spine_signature": str(character.get("spine_signature") or ""),
        "outfit_key": str(character.get("outfit_key") or ""),
    }
    if explicit["spine_signature"] or explicit["outfit_key"]:
        return explicit

    ident = str(character.get("id") or "")
    capabilities = (idx.get("face_capabilities") or {}).get(ident, [])
    if not capabilities:
        return explicit
    record = next((
        item for item in idx.get("characters", [])
        if str(item.get("identifier") or "") == ident
    ), {})
    signature = str(record.get("spine_signature") or "")
    outfit = str(record.get("outfit_key") or "")
    aliases = _spine_outfit_aliases(record.get("spine"))
    if outfit:
        aliases.add(outfit)
    matches = [
        variant for variant in capabilities
        if (not signature or str(variant.get("spine_signature") or "") == signature)
        and (not aliases or str(variant.get("outfit_key") or "") in aliases)
    ]
    if len(matches) != 1 and not signature and not aliases:
        matches = list(capabilities) if len(capabilities) == 1 else []
    if len(matches) != 1:
        return explicit
    return {
        "spine_signature": str(matches[0].get("spine_signature") or ""),
        "outfit_key": str(matches[0].get("outfit_key") or ""),
    }


def face_allowlist(capabilities, identifier, *, spine_signature="", outfit_key=""):
    """Return only observed or verified faces for the chosen safe scope."""
    allow = set()
    for variant in _selected_variants(capabilities, identifier, spine_signature, outfit_key):
        for face in variant.get("faces", []):
            if {"aap_observed", "aa_verified"} & set(face.get("sources", [])):
                allow.add(face["id"])
    return _identity_safe_faces(identifier, allow)


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
            sources = set(face.get("sources", []))
            if "atlas_candidate" in sources or any(
                str(source).startswith("vision:") for source in sources
            ):
                allow.add(face["id"])
    return _identity_safe_faces(identifier, allow)


def semantic_face_allowlist(capabilities, identifier, *, spine_signature="", outfit_key=""):
    """Return parsed, non-special face animations for a semantic modular bone."""
    allow = set()
    for variant in _selected_variants(capabilities, identifier, spine_signature, outfit_key):
        for face in variant.get("faces", []):
            if "spine_semantic" in set(face.get("sources", [])):
                allow.add(face["id"])
    return _identity_safe_faces(identifier, allow)


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
        if face_visual_evidence(face) in {"visual_confirmed", "asset_semantic"}
        and (face.get("semantic_cn") or face.get("cn") or face.get("label"))
        and not (
            face.get("active_label_model")
            and isinstance(face.get("confidence"), (int, float))
            and not isinstance(face.get("confidence"), bool)
            and face.get("confidence") <= 0
        )
        and not str(
            face.get("semantic_cn") or face.get("cn") or face.get("label") or ""
        ).strip().casefold().startswith(("无法识别", "不可识别", "无法判断", "unknown"))
    ]


def _scoped_face_evidence(
    capabilities, identifier, allowed, *, spine_signature="", outfit_key=""
):
    evidence = {}
    for variant in _selected_variants(
        capabilities, identifier, spine_signature, outfit_key
    ):
        for face in variant.get("faces", []):
            face_id = face.get("id")
            if face_id in allowed:
                evidence[face_id] = face_visual_evidence(face)
    return evidence


def annotation_constraints(idx, cast, *, usage_chain=None):
    """Build the complete allowlist used to filter one model response.

    The result is plain data so it can be tested independently from an LLM call.
    Semantic atlas parts intentionally never enter ``faces_by_id``.
    """
    capabilities = idx.get("face_capabilities") or {}
    character_records = {
        record.get("identifier"): record
        for record in idx.get("characters", [])
        if record.get("identifier")
    }
    semantic_modular = {
        record.get("identifier")
        for record in character_records.values()
        if record.get("expression_mode") == "semantic_modular"
    }
    semantic_modular |= {
        character.get("id")
        for character in cast.values()
        if character.get("_expression_mode") == "semantic_modular"
    }
    faces_by_id = {}
    face_evidence_by_id = {}
    face_records_by_id = {}
    if capabilities:
        for character in cast.values():
            ident = character.get("id")
            if ident:
                selector = _character_variant_selector(idx, character)
                official = ident in character_records and not character.get("custom")
                faces_by_id[ident] = (
                    semantic_face_allowlist(capabilities, ident, **selector)
                    if ident in semantic_modular
                    else official_basic_face_allowlist(capabilities, ident, **selector)
                    if official
                    else face_allowlist(capabilities, ident, **selector)
                )
                face_evidence_by_id[ident] = _scoped_face_evidence(
                    capabilities, ident, faces_by_id[ident], **selector
                )
                face_records_by_id[ident] = _allowed_face_records(
                    capabilities,
                    ident,
                    **selector,
                    semantic=ident in semantic_modular,
                    official_basic=official and ident not in semantic_modular,
                )
    else:
        faces_by_id = {
            character["identifier"]: _identity_safe_faces(
                character["identifier"],
                {face["id"] for face in character["faces"]},
            )
            for character in idx.get("characters", []) if character.get("faces")
        }
        # Legacy character catalogs predate evidence metadata, but their face
        # table is still asset-derived. Historical project usage is not enough
        # to add another model-selectable face.
        face_evidence_by_id = {
            ident: {face_id: "asset_semantic" for face_id in face_ids}
            for ident, face_ids in faces_by_id.items()
        }
        face_records_by_id = {
            str(character.get("identifier")): [
                face for face in character.get("faces", [])
                if str(face.get("id") or "")
                not in _IDENTITY_FACE_BLOCKLIST.get(
                    str(character.get("identifier") or ""), frozenset()
                )
            ]
            for character in idx.get("characters", [])
            if character.get("identifier")
        }
        for ident, faces in (idx.get("faces_used") or {}).items():
            faces_by_id.setdefault(
                ident,
                _identity_safe_faces(ident, {face["id"] for face in faces}),
            )
            if ident not in face_evidence_by_id:
                face_evidence_by_id[ident] = {
                    face["id"]: "context_inferred" for face in faces
                }
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
    profiles_by_id = portrait_layout.profiles_for_cast(
        idx,
        cast,
        catalog_fallback=not isinstance(idx.get("portrait_layout_catalog"), dict),
    )
    return {
        "faces_by_id": faces_by_id,
        "face_evidence_by_id": face_evidence_by_id,
        "face_records_by_id": face_records_by_id,
        "sym2cn": sym2cn,
        "ok_emo": set(sym2cn) | set(sym2cn.values()),
        "ok_act": {value["verb"] for value in idx["enums"]["action"].values()},
        "ok_fx": _FX_PARTS,
        "ok_se": set(idx.get("sounds", [])),
        "ok_bg": generator_background_keys(idx) | confirmed_backgrounds,
        "ok_bgfx": set(tables.BGEFFECT) | set(tables.BGFX_CN),
        "confirmed_bg": confirmed_backgrounds,
        "ok_shot": {
            name for name, character in cast.items()
            if character.get("portrait") and not character.get("narrator")
        },
        "portrait_profiles_by_name": {
            name: profiles_by_id.get(str(character.get("id") or ""), {})
            for name, character in cast.items()
            if isinstance(character, Mapping)
        },
    }


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
    active = False
    reset_at_next_line = False
    for item in items:
        if item.get("kind") != "line":
            raw = str(item.get("raw") or "").strip()
            if raw.startswith("##") and active:
                reset_at_next_line = True
                reset_next_line = False
                active = False
            continue
        director = item.get("_director")
        continuity = director.get("continuity") if isinstance(director, Mapping) else None
        command = continuity.get("bgfx", "none") if isinstance(continuity, Mapping) else "none"
        current = item.get("bgfx")
        if command == "end" or (reset_at_next_line and not current):
            item["bgfx"] = "无"
            current = "无"
            active = False
            reset_next_line = False
            reset_at_next_line = False
        elif reset_next_line and not current and command != "hold":
            item["bgfx"] = "无"
            current = "无"
            active = False
            reset_next_line = False
        elif reset_at_next_line and current:
            reset_at_next_line = False
        pending_transient_reset = reset_next_line
        reset_next_line = False
        if not current:
            if command == "hold" and pending_transient_reset:
                reset_next_line = True
            continue
        value, error = tables.resolve_bgeffect(current)
        if error:
            continue
        if not value:
            active = False
            reset_next_line = False
            continue
        active = True
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
    director = item.get("_director")
    if not isinstance(director, Mapping):
        if item.get("_camera_reset"):
            directives.append("@camera_hold auto")
        if item.get("reveal"):
            side = {"left": "左", "right": "右"}.get(str(item["reveal"]), "")
            directives.append(f"@reveal {item['who']}" + (f" {side}" if side else ""))
        return directives
    intent = item.get("_director_intent")
    position_directives = []
    if isinstance(intent, Mapping):
        layout_fields = ("relation_distance", "focus_character", "reaction_target")
        if any(key in intent for key in layout_fields):
            displayable_names = set(item.get("_displayable_names") or ())
            layout = {
                key: director.get(key)
                for key in layout_fields
                if key in intent
                and (
                    key == "relation_distance"
                    or not displayable_names
                    or str(director.get(key) or "") in displayable_names
                    or not str(director.get(key) or "")
                )
            }
            visible_layout_people = {
                str(layout.get(key) or "")
                for key in ("focus_character", "reaction_target")
                if str(layout.get(key) or "")
            }
            if "relation_distance" in layout and len(visible_layout_people) != 2:
                layout.pop("relation_distance", None)
            if layout:
                directives.append(
                    "@layout " + json.dumps(layout, ensure_ascii=False, separators=(",", ":"))
                )
        if "positions" in intent and not (
            set(item.get("_explicit_directives", ())) & {"move", "stage"}
        ):
            positions = director.get("positions")
            if isinstance(positions, Mapping):
                for name, slot in positions.items():
                    position_directives.append(f"@move {name} {slot}")
    visibility_is_explicit = (
        "visible_characters" in intent
        if isinstance(intent, Mapping)
        else "visible_characters" in director
    )
    if visibility_is_explicit:
        visible = list(dict.fromkeys(
            str(name) for name in director.get("visible_characters", []) if str(name)
        ))[:3]
        camera_command = (
            "camera_cut"
            if isinstance(intent, Mapping) and intent.get("shot_transition") == "cut"
            else "camera_hold"
        )
        directives.append(
            f"@{camera_command} {','.join(visible)}" if visible else f"@{camera_command} -"
        )
    elif item.get("_camera_reset"):
        directives.append("@camera_hold auto")
    # A cut must be declared before its target slots. Otherwise the source reads
    # like a visible move that is immediately swallowed by a hard cut. For a
    # held/reframed shot these same directives remain real on-screen movement.
    directives.extend(position_directives)
    if item.get("reveal"):
        side = {"left": "左", "right": "右"}.get(str(item["reveal"]), "")
        directives.append(f"@reveal {item['who']}" + (f" {side}" if side else ""))
    continuity = director.get("continuity")
    fx_command = continuity.get("fx") if isinstance(continuity, Mapping) else "none"
    target = str(director.get("focus_character") or "")
    if not target and item.get("_speaker_has_portrait"):
        target = str(item.get("who") or "")
    if target and fx_command == "end":
        directives.append(f"@fx {target} 无")
    elif target and fx_command in {"start", "escalate"} and item.get("fx"):
        directives.append(f"@fx {target} {item['fx']}")
    return directives


def _has_explicit_fx_lifecycle(item):
    director = item.get("_director")
    continuity = director.get("continuity") if isinstance(director, Mapping) else None
    return (
        isinstance(continuity, Mapping)
        and continuity.get("fx") in {"start", "escalate", "end"}
        and bool(item.get("fx"))
    )


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

def build_static(idx, cast, cast_names, *, story_type="auto", layout_mode="ai",
                 official_db_path=None, dynamic_face_shortlists=False,
                 planned_execution=False):
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
            selector = _character_variant_selector(idx, character)
            faces_by_id[ident] = {
                "faces": _allowed_face_records(
                    capabilities,
                    ident,
                    **selector,
                    semantic=expression_mode == "semantic_modular",
                    official_basic=ident in character_records and not character.get("custom"),
                ),
                "expression_mode": expression_mode,
                "expression_parts": character.get(
                    "_expression_parts", record.get("expression_parts", [])
                ),
            }
        face_examples = load_face_examples(
            cast, faces_by_id, db_path=official_db_path
        )
        return PROMPT.build_system(
            idx, cast, cast_names, faces_by_id, story_type=story_type,
            layout_mode=layout_mode, face_examples=face_examples,
            dynamic_face_shortlists=dynamic_face_shortlists,
            planned_execution=planned_execution,
        )
    faces_by_id = {c["identifier"]: c["faces"] for c in idx["characters"] if c["faces"]}
    for ident, fs in (idx.get("faces_used") or {}).items():
        faces_by_id.setdefault(ident, fs)
    face_examples = load_face_examples(
        cast, faces_by_id, db_path=official_db_path
    )
    return PROMPT.build_system(
        idx, cast, cast_names, faces_by_id, story_type=story_type,
        layout_mode=layout_mode, face_examples=face_examples,
        dynamic_face_shortlists=dynamic_face_shortlists,
        planned_execution=planned_execution,
    )


def build_annotation_static_system(static_rules, source_text, *, source_context_strategy="preserve"):
    if source_context_strategy in {"window", "planned_window"}:
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
    pending_directives = set()
    authored_camera_hold = False
    for item in out:
        if item.get("kind") != "line":
            raw = str(item.get("raw") or "")
            structural_boundary = (
                raw.strip() == "---"
                or bool(re.match(r"^\s*#{1,6}\s+", raw))
            )
            scene_directive = bool(re.match(r"^\s*@(bg|place)\b", raw, re.IGNORECASE))
            if structural_boundary:
                pending_directives.clear()
                authored_camera_hold = False
            elif scene_directive:
                authored_camera_hold = False
            match = re.match(r"^\s*@([A-Za-z_]+)\b\s*(.*)$", raw)
            if match and match.group(1).lower() in _DIRECTIVE_FIELDS:
                command = match.group(1).lower()
                pending_directives.add(_DIRECTIVE_FIELDS[command])
                if command == "camera_hold":
                    authored_camera_hold = match.group(2).strip().lower() not in {"auto", "自动"}
                elif command == "camera":
                    authored_camera_hold = False
            continue
        effective_directives = set(pending_directives)
        if authored_camera_hold:
            effective_directives.add("camera_hold")
        if effective_directives:
            item["_explicit_directives"] = tuple(sorted(effective_directives))
            if pending_directives:
                item["_explicit_directive_starts"] = tuple(sorted(pending_directives))
            item["_explicit_direction_fields"] = tuple(sorted(
                set(item.get("_explicit_direction_fields", ()))
                | (effective_directives - {"camera", "camera_hold"})
            ))
        pending_directives.clear()
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
    if item.get("fx") and not _has_explicit_fx_lifecycle(item):
        anno += f"<{item['fx']}>"
    return f"{item['who']}{anno}: {item['text']}"


def render_annotated_items_with_trace(items):
    """Render annotated items and return a source-identity trace sidecar."""
    out_lines = []
    trace_lines = []
    last_bg = None
    last_camera_signature = None
    has_background = False
    has_rendered_line = False

    def apply_physical_camera_change(*, add=(), remove=(), position_updates=None):
        """Advance camera dedupe state in the same order as emitted commands."""
        nonlocal last_camera_signature
        if last_camera_signature is None:
            return
        visible = list(last_camera_signature[0])
        positions = dict(last_camera_signature[1])
        removed = {str(name) for name in remove if str(name)}
        if removed:
            visible = [name for name in visible if name not in removed]
            for name in removed:
                positions.pop(name, None)
        for name in add:
            name = str(name or "")
            if name and name not in visible:
                visible.append(name)
        for name, slot in dict(position_updates or {}).items():
            if (
                str(name or "")
                and isinstance(slot, int) and not isinstance(slot, bool)
                and 1 <= slot <= 5
            ):
                positions[str(name)] = slot
        last_camera_signature = (tuple(visible[:3]), tuple(sorted(positions.items())))

    def origin(item, kind, *, command="", target=""):
        return {
            "line": len(out_lines) + 1,
            "kind": kind,
            "command": command,
            "source_id": str(item.get("annotation_id") or item.get("_anchor_id") or ""),
            "beat_id": str(item.get("_beat_id") or ""),
            "scene_id": str(item.get("_annotation_scene_id") or item.get("_scene_id") or ""),
            "chunk_id": str(item.get("_annotation_chunk_id") or item.get("_chunk_id") or ""),
            "plan_event_ids": list(item.get("_plan_event_ids") or []),
            "who": str(item.get("who") or ""),
            "target": str(target or ""),
        }

    def emit(text, item, kind, *, command="", target=""):
        trace_entry = origin(item, kind, command=command, target=target)
        out_lines.append(str(text))
        trace_lines.append(trace_entry)

    for item in items:
        if item["kind"] != "line":
            emit(item["raw"], item, "source")
            raw = str(item.get("raw") or "").strip()
            if (
                raw == "---"
                or re.match(r"^#{1,6}\s+", raw)
                or re.match(r"^@(bg|place)\b", raw, re.IGNORECASE)
            ):
                last_camera_signature = None
            continue

        background = item.get("bg")
        background_changed = bool(background and background != last_bg)
        if background_changed:
            emit(f"@bg {background}", item, "directive", command="bg")
            last_bg = background
        if item.get("trans") and (
            not background or (background_changed and (has_background or has_rendered_line))
        ):
            emit(f"@trans {item['trans']}", item, "directive", command="trans")
        if background_changed:
            has_background = True
        if item.get("bgfx"):
            emit(f"@bgfx {item['bgfx']}", item, "directive", command="bgfx")
        if item.get("place"):
            emit(f"@place {item['place']}", item, "directive", command="place")
        for entry in item.get("_beat_enter", ()):
            side = {"left": "左", "right": "右"}.get(str(entry.get("side") or ""), "")
            slot = int(entry.get("slot") or 0)
            suffix = " ".join(value for value in (str(slot) if slot else "", side) if value)
            emit(f"@enter {entry['who']}" + (f" {suffix}" if suffix else ""), item, "directive", command="enter", target=entry["who"])
            apply_physical_camera_change(
                add=[entry.get("who")],
                position_updates={entry.get("who"): slot} if slot else {},
            )
        for entry in item.get("_beat_reveal", ()):
            side = {"left": "左", "right": "右"}.get(str(entry.get("side") or ""), "")
            slot = int(entry.get("slot") or 0)
            suffix = " ".join(value for value in (str(slot) if slot else "", side) if value)
            emit(f"@reveal {entry['who']}" + (f" {suffix}" if suffix else ""), item, "directive", command="reveal", target=entry["who"])
            apply_physical_camera_change(
                add=[entry.get("who")],
                position_updates={entry.get("who"): slot} if slot else {},
            )
        for entry in item.get("_beat_conceal", ()):
            side = {"left": "左", "right": "右"}.get(str(entry.get("side") or ""), "")
            emit(f"@conceal {entry['who']}" + (f" {side}" if side else ""), item, "directive", command="conceal", target=entry["who"])
            apply_physical_camera_change(remove=[entry.get("who")])
        for entry in item.get("_beat_exit", ()):
            side = {"left": "左", "right": "右"}.get(str(entry.get("side") or ""), "")
            emit(f"@exit {entry['who']}" + (f" {side}" if side else ""), item, "directive", command="exit", target=entry["who"])
            apply_physical_camera_change(remove=[entry.get("who")])
        if item.get("move"):
            emit(f"@move {item['who']} {item['move']}", item, "directive", command="move", target=item["who"])
            apply_physical_camera_change(
                position_updates={item.get("who"): item.get("move")},
            )
        if item.get("shake"):
            emit("@bgshake", item, "directive", command="bgshake")
        if item.get("se"):
            emit(f"@se {item['se']}", item, "directive", command="se")
        if item.get("wait_ms"):
            emit(f"@wait {item['wait_ms']}", item, "directive", command="wait")
        if item.get("_annotation_beat"):
            emit("@nodialog", item, "directive", command="nodialog")
        for reaction in item.get("_beat_reactions", ()):
            emit(
                "@react " + json.dumps(reaction, ensure_ascii=False, separators=(",", ":")),
                item, "directive", command="react",
            )
        for reaction in item.get("_reactions", ()):
            emit(
                "@react " + json.dumps(reaction, ensure_ascii=False, separators=(",", ":")),
                item, "directive", command="react", target=str(reaction.get("who") or ""),
            )
        directives_item = item
        director_intent = item.get("_director_intent")
        director = item.get("_director")
        if item.get("_camera_reset"):
            last_camera_signature = None
        if (
            item.get("_annotation_beat")
            and isinstance(director_intent, Mapping)
            and "visible_characters" in director_intent
            and isinstance(director, Mapping)
        ):
            visible = tuple(
                str(name) for name in director.get("visible_characters", []) if str(name)
            )
            positions = director.get("positions")
            position_signature = tuple(sorted(
                (str(name), int(slot))
                for name, slot in positions.items()
                if isinstance(positions, Mapping)
                and isinstance(slot, int)
                and not isinstance(slot, bool)
            )) if isinstance(positions, Mapping) else ()
            signature = (visible, position_signature)
            if signature == last_camera_signature and not director_intent.get("shot_transition"):
                # The beat still contributes its wait/face/action, but its
                # unchanged layout must not create a fake camera declaration.
                directives_item = copy.copy(item)
                directives_item.pop("_director", None)
                directives_item.pop("_director_intent", None)
            else:
                last_camera_signature = signature
        elif isinstance(director_intent, Mapping) and "visible_characters" in director_intent and isinstance(director, Mapping):
            visible = tuple(
                str(name) for name in director.get("visible_characters", []) if str(name)
            )
            positions = director.get("positions")
            signature = (
                visible,
                tuple(sorted(
                    (str(name), int(slot))
                    for name, slot in positions.items()
                    if isinstance(positions, Mapping)
                    and isinstance(slot, int)
                    and not isinstance(slot, bool)
                )) if isinstance(positions, Mapping) else (),
            )
            transition = str(
                director_intent.get("shot_transition")
                or director.get("shot_transition")
                or ""
            )
            shot_operation = str(
                director_intent.get("shot_operation")
                or director.get("shot_operation")
                or ""
            )
            # ``switch_group`` means "establish the selected group".  If it
            # selects the exact same visible characters and slots as the
            # already-rendered shot, a second camera_cut is a provable no-op
            # even when the model also says ``shot_transition=cut``.  Keep
            # semantically distinct operations (impact_insert and
            # replace_center_subject): those may intentionally cut to the
            # same roster while changing the visual emphasis.  This is a
            # deterministic duplicate check, not a camera-count preference.
            same_signature_switch = (
                signature == last_camera_signature
                and transition == "cut"
                and shot_operation == "switch_group"
            )
            if signature == last_camera_signature and (
                transition != "cut" or same_signature_switch
            ):
                # A dialogue row can change focus or relation metadata while
                # keeping exactly the same visible people and slots. Preserve
                # that semantic layout, but do not serialize a second camera
                # hold and the same moves. This is a provable no-op, not an
                # aesthetic filter.
                directives_item = copy.copy(item)
                suppressed_director = dict(director)
                suppressed_intent = dict(director_intent)
                for field in ("visible_characters", "positions", "shot_transition"):
                    suppressed_director.pop(field, None)
                    suppressed_intent.pop(field, None)
                    item.setdefault("_render_direction_drops", []).append({
                        "field": field,
                        "reason": "render_dedup_unchanged_camera_signature",
                    })
                directives_item["_director"] = suppressed_director
                directives_item["_director_intent"] = suppressed_intent
            last_camera_signature = signature
        if (
            item.get("_annotation_beat")
            and isinstance(director_intent, Mapping)
            and director_intent.get("shot_operation") == "continue_group"
            and not director_intent.get("shot_transition")
        ):
            # continue_group is explicitly a hold; it must not serialize a
            # fresh camera declaration for an otherwise unchanged Wait beat.
            directives_item = copy.copy(item)
            directives_item.pop("_director", None)
            directives_item.pop("_director_intent", None)
        for directive in annotation_directives(directives_item):
            match = re.match(r"^@([A-Za-z_]+)", directive)
            emit(
                directive, item, "directive",
                command=match.group(1).lower() if match else "",
            )
        if item.get("reveal"):
            apply_physical_camera_change(add=[item.get("who")])
        emit(render(item), item, "line")
        has_rendered_line = True

    rendered = "\n".join(out_lines) + "\n"
    return rendered, {
        "schema_version": 1,
        "annotated_source_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "lines": trace_lines,
    }


def render_annotated_items(items):
    """Compatibility wrapper returning only rendered source text."""
    return render_annotated_items_with_trace(items)[0]


def build_model_output_audit(
    chunk_outputs, items, trace_lines, diagnostics, *, policy_beats=(),
):
    """Trace each explicit model field through protocol, policy and AAP output."""
    missing = object()
    item_by_source = {
        str(item.get("annotation_id") or ""): item
        for item in items if str(item.get("annotation_id") or "")
    }
    render_drops_by_source = {
        str(item.get("annotation_id") or ""): {
            str(drop.get("field") or ""): str(drop.get("reason") or "")
            for drop in item.get("_render_direction_drops") or ()
            if isinstance(drop, Mapping) and str(drop.get("field") or "")
        }
        for item in items
        if str(item.get("annotation_id") or "")
    }
    # Mirror the writer's deterministic transition suppression so provenance
    # can explain why a valid model value intentionally has no AAP command.
    suppressed_transitions = {}
    last_background = None
    has_background = False
    has_rendered_line = False
    for item in items:
        if item.get("kind") != "line":
            continue
        background = item.get("bg")
        background_changed = bool(background and background != last_background)
        transition = str(item.get("trans") or "")
        can_emit_transition = bool(
            transition
            and (
                not background
                or (background_changed and (has_background or has_rendered_line))
            )
        )
        if transition and not can_emit_transition:
            source_id = str(item.get("annotation_id") or "")
            if source_id:
                suppressed_transitions[source_id] = (
                    "initial_background_transition_suppressed"
                    if background_changed and not (has_background or has_rendered_line)
                    else "redundant_background_transition_suppressed"
                )
        if background_changed:
            last_background = background
            has_background = True
        has_rendered_line = True
    beat_by_id = {
        str(beat.get("beat_id") or ""): beat
        for beat in policy_beats or ()
        if isinstance(beat, Mapping) and str(beat.get("beat_id") or "")
    }
    trace_by_source = {}
    trace_by_beat = {}
    for entry in trace_lines or ():
        row = dict(entry)
        source_id = str(row.get("source_id") or "")
        beat_id = str(row.get("beat_id") or "")
        if source_id:
            trace_by_source.setdefault(source_id, []).append(row)
        if beat_id:
            trace_by_beat.setdefault(beat_id, []).append(row)

    diagnostic_by_source = {}
    for diagnostic in diagnostics or ():
        source_id = str(diagnostic.get("source_id") or diagnostic.get("anchor_id") or "")
        if not source_id:
            continue
        diagnostic_by_source.setdefault(source_id, []).append({
            key: copy.deepcopy(value)
            for key, value in diagnostic.items()
            if value not in (None, "")
        })

    command_fields = {
        "visible_characters": {"camera", "camera_hold", "camera_cut"},
        "positions": {"move"},
        "shot_transition": {"camera", "camera_hold", "camera_cut"},
        "relation_distance": {"layout"},
        "focus_kind": {"layout"},
        "focus_character": {"layout"},
        "reaction_target": {"layout"},
        "move": {"move"}, "reveal": {"reveal"}, "conceal": {"conceal"},
        "enter": {"enter"}, "exit": {"exit"}, "reactions": {"react"},
        "wait_ms": {"wait"}, "se": {"se"}, "bg": {"bg"},
        "place": {"place"}, "trans": {"trans"}, "bgfx": {"bgfx"},
        "shake": {"bgshake"},
    }
    line_embedded_fields = {"face", "emo", "act", "fx", "shot"}
    stateful_direction_fields = (set(DIRECTION_FIELDS) - set(command_fields)) | {
        "focus_kind",
    }
    stateful_beat_fields = {"position", "who", "reason", "shot_operation"}

    def is_empty(value):
        return value is None or value == "" or value is False or value == 0 or value == [] or value == {}

    def source_diagnostics(source_id, field, layer):
        aliases = {field}
        if field == "visible_characters":
            aliases.add("camera")
        if layer == "beat":
            aliases.add("beat")
        matched = [
            copy.deepcopy(row)
            for row in diagnostic_by_source.get(source_id, ())
            if not row.get("field") or str(row.get("field")) in aliases
        ]
        # A field-specific resource or policy finding explains a field loss.
        # General G1 diagnostics remain useful context, but must not replace
        # the exact loss reason merely because they were emitted earlier.
        return sorted(
            matched,
            key=lambda row: 0 if str(row.get("field") or "") in aliases else 1,
        )

    def field_trace(source_id, beat_id, field, layer):
        rows = trace_by_beat.get(beat_id, ()) if beat_id else trace_by_source.get(source_id, ())
        commands = command_fields.get(field)
        if commands:
            return [copy.deepcopy(row) for row in rows if str(row.get("command") or "") in commands]
        if field in line_embedded_fields or (layer == "beat" and field in {"face", "emo", "act", "fx"}):
            return [copy.deepcopy(row) for row in rows if str(row.get("kind") or "") == "line"]
        return []

    def decision(
        *, chunk_id, source_id, layer, field, origin, raw_value,
        expanded_value=missing, validated_value=missing, policy_value=missing,
        beat_id="", validation_diagnostics=(),
    ):
        field_diagnostics = source_diagnostics(source_id, field, layer)
        authored_fields = set(
            (item_by_source.get(source_id) or {}).get("_explicit_direction_fields")
            or ()
        )
        field_aliases = {field}
        if field == "visible_characters":
            field_aliases.add("camera")
        field_diagnostics.extend(
            copy.deepcopy(row)
            for row in validation_diagnostics
            if isinstance(row, Mapping)
            and (
                not row.get("source_id")
                or str(row.get("source_id")) == source_id
            )
            and str(row.get("field") or "") in field_aliases
            and row not in field_diagnostics
        )
        rendered = field_trace(source_id, beat_id, field, layer)
        render_drop_reason = (
            render_drops_by_source.get(source_id, {}).get(field)
            if layer == "direction" else None
        )
        if policy_value is not missing and is_empty(policy_value) and not is_empty(raw_value):
            rendered = []
        discard_reason = ""
        loss_stage = ""
        if is_empty(raw_value):
            status = "explicit_empty"
        elif field in authored_fields:
            # The source author owns this directive. Keep the model value in
            # provenance, but do not report the intentional override as loss.
            status = "applied_or_stateful"
            discard_reason = "authored_source_precedence"
        elif expanded_value is missing:
            status = "missing_after_protocol"
            loss_stage = "protocol_expansion"
            discard_reason = "missing_after_protocol_expansion"
        elif validated_value is missing:
            status = "missing_after_validation"
            loss_stage = "validation"
            discard_reason = "missing_after_validation"
        elif is_empty(validated_value) and not is_empty(raw_value):
            status = "missing_after_validation"
            loss_stage = "validation"
            validation_drop = next(
                (
                    row for row in field_diagnostics
                    if str(row.get("code") or "").startswith(("director_", "validation_"))
                ),
                None,
            )
            discard_reason = str(
                (validation_drop or {}).get("message")
                or (validation_drop or {}).get("code")
                or "validation_removed_nonempty_value"
            )
        elif policy_value is missing:
            policy_drop = next(
                (
                    row for row in field_diagnostics
                    if row.get("code") in {
                        "director_resource_downgraded",
                        "director_unverified_face",
                        "director_policy_drop",
                    }
                ),
                None,
            )
            diagnostic = policy_drop or (field_diagnostics[0] if field_diagnostics else {})
            discard_reason = str(
                diagnostic.get("reason") or diagnostic.get("message")
                or diagnostic.get("code") or "missing_after_policy"
            )
            if discard_reason.startswith("redundant_") or discard_reason == "duplicate_reaction_beat":
                status = "applied_or_stateful"
            else:
                status = "missing_after_policy"
                loss_stage = "policy"
        elif is_empty(policy_value) and not is_empty(validated_value):
            deterministic = next(
                (row for row in field_diagnostics if row.get("resolution") == "deterministic"),
                None,
            )
            if deterministic:
                status = "applied_or_stateful"
                discard_reason = str(
                    deterministic.get("reason") or deterministic.get("message")
                    or deterministic.get("code") or "deterministic_policy_repair"
                )
            else:
                status = "missing_after_policy"
                loss_stage = "policy"
                discard_reason = str(
                    (field_diagnostics[0] if field_diagnostics else {}).get("message")
                    or "policy_replaced_nonempty_value_with_empty"
                )
        elif render_drop_reason and not is_empty(policy_value):
            status = "applied_or_stateful"
            discard_reason = render_drop_reason
        elif field == "trans" and source_id in suppressed_transitions:
            status = "applied_or_stateful"
            discard_reason = suppressed_transitions[source_id]
        elif (
            layer == "direction"
            and field == "relation_distance"
            and str(
                ((item_by_source.get(source_id) or {}).get("_director_intent") or {}).get(
                    "focus_kind"
                )
                or ""
            ) == "offscreen_space"
            and not (
                ((item_by_source.get(source_id) or {}).get("_director_intent") or {}).get(
                    "visible_characters"
                )
            )
        ):
            status = "applied_or_stateful"
            discard_reason = "offscreen_space_has_no_layout"
        elif rendered:
            status = "applied_or_stateful" if layer == "direction" else "applied"
        elif layer == "beat" and field in {"visible_characters", "positions", "shot_transition"}:
            status = "applied_or_stateful"
            discard_reason = "render_dedup_unchanged_camera_signature"
        elif layer == "direction" and field == "shot_transition" and any(
            row.get("code") == "director_policy_drop"
            and row.get("reason") == "redundant_camera_restatement"
            for row in diagnostic_by_source.get(source_id, ())
        ):
            status = "applied_or_stateful"
            discard_reason = "redundant_camera_restatement"
        elif (layer == "direction" and field in stateful_direction_fields) or (
            layer == "beat" and field in stateful_beat_fields
        ) or layer in {"state_delta", "memory_event"}:
            status = "applied_or_stateful"
        else:
            status = "missing_after_policy"
            loss_stage = "render"
            discard_reason = "not_compiled_to_aap"

        result = {
            "source_id": source_id,
            "chunk_id": str(chunk_id),
            "layer": layer,
            "field": field,
            "origin": origin,
            "ai_raw_value": copy.deepcopy(raw_value),
            "expanded_value": None if expanded_value is missing else copy.deepcopy(expanded_value),
            "validated_value": None if validated_value is missing else copy.deepcopy(validated_value),
            "policy_value": None if policy_value is missing else copy.deepcopy(policy_value),
            "final_aap_trace": rendered,
            "status": status,
            "diagnostics": field_diagnostics,
            "discard_reason": discard_reason,
        }
        if beat_id:
            result["beat_id"] = beat_id
        if loss_stage:
            result["loss_stage"] = loss_stage
        return result

    summary = {
        "attempts": 0,
        "accepted_attempts": 0,
        "explicit_decisions": 0,
        "superseded_decisions": 0,
        "explicit_empty": 0,
        "missing_after_protocol": 0,
        "missing_after_validation": 0,
        "missing_after_policy": 0,
        "missing_after_render": 0,
        "applied": 0,
        "applied_or_stateful": 0,
        "rejected_attempt_decisions": 0,
        "rejected_attempt_statuses": {},
        "director_fields": {
            "raw_top_level": 0,
            "raw_nested_d": 0,
            "expanded": 0,
            "direction_intent": 0,
            "compiled_to_aap": 0,
            "rejected_attempts": {
                "raw_top_level": 0,
                "raw_nested_d": 0,
                "expanded": 0,
                "direction_intent": 0,
                "compiled_to_aap": 0,
            },
        },
    }

    def record_summary(row, *, authoritative):
        if not authoritative:
            summary["rejected_attempt_decisions"] += 1
            status = str(row.get("status") or "")
            rejected = summary["rejected_attempt_statuses"]
            rejected[status] = int(rejected.get(status) or 0) + 1
            return
        summary["explicit_decisions"] += 1
        status = str(row.get("status") or "")
        loss_stage = str(row.get("loss_stage") or "")
        if loss_stage == "protocol_expansion":
            summary["missing_after_protocol"] += 1
        elif loss_stage == "validation":
            summary["missing_after_validation"] += 1
        elif loss_stage == "policy":
            summary["missing_after_policy"] += 1
        elif loss_stage == "render":
            summary["missing_after_render"] += 1
        elif status in summary:
            summary[status] += 1

    audit_chunks = []
    for chunk_id, chunk in (chunk_outputs or {}).items():
        if not isinstance(chunk, Mapping):
            continue
        default_target_ids = [str(value) for value in chunk.get("target_ids") or []]
        final_rows = chunk.get("lines_by_id") or {}
        chunk_attempts = []
        for attempt in chunk.get("model_attempts") or []:
            if not isinstance(attempt, Mapping):
                continue
            summary["attempts"] += 1
            if attempt.get("outcome") == "accepted":
                summary["accepted_attempts"] += 1
            authoritative = attempt.get("outcome") == "accepted"
            director_summary = (
                summary["director_fields"]
                if authoritative else summary["director_fields"]["rejected_attempts"]
            )
            target_ids = [str(value) for value in attempt.get("target_ids") or default_target_ids]
            raw_response = attempt.get("response") if isinstance(attempt.get("response"), Mapping) else {}
            expanded_response = (
                attempt.get("expanded_response")
                if isinstance(attempt.get("expanded_response"), Mapping)
                else {}
            )
            validated_response = (
                attempt.get("validated_response")
                if isinstance(attempt.get("validated_response"), Mapping)
                else {}
            )
            validation_diagnostics = [
                copy.deepcopy(row)
                for row in validated_response.get("diagnostics") or []
                if isinstance(row, Mapping)
            ]
            expanded_lines = {
                str(row.get("source_id") or ""): row
                for row in expanded_response.get("lines") or []
                if isinstance(row, Mapping) and str(row.get("source_id") or "")
            }
            validated_rows = validated_response.get("lines_by_id") or {}
            decisions = []

            for raw_line in raw_response.get("lines") or []:
                if not isinstance(raw_line, Mapping):
                    continue
                index = raw_line.get("i")
                source_id = str(raw_line.get("source_id") or "")
                if not source_id and isinstance(index, int) and not isinstance(index, bool) and 1 <= index <= len(target_ids):
                    source_id = target_ids[index - 1]
                nested_d = raw_line.get("d") if isinstance(raw_line.get("d"), Mapping) else {}
                nested_direction = (
                    raw_line.get("direction")
                    if isinstance(raw_line.get("direction"), Mapping)
                    else {}
                )
                expanded_row = expanded_lines.get(source_id) or {}
                validated_row = validated_rows.get(source_id) or {}
                applied_item = item_by_source.get(source_id) or {}
                for field in ANNOTATION_FIELDS:
                    if field in raw_line:
                        raw_value, origin = raw_line[field], "top_level"
                    elif field in nested_d:
                        raw_value, origin = nested_d[field], "nested_d"
                    else:
                        continue
                    row = decision(
                        chunk_id=chunk_id, source_id=source_id, layer="annotation",
                        field=field, origin=origin, raw_value=raw_value,
                        expanded_value=expanded_row[field] if field in expanded_row else missing,
                        validated_value=validated_row[field] if field in validated_row else missing,
                        policy_value=applied_item[field] if field in applied_item else missing,
                        validation_diagnostics=validation_diagnostics,
                    )
                    decisions.append(row)

                for field in LINE_REACTION_FIELDS:
                    if field not in raw_line:
                        continue
                    raw_value = raw_line[field]
                    row = decision(
                        chunk_id=chunk_id, source_id=source_id, layer="annotation",
                        field=field, origin="top_level", raw_value=raw_value,
                        expanded_value=expanded_row[field] if field in expanded_row else missing,
                        validated_value=validated_row[field] if field in validated_row else missing,
                        policy_value=(
                            applied_item.get("_reactions", missing)
                            if field == "reactions" else missing
                        ),
                        validation_diagnostics=validation_diagnostics,
                    )
                    decisions.append(row)

                for field in DIRECTION_FIELDS:
                    if field in raw_line:
                        raw_value, origin = raw_line[field], "top_level"
                        director_summary["raw_top_level"] += 1
                    elif field in nested_d:
                        raw_value, origin = nested_d[field], "nested_d"
                        director_summary["raw_nested_d"] += 1
                    elif field in nested_direction:
                        raw_value, origin = nested_direction[field], "nested_direction"
                    else:
                        continue
                    expanded_direction = expanded_row.get("direction") or {}
                    validated_intent = validated_row.get("direction_intent") or {}
                    policy_intent = applied_item.get("_director_intent") or {}
                    policy_direction = applied_item.get("_director") or {}
                    expanded_value = expanded_direction[field] if field in expanded_direction else missing
                    validated_value = validated_intent[field] if field in validated_intent else missing
                    policy_value = (
                        policy_direction.get(field)
                        if field in policy_intent and field in policy_direction
                        else missing
                    )
                    row = decision(
                        chunk_id=chunk_id, source_id=source_id, layer="direction",
                        field=field, origin=origin, raw_value=raw_value,
                        expanded_value=expanded_value, validated_value=validated_value,
                        policy_value=policy_value,
                        validation_diagnostics=validation_diagnostics,
                    )
                    if expanded_value is not missing:
                        director_summary["expanded"] += 1
                    if validated_value is not missing:
                        director_summary["direction_intent"] += 1
                    if row["final_aap_trace"]:
                        director_summary["compiled_to_aap"] += 1
                    decisions.append(row)

            expanded_beats = [row for row in expanded_response.get("beats") or [] if isinstance(row, Mapping)]
            validated_beats = [row for row in validated_response.get("beats") or [] if isinstance(row, Mapping)]
            for beat_index, raw_beat in enumerate(raw_response.get("beats") or []):
                if not isinstance(raw_beat, Mapping):
                    continue
                anchor = raw_beat.get("anchor_id")
                source_id = str(anchor or "")
                if isinstance(anchor, int) and not isinstance(anchor, bool) and 1 <= anchor <= len(target_ids):
                    source_id = target_ids[anchor - 1]
                expanded_beat = expanded_beats[beat_index] if beat_index < len(expanded_beats) else {}
                validated_beat = validated_beats[beat_index] if beat_index < len(validated_beats) else {}
                beat_id = str(validated_beat.get("beat_id") or "")
                policy_beat = beat_by_id.get(beat_id) or {}
                for field, raw_value in raw_beat.items():
                    if field in {"anchor_id", "beat_id"}:
                        continue
                    row = decision(
                        chunk_id=chunk_id, source_id=source_id, layer="beat",
                        field=str(field), origin="beat", raw_value=raw_value,
                        expanded_value=expanded_beat[field] if field in expanded_beat else missing,
                        validated_value=validated_beat[field] if field in validated_beat else missing,
                        policy_value=policy_beat[field] if field in policy_beat else missing,
                        beat_id=beat_id,
                        validation_diagnostics=validation_diagnostics,
                    )
                    decisions.append(row)

            raw_state = raw_response.get("state_delta") or {}
            expanded_state = expanded_response.get("state_delta") or {}
            validated_state = validated_response.get("state_delta") or {}
            final_state = chunk.get("state_delta") or {}
            for field, raw_value in raw_state.items():
                row = decision(
                    chunk_id=chunk_id, source_id="", layer="state_delta",
                    field=str(field), origin="state_delta", raw_value=raw_value,
                    expanded_value=expanded_state[field] if field in expanded_state else missing,
                    validated_value=validated_state[field] if field in validated_state else missing,
                    policy_value=final_state[field] if field in final_state else missing,
                )
                decisions.append(row)

            def memory_event_key(event):
                return (
                    str(event.get("kind") or ""),
                    tuple(sorted(str(value) for value in event.get("source_ids") or [])),
                )

            raw_events = [row for row in raw_response.get("memory_events") or [] if isinstance(row, Mapping)]
            expanded_events = [row for row in expanded_response.get("memory_events") or [] if isinstance(row, Mapping)]
            validated_events = [row for row in validated_response.get("memory_events") or [] if isinstance(row, Mapping)]
            final_events = [row for row in chunk.get("memory_events") or [] if isinstance(row, Mapping)]
            final_events_by_key = {
                memory_event_key(event): event for event in final_events
            }
            for event_index, raw_event in enumerate(raw_events):
                expanded_event = expanded_events[event_index] if event_index < len(expanded_events) else {}
                validated_event = validated_events[event_index] if event_index < len(validated_events) else {}
                final_event = final_events_by_key.get(memory_event_key(validated_event), {})
                source_ids = validated_event.get("source_ids") or expanded_event.get("source_ids") or []
                source_id = str(source_ids[0]) if source_ids else ""
                for field, raw_value in raw_event.items():
                    row = decision(
                        chunk_id=chunk_id, source_id=source_id, layer="memory_event",
                        field=str(field), origin="memory_event", raw_value=raw_value,
                        expanded_value=expanded_event[field] if field in expanded_event else missing,
                        validated_value=validated_event[field] if field in validated_event else missing,
                        policy_value=final_event[field] if field in final_event else missing,
                    )
                    decisions.append(row)

            chunk_attempts.append({
                key: copy.deepcopy(attempt.get(key))
                for key in (
                    "phase", "request_index", "outcome", "error_code", "error_detail",
                    # Keep deterministic hard-protocol repairs visible in the
                    # final model audit.  A cleared field must be distinguishable
                    # from a model omission or a later policy drop.
                    "protocol_repairs",
                )
                if attempt.get(key) not in (None, "")
            } | {
                "target_ids": target_ids,
                "ai_raw_json": copy.deepcopy(dict(raw_response)),
                "compact_expanded": copy.deepcopy(dict(expanded_response)),
                "validated": copy.deepcopy(dict(validated_response)),
                "decisions": decisions,
            })

        # An accepted G2 repair is a later model decision, not a backend
        # policy stage.  When it explicitly rewrites or clears a field, the
        # earlier execution choice remains useful provenance but is no longer
        # authoritative for the final AAP.  Counting both accepted attempts
        # made an intentional repair clear look like a silent policy loss.
        latest_accepted_decision = {}
        for attempt_index, attempt in enumerate(chunk_attempts):
            if attempt.get("outcome") != "accepted":
                continue
            for decision_index, row in enumerate(attempt.get("decisions") or ()):
                key = (
                    str(row.get("layer") or ""),
                    str(row.get("source_id") or ""),
                    str(row.get("beat_id") or ""),
                    str(row.get("field") or ""),
                )
                latest_accepted_decision[key] = (attempt_index, decision_index)

        for attempt_index, attempt in enumerate(chunk_attempts):
            accepted = attempt.get("outcome") == "accepted"
            for decision_index, row in enumerate(attempt.get("decisions") or ()):
                key = (
                    str(row.get("layer") or ""),
                    str(row.get("source_id") or ""),
                    str(row.get("beat_id") or ""),
                    str(row.get("field") or ""),
                )
                latest = latest_accepted_decision.get(key)
                if accepted and latest != (attempt_index, decision_index):
                    next_attempt = chunk_attempts[latest[0]]
                    row["superseded_status"] = str(row.get("status") or "")
                    row["status"] = "superseded_by_accepted_repair"
                    row.pop("loss_stage", None)
                    row["discard_reason"] = "superseded_by_later_accepted_attempt"
                    row["superseded_by"] = {
                        key: copy.deepcopy(next_attempt.get(key))
                        for key in ("phase", "request_index")
                        if next_attempt.get(key) not in (None, "")
                    }
                    summary["superseded_decisions"] += 1
                    continue
                record_summary(row, authoritative=accepted)

        sources = list(dict.fromkeys(
            default_target_ids + [
                str(beat.get("anchor_id") or "")
                for beat in (chunk.get("beats_by_id") or {}).values()
                if isinstance(beat, Mapping)
            ]
        ))
        chunk_policy_beats = {
            beat_id: copy.deepcopy(beat_by_id[beat_id])
            for beat_id in chunk.get("beats_by_id") or {}
            if beat_id in beat_by_id
        }
        audit_chunks.append({
            "chunk_id": str(chunk_id),
            "scene_id": str(chunk.get("scene_id") or ""),
            "attempts": chunk_attempts,
            "validated_rows": copy.deepcopy(dict(final_rows)),
            "validated_beats": copy.deepcopy(dict(chunk.get("beats_by_id") or {})),
            "policy_rows": {
                source_id: copy.deepcopy(item_by_source.get(source_id) or {})
                for source_id in default_target_ids
            },
            "policy_beats": chunk_policy_beats,
            "render_trace": {
                source_id: trace_by_source.get(source_id, []) for source_id in sources if source_id
            },
            "diagnostics": {
                source_id: diagnostic_by_source.get(source_id, []) for source_id in sources
                if diagnostic_by_source.get(source_id)
            },
        })
    return {"schema_version": 2, "summary": summary, "chunks": audit_chunks}


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
    item = {
        "kind": "line", "raw": "", "who": beat["who"], "text": "",
        "face": beat.get("face", ""), "emo": beat.get("emo", ""),
        "act": beat.get("act", ""), "fx": beat.get("fx", ""),
        "se": beat.get("se", ""), "bg": beat.get("bg", ""),
        "place": beat.get("place", ""), "trans": beat.get("trans", ""),
        "bgfx": beat.get("bgfx", ""),
        "shake": beat.get("shake", False), "wait_ms": beat.get("wait_ms", 0),
        "_beat_reveal": list(beat.get("reveal") or []),
        "_beat_conceal": list(beat.get("conceal") or []),
        "_beat_enter": list(beat.get("enter") or []),
        "_beat_exit": list(beat.get("exit") or []),
        "_beat_reactions": list(beat.get("reactions") or []),
        "_annotation_beat": True,
        "_anchor_id": str(beat.get("anchor_id") or ""),
        "_beat_id": str(beat.get("beat_id") or ""),
        "_scene_id": str(beat.get("_scene_id") or ""),
        "_chunk_id": str(beat.get("_chunk_id") or ""),
        "_plan_event_ids": list(beat.get("_plan_event_ids") or []),
    }
    direction = {}
    intent = {}
    for field in ("visible_characters", "positions", "shot_transition", "shot_operation"):
        if field in beat:
            direction[field] = beat[field]
            intent[field] = beat[field]
    if direction:
        direction.setdefault("continuity", {})
        item["_director"] = direction
        item["_director_intent"] = intent
    return item


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


def _speaker_activation_context(*, text="", emo="", act=""):
    compact_text = re.sub(r"\s+", "", str(text or ""))
    celebration = (
        compact_text.startswith(("太好了！", "太好了!"))
        and any(token in compact_text for token in ("继续", "成功", "通过", "完成", "没问题"))
    )
    eager = (
        str(emo or "") in {"闪亮", "叽喳", "音符"}
        or str(act or "") == "hophop"
        or any(token in compact_text for token in (
            "也可以帮忙", "一起检查", "一起确认", "我也来", "交给爱丽丝", "太好了",
        ))
    )
    formal = any(token in compact_text for token in (
        "报告：", "报告:", "记录要员", "检查结果", "没有发现异常", "确认完毕",
    ))
    return eager, formal, celebration


def _speaker_activation_face(records, current, *, text="", emo="", act=""):
    eager, formal, celebration = _speaker_activation_context(
        text=text, emo=emo, act=act
    )
    candidates = []
    for face in records or ():
        face_id = str(face.get("id") or "")
        semantic = " ".join(str(value or "") for value in (
            face.get("semantic_cn"), face.get("cn"), face.get("label"),
            face.get("primary_emotion"), face.get("usage_hint_cn"),
            face.get("emotion_family"),
            " ".join(str(value) for value in face.get("beat_fit") or ()),
            " ".join(str(value) for value in face.get("search_terms_cn") or ()),
        )).casefold()
        expression_class = str(face.get("expression_class") or "base").lower()
        if (
            not face_id
            or expression_class == "special"
            or (expression_class == "peak" and not celebration)
        ):
            continue
        response = any(word in semantic for word in ("回应", "应答", "接话", "开口", "dialogue"))
        joy = any(word in semantic for word in (
            "欣喜", "开朗", "开心", "高兴", "喜悦", "积极", "期待", "joy",
        ))
        neutral = any(word in semantic for word in (
            "平静", "认真", "冷静", "中性", "说明", "汇报", "neutral", "exposition",
        ))
        exposition = any(word in semantic for word in (
            "陈述", "客观信息", "说明", "汇报", "exposition",
        ))
        listening = any(word in semantic for word in (
            "倾听", "等待回应", "好奇", "listening", "question",
        ))
        avoid = str(face.get("avoid_when_cn") or "").casefold()
        avoids_formal = formal and any(word in avoid for word in (
            "正式报告", "汇报", "客观陈述", "值勤",
        ))
        avoids_ordinary = any(word in avoid for word in (
            "普通对话", "日常对话", "鲜活反应",
        ))
        shy = any(word in semantic for word in (
            "腼腆", "害羞", "难为情", "embarrassment",
        ))
        score = 0
        if formal:
            score += 8 if neutral else 0
            score += 6 if exposition else 0
            score -= 5 if listening else 0
            score -= 4 if joy else 0
        elif eager:
            score += 8 if joy else 0
            score -= 4 if neutral else 0
            score -= 6 if shy else 0
            score += 2 if expression_class == "accent" else 0
            score += 6 if celebration and "celebration" in semantic else 0
            score += 3 if celebration and expression_class == "peak" else 0
        else:
            score += 5 if response else 0
            score += 1 if neutral else 0
        if face_id != str(current or ""):
            score += 1
        if avoids_formal:
            score -= 20
        elif avoids_ordinary and not (celebration or expression_class == "peak"):
            score -= 10
        if not (formal or eager or response):
            continue
        candidates.append((-score, face_id))
    if not candidates:
        return ""
    face_id = min(candidates)[1]
    return "" if face_id == str(current or "") else face_id


def apply_speaker_turn_face_activation(items, cast, constraints, proposals=None):
    """Give a returning speaker one verified response face when AI left it blank."""
    proposal_sink = proposals if proposals is not None else []
    last_faces = {}
    previous_speaker = None
    changes = 0
    records_by_id = constraints.get("face_records_by_id") or {}
    for item in items:
        if item.get("kind") != "line":
            raw = str(item.get("raw") or "").strip()
            if raw == "---" or raw.startswith(("@bg ", "@place ")):
                previous_speaker = None
                last_faces.clear()
            continue
        who = str(item.get("who") or "")
        character = cast.get(who) or {}
        existing = str(item.get("face") or "")
        eager, formal, _celebration = _speaker_activation_context(
            text=item.get("text", ""), emo=item.get("emo", ""), act=item.get("act", "")
        )
        if existing:
            last_faces[who] = existing
        if (
            (not existing and who != previous_speaker) or eager or formal
        ) and (
            character.get("portrait")
            and not character.get("narrator")
        ):
            face_id = _speaker_activation_face(
                records_by_id.get(str(character.get("id") or ""), []),
                last_faces.get(who),
                text=item.get("text", ""),
                emo=item.get("emo", ""),
                act=item.get("act", ""),
            )
            if face_id:
                item["face"] = face_id
                item.setdefault("_direction_origins", {})["face"] = "deterministic"
                last_faces[who] = face_id
                changes += 1
                proposal_sink.append(build_proposal(
                    card_id=item.get("card_id") or str(uuid.uuid4()),
                    p_type="applied_pending",
                    origin="deterministic_supplement",
                    rule="speaker_turn_face_activation",
                    field_name="face",
                    before=existing or None,
                    after=face_id,
                ))
        previous_speaker = who
    return changes


def apply_annotation_response_row(
    item, row, cast, constraints, proposals, dropped, diagnostics=None,
):
    """Apply one validated model row through the existing resource guards."""
    diagnostic_sink = diagnostics if diagnostics is not None else []
    character = cast[item["who"]]
    portrait = character.get("portrait") and not character.get("narrator")
    item["_speaker_has_portrait"] = bool(portrait)
    effective_row, clean, rejected, rejected_details = project_effective_annotation_row(
        row, item, character, constraints,
    )
    if "reactions" in row:
        item["_reactions"] = copy.deepcopy(list(effective_row.get("reactions") or ()))
    if "direction" in row:
        cast_names = list(cast)
        displayable_names = {
            name for name, candidate in cast.items()
            if candidate.get("portrait") and not candidate.get("narrator")
        }
        item["_displayable_names"] = tuple(sorted(displayable_names))
        director, director_diagnostics = normalize_director(
            effective_row.get("direction"),
            cast_names=cast_names,
            displayable_names=displayable_names,
        )
        item["_director"] = director
        if isinstance(effective_row.get("direction_intent"), Mapping):
            item["_director_intent"] = dict(effective_row["direction_intent"])
        source_id = str(item.get("annotation_id") or "")
        diagnostic_sink.extend({**entry, "source_id": source_id} for entry in director_diagnostics)
    card_id = item.get("card_id") or str(uuid.uuid4())
    before_values = {
        field_name: item.get(field_name)
        for field_name in clean
    }
    applied_clean = apply_model_directions(item, clean)
    for field_name, field_value in applied_clean.items():
        proposals.append(build_proposal(
            card_id=card_id, p_type="applied_pending", origin="model",
            rule="llm_annotation", field_name=field_name,
            before=before_values.get(field_name), after=field_value,
        ))
    for rejected_item in rejected_details:
        proposals.append(build_proposal(
            card_id=card_id, p_type="suggested_fix", origin="model",
            rule="llm_rejected_annotation", field_name=rejected_item["field"],
            before=None, after=rejected_item["value"],
        ))
        diagnostic_sink.append({
            "code": rejected_item.get("code") or (
                "director_unverified_face"
                if rejected_item["field"] == "face"
                else "director_resource_downgraded"
            ),
            "level": "high",
            "resolution": "ai_repair",
            "needs_review": True,
            "source_id": str(item.get("annotation_id") or ""),
            "field": rejected_item["field"],
            "message": rejected_item["reason"],
            **{
                key: rejected_item[key]
                for key in (
                    "character", "character_id", "outfit_key",
                    "spine_signature", "face_id", "evidence_level",
                )
                if key in rejected_item
            },
        })
    dropped.extend(rejected)
    authored_fields = set(item.get("_explicit_direction_fields") or ())
    if row.get("place") and "place" not in authored_fields:
        item["place"] = str(row["place"])[:40]
    if row.get("shake") and "shake" not in authored_fields:
        item["shake"] = True
    if row.get("reveal") and "reveal" not in authored_fields:
        item["reveal"] = str(row["reveal"])
    if row.get("bgfx") and "bgfx" not in authored_fields:
        _value, error = tables.resolve_bgeffect(row["bgfx"])
        if error is None:
            item["bgfx"] = row["bgfx"]
        else:
            dropped.append(error or f"未知背景效果 {row['bgfx']}")
    if row.get("trans") and "trans" not in authored_fields:
        value, error = tables.resolve_transition(row["trans"])
        if value:
            item["trans"] = row["trans"]
        else:
            dropped.append(error or f"未知过渡 {row['trans']}")
    if (
        portrait and "move" not in authored_fields
        and isinstance(row.get("move"), int) and 1 <= row["move"] <= 5
    ):
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
        elif rule == "continuity_density":
            for drop in it.get("_direction_drops", []):
                proposals.append(build_proposal(
                    card_id=card_id,
                    p_type="applied_pending",
                    origin="deterministic_postprocessor",
                    rule=str(drop.get("reason") or rule),
                    field_name=str(drop.get("field") or ""),
                    before=drop.get("value"),
                    after=None,
                ))
    return proposals


def apply_direction_supplements(items, cast, *, rule_allowlist=None):
    """Run optional deterministic direction without blocking draft generation."""
    try:
        if rule_allowlist is None:
            return supplement_directions(items, cast), []
        return supplement_directions(
            items, cast, rule_allowlist=rule_allowlist
        ), []
    except Exception as exc:
        return [], [{
            "code": "direction_supplement_failed",
            "level": "warning",
            "message": f"自动演出补全已跳过：{exc}",
        }]


def build_camera_merge_guard(index, cast):
    """Bind camera continuity decisions to the same portrait geometry as AA."""
    profiles_by_id = portrait_layout.profiles_for_cast(
        index,
        cast,
        catalog_fallback=not isinstance(index.get("portrait_layout_catalog"), dict),
    )
    display_profiles = {
        name: profiles_by_id.get(str(character.get("id") or ""), {})
        for name, character in cast.items()
        if isinstance(character, Mapping)
    }
    portrait_names = {
        name for name, character in cast.items()
        if isinstance(character, Mapping)
        and character.get("portrait")
        and not character.get("narrator")
    }
    stage = Stage(profiles=display_profiles, semantic_layout=True)

    def allowed(names):
        unique = tuple(dict.fromkeys(str(name) for name in names if str(name)))
        return (
            2 <= len(unique) <= 3
            and set(unique) <= portrait_names
            and stage.can_fit_composition(unique)
        )

    return allowed


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
    story_type = normalize_story_type(options.get("story_type"))
    layout_mode = normalize_layout_mode(options.get("layout_mode"))
    include_official_face_context = bool(
        options.get("include_official_face_context", False)
    )
    source_text = Path(script_path).read_text(encoding="utf-8")
    raw_usage_chain = options.get("usage_chain")
    usage_chain = raw_usage_chain if isinstance(raw_usage_chain, list) else []
    usage_chain_context = ""
    if usage_chain:
        usage_chain_context = (
            "已确认的场景演出规划（优先遵守其中已确认的背景和音效，不要重新换成其他素材；"
            "BGM 仅作上下文，本阶段不写入）：\n"
            + json.dumps(usage_chain, ensure_ascii=False, separators=(",", ":"))
        )

    cfg, cast, _ = load_cast(cast_path)
    idx = json.load(open(index_path, encoding="utf-8"))
    # The web entry keeps the authoritative labelled DB in user state while
    # each project gets a separate JSON resource index.  Do not infer the DB
    # from the index directory: that used to silently leave a run with only
    # legacy face labels (or create an empty sibling DB).  ``database_paths``
    # is an explicit, read-only overlay list so a future 0.95 setup can add a
    # second labelled source without merging or mutating either database.
    configured_databases = options.get("database_paths")
    if isinstance(configured_databases, (str, os.PathLike)):
        configured_databases = [configured_databases]
    if not isinstance(configured_databases, (list, tuple)):
        configured_databases = []
    if options.get("database_path"):
        configured_databases.insert(0, options["database_path"])
    if not configured_databases:
        configured_databases = [Path(index_path).with_name("aa_assets.db")]
    seen_databases = set()
    for database_path in configured_databases:
        database_path = Path(database_path).expanduser()
        try:
            canonical_database = str(database_path.resolve())
        except OSError:
            canonical_database = str(database_path)
        if canonical_database.casefold() in seen_databases or not database_path.is_file():
            continue
        seen_databases.add(canonical_database.casefold())
        con = assetdb.connect_readonly(database_path)
        try:
            idx = merge_face_capabilities(idx, con)
            # Background/scene labels are an equally important part of the
            # semantic catalogue.  Overlay them in the same explicit,
            # read-only order as face capabilities so a second labelled DB
            # can enrich generation without replacing the first source.
            idx = merge_scene_capabilities(idx, con)
        finally:
            con.close()
    llmcfg = (
        json.load(open(llm_path, encoding="utf-8"))
        if os.path.isfile(llm_path) else {}
    )
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
    # Keep prompt resource order deterministic across checkpoint replays.  A
    # set-based tie leaves equal-frequency cast members in hash order, which
    # changes the request fingerprint without changing the actual inputs.
    used_names = list(dict.fromkeys(items[i]["who"] for i in todo))
    frequency = {
        who: sum(1 for i in todo if items[i]["who"] == who)
        for who in used_names
    }
    for w in sorted(used_names, key=lambda who: (-frequency[who], who)):
        key = cast[w].get("id") or "旁白"
        if key in seen_id:
            continue
        seen_id.add(key)
        used.append(w)
    constraints = annotation_constraints(idx, cast, usage_chain=usage_chain)
    agent_enabled = (
        bool(options.get("agent_enabled", llmcfg.get("agent_enabled", False)))
        or layout_mode == "pure_ai"
    ) and not range_str
    scene_event_planning = bool(options.get("scene_event_planning", False)) and agent_enabled
    scene_asset_context = " ".join(
        str(character.get(field) or "").strip()
        for who in used
        for character in [cast.get(who) or {}]
        for field in ("club", "school", "academy", "affiliation", "organization")
        if str(character.get(field) or "").strip()
    )
    prompt_idx = PROMPT.select_prompt_assets(
        idx, source_text, usage_chain, context_text=scene_asset_context,
    )
    for background in constraints.get("confirmed_bg") or set():
        prompt_idx["bg"].setdefault(background, idx.get("bg", {}).get(background, 0))
    static = build_static(
        prompt_idx, cast, used, story_type=story_type, layout_mode=layout_mode,
        official_db_path=(database_path if include_official_face_context else None),
        dynamic_face_shortlists=agent_enabled,
        planned_execution=scene_event_planning,
    )

    print(f"剧本      {script_path}")
    print(f"待标注    {len(todo)} 行台词（全文 {len(dialog)} 行）")
    print(f"出场      {'、'.join(used)}")
    print(
        f"资源候选  背景 {len(prompt_idx.get('bg') or {})}/"
        f"{len(generator_background_keys(idx))}  音效 "
        f"{len(prompt_idx.get('sounds') or [])}/{len(idx.get('sounds') or [])}"
    )
    print(f"资源表    约 {len(static)//3:,} tokens（会被缓存）")

    if dry_run:
        print("\n" + "=" * 60)
        print(static[:3000])
        print("…（截断）")
        return {
            "text": "", "proposals": [], "diagnostics": [], "out": out_path,
            "story_type": story_type,
        }

    prov = provider_instance or make_provider(llm_path, provider_name)
    print(f"模型      {prov.name} / {prov.model}\n")

    n = llmcfg.get("chunk_lines", 40)
    ctx = llmcfg.get("context_lines", 10)
    dropped, applied = [], 0
    diagnostics = []
    proposals = []
    agent_meta = {}
    agent_result = {}
    annotation_beats = []
    if agent_enabled:
        script_text = source_text
        # PAST/TARGET/FUTURE already supply the relevant source window. Keep
        # full-source duplication as an explicit opt-in instead of the default.
        source_context_strategy = str(
            getattr(prov, "cfg", {}).get("source_context_strategy") or "window"
        )
        if scene_event_planning and source_context_strategy in {"preserve", "window"}:
            source_context_strategy = "planned_window"
        agent_static = build_annotation_static_system(
            static,
            script_text,
            source_context_strategy=source_context_strategy,
        )
        model_config = {
            "provider": getattr(prov, "name", provider_name or llmcfg.get("provider") or ""),
            "model": getattr(prov, "model", ""),
            "runtime_fingerprint_sha256": str(
                options.get("runtime_fingerprint_sha256") or ""
            ),
            "max_tokens": int(getattr(prov, "cfg", {}).get("max_tokens", 16000)),
            "annotation_max_tokens": int(getattr(prov, "cfg", {}).get("annotation_max_tokens") or getattr(prov, "cfg", {}).get("max_tokens", 16000)),
            "reasoning_mode": str(getattr(prov, "cfg", {}).get("reasoning_mode") or "balanced"),
            "reasoning_wire_protocol": str(getattr(prov, "cfg", {}).get("reasoning_wire_protocol") or ""),
            "context_window_tokens": int(getattr(prov, "cfg", {}).get("context_window_tokens") or 0) or None,
            "compact_annotation": bool(getattr(prov, "supports_compact_annotation", False)),
            "source_context_strategy": source_context_strategy,
        }
        fingerprint = build_run_fingerprint(
            script_text, cast, idx,
            hashlib.sha256(static.encode("utf-8")).hexdigest()[:16], 3, "scene-v3",
            model_config,
            story_type=story_type,
            run_mode=str(options.get("run_mode") or "balanced"),
            source_id=str(options.get("source_id") or Path(script_path).resolve()),
            director_version=(
                "stateful-v3-scene-plan"
                if scene_event_planning
                else ("stateful-v2-pure-ai" if layout_mode == "pure_ai" else "stateful-v1")
            ),
        )
        checkpoint_dir = options.get("checkpoint_dir") or os.path.join(HERE, "out", "annotation-checkpoints")
        agent_error = None
        try:
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
                story_type=story_type,
                scene_event_planning=scene_event_planning,
            )
        except AnnotationAgentError as exc:
            # Keep only accepted chunks.  The caller decides whether to turn
            # this provisional render into a review draft.
            agent_error = exc
            agent_result = copy.deepcopy(exc.partial_result or {})
            if not agent_result.get("rows_by_id") and not agent_result.get("beats"):
                raise
        diagnostics.extend(agent_result.get("diagnostics") or [])
        agent_meta = {
            "enabled": True,
            "completed_chunks": agent_result.get("completed_chunks", 0),
            "resumed_chunks": agent_result.get("resumed_chunks", 0),
            "cancelled": bool(agent_result.get("cancelled")),
            "timed_out": bool(agent_result.get("timed_out")),
            "total_targets": int(agent_result.get("total_targets") or 0),
            "completed_targets": int(agent_result.get("completed_targets") or 0),
            "pending_targets": int(agent_result.get("pending_targets") or 0),
            "pending_start_line": agent_result.get("pending_start_line"),
            "pending_end_line": agent_result.get("pending_end_line"),
            "metrics": agent_result.get("metrics") or {},
        }
        if agent_error is not None:
            agent_meta.update({
                "failed": True,
                "failure_stage": agent_error.stage,
                "failure_scene_id": agent_error.scene_id,
                "failure_chunk_id": agent_error.chunk_id,
                "failure_detail": agent_error.detail,
            })
            diagnostics.append({
                "code": "annotation_generation_failed", "level": "error",
                "stage": agent_error.stage, "scene_id": agent_error.scene_id,
                "chunk_id": agent_error.chunk_id, "detail": agent_error.detail,
                "needs_review": True,
            })
        if agent_meta["cancelled"]:
            return {"text": "", "proposals": [], "diagnostics": diagnostics,
                    "out": out_path, "agent": agent_meta, "cancelled": True,
                    "story_type": story_type}
        rows_by_id = agent_result["rows_by_id"]
        annotation_beats = agent_result.get("beats") or []
        for item_index in todo:
            item = items[item_index]
            row = rows_by_id.get(item.get("annotation_id"))
            if row and apply_annotation_response_row(
                item, row, cast, constraints, proposals, dropped, diagnostics,
            ):
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
                if apply_annotation_response_row(
                    items[batch[row_index]], row, cast, constraints,
                    proposals, dropped, diagnostics,
                ):
                    applied += 1
            done = min(start + n, len(todo))
            print(f"  已标注 {done}/{len(todo)} 行")

    if not agent_enabled:
        normalize_contextual_sounds(items, idx)
    # Stateful runs only receive the small set of high-confidence corrections;
    # the broader fallback remains exclusive to the legacy stateless path.
    supplements, supplement_diagnostics = (
        ([], [])
        if layout_mode == "pure_ai"
        else apply_direction_supplements(
            items,
            cast,
            rule_allowlist={
                "eager_positive_participation",
                "formal_result_report_response",
            } if agent_enabled else None,
        )
    )
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
    if agent_enabled:
        if layout_mode == "pure_ai":
            annotation_beats, policy_diagnostics = dedupe_exact_beats(
                items, annotation_beats
            )
        else:
            annotation_beats, policy_diagnostics = normalize_direction_plan(
                items,
                annotation_beats,
                camera_merge_allowed=build_camera_merge_guard(idx, cast),
            )
        diagnostics.extend(policy_diagnostics)
    else:
        normalize_direction_density(items)
    if layout_mode != "pure_ai" and not agent_enabled:
        # This legacy helper uses deliberately narrow phrase heuristics.
        # Stateful runs use plan-aware shortlists plus G2 repair so the backend
        # does not silently overwrite a model decision with a guessed face.
        apply_speaker_turn_face_activation(items, cast, constraints, proposals)
    if layout_mode != "pure_ai":
        proposals.extend(build_postprocessor_proposals(items, rule="continuity_density"))
    normalize_bgfx_lifetime(items)

    final_text, trace_payload = render_annotated_items_with_trace(
        insert_annotation_beats(items, annotation_beats)
    )
    diagnostics = reconcile_quality_diagnostics_with_rendered_trace(
        reclassify_quality_diagnostics(diagnostics),
        trace_payload.get("lines") or [],
    )
    unresolved_quality = [
        dict(item) for item in diagnostics
        if item.get("needs_review")
        and str(item.get("level") or item.get("severity") or "") in {"high", "critical"}
    ]
    trace_payload["director_plan"] = copy.deepcopy(
        agent_result.get("director_plan") or {}
    ) if agent_enabled else {}
    trace_payload["pipeline"] = {
        "version": PIPELINE_VERSION,
        "prompt_revision": getattr(PROMPT, "PROMPT_REVISION", ""),
        "database_paths": sorted(seen_databases),
    }
    trace_payload["quality"] = {
        "result": "needs_review" if unresolved_quality else "pass",
        "issues": unresolved_quality,
    }
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(final_text)
    trace_path = str(out_path) + ".trace.json"
    with open(trace_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(trace_payload, fh, ensure_ascii=False, indent=2)
    model_audit_path = None
    if agent_enabled:
        model_audit = build_model_output_audit(
            agent_result.get("chunk_outputs") or {}, items,
            trace_payload.get("lines") or [], diagnostics,
            policy_beats=annotation_beats,
        )
        model_audit_path = str(out_path) + ".model-audit.json"
        with open(model_audit_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(model_audit, fh, ensure_ascii=False, indent=2)
        trace_payload["model_output_audit"] = {
            "path": model_audit_path,
            **copy.deepcopy(model_audit.get("summary") or {}),
        }
        with open(trace_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(trace_payload, fh, ensure_ascii=False, indent=2)
    if agent_meta:
        agent_meta["needs_review"] = bool(unresolved_quality)

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

    result_payload = {
        "text": final_text,
        "proposals": proposals,
        "diagnostics": diagnostics,
        "out": out_path,
        "trace": trace_path,
        "model_audit": model_audit_path,
        "database_paths": sorted(seen_databases),
        "pipeline_version": PIPELINE_VERSION,
        "prompt_revision": getattr(PROMPT, "PROMPT_REVISION", ""),
        "agent": agent_meta,
        "story_type": story_type,
    }
    if agent_meta and agent_meta.get("failed"):
        result_payload["generation_error"] = {
            "stage": agent_meta.get("failure_stage"),
            "scene_id": agent_meta.get("failure_scene_id"),
            "chunk_id": agent_meta.get("failure_chunk_id"),
            "detail": agent_meta.get("failure_detail"),
        }
        result_payload["partial"] = True
    return result_payload


def main(provider_instance=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("-o", "--out")
    ap.add_argument("--cast", default=os.path.join(HERE, "cast.json"))
    ap.add_argument("--index", default=os.path.join(HERE, "aa_resources.json"))
    ap.add_argument("--llm", default=os.path.join(HERE, "llm.json"))
    ap.add_argument(
        "--database", dest="databases", action="append", default=None,
        help="只读素材标注数据库；可重复传入以叠加第二个已确认事实源",
    )
    ap.add_argument("--provider", help="覆盖 llm.json 里的 provider")
    ap.add_argument("--story-type", choices=sorted(_STORY_TYPES), default="auto")
    ap.add_argument("--range", help="只处理这些台词行，如 1-80")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要发送的提示词，不调 API")
    ap.add_argument(
        "--scene-plan", action=argparse.BooleanOptionalAction, default=True,
        help="启用场景事件规划第一阶段（0.95 默认启用；可用 --no-scene-plan 显式关闭）",
    )
    a = ap.parse_args()

    opts = {
        "script": a.script,
        "out": a.out,
        "cast": a.cast,
        "index": a.index,
        "llm": a.llm,
        "provider": a.provider,
        "story_type": a.story_type,
        "scene_event_planning": a.scene_plan,
        "range": a.range,
        "dry_run": a.dry_run,
        "database_paths": a.databases or [],
    }
    try:
        res = annotate_script(opts, provider_instance=provider_instance)
        print(f"改完之后:  python script2aap.py \"{res['out']}\" -o 工程名 --install")
    except Exception as e:
        sys.exit(f"\n标注错误: {e}")


if __name__ == "__main__":
    main()
