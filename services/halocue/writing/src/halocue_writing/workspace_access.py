"""Per-workspace shared operations and fail-fast exclusive maintenance.

The lock file is intentionally never unlinked: replacing its inode would split
ownership across processes. It is runtime coordination, not backed-up content.
"""

from __future__ import annotations

import errno
import json
import os
import threading
import weakref
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from .errors import DomainError


class WorkspaceBusy(DomainError):
    def __init__(self, *, exclusive: bool):
        super().__init__(
            "backup_restore_busy" if exclusive else "writing_maintenance_busy",
            "仍有写作操作或任务正在执行，请等待结束后再恢复备份。"
            if exclusive
            else "写作数据正在恢复，请稍后重试。",
            status=409,
        )


class WorkspaceRecoveryRequired(DomainError):
    def __init__(self, marker: Path):
        super().__init__(
            "writing_recovery_required",
            "上次恢复未正常完成，已停止访问写作数据。请先人工检查恢复前备份和回滚目录，"
            "不要直接删除恢复标记或继续覆盖。",
            status=409,
            details={"recovery_marker": str(marker)},
        )


if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _lock_file = _kernel32.LockFileEx
    _lock_file.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_Overlapped),
    ]
    _lock_file.restype = wintypes.BOOL
    _unlock_file = _kernel32.UnlockFileEx
    _unlock_file.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_Overlapped),
    ]
    _unlock_file.restype = wintypes.BOOL

    def _try_lock(handle, *, exclusive):
        overlapped = _Overlapped()
        flags = 1 | (2 if exclusive else 0)  # FAIL_IMMEDIATELY | EXCLUSIVE_LOCK
        if _lock_file(
            msvcrt.get_osfhandle(handle.fileno()), flags, 0, 1, 0, ctypes.byref(overlapped)
        ):
            return True
        error = ctypes.get_last_error()
        if error == 33:  # ERROR_LOCK_VIOLATION
            return False
        raise ctypes.WinError(error)

    def _unlock(handle):
        overlapped = _Overlapped()
        if not _unlock_file(
            msvcrt.get_osfhandle(handle.fileno()), 0, 1, 0, ctypes.byref(overlapped)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
else:
    import fcntl

    def _try_lock(handle, *, exclusive):
        try:
            fcntl.flock(handle, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            return True
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise

    def _unlock(handle):
        fcntl.flock(handle, fcntl.LOCK_UN)


class WorkspaceAccess:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self.recovery_marker = data_dir / ".writing-restore-incomplete.json"

    @contextmanager
    def operation(self):
        with self._hold(exclusive=False):
            yield

    @contextmanager
    def maintenance(self):
        with self._hold(exclusive=True):
            yield

    @contextmanager
    def _hold(self, *, exclusive):
        if getattr(self._local, "pid", os.getpid()) != os.getpid():
            self._local.__dict__.clear()
        mode = getattr(self._local, "mode", None)
        if mode is not None:
            if exclusive and mode != "maintenance":
                # Never upgrade a shared operation after it has already read
                # the old workspace. The restore request is a separate boundary.
                raise WorkspaceBusy(exclusive=True)
            yield
            return
        with (self.data_dir / ".writing-access.lock").open("a+b") as handle:
            if not _try_lock(handle, exclusive=exclusive):
                raise WorkspaceBusy(exclusive=exclusive)
            self._local.pid = os.getpid()
            self._local.mode = "maintenance" if exclusive else "operation"
            try:
                if self.recovery_marker.exists():
                    raise WorkspaceRecoveryRequired(self.recovery_marker)
                yield
            finally:
                self._local.mode = None
                _unlock(handle)

    @contextmanager
    def restoring(self):
        """Fail closed after an interrupted or only partially rolled-back restore.

        This marker is not a replay journal. Recovery still needs an operator;
        merely reopening the service must never start writes into partial data.
        """
        if getattr(self._local, "mode", None) != "maintenance":
            raise RuntimeError("restoring requires exclusive workspace admission")
        if getattr(self._local, "restoring", False):
            yield
            return
        with self.recovery_marker.open("x", encoding="utf-8") as marker:
            marker.write('{"schema_version":"writing-restore-guard/1.0","phase":"in_progress"}\n')
            marker.flush()
            os.fsync(marker.fileno())
        self._local.restoring = True
        self._local.rollback_complete = False
        try:
            yield
        except BaseException:
            if self._local.rollback_complete:
                self.recovery_marker.unlink()
            raise
        else:
            self.recovery_marker.unlink()
        finally:
            self._local.restoring = False
            self._local.rollback_complete = False

    def record_restore_paths(self, **paths):
        if not getattr(self._local, "restoring", False):
            raise RuntimeError("restore paths require a restore session")
        with self.recovery_marker.open("w", encoding="utf-8") as marker:
            json.dump(
                {
                    "schema_version": "writing-restore-guard/1.0",
                    "phase": "in_progress",
                    **{key: str(value) for key, value in paths.items()},
                },
                marker,
                ensure_ascii=False,
            )
            marker.flush()
            os.fsync(marker.fileno())

    def rollback_completed(self):
        self._local.rollback_complete = True


_access_by_path: weakref.WeakValueDictionary[str, WorkspaceAccess] = weakref.WeakValueDictionary()
_registry_lock = threading.Lock()


def workspace_access(data_dir: Path) -> WorkspaceAccess:
    path = Path(data_dir).resolve()
    key = os.path.normcase(str(path))
    with _registry_lock:
        access = _access_by_path.get(key)
        if access is None:
            access = WorkspaceAccess(path)
            _access_by_path[key] = access
        return access


def workspace_operation(method):
    """Hold admission for the entire method, including model/HTTP waits."""

    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self.data_access.operation():
            return method(self, *args, **kwargs)

    guarded.workspace_operation = True
    return guarded
