"""
Unit tests for tools/sync_secrets.py (GitHub Secrets Synchronizer).
Tests:
- Token retrieval from environment and ~/.git-credentials
- Sodium public-key encryption
- API interaction with mocked GitHub endpoints
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from tools.sync_secrets import encrypt_secret, get_github_token, sync_github_secrets


def test_encrypt_secret():
    # Valid Base64 32-byte public key
    import nacl.public
    key_pair = nacl.public.PrivateKey.generate()
    pub_key_b64 = key_pair.public_key.encode(nacl.encoding.Base64Encoder).decode("utf-8")
    
    secret = '{"test": "secret_data"}'
    encrypted_b64 = encrypt_secret(pub_key_b64, secret)
    assert isinstance(encrypted_b64, str)
    assert len(encrypted_b64) > 20


def test_get_github_token_from_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_mock_token_123")
    assert get_github_token() == "ghp_mock_token_123"


def test_sync_github_secrets_success(tmp_path, monkeypatch):
    import nacl.public
    key_pair = nacl.public.PrivateKey.generate()
    pub_key_b64 = key_pair.public_key.encode(nacl.encoding.Base64Encoder).decode("utf-8")

    token_file = tmp_path / "youtube_token.json"
    token_file.write_text('{"refresh_token": "mock_refresh"}', encoding="utf-8")

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_mock_token_123")

    mock_resp_pk = MagicMock()
    mock_resp_pk.read.return_value = json.dumps({"key_id": "key_1", "key": pub_key_b64}).encode("utf-8")
    mock_resp_pk.__enter__.return_value = mock_resp_pk

    mock_resp_put = MagicMock()
    mock_resp_put.status = 201
    mock_resp_put.__enter__.return_value = mock_resp_put

    def fake_urlopen(req):
        if "public-key" in req.full_url:
            return mock_resp_pk
        return mock_resp_put

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    ok = sync_github_secrets(token_file=token_file)
    assert ok is True


def test_sync_github_secrets_missing_token_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_mock_token_123")
    missing_file = tmp_path / "non_existent.json"
    
    mock_resp_pk = MagicMock()
    mock_resp_pk.read.return_value = json.dumps({"key_id": "key_1", "key": "abc"}).encode("utf-8")
    monkeypatch.setattr("urllib.request.urlopen", lambda req: mock_resp_pk)

    ok = sync_github_secrets(token_file=missing_file)
    assert ok is False
