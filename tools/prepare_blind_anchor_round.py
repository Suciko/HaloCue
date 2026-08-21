"""Seal blind Stage A dialogue windows and create sequential validation jobs."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


HEAD_RE = re.compile(r"^[^:：]{1,40}?\s*[:：]\s*.*$")
VALID_STORY_TYPES = {"main", "event", "bond"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def required_text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field} must be non-empty")
    return result


def write_immutable(path: Path, data: bytes) -> None:
    if path.exists():
        if not path.is_file() or path.read_bytes() != data:
            raise ValueError(f"sealed artifact differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def dialogue_layout(text: str) -> tuple[list[str], list[int], list[str]]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    dialogue_lines = [
        index for index, line in enumerate(lines)
        if line.strip() and not line.lstrip().startswith("#") and HEAD_RE.match(line)
    ]
    if not dialogue_lines:
        raise ValueError("source contains no dialogue lines")
    header = [line for line in lines[:dialogue_lines[0]] if line.strip()]
    return lines, dialogue_lines, header


def extract_window(text: str, start: int, end: int) -> tuple[str, int]:
    lines, dialogue_lines, header = dialogue_layout(text)
    if start < 1 or end < start or end > len(dialogue_lines):
        raise ValueError(
            f"invalid dialogue range {start}-{end}; source has {len(dialogue_lines)} dialogue lines"
        )
    first_line = dialogue_lines[start - 1]
    last_line = dialogue_lines[end - 1]
    selected = header + lines[first_line:last_line + 1]
    return "\n".join(selected).rstrip() + "\n", len(dialogue_lines)


def load_spec(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("anchor spec must be a JSON object")
    return dict(payload)


def prepare_round(spec_path: Path, output_root: Path) -> dict[str, Any]:
    spec_path = spec_path.resolve()
    output_root = output_root.resolve()
    spec = load_spec(spec_path)
    campaign_id = required_text(spec.get("campaign_id"), "campaign_id")
    round_version = required_text(spec.get("round_version"), "round_version")
    selection_basis = required_text(spec.get("selection_basis"), "selection_basis")
    run_mode = required_text(spec.get("run_mode") or "balanced", "run_mode")
    provider = required_text(
        spec.get("provider") or "codex-sol-subagent", "provider"
    )
    model = required_text(spec.get("model") or "gpt-5.6-sol", "model")
    scenes = spec.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != 3:
        raise ValueError("Stage A anchor spec must contain exactly three scenes")

    jobs: list[dict[str, Any]] = []
    manifest_scenes: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for scene_index, raw_scene in enumerate(scenes):
        if not isinstance(raw_scene, Mapping):
            raise ValueError(f"scene {scene_index} must be an object")
        source_id = required_text(raw_scene.get("source_id"), "source_id")
        if source_id in seen_sources:
            raise ValueError(f"duplicate source_id: {source_id}")
        seen_sources.add(source_id)
        scene_name = required_text(raw_scene.get("directory") or source_id, "directory")
        story_type = required_text(raw_scene.get("story_type"), "story_type")
        if story_type not in VALID_STORY_TYPES:
            raise ValueError(f"invalid story_type for {source_id}: {story_type}")
        source_path = Path(required_text(raw_scene.get("source"), "source")).resolve()
        cast_path = Path(required_text(raw_scene.get("cast"), "cast")).resolve()
        source_bytes = source_path.read_bytes()
        cast_bytes = cast_path.read_bytes()
        source_text = source_bytes.decode("utf-8-sig")
        anchors = raw_scene.get("anchors")
        if not isinstance(anchors, list) or not 3 <= len(anchors) <= 4:
            raise ValueError(f"{source_id} must contain 3 or 4 anchors")
        output_prefix = required_text(
            raw_scene.get("output_stem_prefix") or source_id,
            "output_stem_prefix",
        )
        manifest_anchors = []
        seen_anchors: set[str] = set()
        for anchor_index, raw_anchor in enumerate(anchors):
            if not isinstance(raw_anchor, Mapping):
                raise ValueError(f"anchor {source_id}[{anchor_index}] must be an object")
            anchor_id = required_text(raw_anchor.get("anchor_id"), "anchor_id")
            if anchor_id in seen_anchors:
                raise ValueError(f"duplicate anchor_id in {source_id}: {anchor_id}")
            seen_anchors.add(anchor_id)
            category = required_text(raw_anchor.get("category"), "category")
            rationale = required_text(raw_anchor.get("rationale"), "rationale")
            start = int(raw_anchor.get("start_dialogue") or 0)
            end = int(raw_anchor.get("end_dialogue") or 0)
            window, total_dialogue = extract_window(source_text, start, end)
            sealed_dir = output_root / "stage-a" / "sealed-inputs" / scene_name / anchor_id
            sealed_source = sealed_dir / "dialogue.txt"
            sealed_cast = sealed_dir / "cast.json"
            write_immutable(sealed_source, window.encode("utf-8"))
            write_immutable(sealed_cast, cast_bytes)
            job_dir = output_root / "stage-a" / "candidate" / scene_name / anchor_id
            job = {
                "name": f"{source_id}-{anchor_id}",
                "output_dir": str(job_dir),
                "source": str(sealed_source),
                "cast": str(sealed_cast),
                "source_id": f"{source_id}#{anchor_id}",
                "round_version": round_version,
                "story_type": story_type,
                "output_stem": f"{output_prefix}-{anchor_id}",
                "run_mode": run_mode,
                "provider": provider,
                "model": model,
            }
            jobs.append(job)
            manifest_anchors.append({
                "anchor_id": anchor_id,
                "category": category,
                "rationale": rationale,
                "dialogue_range": [start, end],
                "dialogue_count": end - start + 1,
                "source_dialogue_count": total_dialogue,
                "sealed_source": str(sealed_source.relative_to(output_root)),
                "sealed_source_sha256": sha256_bytes(window.encode("utf-8")),
                "output_dir": str(job_dir.relative_to(output_root)),
            })
        manifest_scenes.append({
            "source_id": source_id,
            "directory": scene_name,
            "story_type": story_type,
            "source_path": str(source_path),
            "source_sha256": sha256_bytes(source_bytes),
            "cast_path": str(cast_path),
            "cast_sha256": sha256_bytes(cast_bytes),
            "anchors": manifest_anchors,
        })

    jobs_payload = {"execution_mode": "sequential", "jobs": jobs}
    manifest = {
        "campaign_id": campaign_id,
        "round_version": round_version,
        "stage": "A",
        "variant": "candidate",
        "status": "inputs_sealed",
        "selection_basis": selection_basis,
        "blind_scope": (
            "frozen dialogue windows and cast only; no official commands, official AAP, "
            "manual annotations, old AAP, old response, or posthoc answer is included"
        ),
        "run_mode": run_mode,
        "provider": provider,
        "model": model,
        "spec_path": str(spec_path),
        "spec_sha256": sha256_bytes(spec_path.read_bytes()),
        "execution_mode": "sequential",
        "jobs_file": "stage-a/jobs.json",
        "scenes": manifest_scenes,
    }
    write_immutable(output_root / "stage-a" / "jobs.json", canonical_bytes(jobs_payload))
    write_immutable(output_root / "ROUND-MANIFEST.json", canonical_bytes(manifest))
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seal three-scene Stage A anchor inputs and sequential jobs"
    )
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = prepare_round(args.spec, args.output_root)
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": manifest["status"],
        "campaign_id": manifest["campaign_id"],
        "round_version": manifest["round_version"],
        "jobs_file": str(args.output_root.resolve() / manifest["jobs_file"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
