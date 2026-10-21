"""
Finance Shorts Pro - HeyGen Video Generation via OpenRouter
Generates cinematic AI video clips per scene using HeyGen via OpenRouter API.
Handles submission, polling, download, and vertical 1080x1920 conversion.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import requests
import subprocess

import config

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = getattr(config, "OPENROUTER_API_KEY", "") or os.environ.get("OPENROUTER_API_KEY", "")
OR_BASE = "https://openrouter.ai/api/v1"
OR_VIDEOS_URL = f"{OR_BASE}/videos"
HEYGEN_MODEL = getattr(config, "VIDEO_MODEL", "heygen/heygen-video-1")

POLL_INTERVAL_SEC = 8
MAX_POLL_ATTEMPTS = 90  # 12 minutes max


def generate_scene_video(
    prompt: str,
    scene_number: int,
    topic_id: str,
    output_dir: Path,
    duration_hint: int = 8,
) -> Path | None:
    """
    Generates a single cinematic scene video using HeyGen via OpenRouter.
    Converts to vertical 1080x1920 and returns the path, or None on failure.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_path = output_dir / f"scene_{scene_number:02d}_raw.mp4"
    final_path = output_dir / f"scene_{scene_number:02d}.mp4"

    # Skip if already generated
    if final_path.exists() and final_path.stat().st_size > 50_000:
        logger.info("Scene %d for %s already exists, skipping generation.", scene_number, topic_id)
        return final_path

    # Enhance prompt for cinematic quality and vertical framing
    enhanced_prompt = (
        f"{prompt} "
        "Cinematic 4K quality, dramatic lighting, vertical 9:16 framing, "
        "dark moody atmosphere, gold color grading, professional film look, "
        "smooth camera motion, depth of field bokeh."
    )[:500]  # HeyGen prompt limit

    logger.info("Submitting HeyGen scene %d for [%s]: %s...", scene_number, topic_id, enhanced_prompt[:60])

    # Submit video generation
    try:
        resp = requests.post(
            OR_VIDEOS_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "X-Title": "FinanceShortsChannel",
            },
            json={
                "model": HEYGEN_MODEL,
                "prompt": enhanced_prompt,
            },
            timeout=30,
        )
        resp.raise_for_status()
        job = resp.json()
        job_id = job.get("id")
        poll_url = job.get("polling_url")
        logger.info("HeyGen job submitted: %s (scene %d)", job_id, scene_number)
    except Exception as e:
        logger.error("Failed to submit HeyGen job for scene %d: %s", scene_number, e)
        return None

    # Poll until complete
    for attempt in range(MAX_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL_SEC)
        try:
            status_resp = requests.get(
                poll_url,
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                timeout=20,
            )
            status_data = status_resp.json()
            status = status_data.get("status", "unknown")

            if attempt % 5 == 0:
                logger.info("[%s] Scene %d status: %s (attempt %d/%d)",
                            topic_id, scene_number, status, attempt + 1, MAX_POLL_ATTEMPTS)

            if status == "completed":
                video_urls = status_data.get("unsigned_urls") or status_data.get("urls", [])
                if not video_urls:
                    logger.error("Completed but no video URLs in response for scene %d", scene_number)
                    return None

                # Download raw video
                download_url = video_urls[0]
                downloaded = _download_video(download_url, raw_path)
                if not downloaded:
                    return None

                # Convert to vertical 1080x1920
                converted = _convert_to_vertical(raw_path, final_path, duration_hint)
                raw_path.unlink(missing_ok=True)
                return final_path if converted else None

            elif status == "failed":
                err = status_data.get("error", "Unknown error")
                logger.error("HeyGen generation failed for scene %d: %s", scene_number, err)
                return None

        except Exception as e:
            logger.warning("Poll attempt %d error for scene %d: %s", attempt + 1, scene_number, e)

    logger.error("HeyGen generation timed out for scene %d of %s", scene_number, topic_id)
    return None


def _download_video(url: str, dest: Path) -> bool:
    """Downloads video from URL to dest path."""
    try:
        # If it's a relative OpenRouter URL, add the auth header
        headers = {}
        if "openrouter.ai" in url:
            headers["Authorization"] = f"Bearer {OPENROUTER_API_KEY}"

        resp = requests.get(url, headers=headers, stream=True, timeout=120)
        resp.raise_for_status()

        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=16384):
                f.write(chunk)

        size = dest.stat().st_size
        logger.info("Downloaded scene video: %s (%.1f KB)", dest.name, size / 1024)
        return size > 10_000
    except Exception as e:
        logger.error("Video download failed: %s", e)
        return False


def _convert_to_vertical(raw: Path, out: Path, target_duration: int = 8) -> bool:
    """
    Converts any resolution video to 1080x1920 vertical with black bars,
    slight zoom for cinematic feel, and loops/trims to target_duration.
    """
    try:
        # Get source dimensions
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=width,height,duration",
             "-of", "json", str(raw)],
            capture_output=True, text=True
        )
        import json
        probe_data = json.loads(probe.stdout)
        src_dur = float(probe_data["streams"][0].get("duration", 5))
        src_w = probe_data["streams"][0].get("width", 1920)
        src_h = probe_data["streams"][0].get("height", 1080)

        # HeyGen generates 1344x768 landscape — we need 1080x1920 portrait
        # Strategy: pad to square, crop center, scale to 1080x1920, add vignette
        if src_dur < target_duration:
            # Loop the video to fill target duration
            loop_count = int(target_duration / src_dur) + 2
            vf_input = f"loop={loop_count}:size={int(src_dur * 24)},trim=duration={target_duration}"
        else:
            vf_input = f"trim=duration={target_duration},setpts=PTS-STARTPTS"

        vf_chain = (
            f"{vf_input},"
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            "setsar=1,"
            "fps=30"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(raw),
            "-vf", vf_chain,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-an",  # No audio in individual scenes (added in final compose step)
            str(out)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("FFmpeg conversion failed: %s", result.stderr[-300:])
            return False

        logger.info("Converted to vertical: %s", out.name)
        return True

    except Exception as e:
        logger.error("Video conversion failed: %s", e)
        return False


def generate_all_scenes(
    scenes: list[dict],
    topic_id: str,
    output_dir: Path,
) -> list[Path]:
    """
    Generates all scene videos in sequence (HeyGen has no parallel limit, but
    sequential is more stable and predictable). Returns list of scene paths.
    """
    output_dir = Path(output_dir)
    generated = []

    for scene in scenes:
        n = scene.get("scene_number", len(generated) + 1)
        prompt = scene.get("heygen_video_prompt", "")
        dur = scene.get("duration_sec", 8)

        if not prompt:
            logger.warning("No HeyGen prompt for scene %d, skipping.", n)
            generated.append(None)
            continue

        scene_path = generate_scene_video(
            prompt=prompt,
            scene_number=n,
            topic_id=topic_id,
            output_dir=output_dir,
            duration_hint=dur,
        )
        generated.append(scene_path)
        logger.info("Scene %d/%d complete: %s", n, len(scenes), "OK" if scene_path else "FAILED")

    success_count = sum(1 for p in generated if p)
    logger.info("Generated %d/%d scenes for %s", success_count, len(scenes), topic_id)
    return generated
