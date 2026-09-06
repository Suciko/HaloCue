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


MAX_WORLD_CARD_BYTES = 5_000_000
PROFILE_FORMAT = "ba-world-card/full/1.0"
EXTRACTOR_VERSION = "halocue-ba-world-import/1.0"
SOURCE_TYPES = {"official_reference", "custom", "mixed", "ba_starter"}
KINDS = {"place", "academy", "organization", "object", "technology", "custom"}
STATUSES = {"confirmed", "inferred", "open", "conflict", "retired"}
SCOPES = {"work", "chapter", "scene"}
ITEM_STATUS = {"active", "archived"}
_CITATION_PATTERNS = (
    re.compile(r":?contentReference\[[^\]]*\]\{[^}]*\}"),
    re.compile(r"\[oaicite:[^\]]+\]"),
    re.compile(r"cite[^]+"),
)


def _issue(code: str, path: str, message: str, **extra: Any) -> dict:
    result = {"code": code, "path": path, "message": message}
    result.update(extra)
    return result


def _clean_string(value: str) -> str:
    cleaned = value
    for pattern in _CITATION_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def _walk_clean(value: Any, fixes: list[dict], path: str = "") -> Any:
    if isinstance(value, str):
        cleaned = _clean_string(value)
        if cleaned != value:
            fixes.append(_issue("clean_whitespace_or_citation", path, "清理引用残留或多余空白。"))
        return cleaned
    if isinstance(value, list):
        return [_walk_clean(item, fixes, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        return {
            key: _walk_clean(item, fixes, f"{path}.{key}" if path else key)
            for key, item in value.items()
        }
    return copy.deepcopy(value)


def _string_list(value: Any, path: str, errors: list[dict]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(_issue("invalid_array", path, "字段必须是数组。"))
        return []
    result = []
    for index, item in enumerate(value):
        text = str(item).strip()
        if text:
            result.append(text)
        else:
            errors.append(_issue("empty_item", f"{path}[{index}]", "数组项不能为空。"))
    return list(dict.fromkeys(result))


def _normalize_items(items: Any, collection: str, errors: list[dict]) -> list[dict]:
    if items is None:
        return []
    if not isinstance(items, list):
        errors.append(_issue("invalid_array", collection, "字段必须是数组。"))
        return []
    result: list[dict] = []
    for index, raw in enumerate(items):
        path = f"{collection}[{index}]"
        if not isinstance(raw, dict):
            errors.append(_issue("invalid_item", path, "条目必须是对象。"))
            continue
        item = dict(raw)
        if collection == "entities":
            name = str(item.get("name", "")).strip()
            if not name:
                errors.append(_issue("required_field", f"{path}.name", "世界观卡需要名称。"))
            kind = str(item.get("kind", "custom")).strip() or "custom"
            if kind not in KINDS:
                errors.append(_issue("invalid_kind", f"{path}.kind", "世界观卡类型无效。", allowed=sorted(KINDS)))
            item["name"] = name
            item["kind"] = kind
            item["summary"] = str(item.get("summary", "")).strip()
            item["aliases"] = _string_list(item.get("aliases", []), f"{path}.aliases", errors)
        else:
            text = str(item.get("text", item.get("label", ""))).strip()
            if not text:
                errors.append(_issue("required_field", f"{path}.text", "条目需要内容。"))
            item["text"] = text
            item["category"] = str(item.get("category", "general")).strip() or "general"
        source = str(item.get("source", "")).strip()
        if not source:
            errors.append(_issue("required_field", f"{path}.source", "每条资料都需要来源。"))
        confidence = str(item.get("confidence_status", "open")).strip() or "open"
        if confidence not in STATUSES:
            errors.append(_issue("invalid_confidence_status", f"{path}.confidence_status", "可信状态无效。"))
        scope = str(item.get("scope", "work")).strip() or "work"
        if scope not in SCOPES:
            errors.append(_issue("invalid_scope", f"{path}.scope", "作用域无效。"))
        status = str(item.get("status", "active")).strip() or "active"
        if status not in ITEM_STATUS:
            errors.append(_issue("invalid_status", f"{path}.status", "条目状态无效。"))
        item["source"] = source
        item["confidence_status"] = confidence
        item["scope"] = scope
        item["participants"] = _string_list(item.get("participants", []), f"{path}.participants", errors)
        item["status"] = status
        item["id"] = str(item.get("id", "")).strip()
        if collection == "entities":
            item["source_type"] = str(item.get("source_type", "")).strip()
            if item["source_type"] and item["source_type"] not in SOURCE_TYPES:
                errors.append(_issue("invalid_source_type", f"{path}.source_type", "世界观卡来源类型无效。"))
            item["related_world_ids"] = _string_list(item.get("related_world_ids", []), f"{path}.related_world_ids", errors)
        result.append(item)
    return result


def clean_and_validate(document: dict) -> tuple[dict, dict]:
    fixes: list[dict] = []
    cleaned = _walk_clean(document, fixes)
    errors: list[dict] = []
    warnings: list[dict] = []
    title = str(cleaned.get("title", "")).strip()
    if not title:
        errors.append(_issue("required_field", "title", "世界观资料需要标题。"))
    source_type = str(cleaned.get("source_type", "custom")).strip() or "custom"
    if source_type not in SOURCE_TYPES:
        errors.append(_issue("invalid_source_type", "source_type", "世界观来源类型无效。"))
    entities = _normalize_items(cleaned.get("entities", []), "entities", errors)
    rules = _normalize_items(cleaned.get("rules", []), "rules", errors)
    timeline = _normalize_items(cleaned.get("timeline", []), "timeline", errors)
    if not entities and not rules and not timeline:
        errors.append(_issue("empty_world_document", "", "至少需要一张世界观卡、规则或时间线事件。"))
    ids: set[str] = set()
    identity_sets: list[tuple[int, set[str]]] = []
    for index, entity in enumerate(entities):
        entity_id = entity.get("id")
        if entity_id:
            if entity_id in ids:
                errors.append(_issue("duplicate_id", f"entities[{index}].id", "世界观卡 ID 必须唯一。", id=entity_id))
            ids.add(entity_id)
        tokens = identity_tokens(entity)
        for previous_index, previous_tokens in identity_sets:
            if tokens.intersection(previous_tokens):
                errors.append(_issue("duplicate_identity", f"entities[{index}]", "同一份资料中不能有名称或别名相交的重复世界观卡。", duplicate_of=previous_index))
        identity_sets.append((index, tokens))
    for index, entity in enumerate(entities):
        invalid = [value for value in entity.get("related_world_ids", []) if value not in ids or value == entity.get("id")]
        if invalid:
            errors.append(_issue("invalid_relation", f"entities[{index}].related_world_ids", "关联必须指向文档中的其他世界观卡。", ids=invalid))
    for collection, items in (("entities", entities), ("rules", rules), ("timeline", timeline)):
        missing = sum(1 for item in items if item.get("confidence_status") == "open")
        if missing:
            warnings.append(_issue("unconfirmed_items", collection, "待核对条目会保留在资料库，但不会进入场景 Agent。", count=missing))
        if any(not item.get("source_type") for item in items if collection == "entities"):
            warnings.append(_issue("implicit_source_type", collection, "未标注 source_type 的卡将继承文档来源类型。"))
    cleaned.update({"title": title, "source_type": source_type, "entities": entities, "rules": rules, "timeline": timeline})
    report = {
        "schema_version": "ba-world-card-validation/1.0",
        "status": "PASS" if not errors else "FAIL",
        "production_ready": not errors,
        "counts": {"entities": len(entities), "rules": len(rules), "timeline": len(timeline), "confirmed": sum(item.get("confidence_status") == "confirmed" for item in (*entities, *rules, *timeline))},
        "safe_fixes": fixes,
        "errors": errors,
        "warnings": warnings,
    }
    return cleaned, report


@dataclass(frozen=True)
class ParsedWorldCard:
    filename: str
    raw_bytes: bytes
    cleaned: dict
    cleaned_bytes: bytes
    source_hash: str
    report: dict

    def public_preview(self) -> dict:
        return {"filename": self.filename, "byte_size": len(self.raw_bytes), "source_hash": self.source_hash, "title": self.cleaned.get("title", ""), "validation_report": self.report}


def parse_import_payload(payload: dict) -> ParsedWorldCard:
    filename = str(payload.get("filename", "")).strip()
    if not filename or not filename.lower().endswith(".json"):
        raise DomainError("invalid_world_card_file", "请选择 .json 格式的 BA 世界观卡。", details={"field": "filename"})
    encoded = payload.get("content_base64")
    if not isinstance(encoded, str) or not encoded.strip():
        raise DomainError("invalid_world_card_file", "世界观卡文件内容为空。", details={"field": "content_base64"})
    try:
        raw_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise DomainError("invalid_world_card_file", "世界观卡文件编码无效。", details={"field": "content_base64"}) from exc
    if len(raw_bytes) > MAX_WORLD_CARD_BYTES:
        raise DomainError("world_card_file_too_large", "世界观卡文件不能超过 5 MB。", status=413, details={"max_bytes": MAX_WORLD_CARD_BYTES, "actual_bytes": len(raw_bytes)})
    try:
        raw_document = json.loads(raw_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise DomainError("invalid_world_card_file", "世界观卡必须使用 UTF-8 编码。", details={"field": "content_base64"}) from exc
    except json.JSONDecodeError as exc:
        raise DomainError("invalid_world_card_json", "世界观卡不是有效 JSON。", details={"line": exc.lineno, "column": exc.colno}) from exc
    if not isinstance(raw_document, dict):
        raise DomainError("invalid_world_card_root", "世界观卡 JSON 顶层必须是对象。", details={"actual_type": type(raw_document).__name__})
    cleaned, report = clean_and_validate(raw_document)
    cleaned_bytes = (json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return ParsedWorldCard(filename, raw_bytes, cleaned, cleaned_bytes, sha256_bytes(raw_bytes), report)


def validation_failure(parsed: ParsedWorldCard) -> DomainError:
    return DomainError("world_card_validation_failed", "BA 世界观卡结构验证未通过。", status=422, details={"preview": parsed.public_preview()})


def identity_tokens(entity: dict) -> set[str]:
    values = [entity.get("name"), *entity.get("aliases", [])]
    return {str(value).strip().casefold() for value in values if str(value or "").strip()}


def cleaned_digest(parsed: ParsedWorldCard) -> str:
    return sha256_bytes(canonical_json(parsed.cleaned).encode("utf-8"))
