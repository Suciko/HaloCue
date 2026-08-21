"""Checkpointed, blind preflight validation with auditable model artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

AA_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AA_ROOT))

from tools.run_blind_validation import (
    BlindCheckpointProvider,
    ResponseNeeded,
    write_json,
)
import webui


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--provider", default="codex-sol-subagent")
    parser.add_argument("--model", default="gpt-5.6-sol")
    args = parser.parse_args()

    root = args.output_dir.resolve()
    for name in ("requests", "responses", "raw-ai"):
        (root / name).mkdir(parents=True, exist_ok=True)
    local_source = root / "input-dialogue.txt"
    source_bytes = args.source.resolve().read_bytes()
    if local_source.exists() and local_source.read_bytes() != source_bytes:
        raise RuntimeError(f"sealed preflight input differs: {local_source}")
    if not local_source.exists():
        local_source.write_bytes(source_bytes)

    database_paths = [Path(path).resolve() for path in webui.configured_asset_database_paths()]
    database_inputs = []
    for path in database_paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        database_inputs.append({
            "path": str(path),
            "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    write_json(root / "input-manifest.json", {
        "blind_scope": (
            "dialogue-only preflight; no official command stream, official staging analysis, "
            "manual annotations, old AAP, or old model response is provided to the model"
        ),
        "source": str(local_source),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "provider": args.provider,
        "model": args.model,
        "run_mode": "balanced",
        "database_paths": [str(path) for path in database_paths],
        "databases": database_inputs,
    })

    provider = BlindCheckpointProvider(
        root, provider_name=args.provider, model_name=args.model,
    )
    original_provider = webui.annotation_provider
    webui.annotation_provider = lambda _profile=None: provider
    try:
        result = webui._preflight_result(str(local_source), scope=args.scope)
    except ResponseNeeded as exc:
        print(json.dumps({
            "status": "response_needed",
            "request": str(exc.request_path),
            "response": str(exc.response_path),
        }, ensure_ascii=False))
        return 20
    finally:
        webui.annotation_provider = original_provider

    write_json(root / "preflight-result.json", result)
    write_json(root / "usage-chain.json", result.get("usage_chain") or [])
    status = {
        "status": "complete",
        "provider": args.provider,
        "model": args.model,
        "usage_chain": str(root / "usage-chain.json"),
        "ai_status": result.get("ai_status"),
        "usage_chain_status": result.get("usage_chain_status"),
        "database_paths": [str(path) for path in database_paths],
        "input_manifest": str(root / "input-manifest.json"),
    }
    write_json(root / "RUN-STATUS.json", status)
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
