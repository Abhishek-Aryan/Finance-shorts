import sys
import shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime
from zoneinfo import ZoneInfo
from storage.schedule_manager import get_all_topics_summary, select_due_row

IST = ZoneInfo("Asia/Kolkata")
fake_clock = datetime(2026, 10, 21, 15, 5, tzinfo=IST)

# Copy workbook
wb_copy = Path("data/backups/test_clock_verification.xlsx")
shutil.copy("data/publishing_schedule.xlsx", wb_copy)

# Verify first 5 rows
schedule = get_all_topics_summary()
for r in schedule[:5]:
    day_num = r['day']
    t_slot = r['time']
    topic = r['topic']
    status = r['status']
    print(f"Day {day_num} [{t_slot}] {topic} -> Status: {status}")

due = select_due_row(now_ist=fake_clock, excel_path=wb_copy)
print(f"\nClock set to: {fake_clock.isoformat()}")
print("Next due row selected:")
print(f"  Row Key:      {due['row_key']}")
print(f"  Day:          {due['day']}")
print(f"  Scheduled:    {due['scheduled_at']}")
print(f"  Topic:        {due['topic']}")
print(f"  Status:       {due['status']}")
print(f"  Attempts:     {due['attempts']}")

if wb_copy.exists():
    wb_copy.unlink()
