"""
Finance Shorts Pro - Plate Quality Gate
Validates image dimensions, center crops to 9:16, resizes to 1080x1920,
and checks top/bottom band luminance and overall textural variance using Pillow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from PIL import Image, ImageStat

import config


@dataclass
class GateResult:
    passed: bool
    luma_top: float
    luma_bottom: float
    stddev: float
    reason: str


def evaluate_plate(
    image_input: Union[Path, str, Image.Image],
    max_luma: Optional[float] = None,
) -> tuple[GateResult, Optional[Image.Image]]:
    """
    Evaluates an image against the quality gate:
    1. Dimension check: width >= 1080 and height >= 1920.
    2. Center crop to 9:16 ratio if needed, resize to exactly 1080x1920 with LANCZOS.
    3. Measure mean luminance for:
       - Top 20% band (rows 0 to 384)
       - Bottom 20% band (rows 1536 to 1920)
    4. Check luminance < max_luma (default 90).
    5. Check full-frame stddev >= 6.0 (reject flat/blank frames).

    Returns (GateResult, processed_image).
    """
    threshold_luma = max_luma if max_luma is not None else getattr(config, "IMAGE_MAX_LUMA", 90.0)

    # 1. Open and convert to RGB
    if isinstance(image_input, (str, Path)):
        img_path = Path(image_input)
        if not img_path.exists():
            return GateResult(
                passed=False, luma_top=0.0, luma_bottom=0.0, stddev=0.0,
                reason=f"File not found: {img_path}"
            ), None
        try:
            img = Image.open(img_path).convert("RGB")
        except Exception as e:
            return GateResult(
                passed=False, luma_top=0.0, luma_bottom=0.0, stddev=0.0,
                reason=f"Failed to open image: {e}"
            ), None
    elif isinstance(image_input, Image.Image):
        img = image_input.convert("RGB")
    else:
        return GateResult(
            passed=False, luma_top=0.0, luma_bottom=0.0, stddev=0.0,
            reason=f"Invalid image input type: {type(image_input)}"
        ), None

    # Check minimum dimensions
    w, h = img.size
    if w < 1080 or h < 1920:
        return GateResult(
            passed=False, luma_top=0.0, luma_bottom=0.0, stddev=0.0,
            reason=f"Dimensions {w}x{h} smaller than required 1080x1920 (no upscaling permitted)"
        ), None

    # 2. Center crop to 9:16 ratio if needed
    target_ratio = 9.0 / 16.0
    current_ratio = w / h

    if abs(current_ratio - target_ratio) > 1e-3:
        if current_ratio > target_ratio:
            # Too wide, crop width
            new_w = int(round(h * target_ratio))
            left = (w - new_w) // 2
            img = img.crop((left, 0, left + new_w, h))
        else:
            # Too tall, crop height
            new_h = int(round(w / target_ratio))
            top = (h - new_h) // 2
            img = img.crop((0, top, w, top + new_h))

    # Resize to exact 1080x1920 with LANCZOS
    if img.size != (1080, 1920):
        img = img.resize((1080, 1920), Image.Resampling.LANCZOS)

    # Convert to grayscale for luminance checks
    gray = img.convert("L")

    # Compute overall standard deviation (textural variance)
    full_stat = ImageStat.Stat(gray)
    stddev = full_stat.stddev[0] if full_stat.stddev else 0.0

    if stddev < 6.0:
        return GateResult(
            passed=False, luma_top=0.0, luma_bottom=0.0, stddev=round(stddev, 2),
            reason=f"Image lacks texture/variance (stddev {stddev:.2f} < 6.0)"
        ), img

    # Top band: rows 0 to 384 (top 20%)
    top_band = gray.crop((0, 0, 1080, 384))
    top_stat = ImageStat.Stat(top_band)
    luma_top = top_stat.mean[0] if top_stat.mean else 0.0

    # Bottom band: rows 1536 to 1920 (bottom 20%)
    bottom_band = gray.crop((0, 1536, 1080, 1920))
    bottom_stat = ImageStat.Stat(bottom_band)
    luma_bottom = bottom_stat.mean[0] if bottom_stat.mean else 0.0

    luma_top_r = round(luma_top, 2)
    luma_bottom_r = round(luma_bottom, 2)
    stddev_r = round(stddev, 2)

    if luma_top > threshold_luma:
        return GateResult(
            passed=False, luma_top=luma_top_r, luma_bottom=luma_bottom_r, stddev=stddev_r,
            reason=f"Top band luminance too high ({luma_top_r:.1f} > {threshold_luma})"
        ), img

    if luma_bottom > threshold_luma:
        return GateResult(
            passed=False, luma_top=luma_top_r, luma_bottom=luma_bottom_r, stddev=stddev_r,
            reason=f"Bottom band luminance too high ({luma_bottom_r:.1f} > {threshold_luma})"
        ), img

    return GateResult(
        passed=True, luma_top=luma_top_r, luma_bottom=luma_bottom_r, stddev=stddev_r,
        reason="Passed quality gate"
    ), img
