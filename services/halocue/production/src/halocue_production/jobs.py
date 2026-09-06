from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .models import new_id


class JobSignal(RuntimeError):
    """A cooperative worker outcome that is not an implementation failure."""

    def __init__(self, message: str, *, result: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.result = result


class JobCancelled(JobSignal):
    pass


class JobPaused(JobSignal):
    pass


class JobSuperseded(JobSignal):
    pass


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
    started_at: str | None = None
    finished_at: str | None = None
    cancel_requested_at: str | None = None
    pause_requested_at: str | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    resumed_from_job_id: str | None = None

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
            started_at=str(value.get("started_at") or "").strip() or None,
            finished_at=str(value.get("finished_at") or "").strip() or None,
            cancel_requested_at=str(value.get("cancel_requested_at") or "").strip() or None,
            pause_requested_at=str(value.get("pause_requested_at") or "").strip() or None,
            progress=value.get("progress") if isinstance(value.get("progress"), dict) else {},
            events=[
                dict(item)
                for item in (value.get("events") if isinstance(value.get("events"), list) else [])
                if isinstance(item, dict)
            ][-100:],
            resumed_from_job_id=str(value.get("resumed_from_job_id") or "").strip() or None,
        )


class JobControl:
    def __init__(self, registry: "JobRegistry", job_id: str) -> None:
        self._registry = registry
        self.job_id = job_id
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._supersede = threading.Event()
        self._stop = threading.Event()
        self._callback_lock = threading.RLock()
        self._stop_callbacks: dict[int, Callable[[], None]] = {}
        self._next_callback_id = 0

    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    def pause_requested(self) -> bool:
        return self._pause.is_set() and not self._cancel.is_set()

    def stop_requested(self) -> bool:
        return self._stop.is_set()

    def superseded_requested(self) -> bool:
        return self._supersede.is_set()

    def wait_for_stop(self, timeout: float | None = None) -> bool:
        return self._stop.wait(timeout)

    def add_stop_callback(self, callback: Callable[[], None]) -> Callable[[], None]:
        with self._callback_lock:
            self._next_callback_id += 1
            callback_id = self._next_callback_id
            self._stop_callbacks[callback_id] = callback
            already_stopped = self._stop.is_set()
        if already_stopped:
            callback()

        def remove() -> None:
            with self._callback_lock:
                self._stop_callbacks.pop(callback_id, None)

        return remove

    def _notify_stop_callbacks(self) -> None:
        with self._callback_lock:
            callbacks = list(self._stop_callbacks.values())
        for callback in callbacks:
            try:
                callback()
            except Exception:
                continue

    def request_cancel(self) -> None:
        self._pause.clear()
        self._supersede.clear()
        self._cancel.set()
        self._stop.set()
        self._notify_stop_callbacks()

    def request_pause(self) -> None:
        if not self._cancel.is_set() and not self._supersede.is_set():
            self._pause.set()
            self._stop.set()
            self._notify_stop_callbacks()

    def request_supersede(self) -> None:
        if not self._cancel.is_set():
            self._pause.clear()
            self._supersede.set()
            self._stop.set()
            self._notify_stop_callbacks()

    def report_progress(
        self,
        phase: str,
        current: int,
        total: int,
        detail: str,
        **fields: Any,
    ) -> None:
        self._registry.update_progress(
            self.job_id,
            phase=phase,
            current=current,
            total=total,
            detail=detail,
            fields=fields,
        )

    def record_event(self, event: dict[str, Any]) -> None:
        self._registry.append_event(self.job_id, event)


class JobRegistry:
    _JOB_ID = re.compile(r"job-[0-9a-f]{12}")

    def __init__(self, base_dir: Path | None = None) -> None:
        self._executors = {
            "generation": ThreadPoolExecutor(max_workers=1, thread_name_prefix="halocue-generation"),
            "compile": ThreadPoolExecutor(max_workers=1, thread_name_prefix="halocue-compile"),
            "utility": ThreadPoolExecutor(max_workers=1, thread_name_prefix="halocue-utility"),
        }
        self._jobs: dict[str, JobRecord] = {}
        self._futures: dict[str, Future] = {}
        self._controls: dict[str, JobControl] = {}
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
                record.finished_at = record.updated_at
                self._persist(record)
            elif record.state == "pausing":
                record.state = "paused"
                record.updated_at = self._now()
                record.finished_at = record.updated_at
                self._persist(record)
            elif record.state == "cancelling":
                record.state = "cancelled"
                record.updated_at = self._now()
                record.finished_at = record.updated_at
                self._persist(record)
            self._jobs[record.job_id] = record

    def _executor_for(self, kind: str) -> ThreadPoolExecutor:
        if kind in {"direction_generation", "cg_advice"}:
            return self._executors["generation"]
        if kind == "compile":
            return self._executors["compile"]
        return self._executors["utility"]

    def _finish(
        self,
        record: JobRecord,
        *,
        state: str,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        now = self._now()
        record.state = state
        record.result = result
        record.error = error
        record.updated_at = now
        record.finished_at = now
        if state == "succeeded":
            record.progress = {
                **record.progress,
                "phase": "completed",
                "percent": 100.0,
                "detail": "任务已完成",
                "updated_at": now,
            }
        elif state in {"paused", "cancelled", "superseded"}:
            detail = {
                "paused": "任务已暂停，检查点已保留",
                "cancelled": "任务已结束，未完成结果不会写回",
                "superseded": "任务输入已变化，旧结果已丢弃",
            }[state]
            record.progress = {
                **record.progress,
                "phase": state,
                "detail": detail,
                "updated_at": now,
            }
        self._persist(record)

    @staticmethod
    def _exception_error(exc: Exception) -> dict[str, Any]:
        error = {
            "code": str(getattr(exc, "code", "job_failed")),
            "message": str(exc),
            "type": type(exc).__name__,
            "retryable": bool(getattr(exc, "retryable", True)),
            "traceback": "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )[-20_000:],
        }
        details = getattr(exc, "details", None)
        if isinstance(details, dict) and details:
            error["details"] = details
        return error

    def submit(
        self,
        kind: str,
        task: Callable[..., dict[str, Any]],
        *,
        run_id: str | None = None,
        retry_context: dict[str, Any] | None = None,
        job_id: str | None = None,
        cooperative: bool = False,
        resumed_from_job_id: str | None = None,
    ) -> JobRecord:
        now = self._now()
        record = JobRecord(
            job_id or new_id("job"), kind, "queued", now, now,
            run_id=run_id,
            retry_context=dict(retry_context or {}),
            progress={
                "phase": "queued",
                "current": 0,
                "total": 0,
                "percent": 0.0,
                "detail": "等待后台执行",
                "updated_at": now,
            },
            resumed_from_job_id=resumed_from_job_id,
        )
        if not self._JOB_ID.fullmatch(record.job_id):
            raise ValueError("invalid job_id")
        control = JobControl(self, record.job_id)
        with self._lock:
            if record.job_id in self._jobs:
                raise ValueError("job_id already exists")
            self._jobs[record.job_id] = record
            self._controls[record.job_id] = control
            self._persist(record)

        def execute() -> None:
            with self._lock:
                if record.state != "queued":
                    if control.cancel_requested() and record.state != "cancelled":
                        self._finish(record, state="cancelled")
                    elif control.pause_requested() and record.state != "paused":
                        self._finish(record, state="paused")
                    return
                record.state = "running"
                record.updated_at = self._now()
                record.started_at = record.updated_at
                record.progress = {
                    **record.progress,
                    "phase": "starting",
                    "detail": "后台任务已经开始",
                    "updated_at": record.updated_at,
                }
                self._persist(record)
            try:
                result = task(control) if cooperative else task()
            except JobPaused as exc:
                with self._lock:
                    self._finish(record, state="paused", result=exc.result)
            except JobCancelled as exc:
                with self._lock:
                    self._finish(record, state="cancelled", result=exc.result)
            except JobSuperseded as exc:
                with self._lock:
                    self._finish(
                        record,
                        state="superseded",
                        result=exc.result,
                        error={"code": "job_superseded", "message": str(exc), "retryable": False},
                    )
            except Exception as exc:
                with self._lock:
                    if control.cancel_requested():
                        self._finish(record, state="cancelled")
                    elif control.pause_requested():
                        self._finish(record, state="paused")
                    elif control.superseded_requested():
                        self._finish(
                            record,
                            state="superseded",
                            error={
                                "code": "job_superseded",
                                "message": "任务输入已变化，迟到结果已丢弃",
                                "retryable": False,
                            },
                        )
                    else:
                        error = self._exception_error(exc)
                        self._finish(record, state="failed", error=error)
                        self.append_event(
                            record.job_id,
                            {"level": "error", "kind": "failure", **error},
                        )
            else:
                with self._lock:
                    if control.cancel_requested():
                        self._finish(record, state="cancelled", result=result)
                    elif control.pause_requested():
                        self._finish(record, state="paused", result=result)
                    elif control.superseded_requested():
                        self._finish(
                            record,
                            state="superseded",
                            result=result,
                            error={
                                "code": "job_superseded",
                                "message": "任务输入已变化，迟到结果已丢弃",
                                "retryable": False,
                            },
                        )
                    else:
                        self._finish(record, state="succeeded", result=result)

        future = self._executor_for(kind).submit(execute)
        with self._lock:
            self._futures[record.job_id] = future
        return record

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            record = self._jobs.get(job_id)
            future = self._futures.get(job_id)
            control = self._controls.get(job_id)
            if record is None or control is None or record.state not in {
                "queued", "running", "pausing", "cancelling",
            }:
                return False
            now = self._now()
            control.request_cancel()
            record.cancel_requested_at = now
            if record.state == "queued" and future is not None and future.cancel():
                self._finish(record, state="cancelled")
                return True
            record.state = "cancelling"
            record.updated_at = now
            record.progress = {
                **record.progress,
                "phase": "cancelling",
                "detail": "正在结束；已通知模型连接立即中止",
                "updated_at": now,
            }
            self._persist(record)
            return True

    def pause(self, job_id: str) -> bool:
        with self._lock:
            record = self._jobs.get(job_id)
            future = self._futures.get(job_id)
            control = self._controls.get(job_id)
            if record is None or control is None or record.state not in {"queued", "running"}:
                return False
            now = self._now()
            control.request_pause()
            record.pause_requested_at = now
            if record.state == "queued" and future is not None and future.cancel():
                self._finish(record, state="paused")
                return True
            record.state = "pausing"
            record.updated_at = now
            record.progress = {
                **record.progress,
                "phase": "pausing",
                "detail": "正在中止当前模型请求，并保留已完成分块的检查点",
                "updated_at": now,
            }
            self._persist(record)
            return True

    def supersede(self, job_id: str) -> bool:
        with self._lock:
            record = self._jobs.get(job_id)
            future = self._futures.get(job_id)
            control = self._controls.get(job_id)
            if record is None or control is None or record.state not in {
                "queued", "running", "pausing",
            }:
                return False
            control.request_supersede()
            if record.state == "queued" and future is not None and future.cancel():
                self._finish(
                    record,
                    state="superseded",
                    error={
                        "code": "job_superseded",
                        "message": "任务输入已变化，排队任务已丢弃",
                        "retryable": False,
                    },
                )
                return True
            now = self._now()
            record.progress = {
                **record.progress,
                "phase": "superseding",
                "detail": "草稿已经变化，正在丢弃旧任务结果",
                "updated_at": now,
            }
            record.updated_at = now
            self._persist(record)
            return True

    def active_for_run(self, run_id: str, *, kind: str | None = None) -> JobRecord | None:
        with self._lock:
            active_states = {"queued", "running", "pausing", "cancelling"}
            candidates = [
                item for item in self._jobs.values()
                if item.run_id == run_id
                and item.state in active_states
                and (kind is None or item.kind == kind)
            ]
            return max(candidates, key=lambda item: item.created_at) if candidates else None

    def update_progress(
        self,
        job_id: str,
        *,
        phase: str,
        current: int,
        total: int,
        detail: str,
        fields: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None or record.state not in {"running", "pausing", "cancelling"}:
                return
            now = self._now()
            current = max(0, int(current or 0))
            total = max(0, int(total or 0))
            record.progress = {
                "phase": str(phase or "running")[:80],
                "current": current,
                "total": total,
                "percent": round(current * 100 / total, 1) if total else 0.0,
                "detail": str(detail or "")[:500],
                "updated_at": now,
                **dict(fields or {}),
            }
            record.updated_at = now
            self._persist(record)

    def append_event(self, job_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            safe = {
                str(key)[:80]: value
                for key, value in dict(event or {}).items()
                if key not in {"prompt", "user", "volatile", "static_system", "reasoning_text"}
            }
            safe.setdefault("at", self._now())
            record.events = (record.events + [safe])[-100:]
            record.updated_at = self._now()
            self._persist(record)

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[JobRecord]:
        with self._lock:
            return sorted(
                self._jobs.values(), key=lambda item: item.updated_at, reverse=True
            )

    def close(self) -> None:
        for executor in self._executors.values():
            executor.shutdown(wait=False, cancel_futures=True)
