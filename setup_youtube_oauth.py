"""
Finance Shorts - YouTube OAuth2 Setup & Verification
Authenticates your YouTube Channel and stores the OAuth2 refresh token
for fully automated, hands-off video uploads.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Ensure project root is in sys.path
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
from logger_setup import setup_logging

logger = setup_logging()

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def authenticate_youtube(force_reauth: bool = False) -> bool:
    """
    Runs the OAuth2 authentication flow for YouTube Data API.
    Saves the refreshed credentials to config.YOUTUBE_TOKEN_FILE.
    Returns True if successfully authenticated.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    secrets_file = config.YOUTUBE_CLIENT_SECRETS_FILE
    token_file = config.YOUTUBE_TOKEN_FILE

    if not secrets_file.exists():
        print(f"\n[ERROR] YouTube Client Secrets file not found at:\n  {secrets_file}")
        print("Please ensure your client_secrets.json is placed in the config directory.\n")
        return False

    creds: Credentials | None = None

    # Check if existing token can be used or refreshed
    if token_file.exists() and not force_reauth:
        try:
            with open(token_file, "r", encoding="utf-8") as f:
                token_data = json.load(f)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            if creds and creds.expired and creds.refresh_token:
                print("Refreshing existing YouTube OAuth token...")
                creds.refresh(Request())
                with open(token_file, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
                print("[OK] Existing token refreshed successfully.")
        except Exception as e:
            logger.warning("Existing token invalid or expired: %s", e)
            creds = None

    # Run browser authentication flow if credentials not valid
    if not creds or not creds.valid:
        print("\n" + "=" * 60)
        print(" YOUTUBE CHANNEL OAUTH2 AUTHENTICATION")
        print("=" * 60)
        print("Opening your default browser to authorize your YouTube channel...")
        print("Select the Google Account that owns your YouTube channel.")
        print("-" * 60)

        flow = InstalledAppFlow.from_client_secrets_file(
            str(secrets_file),
            scopes=SCOPES,
        )

        try:
            creds = flow.run_local_server(
                port=0,
                prompt="consent",
                access_type="offline",
            )
        except Exception as e:
            print(f"\n[ERROR] Browser authentication failed: {e}")
            logger.error("OAuth flow failed: %s", e)
            return False

        # Save credentials to token file
        token_file.parent.mkdir(parents=True, exist_ok=True)
        with open(token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

        print(f"\n[OK] YouTube OAuth credentials saved to:\n  {token_file}")

    # Verify channel access
    try:
        youtube = build("youtube", "v3", credentials=creds)
        res = youtube.channels().list(mine=True, part="snippet,statistics").execute()
        items = res.get("items", [])
        if items:
            channel = items[0]
            snippet = channel.get("snippet", {})
            stats = channel.get("statistics", {})
            title = snippet.get("title", "Unknown")
            subscribers = stats.get("subscriberCount", "Hidden")
            video_count = stats.get("videoCount", "0")

            print("\n" + "=" * 60)
            print(" SUCCESS! CONNECTED TO YOUTUBE CHANNEL:")
            print(f" Channel Title  : {title}")
            print(f" Subscribers    : {subscribers}")
            print(f" Total Videos   : {video_count}")
            print("=" * 60 + "\n")
            return True
        else:
            print("[WARN] Authenticated, but no YouTube channel found for this Google account.")
            return True

    except Exception as e:
        print(f"[ERROR] Could not verify channel: {e}")
        logger.error("Channel verification failed: %s", e)
        return False


if __name__ == "__main__":
    force = "--force" in sys.argv
    success = authenticate_youtube(force_reauth=force)
    if success:
        sys.exit(0)
    else:
        sys.exit(1)
