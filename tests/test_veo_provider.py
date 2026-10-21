"""
Unit tests for Google Veo Video Provider (visuals/veo_provider.py).
Tests:
- Successful generation & usage recording
- 429 transient rate limit retry
- Non-retryable quota exceeded error
- Operation timeout
- Bad ffprobe verification result
- Cost guard / budget cap refusal (per-run and daily limits)
- Verification that no files in visuals/ or content/ import heygen or call HeyGen
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from visuals.veo_provider import VeoProvider
from visuals.video_provider import (
    BudgetCapReached,
    ProviderTimeout,
    QuotaExceeded,
    VideoProviderError,
)


@pytest.fixture
def mock_scenes():
    return [
        {
            "scene_number": 1,
            "scene_type": "hook",
            "duration_sec": 5,
            "voiceover": "Test hook",
            "visual_scene": "Financial charts glowing",
            "video_prompt": "Cinematic charts glowing in dark studio",
        },
        {
            "scene_number": 2,
            "scene_type": "core",
            "duration_sec": 5,
            "voiceover": "Test core",
            "visual_scene": "Stock board with gold lights",
            "video_prompt": "Stock board with gold lights in dark studio",
        },
    ]


def test_veo_provider_success(tmp_path, mock_scenes, monkeypatch):
    """Test full successful Veo generation flow with fake HTTP layer."""
    ledger_file = tmp_path / "usage_ledger.json"
    provider = VeoProvider(
        api_key="test-key",
        ledger_path=ledger_file,
        timeout_seconds=5,
        max_scene_seconds=5,
    )

    # 1. Mock requests.post for predictLongRunning
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {"name": "operations/models/veo-test/operations/op_123"}

    # 2. Mock requests.get for polling and download
    mock_poll_resp = MagicMock()
    mock_poll_resp.status_code = 200
    mock_poll_resp.json.return_value = {
        "done": True,
        "response": {
            "generatedVideos": [
                {"video": {"uri": "https://generativelanguage.googleapis.com/v1beta/files/file_abc"}}
            ]
        },
    }

    mock_download_resp = MagicMock()
    mock_download_resp.status_code = 200
    mock_download_resp.iter_content.return_value = [b"x" * 20000]

    def fake_get(url, *args, **kwargs):
        if "files/file_abc" in url:
            return mock_download_resp
        return mock_poll_resp

    monkeypatch.setattr("requests.post", lambda *a, **kw: mock_post_resp)
    monkeypatch.setattr("requests.get", fake_get)

    # Mock conversion and ffprobe
    monkeypatch.setattr(provider, "_convert_to_vertical", lambda raw, out, dur: out.write_bytes(b"video_bytes"))
    monkeypatch.setattr(provider, "_verify_clip", lambda clip_path, scene_num: None)

    out_dir = tmp_path / "output_scenes"
    paths = provider.generate_all_scenes(mock_scenes, "D01-09:00", out_dir)

    assert len(paths) == 2
    assert all(p.exists() for p in paths)

    # Verify ledger recorded usage
    assert ledger_file.exists()
    ledger_data = json.loads(ledger_file.read_text())
    assert "daily_usage" in ledger_data
    today_records = list(ledger_data["daily_usage"].values())[0]
    assert today_records["total_seconds"] == 10
    assert today_records["total_cost_usd"] > 0


def test_veo_provider_429_retry(tmp_path, mock_scenes, monkeypatch):
    """Test transient 429 rate limit error retries with exponential backoff and succeeds."""
    provider = VeoProvider(api_key="test-key", ledger_path=tmp_path / "ledger.json")

    call_count = 0
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.text = "Rate limit reached. Try again in 2 seconds."

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {"name": "operations/test-op"}

    def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return resp_429
        return resp_200

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda s: None)

    job = provider.submit_scene(mock_scenes[0], 1, tmp_path, topic_id="TEST")
    assert job["operation_name"] == "operations/test-op"
    assert call_count == 2


def test_veo_provider_quota_error(tmp_path, mock_scenes, monkeypatch):
    """Test non-retryable quota error raises QuotaExceeded immediately."""
    provider = VeoProvider(api_key="test-key", ledger_path=tmp_path / "ledger.json")

    resp_quota = MagicMock()
    resp_quota.status_code = 429
    resp_quota.text = "RESOURCE_EXHAUSTED: Quota exceeded for project 123456"

    monkeypatch.setattr("requests.post", lambda *a, **kw: resp_quota)

    with pytest.raises(QuotaExceeded) as exc_info:
        provider.submit_scene(mock_scenes[0], 1, tmp_path, topic_id="TEST")

    assert "quota exceeded" in str(exc_info.value).lower()


def test_veo_provider_timeout(tmp_path, mock_scenes, monkeypatch):
    """Test operation polling times out and raises ProviderTimeout."""
    provider = VeoProvider(
        api_key="test-key",
        ledger_path=tmp_path / "ledger.json",
        timeout_seconds=0.1,  # Short timeout
    )

    mock_poll_resp = MagicMock()
    mock_poll_resp.status_code = 200
    mock_poll_resp.json.return_value = {"done": False}

    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_poll_resp)
    # Advance time quickly
    current_time = 1000.0
    def fake_time():
        nonlocal current_time
        current_time += 1.0
        return current_time

    monkeypatch.setattr("time.time", fake_time)
    monkeypatch.setattr("time.sleep", lambda s: None)

    job = {
        "operation_name": "operations/test-timeout",
        "scene_number": 4,
        "raw_path": tmp_path / "scene_04_raw.mp4",
        "final_path": tmp_path / "scene_04.mp4",
        "duration": 5,
        "topic_id": "D01-09:00",
    }

    with pytest.raises(ProviderTimeout) as exc_info:
        provider.wait_scene(job)

    assert "scene 4" in str(exc_info.value)
    assert "timed out" in str(exc_info.value)


def test_veo_provider_bad_ffprobe(tmp_path, monkeypatch):
    """Test invalid dimensions or negative duration triggers VideoProviderError."""
    provider = VeoProvider(api_key="test-key", ledger_path=tmp_path / "ledger.json")
    dummy_clip = tmp_path / "bad_clip.mp4"
    dummy_clip.write_bytes(b"dummy")

    # Mock ffprobe returning 0 width
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps({"streams": [{"width": 0, "height": 1920, "duration": "5.0"}]})

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: mock_proc)

    with pytest.raises(VideoProviderError) as exc_info:
        provider._verify_clip(dummy_clip, 1)

    assert "bad ffprobe result" in str(exc_info.value).lower()


def test_veo_provider_cost_cap_refusal(tmp_path, mock_scenes, monkeypatch):
    """Test cost guard refuses submission and raises BudgetCapReached when caps are exceeded."""
    ledger_file = tmp_path / "usage_ledger.json"
    provider = VeoProvider(api_key="test-key", ledger_path=ledger_file)

    # 1. Test per-run cap
    provider.max_run_seconds = 5  # mock_scenes is 10s total
    with pytest.raises(BudgetCapReached) as exc_info:
        provider.check_cost_guard(mock_scenes)
    assert "exceeds configured per-run limit" in str(exc_info.value)

    # 2. Test daily cap
    provider.max_run_seconds = 60
    provider.max_daily_seconds = 15

    # Seed ledger with 10s already used today
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    ledger_file.write_text(json.dumps({
        "version": 1,
        "daily_usage": {
            today_str: {"total_seconds": 10, "total_cost_usd": 1.0, "runs": []}
        }
    }))

    # Requesting 10s more: 10 + 10 = 20s > 15s daily cap
    with pytest.raises(BudgetCapReached) as exc_info:
        provider.check_cost_guard(mock_scenes)
    assert "exceeds VEO_MAX_SECONDS_PER_DAY" in str(exc_info.value)


def test_no_heygen_imports_or_calls_in_visuals_or_content():
    """Verify that no active file in visuals/ or content/ imports or calls HeyGen."""
    root = Path(__file__).resolve().parent.parent

    for search_dir in [root / "visuals", root / "content"]:
        for py_file in search_dir.glob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            assert "import heygen" not in text.lower(), f"{py_file} imports heygen"
            assert "from visuals.heygen_generator import" not in text, f"{py_file} imports heygen_generator"
            assert "heygen/heygen-video-1" not in text, f"{py_file} calls heygen-video-1"
