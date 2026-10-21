"""
Finance Shorts - YouTube Publisher
Uploads rendered vertical short videos to YouTube Shorts using the YouTube Data API v3.
Supports:
1. Safe 'test' mode (simulated upload with full metadata persistence and zero real API calls).
2. 'production' mode (OAuth2 authenticated upload to YouTube channel).
3. Idempotency protection to prevent duplicate uploads.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

import config
from storage import database

logger = logging.getLogger(__name__)


def publish_to_youtube(
    topic_id: str,
    privacy_status: str = "unlisted",
    force_test_mode: Optional[bool] = None,
) -> dict[str, Any]:
    """
    Publishes a produced video for topic_id to YouTube Shorts.
    If config.PUBLISHING_MODE == 'test' or force_test_mode is True, runs in simulation mode.
    Returns upload metadata dict.
    """
    # 1. Fetch topic, script, and production record
    topic = database.get_topic(topic_id)
    if not topic:
        raise ValueError(f"Topic {topic_id} not found in database")

    script = database.get_script(topic_id)
    if not script:
        raise ValueError(f"Script for topic {topic_id} not found")

    with database.get_connection() as conn:
        prod_row = conn.execute(
            "SELECT * FROM production WHERE topic_id=?", (topic_id,)
        ).fetchone()

    if not prod_row or not prod_row["video_file"]:
        raise ValueError(f"No rendered video found for topic {topic_id}. Run produce first.")

    video_path = Path(prod_row["video_file"])
    if not video_path.exists():
        raise FileNotFoundError(f"Video file missing on disk: {video_path}")

    # 2. Idempotency check: Already uploaded?
    existing_upload = database.get_upload_by_topic_platform(topic_id, "youtube")
    if existing_upload:
        logger.warning(
            "Topic %s already successfully uploaded to YouTube: %s",
            topic_id, existing_upload.get("published_url"),
        )
        return existing_upload

    # 3. Format Title & Description with #Shorts hashtags
    raw_title = script.get("video_title") or topic.get("topic", "Finance Short")
    if "#Shorts" not in raw_title and "#shorts" not in raw_title:
        title = f"{raw_title[:85]} #Shorts"
    else:
        title = raw_title[:100]

    desc_parts = [
        script.get("video_description", ""),
        "\n\n---\n",
        f"Channel: {config.CHANNEL_NAME} - {config.CHANNEL_TAGLINE}",
        "\nDisclaimer: Educational content only. Not financial advice.",
        "\n\n#Shorts #Finance #PersonalFinance #MoneyTips #Investing #India",
    ]
    description = "".join(desc_parts).strip()

    keywords = script.get("keywords", [])
    if isinstance(keywords, str):
        try:
            keywords = json.loads(keywords)
        except Exception:
            keywords = ["finance", "shorts", "money"]
    keywords.extend(["shorts", "youtube shorts", "finance shorts"])

    upload_id = str(uuid.uuid4())
    database.record_upload_attempt(
        upload_id=upload_id,
        topic_id=topic_id,
        platform="youtube",
        privacy_status=privacy_status,
    )

    is_test_mode = (
        force_test_mode
        if force_test_mode is not None
        else (config.PUBLISHING_MODE.lower() == "test")
    )

    if is_test_mode:
        # ── Test Mode: Safe Simulation ────────────────────────────────────────
        simulated_video_id = f"mock_yt_{topic_id.lower()}_{uuid.uuid4().hex[:6]}"
        published_url = f"https://youtube.com/shorts/{simulated_video_id}"

        # Write metadata audit file
        meta_audit_path = config.OUTPUT_VIDEOS / f"{topic_id}_youtube_upload_meta.json"
        with open(meta_audit_path, "w", encoding="utf-8") as f:
            json.dump({
                "upload_id": upload_id,
                "topic_id": topic_id,
                "title": title,
                "description": description,
                "tags": keywords,
                "privacy_status": privacy_status,
                "simulated_video_id": simulated_video_id,
                "published_url": published_url,
                "mode": "test_simulation",
            }, f, indent=2)

        database.confirm_upload(upload_id, simulated_video_id, published_url)
        database.update_topic_status(topic_id, database.Status.PUBLISHED)

        logger.info(
            "[TEST MODE] Video for %s simulated upload -> %s", topic_id, published_url
        )
        return {
            "upload_id": upload_id,
            "topic_id": topic_id,
            "platform": "youtube",
            "video_id": simulated_video_id,
            "published_url": published_url,
            "title": title,
            "mode": "test",
            "status": "PUBLISHED",
        }

    else:
        # ── Production Mode: Real YouTube Data API v3 Upload ─────────────────
        return _upload_youtube_production(
            upload_id=upload_id,
            topic_id=topic_id,
            video_path=video_path,
            title=title,
            description=description,
            tags=keywords,
            privacy_status=privacy_status,
        )


def _upload_youtube_production(
    upload_id: str,
    topic_id: str,
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    privacy_status: str,
) -> dict[str, Any]:
    """Handles real authenticated OAuth2 YouTube API upload with auto-token refresh."""
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        if not config.YOUTUBE_TOKEN_FILE.exists():
            raise FileNotFoundError(
                f"YouTube OAuth token file missing at {config.YOUTUBE_TOKEN_FILE}.\n"
                "Please run: python setup_youtube_oauth.py to connect your YouTube channel."
            )

        with open(config.YOUTUBE_TOKEN_FILE, "r", encoding="utf-8") as f:
            token_info = json.load(f)

        credentials = Credentials.from_authorized_user_info(token_info)

        # Automatic token refresh if expired
        if credentials.expired and credentials.refresh_token:
            logger.info("YouTube OAuth access token expired. Refreshing token...")
            credentials.refresh(Request())
            with open(config.YOUTUBE_TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(credentials.to_json())
            logger.info("YouTube OAuth access token successfully refreshed.")

        youtube = build("youtube", "v3", credentials=credentials)

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags[:20],
                "categoryId": str(config.YOUTUBE_CATEGORY_ID),
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        # Resumable upload with 1MB chunk size
        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            chunksize=1024 * 1024,
            resumable=True,
        )
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        logger.info("Starting YouTube upload for [%s]: %s (size: %.2f MB)",
                    topic_id, title, video_path.stat().st_size / (1024 * 1024))

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                logger.info("Upload progress for %s: %d%%", topic_id, progress)

        video_id = response.get("id")
        published_url = f"https://youtube.com/shorts/{video_id}"

        database.confirm_upload(upload_id, video_id, published_url)
        database.update_topic_status(topic_id, database.Status.PUBLISHED)

        logger.info("Successfully uploaded %s to YouTube: %s", topic_id, published_url)
        return {
            "upload_id": upload_id,
            "topic_id": topic_id,
            "platform": "youtube",
            "video_id": video_id,
            "published_url": published_url,
            "mode": "production",
            "status": "PUBLISHED",
        }

    except Exception as e:
        logger.error("Failed to upload %s to YouTube: %s", topic_id, e)
        database.fail_upload(upload_id, str(e))
        database.update_topic_status(topic_id, database.Status.FAILED)
        raise


def upload_direct(
    video_path: Path | str,
    title: str,
    description: str,
    tags: Optional[list[str]] = None,
    privacy_status: str | None = None,
) -> dict[str, Any]:
    """Uploads a standalone video file directly to YouTube using OAuth2 credentials."""
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    if config.PUBLISHING_MODE not in ("test", "production"):
        raise ValueError(f"Invalid PUBLISHING_MODE: {config.PUBLISHING_MODE!r}, must be 'test' or 'production'")

    privacy_status = privacy_status or config.YOUTUBE_PRIVACY_STATUS

    if config.PUBLISHING_MODE == "test":
        import time as _time
        test_video_id = f"TEST-{int(_time.time())}"
        test_url = f"https://youtube.com/shorts/{test_video_id}"
        logger.info("[TEST MODE] upload_direct skipped network call. Assigned mock video ID: %s (%s)", test_video_id, test_url)
        return {
            "id": test_video_id,
            "video_id": test_video_id,
            "url": test_url,
            "published_url": test_url,
            "title": title,
            "mode": "test",
            "status": "PUBLISHED",
        }

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not config.YOUTUBE_TOKEN_FILE.exists():
        raise FileNotFoundError(f"YouTube token file missing: {config.YOUTUBE_TOKEN_FILE}")

    with open(config.YOUTUBE_TOKEN_FILE, "r", encoding="utf-8") as f:
        token_info = json.load(f)

    credentials = Credentials.from_authorized_user_info(token_info)
    if credentials.expired and credentials.refresh_token:
        logger.info("Refreshing YouTube OAuth token...")
        credentials.refresh(Request())
        with open(config.YOUTUBE_TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(credentials.to_json())

    youtube = build("youtube", "v3", credentials=credentials)

    if "#Shorts" not in title and "#shorts" not in title:
        title = f"{title[:85]} #Shorts"
    else:
        title = title[:100]

    tags = tags or ["finance", "shorts", "investing", "india"]

    body = {
        "snippet": {
            "title": title,
            "description": description[:4900],
            "tags": tags[:20],
            "categoryId": str(config.YOUTUBE_CATEGORY_ID),
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        chunksize=1024 * 1024,
        resumable=True,
    )
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    logger.info("Direct YouTube upload starting for: %s (%.2f MB)", title, video_path.stat().st_size / 1024 / 1024)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info("Upload progress: %d%%", int(status.progress() * 100))

    video_id = response.get("id", "")
    published_url = f"https://youtube.com/shorts/{video_id}"
    logger.info("Direct YouTube upload complete: %s", published_url)
    return {
        "id": video_id,
        "video_id": video_id,
        "published_url": published_url,
        "title": title,
        "status": "PUBLISHED",
    }


class YouTubePublisher:
    """Convenience wrapper class for direct and topic-based YouTube uploads."""

    def upload(
        self,
        video_path: Path | str,
        title: str,
        description: str,
        tags: Optional[list[str]] = None,
        category_id: str = "27",
        privacy: str = "public",
    ) -> dict[str, Any]:
        return upload_direct(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            privacy_status=privacy,
        )

    def publish_topic(self, topic_id: str, privacy: str = "public") -> dict[str, Any]:
        return publish_to_youtube(topic_id=topic_id, privacy_status=privacy)

