"""
Finance Shorts - Topic Reader
Selects the next eligible topic from the queue, atomically locks it
to prevent double-processing, and exposes topic inspection utilities.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from storage import database
from storage.database import Status

logger = logging.getLogger(__name__)


def get_next_topic() -> Optional[dict[str, Any]]:
    """
    Atomically select and lock the next eligible topic for processing.
    Returns the topic dict or None if the queue is empty.
    Transitions status: IDEA/READY -> RESEARCHING.
    """
    topic = database.get_next_eligible_topic()
    if not topic:
        logger.info("No eligible topics in queue")
        return None

    topic_id = topic["topic_id"]
    # Atomically move to RESEARCHING to prevent double-processing
    database.update_topic_status(topic_id, Status.RESEARCHING)
    logger.info("Locked topic %s -> RESEARCHING: %s", topic_id, topic["topic"])
    return topic


def mark_research_done(topic_id: str) -> None:
    database.update_topic_status(topic_id, Status.RESEARCHED)
    logger.info("Topic %s -> RESEARCHED", topic_id)


def mark_script_generated(topic_id: str) -> None:
    database.update_topic_status(topic_id, Status.SCRIPT_GENERATED)
    logger.info("Topic %s -> SCRIPT_GENERATED", topic_id)


def mark_needs_review(topic_id: str, reason: str = "") -> None:
    database.update_topic_status(topic_id, Status.NEEDS_REVIEW, reason)
    logger.warning("Topic %s -> NEEDS_REVIEW: %s", topic_id, reason)


def mark_script_approved(topic_id: str) -> None:
    database.update_topic_status(topic_id, Status.SCRIPT_APPROVED)
    logger.info("Topic %s -> SCRIPT_APPROVED", topic_id)


def mark_failed(topic_id: str, error: str) -> None:
    database.update_topic_status(topic_id, Status.FAILED, error)
    logger.error("Topic %s -> FAILED: %s", topic_id, error)


def release_topic(topic_id: str) -> None:
    """
    Release a locked topic back to IDEA if processing is abandoned
    (e.g., keyboard interrupt, unexpected crash during research phase).
    """
    database.update_topic_status(topic_id, Status.IDEA)
    logger.warning("Topic %s released back to IDEA", topic_id)


def get_topic(topic_id: str) -> Optional[dict[str, Any]]:
    return database.get_topic(topic_id)


def generate_job_id(topic_id: str, phase: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{topic_id}_{phase}_{ts}_{uuid.uuid4().hex[:6].upper()}"
