"""
Tests for Phase 5: Content Quality (fix 15)
- check_hook_uniqueness detects matching hooks in first 8 words
- Case, punctuation, and extra whitespace do not bypass hook detection
- Generator retries on duplicate hook and accepts unique candidate
- Generator accepts least similar candidate after 3 failures with warning
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from content.script_validator import check_hook_uniqueness, extract_hook_words
from content.openrouter_generator import generate_pro_script


def test_check_hook_uniqueness_with_shared_hook():
    """Two scripts sharing the first 8 words trigger a duplicate hook error."""
    script_a = {
        "voiceover_hook": "Most investors do not realize how inflation silently kills their wealth",
        "scenes": [{"voiceover": "Most investors do not realize how inflation silently kills their wealth."}],
    }
    script_b = {
        "voiceover_hook": "Most investors do not realize how inflation silently kills savings every single year.",
        "scenes": [{"voiceover": "Most investors do not realize how inflation silently kills savings."}],
    }

    # First 8 words for script_a: ['most', 'investors', 'do', 'not', 'realize', 'how', 'inflation', 'silently']
    # First 8 words for script_b: ['most', 'investors', 'do', 'not', 'realize', 'how', 'inflation', 'silently']
    err = check_hook_uniqueness(script_b, [script_a])
    assert err is not None
    assert "Duplicate hook detected" in err or "Duplicate hook" in err


def test_check_hook_uniqueness_with_punctuation_and_casing():
    """Punctuation, casing, and spacing differences are stripped before comparison."""
    recent = ["Most Investors Don't Realize: Why Stock Valuation Ratios Matter!"]
    candidate = {"voiceover_hook": "most investors dont realize why stock valuation ratios matter"}

    err = check_hook_uniqueness(candidate, recent)
    assert err is not None


def test_check_hook_uniqueness_with_distinct_hooks():
    """Distinct hooks return None (no error)."""
    recent = ["Most investors do not realize how inflation kills wealth"]
    candidate = {"voiceover_hook": "Did you know that 90 percent of traders lose money?"}

    err = check_hook_uniqueness(candidate, recent)
    assert err is None


def test_generator_retries_on_duplicate_hook(monkeypatch):
    """Generator loop retries when candidate hook matches recent scripts and accepts unique candidate on retry."""
    recent_scripts = ["Most investors do not realize how inflation kills their money"]

    # First attempt: returns duplicate hook
    dup_script = {
        "video_title": "Dup Title",
        "voiceover_hook": "Most investors do not realize how inflation kills their cash",
        "scenes": [{"voiceover": "Most investors do not realize how inflation kills their cash"}],
    }

    # Second attempt: returns unique hook
    unique_script = {
        "video_title": "Unique Title",
        "voiceover_hook": "In 2008, one simple number predicted the entire market collapse",
        "scenes": [{"voiceover": "In 2008, one simple number predicted the entire market collapse"}],
    }

    call_count = 0
    instructions_received = []

    def mock_single_script(topic, category, objective, extra_instruction=""):
        nonlocal call_count
        call_count += 1
        instructions_received.append(extra_instruction)
        if call_count == 1:
            return dict(dup_script)
        return dict(unique_script)

    monkeypatch.setattr("content.openrouter_generator._generate_single_script", mock_single_script)

    result = generate_pro_script("Topic", "Cat", "Obj", recent_scripts=recent_scripts)
    assert result["voiceover_hook"] == unique_script["voiceover_hook"]
    assert call_count == 2
    assert "Do not begin with 'Most investors don't realize'" in instructions_received[1]


def test_generator_accepts_least_similar_after_3_failures(monkeypatch):
    """After 3 failed uniqueness checks, generator logs WARNING and accepts candidate with least overlap."""
    recent_scripts = ["Most investors do not realize how inflation kills their savings"]

    cands = [
        {"voiceover_hook": "Most investors do not realize how inflation kills their cash immediately", "id": 1, "scenes": []},
        {"voiceover_hook": "Most investors do not realize how inflation kills their debt completely", "id": 2, "scenes": []},
        {"voiceover_hook": "Most investors do not realize how inflation kills their bonds over time", "id": 3, "scenes": []},
    ]
    idx = 0

    def mock_single_script(topic, category, objective, extra_instruction=""):
        nonlocal idx
        res = dict(cands[idx])
        idx += 1
        return res

    monkeypatch.setattr("content.openrouter_generator._generate_single_script", mock_single_script)

    with patch("content.openrouter_generator.logger.warning") as mock_warn:
        chosen = generate_pro_script("Topic", "Cat", "Obj", recent_scripts=recent_scripts)
        assert chosen is not None
        assert mock_warn.called
        assert "After 3 attempts" in mock_warn.call_args[0][0]
