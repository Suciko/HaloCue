# -*- coding: utf-8 -*-
"""
AA 剧本编译器 - 后台任务管理 (jobs.py)
实现 JobManager 单工作者串行队列、服务端 job_id、合作式取消与 24h 自动清理
"""

import datetime
import queue
import threading
import uuid
from typing import Any, Callable, Dict, Mapping, Optional


def _failure_metadata(exc: Exception) -> tuple[str, Dict[str, Any]]:
    """Extract public, stable metadata without coupling jobs to one provider."""
    code = "task_failed"
    detail: Dict[str, Any] = {}
    current: Optional[BaseException] = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        raw_candidate = getattr(current, "code", "")
        candidate = raw_candidate if isinstance(raw_candidate, str) else ""
        if candidate and (code == "task_failed" or candidate != "llm_error"):
            code = candidate
        model = str(getattr(current, "model", "") or "")
        if model:
            detail["model"] = model
        retryable = getattr(current, "retryable", None)
        if isinstance(retryable, bool):
            detail["retryable"] = retryable
        http_status = getattr(current, "http_status", None)
        if isinstance(http_status, int):
            detail["http_status"] = http_status
        current = current.__cause__ or current.__context__
    return code, detail


class Job:
    _ACTIVITY_FIELDS = frozenset({
        "state", "model", "request_started_at_ms", "elapsed_ms", "first_delta_ms",
        "first_reasoning_ms", "first_content_ms", "reasoning_chars", "content_chars",
        "received_chars", "finish_reason", "scene_id", "chunk_id", "chunk_current",
        "chunk_total", "request_index", "retry_count", "subdivision_count",
        "reason", "next_chunk_lines",
    })

    def __init__(self, job_id: str, label: str = "job"):
        self.job_id = job_id
        self.label = label
        self.state = "queued"  # queued | running | succeeded | failed | cancelled
        self.progress = 0.0
        self.detail = ""
        self.result = None
        self.error = None
        self.error_code = None
        self.error_detail: Dict[str, Any] = {}
        self.activity: Dict[str, Any] = {}
        self.cancel_requested = False
        self.created_at = datetime.datetime.now(datetime.timezone.utc)
        self.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self.completed_at: Optional[datetime.datetime] = None
        self._lock = threading.Lock()

    def update_progress(self, progress: float, detail: str = ""):
        with self._lock:
            self.progress = float(progress)
            if detail:
                self.detail = detail
            self.updated_at = datetime.datetime.now(datetime.timezone.utc)

    def update_activity(self, activity: Optional[Mapping[str, Any]]) -> None:
        """Store a sanitized activity snapshot without changing progress/detail."""
        if not isinstance(activity, Mapping):
            return
        snapshot = {key: value for key, value in activity.items() if key in self._ACTIVITY_FIELDS}
        with self._lock:
            self.activity = snapshot
            self.updated_at = datetime.datetime.now(datetime.timezone.utc)

    def is_cancel_requested(self) -> bool:
        with self._lock:
            return self.cancel_requested

    def request_cancel(self):
        with self._lock:
            self.cancel_requested = True
            if self.state == "queued":
                self.state = "cancelled"
                self.completed_at = datetime.datetime.now(datetime.timezone.utc)
            self.updated_at = datetime.datetime.now(datetime.timezone.utc)

    def mark_cancelled(self):
        with self._lock:
            self.state = "cancelled"
            self.completed_at = datetime.datetime.now(datetime.timezone.utc)
            self.updated_at = datetime.datetime.now(datetime.timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "job_id": self.job_id,
                "label": self.label,
                "state": self.state,
                "progress": self.progress,
                "detail": self.detail,
                "activity": dict(self.activity),
                "result": self.result,
                "error": self.error,
                "error_code": self.error_code,
                "error_detail": dict(self.error_detail),
                "cancel_requested": self.cancel_requested,
                "created_at": self.created_at.isoformat(),
                "updated_at": self.updated_at.isoformat(),
                "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            }


class JobManager:
    def __init__(self, ttl_seconds: int = 86400):
        self.ttl_seconds = ttl_seconds
        self._jobs: Dict[str, Job] = {}
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()

        # 启动后台单线程 Worker
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def _worker_loop(self):
        while True:
            job, fn = self._queue.get()
            if job is None:
                break

            with job._lock:
                if job.state == "cancelled":
                    self._queue.task_done()
                    continue
                job.state = "running"
                job.updated_at = datetime.datetime.now(datetime.timezone.utc)

            try:
                res = fn(job)
                with job._lock:
                    if job.state != "cancelled":
                        job.state = "succeeded"
                        job.result = res
                        if job.progress == 0.0:
                            job.progress = 100.0
                        job.completed_at = datetime.datetime.now(datetime.timezone.utc)
            except Exception as e:
                with job._lock:
                    if job.state != "cancelled":
                        job.state = "failed"
                        job.error = str(e)
                        job.error_code, job.error_detail = _failure_metadata(e)
                        job.completed_at = datetime.datetime.now(datetime.timezone.utc)
            finally:
                job.updated_at = datetime.datetime.now(datetime.timezone.utc)
                self._queue.task_done()

    def submit(self, fn: Callable[[Job], Any], label: str = "job", prefix: str = "job-") -> str:
        job_id = f"{prefix}{uuid.uuid4().hex[:12]}"
        job = Job(job_id, label=label)

        with self._lock:
            self._jobs[job_id] = job

        self._queue.put((job, fn))
        return job_id

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            return job.to_dict()

    def cancel(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job.request_cancel()
            return job.to_dict()

    def clean_stale_jobs(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        with self._lock:
            stale_keys = []
            for jid, job in self._jobs.items():
                if job.completed_at:
                    elapsed = (now - job.completed_at).total_seconds()
                    if elapsed > self.ttl_seconds:
                        stale_keys.append(jid)
            for jid in stale_keys:
                del self._jobs[jid]


# 全局单例 JobManager，供 webui 和应用统一使用
global_job_manager = JobManager()
