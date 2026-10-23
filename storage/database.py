"""
Finance Shorts - SQLite Database Layer
Authoritative record for all job state, upload attempts, and idempotency.
The Excel file is the human-editable topic queue; this is the source of truth
for what has actually happened.
"""

from __future__ import annotations

import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

import config

logger = logging.getLogger(__name__)

# ── Schema DDL ────────────────────────────────────────────────────────────────

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS topics (
    topic_id            TEXT PRIMARY KEY,
    topic               TEXT NOT NULL,
    category            TEXT NOT NULL,
    difficulty_level    INTEGER NOT NULL DEFAULT 1,
    audience            TEXT NOT NULL DEFAULT 'beginners',
    key_learning_objective TEXT,
    prerequisites       TEXT,
    status              TEXT NOT NULL DEFAULT 'IDEA',
    retry_count         INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id              TEXT PRIMARY KEY,
    topic_id            TEXT NOT NULL,
    phase               TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'PENDING',
    started_at          TEXT,
    completed_at        TEXT,
    error_message       TEXT,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
);

CREATE TABLE IF NOT EXISTS scripts (
    topic_id            TEXT PRIMARY KEY,
    hook                TEXT,
    body                TEXT,
    example             TEXT,
    takeaway            TEXT,
    closing             TEXT,
    full_script         TEXT,
    video_title         TEXT,
    video_description   TEXT,
    keywords            TEXT,
    scene_plan          TEXT,
    source_references   TEXT,
    unverified_claims   TEXT,
    estimated_duration  REAL,
    word_count          INTEGER,
    model_used          TEXT,
    validated           INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
);

CREATE TABLE IF NOT EXISTS research (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id            TEXT NOT NULL,
    source_url          TEXT,
    source_title        TEXT,
    accessed_at         TEXT,
    published_date      TEXT,
    claim               TEXT,
    verified            INTEGER NOT NULL DEFAULT 0,
    claim_type          TEXT NOT NULL DEFAULT 'fact',
    notes               TEXT,
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
);

CREATE TABLE IF NOT EXISTS production (
    topic_id            TEXT PRIMARY KEY,
    narration_file      TEXT,
    captions_file       TEXT,
    visuals_dir         TEXT,
    video_file          TEXT,
    audio_duration      REAL,
    video_duration      REAL,
    video_width         INTEGER,
    video_height        INTEGER,
    render_report       TEXT,
    validated           INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
);

CREATE TABLE IF NOT EXISTS uploads (
    upload_id           TEXT PRIMARY KEY,
    topic_id            TEXT NOT NULL,
    platform            TEXT NOT NULL,
    attempt_at          TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'PENDING',
    video_id            TEXT,
    published_url       TEXT,
    scheduled_at        TEXT,
    privacy_status      TEXT NOT NULL DEFAULT 'public',
    error_message       TEXT,
    reconciled          INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
);

CREATE TABLE IF NOT EXISTS analytics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id            TEXT NOT NULL,
    platform            TEXT NOT NULL,
    video_id            TEXT NOT NULL,
    fetched_at          TEXT NOT NULL,
    views               INTEGER,
    likes               INTEGER,
    comments            INTEGER,
    watch_time_minutes  REAL,
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key                 TEXT PRIMARY KEY,
    value               TEXT,
    updated_at          TEXT NOT NULL
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_topics_status     ON topics(status);
CREATE INDEX IF NOT EXISTS idx_jobs_topic        ON jobs(topic_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status       ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_uploads_topic     ON uploads(topic_id);
CREATE INDEX IF NOT EXISTS idx_uploads_platform  ON uploads(platform);
CREATE INDEX IF NOT EXISTS idx_research_topic    ON research(topic_id);
"""

# ── Statuses ──────────────────────────────────────────────────────────────────

class Status:
    """Canonical topic lifecycle statuses."""
    IDEA             = "IDEA"
    READY            = "READY"
    RESEARCHING      = "RESEARCHING"
    RESEARCHED       = "RESEARCHED"
    SCRIPT_GENERATED = "SCRIPT_GENERATED"
    NEEDS_REVIEW     = "NEEDS_REVIEW"
    SCRIPT_APPROVED  = "SCRIPT_APPROVED"
    PRODUCING        = "PRODUCING"
    VIDEO_READY      = "VIDEO_READY"
    SCHEDULED        = "SCHEDULED"
    UPLOADING        = "UPLOADING"
    PUBLISHED        = "PUBLISHED"
    FAILED           = "FAILED"

    ALL = (
        IDEA, READY, RESEARCHING, RESEARCHED,
        SCRIPT_GENERATED, NEEDS_REVIEW, SCRIPT_APPROVED,
        PRODUCING, VIDEO_READY, SCHEDULED, UPLOADING,
        PUBLISHED, FAILED,
    )


# ── Connection Management ──────────────────────────────────────────────────────

@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Yield a WAL-mode SQLite connection with row factory set."""
    db_path = config.SQLITE_DB
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Schema Initialisation ─────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables and indexes if they do not exist."""
    with get_connection() as conn:
        conn.executescript(_SCHEMA)
    logger.info("Database initialised at %s", config.SQLITE_DB)


# ── Topic CRUD ────────────────────────────────────────────────────────────────

def upsert_topic(
    topic_id: str,
    topic: str,
    category: str,
    difficulty_level: int = 1,
    audience: str = "beginners",
    key_learning_objective: str = "",
    prerequisites: str = "",
    status: str = Status.IDEA,
) -> None:
    """Insert or update a topic record without overwriting existing progress."""
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO topics
                (topic_id, topic, category, difficulty_level, audience,
                 key_learning_objective, prerequisites, status, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(topic_id) DO UPDATE SET
                topic                  = excluded.topic,
                category               = excluded.category,
                difficulty_level       = excluded.difficulty_level,
                audience               = excluded.audience,
                key_learning_objective = excluded.key_learning_objective,
                prerequisites          = excluded.prerequisites,
                updated_at             = excluded.updated_at
            """,
            (topic_id, topic, category, difficulty_level, audience,
             key_learning_objective, prerequisites, status, now, now),
        )


def update_topic_status(topic_id: str, status: str, error: Optional[str] = None) -> None:
    """Update status (and optional last_error) for a topic."""
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE topics
            SET status = ?, last_error = ?, updated_at = ?
            WHERE topic_id = ?
            """,
            (status, error, now, topic_id),
        )
    logger.debug("Topic %s → %s", topic_id, status)


def get_next_eligible_topic() -> Optional[dict[str, Any]]:
    """
    Return the next topic ready to be processed.
    Priority: READY > IDEA, ordered by difficulty_level ASC, topic_id ASC.
    Skips topics already in progress or completed.
    """
    eligible = (Status.READY, Status.IDEA)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM topics
            WHERE status IN (?, ?)
            ORDER BY
                CASE status WHEN 'READY' THEN 0 ELSE 1 END,
                difficulty_level ASC,
                topic_id ASC
            LIMIT 1
            """,
            eligible,
        ).fetchone()
    return dict(row) if row else None


def get_topic(topic_id: str) -> Optional[dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM topics WHERE topic_id = ?", (topic_id,)
        ).fetchone()
    return dict(row) if row else None


def list_topics(status: Optional[str] = None) -> list[dict[str, Any]]:
    with get_connection() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM topics WHERE status = ? ORDER BY difficulty_level, topic_id",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM topics ORDER BY difficulty_level, topic_id"
            ).fetchall()
    return [dict(r) for r in rows]


def get_script(topic_id: str) -> Optional[dict[str, Any]]:
    """Fetch the generated script for a given topic."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM scripts WHERE topic_id = ?", (topic_id,)
        ).fetchone()
    return dict(row) if row else None


# ── Job CRUD ──────────────────────────────────────────────────────────────────

def create_job(job_id: str, topic_id: str, phase: str) -> None:
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO jobs
                (job_id, topic_id, phase, status, started_at)
            VALUES (?,?,?,'RUNNING',?)
            """,
            (job_id, topic_id, phase, now),
        )


def complete_job(job_id: str) -> None:
    now = _now()
    with get_connection() as conn:
        conn.execute(
            "UPDATE jobs SET status='DONE', completed_at=? WHERE job_id=?",
            (now, job_id),
        )


def fail_job(job_id: str, error: str) -> None:
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status='FAILED', completed_at=?, error_message=?,
                retry_count = retry_count + 1
            WHERE job_id=?
            """,
            (now, error, job_id),
        )


# ── Upload Tracking ───────────────────────────────────────────────────────────

def record_upload_attempt(
    upload_id: str,
    topic_id: str,
    platform: str,
    scheduled_at: Optional[str] = None,
    privacy_status: str = "public",
) -> None:
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO uploads
                (upload_id, topic_id, platform, attempt_at, status,
                 scheduled_at, privacy_status)
            VALUES (?,?,?,?,?,?,?)
            """,
            (upload_id, topic_id, platform, now, "PENDING",
             scheduled_at, privacy_status),
        )


def confirm_upload(upload_id: str, video_id: str, published_url: str) -> None:
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE uploads
            SET status='UPLOADED', video_id=?, published_url=?,
                reconciled=1
            WHERE upload_id=?
            """,
            (video_id, published_url, upload_id),
        )


def fail_upload(upload_id: str, error: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE uploads SET status='FAILED', error_message=? WHERE upload_id=?",
            (error, upload_id),
        )


def get_upload_by_topic_platform(
    topic_id: str, platform: str
) -> Optional[dict[str, Any]]:
    """Check whether a topic was already successfully uploaded to a platform."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM uploads
            WHERE topic_id=? AND platform=? AND status='UPLOADED'
            ORDER BY attempt_at DESC LIMIT 1
            """,
            (topic_id, platform),
        ).fetchone()
    return dict(row) if row else None


# ── Settings ──────────────────────────────────────────────────────────────────

def set_setting(key: str, value: str) -> None:
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, now),
        )


def get_setting(key: str, default: str = "") -> str:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
    return row["value"] if row else default


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
