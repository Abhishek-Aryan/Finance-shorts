"""
Finance Shorts Pro — Full Production Pipeline
Orchestrates: Script (MiniMax) → Audio (TTS) → Video (HeyGen) → Compose → Publish → Mark Done
This is the main end-to-end pipeline for a single topic.
"""

from __future__ import annotations

import json
import logging
import os
import re
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
from storage.schedule_manager import mark_topic_done

logger = logging.getLogger(__name__)

SCENES_SUBDIR = "scenes"


def run_pro_pipeline(
    topic: str,
    category: str,
    objective: str,
    publish_now: bool = True,
    dry_run: bool = False,
) -> dict:
    """
    Complete pipeline for one topic:
    1. Generate script (MiniMax M3.1 Flash via OpenRouter)
    2. Generate TTS audio (Edge-TTS Andrew Multilingual Neural)
    3. Generate scene videos (HeyGen via OpenRouter)
    4. Compose final vertical Short
    5. Publish to YouTube
    6. Mark Excel schedule as Done
    Returns result dict with status, video_path, youtube_url.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    topic_slug = re.sub(r"[^a-z0-9]+", "_", topic.lower())[:40]
    job_id = f"{topic_slug}_{ts}"

    result = {
        "topic": topic, "category": category, "job_id": job_id,
        "status": "started", "script": None,
        "audio_path": None, "scene_paths": [],
        "video_path": None, "youtube_url": None, "error": None,
    }

    # ── Directories ────────────────────────────────────────────────────────────
    job_dir = Path(config.OUTPUT_DIR) / "jobs" / job_id
    scenes_dir = job_dir / SCENES_SUBDIR
    scenes_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ── Step 1: Generate Script ────────────────────────────────────────────
        logger.info("═══ [1/5] SCRIPT GENERATION: %s ═══", topic)
        script = generate_pro_script(topic, category, objective)
        result["script"] = script
        script_path = job_dir / "script.json"
        script_path.write_text(json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Script generated: %d scenes | Voiceover: %d chars",
                    len(script.get("scenes", [])),
                    len(script.get("full_voiceover", "")))

        # ── Step 2: TTS Audio ──────────────────────────────────────────────────
        logger.info("═══ [2/5] TTS AUDIO ═══")
        tts = TTSEngine()
        full_voiceover = script.get("full_voiceover", f"This video is about {topic}.")
        audio_result = tts.generate_audio(
            text=full_voiceover,
            output_dir=str(job_dir),
            filename=f"{topic_slug}_audio",
        )
        audio_path = Path(audio_result["audio_path"])
        srt_path = Path(audio_result.get("srt_path", "")) if audio_result.get("srt_path") else None
        total_duration = audio_result.get("duration", 45.0)
        result["audio_path"] = str(audio_path)
        logger.info("TTS audio: %.1fs | SRT: %s", total_duration, srt_path)

        # ── Step 3: HeyGen Scene Videos ───────────────────────────────────────
        logger.info("═══ [3/5] HEYGEN SCENE VIDEOS (6 scenes) ═══")
        scenes = script.get("scenes", [])
        if not scenes:
            raise ValueError("No scenes in generated script")

        if dry_run:
            logger.info("DRY RUN: Skipping HeyGen generation")
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

        # ── Step 5: Publish to YouTube ────────────────────────────────────────
        if publish_now and not dry_run:
            logger.info("═══ [5/5] PUBLISHING TO YOUTUBE ═══")
            title = script.get("video_title", topic)[:100]
            description = _build_description(script, topic, category)
            tags = script.get("tags", ["finance", "investing", "india", "shorts"])

            publisher = YouTubePublisher()
            yt_result = publisher.upload(
                video_path=str(final_video),
                title=title,
                description=description,
                tags=tags,
                category_id="27",  # Education
                privacy="public",
            )
            yt_url = yt_result.get("published_url") or f"https://youtube.com/shorts/{yt_result.get('id', '')}"
            result["youtube_url"] = yt_url
            logger.info("Published: %s → %s", title[:50], yt_url)

            # Copy to output/videos for direct access
            try:
                dest_copy = config.OUTPUT_VIDEOS / f"{topic_slug}.mp4"
                import shutil
                shutil.copy(str(final_video), str(dest_copy))
            except Exception as ce:
                logger.warning("Could not copy to output/videos: %s", ce)

            # ── Step 6: Mark Done in Excel ────────────────────────────────────
            script_summary = script.get("full_voiceover", "")[:450]
            mark_topic_done(topic, script_summary)
            result["status"] = "published"
        else:
            logger.info("Skipping publish (publish_now=%s, dry_run=%s)", publish_now, dry_run)
            result["status"] = "composed"

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
