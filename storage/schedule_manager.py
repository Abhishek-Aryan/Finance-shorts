"""
Finance Shorts Pro - Schedule Manager
Creates and manages the 14-day publishing schedule Excel sheet (42 topics).
Reads pending topics sorted by publish time, and marks them Done after publishing.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from datetime import datetime, date, time as dt_time, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

import config
from storage import state_store

logger = logging.getLogger(__name__)

SCHEDULE_FILE = Path(config.SCHEDULE_EXCEL)
CURRICULUM_JSON = Path(__file__).parent.parent / "curriculum_42.json"
IST = ZoneInfo("Asia/Kolkata")

DONE_FILL = PatternFill("solid", fgColor="0D2E16")
IN_PROGRESS_FILL = PatternFill("solid", fgColor="1C2D42")
FAILED_FILL = PatternFill("solid", fgColor="3A1010")
ALT_FILL = PatternFill("solid", fgColor="1A1A2E")
DARK_FILL = PatternFill("solid", fgColor="111122")


class ExcelLockedError(Exception):
    """Raised when data/publishing_schedule.xlsx cannot be saved due to file lock."""


def add_status_validation(ws, min_row: int = 2, max_row: int = 43) -> None:
    """Adds or updates the Done/Pending/In progress/Failed dropdown on column J."""
    for dv in list(ws.data_validations.dataValidation):
        if any("J" in str(sq) for sq in dv.sqref):
            ws.data_validations.dataValidation.remove(dv)

    dv = DataValidation(
        type="list",
        formula1='"Done,Pending,In progress,Failed"',
        allow_blank=True,
    )
    ws.add_data_validation(dv)
    dv.add(f"J{min_row}:J{max_row}")


def format_status_cell(cell, status: str, row_idx: int) -> None:
    """Applies distinct fill and font based on status value."""
    val = str(status).strip()
    val_lower = val.lower()
    if "done" in val_lower:
        cell.value = "Done"
        cell.fill = DONE_FILL
        cell.font = Font(name="Calibri", color="39FF14", bold=True, size=10)
    elif "in progress" in val_lower:
        cell.value = "In progress"
        cell.fill = IN_PROGRESS_FILL
        cell.font = Font(name="Calibri", color="00BFFF", bold=True, size=10)
    elif "failed" in val_lower:
        cell.value = "Failed"
        cell.fill = FAILED_FILL
        cell.font = Font(name="Calibri", color="FF4500", bold=True, size=10)
    else:
        cell.value = "Pending"
        row_fill = ALT_FILL if row_idx % 2 == 0 else DARK_FILL
        cell.fill = row_fill
        cell.font = Font(name="Calibri", color="FFA500", bold=True, size=10)


def _parse_time(t_val: Any, row_num: int | None = None) -> dt_time:
    """Parses various time formats into a time object. No silent fallbacks."""
    if isinstance(t_val, dt_time):
        return t_val
    if isinstance(t_val, datetime):
        return t_val.time()
    t_str = str(t_val).strip()
    for fmt in ("%I:%M %p", "%H:%M", "%I:%M%p", "%I:%M:%S %p", "%H:%M:%S"):
        try:
            return datetime.strptime(t_str, fmt).time()
        except ValueError:
            pass
    prefix = f"Row {row_num}: " if row_num is not None else ""
    raise ValueError(f"{prefix}unparseable time {t_val!r}")


def _parse_date(d_val: Any, row_num: int | None = None) -> date:
    """Parses various date formats into a date object. No silent fallbacks."""
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
    prefix = f"Row {row_num}: " if row_num is not None else ""
    raise ValueError(f"{prefix}unparseable date {d_val!r}")


def _save_workbook_with_retry(
    wb: openpyxl.Workbook,
    target_path: Path,
    max_retries: int = 5,
    retry_delay: float = 3.0,
) -> None:
    """Saves workbook atomically using a temp file in the same directory, retrying on PermissionError."""
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(
        dir=str(target_path.parent),
        prefix=f"{target_path.stem}_",
        suffix=".tmp.xlsx",
    )
    os.close(temp_fd)

    for attempt in range(1, max_retries + 1):
        try:
            wb.save(temp_path)
            os.replace(temp_path, str(target_path))
            return
        except PermissionError as pe:
            logger.warning("Excel file %s is locked (attempt %d/%d): %s", target_path, attempt, max_retries, pe)
            if attempt == max_retries:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
                raise ExcelLockedError(f"Close {target_path} in Excel and rerun") from pe
            time.sleep(retry_delay)
        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise


def load_curriculum() -> list[dict]:
    """Loads the 42-topic curriculum from JSON or embedded fallback."""
    if CURRICULUM_JSON.exists():
        try:
            with open(CURRICULUM_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                if len(data) >= 40:
                    return data
        except Exception as e:
            logger.warning("Could not read curriculum_42.json: %s", e)
    return []


def create_schedule_excel() -> Path:
    """
    Creates the full 14-day (42 topics) publishing schedule Excel file
    matching the exact schema requested by the user.
    """
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    curriculum = load_curriculum()
    if not curriculum:
        raise RuntimeError("No curriculum data found to build schedule!")

    wb = Workbook()
    ws = wb.active
    ws.title = "Publishing Schedule"

    # Styling
    HDR_FILL  = PatternFill("solid", fgColor="0D0D0D")
    WHITE     = "FFFFFF"
    GOLD      = "FFD700"
    THIN      = Side(style="thin", color="333333")
    BORDER    = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

    # Column widths
    col_widths = [8, 8, 15, 14, 14, 45, 24, 60, 65, 14]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Headers
    headers = [
        "Day #", "Week", "Date", "Day of Week", "Publish Time",
        "Topic", "Category", "Key Learning Objective", "Script", "Posted?"
    ]
    ws.row_dimensions[1].height = 32
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = Font(name="Calibri", bold=True, color=GOLD, size=11)
        cell.fill = HDR_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER

    # Data Rows
    for row_idx, item in enumerate(curriculum, 2):
        row_fill = ALT_FILL if row_idx % 2 == 0 else DARK_FILL
        status_val = item.get("status", "Pending")
        is_done = "done" in str(status_val).lower()

        row_data = [
            item["day"],
            item["week"],
            item["date_str"],
            item["day_name"],
            item["time_str"],
            item["topic"],
            item["category"],
            item["objective"],
            item.get("script", ""),
            "Done" if is_done else "Pending",
        ]

        for col, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.border = BORDER
            cell.fill = DONE_FILL if (col == 10 and is_done) else row_fill
            cell.alignment = Alignment(horizontal="center" if col in (1, 2, 3, 4, 5, 10) else "left",
                                       vertical="center", wrap_text=True)

            if col == 10:  # Posted?
                format_status_cell(cell, "Done" if is_done else "Pending", row_idx)
            elif col == 6:  # Topic
                cell.font = Font(name="Calibri", color=WHITE, bold=True, size=11)
            elif col == 7:  # Category
                cell.font = Font(name="Calibri", color="ADD8E6", size=10)
            else:
                cell.font = Font(name="Calibri", color="DCDCDC", size=10)

        ws.row_dimensions[row_idx].height = 42

    add_status_validation(ws, min_row=2, max_row=len(curriculum) + 1)
    ws.freeze_panes = "A2"
    _save_workbook_with_retry(wb, SCHEDULE_FILE)
    logger.info("Schedule Excel created: %s (%d rows)", SCHEDULE_FILE.name, len(curriculum))
    return SCHEDULE_FILE


def get_all_topics_summary() -> list[dict]:
    """Returns summary of all topics from Excel."""
    if not SCHEDULE_FILE.exists():
        create_schedule_excel()

    wb = openpyxl.load_workbook(str(SCHEDULE_FILE), data_only=True)
    ws = wb.active
    results = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        row = (row + (None,) * (10 - len(row)))[:10]
        results.append({
            "day": row[0],
            "week": row[1],
            "date": str(row[2]),
            "day_name": str(row[3]),
            "time": str(row[4]),
            "topic": str(row[5]),
            "category": str(row[6]),
            "objective": str(row[7]),
            "script": str(row[8] or ""),
            "status": str(row[9] or "Pending"),
        })
    return results


def select_due_row(
    now_ist: datetime | None = None,
    excel_path: Path | None = None,
    state_file: Path | None = None,
) -> Optional[dict]:
    """
    Selects the due row for publishing:
    1. Load rows, build scheduled_at (IST-aware datetime) from Date + Publish Time.
    2. Candidates = rows with status Pending, scheduled_at <= now_ist, and attempts < 2.
    3. Return the earliest by scheduled_at. If none are due, return None with reason 'nothing due'.
    4. If chosen row is > 3 hours overdue, log a WARNING with exact lateness but still return it.
    5. Never return a row that is Done, In progress, or Failed.
    """
    now = now_ist or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)

    e_path = Path(excel_path or SCHEDULE_FILE)
    st = state_store.load(state_file=state_file, excel_file=e_path)
    state_store.reconcile(st, excel_path=e_path, state_file=state_file, now=now)

    rows = st.get("rows", {})
    candidates = []
    upcoming = []

    for rk, r in rows.items():
        status = r.get("status", "Pending")
        attempts = r.get("attempts", 0)

        # Never return a row that is Done, In progress, or Failed
        if status in ("Done", "In progress", "Failed"):
            continue

        if attempts >= 2:
            continue

        sched_str = r.get("scheduled_at")
        if not sched_str:
            continue

        sched_dt = datetime.fromisoformat(sched_str)
        if sched_dt.tzinfo is None:
            sched_dt = sched_dt.replace(tzinfo=IST)

        row_item = dict(r)
        row_item["_sched_dt"] = sched_dt
        row_item["row_key"] = rk

        if sched_dt <= now:
            candidates.append(row_item)
        else:
            upcoming.append(row_item)

    if not candidates:
        upcoming.sort(key=lambda x: x["_sched_dt"])
        next_slot = upcoming[0]["scheduled_at"] if upcoming else None
        select_due_row.reason = "nothing due"
        select_due_row.next_scheduled_at = next_slot
        logger.info("Nothing due. Next scheduled slot is at %s", next_slot)
        return None

    candidates.sort(key=lambda x: x["_sched_dt"])
    chosen = candidates[0]

    lateness = now - chosen["_sched_dt"]
    if lateness > timedelta(hours=3):
        hours_late = lateness.total_seconds() / 3600.0
        logger.warning(
            "Selected row %s ('%s') is %.1f hours overdue (scheduled %s, now %s)",
            chosen["row_key"], chosen["topic"], hours_late, chosen["scheduled_at"], now.isoformat()
        )

    result = dict(chosen)
    result.pop("_sched_dt", None)
    return result


def get_next_pending_topic() -> Optional[dict]:
    """Backwards-compatible alias for select_due_row."""
    return select_due_row()


def mark_row_done(
    row_key: str,
    expected_topic: str,
    script_text: str = "",
    excel_path: Path | None = None,
    state_file: Path | None = None,
    video_id: str | None = None,
    video_url: str | None = None,
) -> bool:
    """
    Locates the row by row_index and verifies Topic cell equals expected_topic (case-insensitive, exact).
    Updates Excel status to 'Done' and script (first 450 chars).
    Updates state with full script and video details.
    Catches PermissionError with 5 retries (3s wait) before raising ExcelLockedError.
    """
    e_path = Path(excel_path or SCHEDULE_FILE)
    if not e_path.exists():
        create_schedule_excel()

    st = state_store.load(state_file=state_file, excel_file=e_path)
    row_entry = st.get("rows", {}).get(row_key)
    if not row_entry:
        raise KeyError(f"Row key {row_key} not found in state store")

    row_index = row_entry.get("row_index")
    if not row_index:
        raise ValueError(f"No row_index found for row {row_key} in state store")

    wb = openpyxl.load_workbook(str(e_path))
    sheet_name = "Publishing Schedule"
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active

    topic_cell = ws.cell(row=row_index, column=6)  # Col F: Topic
    actual_topic = str(topic_cell.value or "").strip()

    if actual_topic.lower() != expected_topic.strip().lower():
        raise ValueError(
            f"Topic mismatch at row {row_index} for key {row_key}: "
            f"expected {expected_topic!r}, found {actual_topic!r}"
        )

    status_cell = ws.cell(row=row_index, column=10)  # Col J: Posted?
    format_status_cell(status_cell, "Done", row_index)

    script_cell = ws.cell(row=row_index, column=9)   # Col I: Script
    if script_text:
        script_cell.value = script_text[:450]

    add_status_validation(ws)
    _save_workbook_with_retry(wb, e_path)

    # Store full script and video details in state
    state_store.complete(
        row_key=row_key,
        video_id=video_id or row_entry.get("youtube_video_id") or "",
        url=video_url or row_entry.get("youtube_url") or "",
        script_full=script_text or row_entry.get("script_full"),
        state_file=state_file,
    )
    logger.info("Marked row %s ('%s') Done in Excel and state.", row_key, expected_topic)
    return True


def mark_topic_done(topic: str, script_text: str = "") -> bool:
    """Backwards-compatible wrapper matching by exact topic name."""
    st = state_store.load()
    target = topic.strip().lower()
    for rk, r in st.get("rows", {}).items():
        if r.get("topic", "").strip().lower() == target:
            return mark_row_done(row_key=rk, expected_topic=topic, script_text=script_text)
    raise KeyError(f"Topic {topic!r} not found in schedule")
