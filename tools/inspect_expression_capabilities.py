# -*- coding: utf-8 -*-
"""Inspect a Spine bundle without modifying AA, SQLite, or source assets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from asset_validation import validate_spine  # noqa: E402
from spine_semantic_faces import extract_semantic_face_combinations  # noqa: E402


def inspection_report(result):
    """Return a JSON-safe summary that never treats atlas hints as AA evidence."""
    issues = [{"code": issue.code, "message": issue.message} for issue in result.issues]
    if not result.candidate:
        return {"ok": False, "issues": issues}
    metadata = result.candidate.metadata
    try:
        semantic_faces = extract_semantic_face_combinations(metadata["files"]["skel"])
        semantic_face_error = ""
    except ValueError as exc:
        semantic_faces = {}
        semantic_face_error = str(exc)
    mode = metadata.get("expression_mode", "opaque_custom")
    if mode == "semantic_modular":
        next_step = "已读到语义部件；需要在 AA 中记录实际 faceId 后，模型才可切换表情。"
    elif mode == "numbered_composite":
        next_step = "已读到编号候选；需要在 AA 中记录实际 faceId 后，模型才可切换表情。"
    else:
        next_step = "骨骼未提供可读差分标签；可使用默认立绘，不能自动猜测表情。"
    return {
        "ok": result.ok,
        "issues": issues,
        "identifier": result.candidate.aa_key,
        "source": str(result.candidate.source_path),
        "spine_signature": metadata.get("spine_signature", ""),
        "outfit_key": metadata.get("outfit_key", ""),
        "spine_version": metadata.get("spine_version"),
        "expression_mode": mode,
        "candidate_face_ids": metadata.get("faces", []),
        "verified_face_ids": [],
        "semantic_parts": metadata.get("expression_parts", []),
        "semantic_face_combinations": semantic_faces,
        "auto_annotated_face_ids": sorted(semantic_faces),
        "semantic_face_error": semantic_face_error,
        "next_step": next_step,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="只读检查 Spine 骨骼的差分能力")
    parser.add_argument("source", help="包含 .skel/.atlas/.png/-avatar.png 的目录")
    parser.add_argument("--identifier", required=True, help="准备登记到 AA 的角色 Identifier")
    args = parser.parse_args(argv)
    report = inspection_report(validate_spine(args.source, identifier=args.identifier))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
