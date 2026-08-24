from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from typing import Any

from .repository import Repository


AgentWorkHandler = Callable[[dict], Any]


class AgentDispatcher:
    """Lease-based worker for durable Agent operations.

    Handlers receive the complete claimed job dictionary. Its decoded input is
    available as ``job["payload"]``. A handler should return only after its own
    operation has committed. The final queue transition is guarded by the lease
    token, so a cancelled, recovered, or superseded worker cannot mark the job
    successful later.
    """

    def __init__(
        self,
        repository: Repository,
        *,
        worker_id: str | None = None,
        poll_interval: float = 0.2,
        lease_seconds: float = 30.0,
        heartbeat_interval: float | None = None,
    ):
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        heartbeat_interval = heartbeat_interval or max(0.1, lease_seconds / 3)
        if heartbeat_interval <= 0 or heartbeat_interval >= lease_seconds:
            raise ValueError("heartbeat_interval must be positive and shorter than lease_seconds")

        self.repository = repository
        self.worker_id = worker_id or f"dispatcher-{uuid.uuid4().hex[:12]}"
        self.poll_interval = poll_interval
        self.lease_seconds = lease_seconds
        self.heartbeat_interval = heartbeat_interval
        self._handlers: dict[str, AgentWorkHandler] = {}
        self._handlers_lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: dict | None = None

    def register(self, operation: str, handler: AgentWorkHandler) -> None:
        """Register or replace the callable for an operation name."""
        operation = str(operation or "").strip()
        if not operation:
            raise ValueError("operation is required")
        if not callable(handler):
            raise ValueError("handler must be callable")
        with self._handlers_lock:
            self._handlers[operation] = handler

    register_handler = register

    def unregister(self, operation: str) -> None:
        with self._handlers_lock:
            self._handlers.pop(operation, None)

    def start(self) -> dict:
        """Start one daemon worker and return ``{started, worker_id}``."""
        if self._thread and self._thread.is_alive():
            return {"started": False, "worker_id": self.worker_id}
        self._stop.clear()
        self._wake.clear()
        recovery = self.repository.recover_expired_agent_work()
        self._thread = threading.Thread(
            target=self._run,
            name=f"halocue-agent-{self.worker_id}",
            daemon=True,
        )
        self._thread.start()
        return {
            "started": True,
            "worker_id": self.worker_id,
            "recovered_count": recovery["recovered_count"],
        }

    def notify(self) -> None:
        """Wake the poller after a caller enqueues new work."""
        self._wake.set()

    def descriptor(self) -> dict:
        thread = self._thread
        return {
            "worker_id": self.worker_id,
            "running": bool(thread and thread.is_alive()),
            "lease_seconds": self.lease_seconds,
            "poll_interval": self.poll_interval,
            "last_error": self.last_error,
        }

    def close(self, timeout: float = 5.0) -> dict:
        """Request shutdown, join for at most timeout, and report termination."""
        if timeout < 0:
            raise ValueError("timeout cannot be negative")
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread:
            thread.join(timeout=timeout)
        stopped = thread is None or not thread.is_alive()
        if stopped:
            self._thread = None
        return {"stopped": stopped, "worker_id": self.worker_id}

    def run_once(self) -> dict:
        """Claim and execute at most one job; useful for controlled workers/tests."""
        claim = self.repository.claim_agent_work(
            lease_owner=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        job = claim["job"]
        if not job:
            return {"handled": False, "job": None}
        outcome = self._handle(job)
        return {"handled": True, "job": job, **outcome}

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = self.run_once()
                self.last_error = None
            except Exception as exc:  # keep a transient SQLite failure from killing the worker
                self.last_error = {
                    "code": "dispatcher_internal_error",
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
                result = {"handled": False}
            if not result["handled"]:
                self._wake.wait(self.poll_interval)
                self._wake.clear()

    def _handle(self, job: dict) -> dict:
        operation = job["operation"]
        with self._handlers_lock:
            handler = self._handlers.get(operation)
        if not handler:
            error = {
                "code": "agent_operation_not_registered",
                "message": f"No handler is registered for {operation}.",
                "retryable": False,
            }
            applied = self.repository.fail_agent_work(
                job_id=job["id"],
                lease_owner=self.worker_id,
                lease_token=job["lease_token"],
                error=error,
            )["applied"]
            return {"status": "failed", "applied": applied, "error": error}

        heartbeat_stop = threading.Event()
        lease_lost = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat,
            args=(job, heartbeat_stop, lease_lost),
            name=f"halocue-heartbeat-{job['id']}",
            daemon=True,
        )
        heartbeat.start()
        error = None
        result = None
        try:
            result = handler(job)
        except Exception as exc:
            error = {
                "code": "agent_operation_failed",
                "type": type(exc).__name__,
                "message": str(exc),
                "retryable": True,
            }
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=self.heartbeat_interval + 0.5)

        if lease_lost.is_set():
            return {"status": "lease_lost", "applied": False, "error": error}
        if error:
            applied = self.repository.fail_agent_work(
                job_id=job["id"],
                lease_owner=self.worker_id,
                lease_token=job["lease_token"],
                error=error,
            )["applied"]
            return {"status": "failed", "applied": applied, "error": error}
        if (
            not job.get("agent_run_id")
            and isinstance(result, dict)
            and result.get("agent_run_id")
        ):
            bound = self.repository.bind_agent_work_run(
                job_id=job["id"],
                lease_owner=self.worker_id,
                lease_token=job["lease_token"],
                agent_run_id=str(result["agent_run_id"]),
            )
            if not bound["applied"]:
                return {"status": "lease_lost", "applied": False, "error": None}
        applied = self.repository.complete_agent_work(
            job_id=job["id"],
            lease_owner=self.worker_id,
            lease_token=job["lease_token"],
        )["applied"]
        return {
            "status": "succeeded" if applied else "lease_lost",
            "applied": applied,
            "error": None,
        }

    def _heartbeat(
        self,
        job: dict,
        heartbeat_stop: threading.Event,
        lease_lost: threading.Event,
    ) -> None:
        while not heartbeat_stop.wait(self.heartbeat_interval):
            if self._stop.is_set():
                return
            result = self.repository.heartbeat_agent_work(
                job_id=job["id"],
                lease_owner=self.worker_id,
                lease_token=job["lease_token"],
                lease_seconds=self.lease_seconds,
            )
            if not result["applied"]:
                lease_lost.set()
                return
