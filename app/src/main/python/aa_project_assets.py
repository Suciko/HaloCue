# -*- coding: utf-8 -*-
"""AA project/save target selection and process-write guard."""

from __future__ import annotations

import csv
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL", "CLOCK$",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_WINDOWS_FORBIDDEN_CHARACTERS = set('<>:"/\\|?*')


def validate_windows_path_component(value: str, *, label: str = "path component") -> str:
    """Return one safe Windows name, never a path or device alias."""
    if not isinstance(value, str):
        value = str(value)
    if not value or not value.strip():
        raise ValueError(f"{label} must not be empty")
    if value in {".", ".."} or value.rstrip(". ") != value:
        raise ValueError(f"{label} must be a safe Windows path component")
    if any(
        char in _WINDOWS_FORBIDDEN_CHARACTERS
        or unicodedata.category(char) == "Cc"
        for char in value
    ):
        raise ValueError(f"{label} must be a safe Windows path component")
    device_stem = value.split(".", 1)[0].rstrip(" ").upper()
    if device_stem in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{label} must not use a Windows device name")
    return value


def resolve_safe_directory(value: str | Path, *, label: str) -> Path:
    """Resolve a directory target without accepting traversal or UNC input."""
    raw = Path(value).expanduser()
    if str(raw).startswith("\\\\"):
        raise ValueError(f"{label} must not use a UNC path")
    for part in raw.parts:
        if part == raw.anchor:
            continue
        validate_windows_path_component(part, label=label)
    return raw.resolve()


def destination_within(root: str | Path, *components: str) -> Path:
    """Resolve a file target and prove it remains below its intended root."""
    base = resolve_safe_directory(root, label="target root")
    destination = base
    for component in components:
        destination = destination / validate_windows_path_component(
            component, label="target path component"
        )
    destination = destination.resolve()
    try:
        destination.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"target path escapes its intended root: {destination}") from exc
    return destination


_PAIR_LOCKS_GUARD = threading.Lock()
_PAIR_LOCKS: dict[str, threading.RLock] = {}


def _lock_directories(target: "AAProjectTarget | Iterable[str | Path] | str | Path") -> tuple[Path, ...]:
    if isinstance(target, AAProjectTarget):
        values = (target.project_dir, target.save_dir)
    elif isinstance(target, (str, Path)):
        values = (target,)
    else:
        values = tuple(target)
    if not values:
        raise ValueError("at least one registration target is required")
    return tuple(
        resolve_safe_directory(value, label="registration target")
        for value in values
    )


def _pair_lock_key(target: "AAProjectTarget | Iterable[str | Path] | str | Path") -> str:
    return "\0".join(str(path).casefold() for path in _lock_directories(target))


@contextmanager
def _file_lock(lock_path: Path):
    """Acquire an exclusive, process-wide lock without touching AA data paths."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def project_target_lock(target: "AAProjectTarget | Iterable[str | Path] | str | Path"):
    """Serialize one canonical project/save target across threads and processes."""
    key = _pair_lock_key(target)
    with _PAIR_LOCKS_GUARD:
        local_lock = _PAIR_LOCKS.setdefault(key, threading.RLock())
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    lock_path = Path(tempfile.gettempdir()) / "aa-native-custom-assets-locks" / f"{digest}.lock"
    with local_lock:
        with _file_lock(lock_path):
            yield


@dataclass(frozen=True)
class AAProjectTarget:
    project_dir: Path
    save_dir: Path
    project_name: str

    def __post_init__(self) -> None:
        name = validate_windows_path_component(self.project_name, label="AA project name")
        project_dir = resolve_safe_directory(self.project_dir, label="AA project directory")
        save_dir = resolve_safe_directory(self.save_dir, label="AA save directory")
        if project_dir.name != name or save_dir.name != name:
            raise ValueError("AA project/save targets must end in the project name")
        object.__setattr__(self, "project_dir", project_dir)
        object.__setattr__(self, "save_dir", save_dir)
        object.__setattr__(self, "project_name", name)


def resolve_project_target(
    project_dir: str | Path, *, saves_root: str | Path | None = None
) -> AAProjectTarget:
    project = resolve_safe_directory(project_dir, label="AA project directory")
    project_name = validate_windows_path_component(project.name, label="AA project name")
    if saves_root is None:
        if project.parent.name != "projects":
            raise ValueError("AA project directory must use the projects/<name> layout")
        saves = project.parent.parent / "saves"
    else:
        saves = resolve_safe_directory(saves_root, label="AA saves directory")
    return AAProjectTarget(project, destination_within(saves, project_name), project_name)


def is_aa_running(process_names: Iterable[str] = ("AzureArchive.exe",)) -> bool:
    if sys.platform != "win32":
        return False
    for process_name in process_names:
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError as exc:
            raise RuntimeError(f"tasklist process probe failed: {exc}") from exc
        if completed.returncode:
            raise RuntimeError(
                f"tasklist process probe failed with exit code {completed.returncode}"
            )
        for row in csv.reader(io.StringIO(completed.stdout)):
            if row and row[0].strip().casefold() == process_name.casefold():
                return True
    return False


def assert_aa_closed(*, running_probe: Callable[[], bool] | None = None) -> None:
    from aa_registry import AssetRegistrationError

    try:
        running = (running_probe or is_aa_running)()
    except Exception as exc:
        raise AssetRegistrationError(
            f"aa_probe_failed: unable to determine whether AzureArchive is running: {exc}"
        ) from exc
    if running:
        raise AssetRegistrationError("aa_running: 请关闭 AzureArchive 后重试")
