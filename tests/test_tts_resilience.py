"""
Unit and Integration Tests for TTS Engine Resilience.
Tests:
- Edge-TTS multi-voice pool rotation on failure
- Automatic fallback to Google TTS (gTTS) when all Edge voices fail
- Word timestamp generation and SRT production
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from audio.tts_engine import (
    TTSEngine,
    VOICE_FAILOVER_CANDIDATES,
    synthesize_speech,
    _synthesize_gtts_fallback,
    _write_srt,
)


def test_voice_pool_contains_failover_voices():
    """Verify that the failover voice pool has multiple high quality voices."""
    assert len(VOICE_FAILOVER_CANDIDATES) >= 3
    assert "en-US-AndrewMultilingualNeural" in VOICE_FAILOVER_CANDIDATES
    assert "en-US-ChristopherNeural" in VOICE_FAILOVER_CANDIDATES
    assert "en-US-GuyNeural" in VOICE_FAILOVER_CANDIDATES


def test_edge_tts_rotates_through_voice_pool_on_failure(tmp_path):
    """
    Test that if the primary voice fails, _synthesize_edge_tts_async
    retries with subsequent voices in the candidates list.
    """
    import asyncio
    from audio.tts_engine import _synthesize_edge_tts_async
    raw_mp3 = tmp_path / "raw.mp3"

    attempted_voices = []

    async def mock_single(text, out_path, voice, rate):
        attempted_voices.append(voice)
        if len(attempted_voices) < 3:
            raise RuntimeError(f"Simulated network drop for {voice}")
        out_path.write_bytes(b"dummy audio data " * 100)
        return [{"word": "Test", "start": 0.0, "end": 0.5}]

    with patch("audio.tts_engine._synthesize_edge_tts_single", side_effect=mock_single), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        words = asyncio.run(_synthesize_edge_tts_async("Test script text", raw_mp3))

        assert len(attempted_voices) >= 3
        assert attempted_voices[0] == VOICE_FAILOVER_CANDIDATES[0]
        assert raw_mp3.exists()
        assert len(words) == 1


def test_gtts_emergency_fallback_engaged_when_all_edge_voices_fail(tmp_path):
    """
    Test that synthesize_speech catches all Edge-TTS exceptions and
    falls back cleanly to _synthesize_gtts_fallback.
    """
    with patch("asyncio.run", side_effect=RuntimeError("Edge-TTS servers unreachable")), \
         patch("audio.tts_engine._synthesize_gtts_fallback") as mock_gtts, \
         patch("audio.tts_engine.get_audio_duration", return_value=5.0), \
         patch("audio.tts_engine.normalize_audio"):

        mock_gtts.return_value = [
            {"word": "Test", "start": 0.0, "end": 0.5},
            {"word": "fallback", "start": 0.5, "end": 1.0},
        ]

        result = synthesize_speech(
            text="Test fallback",
            output_dir=tmp_path,
            filename_prefix="test_fallback",
            normalize=False,
        )

        assert mock_gtts.called
        assert len(result["word_timestamps"]) == 2
        assert result["duration"] == 5.0


def test_srt_file_generation_from_word_boundaries(tmp_path):
    """Test that SRT kinetic subtitles are formatted correctly from word boundaries."""
    words = [
        {"word": "Welcome", "start": 0.0, "end": 0.5},
        {"word": "to", "start": 0.51, "end": 0.8},
        {"word": "finance", "start": 0.81, "end": 1.4},
    ]
    srt_path = tmp_path / "test.srt"
    _write_srt(words, srt_path)

    assert srt_path.exists()
    content = srt_path.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:01,400" in content
    assert "WELCOME TO FINANCE" in content
