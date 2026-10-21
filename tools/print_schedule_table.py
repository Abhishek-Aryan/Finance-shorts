"""
Finance Shorts Pro - 14-Day Schedule Timing Table Generator.
Reads data/schedule_state.json and generates a markdown table with Date, Day #,
IST Slot, UTC Cron Time, Row Key, and Topic.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Add repo root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config
from storage import state_store

IST = ZoneInfo("Asia/Kolkata")

CRON_UTC_MAP = {
    "09:00": "03:30 UTC (`30 3 * * *`)",
    "15:00": "09:30 UTC (`30 9 * * *`)",
    "20:00": "14:30 UTC (`30 14 * * *`)",
}


def generate_schedule_table(state_file: Path | None = None) -> str:
    """Generates the full markdown timing table from state store."""
    st = state_store.load(state_file=state_file)
    rows = st.get("rows", {})

    sorted_rows = sorted(
        rows.items(),
        key=lambda item: (item[1].get("day", 0), item[1].get("scheduled_at", ""))
    )

    lines = [
        "| Day # | Date | IST Slot | UTC Cron Time | Row Key | Topic | Status |",
        "|:---:|:---:|:---:|:---|:---:|:---|:---:|",
    ]

    for rk, r in sorted_rows:
        day = r.get("day")
        sched_str = r.get("scheduled_at", "")
        topic = r.get("topic", "")
        status = r.get("status", "Pending")

        dt_obj = datetime.fromisoformat(sched_str) if sched_str else None
        date_display = dt_obj.strftime("%d-%b-%Y") if dt_obj else "Unknown"
        time_display = dt_obj.strftime("%H:%M") if dt_obj else "09:00"

        cron_display = CRON_UTC_MAP.get(time_display, "Custom")
        status_display = "Done" if status == "Done" else status

        lines.append(
            f"| Day {day:02d} | {date_display} | {time_display} IST | {cron_display} | `{rk}` | {topic} | {status_display} |"
        )

    return "\n".join(lines)


def main() -> None:
    table = generate_schedule_table()
    print(table)


if __name__ == "__main__":
    main()
