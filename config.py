"""
Finance Shorts - Central Configuration
Loads all settings from environment variables (via .env file).
Never import secrets directly — always use this module.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
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

# ── OpenRouter, Gemini & Veo Models ──────────────────────────
OPENROUTER_API_KEY      = _get("OPENROUTER_API_KEY", "")
GEMINI_API_KEY          = _get("GEMINI_API_KEY", "")
SCRIPT_MODEL            = _get("SCRIPT_MODEL", "gemini-flash-lite-latest")
VIDEO_PROVIDER          = _get("VIDEO_PROVIDER", "veo")
VEO_MODEL               = _get("VEO_MODEL", "veo-3.1-fast-generate-preview")
VEO_MAX_SCENE_SECONDS   = _get_int("VEO_MAX_SCENE_SECONDS", 5)
VEO_TIMEOUT_SECONDS     = _get_int("VEO_TIMEOUT_SECONDS", 300)
VEO_MAX_SECONDS_PER_DAY = _get_int("VEO_MAX_SECONDS_PER_DAY", 60)
VEO_MAX_SECONDS_PER_RUN = _get_int("VEO_MAX_SECONDS_PER_RUN", 60)
USAGE_LEDGER_FILE       = DATA_DIR / "usage_ledger.json"

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
TTS_ENGINE           = _get("TTS_ENGINE", "edge").lower()
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
PUBLISH_TIMES        = [t.strip() for t in _get("PUBLISH_TIMES", "09:00,15:00,20:00").split(",") if t.strip()]
MAX_VIDEOS_PER_DAY   = _get_int("MAX_VIDEOS_PER_DAY", 3)
MIN_QUEUE_BUFFER     = _get_int("MIN_QUEUE_BUFFER", 3)

# ── Publishing Mode ───────────────────────────────────────
PUBLISHING_MODE      = _get("PUBLISHING_MODE", "test")  # "test" | "production"

# ── YouTube ───────────────────────────────────────────────
_secrets_rel = _get("YOUTUBE_CLIENT_SECRETS_FILE", "config/youtube_client_secrets.json")
YOUTUBE_CLIENT_SECRETS_FILE = _ROOT / _secrets_rel if not Path(_secrets_rel).is_absolute() else Path(_secrets_rel)

_token_rel = _get("YOUTUBE_TOKEN_FILE", "config/youtube_token.json")
YOUTUBE_TOKEN_FILE = _ROOT / _token_rel if not Path(_token_rel).is_absolute() else Path(_token_rel)
YOUTUBE_CATEGORY_ID  = _get_int("YOUTUBE_CATEGORY_ID", 27)

_env_privacy = os.environ.get("YOUTUBE_PRIVACY_STATUS", "").strip().lower()
if _env_privacy and _env_privacy not in ("public", "unlisted", "private"):
    raise ValueError(f"Invalid YOUTUBE_PRIVACY_STATUS {_env_privacy!r}, must be 'public', 'unlisted', or 'private'")
YOUTUBE_PRIVACY_STATUS = _env_privacy or "unlisted"
PRIVACY_RAMP_DAYS    = _get_int("PRIVACY_RAMP_DAYS", 3)
MAX_UPLOADS_PER_RUN  = _get_int("MAX_UPLOADS_PER_RUN", 1)


def resolve_youtube_privacy(
    force_privacy: str = "",
    state_file: Path | None = None,
    now: datetime | None = None,
) -> str:
    """
    Determines effective YouTube privacy status according to the safety ramp policy:
    1. force_privacy (from CLI argument / workflow_dispatch input) always wins if set.
    2. Explicit YOUTUBE_PRIVACY_STATUS environment variable wins if provided in os.environ.
    3. Otherwise, for the first PRIVACY_RAMP_DAYS calendar days after the first published date,
       use 'unlisted'; after that, use 'public'.
    Logs which was chosen and why.
    """
    import json
    from zoneinfo import ZoneInfo
    log = logging.getLogger(__name__)

    if force_privacy and force_privacy.strip():
        chosen = force_privacy.strip().lower()
        if chosen not in ("public", "unlisted", "private"):
            raise ValueError(f"Invalid force_privacy {chosen!r}, must be 'public', 'unlisted', or 'private'")
        log.info("YouTube privacy status: '%s' (Forced via force_privacy input)", chosen)
        return chosen

    if "YOUTUBE_PRIVACY_STATUS" in os.environ and os.environ["YOUTUBE_PRIVACY_STATUS"].strip():
        chosen = os.environ["YOUTUBE_PRIVACY_STATUS"].strip().lower()
        if chosen not in ("public", "unlisted", "private"):
            raise ValueError(f"Invalid YOUTUBE_PRIVACY_STATUS {chosen!r}")
        log.info("YouTube privacy status: '%s' (Explicitly set via environment variable)", chosen)
        return chosen

    # Privacy ramp logic: Days 1-3 unlisted, Days 4-14 public
    s_path = Path(state_file or (DATA_DIR / "schedule_state.json"))
    launch_date = None
    if s_path.exists():
        try:
            with open(s_path, "r", encoding="utf-8") as f:
                st = json.load(f)
                for r in st.get("rows", {}).values():
                    if r.get("day") == 1 and r.get("scheduled_at"):
                        s_dt = datetime.fromisoformat(r["scheduled_at"])
                        if launch_date is None or s_dt < launch_date:
                            launch_date = s_dt
                    if r.get("status") == "Done" and r.get("published_at"):
                        p_dt = datetime.fromisoformat(r["published_at"])
                        if launch_date is None or p_dt < launch_date:
                            launch_date = p_dt
        except Exception:
            pass

    now_dt = now or datetime.now(ZoneInfo("Asia/Kolkata"))
    if launch_date:
        days_since_launch = (now_dt.date() - launch_date.date()).days
        if days_since_launch < PRIVACY_RAMP_DAYS:
            log.info(
                "YouTube privacy status: 'unlisted' (Safety ramp active: %d/%d days since launch %s)",
                days_since_launch, PRIVACY_RAMP_DAYS, launch_date.date().isoformat()
            )
            return "unlisted"
        else:
            log.info(
                "YouTube privacy status: 'public' (Safety ramp expired: %d days >= %d days)",
                days_since_launch, PRIVACY_RAMP_DAYS
            )
            return "public"

    log.info("YouTube privacy status: 'unlisted' (Safety ramp: initial launch period)")
    return "unlisted"


# ── Instagram ─────────────────────────────────────────────
INSTAGRAM_PUBLISH_ENABLED = _get_bool("INSTAGRAM_PUBLISH_ENABLED", False)
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
    Return a list of configuration warnings reporting missing names.
    Empty list means everything looks good.
    """
    warnings: list[str] = []

    if PUBLISHING_MODE not in ("test", "production"):
        warnings.append(f"PUBLISHING_MODE must be 'test' or 'production', got: {PUBLISHING_MODE!r}")

    if PUBLISHING_MODE == "production":
        if not YOUTUBE_CLIENT_SECRETS_FILE.exists():
            warnings.append("YOUTUBE_CLIENT_SECRETS_FILE")
        if not YOUTUBE_TOKEN_FILE.exists():
            warnings.append("YOUTUBE_TOKEN_FILE")
        if not OPENROUTER_API_KEY and not GEMINI_API_KEY:
            warnings.append("OPENROUTER_API_KEY_OR_GEMINI_API_KEY")
        if VIDEO_PROVIDER == "veo" and not GEMINI_API_KEY:
            warnings.append("GEMINI_API_KEY")

    if TTS_ENGINE == "piper":
        if not PIPER_EXECUTABLE.exists():
            warnings.append("PIPER_EXECUTABLE")
        if not PIPER_VOICE_MODEL.exists():
            warnings.append("PIPER_VOICE_MODEL")
    else:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            warnings.append("edge_tts")

    return warnings
