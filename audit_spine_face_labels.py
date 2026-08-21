# -*- coding: utf-8 -*-
"""Audit one visual-label version against the immutable Spine batch plan."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from face_semantics import (
    CONTROLLED_BEAT_FIT, CONTROLLED_DELIVERY_FIT,
    CONTROLLED_USAGE_FREQUENCY,
)
from face_label_backend import (
    VISUAL_FACT_ENUMS,
    VISUAL_FACT_FIELDS,
    is_persona_face_blocked,
    resolve_backend_label,
)
from spine_face_labeler import VISION_SCHEMA, _valid_vision_item


HERE = Path(__file__).resolve().parent
EMOTION_FAMILIES = {
    "neutral", "joy", "surprise_fear", "embarrassment",
    "irritation_anger", "sadness_hurt", "confusion_resignation",
}
EXPRESSION_CLASSES = {"base", "accent", "peak", "special"}
HOLD_POLICIES = {"hold", "short", "flash"}
UNUSABLE_PRIMARY_EMOTIONS = {
    "无法识别", "不可识别", "无法判断", "unknown", "unrecognized",
}
SEMANTIC_PROFILE_SUFFIXES = (":semantic-profile-v3", ":semantic-profile-v4")


def _binding_rows(target: dict) -> list[dict]:
    bindings = target.get("identity_bindings") or []
    if bindings:
        return [item for item in bindings if isinstance(item, dict)]
    return [{
        "identifier": target.get("identifier", ""),
        "outfit_key": target.get("outfit_key", ""),
        "spine_signature": target.get("spine_signature", ""),
        "identity_status": target.get("identity_status", "mapped"),
    }]


def _row_key(binding: dict, face_id: str) -> tuple[str, str, str, str]:
    return (
        str(binding.get("identifier") or ""),
        str(binding.get("spine_signature") or ""),
        str(binding.get("outfit_key") or ""),
        str(face_id),
    )


def _json_object(value: object) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _vision_candidate(row: sqlite3.Row) -> dict:
    return {
        **_json_object(row["semantic_json"]),
        "face_id": str(row["face_id"] or ""),
        "primary_emotion": str(row["primary_emotion"] or ""),
        "usage_hint_cn": str(row["description_cn"] or ""),
        "eyes": str(row["eyes"] or ""),
        "brows": str(row["brows"] or ""),
        "mouth": str(row["mouth"] or ""),
        "blush": bool(row["blush"]),
        "tears": bool(row["tears"]),
        "confidence": float(row["confidence"] or 0.0),
        "visual_facts": _json_object(row["observation_json"]),
    }


def _required_vision_fields(*, require_semantic_modes: bool) -> set[str]:
    required = set(VISION_SCHEMA["properties"]["items"]["items"]["required"])
    required.update({
        "visual_facts", "emotion_family", "intensity", "expression_class",
        "beat_fit", "hold_policy", "delivery_fit", "usage_frequency",
        "semantic_confidence", "semantic_tags", "avoid_when_cn",
    })
    if require_semantic_modes:
        required.add("semantic_modes")
    return required


def _semantic_errors(
    row: sqlite3.Row, *, require_two_stage: bool = False,
    require_semantic_profile: bool = False,
) -> list[str]:
    errors = []
    primary_emotion = str(row["primary_emotion"] or "").strip()
    if not primary_emotion:
        errors.append("missing_primary_emotion")
    if not str(row["description_cn"] or "").strip():
        errors.append("missing_usage_hint_cn")
    confidence = row["confidence"]
    if confidence is None or not math.isfinite(float(confidence)) or not 0 <= float(confidence) <= 1:
        errors.append("invalid_confidence")
    elif (
        float(confidence) == 0
        or primary_emotion.casefold() in UNUSABLE_PRIMARY_EMOTIONS
    ):
        errors.append("unusable_visual_label")
    try:
        semantic = json.loads(row["semantic_json"] or "{}")
    except (TypeError, ValueError):
        return [*errors, "invalid_semantic_json"]
    if not isinstance(semantic, dict):
        return [*errors, "invalid_semantic_json"]
    family = semantic.get("emotion_family")
    if family is not None and family not in EMOTION_FAMILIES:
        errors.append("invalid_emotion_family")
    expression_class = semantic.get("expression_class")
    if expression_class is not None and expression_class not in EXPRESSION_CLASSES:
        errors.append("invalid_expression_class")
    hold = semantic.get("hold_policy")
    if hold is not None and hold not in HOLD_POLICIES:
        errors.append("invalid_hold_policy")
    beat_fit = semantic.get("beat_fit") or []
    if not isinstance(beat_fit, list) or any(item not in CONTROLLED_BEAT_FIT for item in beat_fit):
        errors.append("invalid_beat_fit")
    if require_semantic_profile:
        if family not in EMOTION_FAMILIES:
            errors.append("missing_emotion_family")
        intensity = semantic.get("intensity")
        if isinstance(intensity, bool) or not isinstance(intensity, int) or not 0 <= intensity <= 3:
            errors.append("invalid_intensity")
        if expression_class not in EXPRESSION_CLASSES:
            errors.append("missing_expression_class")
        if hold not in HOLD_POLICIES:
            errors.append("missing_hold_policy")
        delivery_fit = semantic.get("delivery_fit")
        if (
            not isinstance(delivery_fit, list) or not delivery_fit
            or any(item not in CONTROLLED_DELIVERY_FIT for item in delivery_fit)
        ):
            errors.append("invalid_delivery_fit")
        if semantic.get("usage_frequency") not in CONTROLLED_USAGE_FREQUENCY:
            errors.append("invalid_usage_frequency")
        semantic_confidence = semantic.get("semantic_confidence")
        if (
            isinstance(semantic_confidence, bool)
            or not isinstance(semantic_confidence, (int, float))
            or not math.isfinite(float(semantic_confidence))
            or not 0 <= float(semantic_confidence) <= 1
        ):
            errors.append("invalid_semantic_confidence")
    if require_two_stage:
        try:
            observation = json.loads(row["observation_json"] or "{}")
        except (TypeError, ValueError):
            observation = None
        if not isinstance(observation, dict):
            errors.append("invalid_observation_json")
        else:
            missing_facts = set(VISUAL_FACT_FIELDS) - set(observation)
            if missing_facts:
                errors.append("incomplete_visual_facts")
            elif any(
                observation.get(field) not in values
                for field, values in VISUAL_FACT_ENUMS.items()
            ):
                errors.append("invalid_visual_fact_enum")
        try:
            backend = json.loads(row["backend_json"] or "{}")
        except (TypeError, ValueError):
            backend = None
        if not isinstance(backend, dict) or not backend.get("pipeline"):
            errors.append("invalid_backend_resolution")
        elif require_semantic_profile and not str(backend.get("pipeline") or "").endswith(("v3", "v4")):
            errors.append("stale_backend_pipeline")
        elif backend.get("review_required"):
            errors.append("backend_review_required")
    head_path = Path(str(row["head_path"] or ""))
    if not head_path.is_file():
        errors.append("missing_head_preview")
    return errors


def audit(plan_path: str | Path, db_path: str | Path, model: str) -> dict:
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    targets = [item for item in plan.get("targets") or [] if isinstance(item, dict)]
    expected = set()
    target_keys = []
    binding_status = Counter()
    for target in targets:
        keys = set()
        for binding in _binding_rows(target):
            binding_status[str(binding.get("identity_status") or "mapped")] += 1
            for face_id in target.get("face_ids") or []:
                key = _row_key(binding, str(face_id))
                expected.add(key)
                keys.add(key)
        target_keys.append((target, keys))

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    columns = {
        str(row[1]) for row in con.execute("PRAGMA table_info(face_visual_label)")
    }
    observation_column = (
        "observation_json" if "observation_json" in columns
        else "'{}' AS observation_json"
    )
    backend_column = (
        "backend_json" if "backend_json" in columns
        else "'{}' AS backend_json"
    )
    def optional_column(name: str, fallback: str) -> str:
        return name if name in columns else f"{fallback} AS {name}"

    rows = con.execute(
        f"""
        SELECT ident,spine_signature,outfit_key,face_id,primary_emotion,
               confidence,description_cn,semantic_json,head_path,
               {optional_column('eyes', "''")},
               {optional_column('brows', "''")},
               {optional_column('mouth', "''")},
               {optional_column('blush', '0')},
               {optional_column('tears', '0')},
               {observation_column},{backend_column}
        FROM face_visual_label WHERE model=?
        """,
        (str(model),),
    ).fetchall()
    con.close()
    actual = {
        (str(row["ident"]), str(row["spine_signature"]),
         str(row["outfit_key"]), str(row["face_id"]))
        for row in rows
    }
    missing = expected - actual
    unexpected = actual - expected
    invalid = []
    vision_item_invalid = []
    expected_persona_blocks = []
    unexpected_backend_blocks = []
    strict_profile = str(model).endswith(SEMANTIC_PROFILE_SUFFIXES)
    required_vision_fields = _required_vision_fields(
        require_semantic_modes=str(model).endswith(":semantic-profile-v4")
    )
    for row in rows:
        key = (
            str(row["ident"]), str(row["spine_signature"]),
            str(row["outfit_key"]), str(row["face_id"]),
        )
        for error in _semantic_errors(
            row,
            require_two_stage=(
                str(model).endswith(":observation-backend-v2")
                or str(model).endswith(SEMANTIC_PROFILE_SUFFIXES)
            ),
            require_semantic_profile=str(model).endswith(SEMANTIC_PROFILE_SUFFIXES),
        ):
            invalid.append({"key": list(key), "error": error})
        if strict_profile:
            candidate = _vision_candidate(row)
            if not _valid_vision_item(candidate, required_vision_fields):
                vision_item_invalid.append(list(key))
            stored_backend = _json_object(row["backend_json"])
            resolved = resolve_backend_label(
                candidate,
                official_profile=stored_backend.get("official_evidence") or {},
                ident=str(row["ident"] or ""),
                face_id=str(row["face_id"] or ""),
            )
            hard_blocks = list(resolved.get("hard_blocks") or [])
            if hard_blocks:
                detail = {"key": list(key), "hard_blocks": hard_blocks}
                if (
                    set(hard_blocks) == {"persona_scope_blocked"}
                    and is_persona_face_blocked(row["ident"], row["face_id"])
                ):
                    expected_persona_blocks.append(detail)
                else:
                    unexpected_backend_blocks.append(detail)
    invalid_error_counts = Counter(item["error"] for item in invalid)
    invalid_keys = {tuple(item["key"]) for item in invalid}

    source_totals = Counter()
    source_complete = Counter()
    complete_targets = 0
    for target, keys in target_keys:
        source = str(target.get("source_kind") or "unknown")
        source_totals[source] += 1
        if keys.issubset(actual):
            complete_targets += 1
            source_complete[source] += 1
    ready = (
        not missing
        and not unexpected
        and not invalid
        and not vision_item_invalid
        and not unexpected_backend_blocks
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready" if ready else "incomplete",
        "model": str(model),
        "plan": str(Path(plan_path).resolve()),
        "database": str(Path(db_path).resolve()),
        "physical_target_count": len(targets),
        "physical_face_count": sum(len(item.get("face_ids") or []) for item in targets),
        "identity_binding_count": sum(binding_status.values()),
        "identity_binding_status": dict(sorted(binding_status.items())),
        "expected_identity_face_rows": len(expected),
        "actual_model_rows": len(actual),
        "complete_target_count": complete_targets,
        "missing_target_count": len(targets) - complete_targets,
        "source_completion": {
            source: {"complete": source_complete[source], "total": total}
            for source, total in sorted(source_totals.items())
        },
        "missing_row_count": len(missing),
        "unexpected_row_count": len(unexpected),
        "invalid_row_count": len(invalid),
        "invalid_key_count": len(invalid_keys),
        "invalid_error_counts": dict(sorted(invalid_error_counts.items())),
        "vision_item_invalid_count": len(vision_item_invalid),
        "expected_persona_block_count": len(expected_persona_blocks),
        "unexpected_backend_hard_block_count": len(unexpected_backend_blocks),
        "missing_rows_sample": [list(item) for item in sorted(missing)[:200]],
        "unexpected_rows_sample": [list(item) for item in sorted(unexpected)[:200]],
        "invalid_rows_sample": invalid[:200],
        "vision_item_invalid_sample": vision_item_invalid[:200],
        "expected_persona_blocks_sample": expected_persona_blocks[:200],
        "unexpected_backend_hard_blocks_sample": unexpected_backend_blocks[:200],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a Spine face label version")
    parser.add_argument("--plan", default=str(HERE / "out" / "spine-face-batch" / "plan.json"))
    parser.add_argument("--db", default=str(HERE / "aa_assets.db"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", default=str(HERE / "out" / "spine-face-label-audit.json"))
    parser.add_argument(
        "--pending-output",
        help="Write the captured missing identity/face rows as an explicit pending list",
    )
    parser.add_argument(
        "--pending-reason",
        default="visual label is unavailable; keep pending rather than guessing face semantics",
    )
    args = parser.parse_args(argv)
    report = audit(args.plan, args.db, args.model)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.pending_output:
        pending = {
            "generated_at": report["generated_at"],
            "model": report["model"],
            "status": "pending",
            "reason": str(args.pending_reason),
            "items_sample": [
                {
                    "identifier": item[0],
                    "spine_signature": item[1],
                    "outfit_key": item[2],
                    "face_id": item[3],
                }
                for item in report["missing_rows_sample"]
            ],
            "truncated": report["missing_row_count"] > len(report["missing_rows_sample"]),
        }
        pending_path = Path(args.pending_output)
        pending_path.parent.mkdir(parents=True, exist_ok=True)
        pending_path.write_text(
            json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps({
        key: report[key] for key in (
            "status", "physical_target_count", "physical_face_count",
            "identity_binding_count", "expected_identity_face_rows",
            "actual_model_rows", "complete_target_count", "missing_row_count",
            "unexpected_row_count", "invalid_row_count",
            "vision_item_invalid_count", "expected_persona_block_count",
            "unexpected_backend_hard_block_count",
        )
    }, ensure_ascii=False, indent=2))
    print(f"report: {output.resolve()}")
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
