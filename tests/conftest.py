"""
Pytest configuration and global fixtures.
Enforces that tests never make real network calls via requests or googleapiclient.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def block_network_calls(monkeypatch):
    """
    Blocks accidental real network calls through requests and googleapiclient.
    Tests must explicitly mock these clients.
    """
    def fail_requests(*args, **kwargs):
        raise RuntimeError("Blocked real network call via requests in test!")

    def fail_googleapiclient(*args, **kwargs):
        raise RuntimeError("Blocked real network call via googleapiclient in test!")

    try:
        import requests
        monkeypatch.setattr(requests.Session, "send", fail_requests)
    except ImportError:
        pass

    try:
        import googleapiclient.http
        monkeypatch.setattr(googleapiclient.http.HttpRequest, "execute", fail_googleapiclient)
    except ImportError:
        pass
