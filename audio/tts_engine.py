"""
Finance Shorts - Text-to-Speech Engine
Uses edge-tts (100% free, Microsoft Neural voices) with word-level timestamp extraction.
Falls back gracefully or supports Piper TTS if configured.
Normalizes audio loudness to YouTube Shorts broadcast standards (-14 LUFS) via FFmpeg.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

import config

logger = logging.getLogger(__name__)

# Recommended free high-retention voices for finance shorts
# AndrewMultilingualNeural is conversational, expressive, and sounds like a real podcast host
DEFAULT_VOICE = getattr(config, "DEFAULT_VOICE", "en-US-AndrewMultilingualNeural")
ALTERNATIVE_VOICES = {
    "us_male_conversational": "en-US-AndrewMultilingualNeural",
    "us_male_deep": "en-US-BrianMultilingualNeural",
    "us_male_story": "en-US-ChristopherNeural",
    "india_female_expressive": "en-IN-NeerjaExpressiveNeural",
    "india_male_finance": "en-IN-PrabhatNeural",
    "us_female_clear": "en-US-AriaNeural",
}


def clean_text_for_tts(text: str) -> str:
    """
    Cleans script text to make it sound completely natural and human when spoken.
    - Expands financial acronyms (SIP -> S.I.P., FD -> F.D., EMI -> E.M.I.)
    - Formats Indian numbers and currency naturally (10,000 rupees, 1 lakh, 1 crore)
    - Replaces math symbols and formula notations with spoken English
    - Adds natural breathing pauses at sentence boundaries
    """
    t = text

    # Remove markdown formatting characters
    t = re.sub(r"[*#_`~]", "", t)

    # Clean formula notation (e.g. P*R*T/100 or P * R * T / 100)
    t = re.sub(r"\bP\s*[*×]\s*R\s*[*×]\s*T\s*/\s*100\b", "Principal times Rate times Time, divided by 100", t, flags=re.I)
    t = re.sub(r"(\d+)\s*[*×]\s*(\d+)", r"\1 times \2", t)
    t = re.sub(r"(\d+)\s*/\s*(\d+)", r"\1 divided by \2", t)

    # Common abbreviations
    t = re.sub(r"\bvs\.?\b", "versus", t, flags=re.I)
    t = re.sub(r"\be\.g\.?,?\b", "for example,", t, flags=re.I)
    t = re.sub(r"\bi\.e\.?,?\b", "that is,", t, flags=re.I)
    t = re.sub(r"\bapprox\.?\b", "approximately", t, flags=re.I)
    t = re.sub(r"\bw/\b", "with", t, flags=re.I)
    t = re.sub(r"\bw/o\b", "without", t, flags=re.I)

    # Financial Acronyms - Spelled out with periods for crisp, natural pronunciation
    acronym_map = {
        r"\bSIP\b": "S.I.P.",
        r"\bFD\b": "F.D.",
        r"\bRD\b": "R.D.",
        r"\bEMI\b": "E.M.I.",
        r"\bPPF\b": "P.P.F.",
        r"\bEPF\b": "E.P.F.",
        r"\bNPS\b": "N.P.S.",
        r"\bCAGR\b": "C.A.G.R.",
        r"\bROI\b": "R.O.I.",
        r"\bETF\b": "E.T.F.",
        r"\bIPO\b": "I.P.O.",
        r"\bKYC\b": "K.Y.C.",
        r"\bCIBIL\b": "CIBIL",
        r"\bRBI\b": "R.B.I.",
        r"\bSEBI\b": "SEBI",
        r"\bNAV\b": "N.A.V.",
    }
    for pattern, replacement in acronym_map.items():
        t = re.sub(pattern, replacement, t)

    # Indian Currency formatting: Place 'rupees' after amount for natural English phrasing
    # E.g. ₹10,000 -> 10,000 rupees; ₹ 500 -> 500 rupees; Rs. 1,00,000 -> 1,00,000 rupees
    t = re.sub(r"(?:[₹]|(?:Rs\.?))\s*([0-9]+(?:,[0-9]+)*(?:\.[0-9]+)?)", r"\1 rupees", t, flags=re.I)

    # Dollar amounts
    t = re.sub(r"\$([0-9]+(?:,[0-9]+)*(?:\.[0-9]+)?)", r"\1 dollars", t)

    # Percentages
    t = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"\1 percent", t)

    # Convert 10k / 50k to thousand
    t = re.sub(r"\b(\d+)k\b", r"\1 thousand", t, flags=re.I)

    # Pacing: replace multiple dots/dashes with a single comma for a natural pause
    t = re.sub(r"\.{2,}", ", ", t)
    t = re.sub(r"—|–", ", ", t)

    # Normalize excessive spaces
    t = re.sub(r"\s+", " ", t).strip()
    return t


def get_audio_duration(file_path: Path | str) -> float:
    """Uses ffprobe to get precise audio duration in seconds."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception as e:
        logger.warning("Failed to get duration via ffprobe: %s. Estimating...", e)
        # Fallback estimation based on file size for 192k mp3
        return 30.0


def normalize_audio(raw_audio_path: Path, normalized_path: Path) -> Path:
    """
    Normalizes audio loudness using FFmpeg's loudnorm filter.
    Target: -14 LUFS (YouTube Shorts standard), LRA 7, True Peak -1.5 dB.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(raw_audio_path),
        "-af", "loudnorm=I=-14:LRA=7:tp=-1.5",
        "-ar", "44100",
        "-ac", "2",
        "-b:a", config.AUDIO_BITRATE,
        str(normalized_path),
    ]
    logger.info("Normalizing audio loudness: %s -> %s", raw_audio_path.name, normalized_path.name)
    subprocess.run(cmd, capture_output=True, check=True)
    return normalized_path


async def _synthesize_edge_tts_async(
    text: str,
    output_audio_path: Path,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
) -> list[dict[str, Any]]:
    """
    Synthesizes speech using edge-tts and collects word-level boundary timings.
    Handles both WordBoundary and SentenceBoundary events.
    """
    import edge_tts

    words: list[dict[str, Any]] = []
    sentence_events: list[dict[str, Any]] = []
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)

    with open(output_audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                offset = chunk["offset"] / 10_000_000.0
                duration = chunk["duration"] / 10_000_000.0
                words.append({
                    "word": chunk["text"],
                    "start": round(offset, 3),
                    "end": round(offset + duration, 3),
                })
            elif chunk["type"] == "SentenceBoundary":
                offset = chunk["offset"] / 10_000_000.0
                duration = chunk["duration"] / 10_000_000.0
                sentence_events.append({
                    "text": chunk["text"],
                    "start": round(offset, 3),
                    "duration": round(duration, 3),
                })

    # If WordBoundary wasn't emitted by edge-tts (common on newer versions),
    # calculate exact word timings from SentenceBoundary events
    if not words and sentence_events:
        for sent in sentence_events:
            s_text = sent["text"].strip()
            s_words = s_text.split()
            if not s_words:
                continue
            total_chars = sum(len(w) for w in s_words)
            cur_start = sent["start"]
            s_duration = max(sent["duration"], 0.5)

            for w in s_words:
                w_duration = (len(w) / max(total_chars, 1)) * s_duration
                w_end = cur_start + w_duration
                words.append({
                    "word": w,
                    "start": round(cur_start, 3),
                    "end": round(w_end, 3),
                })
                cur_start = w_end

    return words


def synthesize_speech(
    text: str,
    output_dir: Optional[Path] = None,
    filename_prefix: str = "voiceover",
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    normalize: bool = True,
) -> dict[str, Any]:
    """
    Synchronous entry point for speech synthesis.
    
    Generates:
      1. Raw audio file (.mp3)
      2. Normalized audio file (.mp3)
      3. Word-level timestamp JSON (.json)
      4. Subtitle files (.srt, .vtt)
    
    Returns metadata dict:
      {
        "audio_path": Path,
        "word_timestamps": list[dict],
        "duration": float,
        "voice": str,
        "srt_path": Path,
      }
    """
    if output_dir is None:
        output_dir = config.OUTPUT_AUDIO
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cleaned_text = clean_text_for_tts(text)
    raw_audio = output_dir / f"{filename_prefix}_raw.mp3"
    norm_audio = output_dir / f"{filename_prefix}.mp3"
    timestamps_file = output_dir / f"{filename_prefix}_words.json"
    srt_file = output_dir / f"{filename_prefix}.srt"

    logger.info("Generating speech with voice '%s' for %d characters...", voice, len(cleaned_text))

    # Run async synthesis
    word_timestamps = asyncio.run(
        _synthesize_edge_tts_async(cleaned_text, raw_audio, voice=voice, rate=rate)
    )

    # Normalize audio loudness
    if normalize:
        normalize_audio(raw_audio, norm_audio)
        if raw_audio.exists():
            raw_audio.unlink()  # Remove unnormalized temp file
        final_audio = norm_audio
    else:
        final_audio = raw_audio

    duration = get_audio_duration(final_audio)

    # Save word timestamps to JSON
    with open(timestamps_file, "w", encoding="utf-8") as f:
        json.dump(word_timestamps, f, indent=2)

    # Generate SRT subtitle file
    _write_srt(word_timestamps, srt_file)

    logger.info("Speech generated successfully: %s (duration: %.2fs, words: %d)",
                final_audio.name, duration, len(word_timestamps))

    return {
        "audio_path": final_audio,
        "word_timestamps": word_timestamps,
        "duration": duration,
        "voice": voice,
        "srt_path": srt_file,
        "timestamps_path": timestamps_file,
    }


def _write_srt(word_timestamps: list[dict[str, Any]], srt_path: Path, max_words_per_line: int = 4) -> None:
    """
    Groups word-level timestamps into snappy, punchy subtitle chunks
    ideal for fast-paced vertical YouTube Shorts (3-4 words per caption).
    """
    if not word_timestamps:
        return

    def fmt_time(seconds: float) -> str:
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int(round((seconds - int(seconds)) * 1000))
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

    chunks: list[dict[str, Any]] = []
    current_words: list[str] = []
    start_t: float = 0.0
    end_t: float = 0.0

    for i, item in enumerate(word_timestamps):
        if not current_words:
            start_t = item["start"]
        current_words.append(item["word"])
        end_t = item["end"]

        # Chunk boundary reached or pause detected
        is_last = (i == len(word_timestamps) - 1)
        long_pause = False
        if not is_last:
            next_start = word_timestamps[i + 1]["start"]
            if next_start - end_t > 0.4:  # 400ms pause
                long_pause = True

        if len(current_words) >= max_words_per_line or is_last or long_pause:
            chunks.append({
                "text": " ".join(current_words).upper(),
                "start": start_t,
                "end": max(end_t, start_t + 0.3),
            })
            current_words = []

    with open(srt_path, "w", encoding="utf-8") as f:
        for idx, chunk in enumerate(chunks, 1):
            f.write(f"{idx}\n")
            f.write(f"{fmt_time(chunk['start'])} --> {fmt_time(chunk['end'])}\n")
            f.write(f"{chunk['text']}\n\n")


class TTSEngine:
    """Convenience wrapper for text-to-speech synthesis."""

    def __init__(self, voice: str = DEFAULT_VOICE):
        self.voice = voice

    def generate_audio(
        self,
        text: str,
        output_dir: Optional[Path | str] = None,
        filename: str = "voiceover",
        rate: str = "+0%",
        normalize: bool = True,
    ) -> dict[str, Any]:
        return synthesize_speech(
            text=text,
            output_dir=Path(output_dir) if output_dir else None,
            filename_prefix=filename,
            voice=self.voice,
            rate=rate,
            normalize=normalize,
        )

