"""
Finance Shorts Pro - Plate Scene Resolver
Resolves the scene visual plate for a curriculum topic with guaranteed fallback.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

import config
from visuals.plate_manifest import load_manifest

logger = logging.getLogger(__name__)

# Cache curriculum map for row_key -> topic_id resolution
_ROW_KEY_TO_TOPIC_ID: dict[str, str] = {}


def _get_row_key_map() -> dict[str, str]:
    global _ROW_KEY_TO_TOPIC_ID
    if _ROW_KEY_TO_TOPIC_ID:
        return _ROW_KEY_TO_TOPIC_ID

    curr_file = Path(config.ROOT_DIR) / "curriculum_42.json"
    if curr_file.exists():
        try:
            with open(curr_file, "r", encoding="utf-8") as f:
                items = json.load(f)
            time_map = {
                "9:00 AM": "09:00",
                "3:00 PM": "15:00",
                "8:00 PM": "20:00",
            }
            for it in items:
                tid = it.get("topic_id")
                day = it.get("day")
                t_str = it.get("time_str", "")
                hm = time_map.get(t_str, "09:00")
                if tid and day is not None:
                    rk = f"D{day:02d}-{hm}"
                    _ROW_KEY_TO_TOPIC_ID[rk] = tid
                    _ROW_KEY_TO_TOPIC_ID[f"D{day}-{hm}"] = tid
        except Exception as e:
            logger.debug("Failed to build row_key map: %s", e)
    return _ROW_KEY_TO_TOPIC_ID


def resolve_topic_id(topic_identifier: str) -> str:
    """Normalizes any topic identifier (T01, D01-09:00, 1, etc.) to canonical Txx."""
    clean = str(topic_identifier).strip()
    if re.match(r"^T\d{1,3}$", clean, re.IGNORECASE):
        num = int(clean[1:])
        return f"T{num:02d}"

    rk_map = _get_row_key_map()
    if clean in rk_map:
        return rk_map[clean]

    # Try numeric index
    m = re.match(r"^\d+$", clean)
    if m:
        return f"T{int(clean):02d}"

    # Extract first digits found if any
    digits = re.findall(r"\d+", clean)
    if digits:
        return f"T{int(digits[0]):02d}"

    return clean


def plate_scene(
    topic_id: str,
    manifest_path: Optional[Path] = None,
    plate_dir: Optional[Path] = None,
    fallback_path: Optional[Path] = None,
) -> Path:
    """
    Returns the Path to assets/plates/{topic_id}.jpg if it exists and passes the
    quality gate in manifest.json.

    If missing or failing the gate, returns assets/presenter/mentor_character_1.png
    and logs a WARNING. Never raises an exception for a missing plate.
    """
    fallback = Path(fallback_path or getattr(config, "PLATE_FALLBACK", Path(config.ROOT_DIR) / "assets" / "presenter" / "mentor_character_1.png"))
    p_dir = Path(plate_dir or getattr(config, "PLATE_DIR", Path(config.ROOT_DIR) / "assets" / "plates"))

    try:
        norm_id = resolve_topic_id(topic_id)
        manifest = load_manifest(manifest_path)
        topics = manifest.get("topics", {})

        topic_entry = topics.get(norm_id) or topics.get(topic_id)
        plate_candidate = p_dir / f"{norm_id}.jpg"

        if topic_entry:
            # Check gate status in manifest
            if not topic_entry.get("passes_gate", False):
                logger.warning(
                    "[PLATE FALLBACK] Topic %s plate exists in manifest but failed quality gate. Using fallback: %s",
                    topic_id, fallback
                )
                return fallback

        if plate_candidate.exists() and plate_candidate.stat().st_size > 0:
            if topic_entry and topic_entry.get("passes_gate", False):
                return plate_candidate
            elif not topic_entry:
                # If file exists on disk without manifest entry, log warning and use fallback
                logger.warning(
                    "[PLATE FALLBACK] Topic %s has file on disk but no manifest gate verification. Using fallback: %s",
                    topic_id, fallback
                )
                return fallback

        logger.warning(
            "[PLATE FALLBACK] Topic %s plate not found at %s. Using fallback: %s",
            topic_id, plate_candidate, fallback
        )
        return fallback

    except Exception as e:
        logger.warning("[PLATE FALLBACK] Unexpected error resolving plate for %s (%s). Using fallback: %s", topic_id, e, fallback)
        return fallback
