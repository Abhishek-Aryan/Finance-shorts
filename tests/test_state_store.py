"""
Tests for storage/state_store.py:
- Row key stability
- Atomic write & crash simulation
- Reconciliation matrix (all cases)
- Initial state generation from Excel
- Lifecycle methods (claim, complete, fail, upsert, get)
- Excel DataValidation dropdown
"""

from __future__ import annotations

import json
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
import openpyxl
import pytest

from storage.state_store import (
    IST,
    RunInProgressError,
    StateConflictError,
    all_rows,
    claim,
    complete,
    compute_row_key,
    fail,
    get,
    load,
    reconcile,
    save,
    upsert,
)
from storage.schedule_manager import add_status_validation, format_status_cell


@pytest.fixture
def mock_excel_schedule(tmp_path):
    """Creates a mock Excel workbook with 3 rows matching publishing_schedule schema."""
    excel_path = tmp_path / "mock_schedule.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Publishing Schedule"

    headers = [
        "Day #", "Week", "Date", "Day of Week", "Publish Time",
        "Topic", "Category", "Key Learning Objective", "Script", "Posted?"
    ]
    ws.append(headers)

    ws.append([1, 1, "20-Oct-2026", "Tuesday", "9:00 AM", "Yield Curve Inversion", "Macro", "Obj 1", "Script 1", "Done"])
    ws.append([1, 1, "20-Oct-2026", "Tuesday", "3:00 PM", "Free Cash Flow", "Corp", "Obj 2", "", "Pending"])
    ws.append([2, 1, "21-Oct-2026", "Wednesday", "9:00 AM", "P/E Ratio", "Valuation", "Obj 3", "", "Pending"])

    add_status_validation(ws, 2, 4)
    wb.save(excel_path)
    return excel_path


def test_row_key_stability():
    """row_key is strictly f'D{day:02d}-{HH:MM}' regardless of topic or row position."""
    assert compute_row_key(1, "9:00 AM") == "D01-09:00"
    assert compute_row_key("1", "09:00") == "D01-09:00"
    assert compute_row_key(2, "3:00 PM") == "D02-15:00"
    assert compute_row_key(14, "8:00 PM") == "D14-20:00"
    assert compute_row_key(5, dt_time(15, 30)) == "D05-15:30"

    with pytest.raises(ValueError):
        compute_row_key(1, "invalid_time")


def test_atomic_write_and_kill_simulation(tmp_path):
    """Writing state uses atomic replacement; an error before replace leaves original file intact."""
    state_file = tmp_path / "state.json"
    initial_data = {
        "version": 1,
        "updated_at": "2026-10-21T09:00:00+05:30",
        "rows": {"D01-09:00": {"status": "Done"}},
    }
    save(initial_data, state_file)
    assert state_file.exists()

    # Simulate crash mid-write by patching json.dump to raise an IOError
    with patch("json.dump", side_effect=IOError("Simulated disk error or crash")):
        with pytest.raises(IOError):
            save({"version": 1, "rows": {"D01-09:00": {"status": "CORRUPTED"}}}, state_file)

    # Read back state file - it must still contain the uncorrupted initial data
    with open(state_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["rows"]["D01-09:00"]["status"] == "Done"


def test_initial_state_build_from_excel(mock_excel_schedule, tmp_path):
    """First run with no state file imports Excel rows properly."""
    state_file = tmp_path / "new_state.json"
    st = load(state_file=state_file, excel_file=mock_excel_schedule)

    assert st["version"] == 1
    assert "D01-09:00" in st["rows"]
    assert "D01-15:00" in st["rows"]
    assert "D02-09:00" in st["rows"]

    r1 = st["rows"]["D01-09:00"]
    assert r1["status"] == "Done"
    assert r1["youtube_video_id"] is None
    assert r1["note"] == "imported from Excel"

    r2 = st["rows"]["D01-15:00"]
    assert r2["status"] == "Pending"
    assert r2["youtube_video_id"] is None


def test_reconciliation_excel_done_state_pending(mock_excel_schedule, tmp_path):
    """Excel Done, state Pending -> accept Excel, set state Done."""
    state_file = tmp_path / "test_state.json"
    st = load(state_file, mock_excel_schedule)

    # Force D01-09:00 in state to Pending while Excel is Done
    st["rows"]["D01-09:00"]["status"] = "Pending"
    save(st, state_file)

    reconciled = reconcile(excel_path=mock_excel_schedule, state_file=state_file)
    assert reconciled["rows"]["D01-09:00"]["status"] == "Done"
    assert reconciled["rows"]["D01-09:00"]["note"] == "accepted from Excel"


def test_reconciliation_excel_done_state_failed(mock_excel_schedule, tmp_path):
    """Excel Done, state Failed -> accept Excel, set state Done."""
    state_file = tmp_path / "test_state.json"
    st = load(state_file, mock_excel_schedule)

    st["rows"]["D01-09:00"]["status"] = "Failed"
    save(st, state_file)

    reconciled = reconcile(excel_path=mock_excel_schedule, state_file=state_file)
    assert reconciled["rows"]["D01-09:00"]["status"] == "Done"


def test_reconciliation_excel_pending_state_done_with_video_id_conflict(mock_excel_schedule, tmp_path):
    """Excel Pending, state Done with video id -> StateConflictError."""
    state_file = tmp_path / "test_state.json"
    st = load(state_file, mock_excel_schedule)

    # In Excel, D01-15:00 is Pending. Put status Done with video_id in state
    st["rows"]["D01-15:00"]["status"] = "Done"
    st["rows"]["D01-15:00"]["youtube_video_id"] = "ABC123XYZ"
    st["rows"]["D01-15:00"]["youtube_url"] = "https://youtube.com/shorts/ABC123XYZ"
    save(st, state_file)

    with pytest.raises(StateConflictError) as exc_info:
        reconcile(excel_path=mock_excel_schedule, state_file=state_file)

    assert "CONFLICT" in str(exc_info.value)
    assert "ABC123XYZ" in str(exc_info.value)


def test_reconciliation_excel_pending_state_in_progress_stale(mock_excel_schedule, tmp_path):
    """Excel Pending, state In progress older than 90m -> Failed with stale claim error, increment attempts."""
    state_file = tmp_path / "test_state.json"
    st = load(state_file, mock_excel_schedule)

    now = datetime(2026, 10, 21, 15, 0, 0, tzinfo=IST)
    claimed_time = now - timedelta(minutes=100)  # 100m old > 90m

    st["rows"]["D01-15:00"]["status"] = "In progress"
    st["rows"]["D01-15:00"]["claimed_at"] = claimed_time.isoformat()
    st["rows"]["D01-15:00"]["attempts"] = 0
    save(st, state_file)

    reconciled = reconcile(excel_path=mock_excel_schedule, state_file=state_file, now=now)
    r = reconciled["rows"]["D01-15:00"]
    assert r["status"] == "Failed"
    assert r["last_error"] == "stale in-progress claim"
    assert r["attempts"] == 1


def test_reconciliation_excel_pending_state_in_progress_active(mock_excel_schedule, tmp_path):
    """Excel Pending, state In progress newer than 90m -> RunInProgressError."""
    state_file = tmp_path / "test_state.json"
    st = load(state_file, mock_excel_schedule)

    now = datetime(2026, 10, 21, 15, 0, 0, tzinfo=IST)
    claimed_time = now - timedelta(minutes=15)  # 15m old < 90m

    st["rows"]["D01-15:00"]["status"] = "In progress"
    st["rows"]["D01-15:00"]["claimed_at"] = claimed_time.isoformat()
    save(st, state_file)

    with pytest.raises(RunInProgressError) as exc_info:
        reconcile(excel_path=mock_excel_schedule, state_file=state_file, now=now)

    assert "In progress" in str(exc_info.value)


def test_lifecycle_methods(tmp_path):
    """Tests claim, complete, fail, upsert, get, all_rows."""
    state_file = tmp_path / "lifecycle_state.json"
    save({"version": 1, "rows": {}}, state_file)

    # Upsert
    upsert("D02-15:00", state_file=state_file, day=2, topic="Test Topic", scheduled_at="2026-10-21T15:00:00+05:30")
    row = get("D02-15:00", state_file=state_file)
    assert row["topic"] == "Test Topic"
    assert row["status"] == "Pending"

    # Claim
    claim("D02-15:00", "job_123", state_file=state_file)
    row = get("D02-15:00", state_file=state_file)
    assert row["status"] == "In progress"
    assert row["job_id"] == "job_123"
    assert row["claimed_at"] is not None

    # Complete
    complete("D02-15:00", "vid_999", "https://youtube.com/shorts/vid_999", script_full="Full script text", state_file=state_file)
    row = get("D02-15:00", state_file=state_file)
    assert row["status"] == "Done"
    assert row["youtube_video_id"] == "vid_999"
    assert row["script_full"] == "Full script text"

    # Fail
    fail("D02-15:00", "Something went wrong", state_file=state_file)
    row = get("D02-15:00", state_file=state_file)
    assert row["last_error"] == "Something went wrong"
    assert row["attempts"] == 1
    assert row["status"] == "Pending"  # first attempt failed resets to Pending

    fail("D02-15:00", "Failed second time", state_file=state_file)
    row = get("D02-15:00", state_file=state_file)
    assert row["attempts"] == 2
    assert row["status"] == "Failed"  # 2 attempts -> Failed

    all_r = all_rows(state_file=state_file)
    assert "D02-15:00" in all_r


def test_excel_data_validation_persists(mock_excel_schedule):
    """Reading back saved Excel file confirms dropdown exists on column J rows 2-4."""
    wb = openpyxl.load_workbook(mock_excel_schedule)
    ws = wb.active
    dvs = list(ws.data_validations.dataValidation)
    assert len(dvs) > 0
    assert any("Done,Pending,In progress,Failed" in str(dv.formula1) for dv in dvs)
    assert any("J" in str(sq) for dv in dvs for sq in dv.sqref)
