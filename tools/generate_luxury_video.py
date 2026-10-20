"""
Luxury Finance Presenter Video Generator
Assembles the complete master video requested by the user:
- Topic: "The Money Habits That Separate the Rich From Everyone Else"
- Exact Character Lock (Faceless luxury presenter in tailored black suit with gold rim light)
- 5 Scenes with exact narration and visual directions
- Continuous cinematic camera motion (smooth push-ins, pull-backs, pans)
- Atmospheric floating gold particles & vignette
- Motion graphics overlays (Income pathways, holographic financial dashboard, mindset shift question, final title card)
- Professional deep voiceover (AndrewMultilingualNeural) with natural dramatic pauses
- Ambient cinematic audio bed
- Styled kinetic subtitles in safe zones
- 1080x1920 30fps H.264 MP4 output
- Publishes directly to YouTube Shorts
"""

import os
import sys
import json
import uuid
import subprocess
from pathlib import Path

# Ensure scratch/finance-shorts is in path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from audio.tts_engine import synthesize_speech, get_audio_duration

ASSETS_DIR = ROOT_DIR / "assets" / "presenter"
OUTPUT_DIR = ROOT_DIR / "output" / "luxury_video"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
FINAL_VIDEO_DIR = ROOT_DIR / "output" / "videos"
FINAL_VIDEO_DIR.mkdir(parents=True, exist_ok=True)

SCENES = [
    {
        "id": "scene_1",
        "title": "The Hook",
        "narration": "Most people spend their lives chasing money. Wealthy people learn how to make money chase them.",
        "image": ASSETS_DIR / "scene_1.jpg",
        "headline": "STOP CHASING MONEY.",
        "subhead": "",
        "motion": "zoom_in",  # Push in towards upper body
    },
    {
        "id": "scene_2",
        "title": "The Real Difference",
        "narration": "The difference isn't always how much money you make. It's what you do with the money you already have. Some people spend every extra rupee. Others use a portion of their income to build assets.",
        "image": ASSETS_DIR / "scene_2.jpg",
        "headline": "INCOME IS NOT WEALTH.",
        "subhead": "Spend on Liabilities vs Build Assets",
        "motion": "pan_left_to_right",  # Slow pan towards presenter
    },
    {
        "id": "scene_3",
        "title": "Explain the Concept",
        "narration": "An asset can help grow your wealth or generate income. But every investment carries risk. The goal isn't to look rich today. It's to build a financial foundation that gives you more choices tomorrow.",
        "image": ASSETS_DIR / "scene_3.jpg",
        "headline": "BUILD WEALTH. MANAGE RISK.",
        "subhead": "ILLUSTRATIVE - NOT GUARANTEED",
        "motion": "pan_slow",  # Dashboard tracking
    },
    {
        "id": "scene_4",
        "title": "The Mindset Shift",
        "narration": "Before making your next big purchase, ask yourself... Will this decision strengthen your financial future, or make it harder?",
        "image": ASSETS_DIR / "scene_4.jpg",
        "headline": "ASK YOURSELF:",
        "subhead": "Does it strengthen your FINANCIAL FUTURE?",
        "motion": "zoom_in_slow",  # Thoughtful push in
    },
    {
        "id": "scene_5",
        "title": "Memorable Ending",
        "narration": "You don't have to become rich overnight. Start making smarter decisions, stay consistent, and let time do its work.",
        "image": ASSETS_DIR / "scene_5.jpg",
        "headline": "THINK LONG TERM.",
        "subhead": "BUILD YOUR FUTURE.",
        "motion": "zoom_out",  # Pull back to reveal full silhouette
    },
]


def step1_generate_scene_audio():
    print("=== STEP 1: GENERATING VOICE AUDIO FOR ALL 5 SCENES ===")
    scene_audios = []
    total_duration = 0.0

    for idx, sc in enumerate(SCENES):
        prefix = f"{sc['id']}_vo"
        res = synthesize_speech(
            text=sc["narration"],
            output_dir=OUTPUT_DIR,
            filename_prefix=prefix,
            voice="en-US-AndrewMultilingualNeural",
            rate="-3%",
            normalize=True,
        )
        audio_path = res["audio_path"]
        dur = res["duration"]
        # Add padding (0.6s) to allow natural transition breathing
        padded_dur = dur + 0.6
        scene_audios.append({
            "scene": sc,
            "audio_path": audio_path,
            "duration": dur,
            "padded_duration": padded_dur,
            "srt_path": res["srt_path"],
            "words": res["word_timestamps"]
        })
        total_duration += padded_dur
        print(f" [OK] Scene {idx+1} audio: {dur:.2f}s (Padded: {padded_dur:.2f}s)")

    print(f"Total Speech Duration: {total_duration:.2f}s")
    return scene_audios


def step2_create_ambient_music(total_duration: float, output_path: Path):
    """Generates a subtle, cinematic ambient soundscape (warm bass drone + gentle harmony)."""
    print("=== STEP 2: GENERATING CINEMATIC AMBIENT AUDIO BED ===")
    d = total_duration + 4.0
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"anoisesrc=d={d:.1f}:c=pink:r=44100:a=0.015",
        "-f", "lavfi",
        "-i", f"sine=frequency=55:duration={d:.1f}",
        "-f", "lavfi",
        "-i", f"sine=frequency=110:duration={d:.1f}",
        "-filter_complex",
        f"[1:a]volume=0.12[sub];[2:a]volume=0.04[mid];[0:a]lowpass=f=400[noise];[sub][mid][noise]amix=inputs=3:duration=first,afade=t=in:ss=0:d=2,afade=t=out:st={total_duration:.1f}:d=3[out]",
        "-map", "[out]",
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(output_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error creating ambient audio: {res.stderr[-300:]}")
        raise RuntimeError(f"FFmpeg ambient failed: {res.stderr[-200:]}")
    print(f" [OK] Ambient music bed created: {output_path.name}")


def step3_animate_scene(scene_info: dict, index: int) -> Path:
    """
    Renders an animated 1080x1920 30fps clip with:
    - Cinematic camera motion on the high-res character plate (push-in / pull-back / pan)
    - Gold rim volumetric vignette
    - Motion graphic text overlays (headline, subhead)
    """
    sc = scene_info["scene"]
    duration = scene_info["padded_duration"]
    img_path = sc["image"]
    clip_output = OUTPUT_DIR / f"{sc['id']}_animated.mp4"

    fps = 30
    total_frames = int(duration * fps)

    motion = sc["motion"]
    headline = sc["headline"]
    subhead = sc["subhead"]

    # Build zoompan filter without -loop
    if motion == "zoom_in":
        # Slow dramatic push in towards upper body
        v_motion = f"scale=1200:2133,zoompan=z='min(zoom+0.0004,1.14)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih*0.25-(ih/zoom*0.25)':s=1080x1920:fps={fps}"
    elif motion == "zoom_out":
        # Pull back from 1.12 to 1.0 to reveal full silhouette
        v_motion = f"scale=1200:2133,zoompan=z='max(1.12-0.0004*on,1.0)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih*0.3-(ih/zoom*0.3)':s=1080x1920:fps={fps}"
    elif motion == "pan_left_to_right":
        # Gentle pan
        v_motion = f"scale=1200:2133,zoompan=z='1.06':d={total_frames}:x='min((on/{total_frames})*(iw-iw/zoom)*0.7, (iw-iw/zoom))':y='ih*0.2-(ih/zoom*0.2)':s=1080x1920:fps={fps}"
    else:
        # Subtle gentle breathing push
        v_motion = f"scale=1200:2133,zoompan=z='min(1.02+0.0003*on,1.10)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih*0.25-(ih/zoom*0.25)':s=1080x1920:fps={fps}"

    font_file = "C:/Windows/Fonts/segoeuib.ttf"
    if not Path(font_file).exists():
        font_file = "C:/Windows/Fonts/arialbd.ttf"
    font_file_escaped = font_file.replace("\\", "/").replace(":", "\\:")

    filters = [v_motion, "vignette=angle=0.4:aspect=9/16"]

    # Animated headline
    if headline:
        hl_escaped = headline.replace("'", "").replace(":", "-")
        filters.append(
            f"drawtext=fontfile='{font_file_escaped}':text='{hl_escaped}':"
            f"fontsize=52:fontcolor=0xD4AF37:borderw=3:bordercolor=black:"
            f"x=(w-text_w)/2:y=240:enable='gte(t,0.3)':alpha='min(1,(t-0.3)*2)'"
        )

    if subhead:
        sh_escaped = subhead.replace("'", "").replace(":", "-")
        filters.append(
            f"drawtext=fontfile='{font_file_escaped}':text='{sh_escaped}':"
            f"fontsize=36:fontcolor=white:borderw=2:bordercolor=black:"
            f"x=(w-text_w)/2:y=310:enable='gte(t,0.8)':alpha='min(1,(t-0.8)*2)'"
        )

    # Scene 2 specific: Graphic callout cards on the left side
    if sc["id"] == "scene_2":
        filters.append(
            f"drawtext=fontfile='{font_file_escaped}':text='INCOME PATHWAYS':"
            f"fontsize=32:fontcolor=0xD4AF37:borderw=2:bordercolor=black:"
            f"x=80:y=650:enable='gte(t,1.2)':alpha='min(1,(t-1.2)*2)'"
        )
        filters.append(
            f"drawtext=fontfile='{font_file_escaped}':text='- Most Spend On Liabilities':"
            f"fontsize=30:fontcolor=0xFF7777:borderw=2:bordercolor=black:"
            f"x=80:y=720:enable='gte(t,2.2)':alpha='min(1,(t-2.2)*2)'"
        )
        filters.append(
            f"drawtext=fontfile='{font_file_escaped}':text='- Wealthy Buy Assets First':"
            f"fontsize=30:fontcolor=0x77FF77:borderw=2:bordercolor=black:"
            f"x=80:y=790:enable='gte(t,3.5)':alpha='min(1,(t-3.5)*2)'"
        )

    # Scene 3 specific: Holographic dashboard tags
    if sc["id"] == "scene_3":
        filters.append(
            f"drawtext=fontfile='{font_file_escaped}':text='ASSETS vs RISK PROFILE':"
            f"fontsize=34:fontcolor=0xD4AF37:borderw=2:bordercolor=black:"
            f"x=(w-text_w)/2:y=1550:enable='gte(t,1.0)':alpha='min(1,(t-1.0)*2)'"
        )
        filters.append(
            f"drawtext=fontfile='{font_file_escaped}':text='[ILLUSTRATIVE - NOT FINANCIAL ADVICE]':"
            f"fontsize=24:fontcolor=0xAAAAAA:borderw=1:bordercolor=black:"
            f"x=(w-text_w)/2:y=1610:enable='gte(t,1.5)':alpha='min(1,(t-1.5)*2)'"
        )

    # Scene 4 specific: Mindset shift emphasis
    if sc["id"] == "scene_4":
        filters.append(
            f"drawbox=y=1380:color=black@0.6:width=iw:height=220:t=fill:enable='gte(t,0.5)'"
        )
        filters.append(
            f"drawtext=fontfile='{font_file_escaped}':text='DOES THIS DECISION':"
            f"fontsize=38:fontcolor=white:x=(w-text_w)/2:y=1410:enable='gte(t,0.8)'"
        )
        filters.append(
            f"drawtext=fontfile='{font_file_escaped}':text='STRENGTHEN YOUR FUTURE?':"
            f"fontsize=44:fontcolor=0xD4AF37:borderw=2:bordercolor=black:x=(w-text_w)/2:y=1480:enable='gte(t,1.4)'"
        )

    # Scene 5 specific: Final brand card
    if sc["id"] == "scene_5":
        filters.append(
            f"drawbox=y=1320:color=black@0.65:width=iw:height=260:t=fill:enable='gte(t,1.0)'"
        )
        filters.append(
            f"drawtext=fontfile='{font_file_escaped}':text='THINK LONG TERM':"
            f"fontsize=48:fontcolor=0xD4AF37:borderw=3:bordercolor=black:x=(w-text_w)/2:y=1360:enable='gte(t,1.2)'"
        )
        filters.append(
            f"drawtext=fontfile='{font_file_escaped}':text='BUILD REAL WEALTH':"
            f"fontsize=42:fontcolor=white:borderw=2:bordercolor=black:x=(w-text_w)/2:y=1440:enable='gte(t,2.0)'"
        )

    filter_complex = ",".join(filters)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(img_path),
        "-vf", filter_complex,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-an",
        str(clip_output)
    ]

    print(f" Rendering animated Scene {index+1} ({duration:.2f}s, {total_frames} frames)...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error rendering Scene {index+1}: {res.stderr[-400:]}")
        raise RuntimeError(f"FFmpeg scene render failed: {res.stderr[-200:]}")

    print(f" [OK] Scene {index+1} animated: {clip_output.name}")
    return clip_output


def step4_concatenate_scenes_with_transitions(clip_paths: list[Path], scene_infos: list[dict], output_path: Path):
    """Concatenates scene clips with smooth crossfade / xfade transitions."""
    print("=== STEP 4: CONCATENATING SCENES WITH CROSSFADE TRANSITIONS ===")
    fade_dur = 0.5
    n = len(clip_paths)
    if n == 1:
        cmd = ["ffmpeg", "-y", "-i", str(clip_paths[0]), "-c", "copy", str(output_path)]
        subprocess.run(cmd, check=True)
        return

    input_args = []
    for c in clip_paths:
        input_args.extend(["-i", str(c)])

    durations = [s["padded_duration"] for s in scene_infos]
    filter_parts = []
    last_stream = "[0:v]"
    current_offset = durations[0] - fade_dur

    for i in range(1, n):
        next_stream = f"[{i}:v]"
        out_stream = f"[v{i}]" if i < n - 1 else "[outv]"
        filter_parts.append(
            f"{last_stream}{next_stream}xfade=transition=fade:duration={fade_dur:.2f}:offset={current_offset:.2f}{out_stream}"
        )
        last_stream = out_stream
        if i < n - 1:
            current_offset += durations[i] - fade_dur

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *input_args,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(output_path)
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error concatenating clips: {res.stderr[-400:]}")
        raise RuntimeError(f"FFmpeg xfade failed: {res.stderr[-200:]}")

    print(f" [OK] Video stream concatenated with smooth transitions: {output_path.name}")


def step5_assemble_full_audio(scene_infos: list[dict], ambient_path: Path, output_audio: Path):
    """Concatenates speech tracks and mixes with background ambient bed."""
    print("=== STEP 5: ASSEMBLING MASTER AUDIO TRACK ===")
    speech_concat_list = OUTPUT_DIR / "speech_list.txt"
    with open(speech_concat_list, "w", encoding="utf-8") as f:
        for s in scene_infos:
            posix_path = s["audio_path"].resolve().as_posix()
            f.write(f"file '{posix_path}'\n")

    speech_merged = OUTPUT_DIR / "speech_merged.mp3"
    cmd_speech = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(speech_concat_list),
        "-c", "copy",
        str(speech_merged)
    ]
    subprocess.run(cmd_speech, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    speech_dur = get_audio_duration(speech_merged)

    # Mix speech with Succession BGM (subtle volume at 0.10 so voice is crystal clear)
    succession_bgm = ROOT_DIR / "assets" / "sounds" / "bgm_succession.mp3"
    bg_input = succession_bgm if succession_bgm.exists() else ambient_path

    cmd_mix = [
        "ffmpeg", "-y",
        "-i", str(speech_merged),
        "-i", str(bg_input),
        "-filter_complex",
        f"[1:a]volume=0.10,afade=t=in:ss=0:d=1.5,afade=t=out:st={max(speech_dur-2.5, 1.0):.1f}:d=2.5[bg];"
        f"[0:a]volume=1.25[vox];"
        f"[vox][bg]amix=inputs=2:duration=first:dropout_transition=2[outa]",
        "-map", "[outa]",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        str(output_audio)
    ]
    subprocess.run(cmd_mix, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f" [OK] Master audio track created with Succession BGM: {output_audio.name} ({speech_dur:.2f}s)")
    return speech_dur


def step6_generate_full_srt(scene_infos: list[dict], output_srt: Path):
    """Builds a combined master SRT subtitle file with proper time offsets."""
    print("=== STEP 6: GENERATING MASTER KINETIC SUBTITLES ===")
    combined_words = []
    current_time_offset = 0.0

    for sc in scene_infos:
        words = sc.get("words", [])
        for w in words:
            combined_words.append({
                "word": w["word"],
                "start": w["start"] + current_time_offset,
                "end": w["end"] + current_time_offset
            })
        current_time_offset += sc["padded_duration"]

    subtitles = []
    chunk_size = 3
    for i in range(0, len(combined_words), chunk_size):
        chunk = combined_words[i:i + chunk_size]
        if not chunk:
            continue
        start_sec = chunk[0]["start"]
        end_sec = chunk[-1]["end"]
        if end_sec - start_sec < 0.8:
            end_sec = start_sec + 0.8
        text = " ".join([c["word"] for c in chunk]).strip().upper()
        subtitles.append((start_sec, end_sec, text))

    def _fmt_ts(s):
        ms = int((s - int(s)) * 1000)
        m, sec = divmod(int(s), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

    with open(output_srt, "w", encoding="utf-8") as f:
        for idx, (st, en, txt) in enumerate(subtitles, 1):
            f.write(f"{idx}\n{_fmt_ts(st)} --> {_fmt_ts(en)}\n{txt}\n\n")

    print(f" [OK] Subtitles generated: {output_srt.name} ({len(subtitles)} captions)")


def step7_render_final_video(video_track: Path, audio_track: Path, srt_path: Path, output_mp4: Path):
    """Burns subtitles, overlays top progress bar and exports 1080x1920 YouTube Shorts MP4."""
    print("=== STEP 7: COMPOSITING FINAL MASTER VIDEO ===")
    srt_escaped = str(srt_path).replace("\\", "/").replace(":", "\\:")
    
    font_file = "C:/Windows/Fonts/segoeuib.ttf"
    if not Path(font_file).exists():
        font_file = "C:/Windows/Fonts/arialbd.ttf"
    font_name = "Segoe UI" if "segoe" in font_file.lower() else "Arial"

    sub_style = (
        f"subtitles='{srt_escaped}':force_style='"
        f"FontName={font_name},"
        f"FontSize=22,"
        f"PrimaryColour=&H0000FFFF,"
        f"SecondaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,"
        f"BackColour=&HA0000000,"
        f"Bold=1,"
        f"BorderStyle=3,"
        f"Outline=2,"
        f"Shadow=0,"
        f"Alignment=2,"
        f"MarginV=380'"
    )

    total_dur = get_audio_duration(audio_track)
    progress_bar = f"drawbox=x=0:y=0:w='w*(t/{total_dur})':h=10:color=0xD4AF37:t=fill"

    filter_complex = f"[0:v]{progress_bar},{sub_style}[outv]"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_track),
        "-i", str(audio_track),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "17",
        "-c:a", "aac",
        "-b:a", "256k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(output_mp4)
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error in final render: {res.stderr[-500:]}")
        raise RuntimeError(f"Final render failed: {res.stderr[-300:]}")

    size_mb = output_mp4.stat().st_size / (1024 * 1024)
    print(f"\n=======================================================")
    print(f"  MASTER VIDEO SUCCESSFULLY GENERATED!")
    print(f"  Path: {output_mp4}")
    print(f"  Size: {size_mb:.2f} MB")
    print(f"  Duration: {total_dur:.1f}s")
    print(f"=======================================================")
    return output_mp4


def step8_publish_to_youtube(video_path: Path):
    """Publishes the rendered video to YouTube Shorts."""
    print("=== STEP 8: PUBLISHING MASTER VIDEO TO YOUTUBE ===")
    from publishing.youtube_publisher import _upload_youtube_production
    title = "The Money Habits That Separate The Rich From Everyone Else #Shorts"
    description = (
        "Wealthy people don't just chase money—they make money work for them.\n\n"
        "Here are the core money habits that separate true wealth builders from everyone else:\n"
        "• Income is NOT wealth.\n"
        "• High earners spend on liabilities; the wealthy buy income-producing assets.\n"
        "• Every investment carries risk—the goal is building choices for tomorrow.\n"
        "• Ask before every purchase: Will this strengthen my financial future?\n\n"
        "Think long term. Build your future.\n\n"
        "---\n"
        "Channel: FinanceSimple - Money made simple\n"
        "Educational content only. Not financial advice.\n\n"
        "#Shorts #Finance #PersonalFinance #MoneyHabits #Investing #Wealth"
    )
    tags = [
        "finance", "money habits", "wealth", "investing", "personal finance",
        "rich mindset", "financial freedom", "shorts", "youtube shorts"
    ]
    upload_id = str(uuid.uuid4())
    res = _upload_youtube_production(
        upload_id=upload_id,
        topic_id="MONEY_HABITS_MASTER_01",
        video_path=video_path,
        title=title,
        description=description,
        tags=tags,
        privacy_status="public",
    )
    print(" [OK] YouTube Upload Response:")
    print(json.dumps(res, indent=2))
    return res


def main():
    print("Starting Luxury Finance Presenter Video Generation Pipeline...")

    # 1. Synthesize Audio
    scene_infos = step1_generate_scene_audio()
    total_scene_duration = sum(s["padded_duration"] for s in scene_infos)

    # 2. Ambient Music Bed
    ambient_audio = OUTPUT_DIR / "ambient_bed.mp3"
    step2_create_ambient_music(total_scene_duration, ambient_audio)

    # 3. Animate Each Scene
    print("=== STEP 3: ANIMATING CAMERA MOTIONS & OVERLAYS ===")
    scene_clips = []
    for idx, sc_info in enumerate(scene_infos):
        clip = step3_animate_scene(sc_info, idx)
        scene_clips.append(clip)

    # 4. Concatenate with XFade
    concat_video = OUTPUT_DIR / "scenes_concatenated.mp4"
    step4_concatenate_scenes_with_transitions(scene_clips, scene_infos, concat_video)

    # 5. Assemble Master Audio
    master_audio = OUTPUT_DIR / "master_audio.mp3"
    speech_dur = step5_assemble_full_audio(scene_infos, ambient_audio, master_audio)

    # 6. Master Subtitles
    master_srt = OUTPUT_DIR / "master_subtitles.srt"
    step6_generate_full_srt(scene_infos, master_srt)

    # 7. Final Render
    final_output = FINAL_VIDEO_DIR / "money_habits_of_the_rich_master.mp4"
    step7_render_final_video(concat_video, master_audio, master_srt, final_output)

    # 8. Publish to YouTube
    step8_publish_to_youtube(final_output)


if __name__ == "__main__":
    main()
