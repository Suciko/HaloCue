"""Run one blind sample with the sealed V7 directing prompts.

This is an A/B harness, not a production prompt rollback.  It keeps the
current resource catalogue, protocol, validation, policy and compiler, while
replacing only the G1 directing prompt and the G2 directing-rule prefix with
the exact strings preserved in the sealed V7 requests.  The current resource
suffix is retained so both arms see the same legal assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


AA_ROOT = Path(__file__).resolve().parents[1]
V7_G1_REQUEST = (
    AA_ROOT / "output" / "sol-shared-v7-blind-balanced" / "main-p03"
    / "requests" / "g1-plan-25bd6f9c7aef89626dab.request.json"
)
V7_G2_REQUEST = (
    AA_ROOT / "output" / "sol-shared-v7-blind-balanced" / "main-p03"
    / "requests" / "g2-execution-a39a7d98509ce82109d3.request.json"
)
RESOURCE_MARKER = "========== 本章可用资源 =========="


def _load_static(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    static = str(value.get("static") or "")
    if not static:
        raise RuntimeError(f"sealed request has no static prompt: {path}")
    return static


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _v7_rule_prefix(static: str) -> str:
    index = static.find(RESOURCE_MARKER)
    if index < 0:
        raise RuntimeError("sealed V7 G2 prompt has no resource marker")
    return static[:index].rstrip()


def _current_resource_suffix(static: str) -> str:
    index = static.find(RESOURCE_MARKER)
    if index < 0:
        raise RuntimeError("current G2 prompt has no resource marker")
    return static[index:]


def _write_manifest(
    output_dir: Path, *, v7_g1: str, v7_g2: str, source: Path, cast: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "kind": "single_window_v7_prompt_ab_arm",
        "blind_generation": True,
        "model": "gpt-5.6-sol",
        "mode": "balanced",
        "prompt_override": {
            "g1": "exact static string from sealed V7 request",
            "g2": (
                "exact V7 directing-rule prefix plus current resource suffix; "
                "current protocol/validation/policy/compiler retained"
            ),
            "v7_g1_request": str(V7_G1_REQUEST),
            "v7_g2_request": str(V7_G2_REQUEST),
            "v7_g1_static_sha256": _sha256_text(v7_g1),
            "v7_g2_static_sha256": _sha256_text(v7_g2),
        },
        "inputs": {
            "dialogue": str(source.resolve()),
            "cast": str(cast.resolve()),
            "old_response_used": False,
            "old_aap_used": False,
            "official_material_used": False,
            "manual_annotation_used": False,
        },
    }
    (output_dir / "AB-MANIFEST.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--cast", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--round-version", default="V10-AB-V7PROMPT")
    parser.add_argument("--story-type", default="main", choices=("main", "event", "bond"))
    parser.add_argument("--output-stem", required=True)
    args = parser.parse_args(argv)

    sys.path.insert(0, str(AA_ROOT))
    v7_g1 = _load_static(V7_G1_REQUEST)
    v7_g2 = _load_static(V7_G2_REQUEST)
    v7_prefix = _v7_rule_prefix(v7_g2)

    import annotation_scene_planner as planner

    planner.PLANNER_SYSTEM_COMPACT = v7_g1
    planner.PLANNER_SYSTEM = v7_g1

    import annotate
    import annotation_agent

    current_build_static = annotate.build_static

    def build_v7_static(*build_args: Any, **build_kwargs: Any) -> str:
        current = current_build_static(*build_args, **build_kwargs)
        return v7_prefix + "\n\n" + _current_resource_suffix(current)

    def build_v7_repair_rules(
        issue_codes: Any = (), *, layout_mode: str = "pure_ai",
    ) -> str:
        del issue_codes, layout_mode
        return v7_prefix

    annotate.build_static = build_v7_static
    annotation_agent.build_repair_rules = build_v7_repair_rules

    from tools import run_blind_validation

    output_dir = args.output_dir.resolve()
    _write_manifest(
        output_dir, v7_g1=v7_g1, v7_g2=v7_g2,
        source=args.source, cast=args.cast,
    )
    return run_blind_validation.main([
        "--output-dir", str(output_dir),
        "--source", str(args.source.resolve()),
        "--cast", str(args.cast.resolve()),
        "--source-id", args.source_id,
        "--round-version", args.round_version,
        "--story-type", args.story_type,
        "--output-stem", args.output_stem,
        "--run-mode", "balanced",
        "--provider", "codex-sol-subagent",
        "--model", "gpt-5.6-sol",
    ])


if __name__ == "__main__":
    raise SystemExit(main())
