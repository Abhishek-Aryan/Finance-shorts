"""
Finance Shorts - Structured Logging Setup
Call setup_logging() once at application startup.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

import config


def setup_logging(level: str = "INFO") -> None:
    """
    Configure root logger with:
    - Rotating file handler (logs/finance_shorts.log, 5 MB × 5 files)
    - Colour-friendly console handler
    Never logs secrets or tokens.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(log_level)

    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(log_level)
    root.addHandler(ch)

    # Rotating file
    log_file = config.LOGS_DIR / "finance_shorts.log"
    fh = logging.handlers.RotatingFileHandler(
        str(log_file),
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    root.addHandler(fh)

    # Suppress noisy third-party loggers
    for noisy in ("urllib3", "httpx", "httpcore", "PIL", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging initialised — level=%s, file=%s", level, log_file
    )
