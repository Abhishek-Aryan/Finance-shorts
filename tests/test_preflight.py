"""
Unit tests for tools/preflight.py.
"""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from tools import preflight
import config


def test_preflight_test_mode(tmp_path, monkeypatch):
    """In test mode, missing API keys and secrets do not trigger exit 2."""
    missing = preflight.check_env_vars(mode="test")
    assert missing == []

    # File check on valid project schedule
    errors = preflight.check_files()
    assert errors == []

    # Binary check
    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        assert preflight.check_binaries() == []

    # Directory check
    assert preflight.check_writable_dirs() == []


def test_preflight_production_missing_keys(monkeypatch):
    """In production mode, missing secrets lists exact missing variable names."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_CLIENT_SECRETS_JSON", raising=False)
    monkeypatch.delenv("YOUTUBE_TOKEN_JSON", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(config, "SCRIPT_MODEL", "gemini-flash-lite-latest")

    missing = preflight.check_env_vars(mode="production")
    assert "OPENROUTER_API_KEY" in missing
    assert "YOUTUBE_CLIENT_SECRETS_JSON" in missing
    assert "YOUTUBE_TOKEN_JSON" in missing
    assert "GEMINI_API_KEY" in missing


def test_preflight_production_all_present(monkeypatch):
    """When all production vars are set, missing list is empty."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRETS_JSON", '{"fake": true}')
    monkeypatch.setenv("YOUTUBE_TOKEN_JSON", '{"token": "fake"}')
    monkeypatch.setenv("GEMINI_API_KEY", "fake_gemini")
    monkeypatch.setattr(config, "SCRIPT_MODEL", "gemini-flash-lite-latest")

    missing = preflight.check_env_vars(mode="production")
    assert missing == []


def test_preflight_instagram_conditional(monkeypatch):
    """Instagram variables are required only when INSTAGRAM_PUBLISH_ENABLED is true."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRETS_JSON", "fake")
    monkeypatch.setenv("YOUTUBE_TOKEN_JSON", "fake")
    monkeypatch.setattr(config, "SCRIPT_MODEL", "ollama")
    monkeypatch.delenv("INSTAGRAM_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("INSTAGRAM_ACCOUNT_ID", raising=False)

    # Disabled -> no instagram variables required
    monkeypatch.setattr(config, "INSTAGRAM_PUBLISH_ENABLED", False)
    assert "INSTAGRAM_ACCESS_TOKEN" not in preflight.check_env_vars("production")

    # Enabled -> required
    monkeypatch.setattr(config, "INSTAGRAM_PUBLISH_ENABLED", True)
    missing = preflight.check_env_vars("production")
    assert "INSTAGRAM_ACCESS_TOKEN" in missing
    assert "INSTAGRAM_ACCOUNT_ID" in missing


def test_preflight_file_errors(tmp_path):
    """Missing or corrupted schedule files are flagged."""
    non_existent = tmp_path / "missing.xlsx"
    errs = preflight.check_files(excel_path=non_existent, state_path=non_existent)
    assert len(errs) == 2
    assert any("Schedule file missing" in e for e in errs)
    assert any("State file missing" in e for e in errs)


def test_preflight_binary_missing(monkeypatch):
    """Missing ffmpeg or ffprobe triggers error."""
    with patch("shutil.which", return_value=None), \
         patch("subprocess.run", side_effect=FileNotFoundError):
        errs = preflight.check_binaries()
        assert len(errs) == 2
        assert any("ffmpeg" in e for e in errs)
        assert any("ffprobe" in e for e in errs)
