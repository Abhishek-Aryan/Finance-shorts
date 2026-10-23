"""
Finance Shorts Pro - Google Veo Video Provider
Implements SceneVideoProvider for Google Veo models via the Gemini API (ai.google.dev).
Features:
- Full support for 9:16 portrait video generation
- Batch submission of all scenes before polling to respect 60-minute job window
- Exponential backoff retry on transient 429/500/503 errors
- Immediate QuotaExceeded failure on resource exhausted errors
- Cost guard enforcing daily and per-run video generation caps (Exit Code 5)
- Automated ffmpeg conversion & ffprobe verification
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import subprocess
import time
from typing import Any
from zoneinfo import ZoneInfo

import requests

import config
from visuals.video_provider import (
    BudgetCapReached,
    ProviderTimeout,
    QuotaExceeded,
    SceneVideoProvider,
    VideoProviderError,
)

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
COST_PER_SECOND = 0.10  # Veo 3.1 Fast baseline estimate (~$0.10/sec for 720p portrait)


def _load_ledger(ledger_path: Path) -> dict:
    if not ledger_path.exists():
        return {"version": 1, "daily_usage": {}}
    try:
        with open(ledger_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Could not read usage ledger (%s), initializing empty: %s", ledger_path, e)
        return {"version": 1, "daily_usage": {}}


def _save_ledger(ledger_path: Path, data: dict) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = ledger_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, ledger_path)


class VeoProvider(SceneVideoProvider):
    """Google Veo Video Provider via Gemini API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        ledger_path: Path | None = None,
        timeout_seconds: int | None = None,
        max_scene_seconds: int | None = None,
    ) -> None:
        self.api_key = api_key or getattr(config, "GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
        self.model = model or getattr(config, "VEO_MODEL", "veo-3.1-fast-generate-preview")
        self.ledger_path = ledger_path or getattr(config, "USAGE_LEDGER_FILE", config.ROOT_DIR / "data" / "usage_ledger.json")
        self.timeout_seconds = timeout_seconds or getattr(config, "VEO_TIMEOUT_SECONDS", 300)
        self.max_scene_seconds = max_scene_seconds or getattr(config, "VEO_MAX_SCENE_SECONDS", 5)
        self.max_daily_seconds = getattr(config, "VEO_MAX_SECONDS_PER_DAY", 60)
        self.max_run_seconds = getattr(config, "VEO_MAX_SECONDS_PER_RUN", 60)

    @property
    def supported_features(self) -> list[str]:
        return ["text_to_video", "image_conditioning", "aspect_ratio_9_16"]

    def estimate_cost(self, scenes: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculates total seconds and estimated USD cost for the scenes."""
        total_seconds = 0
        for scene in scenes:
            dur = scene.get("duration_sec", self.max_scene_seconds)
            total_seconds += int(dur)
        cost_usd = round(total_seconds * COST_PER_SECOND, 4)
        return {
            "total_seconds": total_seconds,
            "estimated_cost_usd": cost_usd,
            "scenes_count": len(scenes),
            "cost_per_second": COST_PER_SECOND,
        }

    def check_cost_guard(self, scenes: list[dict[str, Any]]) -> dict[str, Any]:
        """Verifies current run will not violate per-run or daily caps."""
        est = self.estimate_cost(scenes)
        run_sec = est["total_seconds"]

        if run_sec > self.max_run_seconds:
            msg = (
                f"Video run duration ({run_sec}s) exceeds configured per-run limit "
                f"VEO_MAX_SECONDS_PER_RUN ({self.max_run_seconds}s). Budget cap reached."
            )
            logger.warning(msg)
            raise BudgetCapReached(msg)

        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        ledger = _load_ledger(self.ledger_path)
        daily_record = ledger.get("daily_usage", {}).get(today_str, {})
        used_today = daily_record.get("total_seconds", 0)

        if used_today + run_sec > self.max_daily_seconds:
            msg = (
                f"Video daily usage ({used_today}s used + {run_sec}s requested = {used_today + run_sec}s) "
                f"exceeds VEO_MAX_SECONDS_PER_DAY ({self.max_daily_seconds}s). Budget cap reached."
            )
            logger.warning(msg)
            raise BudgetCapReached(msg)

        return est

    def record_usage(self, topic_id: str, actual_seconds: int, cost_usd: float) -> None:
        """Records video generation seconds and costs into data/usage_ledger.json."""
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        ledger = _load_ledger(self.ledger_path)
        daily_usage = ledger.setdefault("daily_usage", {})
        day_entry = daily_usage.setdefault(today_str, {"total_seconds": 0, "total_cost_usd": 0.0, "runs": []})

        day_entry["total_seconds"] += actual_seconds
        day_entry["total_cost_usd"] = round(day_entry["total_cost_usd"] + cost_usd, 4)
        day_entry["runs"].append({
            "timestamp": datetime.now(IST).isoformat(),
            "topic_id": topic_id,
            "seconds": actual_seconds,
            "cost_usd": cost_usd,
        })
        _save_ledger(self.ledger_path, ledger)
        logger.info(
            "Recorded Veo usage for [%s]: %ds ($%.2f). Total today: %ds ($%.2f)",
            topic_id, actual_seconds, cost_usd, day_entry["total_seconds"], day_entry["total_cost_usd"]
        )

    def submit_scene(
        self,
        scene: dict[str, Any],
        index: int,
        job_dir: Path,
        topic_id: str = "",
    ) -> dict[str, Any]:
        """Submits video generation job to Google Veo via Gemini API."""
        if not self.api_key:
            raise VideoProviderError("Missing GEMINI_API_KEY for Veo video generation.")

        prompt = scene.get("video_prompt") or scene.get("heygen_video_prompt") or scene.get("visual_scene", "")
        duration = int(scene.get("duration_sec", self.max_scene_seconds))
        raw_path = job_dir / f"scene_{index:02d}_raw.mp4"
        final_path = job_dir / f"scene_{index:02d}.mp4"

        # Check if final path exists and is valid
        if final_path.exists() and final_path.stat().st_size > 50_000:
            logger.info("Scene %d for %s already exists, reusing: %s", index, topic_id, final_path.name)
            return {
                "operation_name": None,
                "scene_number": index,
                "raw_path": raw_path,
                "final_path": final_path,
                "duration": duration,
                "topic_id": topic_id,
                "already_exists": True,
            }

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:predictLongRunning"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        # Enhanced prompt for cinematic luxury finance look in 9:16 portrait
        enhanced_prompt = (
            f"{prompt}. 9:16 vertical video portrait, photorealistic 8k, cinematic dramatic lighting, "
            f"dark luxury studio, gold ambient rim light, 30fps."
        )

        # Map requested duration to valid discrete Veo values: 4, 6, 8
        valid_durations = [4, 6, 8]
        closest_duration = min(valid_durations, key=lambda x: abs(x - duration))

        payload = {
            "instances": [{"prompt": enhanced_prompt}],
            "parameters": {
                "aspectRatio": "9:16",
                "durationSeconds": closest_duration,
            },
        }

        # Retry transient errors up to 5 attempts with exponential backoff
        last_error = None
        for attempt in range(1, 6):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=45)
                if resp.status_code == 200:
                    data = resp.json()
                    op_name = data.get("name")
                    if not op_name:
                        raise VideoProviderError(f"No operation name returned for scene {index}: {data}")
                    logger.info("Submitted Veo scene %d [%s]: %s", index, topic_id, op_name)
                    return {
                        "operation_name": op_name,
                        "scene_number": index,
                        "raw_path": raw_path,
                        "final_path": final_path,
                        "duration": duration,
                        "topic_id": topic_id,
                        "already_exists": False,
                    }

                # Non-retryable client errors (400 Bad Request, 404 Model Not Found / Deprecated)
                if resp.status_code in (400, 404):
                    logger.error("Veo API non-retryable client error %d on scene %d: %s", resp.status_code, index, resp.text)
                    raise VideoProviderError(f"Google Veo API client error {resp.status_code}: {resp.text}")

                # Check for quota exhaustion / non-retryable 429
                body = resp.text.lower()
                if resp.status_code == 429 and ("quota" in body or "resource_exhausted" in body or "insufficient" in body):
                    logger.error("Veo API quota exceeded for scene %d: %s", index, resp.text)
                    raise QuotaExceeded(f"Google Veo API quota exceeded: {resp.text}")

                if resp.status_code in (429, 500, 502, 503, 504):
                    wait = 2 ** attempt
                    logger.warning("Transient %d on scene %d (attempt %d/5), retrying in %ds...", resp.status_code, index, attempt, wait)
                    time.sleep(wait)
                    continue

                resp.raise_for_status()

            except (QuotaExceeded, BudgetCapReached, VideoProviderError):
                raise
            except Exception as e:
                last_error = e
                wait = 2 ** attempt
                logger.warning("Error submitting scene %d (attempt %d/5): %s. Retrying in %ds...", index, attempt, e, wait)
                time.sleep(wait)

        raise VideoProviderError(f"Failed to submit Veo scene {index} after 5 attempts: {last_error}")

    def wait_scene(self, job: dict[str, Any]) -> Path:
        """Polls long-running operation, downloads result, converts and verifies clip."""
        final_path = job["final_path"]
        raw_path = job["raw_path"]
        index = job["scene_number"]
        topic_id = job.get("topic_id", "")
        duration = job.get("duration", self.max_scene_seconds)

        if job.get("already_exists") and final_path.exists():
            return final_path

        op_name = job["operation_name"]
        if op_name.startswith("http"):
            poll_url = op_name
        else:
            poll_url = f"https://generativelanguage.googleapis.com/v1beta/{op_name}"

        headers = {"x-goog-api-key": self.api_key}
        start_time = time.time()
        poll_interval = 10

        while True:
            elapsed = time.time() - start_time
            if elapsed > self.timeout_seconds:
                raise ProviderTimeout(
                    f"Veo operation for scene {index} of [{topic_id}] timed out after {int(elapsed)}s: {op_name}"
                )

            time.sleep(poll_interval)
            try:
                resp = requests.get(poll_url, headers=headers, timeout=30)
                if resp.status_code in (429, 500, 502, 503):
                    logger.warning("Transient error polling scene %d (%d), retrying...", index, resp.status_code)
                    continue
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning("Network error polling scene %d: %s", index, e)
                continue

            if not data.get("done", False):
                logger.info(
                    "Polling Veo scene %d [%s] (elapsed: %ds/%ds)...",
                    index, topic_id, int(elapsed), self.timeout_seconds
                )
                continue

            # Check if operation failed
            if "error" in data:
                err = data["error"]
                logger.error("Veo operation error for scene %d: %s", index, err)
                if "quota" in str(err).lower():
                    raise QuotaExceeded(f"Veo quota exceeded for scene {index}: {err}")
                raise VideoProviderError(f"Veo generation failed for scene {index}: {err}")

            # Extract video URL
            response_obj = data.get("response", {})
            generated_videos = response_obj.get("generatedVideos") or response_obj.get("generated_videos", [])
            download_url = None

            if generated_videos and isinstance(generated_videos, list):
                first_vid = generated_videos[0]
                if isinstance(first_vid, dict):
                    video_info = first_vid.get("video", {})
                    download_url = video_info.get("uri") or first_vid.get("uri") or first_vid.get("downloadUrl")

            if not download_url:
                # Check top-level or alternative keys
                download_url = response_obj.get("downloadUrl") or response_obj.get("uri")

            if not download_url:
                raise VideoProviderError(f"Completed scene {index} response missing video URL: {data}")

            # Download video stream
            self._download_video(download_url, raw_path)

            # Convert to standard vertical 1080x1920 portrait with muted audio
            self._convert_to_vertical(raw_path, final_path, duration)
            raw_path.unlink(missing_ok=True)

            # Verify with ffprobe
            self._verify_clip(final_path, index)
            logger.info("Successfully produced Veo scene %d [%s]: %s", index, topic_id, final_path.name)
            return final_path

    def _download_video(self, url: str, dest: Path) -> None:
        """Downloads video stream from authenticated Gemini URI."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        headers = {}
        # Append API key if needed
        download_url = url
        if "generativelanguage.googleapis.com" in url:
            if "key=" not in download_url:
                sep = "&" if "?" in download_url else "?"
                download_url = f"{download_url}{sep}key={self.api_key}"
            headers["x-goog-api-key"] = self.api_key

        resp = requests.get(download_url, headers=headers, stream=True, timeout=120)
        resp.raise_for_status()

        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=32768):
                if chunk:
                    f.write(chunk)

        if not dest.exists() or dest.stat().st_size < 10_000:
            raise VideoProviderError(f"Downloaded video file {dest} is missing or too small.")

    def _convert_to_vertical(self, raw: Path, out: Path, target_duration: int) -> None:
        """Converts raw video to 1080x1920 portrait, 30fps, muted audio."""
        out.parent.mkdir(parents=True, exist_ok=True)
        vf_chain = (
            f"trim=duration={target_duration},setpts=PTS-STARTPTS,"
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
            "-an",  # strip/mute audio so TTS voiceover + BGM can mix cleanly
            str(out),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise VideoProviderError(f"FFmpeg conversion to vertical failed on {raw}: {res.stderr[-300:]}")

    def _verify_clip(self, clip_path: Path, scene_number: int) -> None:
        """Verifies clip format, dimensions, and positive duration using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=width,height,duration",
            "-of", "json", str(clip_path)
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise VideoProviderError(f"ffprobe failed for scene {scene_number}: {proc.stderr}")

        try:
            data = json.loads(proc.stdout)
            streams = data.get("streams", [])
            if not streams:
                raise VideoProviderError(f"No stream found by ffprobe in scene {scene_number}")
            w = int(streams[0].get("width", 0))
            h = int(streams[0].get("height", 0))
            dur = float(streams[0].get("duration", 0))
            if w <= 0 or h <= 0 or dur <= 0:
                raise VideoProviderError(
                    f"Bad ffprobe result for scene {scene_number}: {w}x{h}, {dur}s (must be positive)"
                )
        except Exception as e:
            if isinstance(e, VideoProviderError):
                raise
            raise VideoProviderError(f"Failed to parse ffprobe output for scene {scene_number}: {e}")

    def generate_all_scenes(
        self,
        scenes: list[dict[str, Any]],
        topic_id: str,
        output_dir: Path,
    ) -> list[Path]:
        """
        Orchestrates full scene generation pipeline:
        1. Checks cost guard limits (VEO_MAX_SECONDS_PER_RUN, VEO_MAX_SECONDS_PER_DAY).
        2. Submits all scenes first in batch.
        3. Polls and downloads scenes.
        4. Records actual usage in ledger.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Cost guard check
        est = self.check_cost_guard(scenes)
        logger.info(
            "Veo cost check OK for [%s]: %d scenes, %ds estimated ($%.2f)",
            topic_id, est["scenes_count"], est["total_seconds"], est["estimated_cost_usd"]
        )

        # 2. Submit all scenes in batch
        jobs = []
        for i, scene in enumerate(scenes, start=1):
            job = self.submit_scene(scene, i, output_dir, topic_id=topic_id)
            jobs.append(job)

        # 3. Poll and finalize each scene
        final_paths = []
        actual_seconds = 0
        for job in jobs:
            p = self.wait_scene(job)
            final_paths.append(p)
            actual_seconds += int(job.get("duration", self.max_scene_seconds))

        # 4. Record usage in ledger
        cost_usd = round(actual_seconds * COST_PER_SECOND, 4)
        self.record_usage(topic_id, actual_seconds, cost_usd)

        return final_paths


# Convenience module-level function matching previous interface
def generate_all_scenes(
    scenes: list[dict[str, Any]],
    topic_id: str,
    output_dir: Path,
) -> list[Path]:
    """Generates all scene clips using default VeoProvider."""
    provider = VeoProvider()
    return provider.generate_all_scenes(scenes, topic_id, output_dir)
