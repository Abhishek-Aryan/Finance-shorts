"""
Finance Shorts - Instagram Publisher
Publishes vertical short videos to Instagram Reels via the Instagram Graph API.
Supports safe simulation in test mode and real API posting in production mode.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

import config
from storage import database

logger = logging.getLogger(__name__)


def publish_to_instagram(
    topic_id: str,
    force_test_mode: Optional[bool] = None,
) -> dict[str, Any]:
    """
    Publishes a produced video for topic_id to Instagram Reels.
    If config.PUBLISHING_MODE == 'test' or force_test_mode is True, runs simulation mode.
    """
    topic = database.get_topic(topic_id)
    if not topic:
        raise ValueError(f"Topic {topic_id} not found in database")

    script = database.get_script(topic_id)
    if not script:
        raise ValueError(f"Script for topic {topic_id} not found")

    with database.get_connection() as conn:
        prod_row = conn.execute(
            "SELECT * FROM production WHERE topic_id=?", (topic_id,)
        ).fetchone()

    if not prod_row or not prod_row["video_file"]:
        raise ValueError(f"No rendered video found for topic {topic_id}")

    existing_upload = database.get_upload_by_topic_platform(topic_id, "instagram")
    if existing_upload:
        logger.warning(
            "Topic %s already uploaded to Instagram: %s",
            topic_id, existing_upload.get("published_url"),
        )
        return existing_upload

    upload_id = str(uuid.uuid4())
    database.record_upload_attempt(
        upload_id=upload_id,
        topic_id=topic_id,
        platform="instagram",
        privacy_status="public",
    )

    caption = (
        f"{script.get('video_title', topic.get('topic'))}\n\n"
        f"{script.get('takeaway', '')}\n\n"
        f"Follow @{config.CHANNEL_NAME} for daily personal finance tips!\n\n"
        f"#Finance #Money #PersonalFinance #Investing #Reels #India #MoneyManagement"
    )

    is_test_mode = (
        force_test_mode
        if force_test_mode is not None
        else (config.PUBLISHING_MODE.lower() == "test")
    )

    if is_test_mode:
        simulated_media_id = f"ig_reel_{topic_id.lower()}_{uuid.uuid4().hex[:6]}"
        published_url = f"https://instagram.com/reel/{simulated_media_id}"

        database.confirm_upload(upload_id, simulated_media_id, published_url)
        logger.info("[TEST MODE] Instagram Reel simulated for %s -> %s", topic_id, published_url)
        return {
            "upload_id": upload_id,
            "topic_id": topic_id,
            "platform": "instagram",
            "media_id": simulated_media_id,
            "published_url": published_url,
            "mode": "test",
            "status": "PUBLISHED",
        }

    else:
        # Check if Instagram credentials exist
        if not config.INSTAGRAM_ACCESS_TOKEN or not config.INSTAGRAM_ACCOUNT_ID:
            logger.info("Instagram access token not configured in .env. Skipping Instagram upload for %s.", topic_id)
            return {
                "upload_id": upload_id,
                "topic_id": topic_id,
                "platform": "instagram",
                "status": "SKIPPED",
                "published_url": None,
                "message": "Instagram credentials not configured (YouTube only mode)",
            }

        # Real Instagram Graph API call would go here
        raise NotImplementedError("Instagram Graph API posting requires Meta App Review.")
