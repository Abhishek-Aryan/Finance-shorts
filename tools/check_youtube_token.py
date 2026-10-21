"""
Finance Shorts Pro - YouTube Token Health Checker.

Validates:
1. config/youtube_token.json exists and contains a refresh_token.
2. Refreshes access token via credentials.refresh(Request()).
3. Validates access with a read-only YouTube API call (channels.list(part='id', mine=True)).
4. Atomically writes updated access token back to config/youtube_token.json.

Exit codes:
- 0: Token is healthy and active.
- 2: Token is expired, revoked, missing, or invalid.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Add repo root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config

logger = logging.getLogger(__name__)


def check_youtube_token(token_file: Path | str | None = None) -> int:
    """
    Checks YouTube token health, refreshes if necessary, and makes a lightweight API test call.
    Never prints or logs secret token values.
    Returns exit code 0 on success, 2 on any token error.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError
    from googleapiclient.discovery import build

    t_path = Path(token_file or config.YOUTUBE_TOKEN_FILE)

    if not t_path.exists():
        print(f"[ERROR] YouTube token file does not exist: {t_path}", file=sys.stderr)
        return 2

    try:
        with open(t_path, "r", encoding="utf-8") as f:
            token_data = json.load(f)
    except Exception as exc:
        print(f"[ERROR] Failed to parse YouTube token file {t_path}: {exc}", file=sys.stderr)
        return 2

    if not isinstance(token_data, dict):
        print(f"[ERROR] Invalid token format in {t_path}", file=sys.stderr)
        return 2

    # 1. Must have a refresh_token
    if not token_data.get("refresh_token"):
        print("[ERROR] Token has no refresh token", file=sys.stderr)
        return 2

    # 2. Build Credentials object
    try:
        credentials = Credentials.from_authorized_user_info(token_data)
    except Exception as exc:
        print(f"[ERROR] Could not build credentials from token info: {exc}", file=sys.stderr)
        return 2

    # 3. Refresh credentials
    try:
        credentials.refresh(Request())
    except RefreshError as r_err:
        print(
            "YouTube authorization expired or revoked. Set the Google OAuth app to In production, "
            "then run: python main.py auth-youtube --force, and update the YOUTUBE_TOKEN_JSON secret.",
            file=sys.stderr,
        )
        logger.error("Token refresh failed: %s", r_err)
        return 2
    except Exception as exc:
        print(f"[ERROR] Failed to refresh YouTube credentials: {exc}", file=sys.stderr)
        return 2

    # 4. Cheap read-only verification call
    try:
        youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
        req = youtube.channels().list(part="id", mine=True)
        resp = req.execute()
        items = resp.get("items", [])
        channel_id = items[0]["id"] if items else "unknown"
        print(f"[OK] YouTube token is valid. Connected channel ID: {channel_id}")
    except Exception as exc:
        print(f"[ERROR] YouTube channel check failed: {exc}", file=sys.stderr)
        return 2

    # 5. Write refreshed token back to file
    try:
        updated_dict = json.loads(credentials.to_json())
        # Preserve client credentials if they were in the original token file
        for k in ("client_id", "client_secret"):
            if k in token_data and k not in updated_dict:
                updated_dict[k] = token_data[k]

        tmp_path = t_path.with_suffix(".tmp.json")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(updated_dict, f, indent=2)
        os.replace(tmp_path, str(t_path))
    except Exception as exc:
        print(f"[ERROR] Failed to write updated token back to {t_path}: {exc}", file=sys.stderr)
        return 2

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Check YouTube OAuth2 Token Health")
    parser.add_argument(
        "--token-file",
        help="Path to token file (default: config/youtube_token.json)",
        default=None,
    )
    args = parser.parse_args()
    code = check_youtube_token(args.token_file)
    sys.exit(code)


if __name__ == "__main__":
    main()
