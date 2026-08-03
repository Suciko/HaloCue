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
})


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


def selection_semantics(primary_emotion: str, usage_hint: str) -> str:
    """Combine the two fields the story model uses to choose a face."""
    emotion = str(primary_emotion or "").strip()
    hint = str(usage_hint or "").strip()
    if emotion and hint and emotion != hint:
        return f"{emotion}｜{hint}"
    return emotion or hint


def _compact_vision_item(item: Mapping) -> dict:
    compact = {
        "face_id": item.get("face_id"),
        "primary_emotion": item.get("primary_emotion"),
        "confidence": item.get("confidence"),
    }
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
    return math.isfinite(float(confidence)) and 0.0 <= float(confidence) <= 1.0


_SYSTEM = """你在为视觉小说角色立绘建立供剧情选择的表情语义表。
只判断整体情绪、态度和适用的台词语境，不拆解或描述脸部零件。
不要根据编号猜测，不要根据文件名猜测，也不要把服装、姿势或角色身份当成情绪。
同一批图片属于同一角色，重点比较它们之间的细微差别。
primary_emotion 使用简洁自然的中文，例如“轻微微笑”“不满”“尴尬”“惊讶”。
usage_hint_cn 写成一句简短的使用语境，例如适合怎样的台词、语气、反应或情绪阶段。
使用语境不是关键词触发规则，不得用是否脸红、是否流泪等视觉现象决定是否使用。
不同 face_id 可以拥有完全相同的情绪和使用语境，不要为了区分编号强行制造差异。
置信度范围为 0 到 1；确实模糊时降低置信度，不要硬猜。"""


def make_vision_sheet(
    faces: Sequence[RenderedFace],
    *,
    cell_size: int = 384,
    columns: int = 3,
) -> tuple[bytes, list[str]]:
    """Build one fixed 3x3 comparison sheet with readable face IDs."""
    if columns != 3:
        raise ValueError("vision sheets must use exactly three columns")
    if not 1 <= len(faces) <= 9:
        raise ValueError("vision sheets must contain between 1 and 9 faces")
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
    batch_size: int = 9,
    batch_workers: int = 2,
    confidence_threshold: float = 0.6,
    semantic_hints: dict[str, dict] | None = None,
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

    def request_batch(batch: Sequence[RenderedFace]) -> list[dict]:
        sheet, expected = make_vision_sheet(batch)
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
    face_by_id = {face.face_id: face for face in ordered}
    for index, record in enumerate(list(results)):
        face_id = str(record["face_id"])
        if record.get("failed") and face_id in initial_singletons:
            continue
        if (
            not record.get("failed")
            and float(record.get("confidence") or 0.0) >= confidence_threshold
        ):
            continue
        reviewed_record = request_batch([face_by_id[face_id]])[0]
        if record.get("failed") or not reviewed_record.get("failed"):
            results[index] = reviewed_record
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
    records = list(labels)
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
               confidence,description_cn,head_path,reviewed,manual_json,version,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                str(item.get("head_path") or ""),
                int(bool(manual)),
                json.dumps(manual, ensure_ascii=False, separators=(",", ":")),
                1,
                completed_at,
            ),
        )
        effective_primary = str(manual.get("primary_emotion", primary))
        effective_usage = usage_hint_cn(manual) or usage_hint_cn(item)
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
    manual = {
        key: value
        for key, value in _safe_json_object(row["manual_json"]).items()
        if key in _EDITABLE_FACE_FIELDS
    }
    manual_hint = usage_hint_cn(manual)
    if manual_hint:
        manual["usage_hint_cn"] = manual_hint
        manual["description_cn"] = manual_hint
    effective = {**ai, **manual}
    effective_hint = usage_hint_cn(effective)
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
    rows = con.execute(
        """
        SELECT * FROM face_visual_label
        WHERE ident=? AND spine_signature=? AND outfit_key=?
        ORDER BY face_id, updated_at DESC, confidence DESC, model
        """,
        (str(ident), str(spine_signature or ""), str(outfit_key or "")),
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
        elif key == "secondary_emotions":
            if not isinstance(value, list):
                raise ValueError("标注字段 secondary_emotions 必须是数组")
            clean[key] = [str(item).strip() for item in value if str(item).strip()]
        else:
            clean[key] = str(value).strip()
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
    effective_primary = str(
        manual.get("primary_emotion", row["primary_emotion"] or "")
    )
    effective_usage = usage_hint_cn(manual) or str(row["description_cn"] or "")
    effective_semantics = selection_semantics(
        effective_primary, effective_usage
    )
    con.execute(
        """
        UPDATE face_evidence
        SET label=?, label_cn=?
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
          AND source LIKE 'vision:%'
        """,
        (effective_semantics, effective_semantics, *scope),
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
