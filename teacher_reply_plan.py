"""Frozen source-card association for the single-answer AA export boundary."""

from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

from document import normalize_draft_nodes, parse_document_lossless
from draft_identity import compute_text_fingerprint
from teacher_identity import TeacherIdentityError, teacher_override_from_mapping
from teacher_presentation import effective_teacher_presentation, teacher_reply_ids

SCHEMA_VERSION = "teacher-reply-plan/1.0"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_reply_text(text: Any) -> str:
    if not isinstance(text, str) or not text.strip():
        raise TeacherIdentityError("teacher_reply_empty", "Sel 回答不能为空", status=409)
    if any(ord(c) < 32 or ord(c) == 127 or c in "\u2028\u2029" for c in text) or re.search(
        r"\[s\s*[-+]?\d|(?:^|\\[nr])\s*#|\\[nr]",
        text,
        re.IGNORECASE,
    ):
        raise TeacherIdentityError(
            "teacher_reply_unsafe_text",
            "Sel 回答含不支持的控制文本，请改用槽 0 或修改该台词",
            status=409,
        )
    return text


def _cast(cast_data):
    result = dict(cast_data.get("cast") or {})
    for alias, target in (cast_data.get("alias") or {}).items():
        if target in result:
            result[alias] = result[target]
    return result


def make_reply_plan(text: str, identities: list[dict], cast_data: dict) -> dict | None:
    presentation = effective_teacher_presentation(cast_data)
    if presentation["mode"] != "sel_single":
        return None
    nodes = normalize_draft_nodes(parse_document_lossless(text))
    if not isinstance(identities, list) or len(nodes) != len(identities):
        raise TeacherIdentityError(
            "teacher_reply_source_mismatch", "回答与草稿卡片无法对应", status=409
        )
    cast = _cast(cast_data)
    lines = []
    seen = set()
    for node, identity in zip(nodes, identities):
        card_id = identity.get("card_id") if isinstance(identity, dict) else None
        ids = teacher_reply_ids(card_id)
        if card_id in seen or identity.get("text_fingerprint") != compute_text_fingerprint(
            node.raw
        ):
            raise TeacherIdentityError(
                "teacher_reply_source_mismatch", "回答卡片身份校验失败", status=409
            )
        seen.add(card_id)
        if node.kind != "line":
            continue
        mapping = cast.get(node.fields.get("who"))
        if not isinstance(mapping, dict):
            raise TeacherIdentityError(
                "teacher_reply_source_mismatch", "回答来源缺少演员绑定", status=409
            )
        teacher = teacher_override_from_mapping(mapping) is not None
        dialogue = str(node.fields.get("text") or "")
        if teacher:
            validate_reply_text(dialogue)
        lines.append(
            {
                "card_id": card_id,
                "source_id": identity.get("source_id"),
                "teacher": teacher,
                "character_id": str(mapping.get("id") or ""),
                "source_character_id": str(mapping.get("id") or ""),
                "source_speaker": node.fields.get("who"),
                "compiled_speaker": node.fields.get("who"),
                "text_sha256": text_hash(dialogue),
                **ids,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "presentation": presentation,
        "source_sha256": text_hash(text),
        "compiled_text_sha256": text_hash(text),
        "lines": lines,
    }


def retarget_reply_plan(plan: dict, compiled_text: str, cast_data: dict) -> dict:
    """CG may change speaker spelling/directions, never dialogue order or identity."""
    updated = copy.deepcopy(plan)
    nodes = [node for node in parse_document_lossless(compiled_text) if node.kind == "line"]
    if len(nodes) != len(plan.get("lines", [])):
        raise TeacherIdentityError(
            "teacher_reply_source_mismatch", "CG 回答数量与来源不一致", status=409
        )
    cast = _cast(cast_data)
    for node, row in zip(nodes, updated["lines"]):
        original = row["source_speaker"]
        compiled = node.fields.get("who")
        if compiled != original:
            alias = "__halocue_cg_" + hashlib.sha1(original.encode("utf-8")).hexdigest()[:12]
            mapping = cast.get(compiled, {})
            expected_id = row["source_character_id"] if row["teacher"] else original
            if (
                compiled != alias
                or mapping.get("id") != expected_id
                or mapping.get("portrait") is not False
                or mapping.get("narrator") is not False
            ):
                raise TeacherIdentityError(
                    "teacher_reply_source_mismatch", "CG 回答绑定与来源不一致", status=409
                )
            row["character_id"] = expected_id
        row["compiled_speaker"] = compiled
    updated["compiled_text_sha256"] = text_hash(compiled_text)
    validate_reply_plan(updated, compiled_text, cast_data)
    return updated


def validate_reply_plan(plan: Any, compiled_text: str, cast_data: dict) -> dict:
    if not isinstance(plan, dict) or plan.get("schema_version") != SCHEMA_VERSION:
        raise TeacherIdentityError(
            "teacher_reply_plan_invalid", "Sel 回答缺少有效的冻结来源计划", status=409
        )
    if plan.get("presentation") != effective_teacher_presentation(cast_data) or plan.get(
        "compiled_text_sha256"
    ) != text_hash(compiled_text):
        raise TeacherIdentityError(
            "teacher_reply_source_mismatch", "Sel 回答计划与编译输入不一致", status=409
        )
    nodes = [node for node in parse_document_lossless(compiled_text) if node.kind == "line"]
    lines = plan.get("lines")
    if not isinstance(lines, list) or len(lines) != len(nodes):
        raise TeacherIdentityError(
            "teacher_reply_source_mismatch", "Sel 回答数量与来源不一致", status=409
        )
    cast = _cast(cast_data)
    seen = set()
    for node, row in zip(nodes, lines):
        if not isinstance(row, dict):
            raise TeacherIdentityError(
                "teacher_reply_plan_invalid", "Sel 回答计划记录损坏", status=409
            )
        ids = teacher_reply_ids(row.get("card_id"))
        mapping = cast.get(node.fields.get("who")) or {}
        teacher = teacher_override_from_mapping(mapping) is not None
        if (
            row.get("card_id") in seen
            or any(row.get(k) != v for k, v in ids.items())
            or row.get("text_sha256") != text_hash(str(node.fields.get("text") or ""))
            or row.get("character_id") != str(mapping.get("id") or "")
            or row.get("compiled_speaker") != node.fields.get("who")
            or type(row.get("teacher")) is not bool
            or row["teacher"] != teacher
        ):
            raise TeacherIdentityError(
                "teacher_reply_source_mismatch", "Sel 回答内容或身份与冻结来源不一致", status=409
            )
        if teacher:
            validate_reply_text(node.fields.get("text"))
        seen.add(row["card_id"])
    return plan
