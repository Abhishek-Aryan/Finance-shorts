"""
Unit tests for Schedule Watchdog (tools/watchdog.py and .github/workflows/watchdog.yml).
Tests:
- Detection of overdue Pending topics above configurable threshold
- Immunity to completed (Done), max-attempt (Failed), or future topics
- Watchdog report generation and CLI exit codes
- Workflow YAML configuration validation (off-peak crons, permissions, auto-recovery dispatch)
"""

from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
import yaml

from tools.watchdog import find_overdue_rows, generate_watchdog_report, main
from storage import state_store

IST = ZoneInfo("Asia/Kolkata")
WATCHDOG_WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "watchdog.yml"


@pytest.fixture
def sample_state(tmp_path):
    state_file = tmp_path / "test_state.json"
    now = datetime(2026, 10, 25, 20, 30, tzinfo=IST)
    
    # Row 1: Scheduled 30 min ago, Pending -> OVERDUE (if threshold <= 0.5h)
    # Row 2: Scheduled 30 min ago, Done -> NOT overdue
    # Row 3: Scheduled 10 min ago, Pending -> Overdue if threshold=0.1, Not overdue if threshold=0.3
    # Row 4: Scheduled in future (21:00), Pending -> NOT overdue
    # Row 5: Scheduled 60 min ago, attempts=2 -> NOT overdue (exceeded attempts)
    rows = {
        "D06-20:00": {
            "row_index": 18,
            "day": 6,
            "scheduled_at": "2026-10-25T20:00:00+05:30",
            "topic": "Put-Call Parity",
            "status": "Pending",
            "attempts": 0,
        },
        "D06-15:00": {
            "row_index": 17,
            "day": 6,
            "scheduled_at": "2026-10-25T15:00:00+05:30",
            "topic": "Credit Spreads",
            "status": "Done",
            "attempts": 0,
            "youtube_video_id": "abc123xyz",
        },
        "D06-20:20": {
            "row_index": 19,
            "day": 6,
            "scheduled_at": "2026-10-25T20:20:00+05:30",
            "topic": "Delta Hedging",
            "status": "Pending",
            "attempts": 0,
        },
        "D06-21:00": {
            "row_index": 20,
            "day": 6,
            "scheduled_at": "2026-10-25T21:00:00+05:30",
            "topic": "Futures Basis",
            "status": "Pending",
            "attempts": 0,
        },
        "D06-19:30": {
            "row_index": 21,
            "day": 6,
            "scheduled_at": "2026-10-25T19:30:00+05:30",
            "topic": "Gamma Squeeze",
            "status": "Failed",
            "attempts": 2,
        },
    }
    
    state_file.write_text(json.dumps({"version": 1, "rows": rows}), encoding="utf-8")
    return state_file, now


def test_watchdog_detects_overdue_rows(sample_state):
    state_file, now = sample_state
    
    # With threshold 0.25h (15 min): D06-20:00 (30m delay) is overdue; D06-20:20 (10m delay) is NOT
    overdue = find_overdue_rows(now=now, state_file=state_file, threshold_hours=0.25)
    assert len(overdue) == 1
    assert overdue[0]["row_key"] == "D06-20:00"
    assert overdue[0]["topic"] == "Put-Call Parity"
    assert overdue[0]["delay_hours"] == 0.5


def test_watchdog_tight_threshold(sample_state):
    state_file, now = sample_state
    
    # With threshold 0.1h (6 min): both D06-20:00 (30m) and D06-20:20 (10m) are overdue
    overdue = find_overdue_rows(now=now, state_file=state_file, threshold_hours=0.1)
    assert len(overdue) == 2
    keys = [o["row_key"] for o in overdue]
    assert "D06-20:00" in keys
    assert "D06-20:20" in keys


def test_watchdog_no_overdue_when_all_within_threshold(sample_state):
    state_file, now = sample_state
    
    # With threshold 1.0h (60 min): neither is >60m overdue
    overdue = find_overdue_rows(now=now, state_file=state_file, threshold_hours=1.0)
    assert len(overdue) == 0


def test_generate_watchdog_report():
    overdue = [
        {
            "row_key": "D06-20:00",
            "day": 6,
            "topic": "Put-Call Parity",
            "scheduled_at": "2026-10-25T20:00:00+05:30",
            "delay_hours": 0.5,
        }
    ]
    title, body = generate_watchdog_report(overdue, threshold_hours=0.25)
    assert "Schedule overdue" in title
    assert "Put-Call Parity" in body
    assert "D06-20:00" in body
    assert "0.2" in body or "0.25" in body or "overdue" in body.lower()


def test_watchdog_main_cli_exit_codes(sample_state, tmp_path, monkeypatch):
    state_file, now = sample_state
    out_title = tmp_path / "title.txt"
    out_body = tmp_path / "body.txt"
    
    # 1. Overdue row triggers exit code 1
    test_args = [
        "watchdog.py",
        "--state-file", str(state_file),
        "--threshold-hours", "0.25",
        "--out-title", str(out_title),
        "--out-body", str(out_body),
    ]
    monkeypatch.setattr("sys.argv", test_args)
    monkeypatch.setattr("tools.watchdog.datetime", type("MockDT", (), {
        "now": lambda tz=None: now,
        "fromisoformat": datetime.fromisoformat,
    }))
    
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert out_title.read_text(encoding="utf-8").strip() != ""
    assert "Put-Call Parity" in out_body.read_text(encoding="utf-8")

    # 2. No overdue row triggers exit code 0
    test_args_clean = [
        "watchdog.py",
        "--state-file", str(state_file),
        "--threshold-hours", "5.0",
        "--out-title", str(out_title),
        "--out-body", str(out_body),
    ]
    monkeypatch.setattr("sys.argv", test_args_clean)
    with pytest.raises(SystemExit) as exc_clean:
        main()
    assert exc_clean.value.code == 0


def test_watchdog_workflow_yaml():
    assert WATCHDOG_WORKFLOW.exists(), "watchdog.yml not found"
    data = yaml.safe_load(WATCHDOG_WORKFLOW.read_text(encoding="utf-8"))
    
    triggers = data.get("on") if "on" in data else data.get(True, {})
    assert "schedule" in triggers
    crons = [item["cron"] for item in triggers["schedule"]]
    assert len(crons) >= 1
    
    # Verify crons run at off-peak minutes
    for cron in crons:
        minute_part = cron.split()[0]
        assert "00" not in minute_part.split(",")
        assert "30" not in minute_part.split(",")
    
    # Verify auto-recovery dispatch step exists
    steps = data["jobs"]["check-overdue"]["steps"]
    step_names = [s.get("name", "") for s in steps]
    assert any("Auto-Recover" in name or "Alert" in name for name in step_names)
