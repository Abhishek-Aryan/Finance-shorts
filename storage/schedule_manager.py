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
from datetime import datetime, date, time as dt_time
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

SCHEDULE_FILE = Path(__file__).parent.parent / "data" / "publishing_schedule.xlsx"
CURRICULUM_JSON = Path(__file__).parent.parent / "curriculum_42.json"


def _parse_time(t_str: str) -> dt_time:
    """Parses various time formats into a time object."""
    t_str = str(t_str).strip()
    for fmt in ("%I:%M %p", "%H:%M", "%I:%M%p"):
        try:
            return datetime.strptime(t_str, fmt).time()
        except ValueError:
            pass
    return dt_time(9, 0)


def _parse_date(d_str: str) -> Optional[date]:
    """Parses various date formats into a date object."""
    d_str = str(d_str).strip()
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(d_str, fmt).date()
        except ValueError:
            pass
    return None


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
    ALT_FILL  = PatternFill("solid", fgColor="1A1A2E")
    DARK_FILL = PatternFill("solid", fgColor="111122")
    DONE_FILL = PatternFill("solid", fgColor="0D2E16")
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
                cell.font = Font(name="Calibri", color="39FF14" if is_done else "FFA500", bold=True, size=10)
            elif col == 6:  # Topic
                cell.font = Font(name="Calibri", color=WHITE, bold=True, size=11)
            elif col == 7:  # Category
                cell.font = Font(name="Calibri", color="ADD8E6", size=10)
            else:
                cell.font = Font(name="Calibri", color="DCDCDC", size=10)

        ws.row_dimensions[row_idx].height = 42

    ws.freeze_panes = "A2"
    wb.save(str(SCHEDULE_FILE))
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


def get_next_pending_topic() -> Optional[dict]:
    """Returns the very next unposted topic across the entire curriculum."""
    if not SCHEDULE_FILE.exists():
        create_schedule_excel()

    wb = openpyxl.load_workbook(str(SCHEDULE_FILE), data_only=True)
    ws = wb.active
    candidates = []

    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        row = (row + (None,) * (10 - len(row)))[:10]
        day, week, date_str, day_name, time_str, topic, category, objective, script, status = row

        if not topic:
            continue
        if status and "done" in str(status).strip().lower():
            continue

        row_date = _parse_date(str(date_str)) or date.today()
        t_obj = _parse_time(str(time_str))
        dt_key = datetime.combine(row_date, t_obj)

        candidates.append({
            "day": day,
            "week": week,
            "date": row_date,
            "date_str": date_str,
            "day_name": day_name,
            "time_str": str(time_str).strip(),
            "time_obj": t_obj,
            "topic": str(topic).strip(),
            "category": str(category or "").strip(),
            "objective": str(objective or "").strip(),
            "script": script,
            "status": status,
            "_dt_key": dt_key,
        })

    if not candidates:
        return None

    candidates.sort(key=lambda x: x["_dt_key"])
    return candidates[0]


def mark_topic_done(topic: str, script_text: str = "") -> bool:
    """
    Updates the 'Posted?' column to 'Done' for the matching topic.
    Also records the generated script in the 'Script' column.
    """
    if not SCHEDULE_FILE.exists():
        create_schedule_excel()

    try:
        wb = openpyxl.load_workbook(str(SCHEDULE_FILE))
        ws = wb.active
        DONE_FILL = PatternFill("solid", fgColor="0D2E16")

        found = False
        target = topic.strip().lower()

        for row in ws.iter_rows(min_row=2):
            topic_cell = row[5]   # Col F: Topic
            script_cell = row[8]  # Col I: Script
            status_cell = row[9]  # Col J: Posted?

            cell_val = str(topic_cell.value or "").strip().lower()
            if cell_val == target or target in cell_val or cell_val in target:
                status_cell.value = "Done"
                status_cell.font = Font(name="Calibri", color="39FF14", bold=True, size=10)
                status_cell.fill = DONE_FILL
                if script_text:
                    script_cell.value = script_text[:800]
                found = True
                break

        if not found:
            logger.warning("Topic '%s' not found to mark done.", topic)
            return False

        tmp = SCHEDULE_FILE.with_suffix(".tmp.xlsx")
        wb.save(str(tmp))
        shutil.move(str(tmp), str(SCHEDULE_FILE))
        logger.info("Excel updated: Topic '%s' marked Done.", topic)
        return True

    except Exception as e:
        logger.error("Failed to update Excel for '%s': %s", topic, e)
        return False
