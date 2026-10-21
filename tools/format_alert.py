"""
Finance Shorts Pro - Alert Body & Title Formatter.
Generates sanitized markdown alert bodies for GitHub Issues on publishing failure.
Masks secrets (AIza, ya29., sk-, Bearer) and extracts failed/in-progress topic metadata.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Add repo root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config

IST = ZoneInfo("Asia/Kolkata")

EXIT_CODE_MEANINGS = {
    "0": "OK or nothing due",
    "1": "Pipeline failure (Script generation, TTS audio, HeyGen visuals, or video composition error)",
    "2": "Configuration or credential error (Missing API keys, missing OAuth client secrets, or expired/revoked YouTube token)",
    "3": "State conflict (Excel row is marked 'Pending' but state store records 'Done' with a YouTube video ID)",
    "4": "Published to YouTube, but Excel view is stale / locked",
}


def sanitize_text(text: str) -> str:
    """Masks secret patterns: AIza, ya29., sk-, Bearer tokens."""
    # Mask Google API keys (AIza...)
    text = re.sub(r"AIza[0-9A-Za-z_-]{35}", "***", text)
    # Mask Google OAuth access tokens (ya29....)
    text = re.sub(r"ya29\.[0-9A-Za-z_-]+", "***", text)
    # Mask OpenRouter / OpenAI API keys (sk-...)
    text = re.sub(r"sk-[0-9A-Za-z_-]{20,}", "***", text)
    # Mask Bearer header tokens
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer ***", text)
    return text


def get_latest_failed_or_in_progress_topic(state_file: Path | None = None) -> tuple[str, str, str]:
    """
    Finds the most recently updated row with status 'Failed' or 'In progress' in state.
    Returns (row_key, topic, status).
    """
    s_path = state_file or (config.DATA_DIR / "schedule_state.json")
    if not s_path.exists():
        return ("unknown", "Unknown topic", "unknown")

    try:
        with open(s_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        rows = data.get("rows", {})
        candidates = [
            (rk, r) for rk, r in rows.items()
            if r.get("status") in ("Failed", "In progress")
        ]
        if not candidates:
            # Fallback to any row with attempts > 0 or last_error
            candidates = [
                (rk, r) for rk, r in rows.items()
                if (r.get("attempts", 0) > 0 or r.get("last_error"))
            ]
        if candidates:
            # Sort by scheduled_at or row_index
            rk, r = candidates[-1]
            return (rk, r.get("topic", "Unknown topic"), r.get("status", "unknown"))
    except Exception:
        pass
    return ("unknown", "Unknown topic", "unknown")


def get_last_log_lines(log_path: Path | str | None, num_lines: int = 20) -> str:
    """Reads the last N lines of log file and sanitizes secrets."""
    if not log_path:
        return "No log file specified."
    p = Path(log_path)
    if not p.exists():
        return f"Log file {p} not found."

    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        last_n = lines[-num_lines:] if len(lines) >= num_lines else lines
        raw = "\n".join(last_n)
        return sanitize_text(raw)
    except Exception as exc:
        return f"Failed to read log file: {exc}"


def build_alert(
    exit_code: str | int,
    run_url: str = "",
    log_path: Path | str | None = None,
    state_file: Path | None = None,
    slot_ist: str = "",
) -> tuple[str, str]:
    """
    Constructs (title, body) for GitHub Issue failure alert.
    """
    code_str = str(exit_code)
    meaning = EXIT_CODE_MEANINGS.get(code_str, f"Unknown exit code {code_str}")
    slot = slot_ist or datetime.now(IST).strftime("%H:%M IST")

    row_key, topic, status = get_latest_failed_or_in_progress_topic(state_file)
    log_excerpt = get_last_log_lines(log_path, num_lines=20)

    # Issue Title
    if code_str == "2":
        title = "YouTube token or credentials need attention"
    else:
        title = "Finance Shorts publish failed"

    # Issue Body
    body_lines = [
        f"### 🚨 Automation Alert: {title}",
        "",
        f"- **GitHub Run**: [{run_url or 'Actions Run'}]({run_url or '#'})",
        f"- **Trigger Slot**: `{slot}`",
        f"- **Topic Affected**: `{topic}` (`{row_key}` - status: `{status}`)",
        f"- **Exit Code**: `{code_str}` — *{meaning}*",
        "",
    ]

    if code_str == "2":
        body_lines.extend([
            "#### 🔑 Credential Recovery Instructions:",
            "The YouTube OAuth token or Google Cloud credentials have expired, been revoked, or are missing.",
            "",
            "1. **Authenticate Locally**:",
            "   ```powershell",
            "   .venv\\Scripts\\python main.py auth-youtube --force",
            "   ```",
            "2. **Copy the refreshed token**:",
            "   - Open `config/youtube_token.json` in a text editor.",
            "   - Copy the entire JSON content.",
            "3. **Update GitHub Repository Secret**:",
            "   - Go to: **Settings > Secrets and variables > Actions**.",
            "   - Update the **`YOUTUBE_TOKEN_JSON`** secret with the copied JSON.",
            "4. **Verify OAuth App Publishing Status**:",
            "   - In Google Cloud Console, ensure your OAuth consent screen is set to **'In production'** rather than 'Testing' (tokens in testing expire after ~7 days).",
            "",
        ])

    body_lines.extend([
        "#### 📋 Log Excerpt (Last 20 lines, sanitized):",
        "```text",
        log_excerpt,
        "```",
        "",
        "---",
        "*Automated alert generated by Finance Shorts Pro CI Publisher.*",
    ])

    return (title, "\n".join(body_lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Format GitHub issue alert for failures")
    parser.add_argument("--exit-code", default="1", help="Process exit code")
    parser.add_argument("--run-url", default="", help="GitHub Actions run URL")
    parser.add_argument("--log-path", default="", help="Path to execution log file")
    parser.add_argument("--state-file", default="", help="Path to schedule_state.json")
    parser.add_argument("--slot", default="", help="IST trigger slot string")
    parser.add_argument("--out-title", default="alert_title.txt", help="Output file for issue title")
    parser.add_argument("--out-body", default="alert_body.txt", help="Output file for issue body")

    args = parser.parse_args()

    s_file = Path(args.state_file) if args.state_file else None
    title, body = build_alert(
        exit_code=args.exit_code,
        run_url=args.run_url,
        log_path=args.log_path,
        state_file=s_file,
        slot_ist=args.slot,
    )

    Path(args.out_title).write_text(title, encoding="utf-8")
    Path(args.out_body).write_text(body, encoding="utf-8")
    print(f"Generated alert: '{title}' -> {args.out_title}, {args.out_body}")


if __name__ == "__main__":
    main()
