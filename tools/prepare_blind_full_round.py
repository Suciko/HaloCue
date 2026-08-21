"""Create an immutable three-scene full-round job manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_immutable(path: Path, value: Any) -> None:
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"immutable artifact differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def prepare(source_root: Path, output_root: Path, round_version: str = "V4") -> dict[str, Any]:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    specs = [
        ("main-p03", "main", "Main-P03-V4-Sol-Proactive-Full"),
        ("seia", "event", "CodeBOX-Seia-V4-Sol-Proactive-Full"),
        ("main-3-1-7", "main", "Main-3-1-7-V4-Sol-Proactive-Full"),
    ]
    jobs: list[dict[str, Any]] = []
    scenes: list[dict[str, Any]] = []
    for source_id, story_type, stem in specs:
        source = source_root / source_id / "input-dialogue.txt"
        cast = source_root / source_id / "cast.json"
        if not source.is_file() or not cast.is_file():
            raise FileNotFoundError(f"missing sealed source or cast for {source_id}")
        output_dir = output_root / source_id
        jobs.append({
            "name": source_id,
            "output_dir": str(output_dir),
            "source": str(source),
            "cast": str(cast),
            "source_id": source_id,
            "round_version": round_version,
            "story_type": story_type,
            "output_stem": stem,
            "run_mode": "balanced",
            "provider": "codex-sol-subagent",
            "model": "gpt-5.6-sol",
        })
        scenes.append({
            "source_id": source_id,
            "story_type": story_type,
            "source_path": str(source),
            "source_sha256": digest(source),
            "cast_path": str(cast),
            "cast_sha256": digest(cast),
            "output_dir": str(output_dir.relative_to(output_root)),
        })
    manifest = {
        "campaign_id": "proactive-v4-closeup-contract-20260820",
        "round_version": round_version,
        "stage": "B",
        "variant": "candidate",
        "status": "inputs_declared",
        "blind_scope": (
            "full dialogue and cast only; no official command stream, official AAP, "
            "manual annotation, old AAP, old response, or posthoc answer is included"
        ),
        "selection_basis": "full source dialogue and cast only",
        "execution_mode": "sequential",
        "run_mode": "balanced",
        "provider": "codex-sol-subagent",
        "model": "gpt-5.6-sol",
        "jobs_file": "jobs.json",
        "scenes": scenes,
    }
    write_immutable(output_root / "jobs.json", {"execution_mode": "sequential", "jobs": jobs})
    write_immutable(output_root / "ROUND-MANIFEST.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--round-version", default="V4")
    args = parser.parse_args()
    manifest = prepare(args.source_root, args.output_root, args.round_version)
    print(json.dumps({
        "status": manifest["status"],
        "stage": manifest["stage"],
        "round_version": manifest["round_version"],
        "jobs_file": str(args.output_root.resolve() / manifest["jobs_file"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
