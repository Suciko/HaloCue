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

from face_semantics import CONTROLLED_BEAT_FIT


HERE = Path(__file__).resolve().parent
EMOTION_FAMILIES = {
    "neutral", "joy", "surprise_fear", "embarrassment",
    "irritation_anger", "sadness_hurt", "confusion_resignation",
}
EXPRESSION_CLASSES = {"base", "accent", "peak", "special"}
HOLD_POLICIES = {"hold", "short", "flash"}


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


def _semantic_errors(row: sqlite3.Row) -> list[str]:
    errors = []
    if not str(row["primary_emotion"] or "").strip():
        errors.append("missing_primary_emotion")
    if not str(row["description_cn"] or "").strip():
        errors.append("missing_usage_hint_cn")
    confidence = row["confidence"]
    if confidence is None or not math.isfinite(float(confidence)) or not 0 <= float(confidence) <= 1:
        errors.append("invalid_confidence")
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
    rows = con.execute(
        """
        SELECT ident,spine_signature,outfit_key,face_id,primary_emotion,
               confidence,description_cn,semantic_json,head_path
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
    for row in rows:
        key = (
            str(row["ident"]), str(row["spine_signature"]),
            str(row["outfit_key"]), str(row["face_id"]),
        )
        for error in _semantic_errors(row):
            invalid.append({"key": list(key), "error": error})

    source_totals = Counter()
    source_complete = Counter()
    complete_targets = 0
    for target, keys in target_keys:
        source = str(target.get("source_kind") or "unknown")
        source_totals[source] += 1
        if keys.issubset(actual):
            complete_targets += 1
            source_complete[source] += 1
    ready = not missing and not unexpected and not invalid
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
        "missing_rows_sample": [list(item) for item in sorted(missing)[:200]],
        "unexpected_rows_sample": [list(item) for item in sorted(unexpected)[:200]],
        "invalid_rows_sample": invalid[:200],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a Spine face label version")
    parser.add_argument("--plan", default=str(HERE / "out" / "spine-face-batch" / "plan.json"))
    parser.add_argument("--db", default=str(HERE / "aa_assets.db"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", default=str(HERE / "out" / "spine-face-label-audit.json"))
    args = parser.parse_args(argv)
    report = audit(args.plan, args.db, args.model)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        key: report[key] for key in (
            "status", "physical_target_count", "physical_face_count",
            "identity_binding_count", "expected_identity_face_rows",
            "actual_model_rows", "complete_target_count", "missing_row_count",
            "unexpected_row_count", "invalid_row_count",
        )
    }, ensure_ascii=False, indent=2))
    print(f"report: {output.resolve()}")
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
