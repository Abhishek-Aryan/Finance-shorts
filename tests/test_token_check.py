"""
Unit tests for tools/check_youtube_token.py.
All network calls are strictly mocked.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from google.auth.exceptions import RefreshError

from tools import check_youtube_token


def test_token_file_missing(tmp_path):
    """Missing token file exits with code 2."""
    missing = tmp_path / "non_existent.json"
    code = check_youtube_token.check_youtube_token(missing)
    assert code == 2


def test_token_missing_refresh_token(tmp_path, capsys):
    """Token with no refresh_token exits with code 2."""
    t_file = tmp_path / "no_refresh.json"
    t_file.write_text(json.dumps({"token": "xyz"}), encoding="utf-8")
    code = check_youtube_token.check_youtube_token(t_file)
    assert code == 2
    err = capsys.readouterr().err
    assert "Token has no refresh token" in err


def test_token_revoked_or_expired(tmp_path, capsys):
    """Revoked token (RefreshError) exits with code 2."""
    t_file = tmp_path / "revoked.json"
    t_file.write_text(
        json.dumps({
            "token": "old",
            "refresh_token": "refresh_123",
            "client_id": "client_id_val",
            "client_secret": "client_secret_val",
        }),
        encoding="utf-8",
    )

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_info") as mock_creds:
        inst = MagicMock()
        inst.refresh.side_effect = RefreshError("invalid_grant: Token has been expired or revoked.")
        mock_creds.return_value = inst

        code = check_youtube_token.check_youtube_token(t_file)
        assert code == 2
        err = capsys.readouterr().err
        assert "YouTube authorization expired or revoked" in err


def test_token_valid_and_refreshed(tmp_path, capsys):
    """Valid and refreshable token exits with code 0 and updates token file."""
    t_file = tmp_path / "valid.json"
    t_file.write_text(
        json.dumps({
            "token": "old_token",
            "refresh_token": "refresh_val",
            "client_id": "cid",
            "client_secret": "csec",
        }),
        encoding="utf-8",
    )

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_info") as mock_creds, \
         patch("googleapiclient.discovery.build") as mock_build:

        inst = MagicMock()
        inst.refresh.return_value = None
        inst.to_json.return_value = json.dumps({"token": "new_token", "refresh_token": "refresh_val"})
        mock_creds.return_value = inst

        mock_yt = MagicMock()
        mock_channels = MagicMock()
        mock_list = MagicMock()
        mock_list.execute.return_value = {"items": [{"id": "UC_TEST_123"}]}
        mock_channels.list.return_value = mock_list
        mock_yt.channels.return_value = mock_channels
        mock_build.return_value = mock_yt

        code = check_youtube_token.check_youtube_token(t_file)
        assert code == 0
        out = capsys.readouterr().out
        assert "Connected channel ID: UC_TEST_123" in out

        # Assert token file updated
        updated = json.loads(t_file.read_text(encoding="utf-8"))
        assert updated["token"] == "new_token"
        assert updated["client_id"] == "cid"
