"""
Finance Shorts - generate CLI command
Orchestrates: topic selection -> research summary -> script generation -> validation.
Added to main.py via command registration.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from content import topic_reader, script_generator, script_validator
from storage import database
from storage.database import Status

logger = logging.getLogger(__name__)


def run_generate(topic_id: Optional[str] = None, auto_approve: bool = False) -> dict[str, Any]:
    """
    Full content generation pipeline for one topic.
    
    1. Select topic (or use provided topic_id)
    2. Generate script via local Ollama LLM
    3. Validate script
    4. Mark SCRIPT_GENERATED or NEEDS_REVIEW
    
    Returns the generated script dict.
    """

    # ── 1. Topic selection ────────────────────────────────────────────────
    if topic_id:
        topic = database.get_topic(topic_id)
        if not topic:
            raise ValueError(f"Topic not found: {topic_id}")
        if topic["status"] not in (Status.IDEA, Status.READY, Status.NEEDS_REVIEW):
            raise ValueError(
                f"Topic {topic_id} is not in a generatable state: {topic['status']}"
            )
        database.update_topic_status(topic_id, Status.RESEARCHING)
    else:
        topic = topic_reader.get_next_topic()
        if not topic:
            raise RuntimeError("No eligible topics in queue")
        topic_id = topic["topic_id"]

    logger.info("Generating script for [%s] %s", topic_id, topic["topic"])

    try:
        # ── 2. Script generation ──────────────────────────────────────────
        script = script_generator.generate_script(
            topic_id               = topic_id,
            topic                  = topic["topic"],
            category               = topic["category"],
            difficulty_level       = int(topic.get("difficulty_level") or 1),
            audience               = topic.get("audience", "beginners"),
            key_learning_objective = topic.get("key_learning_objective", ""),
            research_summary       = "",  # Phase 3 research module fills this
        )

        # ── 3. Validation ─────────────────────────────────────────────────
        result = script_validator.validate_script(script)

        if not result.passed:
            error_summary = " | ".join(result.errors)
            topic_reader.mark_needs_review(topic_id, f"Validation failed: {error_summary}")
            logger.warning("Script for %s failed validation: %s", topic_id, error_summary)
            return {
                "status": "NEEDS_REVIEW",
                "topic_id": topic_id,
                "errors": result.errors,
                "warnings": result.warnings,
                "script": script,
            }

        # ── 4. Approval ───────────────────────────────────────────────────
        unverified = script.get("unverified_claims", [])
        if unverified and not auto_approve:
            topic_reader.mark_needs_review(
                topic_id,
                f"Has {len(unverified)} unverified claim(s) requiring manual check"
            )
        elif auto_approve or not unverified:
            topic_reader.mark_script_generated(topic_id)

        # Log warnings
        for w in result.warnings:
            logger.warning("[%s] Warning: %s", topic_id, w)

        return {
            "status": "SCRIPT_GENERATED" if not unverified or auto_approve else "NEEDS_REVIEW",
            "topic_id": topic_id,
            "errors": result.errors,
            "warnings": result.warnings,
            "script": script,
        }

    except Exception as e:
        topic_reader.mark_failed(topic_id, str(e))
        raise
