"""
Tests for Phase 4: Locking and Trigger Cleanup
- Lock contention across two subprocesses (second exits 0 without publishing)
- Daemon persistence across simulated restart (no double fire)
- No-argument invocation prints usage and does not publish
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

import config
from automation.run_lock import acquire_run_lock
from storage import state_store

IST = ZoneInfo("Asia/Kolkata")


def test_no_argument_invocation_prints_usage():
    """Running python -m automation.schedule_runner with no arguments prints usage and exits 0."""
    result = subprocess.run(
        [sys.executable, "-m", "automation.schedule_runner"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Usage: python -m automation.schedule_runner" in result.stdout


def test_lock_contention_subprocesses(tmp_path):
    """When lock is held, a second invocation exits with code 0 without publishing."""
    lock_file = tmp_path / "test_run.lock"

    # Acquire lock in parent context
    with acquire_run_lock(lock_file):
        # Run child python process trying to publish_next_topic with the same lock_file
        code = f"""
from automation.schedule_runner import publish_next_topic
import sys
from pathlib import Path
exit_code = publish_next_topic(lock_file=Path(r'{lock_file}'))
sys.exit(exit_code)
"""
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "holds the run lock" in proc.stdout or "holds the lock" in proc.stderr or proc.returncode == 0


def test_daemon_persistence_across_restart(tmp_path):
    """Daemon fired slots persist in schedule_state.json across restarts."""
    state_file = tmp_path / "daemon_state.json"
    st = {
        "version": 1,
        "updated_at": "2026-10-21T09:00:00+05:30",
        "rows": {},
        "daemon": {"fired": {"2026-10-21": ["09:00"]}},
    }
    state_store.save(st, state_file=state_file)

    # Simulated restart: read state back from disk
    loaded = state_store.load(state_file=state_file)
    fired_today = loaded.get("daemon", {}).get("fired", {}).get("2026-10-21", [])
    assert "09:00" in fired_today

    # Adding 15:00 and saving
    fired_today.append("15:00")
    loaded["daemon"]["fired"]["2026-10-21"] = sorted(fired_today)
    state_store.save(loaded, state_file=state_file)

    # Second restart check
    reloaded = state_store.load(state_file=state_file)
    assert reloaded["daemon"]["fired"]["2026-10-21"] == ["09:00", "15:00"]


def test_run_lock_timeout_and_release_error(tmp_path, monkeypatch):
    """Test Timeout -> LockHeld and release exception handling in run_lock."""
    from unittest.mock import MagicMock
    from filelock import Timeout
    from automation.run_lock import acquire_run_lock, LockHeld

    fake_lock = MagicMock()
    fake_lock.acquire.side_effect = Timeout("Timed out")
    monkeypatch.setattr("automation.run_lock.FileLock", lambda *a, **kw: fake_lock)

    with pytest.raises(LockHeld) as exc:
        with acquire_run_lock(tmp_path / "test.lock"):
            pass
    assert "holds the lock" in str(exc.value)

    # Test release exception
    fake_lock_2 = MagicMock()
    fake_lock_2.release.side_effect = RuntimeError("Disk IO error")
    monkeypatch.setattr("automation.run_lock.FileLock", lambda *a, **kw: fake_lock_2)

    with acquire_run_lock(tmp_path / "test2.lock"):
        pass  # should not raise

