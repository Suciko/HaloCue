"""Cross-thread/process admission for one upstream release, not all production state.

Lock files stay in place: unlinking them would let callers lock different inodes.
This guard is deliberately entered once by the public create_run template method.
"""

from __future__ import annotations

import errno
import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path


if os.name == "nt":
    import msvcrt

    def _lock(handle):
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as error:
                if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                time.sleep(0.05)

    def _unlock(handle):
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(handle):
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

    def _unlock(handle):
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def handoff_lock(data_dir: Path, release_id: str | None):
    if release_id is None:
        yield
        return
    directory = Path(data_dir) / ".handoff-locks"
    directory.mkdir(parents=True, exist_ok=True)
    # Identity never becomes an unchecked filesystem component.
    key = hashlib.sha256(release_id.encode("utf-8")).hexdigest()
    with (directory / f"{key}.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        _lock(handle)
        try:
            yield
        finally:
            _unlock(handle)
