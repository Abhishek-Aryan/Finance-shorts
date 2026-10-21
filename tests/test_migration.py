"""
Migration test against a copy of the real publishing_schedule.xlsx.
Verifies that:
- Day 1 (all 3 rows: 09:00, 15:00, 20:00) and Day 2 09:00 remain Done.
- Day 2 15:00 ('EV/EBITDA vs P/E') is the next pending row.
- Total rows equal 42 (4 Done, 38 Pending).
- All 42 rows produce valid and stable row keys.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

from storage.schedule_manager import IST, select_due_row
from storage.state_store import load
from tools.audit_schedule import audit_schedule


def test_migration_against_real_schedule_copy(tmp_path):
    baseline_excel = Path("data/backups/publishing_schedule_baseline.xlsx")
    real_excel = baseline_excel if baseline_excel.exists() else Path("data/publishing_schedule.xlsx")
    assert real_excel.exists()

    copy_excel = tmp_path / "publishing_schedule_migrated.xlsx"
    shutil.copy(real_excel, copy_excel)

    # 1. Audit check
    audit_results = audit_schedule(copy_excel)
    assert audit_results["total_rows"] == 42
    assert audit_results["status_counts"].get("Done") == 4
    assert audit_results["status_counts"].get("Pending") == 38
    assert len(audit_results["duplicate_topics"]) == 0
    assert len(audit_results["unparseable_dates"]) == 0
    assert len(audit_results["unparseable_times"]) == 0

    # 2. State loading check
    copy_state = tmp_path / "schedule_state_migrated.json"
    st = load(state_file=copy_state, excel_file=copy_excel)
    assert len(st["rows"]) == 42

    # Check Day 1 rows are Done
    assert st["rows"]["D01-09:00"]["status"] == "Done"
    assert st["rows"]["D01-15:00"]["status"] == "Done"
    assert st["rows"]["D01-20:00"]["status"] == "Done"

    # Check Day 2 09:00 is Done
    assert st["rows"]["D02-09:00"]["status"] == "Done"

    # Check Day 2 15:00 is Pending
    assert st["rows"]["D02-15:00"]["status"] == "Pending"
    assert st["rows"]["D02-15:00"]["topic"] == "EV/EBITDA vs P/E"

    # 3. select_due_row at Day 2 15:05 IST selects Day 2 15:00
    now_ist = datetime(2026, 10, 21, 15, 5, 0, tzinfo=IST)
    selected = select_due_row(now_ist=now_ist, excel_path=copy_excel, state_file=copy_state)
    assert selected is not None
    assert selected["row_key"] == "D02-15:00"
    assert selected["topic"] == "EV/EBITDA vs P/E"
    assert selected["day"] == 2
