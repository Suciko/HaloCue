from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.run_blind_round import (
    BlindJob, _aggregate_job_reports, _response_ready, build_command, load_jobs, run_job,
    run_round, watch_round,
)


def _job(tmp_path: Path, name: str, output_name: str) -> dict[str, str]:
    return {
        "name": name,
        "output_dir": str(tmp_path / output_name),
        "source": str(tmp_path / f"{name}.txt"),
        "cast": str(tmp_path / "cast.json"),
        "source_id": name,
        "round_version": "V-test",
        "story_type": "main",
        "output_stem": f"{name}-out",
    }


def test_load_jobs_rejects_shared_output_directories(tmp_path: Path):
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps([
        _job(tmp_path, "p03", "same"),
        _job(tmp_path, "seia", "same"),
    ]), encoding="utf-8")
    with pytest.raises(ValueError, match="share output_dir"):
        load_jobs(path)


def test_build_command_keeps_round_identity_and_refresh_flag(tmp_path: Path):
    job = BlindJob(
        name="p03", output_dir=tmp_path / "p03", source=tmp_path / "p03.txt",
        cast=tmp_path / "cast.json", source_id="main-p03", round_version="V5",
        story_type="main", output_stem="Main-P03-V5-Sol-Blind",
        provider="codex-sol-subagent", model="gpt-5.6-sol", refresh_responses=True,
    )
    command = build_command(job, python_executable="python-test")
    assert command[0] == "python-test"
    assert command[command.index("--source-id") + 1] == "main-p03"
    assert command[command.index("--round-version") + 1] == "V5"
    assert command[command.index("--model") + 1] == "gpt-5.6-sol"
    assert command[-1] == "--refresh-responses"


def test_run_job_forces_utf8_child_output(monkeypatch, tmp_path: Path):
    job = BlindJob(
        name="seia", output_dir=tmp_path / "seia", source=tmp_path / "seia.txt",
        cast=tmp_path / "cast.json", source_id="codebox-seia", round_version="V5",
        story_type="event", output_stem="CodeBOX-Seia-V5-Sol-Blind",
    )
    captured = {}

    class Completed:
        returncode = 20
        stdout = '{"status":"response_needed"}\n'
        stderr = ""

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return Completed()

    monkeypatch.setattr("tools.run_blind_round.subprocess.run", fake_run)
    result = run_job(job)

    assert captured["encoding"] == "utf-8"
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
    assert result["status"] == "response_needed"


def test_run_round_executes_jobs_sequentially_and_continues_after_response_needed(
    monkeypatch, tmp_path: Path,
):
    jobs = [
        BlindJob(
            name=name, output_dir=tmp_path / name, source=tmp_path / f"{name}.txt",
            cast=tmp_path / "cast.json", source_id=name, round_version="V4",
            story_type="main", output_stem=name,
        )
        for name in ("first", "second", "third")
    ]
    calls = []

    def fake_run(job):
        calls.append(job.name)
        return {
            "name": job.name, "output_dir": str(job.output_dir), "returncode": 20,
            "status": "response_needed", "duration_seconds": 1.0,
            "stdout": "", "stderr": "",
        }

    monkeypatch.setattr("tools.run_blind_round.run_job", fake_run)
    report = run_round(jobs)

    assert calls == ["first", "second", "third"]
    assert report["execution_mode"] == "sequential"
    assert report["status"] == "response_needed"
    assert [item["name"] for item in report["jobs"]] == calls


def test_reviewable_job_does_not_block_pending_jobs(monkeypatch, tmp_path: Path):
    jobs = [
        BlindJob(
            name=name, output_dir=tmp_path / name, source=tmp_path / f"{name}.txt",
            cast=tmp_path / "cast.json", source_id=name, round_version="V4",
            story_type="main", output_stem=name,
        )
        for name in ("review", "pending", "done")
    ]

    outcomes = iter(("needs_review", "response_needed", "complete"))
    monkeypatch.setattr("tools.run_blind_round.run_job", lambda job: {
        "name": job.name, "output_dir": str(job.output_dir), "returncode": 0,
        "status": next(outcomes), "duration_seconds": 1.0, "stdout": "", "stderr": "",
    })

    report = run_round(jobs)

    assert report["status"] == "response_needed"
    assert _aggregate_job_reports({
        "review": {"name": "review", "status": "needs_review", "duration_seconds": 1},
        "done": {"name": "done", "status": "complete", "duration_seconds": 1},
    })["status"] == "needs_review"


def test_run_round_rejects_parallel_worker_count(tmp_path: Path):
    job = BlindJob(
        name="only", output_dir=tmp_path / "only", source=tmp_path / "only.txt",
        cast=tmp_path / "cast.json", source_id="only", round_version="V4",
        story_type="main", output_stem="only",
    )

    with pytest.raises(ValueError, match="sequentially"):
        run_round([job], max_workers=2)


def test_response_ready_requires_the_marker_exact_path(tmp_path: Path):
    job = BlindJob(
        name="only", output_dir=tmp_path / "only", source=tmp_path / "only.txt",
        cast=tmp_path / "cast.json", source_id="only", round_version="V4",
        story_type="main", output_stem="only",
    )
    job.output_dir.mkdir()
    marker = job.output_dir / "resume-needed.json"
    response = job.output_dir / "responses" / "g1-plan-new.response.json"
    marker.write_text(json.dumps({
        "status": "response_needed", "response": str(response),
    }), encoding="utf-8")
    (job.output_dir / "responses").mkdir()
    assert _response_ready(job) is False
    response.write_text("{}", encoding="utf-8")
    assert _response_ready(job) is True


def test_watch_round_replays_response_needed_until_complete(monkeypatch, tmp_path: Path):
    job = BlindJob(
        name="only", output_dir=tmp_path / "only", source=tmp_path / "only.txt",
        cast=tmp_path / "cast.json", source_id="only", round_version="V4",
        story_type="main", output_stem="only",
    )
    reports = iter((
        {"status": "response_needed", "jobs": [], "max_duration_seconds": 0, "sum_duration_seconds": 0},
        {"status": "complete", "jobs": [], "max_duration_seconds": 0, "sum_duration_seconds": 0},
    ))
    clock = iter((0.0, 0.0, 1.0))
    sleeps = []
    reports_seen = []
    monkeypatch.setattr("tools.run_blind_round.run_round", lambda *args, **kwargs: next(reports))
    monkeypatch.setattr("tools.run_blind_round.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("tools.run_blind_round.time.sleep", sleeps.append)

    report = watch_round(
        [job], poll_seconds=1.0, max_wait_seconds=10.0,
        on_report=reports_seen.append,
    )

    assert report["status"] == "complete"
    assert report["watch_status"] == "complete"
    assert sleeps == [1.0]
    assert [item["status"] for item in reports_seen] == ["response_needed", "complete"]


def test_watch_round_rejects_invalid_wait_parameters(tmp_path: Path):
    job = BlindJob(
        name="only", output_dir=tmp_path / "only", source=tmp_path / "only.txt",
        cast=tmp_path / "cast.json", source_id="only", round_version="V4",
        story_type="main", output_stem="only",
    )

    with pytest.raises(ValueError, match="poll_seconds"):
        watch_round([job], poll_seconds=0)
    with pytest.raises(ValueError, match="max_wait_seconds"):
        watch_round([job], max_wait_seconds=-1)
