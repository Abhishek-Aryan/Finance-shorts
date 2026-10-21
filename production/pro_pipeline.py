"""
Finance Shorts Pro — Full Production Pipeline
Orchestrates: Script (Gemini/OpenRouter) → Audio (TTS) → Video (HeyGen) → Compose → Verify → Publish
Split into two distinct steps:
- run_pro_pipeline: runs generation and composition up to final MP4
- verify_composed_video: validates duration, resolution, audio streams
- publish_composed: uploads to YouTube with category_id and privacy_status from config
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
from content.openrouter_generator import generate_pro_script
from audio.tts_engine import TTSEngine
from visuals.heygen_generator import generate_all_scenes
from visuals.cinematic_composer import compose_pro_video
from publishing.youtube_publisher import YouTubePublisher

logger = logging.getLogger(__name__)

SCENES_SUBDIR = "scenes"


def verify_composed_video(video_path: Path | str) -> dict:
    """
    Verifies that the video file exists and is a valid video:
    - ffprobe duration between 15 and 60 seconds
    - 1080x1920 resolution
    - at least one audio stream present
    Raises ValueError or FileNotFoundError if validation fails.
    """
    v_path = Path(video_path)
    if not v_path.exists():
        raise FileNotFoundError(f"Video file does not exist: {v_path}")
    if v_path.stat().st_size == 0:
        raise ValueError(f"Video file is empty (0 bytes): {v_path}")

    try:
        import ffmpeg
        probe = ffmpeg.probe(str(v_path))
    except Exception as e:
        raise ValueError(f"Failed to probe video file {v_path}: {e}")

    format_info = probe.get("format", {})
    streams = probe.get("streams", [])

    duration_str = format_info.get("duration")
    if not duration_str:
        raise ValueError(f"Video {v_path} has missing duration")
    duration = float(duration_str)

    if not (15.0 <= duration <= 60.0):
        raise ValueError(f"Video duration {duration:.1f}s is outside valid range [15s, 60s]")

    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not v_stream:
        raise ValueError(f"Video {v_path} contains no video stream")

    width = int(v_stream.get("width", 0))
    height = int(v_stream.get("height", 0))
    if width != 1080 or height != 1920:
        raise ValueError(f"Video resolution {width}x{height} does not match required 1080x1920")

    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not a_stream:
        raise ValueError(f"Video {v_path} contains no audio stream")

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "has_audio": True,
    }


def run_pro_pipeline(
    topic: str,
    category: str,
    objective: str,
    publish_now: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Complete generation pipeline for one topic (up to composition).
    Does NOT upload to YouTube or update schedule state.
    Returns result dict with status='composed', video_path, script, job_id.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    topic_slug = re.sub(r"[^a-z0-9]+", "_", topic.lower())[:40]
    job_id = f"{topic_slug}_{ts}"

    result = {
        "topic": topic,
        "category": category,
        "objective": objective,
        "job_id": job_id,
        "status": "started",
        "script": None,
        "audio_path": None,
        "scene_paths": [],
        "video_path": None,
        "youtube_url": None,
        "error": None,
    }

    job_dir = Path(config.OUTPUT_DIR) / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    scenes_dir = job_dir / SCENES_SUBDIR
    scenes_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ── Step 1: Script Generation ─────────────────────────────────────────
        logger.info("═══ [1/5] SCRIPT GENERATION: %s ═══", topic)
        script = generate_pro_script(
            topic=topic,
            category=category,
            learning_objective=objective,
        )
        result["script"] = script
        scenes = script.get("scenes", [])
        voiceover_text = script.get("full_voiceover", "")
        logger.info("Script generated: %d scenes | Voiceover: %d chars",
                    len(scenes), len(voiceover_text))

        script_file = job_dir / "script.json"
        with open(script_file, "w", encoding="utf-8") as f:
            json.dump(script, f, indent=2, ensure_ascii=False)

        # ── Step 2: TTS Audio ──────────────────────────────────────────────────
        logger.info("═══ [2/5] TTS AUDIO ═══")
        tts_engine = TTSEngine()
        audio_filename = f"{topic_slug}_audio.mp3"
        audio_output = job_dir / audio_filename

        tts_result = tts_engine.generate_speech(
            text=voiceover_text,
            output_filename=str(audio_output),
        )
        audio_path = Path(tts_result["audio_file"])
        srt_path = Path(tts_result.get("srt_file", "")) if tts_result.get("srt_file") else None
        total_duration = tts_result["duration_seconds"]

        result["audio_path"] = str(audio_path)
        result["duration"] = total_duration
        logger.info("TTS audio: %.1fs | SRT: %s", total_duration, srt_path)

        # ── Step 3: HeyGen Scene Videos ───────────────────────────────────────
        logger.info("═══ [3/5] HEYGEN SCENE VIDEOS (%d scenes) ═══", len(scenes))
        if dry_run:
            logger.info("[DRY RUN] Skipping HeyGen scene generation")
            scene_paths = [None] * len(scenes)
        else:
            scene_paths = generate_all_scenes(scenes, job_id, scenes_dir)

        result["scene_paths"] = [str(p) if p else None for p in scene_paths]
        ok_count = sum(1 for p in scene_paths if p and Path(p).exists())
        logger.info("Scenes generated: %d/%d OK", ok_count, len(scenes))

        # ── Step 4: Compose Final Video ───────────────────────────────────────
        logger.info("═══ [4/5] COMPOSING FINAL SHORT ═══")
        output_mp4 = job_dir / f"{topic_slug}_final.mp4"
        final_video = compose_pro_video(
            scene_video_paths=scene_paths,
            scene_data=scenes,
            audio_path=audio_path,
            srt_path=srt_path,
            output_mp4=output_mp4,
            total_duration=total_duration,
            topic_title=topic,
            category=category,
        )
        result["video_path"] = str(final_video)

        size_mb = final_video.stat().st_size / (1024 * 1024)
        logger.info("Final video: %s (%.2f MB)", final_video.name, size_mb)
        result["status"] = "composed"

        # Copy to output/videos for direct access
        try:
            dest_copy = config.OUTPUT_VIDEOS / f"{topic_slug}.mp4"
            shutil.copy(str(final_video), str(dest_copy))
        except Exception as ce:
            logger.warning("Could not copy to output/videos: %s", ce)

        return result

    except Exception as e:
        logger.error("Pipeline failed for [%s]: %s", topic, e, exc_info=True)
        result["status"] = "failed"
        result["error"] = str(e)
        return result


def _build_description(script: dict, topic: str, category: str) -> str:
    """Builds a rich YouTube description from the script."""
    desc = script.get("video_description", "")
    if not desc:
        desc = (
            f"In this Short: {topic}\n\n"
            f"Category: {category}\n\n"
            f"Key insight: {script.get('key_stat', '')}\n\n"
            "Follow for daily finance intelligence. 📊💰"
        )

    chapter_tags = script.get("chapter_tags", "")
    full_desc = f"{desc}\n\n{chapter_tags}\n\n"
    full_desc += "#Shorts #Finance #Investing #IndianMarkets #PersonalFinance #MoneyTips #StockMarket"
    return full_desc[:4950]  # YouTube limit is 5000 chars


def publish_composed(
    result: dict,
    dry_run: bool = False,
    privacy_status: str | None = None,
    category_id: str | None = None,
) -> dict:
    """
    Publishes a composed video result to YouTube:
    - Bypasses real upload and probing in test mode or dry_run
    - Verifies video file via verify_composed_video before real upload
    - Uses config.YOUTUBE_CATEGORY_ID and config.YOUTUBE_PRIVACY_STATUS
    Returns dict with video_id, url, published_url, status.
    """
    video_path = result.get("video_path")
    if not video_path:
        raise ValueError(f"No video_path found in result for {result.get('topic')}")

    topic = result["topic"]
    category = result.get("category", "Finance")
    script = result.get("script") or {}
    job_id = result.get("job_id", f"job_{int(time.time())}")

    privacy = privacy_status or config.YOUTUBE_PRIVACY_STATUS
    cat_id = category_id or str(config.YOUTUBE_CATEGORY_ID)

    if dry_run or config.PUBLISHING_MODE == "test":
        mock_id = f"TEST-{job_id}"
        mock_url = f"https://youtube.com/shorts/{mock_id}"
        logger.info("[DRY RUN / TEST] Skipped YouTube upload. Assigned mock video ID: %s (%s)", mock_id, mock_url)
        return {
            "video_id": mock_id,
            "youtube_video_id": mock_id,
            "url": mock_url,
            "published_url": mock_url,
            "mode": "test",
            "status": "published",
        }

    verify_composed_video(video_path)

    logger.info("═══ PUBLISHING TO YOUTUBE: %s ═══", topic)
    title = script.get("video_title", topic)[:100]
    description = _build_description(script, topic, category)
    tags = script.get("tags", ["finance", "investing", "india", "shorts"])

    publisher = YouTubePublisher()
    yt_result = publisher.upload(
        video_path=str(video_path),
        title=title,
        description=description,
        tags=tags,
        category_id=cat_id,
        privacy=privacy,
    )
    video_id = yt_result.get("video_id") or yt_result.get("id")
    url = yt_result.get("published_url") or f"https://youtube.com/shorts/{video_id}"
    logger.info("Published to YouTube: %s -> %s", title[:50], url)

    return {
        "video_id": video_id,
        "youtube_video_id": video_id,
        "url": url,
        "published_url": url,
        "mode": "production",
        "status": "published",
    }
