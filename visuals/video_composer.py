"""
Finance Shorts - Video Composer
Assembles scene frame images, voiceover audio, and styled subtitles into
a crisp 1080x1920 30fps vertical MP4 video using FFmpeg.
Includes subtle motion, safe-zone captions, and audio-video synchronization.
"""

from __future__ import annotations

import logging
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

import config

logger = logging.getLogger(__name__)


def compose_short_video(
    scene_images: list[Path],
    scene_durations: list[float],
    audio_path: Path,
    srt_path: Optional[Path],
    output_mp4: Path,
    total_duration: Optional[float] = None,
) -> Path:
    """
    Renders an educational YouTube Short MP4 video:
    1. Creates a timed image concatenation script matching each scene's audio timing.
    2. Overlays styled kinetic subtitles in the YouTube Shorts safe zone.
    3. Merges high-quality AAC voiceover.
    4. Encodes to 1080x1920 vertical H.264 MP4.
    """
    output_mp4 = Path(output_mp4)
    output_mp4.parent.mkdir(parents=True, exist_ok=True)

    if len(scene_images) != len(scene_durations):
        raise ValueError(
            f"Mismatch between images ({len(scene_images)}) and durations ({len(scene_durations)})"
        )

    # Build FFmpeg concat file
    concat_lines: list[str] = []
    for img_path, dur in zip(scene_images, scene_durations):
        # Forward slashes for FFmpeg compatibility
        escaped_path = str(img_path.resolve()).replace("\\", "/")
        concat_lines.append(f"file '{escaped_path}'")
        concat_lines.append(f"duration {dur:.3f}")

    # FFmpeg concat format requires repeating the last file without duration
    if scene_images:
        last_escaped = str(scene_images[-1].resolve()).replace("\\", "/")
        concat_lines.append(f"file '{last_escaped}'")

    concat_file = output_mp4.parent / f"{output_mp4.stem}_concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        f.write("\n".join(concat_lines) + "\n")

    # Build video filters:
    # 1. Scale to 1080x1920, force 30fps
    vf_chain: list[str] = [
        f"scale={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT}:force_original_aspect_ratio=decrease",
        f"pad={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black",
        f"fps={config.VIDEO_FPS}",
    ]

    # 2. Animated top progress bar (0% to 100% dynamically tracking video playback)
    dur_total = total_duration or sum(scene_durations)
    dur_total = max(dur_total, 1.0)
    vf_chain.append("drawbox=x=0:y=0:w=iw:h=12:color=0x1E293B@0.8:t=fill")
    vf_chain.append(f"drawbox=x=0:y=0:w='min(iw,iw*t/{dur_total:.3f})':h=12:color=0x00E5FF@1:t=fill")

    # 3. Add styled subtitle overlay if srt exists
    if srt_path and Path(srt_path).exists():
        escaped_srt = str(Path(srt_path).resolve()).replace("\\", "/").replace(":", "\\:")
        # Styling: High-retention yellow text, black pill box, placed in mobile safe zone
        sub_style = (
            "FontName=Arial,"
            "FontSize=23,"
            "Bold=1,"
            "PrimaryColour=&H0000FFFF,"      # Bright vibrant yellow
            "SecondaryColour=&H00FFFFFF,"    # White
            "OutlineColour=&H00000000,"      # Black outline
            "BackColour=&HA0000000,"         # Semi-transparent dark pill background
            "BorderStyle=3,"                 # Opaque pill box behind text
            "Outline=3,"
            "Shadow=0,"
            "Alignment=2,"                   # Bottom-center
            "MarginV=320"                    # Safe zone above YouTube Shorts title/sound tags
        )
        vf_chain.append(f"subtitles='{escaped_srt}':force_style='{sub_style}'")

    vf_str = ",".join(vf_chain)

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-i", str(audio_path),
        "-vf", vf_str,
        "-c:v", "libx264",
        "-preset", "faster",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", config.AUDIO_BITRATE,
        "-shortest",
        str(output_mp4),
    ]

    logger.info("Rendering video: %s (duration: ~%s s)", output_mp4.name, sum(scene_durations))
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Clean up temp concat file
    if concat_file.exists():
        concat_file.unlink()

    if result.returncode != 0:
        logger.error("FFmpeg error: %s", result.stderr)
        raise RuntimeError(f"FFmpeg video encoding failed: {result.stderr[-400:]}")

    logger.info("Video successfully rendered: %s (size: %.2f MB)",
                output_mp4.name, output_mp4.stat().st_size / (1024 * 1024))
    return output_mp4
