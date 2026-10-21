"""
Tests for Phase 3 and Phase 9: Publish Flow and Exit Codes (tests/test_publish_flow.py)
Tests:
- Call order using a spy: claim -> script -> TTS -> Veo -> compose -> verify -> idempotency -> upload -> state -> Excel
- Excel failure after upload -> exit code 4 and state Done
- Test mode never calls the upload client
- Dry-run never marks Done in Excel or state
- Budget cap -> exit code 5 and row stays Pending
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import openpyxl
import pytest

import config
from automation.schedule_runner import IST, publish_next_topic
from storage.schedule_manager import ExcelLockedError
from storage import state_store
from visuals.video_provider import BudgetCapReached


@pytest.fixture
def clean_flow_env(tmp_path):
    excel_path = tmp_path / "flow_schedule.xlsx"
    state_path = tmp_path / "flow_state.json"
    lock_path = tmp_path / ".flow.lock"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Publishing Schedule"
    headers = [
        "Day #", "Week", "Date", "Day of Week", "Publish Time",
        "Topic", "Category", "Key Learning Objective", "Script", "Posted?"
    ]
    ws.append(headers)
    ws.append([1, 1, "20-Oct-2026", "Tuesday", "9:00 AM", "Topic One", "Macro", "Obj 1", "", "Pending"])
    ws.append([1, 1, "20-Oct-2026", "Tuesday", "3:00 PM", "Topic Two", "Macro", "Obj 2", "", "Pending"])
    wb.save(excel_path)

    state_store.load(state_file=state_path, excel_file=excel_path)

    return {
        "excel_path": excel_path,
        "state_path": state_path,
        "lock_path": lock_path,
    }


def test_publish_flow_call_order(clean_flow_env, monkeypatch, tmp_path):
    """Verify call order using a spy: claim -> script -> TTS -> Veo -> compose -> verify -> idempotency -> upload -> state -> Excel."""
    env = clean_flow_env
    events = []

    # Spy claim
    orig_claim = state_store.claim
    def spy_claim(rk, *args, **kwargs):
        events.append("claim")
        return orig_claim(rk, *args, **kwargs)
    monkeypatch.setattr("storage.state_store.claim", spy_claim)

    # Spy pipeline internals
    mock_video = tmp_path / "mock.mp4"
    mock_video.write_bytes(b"mock" * 5000)

    def spy_pipeline(*args, **kwargs):
        events.append("pipeline_execute")
        return {
            "status": "composed",
            "video_path": str(mock_video),
            "topic": "Topic One",
            "script": {"full_voiceover": "Test script voiceover text", "video_title": "Topic One"},
        }
    monkeypatch.setattr("automation.schedule_runner.run_pro_pipeline", spy_pipeline)
    monkeypatch.setattr("automation.schedule_runner.verify_composed_video", lambda p: events.append("verify"))

    # Spy idempotency
    orig_idemp = state_store.load
    def spy_idemp(*args, **kwargs):
        events.append("idempotency_check")
        return orig_idemp(*args, **kwargs)
    monkeypatch.setattr("automation.schedule_runner.check_idempotency", lambda *a, **kw: (events.append("idempotency"), (None, None))[1])

    # Spy upload
    def spy_upload(*args, **kwargs):
        events.append("upload")
        return {
            "video_id": "REAL_V123",
            "youtube_video_id": "REAL_V123",
            "url": "https://youtube.com/shorts/REAL_V123",
            "status": "published",
        }
    monkeypatch.setattr("automation.schedule_runner.publish_composed", spy_upload)

    # Spy state complete
    orig_comp = state_store.complete
    def spy_complete(*args, **kwargs):
        events.append("state_complete")
        return orig_comp(*args, **kwargs)
    monkeypatch.setattr("storage.state_store.complete", spy_complete)

    # Spy mark_row_done
    orig_mrd = "storage.schedule_manager.mark_row_done"
    monkeypatch.setattr("automation.schedule_runner.mark_row_done", lambda *a, **kw: (events.append("excel_mark_done"), True)[1])

    monkeypatch.setattr(config, "PUBLISHING_MODE", "production")
    now_due = datetime(2026, 10, 20, 9, 30, tzinfo=IST)

    exit_code = publish_next_topic(
        dry_run=False,
        now=now_due,
        excel_path=env["excel_path"],
        state_file=env["state_path"],
        lock_file=env["lock_path"],
    )

    assert exit_code == 0
    expected_sequence = [
        "claim",
        "pipeline_execute",
        "verify",
        "idempotency",
        "upload",
        "state_complete",
        "excel_mark_done",
    ]
    assert events == expected_sequence


def test_excel_failure_after_upload_exit_4_and_state_done(clean_flow_env, monkeypatch, tmp_path):
    """When upload succeeds but Excel write fails, state must remain Done and exit code must be 4."""
    env = clean_flow_env
    mock_video = tmp_path / "mock.mp4"
    mock_video.write_bytes(b"mock" * 5000)

    monkeypatch.setattr("automation.schedule_runner.run_pro_pipeline", lambda *a, **kw: {
        "status": "composed",
        "video_path": str(mock_video),
        "topic": "Topic One",
        "script": {"full_voiceover": "VO text", "video_title": "Topic One"},
    })
    monkeypatch.setattr("automation.schedule_runner.verify_composed_video", lambda p: None)
    monkeypatch.setattr("automation.schedule_runner.publish_composed", lambda *a, **kw: {
        "video_id": "SAVED_YT_ID",
        "url": "https://youtube.com/shorts/SAVED_YT_ID",
        "status": "published",
    })
    monkeypatch.setattr("automation.schedule_runner.mark_row_done", MagicMock(side_effect=ExcelLockedError("Locked")))
    monkeypatch.setattr(config, "PUBLISHING_MODE", "production")

    now_due = datetime(2026, 10, 20, 9, 30, tzinfo=IST)
    exit_code = publish_next_topic(
        dry_run=False,
        now=now_due,
        excel_path=env["excel_path"],
        state_file=env["state_path"],
        lock_file=env["lock_path"],
    )

    assert exit_code == 4

    # Verify state was saved as Done with the video ID
    st = state_store.load(state_file=env["state_path"])
    row = st["rows"]["D01-09:00"]
    assert row["status"] == "Done"
    assert row["youtube_video_id"] == "SAVED_YT_ID"


def test_test_mode_never_calls_upload_client(clean_flow_env, monkeypatch, tmp_path):
    """In test mode, publish_composed produces mock ID and real YouTubePublisher is never invoked."""
    env = clean_flow_env
    mock_video = tmp_path / "mock.mp4"
    mock_video.write_bytes(b"mock" * 5000)

    monkeypatch.setattr("automation.schedule_runner.run_pro_pipeline", lambda *a, **kw: {
        "status": "composed",
        "video_path": str(mock_video),
        "topic": "Topic One",
        "script": {"full_voiceover": "VO", "video_title": "Topic One"},
    })
    monkeypatch.setattr("automation.schedule_runner.verify_composed_video", lambda p: None)

    upload_spy = MagicMock()
    monkeypatch.setattr("production.pro_pipeline.YouTubePublisher.upload", upload_spy)
    monkeypatch.setattr(config, "PUBLISHING_MODE", "test")

    now_due = datetime(2026, 10, 20, 9, 30, tzinfo=IST)
    exit_code = publish_next_topic(
        dry_run=False,
        now=now_due,
        excel_path=env["excel_path"],
        state_file=env["state_path"],
        lock_file=env["lock_path"],
    )

    assert exit_code == 0
    upload_spy.assert_not_called()

    # In test mode, video ID is TEST-...
    st = state_store.load(state_file=env["state_path"])
    assert "TEST-" in st["rows"]["D01-09:00"]["youtube_video_id"]


def test_dry_run_never_marks_done(clean_flow_env, monkeypatch):
    """In dry-run mode, neither Excel nor state store are updated to Done."""
    env = clean_flow_env
    monkeypatch.setattr("automation.schedule_runner.run_pro_pipeline", lambda *a, **kw: {
        "status": "composed",
        "video_path": "fake.mp4",
        "topic": "Topic One",
        "script": {"full_voiceover": "VO", "video_title": "Topic One"},
    })

    now_due = datetime(2026, 10, 20, 9, 30, tzinfo=IST)
    exit_code = publish_next_topic(
        dry_run=True,
        now=now_due,
        excel_path=env["excel_path"],
        state_file=env["state_path"],
        lock_file=env["lock_path"],
    )

    assert exit_code == 0

    st = state_store.load(state_file=env["state_path"])
    assert st["rows"]["D01-09:00"]["status"] == "Pending"

    wb = openpyxl.load_workbook(env["excel_path"])
    assert wb.active.cell(row=2, column=10).value == "Pending"


def test_budget_cap_exit_5_and_row_stays_pending(clean_flow_env, monkeypatch):
    """When budget cap is reached, returns exit code 5 and row remains Pending."""
    env = clean_flow_env

    def raise_cap(*args, **kwargs):
        raise BudgetCapReached("Per-run budget cap 60s exceeded")

    monkeypatch.setattr("automation.schedule_runner.run_pro_pipeline", raise_cap)

    now_due = datetime(2026, 10, 20, 9, 30, tzinfo=IST)
    exit_code = publish_next_topic(
        dry_run=False,
        now=now_due,
        excel_path=env["excel_path"],
        state_file=env["state_path"],
        lock_file=env["lock_path"],
    )

    assert exit_code == 5

    # Verify state row stayed Pending and attempts was NOT incremented
    st = state_store.load(state_file=env["state_path"])
    row = st["rows"]["D01-09:00"]
    assert row["status"] == "Pending"
    assert row["attempts"] == 0

    # Excel row remains Pending
    wb = openpyxl.load_workbook(env["excel_path"])
    assert wb.active.cell(row=2, column=10).value == "Pending"
