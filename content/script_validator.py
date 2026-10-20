"""
Finance Shorts - Script Validator
Validates generated scripts for:
1. JSON schema compliance (via script_generator)
2. Word count bounds
3. Estimated duration (30-60 seconds)
4. Financial calculation accuracy
5. Presence of unverified claims requiring review
6. Prohibited content (guaranteed returns, specific security recommendations)
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

import config
from content.script_generator import estimate_duration_seconds

logger = logging.getLogger(__name__)

# ── Prohibited patterns ───────────────────────────────────────────────────────

_PROHIBITED_PATTERNS = [
    (r"\bguarantee[ds]?\b.{0,30}\breturns?\b", "Claims guaranteed returns"),
    (r"\byou (will|shall) (definitely|certainly) (earn|make|get)",
                                              "Promises specific financial outcome"),
    (r"\bbuy (this|these) stocks?\b",         "Recommends specific security purchase"),
    (r"\b(100%|hundred percent) safe\b",      "Claims 100% safety for investment"),
    (r"\brisk[- ]free\b",                     "Claims risk-free investment"),
    (r"\bget rich quick\b",                   "Get-rich-quick language"),
]


class ValidationResult:
    def __init__(self) -> None:
        self.passed = True
        self.errors: list[str]   = []
        self.warnings: list[str] = []

    def fail(self, msg: str) -> None:
        self.passed = False
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def __bool__(self) -> bool:
        return self.passed


def validate_script(script: dict[str, Any]) -> ValidationResult:
    """
    Run all validation checks on a generated script dict.
    Returns a ValidationResult — check .passed, .errors, .warnings.
    """
    result = ValidationResult()
    full_text = script.get("full_script", "")
    word_count = len(full_text.split())

    # 1. Word count bounds
    if word_count < config.SCRIPT_MIN_WORDS:
        result.fail(
            f"Script too short: {word_count} words (min {config.SCRIPT_MIN_WORDS})"
        )
    elif word_count > config.SCRIPT_MAX_WORDS + 20:  # allow small overrun
        result.warn(
            f"Script may be too long: {word_count} words (target {config.SCRIPT_MAX_WORDS})"
        )

    # 2. Estimated duration
    duration = estimate_duration_seconds(word_count)
    if duration < config.TARGET_DURATION_MIN:
        result.fail(
            f"Estimated duration too short: {duration:.1f}s (min {config.TARGET_DURATION_MIN}s)"
        )
    elif duration > config.TARGET_DURATION_MAX + 10:
        result.warn(
            f"Estimated duration may be too long: {duration:.1f}s (target max {config.TARGET_DURATION_MAX}s)"
        )

    # 3. Required fields
    for field in ("hook", "explanation", "example", "takeaway", "closing",
                  "video_title", "video_description"):
        if not script.get(field, "").strip():
            result.fail(f"Missing required field: {field}")

    # 4. Video title length
    title = script.get("video_title", "")
    if len(title) > 100:
        result.warn(f"Video title is long ({len(title)} chars) — consider shortening")

    # 5. Scene plan
    scenes = script.get("scene_plan", [])
    if len(scenes) < 3:
        result.fail(f"Scene plan too short: {len(scenes)} scenes (min 3)")
    else:
        total_scene_duration = sum(s.get("duration_seconds", 0) for s in scenes)
        if total_scene_duration < 20:
            result.warn(f"Total scene duration is only {total_scene_duration}s — may be too short")

    # 6. Prohibited content
    combined_text = full_text + " " + script.get("video_title", "")
    for pattern, description in _PROHIBITED_PATTERNS:
        if re.search(pattern, combined_text, re.IGNORECASE):
            result.fail(f"Prohibited content: {description}")

    # 7. Unverified claims
    unverified = script.get("unverified_claims", [])
    if unverified:
        result.warn(
            f"Script contains {len(unverified)} unverified claim(s) that need fact-checking: "
            + "; ".join(unverified[:3])
        )

    # 8. Keywords
    if len(script.get("keywords", [])) < 3:
        result.warn("Fewer than 3 keywords — add more for discoverability")

    # 9. Financial calculation spot-check
    calc_errors = _check_financial_calculations(full_text)
    for err in calc_errors:
        result.warn(f"Possible calculation issue: {err}")

    logger.info(
        "Script validation for topic %s: %s | errors=%d | warnings=%d",
        script.get("topic_id", "?"),
        "PASS" if result.passed else "FAIL",
        len(result.errors),
        len(result.warnings),
    )
    return result


def _check_financial_calculations(text: str) -> list[str]:
    """
    Spot-check simple interest calculations mentioned in the script text.
    Looks for patterns like 'P=10000, R=8%, T=1 year -> interest = X'
    and verifies with Python arithmetic.
    Returns list of discrepancy descriptions.
    """
    issues: list[str] = []

    # Pattern: "₹X at Y% for Z years" → "₹R"
    # e.g., "Rs. 10,000 at 8% for 1 year gives Rs. 800"
    si_pattern = re.compile(
        r"(?:Rs\.?|INR|₹)\s*([\d,]+)\s+at\s+([\d.]+)%\s+for\s+(\d+)\s+years?\s+(?:gives?|earns?|yields?|is|=)\s+(?:Rs\.?|INR|₹)\s*([\d,]+)",
        re.IGNORECASE,
    )
    for m in si_pattern.finditer(text):
        try:
            p   = float(m.group(1).replace(",", ""))
            r   = float(m.group(2))
            t   = float(m.group(3))
            stated = float(m.group(4).replace(",", ""))
            expected = p * r * t / 100
            if abs(expected - stated) / max(expected, 1) > 0.02:  # 2% tolerance
                issues.append(
                    f"Simple interest mismatch: P={p}, R={r}%, T={t} → expected {expected:.0f}, stated {stated:.0f}"
                )
        except (ValueError, ZeroDivisionError):
            pass

    # Compound interest check: A = P(1 + r/n)^(nt)
    # Pattern: "Rs. X at Y% compounded annually for Z years gives Rs. W"
    ci_pattern = re.compile(
        r"(?:Rs\.?|INR|₹)\s*([\d,]+)\s+(?:compounded|at)\s+([\d.]+)%\s+(?:compounded\s+)?annually\s+for\s+(\d+)\s+years?\s+(?:gives?|grows?\s+to|becomes?)\s+(?:Rs\.?|INR|₹)\s*([\d,]+)",
        re.IGNORECASE,
    )
    for m in ci_pattern.finditer(text):
        try:
            p      = float(m.group(1).replace(",", ""))
            r      = float(m.group(2)) / 100
            t      = float(m.group(3))
            stated = float(m.group(4).replace(",", ""))
            expected = p * ((1 + r) ** t)
            if abs(expected - stated) / max(expected, 1) > 0.05:  # 5% tolerance
                issues.append(
                    f"Compound interest mismatch: P={p}, r={r*100}%, t={t} → expected {expected:.0f}, stated {stated:.0f}"
                )
        except (ValueError, ZeroDivisionError, OverflowError):
            pass

    return issues
