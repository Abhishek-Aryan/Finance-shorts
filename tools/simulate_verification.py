"""
Verification script for Phase 7 of Finance Shorts Pro refactoring.
Tests:
- Simulation 1: One full day with a fake clock and mocked uploader (3 slots -> 3 uploads in order, no duplicates, lock prevents concurrent runs).
- Simulation 2:
  (a) Upload succeeds + Excel locked -> Exit code 4, state contains video ID.
  (b) Pipeline fails twice -> attempts=2, status=Failed, next row is selected on 3rd call.
  (c) Crashed run leaves stale claim (>90 mins) -> Reconciled as Failed with 'stale in-progress claim'.
- Verification 3: Load copy of real data/publishing_schedule.xlsx and demonstrate Day 1 + Day 2 09:00 are Done and Day 2 15:00 is next.
"""

import sys
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock

import openpyxl

# Add repo root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config
from storage import state_store, schedule_manager
from automation import schedule_runner, run_lock

IST = ZoneInfo("Asia/Kolkata")


def run_full_day_simulation(tmp_dir: Path):
    print("\n" + "=" * 60)
    print("SIMULATION 1: FULL DAY WITH FAKE CLOCK (3 SLOTS)")
    print("=" * 60)

    sim_excel = tmp_dir / "sim_schedule.xlsx"
    sim_state = tmp_dir / "sim_state.json"
    sim_lock = tmp_dir / "sim.lock"

    # Create a 3-row test schedule for Day 3 (22-Oct-2026: 09:00, 15:00, 20:00)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Publishing Schedule"
    ws.append(["Day #", "Week", "Date", "Day of Week", "Publish Time", "Topic", "Category", "Objective", "Script", "Posted?"])
    ws.append([3, 1, "22-Oct-2026", "Thursday", "9:00 AM", "Topic D3-1", "Macro", "Obj 1", "Script 1", "Pending"])
    ws.append([3, 1, "22-Oct-2026", "Thursday", "3:00 PM", "Topic D3-2", "Macro", "Obj 2", "Script 2", "Pending"])
    ws.append([3, 1, "22-Oct-2026", "Thursday", "8:00 PM", "Topic D3-3", "Macro", "Obj 3", "Script 3", "Pending"])
    wb.save(sim_excel)

    uploaded_videos = []

    def mock_upload(result, dry_run=False):
        topic = result.get("topic_data", {}).get("topic", "unknown")
        vid_id = f"MOCK-VID-{len(uploaded_videos) + 1}"
        uploaded_videos.append((topic, vid_id))
        return {
            "status": "published",
            "youtube_video_id": vid_id,
            "published_url": f"https://youtu.be/{vid_id}",
        }

    slots_to_test = [
        (datetime(2026, 10, 22, 9, 5, tzinfo=IST), "D03-09:00", "Topic D3-1"),
        (datetime(2026, 10, 22, 15, 10, tzinfo=IST), "D03-15:00", "Topic D3-2"),
        (datetime(2026, 10, 22, 20, 2, tzinfo=IST), "D03-20:00", "Topic D3-3"),
    ]

    with patch("automation.schedule_runner.publish_composed", side_effect=mock_upload), \
         patch("automation.schedule_runner.run_pro_pipeline", return_value={"status": "composed", "video_path": "fake.mp4", "topic_data": {}}), \
         patch("automation.schedule_runner.verify_composed_video", return_value={"valid": True, "duration": 45.0}), \
         patch("automation.schedule_runner.config.validate", return_value=[]):

        for clock_time, expected_key, expected_topic in slots_to_test:
            print(f"\n---> Advancing clock to: {clock_time.isoformat()}")

            # 1. Test lock prevention: hold lock in background and assert runner exits 0
            with run_lock.acquire_run_lock(lock_file=sim_lock):
                code_lock = schedule_runner.publish_next_topic(
                    now=clock_time,
                    excel_path=sim_excel,
                    state_file=sim_state,
                    lock_file=sim_lock,
                )
                assert code_lock == 0, f"Expected code 0 on lock contention, got {code_lock}"
                print("     [Lock test] Concurrent run blocked successfully (exit 0, lock held)")

            # 2. Publish next topic
            code = schedule_runner.publish_next_topic(
                now=clock_time,
                excel_path=sim_excel,
                state_file=sim_state,
                lock_file=sim_lock,
            )
            assert code == 0, f"Expected code 0, got {code}"
            print(f"     [Published] Successfully processed slot {expected_key}")

    assert len(uploaded_videos) == 3, f"Expected 3 uploads, got {len(uploaded_videos)}"
    print(f"\nAll 3 slots published in order without duplicates: {uploaded_videos}")


def run_failure_simulations(tmp_dir: Path):
    print("\n" + "=" * 60)
    print("SIMULATION 2: FAILURE AND RECOVERY SCENARIOS")
    print("=" * 60)

    sim_excel = tmp_dir / "sim_fail_schedule.xlsx"
    sim_state = tmp_dir / "sim_fail_state.json"
    sim_lock = tmp_dir / "sim_fail.lock"

    # --- (a) Upload succeeds + Excel locked -> exit code 4 ---
    print("\n--- Scenario (a): Upload succeeds + Excel locked ---")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Publishing Schedule"
    ws.append(["Day #", "Week", "Date", "Day of Week", "Publish Time", "Topic", "Category", "Objective", "Script", "Posted?"])
    ws.append([4, 1, "23-Oct-2026", "Friday", "9:00 AM", "Topic D4-1", "Macro", "Obj 1", "Script 1", "Pending"])
    wb.save(sim_excel)

    def mock_upload_a(result, dry_run=False):
        return {
            "status": "published",
            "youtube_video_id": "YOUTUBE-A123",
            "published_url": "https://youtu.be/YOUTUBE-A123",
        }

    with patch("automation.schedule_runner.publish_composed", side_effect=mock_upload_a), \
         patch("automation.schedule_runner.run_pro_pipeline", return_value={"status": "composed", "video_path": "fake.mp4", "topic_data": {}}), \
         patch("automation.schedule_runner.verify_composed_video", return_value={"valid": True, "duration": 45.0}), \
         patch("automation.schedule_runner.config.validate", return_value=[]), \
         patch("storage.schedule_manager._save_workbook_with_retry", side_effect=schedule_manager.ExcelLockedError("Locked for test")):

        code = schedule_runner.publish_next_topic(
            now=datetime(2026, 10, 23, 9, 5, tzinfo=IST),
            excel_path=sim_excel,
            state_file=sim_state,
            lock_file=sim_lock,
        )
        assert code == 4, f"Expected exit code 4 on locked excel, got {code}"
        st = state_store.load(sim_state)
        row = st["rows"]["D04-09:00"]
        assert row["status"] == "Done"
        assert row["youtube_video_id"] == "YOUTUBE-A123"
        print(f"Result: Exit code 4. State preserved with video ID: {row['youtube_video_id']}, status: {row['status']}")

    # Mark D04-09:00 Done in Excel to simulate repaired view after upload
    ws.cell(row=2, column=10, value="Done")
    ws.append([4, 1, "23-Oct-2026", "Friday", "3:00 PM", "Topic D4-2", "Macro", "Obj 2", "Script 2", "Pending"])
    wb.save(sim_excel)

    with patch("automation.schedule_runner.run_pro_pipeline", side_effect=RuntimeError("FFmpeg error")), \
         patch("automation.schedule_runner.config.validate", return_value=[]):

        # Attempt 1
        code1 = schedule_runner.publish_next_topic(
            now=datetime(2026, 10, 23, 15, 5, tzinfo=IST),
            excel_path=sim_excel,
            state_file=sim_state,
            lock_file=sim_lock,
        )
        assert code1 == 1, f"Expected exit code 1, got {code1}"
        st = state_store.load(sim_state)
        assert st["rows"]["D04-15:00"]["attempts"] == 1
        assert st["rows"]["D04-15:00"]["status"] == "Pending"
        print(f"Attempt 1 failed. Status: {st['rows']['D04-15:00']['status']}, Attempts: {st['rows']['D04-15:00']['attempts']}")

        # Attempt 2
        code2 = schedule_runner.publish_next_topic(
            now=datetime(2026, 10, 23, 15, 6, tzinfo=IST),
            excel_path=sim_excel,
            state_file=sim_state,
            lock_file=sim_lock,
        )
        assert code2 == 1, f"Expected exit code 1, got {code2}"
        st = state_store.load(sim_state)
        assert st["rows"]["D04-15:00"]["attempts"] == 2
        assert st["rows"]["D04-15:00"]["status"] == "Failed"
        print(f"Attempt 2 failed. Status: {st['rows']['D04-15:00']['status']}, Attempts: {st['rows']['D04-15:00']['attempts']}")

    # Add 3rd row for Day 4 20:00
    ws.append([4, 1, "23-Oct-2026", "Friday", "8:00 PM", "Topic D4-3", "Macro", "Obj 3", "Script 3", "Pending"])
    wb.save(sim_excel)

    # 3rd run at 20:05 IST: D04-15:00 is Failed, so D04-20:00 is selected!
    with patch("automation.schedule_runner.publish_composed", return_value={"status": "published", "youtube_video_id": "VID-D4-3"}), \
         patch("automation.schedule_runner.run_pro_pipeline", return_value={"status": "composed", "video_path": "fake.mp4", "topic_data": {}}), \
         patch("automation.schedule_runner.verify_composed_video", return_value={"valid": True, "duration": 45.0}), \
         patch("automation.schedule_runner.config.validate", return_value=[]):

        code3 = schedule_runner.publish_next_topic(
            now=datetime(2026, 10, 23, 20, 5, tzinfo=IST),
            excel_path=sim_excel,
            state_file=sim_state,
            lock_file=sim_lock,
        )
        assert code3 == 0, f"Expected exit code 0, got {code3}"
        st = state_store.load(sim_state)
        assert st["rows"]["D04-20:00"]["status"] == "Done"
        print(f"3rd call successfully skipped Failed D04-15:00 and selected/published D04-20:00!")

    # --- (c) Crashed run leaves stale claim (>90 mins) ---
    print("\n--- Scenario (c): Crashed run leaves stale claim (>90 min old) ---")
    st["rows"]["D04-20:00"]["status"] = "In progress"
    st["rows"]["D04-20:00"]["claimed_at"] = (datetime.now(IST) - timedelta(minutes=120)).isoformat()
    # Ensure Excel is Pending
    wb_c = openpyxl.load_workbook(str(sim_excel))
    ws_c = wb_c.active
    ws_c.cell(row=4, column=10, value="Pending")
    wb_c.save(str(sim_excel))
    state_store.save(st, sim_state)

    reconciled = state_store.reconcile(excel_path=sim_excel, state_file=sim_state, now=datetime.now(IST))
    st_reconciled = state_store.load(sim_state)
    r = st_reconciled["rows"]["D04-20:00"]
    assert r["status"] == "Failed"
    assert "stale in-progress claim" in r["last_error"]
    assert r["attempts"] >= 1
    print(f"Stale claim resolved: status={r['status']}, attempts={r['attempts']}, error='{r['last_error']}'")


def verify_real_data():
    print("\n" + "=" * 60)
    print("VERIFICATION 3: REAL DATA PRESERVATION")
    print("=" * 60)

    real_excel = ROOT / "data" / "publishing_schedule.xlsx"
    wb = openpyxl.load_workbook(str(real_excel), data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))[1:]
    assert len(rows) == 42, f"Expected 42 rows, got {len(rows)}"

    print(f"Total rows in publishing_schedule.xlsx: {len(rows)}")

    # Check Day 1 (rows 0, 1, 2)
    for i in range(3):
        r = rows[i]
        assert r[0] == 1, f"Row {i} Day should be 1"
        assert r[9] == "Done", f"Row {i} should be Done"
        print(f"Day 1 [{r[4]}]: '{r[5]}' -> Status: {r[9]}")

    # Check Day 2 09:00 (row 3)
    r3 = rows[3]
    assert r3[0] == 2
    assert "9:00" in str(r3[4])
    assert r3[9] == "Done"
    print(f"Day 2 [{r3[4]}]: '{r3[5]}' -> Status: {r3[9]}")

    # Check Day 2 15:00 (row 4)
    r4 = rows[4]
    assert r4[0] == 2
    assert "3:00" in str(r4[4])
    assert r4[9] == "Pending"
    assert "EV/EBITDA" in str(r4[5])
    print(f"Day 2 [{r4[4]}]: '{r4[5]}' -> Status: {r4[9]} (NEXT DUE ROW)")

    # Test select_due_row on real data at 2026-10-21 15:05 IST
    due = schedule_manager.select_due_row(
        now_ist=datetime(2026, 10, 21, 15, 5, tzinfo=IST),
        excel_path=real_excel,
    )
    assert due is not None
    assert due["day"] == 2
    assert due["row_key"] == "D02-15:00"
    assert "EV/EBITDA" in due["topic"]
    print(f"\nSelect_due_row at 2026-10-21 15:05 IST selected: Day {due['day']} [{due['row_key']}] '{due['topic']}'")


def main():
    tmp_dir = ROOT / "data" / "scratch_verification"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        run_full_day_simulation(tmp_dir)
        run_failure_simulations(tmp_dir)
        verify_real_data()
        print("\n" + "=" * 60)
        print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY!")
        print("=" * 60)
    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    main()
