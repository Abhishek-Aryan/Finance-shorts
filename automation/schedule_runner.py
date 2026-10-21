"""
Finance Shorts Pro - Autonomous Schedule Trigger Runner
Monitors the 14-day publishing schedule (data/publishing_schedule.xlsx).
Runs continuously or as a cron trigger to:
1. Identify the next due topic according to IST time (09:00, 15:00, 20:00).
2. Generate script (Gemini / OpenRouter) + TTS (Edge-TTS Andrew Neural) + HeyGen scene visuals.
3. Compose and verify final vertical 1080x1920 Short.
4. Publish directly to connected YouTube channel.
5. Update schedule state atomically and mark 'Done' in the Excel sheet.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import openpyxl

import config
from automation.run_lock import LockHeld, acquire_run_lock
from production.pro_pipeline import publish_composed, run_pro_pipeline, verify_composed_video
from storage import state_store
from storage.schedule_manager import (
    ExcelLockedError,
    format_status_cell,
    get_all_topics_summary,
    mark_row_done,
    select_due_row,
)

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")


def print_schedule_status(excel_path: Path | None = None, state_file: Path | None = None) -> None:
    """Prints a clean CLI summary of the current schedule and status."""
    topics = get_all_topics_summary()
    total = len(topics)
    done = sum(1 for t in topics if "done" in str(t.get("status", "")).lower())
    pending = total - done

    print("\n" + "=" * 70)
    print("  FINANCE SHORTS PRO — 14-DAY PUBLISHING SCHEDULE STATUS")
    print("=" * 70)
    print(f"  Total Topics: {total} | Done: {done} | Pending: {pending}")
    print("-" * 70)
    print(f"  {'Day':<5} {'Time':<10} {'Topic':<38} {'Status':<10}")
    print("-" * 70)

    for t in topics:
        status_val = str(t.get("status", "")).strip()
        status_sym = "[DONE]" if "done" in status_val.lower() else f"[{status_val or 'Pending'}]"
        print(f"  D{t['day']:<4} {t['time']:<10} {t['topic'][:36]:<38} {status_sym}")

    print("-" * 70)
    next_topic = select_due_row(excel_path=excel_path, state_file=state_file)
    if next_topic:
        print(f"  >>> NEXT UP: Day {next_topic['day']} [{next_topic.get('row_key', '')}] {next_topic['topic']}")
        print(f"      Category: {next_topic.get('category', '')}")
    else:
        next_slot = getattr(select_due_row, "next_scheduled_at", None)
        if next_slot:
            print(f"  Nothing due right now. Next scheduled slot is at: {next_slot}")
        else:
            print("  All topics in the curriculum have been completed!")
    print("=" * 70 + "\n")


def check_idempotency(
    row_key: str,
    state_file: Path | None = None,
    excel_file: Path | None = None,
) -> tuple[str | None, str | None]:
    """Checks if the row already has a published youtube_video_id in state."""
    current_state = state_store.load(state_file=state_file, excel_file=excel_file)
    row = current_state.get("rows", {}).get(row_key, {})
    return row.get("youtube_video_id"), row.get("youtube_url")


def publish_next_topic(
    dry_run: bool = False,
    now: datetime | None = None,
    excel_path: Path | None = None,
    state_file: Path | None = None,
    lock_file: Path | None = None,
    force_privacy: str | None = None,
) -> int:
    """
    Publishes the next due topic according to the strict 10-step publish safety sequence.

    Exit codes:
      0 = OK or nothing due
      1 = Pipeline failure
      2 = Configuration or credential error
      3 = State conflict between Excel and state
      4 = Published to YouTube, but Excel view is stale / locked
    """
    now_dt = now or datetime.now(IST)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)

    e_path = Path(excel_path or config.SCHEDULE_EXCEL)
    s_path = Path(state_file or (config.DATA_DIR / "schedule_state.json"))

    # ── Step 0: Config and Credential Validation ─────────────────────────────
    warnings = config.validate()
    if config.PUBLISHING_MODE == "production" and not dry_run:
        crit_errors = [
            w for w in warnings
            if "YouTube client secrets" in w
            or "YouTube token file" in w
            or "Both OPENROUTER_API_KEY and GEMINI_API_KEY" in w
        ]
        if crit_errors:
            logger.error("Configuration validation failed in production mode: %s", crit_errors)
            for err in crit_errors:
                print(f"[CONFIG ERROR] {err}", file=sys.stderr)
            return 2

    # ── Step 1: Acquire the Run Lock ─────────────────────────────────────────
    try:
        lock_ctx = acquire_run_lock(lock_file=lock_file)
        lock_ctx.__enter__()
    except LockHeld:
        logger.info("Another run holds the lock. Exiting cleanly.")
        print("Another publishing process holds the run lock. Skipping this invocation.")
        return 0

    try:
        # ── Step 2: Reconcile Excel and State ────────────────────────────────
        try:
            st = state_store.reconcile(excel_path=e_path, state_file=s_path, now=now_dt)
        except state_store.StateConflictError as sce:
            logger.error("State conflict: %s", sce)
            return 3
        except state_store.RunInProgressError as ripe:
            logger.info("Another run is currently working: %s", ripe)
            return 0

        # ── Step 3: Select Due Row ────────────────────────────────────────────
        row = select_due_row(now_ist=now_dt, excel_path=e_path, state_file=s_path)
        if not row:
            next_slot = getattr(select_due_row, "next_scheduled_at", None)
            logger.info("Nothing due right now. Next scheduled slot: %s", next_slot)
            return 0

        row_key = row["row_key"]
        topic_title = row["topic"]
        category = row.get("category", "Finance")
        objective = row.get("objective", "")
        row_index = row.get("row_index", 2)
        job_id = f"{row_key}_{int(time.time())}"

        logger.info("Claiming due topic: %s (%s)", row_key, topic_title)

        # ── Step 4: Claim Row (Both state and Excel writes must succeed) ─────
        if not dry_run:
            try:
                state_store.claim(row_key, job_id=job_id, state_file=s_path, now=now_dt)

                wb = openpyxl.load_workbook(str(e_path))
                ws = wb["Publishing Schedule"] if "Publishing Schedule" in wb.sheetnames else wb.active
                format_status_cell(ws.cell(row=row_index, column=10), "In progress", row_index)
                wb.save(str(e_path))
            except Exception as ce:
                logger.error("Failed to claim row %s: %s", row_key, ce)
                state_store.fail(row_key, f"Claim failed: {ce}", state_file=s_path)
                return 1
        else:
            logger.info("[DRY RUN] In-memory claim for %s (job_id: %s)", row_key, job_id)

        # ── Step 5: Run Pro Pipeline (Up to compose step) ────────────────────
        try:
            compose_result = run_pro_pipeline(
                topic=topic_title,
                category=category,
                objective=objective,
                publish_now=False,
                dry_run=dry_run,
            )
            if compose_result.get("status") != "composed":
                raise RuntimeError(f"Composition did not produce 'composed' status: {compose_result.get('error')}")

            video_path = compose_result.get("video_path")
            if not video_path:
                raise RuntimeError("No final video path produced by composition step")

            # Verify video
            if not dry_run and config.PUBLISHING_MODE == "production":
                verify_composed_video(video_path)

        except Exception as pe:
            logger.error("Pipeline failure for %s before upload: %s", row_key, pe, exc_info=True)
            if not dry_run:
                state_store.fail(row_key, str(pe), state_file=s_path)
            return 1

        # ── Step 6: Idempotency Check Immediately Before Upload ──────────────
        existing_video_id, existing_url = check_idempotency(row_key, state_file=s_path, excel_file=e_path)

        if existing_video_id:
            logger.info("Idempotency check: %s already has video id %s. Skipping upload.", row_key, existing_video_id)
            published_res = {
                "video_id": existing_video_id,
                "youtube_video_id": existing_video_id,
                "url": existing_url,
                "published_url": existing_url,
                "status": "published",
            }
        else:
            # ── Step 7: Upload ───────────────────────────────────────────────
            effective_privacy = config.resolve_youtube_privacy(
                force_privacy=force_privacy or "",
                state_file=s_path,
                now=now_dt,
            )
            try:
                published_res = publish_composed(
                    compose_result,
                    dry_run=dry_run,
                    privacy_status=effective_privacy,
                )
            except Exception as ue:
                logger.error("Upload failure for %s: %s", row_key, ue, exc_info=True)
                if not dry_run:
                    state_store.fail(row_key, str(ue), state_file=s_path)
                return 1

        # ── Step 8: Upload Success Handling ──────────────────────────────────
        if dry_run:
            logger.info("[DRY RUN] Completed dry run for %s. Leaving state and Excel unmodified.", row_key)
            print(f"[DRY RUN SUCCESS] Simulated publish for: {topic_title} (ID: {published_res.get('video_id')})")
            return 0

        vid = published_res.get("video_id") or published_res.get("youtube_video_id")
        url = published_res.get("published_url") or published_res.get("url")
        full_script = compose_result.get("script", {}).get("full_voiceover", "")

        # IMMEDIATELY write video id to state
        state_store.complete(
            row_key=row_key,
            video_id=vid,
            url=url,
            script_full=full_script,
            state_file=s_path,
            now=now_dt,
        )
        logger.info("Recorded video ID %s in state store for %s.", vid, row_key)

        # Mark Done in Excel
        try:
            mark_row_done(
                row_key=row_key,
                expected_topic=topic_title,
                script_text=full_script,
                excel_path=e_path,
                state_file=s_path,
                video_id=vid,
                video_url=url,
            )
            print(f"[PUBLISHED] {topic_title} -> {url}")
            return 0
        except (ExcelLockedError, Exception) as ee:
            logger.error("Upload succeeded (ID: %s, URL: %s) but Excel write failed: %s", vid, url, ee)
            print(f"[WARNING] Video was published to YouTube ({url}), but Excel could not be updated: {ee}", file=sys.stderr)
            return 4

    finally:
        # ── Step 10: Always release lock ─────────────────────────────────────
        try:
            lock_ctx.__exit__(None, None, None)
        except Exception:
            pass


def run_trigger_daemon(poll_interval_sec: int = 30, dry_run: bool = False) -> None:
    """
    Runs continuously, monitoring IST time and trigger slots.
    Persists fired slots into state store to avoid double-fires across restarts.
    Trigger slots: read from config.PUBLISH_TIMES (default: 09:00, 15:00, 20:00 IST).
    """
    print("Starting Finance Shorts Autonomous Schedule Daemon...")
    print("   Timezone: Asia/Kolkata (IST)")
    print(f"   Triggers: {', '.join(config.PUBLISH_TIMES)} IST")
    print("   Press Ctrl+C to stop.\n")

    slots = config.PUBLISH_TIMES

    while True:
        try:
            now_ist = datetime.now(IST)
            today_str = now_ist.strftime("%Y-%m-%d")

            st = state_store.load()
            daemon_state = st.setdefault("daemon", {})
            fired_map = daemon_state.setdefault("fired", {})
            fired_today = set(fired_map.get(today_str, []))

            for slot_time in slots:
                if slot_time in fired_today:
                    continue

                try:
                    slot_h, slot_m = [int(p) for p in slot_time.split(":")]
                except ValueError:
                    continue

                slot_dt = now_ist.replace(hour=slot_h, minute=slot_m, second=0, microsecond=0)

                # Widen trigger window: any time after the slot until next slot
                if now_ist >= slot_dt:
                    logger.info("SCHEDULE TRIGGER FIRED: %s IST (%s)", slot_time, today_str)
                    print(f"\n[TRIGGER] Fired for {slot_time} IST! Processing next topic...")

                    exit_code = publish_next_topic(dry_run=dry_run, now=now_ist)
                    if exit_code in (0, 4):
                        fired_today.add(slot_time)
                        fired_map[today_str] = sorted(list(fired_today))
                        state_store.save(st)

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
    elif len(sys.argv) > 1 and sys.argv[1] == "publish":
        code = publish_next_topic()
        sys.exit(code)
    else:
        print("Usage: python -m automation.schedule_runner [status|daemon|publish]")
        sys.exit(0)
