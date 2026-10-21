"""
Finance Shorts Pro - State Store
Manages data/schedule_state.json with atomic writes, state lifecycle,
and reconciliation against the Excel publishing schedule.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import openpyxl
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.styles import Font, PatternFill

import config

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_STATE_FILE = config.DATA_DIR / "schedule_state.json"
DEFAULT_EXCEL_FILE = config.SCHEDULE_EXCEL

# Custom exceptions for reconciliation
class StateConflictError(Exception):
    """Raised when Excel says Pending but state already has a published YouTube video ID."""


class RunInProgressError(Exception):
    """Raised when an active run is currently working on the row (< 90 mins old)."""


def _parse_time(t_val: Any) -> dt_time:
    if isinstance(t_val, dt_time):
        return t_val
    if isinstance(t_val, datetime):
        return t_val.time()
    t_str = str(t_val).strip()
    for fmt in ("%I:%M %p", "%H:%M", "%I:%M%p"):
        try:
            return datetime.strptime(t_str, fmt).time()
        except ValueError:
            pass
    raise ValueError(f"Unparseable time: {t_val!r}")


def _parse_date(d_val: Any) -> date:
    if isinstance(d_val, datetime):
        return d_val.date()
    if isinstance(d_val, date):
        return d_val
    d_str = str(d_val).strip()
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(d_str, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unparseable date: {d_val!r}")


def compute_row_key(day: int | str, publish_time: Any) -> str:
    """
    Computes row_key strictly from Day and Publish Time.
    Format: f"D{day:02d}-{HH:MM}" (e.g. "D01-09:00", "D02-15:00").
    Never derived from row position or topic text.
    """
    day_int = int(day)
    t_obj = _parse_time(publish_time)
    return f"D{day_int:02d}-{t_obj.strftime('%H:%M')}"


def _build_initial_state_from_excel(excel_path: Path) -> dict:
    """Builds initial state dictionary from existing Excel schedule."""
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel schedule not found: {excel_path}")

    wb = openpyxl.load_workbook(str(excel_path), data_only=True)
    sheet_name = "Publishing Schedule"
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active

    rows_dict = {}
    for row_idx, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not r or not r[0]:
            continue
        r = (r + (None,) * (10 - len(r)))[:10]
        day, week, date_val, day_name, time_val, topic, category, objective, script, status = r

        if not topic:
            continue

        d_obj = _parse_date(date_val)
        t_obj = _parse_time(time_val)
        scheduled_dt = datetime.combine(d_obj, t_obj, tzinfo=IST)
        rk = compute_row_key(day, t_obj)

        is_done = "done" in str(status).strip().lower()
        row_status = "Done" if is_done else "Pending"

        row_entry: dict[str, Any] = {
            "row_index": row_idx,
            "day": int(day),
            "scheduled_at": scheduled_dt.isoformat(),
            "topic": str(topic).strip(),
            "status": row_status,
            "attempts": 0,
            "job_id": None,
            "claimed_at": None,
            "youtube_video_id": None,
            "youtube_url": None,
            "published_at": None,
            "last_error": None,
            "script_full": str(script).strip() if script else None,
        }
        if is_done:
            row_entry["note"] = "imported from Excel"

        rows_dict[rk] = row_entry

    now_iso = datetime.now(IST).isoformat()
    return {
        "version": 1,
        "updated_at": now_iso,
        "rows": rows_dict,
    }


def load(state_file: Path | None = None, excel_file: Path | None = None) -> dict:
    """Loads state from JSON. If state file does not exist, builds it from Excel."""
    s_path = Path(state_file) if state_file else DEFAULT_STATE_FILE
    e_path = Path(excel_file) if excel_file else Path(DEFAULT_EXCEL_FILE)

    if s_path.exists():
        try:
            with open(s_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "rows" in data:
                    return data
        except Exception as e:
            logger.warning("Failed to load existing state file %s (%s), rebuilding...", s_path, e)

    state = _build_initial_state_from_excel(e_path)
    save(state, s_path)
    return state


def save(state: dict, state_file: Path | None = None) -> None:
    """Atomically writes state to state_file via temporary file in same folder."""
    s_path = Path(state_file) if state_file else DEFAULT_STATE_FILE
    s_path.parent.mkdir(parents=True, exist_ok=True)

    state["updated_at"] = datetime.now(IST).isoformat()
    temp_fd, temp_path = tempfile.mkstemp(
        dir=str(s_path.parent),
        prefix=f"{s_path.stem}_",
        suffix=".tmp"
    )
    try:
        with open(temp_fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, str(s_path))
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def get(row_key: str, state_file: Path | None = None) -> dict | None:
    """Gets a specific row dictionary by row_key."""
    st = load(state_file)
    return st.get("rows", {}).get(row_key)


def upsert(row_key: str, state_file: Path | None = None, **fields) -> dict:
    """Updates or inserts fields for a given row_key, saves, and returns the row."""
    st = load(state_file)
    if "rows" not in st:
        st["rows"] = {}
    if row_key not in st["rows"]:
        st["rows"][row_key] = {"attempts": 0, "status": "Pending"}
    st["rows"][row_key].update(fields)
    save(st, state_file)
    return st["rows"][row_key]


def claim(row_key: str, job_id: str, state_file: Path | None = None, now: datetime | None = None) -> dict:
    """Claims a row for processing by setting status to 'In progress' and claimed_at."""
    claim_time = now or datetime.now(IST)
    return upsert(
        row_key,
        state_file=state_file,
        status="In progress",
        job_id=job_id,
        claimed_at=claim_time.isoformat(),
        last_error=None,
    )


def complete(
    row_key: str,
    video_id: str,
    url: str,
    script_full: str | None = None,
    state_file: Path | None = None,
    now: datetime | None = None,
) -> dict:
    """Marks a row complete with YouTube publishing metadata and full script."""
    comp_time = now or datetime.now(IST)
    updates: dict[str, Any] = {
        "status": "Done",
        "youtube_video_id": video_id,
        "youtube_url": url,
        "published_at": comp_time.isoformat(),
    }
    if script_full is not None:
        updates["script_full"] = script_full
    return upsert(row_key, state_file=state_file, **updates)


def fail(row_key: str, error: str, state_file: Path | None = None) -> dict:
    """Records an error message on the row."""
    st = load(state_file)
    row = st.get("rows", {}).get(row_key, {})
    attempts = row.get("attempts", 0) + 1
    new_status = "Failed" if attempts >= 2 else "Pending"
    return upsert(
        row_key,
        state_file=state_file,
        last_error=str(error),
        attempts=attempts,
        status=new_status,
    )


def all_rows(state_file: Path | None = None) -> dict[str, dict]:
    """Returns all rows from state dictionary."""
    st = load(state_file)
    return st.get("rows", {})


def reconcile(
    state: dict | None = None,
    excel_path: Path | None = None,
    state_file: Path | None = None,
    now: datetime | None = None,
) -> dict:
    """
    Reconciles state against Excel publishing schedule:
    - Excel Done, state Pending/Failed -> accept Excel, set state Done.
    - Excel Pending, state Done with a video id -> CONFLICT (raise StateConflictError).
    - Excel Pending, state 'In progress' older than 90m -> treat as crashed, set Failed, increment attempts.
    - Excel Pending, state 'In progress' newer than 90m -> another run is working (raise RunInProgressError).
    """
    s_path = Path(state_file) if state_file else DEFAULT_STATE_FILE
    e_path = Path(excel_path) if excel_path else Path(DEFAULT_EXCEL_FILE)
    now_dt = now or datetime.now(IST)

    st = state if state is not None else load(s_path, e_path)
    rows_state = st.setdefault("rows", {})

    if not e_path.exists():
        return st

    wb = openpyxl.load_workbook(str(e_path), data_only=True)
    sheet_name = "Publishing Schedule"
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active

    modified = False

    for row_idx, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not r or not r[0]:
            continue
        r = (r + (None,) * (10 - len(r)))[:10]
        day, week, date_val, day_name, time_val, topic, category, objective, script, status_cell = r

        if not topic:
            continue

        rk = compute_row_key(day, time_val)
        excel_status = str(status_cell or "").strip()
        is_excel_done = "done" in excel_status.lower()

        state_entry = rows_state.get(rk)
        if not state_entry:
            continue

        state_status = state_entry.get("status", "Pending")
        video_id = state_entry.get("youtube_video_id")

        if is_excel_done:
            # Excel Done, state Pending/Failed -> accept Excel
            if state_status in ("Pending", "Failed", "In progress"):
                logger.info("Reconciliation: accepting manual Excel 'Done' for %s (%s)", rk, topic)
                state_entry["status"] = "Done"
                state_entry["note"] = "accepted from Excel"
                modified = True
        else:
            # Excel is Pending (or not Done)
            if state_status == "Done" and video_id:
                # CONFLICT!
                msg = (
                    f"CONFLICT on row {rk} (Topic: '{topic}'): "
                    f"Excel 'Posted?' is '{excel_status}', but state is 'Done' with "
                    f"youtube_video_id='{video_id}' (URL: {state_entry.get('youtube_url')}). "
                    f"Refusing to re-upload."
                )
                print(f"\n[ERROR] {msg}\n", file=sys.stderr)
                raise StateConflictError(msg)

            if state_status == "In progress":
                claimed_at_str = state_entry.get("claimed_at")
                is_stale = False
                age_minutes = 999.0

                if claimed_at_str:
                    try:
                        claimed_dt = datetime.fromisoformat(claimed_at_str)
                        if claimed_dt.tzinfo is None:
                            claimed_dt = claimed_dt.replace(tzinfo=IST)
                        age = now_dt - claimed_dt
                        age_minutes = age.total_seconds() / 60.0
                        if age >= timedelta(minutes=90):
                            is_stale = True
                    except Exception:
                        is_stale = True
                else:
                    is_stale = True

                if is_stale:
                    logger.warning(
                        "Reconciliation: stale 'In progress' claim for %s (claimed %s, age ~%.1f min). Marking Failed.",
                        rk, claimed_at_str, age_minutes
                    )
                    state_entry["status"] = "Failed"
                    state_entry["last_error"] = "stale in-progress claim"
                    state_entry["attempts"] = state_entry.get("attempts", 0) + 1
                    modified = True
                else:
                    logger.info("Reconciliation: %s is currently in progress (age ~%.1f min < 90 min)", rk, age_minutes)
                    raise RunInProgressError(f"Row {rk} is currently In progress (~{age_minutes:.1f}m old).")

    if modified:
        save(st, s_path)

    return st
