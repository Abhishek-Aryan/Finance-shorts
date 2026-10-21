"""
Finance Shorts Pro - Preflight Environment & Health Checker.

Validates:
1. Critical environment variables in production mode:
   - OPENROUTER_API_KEY
   - YOUTUBE_CLIENT_SECRETS_JSON
   - YOUTUBE_TOKEN_JSON
   - GEMINI_API_KEY (if SCRIPT_MODEL uses Gemini)
   - INSTAGRAM_* (only if Instagram publishing is enabled)
2. Schedule files exist and load:
   - data/publishing_schedule.xlsx
   - data/schedule_state.json
3. Binary dependencies on PATH:
   - ffmpeg
   - ffprobe
4. Directory permissions:
   - output/ and logs/ must be writable.

Exit codes:
- 0: All checks passed.
- 2: Configuration or credential error.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Add repo root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config


def check_env_vars(mode: str) -> list[str]:
    """Checks required environment variables for production mode. Returns list of missing names."""
    if mode != "production":
        return []

    missing: list[str] = []

    # Mandatory production variables
    required_vars = [
        "OPENROUTER_API_KEY",
        "YOUTUBE_CLIENT_SECRETS_JSON",
        "YOUTUBE_TOKEN_JSON",
    ]

    # Check Gemini API Key if Gemini is the script model
    script_model = getattr(config, "SCRIPT_MODEL", "gemini-flash-lite-latest")
    if "gemini" in script_model.lower():
        required_vars.append("GEMINI_API_KEY")

    # Instagram variables only if Instagram is enabled
    instagram_enabled = getattr(config, "INSTAGRAM_PUBLISH_ENABLED", False) or (
        os.environ.get("INSTAGRAM_PUBLISH_ENABLED", "").lower() in ("true", "1", "yes")
    )
    if instagram_enabled:
        required_vars.extend(["INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_ACCOUNT_ID"])

    for var in required_vars:
        val = os.environ.get(var)
        if not val or not val.strip():
            missing.append(var)

    return missing


def check_files(excel_path: Path | None = None, state_path: Path | None = None) -> list[str]:
    """Validates that publishing schedule Excel and JSON state store exist and load."""
    errors: list[str] = []
    e_path = excel_path or config.SCHEDULE_EXCEL
    s_path = state_path or (config.DATA_DIR / "schedule_state.json")

    # Check Excel
    if not e_path.exists():
        errors.append(f"Schedule file missing: {e_path}")
    else:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(str(e_path), data_only=True)
            if "Publishing Schedule" not in wb.sheetnames and not wb.active:
                errors.append(f"Invalid Excel sheet structure: {e_path}")
        except Exception as exc:
            errors.append(f"Failed to load Excel workbook {e_path}: {exc}")

    # Check JSON state
    if not s_path.exists():
        errors.append(f"State file missing: {s_path}")
    else:
        try:
            with open(s_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict) or "rows" not in data:
                    errors.append(f"State file {s_path} is missing 'rows' structure")
        except Exception as exc:
            errors.append(f"Failed to load JSON state {s_path}: {exc}")

    return errors


def check_binaries() -> list[str]:
    """Validates that ffmpeg and ffprobe are available on system PATH."""
    errors: list[str] = []
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            # Also test running the binary in case which fails on some Windows/sandbox PATH setups
            try:
                subprocess.run(
                    [binary, "-version"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
            except Exception:
                errors.append(f"Required binary not found on PATH: {binary}")
    return errors


def check_writable_dirs() -> list[str]:
    """Validates that output and logs directories exist and are writable."""
    errors: list[str] = []
    for dir_path in (config.OUTPUT_DIR, config.LOGS_DIR):
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=str(dir_path), delete=True) as tmp:
                tmp.write(b"preflight_write_test")
        except Exception as exc:
            errors.append(f"Directory is not writable: {dir_path} ({exc})")
    return errors


def run_preflight(mode: str | None = None) -> int:
    """Runs all preflight checks and returns exit code (0 for pass, 2 for failure)."""
    # Determine mode
    resolved_mode = mode or os.environ.get("MODE") or config.PUBLISHING_MODE
    resolved_mode = resolved_mode.lower().strip()

    print(f"=== FINANCE SHORTS PRO PREFLIGHT (Mode: {resolved_mode.upper()}) ===")

    # 1. Environment variables check
    missing_vars = check_env_vars(resolved_mode)
    if missing_vars:
        print("[CONFIG ERROR] Missing required environment variables:")
        for var in missing_vars:
            print(f"  - {var}")
        return 2

    # 2. File checks
    file_errors = check_files()
    if file_errors:
        print("[CONFIG ERROR] Schedule file errors:")
        for err in file_errors:
            print(f"  - {err}")
        return 2

    # 3. Binary dependencies check
    bin_errors = check_binaries()
    if bin_errors:
        print("[CONFIG ERROR] Binary dependency errors:")
        for err in bin_errors:
            print(f"  - {err}")
        return 2

    # 4. Writable directories check
    dir_errors = check_writable_dirs()
    if dir_errors:
        print("[CONFIG ERROR] Storage directory errors:")
        for err in dir_errors:
            print(f"  - {err}")
        return 2

    print("[OK] All preflight checks passed successfully.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight check for Finance Shorts Pro")
    parser.add_argument(
        "--mode",
        choices=["test", "production"],
        default=None,
        help="Publishing mode (default: inferred from environment or config)",
    )
    args = parser.parse_args()
    code = run_preflight(args.mode)
    sys.exit(code)


if __name__ == "__main__":
    main()
