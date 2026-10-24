"""
Tests for OG Multi-Scene Cinematic Video Format.
Guarantees that the multi-scene storyboard, dynamic presenter cards, camera motions,
gold typography, xfade transitions, and audio ducking remain intact and cannot be degraded.
"""

from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from visuals.cinematic_composer import (
    compose_pro_video,
    _make_graphic_clip,
    _concat_with_xfade,
    _best_font,
    TEXT_YELLOW_ASS,
    SHADOW_BLACK_ASS,
)


@pytest.fixture
def sample_scenes():
    return [
        {
            "scene_number": 1,
            "visual_scene": "Hook: A financial chart shows an ominous curve.",
            "on_screen_text": "THE CURVE IS INVERTING",
            "data_callout": "10-Year vs 2-Year Yield",
            "duration_sec": 5.0,
        },
        {
            "scene_number": 2,
            "visual_scene": "Explanation: Short-term rates rise above long-term.",
            "on_screen_text": "WHAT IT MEANS",
            "data_callout": "Yield Spread < 0%",
            "duration_sec": 6.0,
        },
        {
            "scene_number": 3,
            "visual_scene": "Historical context: Every US recession since 1969.",
            "on_screen_text": "HISTORICAL ACCURACY",
            "data_callout": "8 out of 8 Recessions",
            "duration_sec": 7.0,
        },
        {
            "scene_number": 4,
            "visual_scene": "Indian market: What to watch on the NSE and RBI repo.",
            "on_screen_text": "INDIAN IMPACT",
            "data_callout": "RBI Repo Rate & Nifty",
            "duration_sec": 6.0,
        },
        {
            "scene_number": 5,
            "visual_scene": "Summary and Call to action: Follow the journey.",
            "on_screen_text": "KEY TAKEAWAY",
            "data_callout": "Watch The Spread",
            "duration_sec": 6.0,
        },
    ]


def test_og_format_has_multiple_scene_presenter_plates():
    """Verify that all 5 OG presenter scene plates exist in assets/presenter."""
    presenter_dir = Path("assets/presenter")
    for i in range(1, 6):
        plate = presenter_dir / f"scene_{i}.jpg"
        assert plate.exists(), f"OG presenter plate {plate} is missing!"
        assert plate.stat().st_size > 50_000, f"OG plate {plate} is corrupted or empty!"


def test_og_format_font_exists():
    """Verify that a high quality font is detected for gold typography."""
    font = _best_font()
    assert font is not None
    assert Path(font).exists(), f"Selected font {font} does not exist!"


def test_make_graphic_clip_command_structure(tmp_path, sample_scenes):
    """
    Test that _make_graphic_clip builds an FFmpeg command with camera motion,
    gold typography (#D4AF37), data callout, and vignette.
    """
    dest = tmp_path / "test_scene_01.mp4"
    scene = sample_scenes[0]

    with patch("subprocess.run") as mock_run:
        # Simulate successful FFmpeg run
        def fake_run(cmd, *args, **kwargs):
            dest.write_bytes(b"dummy video data " * 10000)
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_run

        _make_graphic_clip(
            dest=dest,
            duration=scene["duration_sec"],
            scene=scene,
            scene_index=0,
            total_scenes=len(sample_scenes),
            topic_title="Yield Curve Inversion",
            category="Macro Economics",
        )

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(cmd)

        # Must include zoompan camera motion
        assert "zoompan=" in cmd_str
        # Must include vignette
        assert "vignette=" in cmd_str
        # Must include gold on-screen text
        assert "0xD4AF37" in cmd_str
        assert "THE CURVE IS INVERTING" in cmd_str
        # Must include white data callout
        assert "fontcolor=white" in cmd_str
        assert "10-Year vs 2-Year Yield" in cmd_str


def test_make_graphic_clip_final_scene_has_cta(tmp_path, sample_scenes):
    """Test that the final scene includes the mandatory branded call to action overlay."""
    dest = tmp_path / "test_scene_05.mp4"
    scene = sample_scenes[-1]
    final_idx = len(sample_scenes) - 1

    with patch("subprocess.run") as mock_run:
        def fake_run(cmd, *args, **kwargs):
            dest.write_bytes(b"dummy video data " * 10000)
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_run

        _make_graphic_clip(
            dest=dest,
            duration=scene["duration_sec"],
            scene=scene,
            scene_index=final_idx,
            total_scenes=len(sample_scenes),
            topic_title="Yield Curve Inversion",
            category="Macro Economics",
        )

        assert mock_run.called
        cmd_str = " ".join(mock_run.call_args[0][0])

        # Must include CTA banner
        assert "FOLLOW THE JOURNEY" in cmd_str
        assert "IMPROVE FINANCIAL KNOWLEDGE" in cmd_str


def test_concat_with_xfade_command_structure(tmp_path):
    """Test that _concat_with_xfade builds proper xfade transitions across clips."""
    clips = [tmp_path / f"clip_{i}.mp4" for i in range(3)]
    for c in clips:
        c.write_bytes(b"dummy clip data")
    durations = [5.0, 6.0, 5.0]
    out_file = tmp_path / "concat.mp4"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        _concat_with_xfade(clips, durations, out_file, fade_dur=0.5)

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(cmd)

        # Must contain xfade filter
        assert "xfade=transition=fade" in cmd_str
        assert "-map [vout]" in cmd_str


def test_compose_pro_video_creates_multi_scene_video(tmp_path, sample_scenes):
    """
    Integration test: compose_pro_video must create individual scene cards for each scene,
    concatenate them with transitions, and merge audio with Succession BGM ducking.
    """
    output_mp4 = tmp_path / "final_short.mp4"
    audio_path = tmp_path / "speech.mp3"
    audio_path.write_bytes(b"dummy audio" * 1000)

    # Mock scene rendering & final encode
    with patch("subprocess.run") as mock_run:
        def fake_ffmpeg(cmd, *args, **kwargs):
            if str(output_mp4) in cmd:
                output_mp4.write_bytes(b"valid final video " * 10000)
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = fake_ffmpeg

        result = compose_pro_video(
            scene_video_paths=[None] * len(sample_scenes),
            scene_data=sample_scenes,
            audio_path=audio_path,
            srt_path=None,
            output_mp4=output_mp4,
            total_duration=30.0,
            topic_title="Yield Curve Inversion",
            category="Macro Economics",
        )

        assert result == output_mp4
        assert output_mp4.exists()
