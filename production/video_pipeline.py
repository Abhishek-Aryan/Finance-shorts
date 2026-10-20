"""
Finance Shorts - End-to-End Video Production Pipeline
Orchestrates:
1. Fetching approved or generated script from DB.
2. Generating audio voiceover + kinetic SRT subtitles (Edge-TTS).
3. Rendering 1080x1920 scene cards with dark-mode styling and charts.
4. Composing the final vertical MP4 with FFmpeg.
5. Updating database status to READY_TO_PUBLISH.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import config
from audio.tts_engine import synthesize_speech
from storage import database
from visuals.graphic_generator import render_scene_frame
from visuals.video_composer import compose_short_video

logger = logging.getLogger(__name__)


def produce_video_for_topic(
    topic_id: str,
    voice: Optional[str] = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Produces a complete YouTube Short MP4 video for a topic.
    Returns metadata dict with paths to generated assets and stats.
    """
    # 1. Fetch script and topic metadata
    topic = database.get_topic(topic_id)
    if not topic:
        raise ValueError(f"Topic not found: {topic_id}")

    script = database.get_script(topic_id)
    if not script:
        raise ValueError(f"No script found for topic {topic_id}. Run 'generate' first.")

    # Parse scene plan and details
    scene_plan = script.get("scene_plan", [])
    if isinstance(scene_plan, str):
        try:
            scene_plan = json.loads(scene_plan)
        except Exception:
            scene_plan = []

    full_script_text = script.get("full_script", "")
    if not full_script_text:
        raise ValueError(f"Topic {topic_id} has an empty script")

    video_title = script.get("video_title") or topic.get("topic", "Finance Short")
    category = topic.get("category", "Finance")

    logger.info("Starting video production for [%s]: %s", topic_id, video_title)

    # 2. Synthesize audio narration
    audio_dir = config.OUTPUT_AUDIO / topic_id
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_meta = synthesize_speech(
        text=full_script_text,
        output_dir=audio_dir,
        filename_prefix=f"{topic_id}_narration",
        voice=voice or config.DEFAULT_VOICE,
    )
    total_audio_duration = audio_meta["duration"]
    logger.info("Generated voiceover: %.2fs for %s", total_audio_duration, topic_id)

    # 3. Render 1080x1920 scene frames
    visuals_dir = config.OUTPUT_VISUALS / topic_id
    visuals_dir.mkdir(parents=True, exist_ok=True)

    if not scene_plan:
        # Fallback to 5 default scenes
        scene_plan = [
            {"scene_number": 1, "duration_seconds": 6, "on_screen_text": script.get("hook", "Did You Know?")[:40], "narration": script.get("hook", "")},
            {"scene_number": 2, "duration_seconds": 12, "on_screen_text": video_title[:40], "narration": script.get("explanation", "")},
            {"scene_number": 3, "duration_seconds": 12, "on_screen_text": "Real Life Example", "narration": script.get("example", "")},
            {"scene_number": 4, "duration_seconds": 8, "on_screen_text": "Key Takeaway", "narration": script.get("takeaway", "")},
            {"scene_number": 5, "duration_seconds": 6, "on_screen_text": "Follow For More", "narration": script.get("closing", "")},
        ]

    total_scenes = len(scene_plan)
    scene_frames: list[Path] = []
    nominal_durations: list[float] = []

    for i, sc in enumerate(scene_plan):
        frame_path = visuals_dir / f"scene_{i + 1:02d}.png"
        on_screen = sc.get("on_screen_text") or f"Key Point {i + 1}"
        narration = sc.get("narration") or ""
        
        # Determine if chart should be displayed
        include_chart = (i == 2) or ("chart" in sc.get("visual", "").lower())
        chart_type = "comparison" if "comparison" in sc.get("visual", "").lower() else "growth"

        render_scene_frame(
            scene_index=i,
            total_scenes=total_scenes,
            topic_id=topic_id,
            topic_title=video_title,
            category=category,
            on_screen_text=on_screen,
            scene_narration=narration,
            output_path=frame_path,
            include_chart=include_chart,
            chart_type=chart_type,
        )
        scene_frames.append(frame_path)
        nominal_durations.append(float(sc.get("duration_seconds", 8.0)))

    # Scale scene durations to match total audio duration precisely
    sum_nominal = sum(nominal_durations) if nominal_durations else 1.0
    actual_durations = [
        round((d / sum_nominal) * total_audio_duration, 3) for d in nominal_durations
    ]
    # Ensure sum of durations matches audio exactly
    dur_diff = total_audio_duration - sum(actual_durations)
    actual_durations[-1] = round(actual_durations[-1] + dur_diff, 3)

    # 4. Compose final MP4 video with FFmpeg
    video_dir = config.OUTPUT_VIDEOS
    video_dir.mkdir(parents=True, exist_ok=True)
    output_mp4 = video_dir / f"{topic_id}.mp4"

    compose_short_video(
        scene_images=scene_frames,
        scene_durations=actual_durations,
        audio_path=audio_meta["audio_path"],
        srt_path=audio_meta["srt_path"],
        output_mp4=output_mp4,
        total_duration=total_audio_duration,
    )

    # 5. Persist record in database
    file_size_mb = round(output_mp4.stat().st_size / (1024 * 1024), 2)
    now = database._now()
    with database.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO production
                (topic_id, narration_file, captions_file, visuals_dir,
                 video_file, audio_duration, video_duration, video_width,
                 video_height, render_report, validated, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(topic_id) DO UPDATE SET
                narration_file=excluded.narration_file,
                captions_file=excluded.captions_file,
                visuals_dir=excluded.visuals_dir,
                video_file=excluded.video_file,
                audio_duration=excluded.audio_duration,
                video_duration=excluded.video_duration,
                video_width=excluded.video_width,
                video_height=excluded.video_height,
                render_report=excluded.render_report,
                validated=1,
                updated_at=excluded.updated_at
            """,
            (
                topic_id,
                str(audio_meta["audio_path"]),
                str(audio_meta["srt_path"]),
                str(visuals_dir),
                str(output_mp4),
                total_audio_duration,
                total_audio_duration,
                config.VIDEO_WIDTH,
                config.VIDEO_HEIGHT,
                f"Rendered {total_scenes} scenes in 1080x1920 @ 30fps ({file_size_mb} MB)",
                now,
                now,
            ),
        )

    # Update topic status to VIDEO_READY
    database.update_topic_status(topic_id, database.Status.VIDEO_READY)

    logger.info("Video production complete for [%s]: %s (%.2f MB, %.1fs)",
                topic_id, output_mp4.name, file_size_mb, total_audio_duration)

    return {
        "topic_id": topic_id,
        "video_path": str(output_mp4),
        "duration": total_audio_duration,
        "size_mb": file_size_mb,
        "scenes_count": total_scenes,
        "srt_path": str(audio_meta["srt_path"]),
        "status": database.Status.VIDEO_READY,
    }

