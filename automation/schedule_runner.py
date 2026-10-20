"""
Finance Shorts Pro - Autonomous Schedule Trigger Runner
Monitors the 14-day publishing schedule (data/publishing_schedule.xlsx).
Runs continuously or as a cron trigger to:
1. Identify the next due topic according to IST time (09:00, 15:00, 20:00).
2. Generate script (MiniMax M3.1 Flash) + TTS (Andrew Neural) + HeyGen AI video clips.
3. Compose final cinematic vertical Short.
4. Publish directly to connected YouTube channel.
5. Update 'Posted?' column from 'Pending' to 'Done' in the Excel sheet.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
import pytz

import config
from production.pro_pipeline import run_pro_pipeline
from storage.schedule_manager import (
    get_next_pending_topic,
    get_all_topics_summary,
    mark_topic_done,
    create_schedule_excel,
)

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")


def print_schedule_status() -> None:
    """Prints a beautiful CLI summary of the current schedule and status."""
    topics = get_all_topics_summary()
    if not topics:
        create_schedule_excel()
        topics = get_all_topics_summary()

    total = len(topics)
    done = sum(1 for t in topics if "done" in str(t.get("status", "")).lower())
    pending = total - done

    print("\n" + "=" * 70)
    print(f"  FINANCE SHORTS PRO — 14-DAY PUBLISHING SCHEDULE STATUS")
    print("=" * 70)
    print(f"  Total Topics: {total} | Done: {done} | Pending: {pending}")
    print("-" * 70)
    print(f"  {'Day':<5} {'Time':<10} {'Topic':<38} {'Status':<10}")
    print("-" * 70)

    for t in topics:
        status_sym = "✅ Done" if "done" in str(t.get("status", "")).lower() else "⏳ Pending"
        print(f"  D{t['day']:<4} {t['time']:<10} {t['topic'][:36]:<38} {status_sym}")

    print("-" * 70)
    next_topic = get_next_pending_topic()
    if next_topic:
        print(f"  >>> NEXT UP: Day {next_topic['day']} [{next_topic['time_str']}] {next_topic['topic']}")
        print(f"      Category: {next_topic['category']}")
        print(f"      Objective: {next_topic['objective'][:60]}...")
    else:
        print("  🎉 All 42 topics in the curriculum have been published!")
    print("=" * 70 + "\n")


def publish_next_topic(dry_run: bool = False) -> dict:
    """
    Finds the very next pending topic in the Excel schedule, runs the full
    cinematic pipeline, uploads it to YouTube, and marks it Done in Excel.
    """
    next_topic = get_next_pending_topic()
    if not next_topic:
        logger.info("No pending topics left in the schedule!")
        return {"status": "all_completed"}

    topic_title = next_topic["topic"]
    category = next_topic["category"]
    objective = next_topic["objective"]
    day_num = next_topic["day"]
    time_str = next_topic["time_str"]

    logger.info("Starting pipeline for NEXT topic: Day %s [%s] - %s", day_num, time_str, topic_title)
    print(f"\n🚀 Running Pro Pipeline for: Day {day_num} [{time_str}] {topic_title}...")

    result = run_pro_pipeline(
        topic=topic_title,
        category=category,
        objective=objective,
        publish_now=True,
        dry_run=dry_run,
    )

    if result.get("status") in ("published", "composed"):
        print(f"✅ Successfully processed: {topic_title}")
        if result.get("youtube_url"):
            print(f"🔗 YouTube Short URL: {result['youtube_url']}")
        print(f"📝 Marked as Done in data/publishing_schedule.xlsx")
    else:
        print(f"❌ Failed: {result.get('error')}")

    return result


def run_trigger_daemon(poll_interval_sec: int = 60, dry_run: bool = False) -> None:
    """
    Runs continuously, monitoring IST time and trigger intervals.
    Publishes when the scheduled trigger time is reached.
    Trigger slots: 09:00, 15:00, 20:00 IST.
    """
    print("🕒 Starting Finance Shorts Autonomous Schedule Daemon...")
    print("   Timezone: Asia/Kolkata (IST)")
    print("   Triggers: 09:00 AM, 3:00 PM, 8:00 PM IST")
    print("   Press Ctrl+C to stop.\n")

    triggered_today: set[str] = set()
    last_checked_date: Optional[date] = None

    while True:
        try:
            now_ist = datetime.now(IST)
            today_date = now_ist.date()

            # Reset triggers at midnight
            if last_checked_date != today_date:
                triggered_today.clear()
                last_checked_date = today_date
                logger.info("New day: %s. Resetting triggered slots.", today_date)

            cur_time_str = now_ist.strftime("%H:%M")
            cur_hm = (now_ist.hour, now_ist.minute)

            # Slots in 24hr format: 09:00, 15:00, 20:00
            slots = [
                ("09:00", 9, 0),
                ("15:00", 15, 0),
                ("20:00", 20, 0),
            ]

            for slot_label, slot_h, slot_m in slots:
                # Trigger window: within 5 minutes after scheduled time
                if slot_label not in triggered_today:
                    slot_dt = now_ist.replace(hour=slot_h, minute=slot_m, second=0, microsecond=0)
                    diff_sec = (now_ist - slot_dt).total_seconds()

                    if 0 <= diff_sec <= 300:
                        logger.info("⏰ SCHEDULE TRIGGER FIRED: %s IST (%s)", slot_label, today_date)
                        print(f"\n⏰ Trigger fired for {slot_label} IST! Processing next topic...")
                        triggered_today.add(slot_label)

                        # Run next topic
                        publish_next_topic(dry_run=dry_run)

            time.sleep(poll_interval_sec)

        except KeyboardInterrupt:
            print("\nDaemon stopped by user.")
            break
        except Exception as e:
            logger.error("Error in schedule daemon: %s", e, exc_info=True)
            time.sleep(poll_interval_sec)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print_schedule_status()
    elif len(sys.argv) > 1 and sys.argv[1] == "daemon":
        run_trigger_daemon()
    else:
        # Default: publish the next topic now
        publish_next_topic()
