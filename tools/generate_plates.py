"""
Finance Shorts Pro - Batch Plate Generator
Generates vertical 9:16 luxury cinematic still plates using Antigravity generator.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

# Add repo root to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config
from visuals.plate_gate import evaluate_plate
from visuals.plate_manifest import load_manifest, save_manifest
from visuals.plate_prompt import build_plate_prompt

IST = ZoneInfo("Asia/Kolkata")

# Setup plates logger
LOG_DIR = Path(config.DATA_DIR) / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "plates.log"

logger = logging.getLogger("plates_generator")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")

fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
fh.setFormatter(formatter)
logger.addHandler(fh)


def soften_subject(subject: str, attempt: int) -> str:
    """Softens subject prompt slightly on 'No image data found' (safety/filter avoidance)."""
    clean = subject.replace("shadowy", "peaceful").replace("storm", "calm atmosphere")
    if attempt == 1:
        return f"{clean}, peaceful artistic composition"
    return f"minimalist abstract geometry, {clean}"


def run_node_generator(
    gen_script: Path | str,
    prompt: str,
    output_png: Path,
    aspect_ratio: str = "9:16",
) -> tuple[int, str, str]:
    """
    Executes the Antigravity node image generation script via subprocess.
    Returns (returncode, stdout, stderr).
    """
    cmd = [
        "node",
        str(gen_script),
        "--prompt",
        prompt,
        "--output",
        str(output_png),
        "--aspect-ratio",
        aspect_ratio,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return res.returncode, res.stdout, res.stderr


def generate_plates(
    curriculum_path: Optional[Path] = None,
    plates_dir: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    only_ids: Optional[list[str]] = None,
    force: bool = False,
    max_per_run: int = 10,
    dry_run: bool = False,
    backoff_delays: tuple[float, ...] = (60.0, 120.0, 240.0),
    gen_script: Optional[str] = None,
) -> int:
    """
    Batch generates topic plates with strict retry, backoff, and quality gate policies.
    Returns exit code:
      0 = all requested generated or skipped
      1 = any topic flagged or failed
      2 = auth failure
    """
    c_path = Path(curriculum_path or (ROOT / "curriculum_42.json"))
    p_dir = Path(plates_dir or getattr(config, "PLATE_DIR", ROOT / "assets" / "plates"))
    p_dir.mkdir(parents=True, exist_ok=True)
    m_path = Path(manifest_path or (p_dir / "manifest.json"))

    active_script = gen_script or os.environ.get("ANTIGRAVITY_GEN_SCRIPT") or getattr(config, "ANTIGRAVITY_GEN_SCRIPT", "")

    if not c_path.exists():
        logger.error("Curriculum file not found: %s", c_path)
        print(f"[ERROR] Curriculum file not found: {c_path}", file=sys.stderr)
        return 1

    with open(c_path, "r", encoding="utf-8") as f:
        topics = json.load(f)

    if only_ids:
        only_set = {str(i).strip().upper() for i in only_ids}
        topics = [t for t in topics if str(t.get("topic_id", "")).strip().upper() in only_set]

    manifest = load_manifest(m_path)
    manifest_topics = manifest.setdefault("topics", {})

    generated_count = 0
    any_failed_or_flagged = False
    temp_dir = p_dir / ".temp_gen"
    temp_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 70)
    print("  FINANCE SHORTS PRO — BATCH PLATE GENERATOR")
    print(f"  Target: {len(topics)} topics | Cap: {max_per_run} | Force: {force} | DryRun: {dry_run}")
    print("=" * 70)

    try:
        for idx, topic in enumerate(topics):
            tid = str(topic.get("topic_id", f"T{idx+1:02d}"))
            out_jpg = p_dir / f"{tid}.jpg"

            # Check skip condition
            if out_jpg.exists() and not force:
                m_entry = manifest_topics.get(tid)
                luma = f"top={m_entry.get('luma_top', '?')}/bot={m_entry.get('luma_bottom', '?')}" if m_entry else "existing"
                print(f"  [{tid}] status=skipped  attempts=0  luma={luma}")
                logger.info("[%s] skipped: plate exists and force=False", tid)
                continue

            if generated_count >= max_per_run:
                remaining = len(topics) - idx
                print(f"\n[INFO] Reached max-per-run cap ({max_per_run}). {remaining} topic(s) remaining for next run.")
                logger.info("Reached max-per-run cap (%d). Remaining: %d", max_per_run, remaining)
                break

            # Build prompt
            try:
                prompt = build_plate_prompt(topic)
            except Exception as pe:
                print(f"  [{tid}] status=failed   attempts=0  reason=prompt_error: {pe}")
                logger.error("[%s] prompt building error: %s", tid, pe)
                any_failed_or_flagged = True
                continue

            if dry_run:
                print(f"  [{tid}] status=ok (dry-run)  prompt='{prompt[:60]}...'")
                generated_count += 1
                continue

            # Generation loop with retries
            temp_png = temp_dir / f"{tid}_{int(time.time())}.png"
            status = "failed"
            attempts = 0
            gate_res = None
            consecutive_429_count = 0

            current_subject = topic.get("visual_subject", "")
            current_prompt = prompt

            if not active_script:
                logger.error("ANTIGRAVITY_GEN_SCRIPT is not set. Please set it in .env or environment.")
                print(
                    "[ERROR] ANTIGRAVITY_GEN_SCRIPT is not configured.\n"
                    "Set ANTIGRAVITY_GEN_SCRIPT in .env or environment to point to generate.js.",
                    file=sys.stderr,
                )
                return 2

            while attempts < 3:
                attempts += 1
                logger.info("[%s] Calling generator (attempt %d/3)...", tid, attempts)
                retcode, stdout, stderr = run_node_generator(active_script, current_prompt, temp_png)

                combined_output = f"{stdout}\n{stderr}"

                # 1. Auth Error Check
                if "Auth Error" in combined_output or "authentication error" in combined_output.lower():
                    print("\n[FATAL] Antigravity generator authentication error encountered!", file=sys.stderr)
                    print("Please run the Antigravity login command to refresh your local OAuth credentials.\n", file=sys.stderr)
                    logger.critical("[%s] Auth error encountered: %s", tid, combined_output)
                    return 2

                # 2. 429 / Quota check
                if "429" in combined_output or "Resource Exhausted" in combined_output or "quota" in combined_output.lower():
                    if consecutive_429_count < len(backoff_delays):
                        delay = backoff_delays[consecutive_429_count]
                        consecutive_429_count += 1
                        logger.warning("[%s] 429 Resource Exhausted. Sleeping %ds (backoff %d/%d)...", tid, delay, consecutive_429_count, len(backoff_delays))
                        print(f"  [{tid}] 429 Resource Exhausted. Backing off for {delay:.0f}s...")
                        time.sleep(delay)
                        continue
                    else:
                        logger.error("[%s] 429 backoff exhausted after 3 failures. Halting batch.", tid)
                        print(f"\n[ERROR] 429 Resource Exhausted. Exponential backoff exhausted. Stopping run.", file=sys.stderr)
                        return 1

                # Reset 429 counter on non-429
                consecutive_429_count = 0

                # 3. No image data found (safety refusal or API change)
                if "No image data found" in combined_output or not temp_png.exists() or temp_png.stat().st_size == 0:
                    if attempts < 3:
                        logger.warning("[%s] No image data found. Softening visual subject (attempt %d)...", tid, attempts)
                        current_subject = soften_subject(topic.get("visual_subject", ""), attempts)
                        alt_topic = dict(topic)
                        alt_topic["visual_subject"] = current_subject
                        current_prompt = build_plate_prompt(alt_topic)
                        continue
                    else:
                        logger.error("[%s] Failed to generate after 2 soften retries. Flagging topic.", tid)
                        status = "flagged"
                        break

                # 4. Success confirmation: "MEDIA:" in stdout and valid file
                if retcode == 0 and "MEDIA:" in stdout and temp_png.exists() and temp_png.stat().st_size > 0:
                    # Run Quality Gate
                    gate_res, processed_img = evaluate_plate(temp_png)
                    if processed_img and gate_res.passed:
                        # Save final JPEG
                        processed_img.save(out_jpg, "JPEG", quality=95)
                        status = "ok"
                        break
                    elif processed_img and not gate_res.passed:
                        # Failed gate (e.g. too bright or flat)
                        logger.warning("[%s] Image generated but failed quality gate: %s", tid, gate_res.reason)
                        if attempts < 3:
                            continue
                        else:
                            # Save with passes_gate=False in manifest
                            processed_img.save(out_jpg, "JPEG", quality=95)
                            status = "flagged"
                            break

            # Record in manifest
            now_str = datetime.now(IST).isoformat()
            entry_data = {
                "file": f"assets/plates/{tid}.jpg",
                "prompt": current_prompt,
                "generator": "antigravity-image-gen",
                "aspect_ratio": "9:16",
                "generated_at": now_str,
                "attempts": attempts,
                "luma_top": getattr(gate_res, "luma_top", 0.0) if gate_res else 0.0,
                "luma_bottom": getattr(gate_res, "luma_bottom", 0.0) if gate_res else 0.0,
                "passes_gate": getattr(gate_res, "passed", False) if gate_res else False,
                "status": status,
            }
            manifest.setdefault("topics", {})[tid] = entry_data
            save_manifest(manifest, m_path)

            luma_disp = f"top={entry_data['luma_top']}/bot={entry_data['luma_bottom']}"
            print(f"  [{tid}] status={status:<7} attempts={attempts}  luma={luma_disp}")
            logger.info("[%s] status=%s attempts=%d luma=%s", tid, status, attempts, luma_disp)

            if status in ("flagged", "failed"):
                any_failed_or_flagged = True
            elif status == "ok":
                generated_count += 1

            # Cleanup temp png
            temp_png.unlink(missing_ok=True)

    finally:
        # Clean temp directory
        try:
            for f in temp_dir.glob("*.png"):
                f.unlink(missing_ok=True)
            temp_dir.rmdir()
        except Exception:
            pass

    print("=" * 70)
    print(f"Batch completed. Generated: {generated_count} | Flagged/Failed: {1 if any_failed_or_flagged else 0}\n")
    return 1 if any_failed_or_flagged else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Antigravity Visual Plates Batch Generator")
    parser.add_argument("--only", nargs="+", help="Specific topic ID(s) to generate (e.g. T01 T02)")
    parser.add_argument("--force", action="store_true", help="Regenerate even if plate exists")
    parser.add_argument("--max-per-run", type=int, default=10, help="Max plates to generate in this run (default: 10)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate generation without executing node script")

    args = parser.parse_args()

    code = generate_plates(
        only_ids=args.only,
        force=args.force,
        max_per_run=args.max_per_run,
        dry_run=args.dry_run,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
