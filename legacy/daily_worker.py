"""
Finance Shorts - Autonomous Daily Worker
Orchestrates the entire automated cycle:
1. Syncs human edits from Excel -> SQLite.
2. Evaluates queue health against MIN_QUEUE_BUFFER.
3. Automatically generates scripts & renders videos to maintain healthy buffer.
4. Selects scheduled / ready videos and publishes according to daily cadence.
5. Syncs updated publication status and analytics back to Excel.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import config
from content.pipeline import run_generate
from production.video_pipeline import produce_video_for_topic
from publishing.youtube_publisher import publish_to_youtube
from publishing.instagram_publisher import publish_to_instagram
from storage import database
from storage.spreadsheet_manager import read_topics, sync_db_to_excel

logger = logging.getLogger(__name__)


def run_daily_cycle(
    max_videos_to_publish: int = 1,
    target_buffer_count: Optional[int] = None,
    mode: Optional[str] = None,
) -> dict[str, Any]:
    """
    Executes a complete automated daily cycle.
    """
    if mode:
        config.PUBLISHING_MODE = mode

    target_buffer = target_buffer_count or config.MIN_QUEUE_BUFFER
    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": config.PUBLISHING_MODE,
        "produced_videos": [],
        "published_videos": [],
        "errors": [],
    }

    logger.info("=== STARTING DAILY AUTOMATION CYCLE (Mode: %s) ===", config.PUBLISHING_MODE)

    # ── Step 1: Check Current Ready Buffer ────────────────────────────────────
    ready_topics = database.list_topics(status=database.Status.VIDEO_READY)
    logger.info("Current buffer: %d video(s) ready (Target buffer: %d)", len(ready_topics), target_buffer)

    # ── Step 2: Top-Up Buffer If Low ──────────────────────────────────────────
    buffer_deficit = max(0, target_buffer - len(ready_topics))
    if buffer_deficit > 0:
        logger.info("Buffer deficit: %d. Auto-producing new video(s)...", buffer_deficit)
        for i in range(buffer_deficit):
            next_topic = database.get_next_eligible_topic()
            if not next_topic:
                logger.warning("No eligible IDEA topics remaining in queue.")
                break

            t_id = next_topic["topic_id"]
            logger.info("Auto-producing topic [%s]: %s", t_id, next_topic["topic"])
            try:
                # Generate script with local Ollama
                gen_res = run_generate(topic_id=t_id, auto_approve=True)
                # Produce video (TTS + Visuals + FFmpeg)
                prod_res = produce_video_for_topic(t_id)
                report["produced_videos"].append(prod_res)
                logger.info("Successfully added [%s] to ready buffer", t_id)
            except Exception as e:
                err_msg = f"Failed to auto-produce {t_id}: {e}"
                logger.error(err_msg)
                report["errors"].append(err_msg)
                database.update_topic_status(t_id, database.Status.FAILED, error=str(e))
                break

    # Refresh ready topics list
    ready_topics = database.list_topics(status=database.Status.VIDEO_READY)

    # ── Step 3: Publish Video(s) For Today ─────────────────────────────────────
    publish_count = min(len(ready_topics), max_videos_to_publish)
    for i in range(publish_count):
        topic_to_publish = ready_topics[i]
        t_id = topic_to_publish["topic_id"]
        logger.info("Publishing [%s] (%d/%d for today)...", t_id, i + 1, publish_count)

        try:
            yt_res = publish_to_youtube(t_id)
            ig_res = publish_to_instagram(t_id)
            report["published_videos"].append({
                "topic_id": t_id,
                "youtube": yt_res,
                "instagram": ig_res,
            })
            logger.info("Published [%s] successfully to YouTube & Instagram", t_id)
        except Exception as e:
            err_msg = f"Failed to publish {t_id}: {e}"
            logger.error(err_msg)
            report["errors"].append(err_msg)

    # ── Step 4: Sync SQLite State to Excel ────────────────────────────────────
    try:
        sync_db_to_excel()
        logger.info("Updated Excel spreadsheet with latest cycle status")
    except Exception as e:
        logger.error("Failed to sync Excel: %s", e)
        report["errors"].append(f"Excel sync error: {e}")

    # Summary
    logger.info(
        "=== DAILY CYCLE COMPLETE: %d produced, %d published, %d errors ===",
        len(report["produced_videos"]),
        len(report["published_videos"]),
        len(report["errors"]),
    )
    return report
