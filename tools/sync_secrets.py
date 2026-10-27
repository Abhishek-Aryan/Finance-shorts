"""
Finance Shorts Pro - GitHub Secrets Synchronizer.
Encrypts and uploads refreshed credentials (such as YOUTUBE_TOKEN_JSON)
directly to GitHub Actions repository secrets using LibSodium (PyNaCl).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import urllib.request
import urllib.error
from base64 import b64encode
from pathlib import Path
from nacl import encoding, public

logger = logging.getLogger(__name__)

REPO_OWNER = "Abhishek-Aryan"
REPO_NAME = "Finance-shorts"


def encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    """Encrypts secret with the repository's public key using LibSodium SealedBox."""
    pub_key = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(pub_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return b64encode(encrypted).decode("utf-8")


def get_github_token() -> str | None:
    """Retrieves GitHub token from environment or ~/.git-credentials."""
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        return token

    cred_file = Path.home() / ".git-credentials"
    if cred_file.exists():
        try:
            content = cred_file.read_text(encoding="utf-8")
            m = re.search(r"https://([^:]+):([^@]+)@github\.com", content)
            if m:
                return m.group(2)
        except Exception as e:
            logger.warning("Could not read .git-credentials: %s", e)

    return None


def sync_github_secrets(token_file: Path | str | None = None) -> bool:
    """
    Encrypts and syncs YOUTUBE_TOKEN_JSON (and client secrets if present) to GitHub repo secrets.
    Returns True on success, False otherwise.
    """
    token = get_github_token()
    if not token:
        print("[ERROR] GitHub token not found in env or .git-credentials", file=sys.stderr)
        return False

    headers = {
        "User-Agent": "Finance-Shorts-Sync/1.0",
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }

    # 1. Fetch public key
    pk_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/secrets/public-key"
    req = urllib.request.Request(pk_url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            pk_data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"[ERROR] Failed to fetch repository public key: {exc}", file=sys.stderr)
        return False

    key_id = pk_data["key_id"]
    public_key = pk_data["key"]

    # 2. Gather secrets to sync
    t_path = Path(token_file) if token_file else Path("config/youtube_token.json")
    if not t_path.exists():
        print(f"[ERROR] Token file does not exist: {t_path}", file=sys.stderr)
        return False

    token_content = t_path.read_text(encoding="utf-8").strip()
    secrets_to_upload = {
        "YOUTUBE_TOKEN_JSON": token_content,
    }

    client_secrets_file = Path("config/youtube_client_secrets.json")
    if client_secrets_file.exists():
        secrets_to_upload["YOUTUBE_CLIENT_SECRETS_JSON"] = client_secrets_file.read_text(encoding="utf-8").strip()

    # 3. Encrypt and upload each secret
    all_ok = True
    for secret_name, secret_val in secrets_to_upload.items():
        try:
            enc_val = encrypt_secret(public_key, secret_val)
            payload = json.dumps({
                "encrypted_value": enc_val,
                "key_id": key_id
            }).encode("utf-8")

            sec_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/secrets/{secret_name}"
            put_req = urllib.request.Request(sec_url, data=payload, headers=headers, method="PUT")
            with urllib.request.urlopen(put_req) as resp:
                print(f"[OK] Synced GitHub Secret '{secret_name}' (HTTP {resp.status})")
        except Exception as exc:
            print(f"[ERROR] Failed to sync secret '{secret_name}': {exc}", file=sys.stderr)
            all_ok = False

    return all_ok


if __name__ == "__main__":
    t_file = sys.argv[1] if len(sys.argv) > 1 else None
    success = sync_github_secrets(token_file=t_file)
    sys.exit(0 if success else 1)
