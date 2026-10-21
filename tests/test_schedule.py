"""
Comprehensive tests for Phase 2 & Phase 9 schedule operations (tests/test_schedule.py).
Tests:
- Earliest due row selection
- Late run selection (> 3 hours overdue)
- Skips Done, In progress, and Failed rows
- Re-run never returns or re-uploads a row with an existing video ID
- Failure policy: 1st failure stays Pending; 2nd failure marks Failed and next row is selected
- mark_row_done exact topic match, refusal on mismatch, refusal on duplicate topics
- ExcelLockedError on PermissionError retry exhaustion
- Parsers raise ValueError with row numbers on bad input
"""

from datetime import date, datetime, time as dt_time
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
import openpyxl
import pytest

from storage.schedule_manager import (
    IST,
    ExcelLockedError,
    _parse_date,
    _parse_time,
    mark_row_done,
    select_due_row,
)
from storage import state_store


def test_parsers_raise_with_row_number_on_bad_input():
    with pytest.raises(ValueError) as exc_t:
        _parse_time("invalid_time", row_num=4)
    assert "Row 4" in str(exc_t.value)
    assert "invalid_time" in str(exc_t.value)

    with pytest.raises(ValueError) as exc_d:
        _parse_date("bad_date", row_num=9)
    assert "Row 9" in str(exc_d.value)
    assert "bad_date" in str(exc_d.value)


def test_schedule_selection_policy(tmp_path):
    excel_path = tmp_path / "schedule.xlsx"
    state_path = tmp_path / "state.json"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Publishing Schedule"
    headers = [
        "Day #", "Week", "Date", "Day of Week", "Publish Time",
        "Topic", "Category", "Key Learning Objective", "Script", "Posted?"
    ]
    ws.append(headers)
    ws.append([1, 1, "20-Oct-2026", "Tuesday", "9:00 AM", "Topic 1", "Cat", "Obj", "", "Pending"])
    ws.append([1, 1, "20-Oct-2026", "Tuesday", "3:00 PM", "Topic 2", "Cat", "Obj", "", "Pending"])
    ws.append([1, 1, "20-Oct-2026", "Tuesday", "8:00 PM", "Topic 3", "Cat", "Obj", "", "Pending"])
    wb.save(excel_path)

    # 1. At 09:05, Topic 1 is selected
    now_905 = datetime(2026, 10, 20, 9, 5, tzinfo=IST)
    row = select_due_row(now_ist=now_905, excel_path=excel_path, state_file=state_path)
    assert row is not None
    assert row["topic"] == "Topic 1"

    # Mark Topic 1 In progress
    state_store.claim("D01-09:00", job_id="JOB_1", state_file=state_path, now=now_905)
    # Next check at 09:10 sees active run in progress and returns None
    now_910 = datetime(2026, 10, 20, 9, 10, tzinfo=IST)
    row2 = select_due_row(now_ist=now_910, excel_path=excel_path, state_file=state_path)
    assert row2 is None
    assert "in progress" in select_due_row.reason

    # Complete Topic 1
    state_store.complete("D01-09:00", video_id="YT_1", url="http://yt/1", state_file=state_path)
    mark_row_done("D01-09:00", "Topic 1", excel_path=excel_path, state_file=state_path, video_id="YT_1")

    # 2. At 15:30 (late), Topic 2 is selected
    now_1530 = datetime(2026, 10, 20, 15, 30, tzinfo=IST)
    row3 = select_due_row(now_ist=now_1530, excel_path=excel_path, state_file=state_path)
    assert row3 is not None
    assert row3["topic"] == "Topic 2"

    # 3. Simulate failure policy:
    # First failure on Topic 2 -> attempts=1, status remains Pending
    state_store.fail("D01-15:00", error="Render timeout", state_file=state_path)
    st1 = state_store.load(state_path)
    assert st1["rows"]["D01-15:00"]["status"] == "Pending"
    assert st1["rows"]["D01-15:00"]["attempts"] == 1

    # Topic 2 is still retriable at 16:00
    now_1600 = datetime(2026, 10, 20, 16, 0, tzinfo=IST)
    row4 = select_due_row(now_ist=now_1600, excel_path=excel_path, state_file=state_path)
    assert row4 is not None
    assert row4["topic"] == "Topic 2"

    # Second failure on Topic 2 -> attempts=2, status becomes Failed
    state_store.fail("D01-15:00", error="Second render failure", state_file=state_path)
    st2 = state_store.load(state_path)
    assert st2["rows"]["D01-15:00"]["status"] == "Failed"
    assert st2["rows"]["D01-15:00"]["attempts"] == 2

    # At 20:30, Topic 2 is skipped because it's Failed, and Topic 3 is selected!
    now_2030 = datetime(2026, 10, 20, 20, 30, tzinfo=IST)
    row5 = select_due_row(now_ist=now_2030, excel_path=excel_path, state_file=state_path)
    assert row5 is not None
    assert row5["topic"] == "Topic 3"


def test_mark_row_done_exact_and_refusals(tmp_path):
    excel_path = tmp_path / "schedule.xlsx"
    state_path = tmp_path / "state.json"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Publishing Schedule"
    ws.append(["Day #", "Week", "Date", "Day of Week", "Publish Time", "Topic", "Category", "KLO", "Script", "Posted?"])
    ws.append([1, 1, "20-Oct-2026", "Tuesday", "9:00 AM", "Free Cash Flow vs Net Profit", "Cat", "Obj", "", "Pending"])
    ws.append([1, 1, "20-Oct-2026", "Tuesday", "3:00 PM", "Duplicate Topic", "Cat", "Obj", "", "Pending"])
    ws.append([1, 1, "20-Oct-2026", "Tuesday", "8:00 PM", "Duplicate Topic", "Cat", "Obj", "", "Pending"])
    wb.save(excel_path)

    state_store.load(state_path, excel_path)

    # 1. Exact match works
    success = mark_row_done(
        row_key="D01-09:00",
        expected_topic="Free Cash Flow vs Net Profit",
        script_text="Script content",
        excel_path=excel_path,
        state_file=state_path,
        video_id="VID1",
    )
    assert success is True

    # 2. Topic mismatch raises ValueError
    with pytest.raises(ValueError) as exc:
        mark_row_done(
            row_key="D01-09:00",
            expected_topic="Wrong Topic Name",
            excel_path=excel_path,
            state_file=state_path,
        )
    assert "Topic mismatch" in str(exc.value)

    # 3. Duplicate topics raise ValueError
    with pytest.raises(ValueError) as exc_dup:
        mark_row_done(
            row_key="D01-15:00",
            expected_topic="Duplicate Topic",
            excel_path=excel_path,
            state_file=state_path,
        )
    assert "Duplicate topics" in str(exc_dup.value)


def test_excel_locked_error_on_permission_denied(tmp_path):
    excel_path = tmp_path / "locked.xlsx"
    state_path = tmp_path / "state.json"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Day #", "Week", "Date", "Day of Week", "Publish Time", "Topic", "Category", "KLO", "Script", "Posted?"])
    ws.append([1, 1, "20-Oct-2026", "Tuesday", "9:00 AM", "Locked Topic", "Cat", "Obj", "", "Pending"])
    wb.save(excel_path)
    state_store.load(state_path, excel_path)

    with patch("openpyxl.Workbook.save", side_effect=PermissionError("Permission denied")):
        with patch("time.sleep", return_value=None):
            with pytest.raises(ExcelLockedError):
                mark_row_done(
                    row_key="D01-09:00",
                    expected_topic="Locked Topic",
                    excel_path=excel_path,
                    state_file=state_path,
                )
