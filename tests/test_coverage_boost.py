"""
Tests specifically designed to achieve >=85% test coverage across storage/ and automation/.
"""

import os
from datetime import datetime, date, time as dt_time
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import pytest
import openpyxl

import config
from storage import schedule_manager, state_store, spreadsheet_manager, database
from automation import schedule_runner, run_lock

IST = ZoneInfo("Asia/Kolkata")


def test_storage_schedule_manager_helpers(tmp_path, monkeypatch):
    """Test helper parsing and status formatting functions in schedule_manager."""
    # datetime and date parsing
    dt_val = datetime(2026, 10, 20, 9, 0)
    assert schedule_manager._parse_time(dt_val) == dt_time(9, 0)
    assert schedule_manager._parse_date(dt_val) == date(2026, 10, 20)
    assert schedule_manager._parse_date(date(2026, 10, 20)) == date(2026, 10, 20)
    assert schedule_manager._parse_date("2026-10-20") == date(2026, 10, 20)
    assert schedule_manager._parse_date("20/10/2026") == date(2026, 10, 20)
    assert schedule_manager._parse_time("09:00:00") == dt_time(9, 0)
    assert schedule_manager._parse_time("09:00:00 AM") == dt_time(9, 0)

    # format_status_cell
    wb = openpyxl.Workbook()
    ws = wb.active
    c1 = ws.cell(row=2, column=1)
    schedule_manager.format_status_cell(c1, "Failed", 2)
    assert c1.value == "Failed"
    c2 = ws.cell(row=3, column=1)
    schedule_manager.format_status_cell(c2, "Pending", 3)
    assert c2.value == "Pending"

    # get_all_topics_summary
    summary = schedule_manager.get_all_topics_summary()
    assert len(summary) >= 40
    assert summary[0]["day"] == 1

    # load_curriculum fallback
    curriculum = schedule_manager.load_curriculum()
    assert isinstance(curriculum, list)

    # create_schedule_excel to a custom path
    custom_excel = tmp_path / "custom_sched.xlsx"
    monkeypatch.setattr(schedule_manager, "SCHEDULE_FILE", custom_excel)
    created = schedule_manager.create_schedule_excel()
    assert created.exists()


def test_storage_spreadsheet_manager(tmp_path, monkeypatch):
    """Exercise spreadsheet_manager create_workbook, read_topics, update_topic, and sync."""
    excel_path = tmp_path / "finance_content_queue.xlsx"
    monkeypatch.setattr(config, "EXCEL_FILE", excel_path)
    
    # Run create_workbook
    spreadsheet_manager.create_workbook()
    assert excel_path.exists()

    # Re-run create_workbook to trigger backup branch
    spreadsheet_manager.create_workbook()

    # Read topics
    topics = spreadsheet_manager.read_topics()
    assert len(topics) == 100
    assert topics[0]["topic_id"] == "FIN001"

    # Update topic in Excel
    spreadsheet_manager.update_topic_in_excel("FIN001", {"status": "READY", "video_title": "Test Title"})
    updated = spreadsheet_manager.read_topics()
    assert updated[0]["status"] == "READY"

    # Sync db to excel
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(config, "SQLITE_DB", db_path)
    database.init_db()
    spreadsheet_manager.sync_db_to_excel()


def test_state_store_edge_cases(tmp_path, monkeypatch):
    """Test state_store corrupted file, claim edge cases, and unknown keys."""
    state_file = tmp_path / "state_test.json"
    
    # Corrupted json
    state_file.write_text("{corrupt json", encoding="utf-8")
    loaded = state_store.load(state_file)
    assert loaded["version"] == 1
    assert "rows" in loaded

    # Fail unknown key
    state_store.fail("D99-99:99", "random error", state_file=state_file)


def test_schedule_runner_print_status(capsys):
    """Test print_schedule_status output."""
    schedule_runner.print_schedule_status()
    out = capsys.readouterr().out
    assert "FINANCE SHORTS PRO" in out
    assert "Total Topics" in out


def test_schedule_runner_publish_next_branches(tmp_path, monkeypatch):
    """Test publish_next_topic branches: config err, lock held, conflict, nothing due, excel fail."""
    # Isolate Excel and State to tmp_path
    excel_path = tmp_path / "sched.xlsx"
    state_path = tmp_path / "state.json"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Publishing Schedule"
    ws.append(["Day #", "Week", "Date", "Day of Week", "Publish Time", "Topic", "Category", "Objective", "Script", "Posted?"])
    ws.append([1, 1, "20-Oct-2026", "Tuesday", "9:00 AM", "Topic 1", "Basics", "Obj", "Script", "Pending"])
    wb.save(excel_path)

    # 1. Config error (Exit code 2 in production mode)
    monkeypatch.setattr(config, "PUBLISHING_MODE", "production")
    with patch("automation.schedule_runner.config.validate", return_value=["YOUTUBE_CLIENT_SECRETS_FILE"]):
        assert schedule_runner.publish_next_topic(excel_path=excel_path, state_file=state_path) == 2

    # 2. Lock held (Exit code 0)
    with patch("automation.schedule_runner.config.validate", return_value=[]), \
         patch("automation.schedule_runner.acquire_run_lock", side_effect=run_lock.LockHeld("Locked")):
        assert schedule_runner.publish_next_topic(excel_path=excel_path, state_file=state_path) == 0

    # 3. State conflict (Exit code 3)
    
    st = {
        "version": 1,
        "updated_at": "2026-10-21T09:00:00+05:30",
        "rows": {
            "D01-09:00": {
                "row_index": 2, "day": 1, "scheduled_at": "2026-10-20T09:00:00+05:30",
                "topic": "Topic 1", "status": "Done", "attempts": 0, "youtube_video_id": "vid123",
                "youtube_url": None, "published_at": None, "last_error": None, "script_full": None
            }
        }
    }
    state_store.save(st, state_path)

    with patch("automation.schedule_runner.config.validate", return_value=[]), \
         patch("automation.schedule_runner.acquire_run_lock"):
        code = schedule_runner.publish_next_topic(excel_path=excel_path, state_file=state_path)
        assert code == 3

    # 4. Nothing due (Exit code 0)
    past_now = datetime(2026, 10, 19, 8, 0, tzinfo=IST)
    st["rows"]["D01-09:00"]["status"] = "Pending"
    st["rows"]["D01-09:00"]["youtube_video_id"] = None
    state_store.save(st, state_path)

    with patch("automation.schedule_runner.config.validate", return_value=[]), \
         patch("automation.schedule_runner.acquire_run_lock"):
        code = schedule_runner.publish_next_topic(now=past_now, excel_path=excel_path, state_file=state_path)
        assert code == 0


def test_schedule_runner_daemon_single_iteration(tmp_path, monkeypatch):
    """Test run_trigger_daemon execution and stop."""
    state_file = tmp_path / "daemon_state.json"
    fake_state = {
        "version": 1,
        "updated_at": "2026-10-21T09:00:00+05:30",
        "rows": {},
        "daemon": {"fired": {}}
    }
    state_store.save(fake_state, state_file=state_file)

    monkeypatch.setattr(state_store, "DEFAULT_STATE_FILE", state_file)
    monkeypatch.setattr(config, "PUBLISH_TIMES", ["09:00"])

    called = []
    def fake_publish(dry_run=False, now=None):
        called.append(True)
        return 0

    monkeypatch.setattr(schedule_runner, "publish_next_topic", fake_publish)
    
    def fake_sleep(sec):
        raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", fake_sleep)

    fixed_now = datetime(2026, 10, 21, 9, 5, tzinfo=IST)
    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(schedule_runner, "datetime", FakeDateTime)
    schedule_runner.run_trigger_daemon(dry_run=True, poll_interval_sec=1)

    assert len(called) == 1


def test_schedule_runner_main_and_status(capsys):
    """Test __main__ CLI handling and print_schedule_status with a due topic."""
    import runpy
    with patch("sys.argv", ["schedule_runner.py"]), pytest.raises(SystemExit) as exc:
        runpy.run_module("automation.schedule_runner", run_name="__main__")
    assert exc.value.code == 0

    with patch("automation.schedule_runner.select_due_row", return_value={"day": 1, "row_key": "D01-09:00", "topic": "Yield Curve", "category": "Macro"}):
        schedule_runner.print_schedule_status()
        out = capsys.readouterr().out
        assert "NEXT UP: Day 1 [D01-09:00] Yield Curve" in out


def test_schedule_runner_more_branches(tmp_path, monkeypatch, capsys):
    """Test naive now, RunInProgressError, and status empty branches."""
    excel_path = tmp_path / "sched.xlsx"
    state_path = tmp_path / "state.json"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Publishing Schedule"
    ws.append(["Day #", "Week", "Date", "Day of Week", "Publish Time", "Topic", "Category", "Objective", "Script", "Posted?"])
    ws.append([1, 1, "20-Oct-2026", "Tuesday", "9:00 AM", "Topic 1", "Basics", "Obj", "Script", "Pending"])
    wb.save(excel_path)

    # 1. RunInProgressError returns 0
    with patch("automation.schedule_runner.config.validate", return_value=[]), \
         patch("automation.schedule_runner.acquire_run_lock"), \
         patch("automation.schedule_runner.state_store.reconcile", side_effect=state_store.RunInProgressError("Active")):
        code = schedule_runner.publish_next_topic(
            now=datetime(2026, 10, 20, 9, 0),  # naive datetime to test tz replacement
            excel_path=excel_path,
            state_file=state_path,
        )
        assert code == 0

    # 2. print_schedule_status with next_slot
    with patch("automation.schedule_runner.select_due_row", return_value=None):
        setattr(schedule_runner.select_due_row, "next_scheduled_at", "2026-10-21 15:00")
        schedule_runner.print_schedule_status(excel_path=excel_path, state_file=state_path)
        out = capsys.readouterr().out
        assert "Next scheduled slot is at" in out

        # When next_slot is None
        setattr(schedule_runner.select_due_row, "next_scheduled_at", None)
        schedule_runner.print_schedule_status(excel_path=excel_path, state_file=state_path)
        out2 = capsys.readouterr().out
        assert "All topics in the curriculum have been completed!" in out2

    # 3. CLI status
    import runpy
    with patch("sys.argv", ["schedule_runner.py", "status"]):
        runpy.run_module("automation.schedule_runner", run_name="__main__")
        out3 = capsys.readouterr().out
        assert "FINANCE SHORTS PRO" in out3
