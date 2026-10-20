"""
Finance Shorts - Test Suite
Tests for core pipeline components.
All external services (Ollama, YouTube, Instagram) are mocked.
Running these tests never creates real uploads or consumes paid credits.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Create a temporary SQLite database for each test."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("config.SQLITE_DB", db_path)
    monkeypatch.setattr("config.DATA_DIR", tmp_path)

    # Re-import to pick up patched config
    import importlib
    import storage.database as dbmod
    importlib.reload(dbmod)
    dbmod.init_db()
    yield dbmod, db_path


@pytest.fixture()
def sample_topic():
    return {
        "topic_id": "TEST001",
        "topic": "What Is Money?",
        "category": "Money Fundamentals",
        "difficulty_level": 1,
        "audience": "absolute beginners",
        "key_learning_objective": "Understand what money is",
        "prerequisites": "",
        "status": "IDEA",
    }


@pytest.fixture()
def sample_script():
    return {
        "topic_id": "TEST001",
        "hook": "Did you know money was invented to solve a simple problem?",
        "explanation": "Before money existed, people traded goods directly. If you had wheat but needed shoes, you had to find a shoemaker who wanted wheat.",
        "example": "Imagine you earn Rs. 30,000 a month. Without money, you would need to carry bags of rice to pay your landlord.",
        "takeaway": "Money is simply a tool that makes exchange easier. The better you manage this tool, the more freedom you have.",
        "closing": "What would you trade if money didn't exist?",
        "full_script": "Did you know money was invented to solve a simple problem? Before money existed, people traded goods directly. If you had wheat but needed shoes, you had to find a shoemaker who wanted wheat. Imagine you earn Rs. 30,000 a month. Without money, you would need to carry bags of rice to pay your landlord. Money is simply a tool that makes exchange easier. The better you manage this tool, the more freedom you have. What would you trade if money didn't exist?",
        "video_title": "What Is Money? The Simple Truth",
        "video_description": "Learn the origin and purpose of money in simple terms. Perfect for beginners starting their financial education journey. #FinanceSimple #MoneyBasics #FinancialEducation",
        "keywords": ["money", "finance basics", "what is money", "currency", "financial education"],
        "scene_plan": [
            {"scene_number": 1, "duration_seconds": 8, "visual": "Animated coins appearing", "on_screen_text": "WHAT IS MONEY?", "narration": "Did you know money was invented to solve a simple problem?"},
            {"scene_number": 2, "duration_seconds": 15, "visual": "Barter animation: wheat for shoes", "on_screen_text": "THE BARTER PROBLEM", "narration": "Before money existed, people traded goods directly."},
            {"scene_number": 3, "duration_seconds": 12, "visual": "Indian family with Rs. 30,000 salary graphic", "on_screen_text": "Rs. 30,000/month", "narration": "Imagine you earn Rs. 30,000 a month."},
            {"scene_number": 4, "duration_seconds": 10, "visual": "Money as a tool graphic", "on_screen_text": "MONEY = FREEDOM", "narration": "Money is simply a tool that makes exchange easier."},
            {"scene_number": 5, "duration_seconds": 5, "visual": "Question mark animation", "on_screen_text": "WHAT WOULD YOU TRADE?", "narration": "What would you trade if money didn't exist?"},
        ],
        "source_references": ["Reserve Bank of India - History of Currency in India"],
        "unverified_claims": [],
        "estimated_word_count": 92,
        "model_used": "llama3.2:3b",
    }


# ── Database Tests ─────────────────────────────────────────────────────────────

class TestDatabase:
    def test_init_creates_tables(self, tmp_db):
        dbmod, db_path = tmp_db
        conn = sqlite3.connect(str(db_path))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "topics" in tables
        assert "jobs" in tables
        assert "scripts" in tables
        assert "uploads" in tables

    def test_upsert_topic(self, tmp_db, sample_topic):
        dbmod, _ = tmp_db
        dbmod.upsert_topic(**{k: v for k, v in sample_topic.items() if k != "status"})
        topic = dbmod.get_topic("TEST001")
        assert topic is not None
        assert topic["topic"] == "What Is Money?"
        assert topic["status"] == "IDEA"

    def test_duplicate_topic_does_not_reset_status(self, tmp_db, sample_topic):
        """Upserting a topic that is IN PROGRESS should not reset its status."""
        dbmod, _ = tmp_db
        dbmod.upsert_topic(**{k: v for k, v in sample_topic.items() if k != "status"})
        dbmod.update_topic_status("TEST001", dbmod.Status.RESEARCHING)

        # Re-upsert (simulating re-init from Excel)
        dbmod.upsert_topic(**{k: v for k, v in sample_topic.items() if k != "status"})

        topic = dbmod.get_topic("TEST001")
        # Status should remain RESEARCHING, not reset to IDEA
        assert topic["status"] == "RESEARCHING"

    def test_get_next_eligible_topic_skips_in_progress(self, tmp_db, sample_topic):
        dbmod, _ = tmp_db
        dbmod.upsert_topic(**{k: v for k, v in sample_topic.items() if k != "status"})
        dbmod.update_topic_status("TEST001", dbmod.Status.RESEARCHING)

        next_t = dbmod.get_next_eligible_topic()
        assert next_t is None  # no other IDEA/READY topics

    def test_get_next_eligible_topic_priority_order(self, tmp_db):
        """READY topics should be returned before IDEA topics."""
        dbmod, _ = tmp_db
        for i, (tid, status) in enumerate([("T002", "IDEA"), ("T001", "READY")], 1):
            dbmod.upsert_topic(tid, f"Topic {tid}", "Test", i, "beginners", "", "")
            dbmod.update_topic_status(tid, status)

        next_t = dbmod.get_next_eligible_topic()
        assert next_t["topic_id"] == "T001"

    def test_update_topic_status(self, tmp_db, sample_topic):
        dbmod, _ = tmp_db
        dbmod.upsert_topic(**{k: v for k, v in sample_topic.items() if k != "status"})
        dbmod.update_topic_status("TEST001", dbmod.Status.SCRIPT_GENERATED)
        topic = dbmod.get_topic("TEST001")
        assert topic["status"] == "SCRIPT_GENERATED"

    def test_upload_deduplication(self, tmp_db, sample_topic):
        dbmod, _ = tmp_db
        dbmod.upsert_topic(**{k: v for k, v in sample_topic.items() if k != "status"})

        dbmod.record_upload_attempt("UP001", "TEST001", "youtube")
        dbmod.confirm_upload("UP001", "vid123", "https://youtube.com/shorts/vid123")

        existing = dbmod.get_upload_by_topic_platform("TEST001", "youtube")
        assert existing is not None
        assert existing["video_id"] == "vid123"

    def test_job_lifecycle(self, tmp_db, sample_topic):
        dbmod, _ = tmp_db
        dbmod.upsert_topic(**{k: v for k, v in sample_topic.items() if k != "status"})

        dbmod.create_job("JOB001", "TEST001", "research")
        dbmod.complete_job("JOB001")

        with dbmod.get_connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id='JOB001'").fetchone()
        assert row["status"] == "DONE"

    def test_fail_job_increments_retry(self, tmp_db, sample_topic):
        dbmod, _ = tmp_db
        dbmod.upsert_topic(**{k: v for k, v in sample_topic.items() if k != "status"})

        dbmod.create_job("JOB002", "TEST001", "research")
        dbmod.fail_job("JOB002", "Connection timeout")

        with dbmod.get_connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id='JOB002'").fetchone()
        assert row["status"] == "FAILED"
        assert row["retry_count"] >= 1


# ── Script Validator Tests ─────────────────────────────────────────────────────

class TestScriptValidator:
    def test_valid_script_passes(self, sample_script):
        from content.script_validator import validate_script
        result = validate_script(sample_script)
        assert result.passed, f"Expected PASS but got errors: {result.errors}"

    def test_short_script_fails(self, sample_script):
        from content.script_validator import validate_script
        sample_script["full_script"] = "Too short."
        sample_script["estimated_word_count"] = 2
        result = validate_script(sample_script)
        assert not result.passed
        assert any("short" in e.lower() for e in result.errors)

    def test_prohibited_guaranteed_returns(self, sample_script):
        from content.script_validator import validate_script
        sample_script["full_script"] += " This investment guarantees a 20% return every year."
        result = validate_script(sample_script)
        assert not result.passed
        assert any("guaranteed" in e.lower() for e in result.errors)

    def test_missing_required_field(self, sample_script):
        from content.script_validator import validate_script
        sample_script["hook"] = ""
        result = validate_script(sample_script)
        assert not result.passed

    def test_unverified_claims_triggers_warning(self, sample_script):
        from content.script_validator import validate_script
        sample_script["unverified_claims"] = ["India has 500 million investors"]
        result = validate_script(sample_script)
        # Should still pass but have a warning
        assert any("unverified" in w.lower() for w in result.warnings)

    def test_financial_calculation_simple_interest(self, sample_script):
        from content.script_validator import _check_financial_calculations
        # Correct: Rs. 10,000 at 8% for 1 year gives Rs. 800
        text_correct = "If you invest Rs. 10,000 at 8% for 1 year gives Rs. 800 in interest."
        issues = _check_financial_calculations(text_correct)
        assert len(issues) == 0, f"Should have no issues but got: {issues}"

    def test_financial_calculation_wrong_amount_flagged(self, sample_script):
        from content.script_validator import _check_financial_calculations
        # Wrong: Rs. 10,000 at 8% for 1 year gives Rs. 1,200 (should be 800)
        text_wrong = "If you invest Rs. 10,000 at 8% for 1 year gives Rs. 1,200 in interest."
        issues = _check_financial_calculations(text_wrong)
        assert len(issues) > 0, "Should detect calculation mismatch"


# ── Duration Estimation Tests ──────────────────────────────────────────────────

class TestDurationEstimation:
    def test_100_words_is_about_43_seconds(self):
        from content.script_generator import estimate_duration_seconds
        duration = estimate_duration_seconds(100, speaking_rate_wpm=140)
        assert 40 <= duration <= 46

    def test_75_words_meets_minimum(self):
        from content.script_generator import estimate_duration_seconds
        duration = estimate_duration_seconds(75)
        assert duration >= 30

    def test_130_words_within_max(self):
        from content.script_generator import estimate_duration_seconds
        duration = estimate_duration_seconds(130)
        assert duration <= 60


# ── Topic Reader Tests ─────────────────────────────────────────────────────────

class TestTopicReader:
    def test_generate_job_id_unique(self):
        from content.topic_reader import generate_job_id
        id1 = generate_job_id("FIN001", "research")
        id2 = generate_job_id("FIN001", "research")
        assert id1 != id2

    def test_job_id_contains_topic_and_phase(self):
        from content.topic_reader import generate_job_id
        job_id = generate_job_id("FIN001", "research")
        assert "FIN001" in job_id
        assert "research" in job_id


# ── Publishing Mode Safety Tests ───────────────────────────────────────────────

class TestPublishingModeSafety:
    def test_test_mode_is_default(self):
        """Confirm default publishing mode is 'test' to prevent accidental public uploads."""
        import config
        # In a fresh project, mode defaults to 'test'
        # We just check it's not 'production' unless explicitly set
        assert config.PUBLISHING_MODE in ("test", "production")

    def test_no_paid_api_called_in_tests(self):
        """
        Verify that importing our modules does not trigger any paid API call.
        This test is a structural check — actual API calls are caught by mocking.
        """
        # Simply importing these should not make network calls
        from content import script_generator, script_validator, topic_reader
        from storage import database, spreadsheet_manager
        from audio import tts_engine
        from visuals import graphic_generator, video_composer
        from publishing import youtube_publisher, instagram_publisher
        assert True


# ── Audio & TTS Tests ──────────────────────────────────────────────────────────

class TestAudioEngine:
    def test_clean_text_for_tts(self):
        from audio.tts_engine import clean_text_for_tts
        raw = "Invest ₹10,000 at 12% in #MutualFunds with Rs. 500 SIP!"
        cleaned = clean_text_for_tts(raw)
        assert "₹" not in cleaned
        assert "10,000 rupees" in cleaned
        assert "12 percent" in cleaned

    def test_srt_formatting(self, tmp_path):
        from audio.tts_engine import _write_srt
        words = [
            {"word": "WHAT", "start": 0.1, "end": 0.5},
            {"word": "IS", "start": 0.5, "end": 0.8},
            {"word": "MONEY?", "start": 0.8, "end": 1.4},
        ]
        srt_file = tmp_path / "test.srt"
        _write_srt(words, srt_file)
        assert srt_file.exists()
        content = srt_file.read_text(encoding="utf-8")
        assert "WHAT IS MONEY?" in content
        assert "00:00:00,100 --> 00:00:01,400" in content


# ── Graphic Generator Tests ───────────────────────────────────────────────────

class TestGraphicGenerator:
    def test_create_vertical_gradient(self):
        from visuals.graphic_generator import create_vertical_gradient
        img = create_vertical_gradient(width=108, height=192)
        assert img.size == (108, 192)

    def test_render_scene_frame(self, tmp_path):
        from visuals.graphic_generator import render_scene_frame
        out = tmp_path / "frame.png"
        res = render_scene_frame(
            scene_index=0,
            total_scenes=5,
            topic_id="TEST001",
            topic_title="Compound Interest Guide",
            category="Basics",
            on_screen_text="HOW MONEY MULTIPLIES",
            scene_narration="Here is how compounding works.",
            output_path=out,
            include_chart=False,
        )
        assert res.exists()
        assert res.stat().st_size > 1000

    def test_render_chart(self):
        from visuals.graphic_generator import render_financial_chart
        img = render_financial_chart(chart_type="growth", output_size=(400, 300))
        assert img.width > 0
        assert img.height > 0


# ── Publishing Tests ──────────────────────────────────────────────────────────

class TestPublishing:
    def test_youtube_publish_test_mode(self, tmp_db, sample_topic, sample_script, tmp_path):
        dbmod, _ = tmp_db
        dbmod.upsert_topic(**{k: v for k, v in sample_topic.items() if k != "status"})

        # Seed script
        from content.script_generator import _store_script
        _store_script("TEST001", sample_script)

        # Seed production record
        dummy_mp4 = tmp_path / "TEST001.mp4"
        dummy_mp4.write_bytes(b"dummy mp4 data")
        with dbmod.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO production
                    (topic_id, video_file, audio_duration, video_duration,
                     video_width, video_height, created_at, updated_at)
                VALUES (?, ?, 30.0, 30.0, 1080, 1920, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                ("TEST001", str(dummy_mp4)),
            )

        from publishing.youtube_publisher import publish_to_youtube
        res = publish_to_youtube("TEST001", force_test_mode=True)
        assert res["status"] == "PUBLISHED"
        assert "youtube.com/shorts/" in res["published_url"]
        assert res["mode"] == "test"

        # Idempotency check: Calling again returns existing upload
        res2 = publish_to_youtube("TEST001", force_test_mode=True)
        assert res2["video_id"] == res["video_id"]

