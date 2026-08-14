# -*- coding: utf-8 -*-
"""Multimodal semantic labels for rendered Spine face animations."""

from __future__ import annotations

import io
import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

import assetdb
from face_semantics import (
    CONTROLLED_BEAT_FIT,
    compact_label_cache,
    normalize_semantic_payload,
)
from spine_face_renderer import RenderedFace


_EDITABLE_FACE_FIELDS = frozenset({
    "primary_emotion",
    "secondary_emotions",
    "valence",
    "arousal",
    "eyes",
    "brows",
    "mouth",
    "blush",
    "tears",
    "description_cn",
    "usage_hint_cn",
    "emotion_family",
    "intensity",
    "expression_class",
    "beat_fit",
    "hold_policy",
    "special_tags",
    "search_terms_cn",
    "near_duplicate_of",
    "avoid_when_cn",
})

_SEMANTIC_FIELDS = frozenset({
    "emotion_family", "intensity", "expression_class", "beat_fit",
    "hold_policy", "special_tags", "search_terms_cn", "near_duplicate_of",
    "avoid_when_cn",
})
_EMOTION_FAMILIES = frozenset({
    "neutral", "joy", "surprise_fear", "embarrassment",
    "irritation_anger", "sadness_hurt", "confusion_resignation",
})
_EXPRESSION_CLASSES = frozenset({"base", "accent", "peak", "special"})
_HOLD_POLICIES = frozenset({"hold", "short", "flash"})
_VISUAL_USAGE_MARKERS = (
    "眼睛", "眼神", "睁眼", "闭眼", "眉毛", "眉头", "嘴巴", "嘴角",
    "脸红", "泛红", "泪水", "流泪", "冷汗", "画面中", "图中",
)


VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "face_id": {"type": "string"},
                    "primary_emotion": {"type": "string"},
                    "usage_hint_cn": {"type": "string"},
                    "confidence": {"type": "number"},
                    "emotion_family": {"type": "string", "enum": sorted(_EMOTION_FAMILIES)},
                    "intensity": {"type": "integer", "minimum": 0, "maximum": 3},
                    "expression_class": {"type": "string", "enum": sorted(_EXPRESSION_CLASSES)},
                    "beat_fit": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(CONTROLLED_BEAT_FIT)},
                    },
                    "hold_policy": {"type": "string", "enum": sorted(_HOLD_POLICIES)},
                    "search_terms_cn": {"type": "array", "items": {"type": "string"}},
                    "avoid_when_cn": {"type": "string"},
                },
                "required": [
                    "face_id",
                    "primary_emotion",
                    "usage_hint_cn",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


_VISION_STRING_FIELDS = frozenset({
    "face_id", "primary_emotion", "usage_hint_cn",
})


def usage_hint_cn(item: Mapping) -> str:
    """Return the selection hint from the compact or legacy label shape."""
    return str(
        item.get("usage_hint_cn") or item.get("description_cn") or ""
    ).strip()


def _manual_usage_hint(item: Mapping) -> tuple[bool, str]:
    """Return whether a manual hint override exists, including an empty one."""
    if "description_cn" in item:
        return True, str(item.get("description_cn") or "").strip()
    if "usage_hint_cn" in item:
        return True, str(item.get("usage_hint_cn") or "").strip()
    return False, ""


def selection_semantics(primary_emotion: str, usage_hint: str) -> str:
    """Combine the two fields the story model uses to choose a face."""
    emotion = str(primary_emotion or "").strip()
    hint = str(usage_hint or "").strip()
    if emotion and hint and emotion != hint:
        return f"{emotion}｜{hint}"
    return emotion or hint


def _compact_vision_item(item: Mapping) -> dict:
    compact = dict(item)
    if "usage_hint_cn" in item:
        compact["usage_hint_cn"] = item.get("usage_hint_cn")
    elif "description_cn" in item:
        compact["usage_hint_cn"] = item.get("description_cn")
    return compact


def _valid_vision_item(item: dict, required: set[str]) -> bool:
    if not required.issubset(item):
        return False
    if any(not isinstance(item.get(field), str) for field in _VISION_STRING_FIELDS):
        return False
    confidence = item.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return False
    if not math.isfinite(float(confidence)) or not 0.0 <= float(confidence) <= 1.0:
        return False
    family = item.get("emotion_family")
    if family is not None and family not in _EMOTION_FAMILIES:
        return False
    intensity = item.get("intensity")
    if intensity is not None and (
        isinstance(intensity, bool) or not isinstance(intensity, int)
        or not 0 <= intensity <= 3
    ):
        return False
    expression_class = item.get("expression_class")
    if expression_class is not None and expression_class not in _EXPRESSION_CLASSES:
        return False
    hold_policy = item.get("hold_policy")
    if hold_policy is not None and hold_policy not in _HOLD_POLICIES:
        return False
    for field in ("beat_fit", "search_terms_cn"):
        value = item.get(field)
        if value is not None and (
            not isinstance(value, list) or any(not isinstance(entry, str) for entry in value)
        ):
            return False
    if any(value not in CONTROLLED_BEAT_FIT for value in item.get("beat_fit") or []):
        return False
    if "avoid_when_cn" in item and not isinstance(item["avoid_when_cn"], str):
        return False
    return True


_SYSTEM = """你在为视觉小说角色立绘建立供剧情选择的表情语义表。
只判断整体情绪、态度和适用的台词语境，不拆解或描述脸部零件。
不要根据编号猜测，不要根据文件名猜测，也不要把服装、姿势或角色身份当成情绪。
同一批图片属于同一角色，重点比较它们之间的细微差别。
primary_emotion 使用简洁自然的中文，例如“轻微微笑”“不满”“尴尬”“惊讶”。
usage_hint_cn 写成一句简短的使用语境，例如适合怎样的台词、语气、反应或情绪阶段。
使用语境不是关键词触发规则，不得用是否脸红、是否流泪等视觉现象决定是否使用。
不同 face_id 可以拥有完全相同的情绪和使用语境，不要为了区分编号强行制造差异。
如果输出结构允许，还要填写：emotion_family（七类情绪族）、intensity（0-3）、
expression_class（base/accent/peak/special）、beat_fit（适合的剧情节拍）、
hold_policy（hold/short/flash）、special_tags 和 avoid_when_cn。
这些字段描述剧情使用方式，不得改写成眉眼嘴等视觉零件清单。
置信度范围为 0 到 1；确实模糊时降低置信度，不要硬猜。"""


_SYSTEM += """
跨批次标注同一角色时，CHARACTER_LABEL_CACHE 是已经确认的同角色表情摘要。
必须比较缓存与当前图片，找出当前表情可见的最小语义差异，并让使用语境足以区分实际用途；不得仅换同义词制造区别。
如果画面确实等价，可以保持相同语义，但不得根据编号臆造差别。
beat_fit 只能使用给定枚举；自由中文检索词只能写入 search_terms_cn。
"""


def _needs_single_face_review(record: Mapping, confidence_threshold: float) -> bool:
    if record.get("failed"):
        return True
    if float(record.get("confidence") or 0.0) < confidence_threshold:
        return True
    emotion = str(record.get("primary_emotion") or "").strip()
    usage = usage_hint_cn(record)
    if not emotion or len(usage) < 4:
        return True
    return any(marker in usage for marker in _VISUAL_USAGE_MARKERS)


def make_vision_sheet(
    faces: Sequence[RenderedFace],
    *,
    cell_size: int = 384,
    columns: int = 2,
) -> tuple[bytes, list[str]]:
    """Build one fixed 3x3 comparison sheet with readable face IDs."""
    if columns not in (2, 3):
        raise ValueError("vision sheets must use two or three columns")
    max_faces = 4 if columns == 2 else 9
    if not 1 <= len(faces) <= max_faces:
        raise ValueError(f"vision sheets must contain between 1 and {max_faces} faces")
    if cell_size < 120:
        raise ValueError("vision sheet cells must be at least 120 pixels")
    ordered = sorted(faces, key=lambda face: face.face_id)
    face_ids = [face.face_id for face in ordered]
    sheet = Image.new(
        "RGB",
        (columns * cell_size, columns * cell_size),
        (54, 57, 63),
    )
    draw = ImageDraw.Draw(sheet)
    label_height = max(38, cell_size // 7)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(22, cell_size // 11))
    except OSError:
        font = ImageFont.load_default()
    for index, face in enumerate(ordered):
        x = (index % columns) * cell_size
        y = (index // columns) * cell_size
        tile = Image.new("RGB", (cell_size, cell_size), (226, 228, 232))
        head = Image.open(face.head_path).convert("RGBA")
        head.thumbnail(
            (cell_size - 20, cell_size - label_height - 18),
            Image.Resampling.LANCZOS,
        )
        tile.paste(
            head.convert("RGB"),
            ((cell_size - head.width) // 2, (cell_size - label_height - head.height) // 2),
            head.getchannel("A"),
        )
        sheet.paste(tile, (x, y))
        draw.rectangle(
            (x, y + cell_size - label_height, x + cell_size, y + cell_size),
            fill=(19, 25, 36),
        )
        label = f"FACE {face.face_id}"
        draw.text(
            (x + 12, y + cell_size - label_height + 5),
            label,
            fill=(255, 255, 255),
            font=font,
        )
    buffer = io.BytesIO()
    sheet.save(buffer, format="JPEG", quality=92, optimize=True)
    return buffer.getvalue(), face_ids


def label_face_images(
    provider,
    faces: Sequence[RenderedFace],
    *,
    batch_size: int = 4,
    batch_workers: int = 2,
    confidence_threshold: float = 0.6,
    semantic_hints: dict[str, dict] | None = None,
    comparison_memory: bool = False,
    max_attempts: int = 3,
    progress: Callable[[int, int, int, int], None] | None = None,
) -> list[dict]:
    """Label numbered 3x3 sheets concurrently, then review uncertain faces."""
    if not 1 <= batch_size <= 9:
        raise ValueError("batch_size must be between 1 and 9")
    if batch_workers < 1:
        raise ValueError("batch_workers must be at least 1")
    if not 0 <= confidence_threshold <= 1:
        raise ValueError("confidence_threshold must be between 0 and 1")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    ordered = sorted(faces, key=lambda face: face.face_id)
    hints = semantic_hints or {}
    if not ordered:
        return []
    batches = [
        ordered[start : start + batch_size]
        for start in range(0, len(ordered), batch_size)
    ]
    initial_singletons = {
        batch[0].face_id for batch in batches if len(batch) == 1
    }
    required = set(VISION_SCHEMA["properties"]["items"]["items"]["required"])

    def request_batch(
        batch: Sequence[RenderedFace], prior_records: Sequence[Mapping] = ()
    ) -> list[dict]:
        sheet, expected = make_vision_sheet(batch, columns=2 if len(batch) <= 4 else 3)
        images = [("编号九宫格:" + ",".join(expected), sheet)]
        hint_lines = []
        for face in batch:
            labels = hints.get(face.face_id, {}).get("labels") or []
            if labels:
                hint_lines.append(
                    f"{face.face_id}: 骨骼部件名候选={','.join(map(str, labels))}"
                )
        user = (
            "请读取这张带 FACE 编号的九宫格，逐格标注以下 face_id，"
            "返回数量和编号必须完全一致："
            + "、".join(expected)
            + '\n必须只返回一个 JSON 对象，根键必须是 "items"。'
            + "items 数组中每项必须完整包含：face_id、primary_emotion、"
            + "usage_hint_cn、confidence。"
            + "只写整体情绪和使用语境，不要描述眼睛、眉毛、嘴部、脸红或泪水。"
        )
        if hint_lines:
            user += (
                "\n以下只是制作者命名提供的弱提示；与画面冲突时必须以画面为准：\n"
                + "\n".join(hint_lines)
            )
        cache = compact_label_cache(prior_records)
        if comparison_memory and cache:
            user += (
                "\n\nCHARACTER_LABEL_CACHE（同一角色此前已完成的表情，仅用于比较和避免语义重复）：\n"
                + cache
                + "\n请明确区分当前图片与缓存中最接近的表情；不得只改同义词，也不得编造画面中不存在的差异。"
            )
        last_error: Exception | None = None
        items: list[dict] | None = None
        for attempt in range(1, max_attempts + 1):
            attempt_user = user
            if attempt > 1:
                attempt_user += (
                    f"\n这是第 {attempt} 次校正请求。上次响应为空、结构错误或字段不完整。"
                    "不要使用 Markdown 说明，不要省略字段，严格按上述 JSON 结构重答。"
                )
            try:
                response = provider.complete_json_vision(
                    _SYSTEM, images, attempt_user, VISION_SCHEMA
                )
                if not isinstance(response, dict):
                    raise ValueError("response root is not an object")
                candidate = response.get("items")
                if not isinstance(candidate, list):
                    raise ValueError('response root does not contain an "items" array')
                if not all(isinstance(item, dict) for item in candidate):
                    raise ValueError("items contains a non-object value")
                items = [_compact_vision_item(item) for item in candidate]
                last_error = None
                break
            except Exception as exc:
                last_error = exc
        occurrences: dict[str, list[dict]] = {face_id: [] for face_id in expected}
        for item in items or []:
            face_id = str(item.get("face_id") or "")
            if face_id in occurrences:
                occurrences[face_id].append(item)
        records = []
        for face in batch:
            matches = occurrences[face.face_id]
            if len(matches) != 1 or not _valid_vision_item(matches[0], required):
                records.append({
                    "face_id": face.face_id,
                    "head_path": str(face.head_path),
                    "failed": True,
                    "error": "vision_label_failed",
                })
                continue
            record = dict(matches[0])
            record["face_id"] = face.face_id
            record["head_path"] = str(face.head_path)
            record["confidence"] = max(
                0.0, min(1.0, float(record.get("confidence") or 0.0))
            )
            records.append(record)
        return records

    completed = 0
    completed_batches = 0
    reviewed = 0
    state_lock = threading.Lock()
    if comparison_memory:
        results = []
        for batch in batches:
            records = request_batch(batch, results)
            results.extend(records)
            completed += len(records)
            completed_batches += 1
            if progress:
                progress(completed, len(ordered), completed_batches, reviewed)
    else:
        batch_results: dict[int, list[dict]] = {}
        with ThreadPoolExecutor(max_workers=min(2, batch_workers, len(batches))) as executor:
            future_to_index = {
                executor.submit(request_batch, batch): index
                for index, batch in enumerate(batches)
            }
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                records = future.result()
                batch_results[index] = records
                with state_lock:
                    completed += len(records)
                    completed_batches += 1
                    if progress:
                        progress(completed, len(ordered), completed_batches, reviewed)
        results = [
            record
            for index in range(len(batches))
            for record in batch_results[index]
        ]

    duplicate_of = {}
    if comparison_memory:
        seen_semantics = {}
        for record in results:
            if record.get("failed"):
                continue
            key = (
                str(record.get("primary_emotion") or "").strip().casefold(),
                usage_hint_cn(record).casefold(),
            )
            if key in seen_semantics:
                duplicate_of[str(record["face_id"])] = seen_semantics[key]
            else:
                seen_semantics[key] = str(record["face_id"])
    face_by_id = {face.face_id: face for face in ordered}
    for index, record in enumerate(list(results)):
        face_id = str(record["face_id"])
        if record.get("failed") and face_id in initial_singletons:
            continue
        if (
            not _needs_single_face_review(record, confidence_threshold)
            and face_id not in duplicate_of
        ):
            continue
        comparison = [
            other for other in results if str(other.get("face_id")) != face_id
        ] if comparison_memory else []
        reviewed_record = request_batch([face_by_id[face_id]], comparison)[0]
        if record.get("failed") or not reviewed_record.get("failed"):
            results[index] = reviewed_record
        if face_id in duplicate_of and not reviewed_record.get("failed"):
            reference = duplicate_of[face_id]
            reference_record = next(
                (item for item in results if str(item.get("face_id")) == reference), {}
            )
            reviewed_key = (
                str(reviewed_record.get("primary_emotion") or "").strip().casefold(),
                usage_hint_cn(reviewed_record).casefold(),
            )
            reference_key = (
                str(reference_record.get("primary_emotion") or "").strip().casefold(),
                usage_hint_cn(reference_record).casefold(),
            )
            if reviewed_key == reference_key:
                results[index]["near_duplicate_of"] = reference
        reviewed += 1
        if progress:
            progress(completed, len(ordered), completed_batches, reviewed)
    return sorted(results, key=lambda item: str(item["face_id"]))


def persist_visual_face_labels(
    con,
    *,
    ident: str,
    spine_signature: str,
    outfit_key: str,
    model: str,
    labels: Iterable[dict],
) -> dict:
    """Upsert one model's labels while retaining user-authored overrides."""
    ident = str(ident)
    signature = str(spine_signature or "")
    outfit = str(outfit_key or "")
    model = str(model)
    source = f"vision:{model}"
    records = [normalize_semantic_payload(item) for item in labels]
    con.execute(
        """
        INSERT OR IGNORE INTO character_variant(ident,spine_signature,outfit_key,spine)
        VALUES (?, ?, ?, '')
        """,
        (ident, signature, outfit),
    )
    completed_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    for item in records:
        face_id = str(item["face_id"])
        if item.get("failed"):
            continue
        primary = str(item.get("primary_emotion") or "").strip()
        secondary = [
            str(value).strip()
            for value in item.get("secondary_emotions") or []
            if str(value).strip()
        ]
        manual_row = con.execute(
            """
            SELECT manual_json FROM face_visual_label
            WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
              AND manual_json IS NOT NULL AND manual_json!='{}'
            ORDER BY updated_at DESC, model
            LIMIT 1
            """,
            (ident, signature, outfit, face_id),
        ).fetchone()
        manual = _safe_json_object(manual_row["manual_json"] if manual_row else "{}")
        con.execute(
            """
            INSERT INTO face_visual_label
              (ident,spine_signature,outfit_key,face_id,model,primary_emotion,
               secondary_json,valence,arousal,eyes,brows,mouth,blush,tears,
               confidence,description_cn,semantic_json,head_path,reviewed,manual_json,version,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ident,spine_signature,outfit_key,face_id,model) DO UPDATE SET
              primary_emotion=excluded.primary_emotion,
              secondary_json=excluded.secondary_json,
              valence=excluded.valence,
              arousal=excluded.arousal,
              eyes=excluded.eyes,
              brows=excluded.brows,
              mouth=excluded.mouth,
              blush=excluded.blush,
              tears=excluded.tears,
              confidence=excluded.confidence,
              description_cn=excluded.description_cn,
              semantic_json=excluded.semantic_json,
              head_path=excluded.head_path,
              version=face_visual_label.version+1,
              updated_at=excluded.updated_at
            """,
            (
                ident,
                signature,
                outfit,
                face_id,
                model,
                primary,
                json.dumps(secondary, ensure_ascii=False),
                str(item.get("valence") or ""),
                str(item.get("arousal") or ""),
                str(item.get("eyes") or ""),
                str(item.get("brows") or ""),
                str(item.get("mouth") or ""),
                int(bool(item.get("blush"))),
                int(bool(item.get("tears"))),
                float(item.get("confidence") or 0.0),
                usage_hint_cn(item),
                json.dumps(
                    {key: item[key] for key in _SEMANTIC_FIELDS if key in item},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                str(item.get("head_path") or ""),
                int(bool(manual)),
                json.dumps(manual, ensure_ascii=False, separators=(",", ":")),
                1,
                completed_at,
            ),
        )
        effective_primary = str(manual.get("primary_emotion", primary))
        has_manual_usage, manual_usage = _manual_usage_hint(manual)
        effective_usage = (
            manual_usage if has_manual_usage else usage_hint_cn(item)
        )
        effective_semantics = selection_semantics(
            effective_primary, effective_usage
        )
        con.execute(
            """
            DELETE FROM face_evidence
            WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
              AND source=?
            """,
            (ident, signature, outfit, face_id, source),
        )
        con.execute(
            """
            INSERT INTO face_evidence
              (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count)
            VALUES (?,?,?,?,?,?,?,?,0)
            """,
            (
                ident,
                signature,
                outfit,
                face_id,
                source,
                json.dumps(item, ensure_ascii=False),
                effective_semantics,
                effective_semantics,
            ),
        )
    con.commit()
    failures = [
        {
            "face_id": str(item["face_id"]),
            "error": str(item.get("error") or "vision_label_failed"),
        }
        for item in records
        if item.get("failed")
    ]
    return {
        "saved_count": len(records) - len(failures),
        "failed_count": len(failures),
        "failures": failures,
        "completed_at": completed_at,
    }


def refresh_visual_face_preview_paths(
    con,
    *,
    ident: str,
    spine_signature: str,
    outfit_key: str,
    faces: Iterable[RenderedFace],
) -> int:
    """Point every saved model row at the latest rendered head preview."""
    scope = (
        str(ident),
        str(spine_signature or ""),
        str(outfit_key or ""),
    )
    updated_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    changed = 0
    for face in faces:
        head_path = str(Path(face.head_path).resolve())
        cursor = con.execute(
            """
            UPDATE face_visual_label
            SET head_path=?, version=version+1, updated_at=?
            WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
              AND COALESCE(head_path, '')<>?
            """,
            (
                head_path,
                updated_at,
                *scope,
                str(face.face_id),
                head_path,
            ),
        )
        changed += max(0, int(cursor.rowcount or 0))
    con.commit()
    return changed


def _safe_json_object(value) -> dict:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _visual_label_record(row) -> dict:
    try:
        secondary = json.loads(row["secondary_json"] or "[]")
    except (TypeError, ValueError):
        secondary = []
    if not isinstance(secondary, list):
        secondary = []
    hint = str(row["description_cn"] or "")
    try:
        semantic = normalize_semantic_payload(_safe_json_object(row["semantic_json"]))
    except (KeyError, TypeError):
        semantic = {}
    ai = {
        "primary_emotion": str(row["primary_emotion"] or ""),
        "secondary_emotions": [str(value) for value in secondary],
        "valence": str(row["valence"] or ""),
        "arousal": str(row["arousal"] or ""),
        "eyes": str(row["eyes"] or ""),
        "brows": str(row["brows"] or ""),
        "mouth": str(row["mouth"] or ""),
        "blush": bool(row["blush"]),
        "tears": bool(row["tears"]),
        "confidence": max(0.0, min(1.0, float(row["confidence"] or 0.0))),
        "description_cn": str(row["description_cn"] or ""),
        "usage_hint_cn": hint,
    }
    ai.update(semantic)
    ai["semantic_level"] = "rich" if semantic else (
        "basic" if ai["primary_emotion"] or ai["usage_hint_cn"] else "unknown"
    )
    manual = {
        key: value
        for key, value in _safe_json_object(row["manual_json"]).items()
        if key in _EDITABLE_FACE_FIELDS
    }
    has_manual_hint, manual_hint = _manual_usage_hint(manual)
    if has_manual_hint:
        manual["usage_hint_cn"] = manual_hint
        manual["description_cn"] = manual_hint
    effective = normalize_semantic_payload({**ai, **manual})
    effective_hint = manual_hint if has_manual_hint else hint
    effective["usage_hint_cn"] = effective_hint
    effective["description_cn"] = effective_hint
    return {
        "ident": str(row["ident"]),
        "spine_signature": str(row["spine_signature"]),
        "outfit_key": str(row["outfit_key"]),
        "face_id": str(row["face_id"]),
        "model": str(row["model"]),
        "ai": ai,
        "manual": manual,
        "effective": effective,
        "head_path": str(row["head_path"] or ""),
        "reviewed": bool(manual),
        "version": max(1, int(row["version"] or 1)),
        "updated_at": str(row["updated_at"] or ""),
    }


def list_visual_face_labels(
    con,
    *,
    ident: str,
    spine_signature: str,
    outfit_key: str,
) -> list[dict]:
    """Return one current, editable visual record for every face ID."""
    rows = assetdb.effective_visual_label_rows(
        con,
        ident=str(ident),
        spine_signature=str(spine_signature or ""),
        outfit_key=str(outfit_key or ""),
    )
    records: dict[str, dict] = {}
    for row in rows:
        face_id = str(row["face_id"])
        records.setdefault(face_id, _visual_label_record(row))
    return [records[face_id] for face_id in sorted(records)]


def _validate_manual_patch(patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("标注内容必须是对象")
    unknown = set(patch) - _EDITABLE_FACE_FIELDS
    if unknown:
        raise ValueError("不支持的标注字段：" + "、".join(sorted(unknown)))
    if (
        "usage_hint_cn" in patch
        and "description_cn" in patch
        and patch["usage_hint_cn"] != patch["description_cn"]
    ):
        raise ValueError("usage_hint_cn 与 description_cn 不能冲突")
    normalized = dict(patch)
    if "usage_hint_cn" in normalized:
        normalized["description_cn"] = normalized.pop("usage_hint_cn")
    clean = {}
    for key, value in normalized.items():
        if value is None:
            clean[key] = None
        elif key in {"blush", "tears"}:
            if not isinstance(value, bool):
                raise ValueError(f"标注字段 {key} 必须是布尔值")
            clean[key] = value
        elif key in {"secondary_emotions", "beat_fit", "special_tags", "search_terms_cn"}:
            if not isinstance(value, list):
                raise ValueError(f"标注字段 {key} 必须是数组")
            clean[key] = [str(item).strip() for item in value if str(item).strip()]
        else:
            clean[key] = str(value).strip()
    if any(
        value not in CONTROLLED_BEAT_FIT
        for value in clean.get("beat_fit") or []
        if value is not None
    ):
        raise ValueError("标注字段 beat_fit 包含未受控的节拍值")
    return clean


def update_visual_face_label(
    con,
    *,
    ident: str,
    spine_signature: str,
    outfit_key: str,
    face_id: str,
    patch: dict,
    expected_version: int,
) -> dict:
    """Apply a manual override with optimistic locking and return merged data."""
    clean = _validate_manual_patch(patch)
    scope = (
        str(ident), str(spine_signature or ""), str(outfit_key or ""), str(face_id)
    )
    row = con.execute(
        """
        SELECT * FROM face_visual_label
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
        ORDER BY updated_at DESC, confidence DESC, model
        LIMIT 1
        """,
        scope,
    ).fetchone()
    if row is None:
        raise KeyError("表情标注不存在")
    if int(row["version"] or 1) != int(expected_version):
        raise ValueError("标注版本已更新，请刷新后重试")
    manual = _safe_json_object(row["manual_json"])
    for key, value in clean.items():
        if value is None:
            manual.pop(key, None)
        else:
            manual[key] = value
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cursor = con.execute(
        """
        UPDATE face_visual_label
        SET manual_json=?, reviewed=?, version=version+1, updated_at=?
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
          AND model=? AND version=?
        """,
        (
            json.dumps(manual, ensure_ascii=False, separators=(",", ":")),
            int(bool(manual)),
            updated_at,
            *scope,
            str(row["model"]),
            int(expected_version),
        ),
    )
    if cursor.rowcount != 1:
        con.rollback()
        raise ValueError("标注版本已更新，请刷新后重试")
    con.execute(
        """
        UPDATE face_visual_label
        SET manual_json=?, reviewed=?, version=version+1, updated_at=?
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
          AND model!=?
        """,
        (
            json.dumps(manual, ensure_ascii=False, separators=(",", ":")),
            int(bool(manual)),
            updated_at,
            *scope,
            str(row["model"]),
        ),
    )
    has_manual_usage, manual_usage = _manual_usage_hint(manual)
    model_rows = con.execute(
        """
        SELECT model,primary_emotion,description_cn FROM face_visual_label
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
        """,
        scope,
    ).fetchall()
    for model_row in model_rows:
        effective_primary = str(
            manual.get("primary_emotion", model_row["primary_emotion"] or "")
        )
        effective_usage = (
            manual_usage
            if has_manual_usage
            else str(model_row["description_cn"] or "")
        )
        effective_semantics = selection_semantics(
            effective_primary, effective_usage
        )
        con.execute(
            """
            UPDATE face_evidence
            SET label=?, label_cn=?
            WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
              AND source=?
            """,
            (
                effective_semantics,
                effective_semantics,
                *scope,
                f"vision:{model_row['model']}",
            ),
        )
    con.commit()
    refreshed = con.execute(
        """
        SELECT * FROM face_visual_label
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=? AND model=?
        """,
        (*scope, str(row["model"])),
    ).fetchone()
    return _visual_label_record(refreshed)


def make_contact_sheet(
    faces: Sequence[RenderedFace],
    output: str | Path,
    *,
    columns: int = 6,
    cell_size: int = 224,
) -> Path:
    """Create a review sheet with a stable face ID under each cropped head."""
    ordered = sorted(faces, key=lambda face: face.face_id)
    rows = (len(ordered) + columns - 1) // columns
    label_height = 30
    sheet = Image.new(
        "RGB",
        (columns * cell_size, rows * (cell_size + label_height)),
        (42, 42, 46),
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, face in enumerate(ordered):
        x = (index % columns) * cell_size
        y = (index // columns) * (cell_size + label_height)
        head = Image.open(face.head_path).convert("RGBA")
        head.thumbnail((cell_size, cell_size), Image.Resampling.LANCZOS)
        tile = Image.new("RGB", (cell_size, cell_size), (220, 220, 220))
        tile.paste(
            head.convert("RGB"),
            ((cell_size - head.width) // 2, (cell_size - head.height) // 2),
            head.getchannel("A"),
        )
        sheet.paste(tile, (x, y))
        draw.text((x + 8, y + cell_size + 7), face.face_id, fill="white", font=font)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, format="JPEG", quality=92)
    return destination
