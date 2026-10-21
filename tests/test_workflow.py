"""
Unit tests for .github/workflows/publish_shorts.yml.
Validates syntax, security rules, cron schedules, concurrency, and permissions.
"""

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
import yaml

WORKFLOW_PATH = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "publish_shorts.yml"
IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(scope="module")
def workflow_data():
    assert WORKFLOW_PATH.exists(), f"Workflow file {WORKFLOW_PATH} does not exist"
    with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_workflow_cron_schedules(workflow_data):
    """
    Assert exactly 3 cron entries, whose UTC times are 03:30, 09:30, 14:30
    and convert to 09:00, 15:00, 20:00 in Asia/Kolkata.
    """
    triggers = workflow_data.get("on") if "on" in workflow_data else workflow_data.get(True, {})
    schedule = triggers.get("schedule", [])
    assert len(schedule) == 3, f"Expected 3 cron triggers, got {len(schedule)}"

    crons = [item["cron"] for item in schedule]
    expected_crons = ["30 3 * * *", "30 9 * * *", "30 14 * * *"]
    assert crons == expected_crons

    # Verify UTC to IST conversion
    expected_ist_hours = [9, 15, 20]
    for cron_expr, exp_h in zip(crons, expected_ist_hours):
        parts = cron_expr.split()
        minute_utc, hour_utc = int(parts[0]), int(parts[1])
        utc_dt = datetime(2026, 10, 21, hour_utc, minute_utc, tzinfo=timezone.utc)
        ist_dt = utc_dt.astimezone(IST)
        assert ist_dt.hour == exp_h, f"Cron {cron_expr} did not convert to hour {exp_h} IST (got {ist_dt.hour})"
        assert ist_dt.minute == 0, f"Cron {cron_expr} did not convert to minute 0 IST (got {ist_dt.minute})"


def test_workflow_concurrency(workflow_data):
    """Verify concurrency group is set and cancel-in-progress is false."""
    concurrency = workflow_data.get("concurrency")
    assert isinstance(concurrency, dict)
    assert concurrency.get("group") == "finance-shorts-publish"
    assert concurrency.get("cancel-in-progress") is False


def test_workflow_permissions(workflow_data):
    """Verify permissions explicitly has ONLY contents: write and issues: write."""
    perms = workflow_data.get("permissions")
    assert isinstance(perms, dict)
    assert perms == {"contents": "write", "issues": "write"}


def test_workflow_timeout_minutes(workflow_data):
    """Verify timeout-minutes is set on publish job."""
    jobs = workflow_data.get("jobs", {})
    assert "publish" in jobs
    publish_job = jobs["publish"]
    assert publish_job.get("timeout-minutes") == 90


def test_no_secrets_in_step_bodies(workflow_data):
    """Verify no step run body contains '${{ secrets.' (prevent injection and leaks)."""
    raw_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    steps = workflow_data["jobs"]["publish"].get("steps", [])

    for idx, step in enumerate(steps, 1):
        name = step.get("name", f"Step #{idx}")
        run_body = step.get("run", "")
        assert "${{ secrets." not in run_body, (
            f"Step '{name}' directly interpolates secrets in run body! "
            f"Pass secrets via env: instead."
        )


def test_every_step_has_name(workflow_data):
    """Every step in the workflow must have a descriptive name."""
    steps = workflow_data["jobs"]["publish"].get("steps", [])
    for idx, step in enumerate(steps, 1):
        assert "name" in step and step["name"].strip(), f"Step #{idx} is missing a name"
