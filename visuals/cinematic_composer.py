"""
Finance Shorts Pro - Cinematic Video Composer
Assembles Google Veo scene clips with:
- Professional voiceover (Andrew Multilingual Neural TTS)
- Animated text overlays (scene titles, data callouts)
- Animated progress bar
- Gold particle effects
- Safe-zone kinetic subtitles
- Cross-dissolve transitions between scenes
Outputs a vertical 1080x1920 30fps YouTube Shorts MP4.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger(__name__)

# Font lookup (prefer Roboto Black for bold overlays)
FONT_SEARCH = [
    str(Path(config.ROOT_DIR) / "assets" / "fonts" / "Roboto-Black.ttf"),
    str(Path(config.ROOT_DIR) / "assets" / "fonts" / "Roboto-Bold.ttf"),
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]

def _best_font() -> str:
    for f in FONT_SEARCH:
        if Path(f).exists():
            return f
    return ""

# Color constants (ASS subtitle style hex is BGR)
TEXT_YELLOW_ASS  = "&H0000FFFF"   # Bright yellow
TEXT_WHITE_ASS   = "&H00FFFFFF"
TEXT_CYAN_ASS    = "&H00FFFF00"
SHADOW_BLACK_ASS = "&H00000000"
BOX_BG_ASS       = "&HA0000000"   # 63% opaque black


def compose_pro_video(
    scene_video_paths: list[Optional[Path]],
    scene_data: list[dict],
    audio_path: Path,
    srt_path: Optional[Path],
    output_mp4: Path,
    total_duration: float,
    topic_title: str = "Finance Short",
    category: str = "Finance",
) -> Path:
    """
    Assembles the full cinematic Short:
    1. Concatenates scene MP4s (Veo clips or dynamic graphic motion cards) with crossfade transitions
    2. Overlays animated text (on_screen_text + data_callout per scene)
    3. Burns kinetic subtitles
    4. Adds animated top progress bar
    5. Merges TTS voiceover audio
    """
    output_mp4 = Path(output_mp4)
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    font = _best_font()

    # ── Step 1: Build scene clip list with rich graphic fallbacks ─────────────
    scene_clips: list[Path] = []
    scene_durations: list[float] = []
    tmp_blanks: list[Path] = []

    for i, (clip_path, scene) in enumerate(zip(scene_video_paths, scene_data)):
        dur = float(scene.get("duration_sec", 8))
        scene_durations.append(dur)

        if clip_path and clip_path.exists() and clip_path.stat().st_size > 50_000:
            scene_clips.append(clip_path)
        else:
            # Generate rich animated graphic card clip
            card_clip = output_mp4.parent / f"scene_card_{i+1:02d}.mp4"
            _make_graphic_clip(
                dest=card_clip,
                duration=dur,
                scene=scene,
                scene_index=i,
                total_scenes=len(scene_data),
                topic_title=topic_title,
                category=category,
            )
            tmp_blanks.append(card_clip)
            scene_clips.append(card_clip)

    # ── Step 2: Concatenate with xfade crossdissolve transitions ────────────
    concat_path = output_mp4.parent / f"{output_mp4.stem}_concat.mp4"
    _concat_with_xfade(scene_clips, scene_durations, concat_path)

    # ── Step 3: Build FFmpeg overlay filter for text + subtitles + progress bar ─
    vf_parts = []

    # Scale/ensure correct dimensions
    vf_parts.append("scale=1080:1920:force_original_aspect_ratio=decrease")
    vf_parts.append("pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black")
    vf_parts.append("fps=30")

    # Top border line (gold)
    vf_parts.append("drawbox=x=0:y=0:w=iw:h=8:color=0xD4AF37@1:t=fill")



    # Kinetic subtitles (yellow, safe-zone)
    if srt_path and Path(srt_path).exists():
        try:
            srt_rel = str(Path(srt_path).resolve().relative_to(Path.cwd())).replace("\\", "/")
        except Exception:
            srt_rel = str(srt_path).replace("\\", "/")

        sub_style = (
            "FontName=Arial,"
            "FontSize=24,"
            "Bold=1,"
            f"PrimaryColour={TEXT_YELLOW_ASS},"
            f"SecondaryColour={TEXT_WHITE_ASS},"
            f"OutlineColour={SHADOW_BLACK_ASS},"
            f"BackColour={BOX_BG_ASS},"
            "BorderStyle=3,"
            "Outline=3,"
            "Shadow=0,"
            "Alignment=2,"
            "MarginV=320"
        )
        vf_parts.append(f"subtitles={srt_rel}:force_style='{sub_style}'")

    vf_str = ",".join(vf_parts)

    # ── Step 4: Final encode — video + TTS audio + Succession BGM ──────────────
    bgm_path = Path(config.ROOT_DIR) / "assets" / "sounds" / "bgm_succession.mp3"
    if bgm_path.exists():
        bgm_vol = getattr(config, "BGM_VOLUME", 0.18)
        vox_vol = getattr(config, "VOICE_VOLUME", 1.25)
        filter_complex = (
            f"[0:v]{vf_str}[outv];"
            f"[2:a]volume={bgm_vol:.2f},afade=t=in:ss=0:d=1.5,afade=t=out:st={max(total_duration - 2.5, 1.0):.1f}:d=2.5[bg];"
            f"[1:a]volume={vox_vol:.2f}[vox];"
            f"[vox][bg]amix=inputs=2:duration=first:dropout_transition=2[outa]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(concat_path),
            "-i", str(audio_path),
            "-i", str(bgm_path),
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "[outa]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", config.AUDIO_BITRATE,
            "-shortest",
            str(output_mp4),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(concat_path),
            "-i", str(audio_path),
            "-vf", vf_str,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", config.AUDIO_BITRATE,
            "-shortest",
            str(output_mp4),
        ]
    logger.info("Final render with Succession BGM: %s (%.1fs)", output_mp4.name, total_duration)
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Cleanup
    concat_path.unlink(missing_ok=True)
    for b in tmp_blanks:
        b.unlink(missing_ok=True)

    if result.returncode != 0:
        logger.error("FFmpeg final render error: %s", result.stderr[-500:])
        raise RuntimeError(f"Final render failed: {result.stderr[-300:]}")

    size_mb = output_mp4.stat().st_size / (1024 * 1024)
    logger.info("Pro video rendered: %s (%.2f MB, %.1fs)", output_mp4.name, size_mb, total_duration)
    return output_mp4


def _make_graphic_clip(
    dest: Path,
    duration: float,
    scene: dict,
    scene_index: int,
    total_scenes: int,
    topic_title: str,
    category: str,
) -> None:
    """Renders a dynamic 1080x1920 cinematic character scene clip with camera motion and gold typography."""
    try:
        presenter_dir = Path(config.ROOT_DIR) / "assets" / "presenter"
        plate_idx = (scene_index % 5) + 1
        plate_path = presenter_dir / f"scene_{plate_idx}.jpg"
        if not plate_path.exists():
            plate_path = presenter_dir / "character_reference.png"

        if plate_path.exists():
            fps = 30
            total_frames = max(int(duration * fps), 30)

            # Camera motion per scene
            if plate_idx == 1:
                v_motion = f"scale=1200:2133,zoompan=z='min(zoom+0.0004,1.14)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih*0.25-(ih/zoom*0.25)':s=1080x1920:fps={fps}"
            elif plate_idx == 5 or scene_index == total_scenes - 1:
                v_motion = f"scale=1200:2133,zoompan=z='max(1.12-0.0004*on,1.0)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih*0.3-(ih/zoom*0.3)':s=1080x1920:fps={fps}"
            elif plate_idx == 2:
                v_motion = f"scale=1200:2133,zoompan=z='1.06':d={total_frames}:x='min((on/{total_frames})*(iw-iw/zoom)*0.7, (iw-iw/zoom))':y='ih*0.2-(ih/zoom*0.2)':s=1080x1920:fps={fps}"
            else:
                v_motion = f"scale=1200:2133,zoompan=z='min(1.02+0.0003*on,1.10)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih*0.25-(ih/zoom*0.25)':s=1080x1920:fps={fps}"

            font = _best_font()
            font_escaped = font.replace("\\", "/").replace(":", "\\:") if font else ""

            filters = [v_motion, "vignette=angle=0.4:aspect=9/16"]

            on_screen = (scene.get("on_screen_text") or topic_title).replace("'", "").replace(":", " - ").replace("%", "pct")
            if font_escaped and on_screen:
                filters.append(
                    f"drawtext=fontfile='{font_escaped}':text='{on_screen}':"
                    f"fontsize=46:fontcolor=0xD4AF37:borderw=3:bordercolor=black:"
                    f"x=(w-text_w)/2:y=240:enable='gte(t,0.3)':alpha='min(1,(t-0.3)*2)'"
                )

            data_callout = (scene.get("data_callout") or "").replace("'", "").replace(":", " - ").replace("%", "pct")
            if font_escaped and data_callout:
                filters.append(
                    f"drawtext=fontfile='{font_escaped}':text='{data_callout}':"
                    f"fontsize=34:fontcolor=white:borderw=2:bordercolor=black:"
                    f"x=(w-text_w)/2:y=310:enable='gte(t,0.8)':alpha='min(1,(t-0.8)*2)'"
                )

            # Mandatory call to action overlay on final scene
            if scene_index == total_scenes - 1 and font_escaped:
                filters.append(
                    f"drawbox=y=1320:color=black@0.65:width=iw:height=260:t=fill:enable='gte(t,0.8)'"
                )
                filters.append(
                    f"drawtext=fontfile='{font_escaped}':text='FOLLOW THE JOURNEY':"
                    f"fontsize=46:fontcolor=0xD4AF37:borderw=3:bordercolor=black:x=(w-text_w)/2:y=1360:enable='gte(t,1.0)'"
                )
                filters.append(
                    f"drawtext=fontfile='{font_escaped}':text='IMPROVE FINANCIAL KNOWLEDGE':"
                    f"fontsize=36:fontcolor=white:borderw=2:bordercolor=black:x=(w-text_w)/2:y=1440:enable='gte(t,1.5)'"
                )

            filter_complex = ",".join(filters)

            cmd = [
                "ffmpeg", "-y",
                "-i", str(plate_path),
                "-vf", filter_complex,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-an",
                str(dest)
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0 and dest.exists() and dest.stat().st_size > 10000:
                return
            else:
                logger.warning("FFmpeg presenter scene error: %s", res.stderr[-300:] if res.stderr else "Unknown")
    except Exception as e:
        logger.warning("Presenter scene generation failed for scene %d: %s", scene_index + 1, e)

    _make_blank_clip(dest, duration)


def _make_blank_clip(dest: Path, duration: float) -> None:
    """Creates a black 1080x1920 fallback clip for missing scenes."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s=1080x1920:d={duration:.3f}",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", str(dest)
    ]
    subprocess.run(cmd, capture_output=True)


def _concat_with_xfade(
    clips: list[Path],
    durations: list[float],
    output: Path,
    fade_dur: float = 0.5,
) -> None:
    """
    Concatenates clips with xfade crossdissolve transitions.
    Uses FFmpeg xfade filter for smooth blends.
    """
    if len(clips) == 1:
        # Single clip, just copy
        subprocess.run(["ffmpeg", "-y", "-i", str(clips[0]), "-c", "copy", str(output)], capture_output=True)
        return

    # Build FFmpeg complex filter graph for xfade
    # Each xfade transition needs the cumulative offset
    inputs = []
    for c in clips:
        inputs += ["-i", str(c)]

    # Build filter chain: [0][1]xfade=...[v01]; [v01][2]xfade=...[v012]; ...
    filters = []
    offset = 0.0
    prev_label = "0:v"

    for i in range(1, len(clips)):
        offset += durations[i - 1] - fade_dur
        out_label = f"v{i}"
        if i < len(clips) - 1:
            filters.append(
                f"[{prev_label}][{i}:v]xfade=transition=fade:duration={fade_dur:.2f}:offset={offset:.3f}[{out_label}]"
            )
        else:
            filters.append(
                f"[{prev_label}][{i}:v]xfade=transition=fade:duration={fade_dur:.2f}:offset={offset:.3f}[vout]"
            )
        prev_label = out_label

    filter_complex = ";".join(filters)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-an",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning("xfade concat failed, falling back to simple concat: %s", result.stderr[-200:])
        _simple_concat(clips, output)


def _simple_concat(clips: list[Path], output: Path) -> None:
    """Simple concat fallback without transitions."""
    concat_file = output.parent / f"{output.stem}_list.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for c in clips:
            f.write(f"file '{str(c).replace(chr(92), '/')}'\n")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an", str(output)
    ]
    subprocess.run(cmd, capture_output=True)
    concat_file.unlink(missing_ok=True)
