from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .models import new_id


@dataclass
class JobRecord:
    job_id: str
    kind: str
    state: str
    created_at: str
    updated_at: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    run_id: str | None = None
    # Only non-sensitive inputs needed to submit the same stage again.
    retry_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "JobRecord":
        return cls(
            job_id=str(value["job_id"]),
            kind=str(value["kind"]),
            state=str(value["state"]),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            result=value.get("result") if isinstance(value.get("result"), dict) else None,
            error=value.get("error") if isinstance(value.get("error"), dict) else None,
            run_id=str(value.get("run_id") or "").strip() or None,
            retry_context=(value.get("retry_context") if isinstance(value.get("retry_context"), dict) else {}),
        )


class JobRegistry:
    _JOB_ID = re.compile(r"job-[0-9a-f]{12}")

    def __init__(self, base_dir: Path | None = None) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="halocue")
        self._jobs: dict[str, JobRecord] = {}
        self._futures: dict[str, Future] = {}
        self._lock = threading.RLock()
        self._base_dir = base_dir
        if self._base_dir:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            self._restore()

    @staticmethod
    def _now() -> str:
        return dt.datetime.now(dt.timezone.utc).isoformat()

    def _path(self, job_id: str) -> Path | None:
        return self._base_dir / f"{job_id}.json" if self._base_dir else None

    def _persist(self, record: JobRecord) -> None:
        path = self._path(record.job_id)
        if path is None:
            return
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, path)

    def _restore(self) -> None:
        for path in self._base_dir.glob("job-*.json") if self._base_dir else []:
            try:
                record = JobRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if not self._JOB_ID.fullmatch(record.job_id):
                continue
            if record.state in {"queued", "running"}:
                record.state = "interrupted"
                record.error = {
                    "code": "job_interrupted",
                    "message": "服务重启时任务仍在执行，需要重新提交",
                }
                record.updated_at = self._now()
                self._persist(record)
            self._jobs[record.job_id] = record

    def submit(
        self,
        kind: str,
        task: Callable[[], dict[str, Any]],
        *,
        run_id: str | None = None,
        retry_context: dict[str, Any] | None = None,
    ) -> JobRecord:
        now = self._now()
        record = JobRecord(
            new_id("job"), kind, "queued", now, now,
            run_id=run_id,
            retry_context=dict(retry_context or {}),
        )
        with self._lock:
            self._jobs[record.job_id] = record
            self._persist(record)

        def execute() -> None:
            with self._lock:
                record.state = "running"
                record.updated_at = self._now()
                self._persist(record)
            try:
                result = task()
            except Exception as exc:
                with self._lock:
                    record.state = "failed"
                    record.error = {
                        "code": str(getattr(exc, "code", "job_failed")),
                        "message": str(exc),
                    }
                    record.updated_at = self._now()
                    self._persist(record)
            else:
                with self._lock:
                    record.state = "succeeded"
                    record.result = result
                    record.updated_at = self._now()
                    self._persist(record)

        future = self._executor.submit(execute)
        with self._lock:
            self._futures[record.job_id] = future
        return record

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            record = self._jobs.get(job_id)
            future = self._futures.get(job_id)
            if record is None or record.state != "queued" or future is None:
                return False
            if not future.cancel():
                return False
            record.state = "cancelled"
            record.updated_at = self._now()
            record.error = None
            self._persist(record)
            return True

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[JobRecord]:
        with self._lock:
            return sorted(
                self._jobs.values(), key=lambda item: item.updated_at, reverse=True
            )

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
