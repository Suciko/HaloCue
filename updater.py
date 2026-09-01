"""Standalone updater process used after HaloCue exits."""

from __future__ import annotations

import argparse
import os
import subprocess
import shutil
import sys
import time
from pathlib import Path

from update_manager import UpdateError, swap_installation


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    try:
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return False
        ctypes.windll.kernel32.CloseHandle(process)
        return True
    except Exception:
        return True


def wait_for_exit(pid: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while _pid_running(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if _pid_running(pid):
        raise UpdateError("HaloCue did not exit before the update timeout")


def apply_update(
    *,
    pid: int,
    install_root: Path,
    staged_root: Path,
    launch: bool = True,
) -> dict[str, object]:
    wait_for_exit(pid, timeout=30.0)
    install_root = Path(install_root).resolve()
    staged_root = Path(staged_root).resolve()
    temporary_stage = None
    if install_root.parent != staged_root.parent:
        # Downloads normally live under %LOCALAPPDATA%; copy to the install
        # volume before the atomic directory swap.
        temporary_stage = install_root.parent / f".{install_root.name}.staged-{os.getpid()}"
        if temporary_stage.exists():
            shutil.rmtree(temporary_stage)
        shutil.copytree(staged_root, temporary_stage)
        staged_root = temporary_stage
    rollback = swap_installation(install_root, staged_root)
    launched = False
    try:
        if launch:
            subprocess.Popen(
                [str(Path(install_root) / "HaloCue.exe")],
                cwd=install_root,
                close_fds=True,
            )
            launched = True
    except OSError as exc:
        # Keep the old directory available and restore it if the new executable
        # could not even be started.
        os.replace(install_root, staged_root)
        os.replace(rollback, install_root)
        raise UpdateError("updated HaloCue could not be started") from exc
    return {"ok": True, "rollback": str(rollback), "launched": launched}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--staged-root", type=Path, required=True)
    parser.add_argument("--no-launch", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = apply_update(
            pid=args.pid,
            install_root=args.install_root,
            staged_root=args.staged_root,
            launch=not args.no_launch,
        )
    except (OSError, UpdateError) as exc:
        print(f"HaloCue update failed: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
