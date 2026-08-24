from __future__ import annotations

import base64
import binascii
import copy
import json
import re
from dataclasses import dataclass
from typing import Any

from .errors import DomainError
from .repository import canonical_json, sha256_bytes


MAX_CHARACTER_CARD_BYTES = 5_000_000
PROFILE_FORMAT = "ba-character-card/full/1.0"
EXTRACTOR_VERSION = "halocue-ba-character-import/1.0"

PURE_SOURCE_ID = re.compile(r"^\d+$")
COMBINED_SOURCE_ID = re.compile(r"^(\d+)\s+(.+)$")
CITATION_PATTERNS = (
    re.compile(r":?contentReference\[[^\]]*\]\{[^}]*\}"),
    re.compile(r"\[oaicite:[^\]]+\]"),
    re.compile(r"cite[^]+"),
)
SEMANTIC_RISK_PATTERNS = {
    "absolute_claim": re.compile(r"真正驱动|本质上|总是|永远|必然|无论何时"),
    "mind_reading": re.compile(r"识破所有|读取.*心理|看穿所有|谁在隐瞒|隐藏动机"),
    "frequency_formula": re.compile(r"大量停顿|频繁省略号|每句|句句|固定每"),
}
EVENT_LEXICON_PATTERN = re.compile(r"一般人A|第\d+话|一次性笑点|剧情专用")
REQUIRED_TOP_LEVEL = ("name", "core", "personality", "speech", "emotions", "relations", "ooc")
EXAMPLE_FIELDS = ("line", "source_id", "source_title", "state", "relation", "function")
SEQUENCE_FIELDS = ("source_id", "source_title", "context", "function", "turns")
SAMPLE_FORMS = {"bond_choice", "main_story_choice", "scene_dialogue", "momotalk"}
VERIFIED_EVIDENCE = {"local_exact", "local_variant"}


def _issue(code: str, path: str, message: str, **extra: Any) -> dict:
    result = {"code": code, "path": path, "message": message}
    result.update(extra)
    return result


def _clean_string(value: str) -> str:
    cleaned = value
    for pattern in CITATION_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s*\n\s*", " ", cleaned)
    return cleaned.strip()


def _walk_clean(value: Any, path: str, fixes: list[dict]) -> Any:
    if isinstance(value, str):
        cleaned = _clean_string(value)
        if cleaned != value:
            fixes.append(_issue("clean_whitespace_or_citation", path, "清理引用残留或多余空白。"))
        return cleaned
    if isinstance(value, list):
        return [_walk_clean(item, f"{path}[{index}]", fixes) for index, item in enumerate(value)]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else key
            if key == "source_aliases" and item in (None, [], ""):
                fixes.append(_issue("drop_empty_source_aliases", child_path, "删除空 source_aliases。"))
                continue
            result[key] = _walk_clean(item, child_path, fixes)
        return result
    return copy.deepcopy(value)


def _split_source_ids(value: Any, path: str, fixes: list[dict], errors: list[dict]) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _split_source_ids(item, f"{path}[{index}]", fixes, errors)
        return
    if not isinstance(value, dict):
        return
    source = value.get("source_id")
    if isinstance(source, str) and not PURE_SOURCE_ID.fullmatch(source):
        match = COMBINED_SOURCE_ID.fullmatch(source)
        if match:
            source_id, title = match.groups()
            existing_title = str(value.get("source_title", "")).strip()
            if existing_title and existing_title != title:
                errors.append(_issue(
                    "source_title_conflict",
                    f"{path}.source_id",
                    "组合 source_id 中的标题与 source_title 冲突，不能自动拆分。",
                ))
            else:
                value["source_id"] = source_id
                value["source_title"] = title
                fixes.append(_issue("split_source_id", f"{path}.source_id", "拆分编号与标题。"))
    for key, item in value.items():
        _split_source_ids(item, f"{path}.{key}" if path else key, fixes, errors)


def _semantic_warnings(value: Any, path: str = "") -> list[dict]:
    warnings: list[dict] = []
    if isinstance(value, dict):
        for key, item in value.items():
            warnings.extend(_semantic_warnings(item, f"{path}.{key}" if path else key))
        return warnings
    if isinstance(value, list):
        for index, item in enumerate(value):
            warnings.extend(_semantic_warnings(item, f"{path}[{index}]"))
        return warnings
    if not isinstance(value, str):
        return warnings
    for code, pattern in SEMANTIC_RISK_PATTERNS.items():
        hits = sorted(set(pattern.findall(value)))
        if hits:
            warnings.append(_issue(code, path, "可能把有边界的规律写成绝对规则。", hits=hits))
    if path.endswith("lexical_preferences") and EVENT_LEXICON_PATTERN.search(value):
        warnings.append(_issue("event_specific_lexicon", path, "lexical_preferences 可能包含剧情专用身份或一次性笑点。"))
    return warnings


def _target_names(card: dict) -> set[str]:
    names = {str(card.get("name", "")).strip().casefold()}
    aliases = card.get("aliases", [])
    if isinstance(aliases, list):
        names.update(str(item).strip().casefold() for item in aliases if str(item).strip())
    return names - {""}


def _evidence_status(item: dict) -> str:
    status = str(item.get("evidence_status", "")).strip()
    if status:
        return status
    item["evidence_status"] = "external_unverified"
    return "external_unverified"


def clean_and_validate(card: dict) -> tuple[dict, dict]:
    fixes: list[dict] = []
    split_errors: list[dict] = []
    cleaned = _walk_clean(card, "", fixes)
    _split_source_ids(cleaned, "", fixes, split_errors)

    errors = list(split_errors)
    warnings = _semantic_warnings(cleaned)
    for key in REQUIRED_TOP_LEVEL:
        value = cleaned.get(key)
        valid = bool(str(value).strip()) if isinstance(value, str) else bool(value)
        if not valid:
            errors.append(_issue("required_field", key, f"缺少有效字段 {key}。"))
    for key in ("personality", "emotions", "relations"):
        if not isinstance(cleaned.get(key), dict) or not cleaned.get(key):
            errors.append(_issue("invalid_mapping", key, f"{key} 必须是非空对象。"))

    speech = cleaned.get("speech")
    if not isinstance(speech, dict):
        errors.append(_issue("invalid_mapping", "speech", "speech 必须是对象。"))
        speech = {}
    examples = speech.get("voice_examples", [])
    sequences = speech.get("voice_sequences", [])
    if not isinstance(examples, list):
        errors.append(_issue("invalid_array", "speech.voice_examples", "voice_examples 必须是数组。"))
        examples = []
    if not isinstance(sequences, list):
        errors.append(_issue("invalid_array", "speech.voice_sequences", "voice_sequences 必须是数组。"))
        sequences = []

    example_sources: list[str] = []
    verified_example_sources: list[str] = []
    missing_evidence = 0
    for index, item in enumerate(examples):
        path = f"speech.voice_examples[{index}]"
        if not isinstance(item, dict):
            errors.append(_issue("invalid_example", path, "例句必须是对象。"))
            continue
        missing = [field for field in EXAMPLE_FIELDS if not str(item.get(field, "")).strip()]
        if missing:
            errors.append(_issue("missing_example_fields", path, "例句缺少字段：" + "、".join(missing)))
            continue
        source = str(item["source_id"]).strip()
        if not PURE_SOURCE_ID.fullmatch(source):
            errors.append(_issue("invalid_source_id", f"{path}.source_id", "source_id 必须是纯编号。"))
            continue
        example_sources.append(source)
        had_status = bool(str(item.get("evidence_status", "")).strip())
        status = _evidence_status(item)
        if not had_status:
            missing_evidence += 1
        if status in VERIFIED_EVIDENCE:
            verified_example_sources.append(source)

    target_names = _target_names(cleaned)
    sequence_sources: list[str] = []
    verified_sequence_sources: list[str] = []
    bidirectional = 0
    monologue_dominant = 0
    for index, item in enumerate(sequences):
        path = f"speech.voice_sequences[{index}]"
        if not isinstance(item, dict):
            errors.append(_issue("invalid_sequence", path, "连续样本必须是对象。"))
            continue
        missing = [field for field in SEQUENCE_FIELDS if not item.get(field)]
        if missing:
            errors.append(_issue("missing_sequence_fields", path, "连续样本缺少字段：" + "、".join(missing)))
            continue
        sample_form = item.get("sample_form")
        if sample_form is not None and str(sample_form).strip() not in SAMPLE_FORMS:
            errors.append(_issue(
                "invalid_sample_form",
                f"{path}.sample_form",
                "sample_form 只能是 bond_choice / main_story_choice / scene_dialogue / momotalk。",
            ))
        source = str(item["source_id"]).strip()
        if not PURE_SOURCE_ID.fullmatch(source):
            errors.append(_issue("invalid_source_id", f"{path}.source_id", "source_id 必须是纯编号。"))
            continue
        turns = item.get("turns")
        if not isinstance(turns, list) or not 3 <= len(turns) <= 8:
            errors.append(_issue("invalid_turn_count", f"{path}.turns", "连续样本必须包含3-8轮。"))
            continue
        sequence_sources.append(source)
        target_turns = 0
        other_turns = 0
        for turn_index, turn in enumerate(turns):
            turn_path = f"{path}.turns[{turn_index}]"
            if not isinstance(turn, dict) or not str(turn.get("speaker", "")).strip() or not str(turn.get("line", "")).strip():
                errors.append(_issue("invalid_turn", turn_path, "话轮必须包含 speaker 与 line。"))
                continue
            if str(turn["speaker"]).strip().casefold() in target_names:
                target_turns += 1
            else:
                other_turns += 1
        had_status = bool(str(item.get("evidence_status", "")).strip())
        status = _evidence_status(item)
        if not had_status:
            missing_evidence += 1
        if status in VERIFIED_EVIDENCE:
            verified_sequence_sources.append(source)
        if target_turns and other_turns:
            bidirectional += 1
        if target_turns >= 3 and target_turns / len(turns) >= 0.75:
            monologue_dominant += 1

    if len(sequences) < 4:
        errors.append(_issue("too_few_sequences", "speech.voice_sequences", "至少需要4段连续样本。"))
    if len(set(sequence_sources)) < 4:
        errors.append(_issue("too_few_sequence_sources", "speech.voice_sequences", "连续样本至少覆盖4个来源。"))
    if bidirectional < 3:
        errors.append(_issue("too_few_bidirectional_sequences", "speech.voice_sequences", "至少需要3段真实双向承接。"))
    if monologue_dominant > 2:
        warnings.append(_issue("too_many_monologues", "speech.voice_sequences", "单方面说明型样本超过2段；普通写作可用，但连续承接覆盖偏弱。"))
    if missing_evidence:
        warnings.append(_issue(
            "evidence_not_locally_checked",
            "speech",
            "未提供本地官方语料；缺少 evidence_status 的样本按 external_unverified 保留，未冒充本地核验。",
            count=missing_evidence,
        ))

    status = "PASS" if not errors else "FAIL"
    production_ready = status == "PASS"
    report = {
        "schema_version": "ba-character-card-validation/1.0",
        "status": status,
        "character": str(cleaned.get("name", "")),
        "production_ready": production_ready,
        "open_humanness_ready": production_ready and len(set(verified_sequence_sources)) >= 2,
        "controlled_rewrite_ready": production_ready and len(set(verified_example_sources)) >= 2,
        "counts": {
            "voice_examples": len(examples),
            "voice_example_sources": len(set(example_sources)),
            "voice_sequences": len(sequences),
            "voice_sequence_sources": len(set(sequence_sources)),
            "locally_verified_example_sources": len(set(verified_example_sources)),
            "locally_verified_sequence_sources": len(set(verified_sequence_sources)),
            "bidirectional_sequences": bidirectional,
            "monologue_dominant_sequences": monologue_dominant,
        },
        "eligible_sources": {
            "voice_examples": sorted(set(verified_example_sources)),
            "voice_sequences": sorted(set(verified_sequence_sources)),
        },
        "safe_fixes": fixes,
        "errors": errors,
        "warnings": warnings,
    }
    return cleaned, report


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [item for child in value for item in _flatten_strings(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _flatten_strings(child)]
    return []


def _first_text(value: Any, fallback: str = "") -> str:
    values = _flatten_strings(value)
    return values[0] if values else fallback


def _relationships(relations: Any) -> list[dict]:
    result: list[dict] = []
    if isinstance(relations, dict):
        for target, value in relations.items():
            target_name = str(target).strip()
            if not target_name:
                continue
            if isinstance(value, dict):
                kind = str(value.get("kind") or value.get("relation") or "关系待定").strip()
                summary = _first_text(value.get("summary") or value.get("description") or value)
            else:
                kind = "关系待定"
                summary = _first_text(value)
            result.append({"target": target_name, "kind": kind or "关系待定", "summary": summary, "status": "confirmed"})
    elif isinstance(relations, list):
        for value in relations:
            if not isinstance(value, dict):
                continue
            target = str(value.get("target") or value.get("name") or value.get("character") or "").strip()
            if target:
                result.append({
                    "target": target,
                    "kind": str(value.get("kind") or value.get("relation") or "关系待定").strip(),
                    "summary": _first_text(value.get("summary") or value.get("description") or value),
                    "status": str(value.get("status") or "confirmed").strip(),
                })
    return result


def build_character_card_payload(parsed: "ParsedCharacterCard", source_label: str) -> dict:
    card = parsed.cleaned
    speech = card.get("speech") if isinstance(card.get("speech"), dict) else {}
    voice_source = {key: value for key, value in speech.items() if key not in {"voice_examples", "voice_sequences"}}
    voice_anchors = _flatten_strings(voice_source)[:4]
    if not voice_anchors:
        voice_anchors = ["完整 BA 人物主档已导入；运行时按结构化语音样本和人物边界抽取。"]
    ooc_constraints = _flatten_strings(card.get("ooc"))[:12]
    aliases = card.get("aliases", []) if isinstance(card.get("aliases"), list) else []
    canonical_name = str(card.get("canonical_name") or card.get("name") or "").strip()
    return {
        "name": str(card.get("name", "")).strip(),
        "canonical_name": canonical_name,
        "aliases": [str(item).strip() for item in aliases if str(item).strip()],
        "source_type": "official_reference",
        "role": _first_text(card.get("core")),
        "voice_anchors": voice_anchors,
        "knowledge_boundary": _first_text(card.get("knowledge_boundary") or card.get("knowledge") or card.get("core")),
        "ooc_constraints": ooc_constraints,
        "relationships": _relationships(card.get("relations")),
        "source_refs": [source_label, f"导入文件：{parsed.filename}"],
        "source_hash": parsed.source_hash,
        "profile_format": PROFILE_FORMAT,
        "extractor_version": EXTRACTOR_VERSION,
        "trust_status": "confirmed",
        "status": "active",
        "ba_profile": card,
        "validation_report": parsed.report,
        "import_filename": parsed.filename,
    }


@dataclass(frozen=True)
class ParsedCharacterCard:
    filename: str
    raw_bytes: bytes
    cleaned: dict
    cleaned_bytes: bytes
    source_hash: str
    report: dict

    def public_preview(self) -> dict:
        return {
            "filename": self.filename,
            "byte_size": len(self.raw_bytes),
            "source_hash": self.source_hash,
            "character": self.report.get("character", ""),
            "validation_report": self.report,
        }


def parse_import_payload(payload: dict) -> ParsedCharacterCard:
    filename = str(payload.get("filename", "")).strip()
    if not filename or not filename.lower().endswith(".json"):
        raise DomainError("invalid_character_card_file", "请选择 .json 格式的 BA 人物卡。", details={"field": "filename"})
    encoded = payload.get("content_base64")
    if not isinstance(encoded, str) or not encoded.strip():
        raise DomainError("invalid_character_card_file", "人物卡文件内容为空。", details={"field": "content_base64"})
    try:
        raw_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise DomainError("invalid_character_card_file", "人物卡文件编码无效。", details={"field": "content_base64"}) from exc
    if len(raw_bytes) > MAX_CHARACTER_CARD_BYTES:
        raise DomainError(
            "character_card_file_too_large",
            "人物卡文件不能超过 5 MB。",
            status=413,
            details={"max_bytes": MAX_CHARACTER_CARD_BYTES, "actual_bytes": len(raw_bytes)},
        )
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DomainError("invalid_character_card_file", "人物卡必须使用 UTF-8 编码。", details={"field": "content_base64"}) from exc
    try:
        raw_card = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DomainError(
            "invalid_character_card_json",
            "人物卡不是有效 JSON。",
            details={"line": exc.lineno, "column": exc.colno},
        ) from exc
    if not isinstance(raw_card, dict):
        raise DomainError("invalid_character_card_root", "人物卡 JSON 顶层必须是对象。", details={"actual_type": type(raw_card).__name__})
    cleaned, report = clean_and_validate(raw_card)
    cleaned_bytes = (json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return ParsedCharacterCard(
        filename=filename,
        raw_bytes=raw_bytes,
        cleaned=cleaned,
        cleaned_bytes=cleaned_bytes,
        source_hash=sha256_bytes(raw_bytes),
        report=report,
    )


def validation_failure(parsed: ParsedCharacterCard) -> DomainError:
    return DomainError(
        "character_card_validation_failed",
        "BA 人物卡结构验证未通过。",
        status=422,
        details={"preview": parsed.public_preview()},
    )


def identity_tokens(content: dict) -> set[str]:
    values = [content.get("name"), content.get("canonical_name")]
    values.extend(content.get("aliases", []) if isinstance(content.get("aliases"), list) else [])
    profile = content.get("ba_profile")
    if isinstance(profile, dict):
        values.extend([profile.get("name"), profile.get("canonical_name")])
        values.extend(profile.get("aliases", []) if isinstance(profile.get("aliases"), list) else [])
    return {str(value).strip().casefold() for value in values if str(value or "").strip()}


def cleaned_digest(parsed: ParsedCharacterCard) -> str:
    return sha256_bytes(canonical_json(parsed.cleaned).encode("utf-8"))
