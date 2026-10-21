"""
Finance Shorts Pro - Run Lock
Ensures only one publishing run executes at a time.
Uses data/.publish.lock with non-blocking acquisition (timeout=0).
Raises LockHeld on contention.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from filelock import FileLock, Timeout

import config

logger = logging.getLogger(__name__)

DEFAULT_LOCK_FILE = config.DATA_DIR / ".publish.lock"


class LockHeld(Exception):
    """Raised when another publishing process already holds the run lock."""


@contextmanager
def acquire_run_lock(lock_file: Path | None = None) -> Generator[Path, None, None]:
    """
    Context manager acquiring non-blocking lock on data/.publish.lock.
    Raises LockHeld immediately if the lock is held by another process.
    """
    l_path = Path(lock_file) if lock_file else DEFAULT_LOCK_FILE
    l_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(l_path), timeout=0)

    try:
        lock.acquire()
    except Timeout:
        raise LockHeld(f"Another process already holds the lock on {l_path}")

    try:
        yield l_path
    finally:
        try:
            lock.release()
        except Exception as e:
            logger.warning("Error releasing run lock %s: %s", l_path, e)
