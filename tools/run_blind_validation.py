from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping


AA_ROOT = Path(__file__).resolve().parents[1]
BLIND_LAYOUT_MODE = "pure_ai"

RUNTIME_FINGERPRINT_FILES = (
    "tools/run_blind_validation.py",
    "prompt.py",
    "annotation_scene_planner.py",
    "annotation_protocol.py",
    "annotation_agent.py",
    "annotate.py",
    "annotation_memory.py",
    "direction_quality.py",
    "director_policy.py",
    "director_state.py",
    "script2aap.py",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_runtime_fingerprint(root: Path = AA_ROOT) -> dict[str, Any]:
    files = {
        relative: sha256_bytes((root / relative).read_bytes())
        for relative in RUNTIME_FINGERPRINT_FILES
    }
    aggregate = sha256_bytes(
        json.dumps(files, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    return {"sha256": aggregate, "files": files}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


class ResponseNeeded(BaseException):
    def __init__(self, request_path: Path, response_path: Path):
        self.request_path = request_path
        self.response_path = response_path
        super().__init__(f"response needed: {response_path.name}")


class BlindCheckpointProvider:
    name = "codex-terra-subagent"
    model = "gpt-5.6-terra"
    supports_compact_annotation = True
    replay_checkpoint_outputs = True

    def __init__(
        self,
        root: Path,
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
        replay_checkpoint_outputs: bool = True,
    ) -> None:
        self.root = root
        self.name = str(provider_name or self.name)
        self.model = str(model_name or self.model)
        self.replay_checkpoint_outputs = bool(replay_checkpoint_outputs)
        self.cfg = {
            "provider": self.name,
            "model": self.model,
            "max_tokens": 128_000,
            "annotation_max_tokens": 128_000,
            "context_window_tokens": 1_050_000,
            "reasoning_mode": "balanced",
            "reasoning_wire_protocol": "",
        }
        self.calls = 0
        self.request_records: list[dict[str, Any]] = []
        self.reasoning_records: list[dict[str, Any]] = []

    @staticmethod
    def _stage(static: str, user: str) -> str:
        if "场景事件规划器" in static:
            return "g1-plan"
        if "轻量初审规划器" in static:
            return "preflight"
        if "G2_EXECUTION_REPAIR" in user:
            return "g2-repair"
        return "g2-execution"

    def _response_candidates(self, stem: str, primary: Path) -> list[Path]:
        """Return immutable response attempts in consumption order.

        The primary path is kept for the first attempt. Later repair attempts
        use ``.attempt-N.response.json`` so a failed response remains
        inspectable and is never overwritten.
        """
        alternates = sorted(
            (self.root / "responses").glob(f"{stem}.attempt-*.response.json"),
            key=lambda path: (
                int(path.name.split(".attempt-", 1)[1].split(".response.json", 1)[0])
                if ".attempt-" in path.name else -1,
                path.name,
            ),
        )
        return [primary, *alternates]

    def complete_json(
        self, static: str, volatile: str, user: str, schema: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        self.calls += 1
        stage = self._stage(static, user)
        schema_text = json.dumps(schema, ensure_ascii=False, sort_keys=True)
        request_fingerprint = sha256_bytes(
            "\x00".join((stage, static, volatile, user, schema_text)).encode("utf-8")
        )
        stem = f"{stage}-{request_fingerprint[:20]}"
        request_path = self.root / "requests" / f"{stem}.request.json"
        response_path = self.root / "responses" / f"{stem}.response.json"
        payload = {
            "stage": stage,
            "request_index": self.calls,
            "request_fingerprint": request_fingerprint,
            "provider": self.name,
            "model": self.model,
            "configured_max_tokens": self.cfg["annotation_max_tokens"],
            "static": static,
            "volatile": volatile,
            "user": user,
            "schema": schema,
            "hashes": {
                "static_sha256": sha256_bytes(static.encode("utf-8")),
                "volatile_sha256": sha256_bytes(volatile.encode("utf-8")),
                "user_sha256": sha256_bytes(user.encode("utf-8")),
                "schema_sha256": sha256_bytes(schema_text.encode("utf-8")),
            },
        }
        write_json(request_path, payload)
        self.request_records.append({
            "provider": self.name,
            "model": self.model,
            "stage": stage,
            "request_index": self.calls,
            "request_path": str(request_path),
            "request_fingerprint": request_fingerprint,
            **payload["hashes"],
        })
        response_candidates = self._response_candidates(stem, response_path)
        consumed_response_path = next(
            (candidate for candidate in reversed(response_candidates) if candidate.is_file()),
            None,
        )
        if consumed_response_path is None:
            write_json(self.root / "resume-needed.json", {
                "status": "response_needed",
                "stage": stage,
                "request_fingerprint": request_fingerprint,
                "request": str(request_path),
                "response": str(response_path),
            })
            raise ResponseNeeded(request_path, response_path)

        response_path = consumed_response_path
        response_bytes = response_path.read_bytes()
        response = json.loads(response_bytes.decode("utf-8"))
        prior = sorted((self.root / "raw-ai").glob(f"{stem}.attempt-*.raw.json"))
        raw_path = self.root / "raw-ai" / f"{stem}.attempt-{len(prior) + 1}.raw.json"
        write_json(raw_path, response)
        # Keep immutable provenance on the request record.  The checkpoint
        # stores this record on the attempt, allowing a later run to tell a
        # newly-arrived repair response from the response it already used.
        if self.request_records:
            self.request_records[-1].update({
                "response_path": str(response_path),
                "response_sha256": sha256_bytes(response_bytes),
                "raw_path": str(raw_path),
                "raw_attempt": len(prior) + 1,
            })
        return response

    def checkpoint_replay_mode(self, saved_output: Mapping[str, Any]) -> str:
        """Return the smallest replay needed for a persisted chunk.

        A response file is intentionally mutable between blind-test turns:
        the external subagent writes a repair response after the first run
        stopped.  Compare its current bytes with the hash recorded when that
        attempt was consumed.  Older checkpoints without metadata are left
        replayable; new runs will write the richer metadata going forward.
        """
        attempts = saved_output.get("model_attempts") or []
        for attempt in attempts:
            if not isinstance(attempt, Mapping) or attempt.get("phase") != "g2_repair":
                continue
            fingerprint = str(attempt.get("request_fingerprint") or "")
            consumed = str(attempt.get("response_sha256") or "")
            legacy = not fingerprint or not consumed
            if not fingerprint or not consumed:
                fingerprint, consumed = self._legacy_repair_identity(attempt)
            if not fingerprint or not consumed:
                continue
            primary = self.root / "responses" / (
                f"g2-repair-{fingerprint[:20]}.response.json"
            )
            response_paths = self._response_candidates(
                f"g2-repair-{fingerprint[:20]}", primary,
            )
            changed = False
            for response_path in response_paths:
                if not response_path.is_file():
                    continue
                if legacy:
                    try:
                        current = self._json_digest(response_path)
                    except (OSError, ValueError, json.JSONDecodeError):
                        current = sha256_bytes(response_path.read_bytes())
                else:
                    current = sha256_bytes(response_path.read_bytes())
                if current != consumed:
                    changed = True
            if changed:
                return "g2_repair"
        return "reuse"

    @staticmethod
    def _json_digest(path: Path) -> str:
        value = json.loads(path.read_text(encoding="utf-8"))
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256_bytes(encoded.encode("utf-8"))

    def _legacy_repair_identity(self, attempt: Mapping[str, Any]) -> tuple[str, str]:
        response = attempt.get("response")
        if not isinstance(response, Mapping):
            return "", ""
        encoded = json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        consumed = sha256_bytes(encoded.encode("utf-8"))
        for raw_path in sorted((self.root / "raw-ai").glob("g2-repair-*.attempt-*.raw.json")):
            try:
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if raw == response:
                return raw_path.name.split(".attempt-", 1)[0].removeprefix("g2-repair-"), consumed
        return "", ""

    def report(self) -> str:
        return f"{self.name}/{self.model} calls={self.calls}"


def copy_immutable(source: Path, target: Path) -> None:
    if target.exists():
        if source.read_bytes() != target.read_bytes():
            raise RuntimeError(f"sealed input differs: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def prepare_inputs(
    args: argparse.Namespace,
    runtime_fingerprint: Mapping[str, Any],
) -> tuple[Path, Path, list[dict[str, Any]]]:
    root = args.output_dir.resolve()
    for name in ("requests", "responses", "raw-ai", "checkpoints", "compiled"):
        (root / name).mkdir(parents=True, exist_ok=True)
    local_source = root / "input-dialogue.txt"
    local_cast = root / "cast.json"
    copy_immutable(args.source.resolve(), local_source)
    copy_immutable(args.cast.resolve(), local_cast)
    usage_chain: list[dict[str, Any]] = []
    local_usage_chain = None
    if args.usage_chain is not None:
        raw_usage_chain = json.loads(args.usage_chain.read_text(encoding="utf-8"))
        if not isinstance(raw_usage_chain, list):
            raise ValueError("usage chain must be a JSON array")
        usage_chain = [dict(item) for item in raw_usage_chain if isinstance(item, Mapping)]
        local_usage_chain = root / "usage-chain.json"
        copy_immutable(args.usage_chain.resolve(), local_usage_chain)
    inputs = []
    database_paths = [Path(path).resolve() for path in (args.databases or [])]
    if not database_paths:
        database_paths = [AA_ROOT / "aa_assets.db"]
    for path, role in (
        (local_source, "dialogue_only_source"),
        (local_cast, "cast"),
        (AA_ROOT / "aa_resources.json", "current_resource_index"),
    ):
        inputs.append({
            "role": role,
            "path": str(path),
            "size": path.stat().st_size,
            "sha256": sha256_bytes(path.read_bytes()),
        })
    if local_usage_chain is not None:
        inputs.append({
            "role": "current_preflight_usage_chain",
            "path": str(local_usage_chain),
            "size": local_usage_chain.stat().st_size,
            "sha256": sha256_bytes(local_usage_chain.read_bytes()),
        })
    for index, path in enumerate(database_paths):
        if not path.is_file():
            raise FileNotFoundError(path)
        inputs.append({
            "role": "current_asset_database" if index == 0 else "asset_database_overlay",
            "path": str(path),
            "size": path.stat().st_size,
            "sha256": sha256_bytes(path.read_bytes()),
        })
    write_json(root / "input-manifest.json", {
        "blind_scope": (
            "dialogue-only input; no official command stream, official staging analysis, "
            "manual annotations, old AAP, or old model response is provided to the model"
        ),
        "source_id": args.source_id,
        "round_version": args.round_version,
        "story_type": args.story_type,
        "run_mode": args.run_mode,
        "provider": args.provider,
        "model": args.model,
        "model_output_limit": {
            "configured_annotation_max_tokens": 128_000,
            "override_used": False,
            "hard_character_budget_used": False,
        },
        "scene_event_planning": True,
        "official_face_context": False,
        "database_paths": [str(path) for path in database_paths],
        "runtime_fingerprint": dict(runtime_fingerprint),
        "inputs": inputs,
    })
    return local_source, local_cast, usage_chain


def compile_result(root: Path, output_stem: str, cast_path: Path) -> dict[str, Any]:
    import script2aap

    script2aap.HERE = str(root)
    return script2aap.compile_script({
        "script": str(root / f"{output_stem}.annotated.txt"),
        "trace": str(root / f"{output_stem}.annotated.txt.trace.json"),
        "out": output_stem,
        "cast": str(cast_path),
        "index": str(AA_ROOT / "aa_resources.json"),
        "install": False,
        "layout_mode": BLIND_LAYOUT_MODE,
    })


def build_run_status(
    result: Mapping[str, Any], compiled: Mapping[str, Any]
) -> dict[str, Any]:
    agent = result.get("agent") or {}
    needs_review = bool(
        isinstance(agent, Mapping) and agent.get("needs_review")
    )
    return {
        "status": "needs_review" if needs_review else "complete",
        "needs_review": needs_review,
        "annotated": result.get("out"),
        "model_audit": result.get("model_audit"),
        "aap_file": compiled.get("aap_file"),
        "quality": compiled.get("quality"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--cast", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--round-version", required=True)
    parser.add_argument("--story-type", choices=("main", "event", "bond"), required=True)
    parser.add_argument("--output-stem", required=True)
    parser.add_argument(
        "--usage-chain", type=Path,
        help="当前 preflight 生成并已校验的 usage-chain JSON",
    )
    parser.add_argument("--run-mode", default="balanced")
    parser.add_argument("--provider", default=BlindCheckpointProvider.name)
    parser.add_argument("--model", default=BlindCheckpointProvider.model)
    parser.add_argument(
        "--database", dest="databases", action="append", default=None,
        help="显式追加只读素材标注数据库；可重复传入",
    )
    parser.add_argument(
        "--refresh-responses", action="store_true",
        help="revalidate persisted responses instead of replaying completed chunk outputs",
    )
    args = parser.parse_args(argv)

    root = args.output_dir.resolve()
    runtime_fingerprint = build_runtime_fingerprint()
    source_path, cast_path, usage_chain = prepare_inputs(args, runtime_fingerprint)
    sys.path.insert(0, str(AA_ROOT))
    import annotate

    provider = BlindCheckpointProvider(
        root,
        provider_name=args.provider,
        model_name=args.model,
        replay_checkpoint_outputs=not args.refresh_responses,
    )
    try:
        result = annotate.annotate_script({
            "script": str(source_path),
            "out": str(root / f"{args.output_stem}.annotated.txt"),
            "cast": str(cast_path),
            "index": str(AA_ROOT / "aa_resources.json"),
            "llm": str(AA_ROOT / "llm.json"),
            "agent_enabled": True,
            "checkpoint_dir": str(root / "checkpoints"),
            "story_type": args.story_type,
            "scene_event_planning": True,
            "include_official_face_context": False,
            "layout_mode": BLIND_LAYOUT_MODE,
            "source_context_strategy": "window",
            "run_mode": args.run_mode,
            "source_id": args.source_id,
            "runtime_fingerprint_sha256": runtime_fingerprint["sha256"],
            "database_paths": list(args.databases or []),
            "usage_chain": usage_chain,
        }, provider_instance=provider)
    except ResponseNeeded as exc:
        print(json.dumps({
            "status": "response_needed",
            "request": str(exc.request_path),
            "response": str(exc.response_path),
        }, ensure_ascii=False))
        return 20

    total_targets = int((result.get("agent") or {}).get("total_targets") or 0)
    if total_targets <= 0:
        failure = {
            "status": "invalid_input_format",
            "reason": "blind validation parsed zero dialogue targets",
            "source": str(source_path),
            "annotated": result.get("out"),
            "model_invoked": False,
        }
        write_json(root / "RUN-STATUS.json", failure)
        print(json.dumps(failure, ensure_ascii=False, default=str))
        return 21

    write_json(root / "annotate-result.json", result)
    compiled = compile_result(root, args.output_stem, cast_path)
    write_json(root / "compile-result.json", compiled)
    marker = root / "resume-needed.json"
    if marker.exists():
        marker.unlink()
    run_status = build_run_status(result, compiled)
    write_json(root / "RUN-STATUS.json", run_status)
    print(json.dumps(run_status, ensure_ascii=False, default=str))
    return 22 if run_status["needs_review"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
