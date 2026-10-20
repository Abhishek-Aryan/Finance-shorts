"""
Finance Shorts - Central Configuration
Loads all settings from environment variables (via .env file).
Never import secrets directly — always use this module.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_ROOT = Path(__file__).parent
load_dotenv(_ROOT / ".env", override=False)


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _get_int(key: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def _get_float(key: str, default: float = 0.0) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def _get_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, str(default)).lower()
    return val in ("1", "true", "yes", "on")


# ── Project Paths ──────────────────────────────────────────
ROOT_DIR       = _ROOT
DATA_DIR       = _ROOT / _get("DATA_DIR", "data")
OUTPUT_DIR     = _ROOT / _get("OUTPUT_DIR", "output")
LOGS_DIR       = _ROOT / _get("LOGS_DIR", "logs")
ASSETS_DIR     = _ROOT / _get("ASSETS_DIR", "assets")
CONFIG_DIR     = _ROOT / "config"

EXCEL_FILE     = _ROOT / _get("EXCEL_FILE", "data/finance_content_queue.xlsx")
SCHEDULE_EXCEL = _ROOT / _get("SCHEDULE_EXCEL", "data/publishing_schedule.xlsx")
SQLITE_DB      = _ROOT / _get("SQLITE_DB", "data/finance_shorts.db")

# ── OpenRouter, Gemini & HeyGen Models ────────────────────────
OPENROUTER_API_KEY = _get("OPENROUTER_API_KEY", "")
GEMINI_API_KEY     = _get("GEMINI_API_KEY", "")
SCRIPT_MODEL       = _get("SCRIPT_MODEL", "gemini-flash-lite-latest")
VIDEO_MODEL        = _get("VIDEO_MODEL", "heygen/heygen-video-1")

OUTPUT_VIDEOS  = OUTPUT_DIR / "videos"
OUTPUT_AUDIO   = OUTPUT_DIR / "audio"
OUTPUT_VISUALS = OUTPUT_DIR / "visuals"

# Ensure critical dirs exist at import time
for _d in (DATA_DIR, OUTPUT_VIDEOS, OUTPUT_AUDIO, OUTPUT_VISUALS, LOGS_DIR, CONFIG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Ollama / LLM ──────────────────────────────────────────
OLLAMA_HOST        = _get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL       = _get("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TEMPERATURE = _get_float("OLLAMA_TEMPERATURE", 0.7)
OLLAMA_MAX_TOKENS  = _get_int("OLLAMA_MAX_TOKENS", 2048)
OLLAMA_TIMEOUT     = _get_int("OLLAMA_TIMEOUT", 120)
OLLAMA_RETRY_COUNT = _get_int("OLLAMA_RETRY_COUNT", 3)

# ── TTS / Voice & Audio Mix ───────────────────────────────
DEFAULT_VOICE        = _get("DEFAULT_VOICE", "en-US-AndrewMultilingualNeural")
PIPER_EXECUTABLE     = _ROOT / _get("PIPER_EXECUTABLE", "piper/piper.exe")
PIPER_VOICE_MODEL    = _ROOT / _get("PIPER_VOICE_MODEL", "assets/voices/en_US-lessac-medium.onnx")
PIPER_SPEAKING_RATE  = _get_float("PIPER_SPEAKING_RATE", 1.0)
BGM_VOLUME           = _get_float("BGM_VOLUME", 0.18)
VOICE_VOLUME         = _get_float("VOICE_VOLUME", 1.25)

# ── Video ─────────────────────────────────────────────────
VIDEO_WIDTH          = _get_int("VIDEO_WIDTH", 1080)
VIDEO_HEIGHT         = _get_int("VIDEO_HEIGHT", 1920)
VIDEO_FPS            = _get_int("VIDEO_FPS", 30)
VIDEO_BITRATE        = _get("VIDEO_BITRATE", "4000k")
AUDIO_BITRATE        = _get("AUDIO_BITRATE", "192k")
TARGET_DURATION_MIN  = _get_int("TARGET_DURATION_MIN", 30)
TARGET_DURATION_MAX  = _get_int("TARGET_DURATION_MAX", 60)

# ── Publishing Schedule ───────────────────────────────────
TIMEZONE             = _get("TIMEZONE", "Asia/Kolkata")
PUBLISH_TIMES        = [t.strip() for t in _get("PUBLISH_TIMES", "08:00,19:00").split(",")]
MAX_VIDEOS_PER_DAY   = _get_int("MAX_VIDEOS_PER_DAY", 2)
MIN_QUEUE_BUFFER     = _get_int("MIN_QUEUE_BUFFER", 3)

# ── Publishing Mode ───────────────────────────────────────
PUBLISHING_MODE      = _get("PUBLISHING_MODE", "test")  # "test" | "production"

# ── YouTube ───────────────────────────────────────────────
_secrets_rel = _get("YOUTUBE_CLIENT_SECRETS_FILE", "config/youtube_client_secrets.json")
YOUTUBE_CLIENT_SECRETS_FILE = _ROOT / _secrets_rel if not Path(_secrets_rel).is_absolute() else Path(_secrets_rel)

_token_rel = _get("YOUTUBE_TOKEN_FILE", "config/youtube_token.json")
YOUTUBE_TOKEN_FILE = _ROOT / _token_rel if not Path(_token_rel).is_absolute() else Path(_token_rel)
YOUTUBE_CATEGORY_ID  = _get_int("YOUTUBE_CATEGORY_ID", 27)

# ── Instagram ─────────────────────────────────────────────
INSTAGRAM_ACCESS_TOKEN = _get("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_ACCOUNT_ID   = _get("INSTAGRAM_ACCOUNT_ID", "")
INSTAGRAM_APP_ID       = _get("INSTAGRAM_APP_ID", "")
INSTAGRAM_APP_SECRET   = _get("INSTAGRAM_APP_SECRET", "")

# ── Channel Branding ──────────────────────────────────────
CHANNEL_NAME     = _get("CHANNEL_NAME", "FinanceSimple")
CHANNEL_TAGLINE  = _get("CHANNEL_TAGLINE", "Money made simple")

# ── Content ───────────────────────────────────────────────
DEFAULT_AUDIENCE  = _get("DEFAULT_AUDIENCE", "beginners")
SCRIPT_MIN_WORDS  = _get_int("SCRIPT_MIN_WORDS", 75)
SCRIPT_MAX_WORDS  = _get_int("SCRIPT_MAX_WORDS", 130)

# ── Notifications ─────────────────────────────────────────
NOTIFY_EMAIL_ENABLED   = _get_bool("NOTIFY_EMAIL_ENABLED", False)
NOTIFY_SMTP_HOST       = _get("NOTIFY_SMTP_HOST", "smtp.gmail.com")
NOTIFY_SMTP_PORT       = _get_int("NOTIFY_SMTP_PORT", 587)
NOTIFY_EMAIL_FROM      = _get("NOTIFY_EMAIL_FROM", "")
NOTIFY_EMAIL_TO        = _get("NOTIFY_EMAIL_TO", "")
NOTIFY_EMAIL_PASSWORD  = _get("NOTIFY_EMAIL_PASSWORD", "")


def validate() -> list[str]:
    """
    Return a list of configuration warnings.
    Empty list means everything looks good.
    """
    warnings: list[str] = []

    if PUBLISHING_MODE not in ("test", "production"):
        warnings.append(f"PUBLISHING_MODE must be 'test' or 'production', got: {PUBLISHING_MODE!r}")

    if PUBLISHING_MODE == "production":
        if not YOUTUBE_CLIENT_SECRETS_FILE.exists():
            warnings.append(f"YouTube client secrets not found: {YOUTUBE_CLIENT_SECRETS_FILE}")
        if not INSTAGRAM_ACCESS_TOKEN:
            warnings.append("INSTAGRAM_ACCESS_TOKEN is empty — Instagram publishing will fail")

    if not PIPER_EXECUTABLE.exists():
        warnings.append(f"Piper TTS not found at: {PIPER_EXECUTABLE} — TTS will fail")

    if not PIPER_VOICE_MODEL.exists():
        warnings.append(f"Piper voice model not found at: {PIPER_VOICE_MODEL} — TTS will fail")

    return warnings
