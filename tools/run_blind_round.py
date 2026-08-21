"""Run isolated blind-validation jobs sequentially in declared order."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

AA_ROOT = Path(__file__).resolve().parents[1]
VALID_STORY_TYPES = {"main", "event", "bond"}


@dataclass(frozen=True)
class BlindJob:
    name: str
    output_dir: Path
    source: Path
    cast: Path
    source_id: str
    round_version: str
    story_type: str
    output_stem: str
    run_mode: str = "balanced"
    provider: str = "codex-sol-subagent"
    model: str = "gpt-5.6-sol"
    refresh_responses: bool = False
    database_paths: tuple[str, ...] = ()


def _text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"job field {field!r} must be non-empty")
    return result


def load_jobs(path: Path) -> list[BlindJob]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, Mapping):
        payload = payload.get("jobs")
    if not isinstance(payload, list) or not payload:
        raise ValueError("jobs file must contain a non-empty JSON array")
    jobs: list[BlindJob] = []
    names: set[str] = set()
    output_dirs: set[Path] = set()
    for index, raw in enumerate(payload):
        if not isinstance(raw, Mapping):
            raise ValueError(f"job {index} must be an object")
        name = _text(raw.get("name"), "name")
        output_dir = Path(_text(raw.get("output_dir"), "output_dir")).resolve()
        if name in names:
            raise ValueError(f"duplicate job name: {name}")
        if output_dir in output_dirs:
            raise ValueError(f"jobs must not share output_dir: {output_dir}")
        story_type = _text(raw.get("story_type"), "story_type")
        if story_type not in VALID_STORY_TYPES:
            raise ValueError(f"job {name} has invalid story_type: {story_type}")
        names.add(name)
        output_dirs.add(output_dir)
        jobs.append(BlindJob(
            name=name,
            output_dir=output_dir,
            source=Path(_text(raw.get("source"), "source")).resolve(),
            cast=Path(_text(raw.get("cast"), "cast")).resolve(),
            source_id=_text(raw.get("source_id"), "source_id"),
            round_version=_text(raw.get("round_version"), "round_version"),
            story_type=story_type,
            output_stem=_text(raw.get("output_stem"), "output_stem"),
            run_mode=str(raw.get("run_mode") or "balanced"),
            provider=str(raw.get("provider") or "codex-sol-subagent"),
            model=str(raw.get("model") or "gpt-5.6-sol"),
            refresh_responses=bool(raw.get("refresh_responses", False)),
            database_paths=tuple(
                str(item) for item in (raw.get("database_paths") or [])
                if str(item).strip()
            ),
        ))
    return jobs


def build_command(job: BlindJob, *, python_executable: str = sys.executable) -> list[str]:
    command = [python_executable, str(AA_ROOT / "tools" / "run_blind_validation.py"),
               "--output-dir", str(job.output_dir), "--source", str(job.source),
               "--cast", str(job.cast), "--source-id", job.source_id,
               "--round-version", job.round_version, "--story-type", job.story_type,
               "--output-stem", job.output_stem, "--run-mode", job.run_mode,
               "--provider", job.provider, "--model", job.model]
    if job.refresh_responses:
        command.append("--refresh-responses")
    for database_path in job.database_paths:
        command.extend(["--database", database_path])
    return command


def run_job(job: BlindJob) -> dict[str, Any]:
    started = time.time()
    child_env = dict(os.environ)
    child_env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(build_command(job), cwd=str(AA_ROOT), capture_output=True,
                               text=True, encoding="utf-8", errors="replace", check=False,
                               env=child_env)
    status = "failed"
    for line in reversed(completed.stdout.splitlines()):
        if not line.strip().startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, Mapping) and parsed.get("status"):
            status = str(parsed["status"])
            break
    return {"name": job.name, "output_dir": str(job.output_dir),
            "returncode": completed.returncode, "status": status,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": completed.stdout, "stderr": completed.stderr}


def run_round(jobs: Sequence[BlindJob], *, max_workers: int | None = None) -> dict[str, Any]:
    if not jobs:
        raise ValueError("at least one blind-validation job is required")
    if max_workers not in (None, 1):
        raise ValueError("blind-validation model requests must run sequentially")
    ordered = [run_job(job) for job in jobs]
    status = _summarize_status(item.get("status") for item in ordered)
    return {"status": status, "jobs": ordered, "execution_mode": "sequential",
            "max_duration_seconds": max(item["duration_seconds"] for item in ordered),
            "sum_duration_seconds": round(sum(item["duration_seconds"] for item in ordered), 3)}


def _response_ready(job: BlindJob) -> bool:
    """Return whether the exact response named by the current marker exists.

    A blind request is immutable.  An older response in the same directory is
    not evidence for a newer fingerprint, so the marker's exact path is the
    only response that may wake a replay.
    """
    marker = job.output_dir / "resume-needed.json"
    if not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if str(payload.get("status") or "") != "response_needed":
        return False
    response = str(payload.get("response") or "").strip()
    return bool(response) and Path(response).is_file()


def _aggregate_job_reports(reports: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    ordered = list(reports.values())
    status = _summarize_status(item.get("status") for item in ordered)
    durations = [float(item.get("duration_seconds") or 0.0) for item in ordered]
    return {
        "status": status,
        "jobs": ordered,
        "execution_mode": "sequential",
        "max_duration_seconds": round(max(durations, default=0.0), 3),
        "sum_duration_seconds": round(sum(durations), 3),
    }


def _summarize_status(statuses: Any) -> str:
    """Separate pending model work from completed-but-reviewable output.

    A quality review is terminal for that job, but must not prevent the
    watcher from replaying other jobs whose exact model response has arrived.
    """
    normalized = {str(status or "failed") for status in statuses}
    if "failed" in normalized:
        return "failed"
    if "response_needed" in normalized:
        return "response_needed"
    if "needs_review" in normalized:
        return "needs_review"
    return "complete" if normalized <= {"complete"} else "failed"


def watch_round(
    jobs: Sequence[BlindJob], *, poll_seconds: float = 30.0,
    max_wait_seconds: float = 36_000.0, max_workers: int | None = None,
    on_report: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Keep replaying a round until external response files arrive.

    The watcher never creates model responses.  It only reruns the existing
    checkpoint-aware sequential runner after a ``response_needed`` result, so
    a Sol sub-agent can populate request-specific response files asynchronously.
    """
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    if max_wait_seconds < 0:
        raise ValueError("max_wait_seconds must be non-negative")
    started = time.monotonic()
    report = run_round(jobs, max_workers=max_workers)
    if on_report:
        on_report(report)
    # Keep one authoritative result per declared job.  Replaying only jobs
    # whose exact response has arrived prevents unrelated missing responses
    # from generating new request fingerprints every polling interval.
    job_reports = {
        str(item.get("name") or ""): dict(item)
        for item in report.get("jobs") or []
        if str(item.get("name") or "")
    }
    # Tiny synthetic callers/tests may provide no per-job records. Preserve the
    # old polling behavior for that case; real blind rounds always have them.
    per_job_polling = bool(job_reports)
    while report["status"] == "response_needed":
        elapsed = time.monotonic() - started
        if elapsed >= max_wait_seconds:
            report = dict(report)
            report["watch_status"] = "timeout"
            report["watch_elapsed_seconds"] = round(elapsed, 3)
            if on_report:
                on_report(report)
            return report
        time.sleep(min(poll_seconds, max_wait_seconds - elapsed))
        if per_job_polling:
            ready_jobs = [job for job in jobs if _response_ready(job)]
            if not ready_jobs:
                continue
            ready_report = run_round(ready_jobs, max_workers=max_workers)
            for item in ready_report.get("jobs") or []:
                name = str(item.get("name") or "")
                if name:
                    job_reports[name] = dict(item)
            report = _aggregate_job_reports(job_reports)
        else:
            report = run_round(jobs, max_workers=max_workers)
        if on_report and report["status"] == "response_needed":
            on_report(report)
    report = dict(report)
    report["watch_status"] = "complete" if report["status"] in {"complete", "needs_review"} else "failed"
    report["watch_elapsed_seconds"] = round(time.monotonic() - started, 3)
    if on_report:
        on_report(report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run isolated blind-validation jobs sequentially")
    parser.add_argument("--jobs-file", type=Path, required=True)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument(
        "--max-workers", type=int, choices=(1,),
        help="compatibility option; blind model requests are always sequential",
    )
    parser.add_argument(
        "--watch", action="store_true",
        help="keep replaying response-needed jobs until responses arrive or the wait expires",
    )
    parser.add_argument(
        "--poll-seconds", type=float, default=30.0,
        help="seconds between checkpoint-aware replay attempts in watch mode",
    )
    parser.add_argument(
        "--max-wait-seconds", type=float, default=36_000.0,
        help="maximum watch duration; defaults to ten hours",
    )
    args = parser.parse_args(argv)
    try:
        jobs = load_jobs(args.jobs_file.resolve())
        status_path = args.status_file.resolve() if args.status_file else None

        def save_status(report: dict[str, Any]) -> None:
            if status_path:
                status_path.parent.mkdir(parents=True, exist_ok=True)
                status_path.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

        report = watch_round(
            jobs, poll_seconds=args.poll_seconds,
            max_wait_seconds=args.max_wait_seconds,
            max_workers=args.max_workers,
            on_report=save_status if args.watch else None,
        ) if args.watch else run_round(jobs, max_workers=args.max_workers)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.status_file and not args.watch:
        args.status_file.parent.mkdir(parents=True, exist_ok=True)
        args.status_file.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["status"] == "complete" else 20 if report["status"] == "response_needed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
