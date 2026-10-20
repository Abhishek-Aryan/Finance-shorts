"""
Finance Shorts - High-Retention Visual Graphic Generator (Pro Edition)
Generates vertical (1080x1920) scene cards with rich dark-mode aesthetics,
ambient studio glow, glassmorphism containers, financial chart callouts,
and punchy typography.
Uses Pillow and Matplotlib — 100% free, local, and zero-cost.
"""

from __future__ import annotations

import io
import logging
import math
import re
from pathlib import Path
from typing import Any, Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

import config

logger = logging.getLogger(__name__)

# ── Color Palette (Studio Dark Mode) ──────────────────────────────────────────
BG_TOP       = (7, 11, 20)        # Deep Midnight Slate #070B14
BG_BOTTOM    = (13, 25, 54)       # Deep Studio Navy #0D1936
CARD_BG      = (20, 30, 52, 220)  # Glassmorphic Slate with alpha
CARD_BORDER  = (59, 130, 246)     # Electric Blue #3B82F6
ACCENT_CYAN  = (6, 182, 212)      # Cyan #06B6D4
ACCENT_GOLD  = (245, 158, 11)     # Amber Gold #F59E0B
ACCENT_GREEN = (16, 185, 129)     # Emerald Green #10B981
ACCENT_CORAL = (244, 63, 94)      # Coral / Red #F43F5E
TEXT_WHITE   = (255, 255, 255)
TEXT_MUTED   = (148, 163, 184)    # Slate 400 #94A3B8


def _get_font(size: int, bold: bool = False, black: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Finds modern fonts (Roboto Black/Bold/Medium) from assets/fonts or Windows system fonts."""
    if black:
        preferred = ["Roboto-Black.ttf", "arialbd.ttf", "segoeuib.ttf"]
    elif bold:
        preferred = ["Roboto-Bold.ttf", "segoeuib.ttf", "arialbd.ttf", "calibrib.ttf"]
    else:
        preferred = ["Roboto-Medium.ttf", "Roboto-Regular.ttf", "segoeui.ttf", "arial.ttf", "calibri.ttf"]

    search_dirs = [
        Path(config.ROOT_DIR) / "assets" / "fonts",
        Path("C:/Windows/Fonts"),
    ]

    for fname in preferred:
        for sdir in search_dirs:
            p = sdir / fname
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), size)
                except Exception:
                    continue

    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def create_vertical_gradient(
    width: int = config.VIDEO_WIDTH,
    height: int = config.VIDEO_HEIGHT,
    glow_color: Tuple[int, int, int] = (29, 78, 216),
) -> Image.Image:
    """Creates a smooth 9:16 vertical gradient with ambient studio lighting."""
    top_color = BG_TOP
    bottom_color = BG_BOTTOM
    top_arr = np.array(top_color, dtype=np.float32)
    bottom_arr = np.array(bottom_color, dtype=np.float32)

    # Vertical linear ramp
    t = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    gradient_arr = (top_arr * (1.0 - t) + bottom_arr * t).astype(np.uint8)
    base_img = Image.fromarray(np.tile(gradient_arr[:, None, :], (1, width, 1))).convert("RGBA")

    # Ambient radial studio glow orb behind card
    glow_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_overlay)
    cx, cy = width // 2, 700
    r = 380
    glow_draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*glow_color, 45))
    glow_overlay = glow_overlay.filter(ImageFilter.GaussianBlur(95))

    base_img = Image.alpha_composite(base_img, glow_overlay)
    return base_img.convert("RGB")


def render_financial_chart(
    chart_type: str = "growth",
    output_size: Tuple[int, int] = (840, 500),
) -> Image.Image:
    """
    Renders clean, modern dark-mode financial charts via Matplotlib.
    chart_type options: 'growth' (compound curve), 'comparison' (bar chart), 'ratio'.
    """
    fig, ax = plt.subplots(figsize=(output_size[0] / 100, output_size[1] / 100), dpi=100)
    fig.patch.set_facecolor("#141E34")
    fig.patch.set_alpha(0.0)
    ax.set_facecolor("#0F172A")

    if chart_type == "growth":
        years = np.arange(1, 16)
        simple_wealth = 100000 + 100000 * 0.08 * years
        compound_wealth = 100000 * (1.12 ** years)

        ax.plot(years, simple_wealth / 100000, label="Savings / Simple", color="#94A3B8", linestyle="--", linewidth=3)
        ax.plot(years, compound_wealth / 100000, label="Compound Growth", color="#10B981", linewidth=4)
        ax.fill_between(years, simple_wealth / 100000, compound_wealth / 100000, color="#10B981", alpha=0.20)

        ax.set_title("COMPOUND WEALTH ACCELERATION", color="#F8FAFC", fontsize=15, fontweight="bold", pad=12)
        ax.set_xlabel("Years Invested", color="#94A3B8", fontsize=11)
        ax.set_ylabel("Wealth (Lakhs INR)", color="#94A3B8", fontsize=11)
        ax.tick_params(colors="#94A3B8", labelsize=10)
        ax.legend(facecolor="#1E293B", edgecolor="#3B82F6", labelcolor="#F8FAFC", fontsize=11, loc="upper left")

    elif chart_type == "comparison":
        categories = ["Savings", "Investments", "Needs", "Wants"]
        values = [20, 30, 40, 10]
        colors = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444"]

        bars = ax.bar(categories, values, color=colors, width=0.55, edgecolor="#ffffff", linewidth=1.2)
        ax.set_title("THE 50 / 30 / 20 BUDGET RULE", color="#F8FAFC", fontsize=15, fontweight="bold", pad=12)
        ax.set_ylabel("% of Monthly Income", color="#94A3B8", fontsize=11)
        ax.tick_params(colors="#94A3B8", labelsize=11)
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f"{height}%",
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 4), textcoords="offset points",
                        ha="center", va="bottom", color="#F8FAFC", fontweight="bold", fontsize=12)

    else:
        steps = ["Earn", "Save", "Invest", "Compound", "Freedom"]
        scores = [1, 2, 3, 4, 5]
        ax.plot(steps, scores, marker="o", markersize=10, color="#F59E0B", linewidth=4)
        ax.set_title("5 STEPS TO FINANCIAL FREEDOM", color="#F8FAFC", fontsize=15, fontweight="bold", pad=12)
        ax.tick_params(colors="#94A3B8", labelsize=11)

    for spine in ax.spines.values():
        spine.set_color("#334155")
        spine.set_linewidth(1.5)
    ax.grid(True, linestyle=":", alpha=0.35, color="#64748B")

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", transparent=True, dpi=100)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGBA")


# Badge types per scene index for high-retention video rhythm
SCENE_BADGES = {
    0: ("🔥 WEALTH SECRET", (245, 158, 11), (251, 191, 36)),   # Amber/Gold for Hook
    1: ("💡 THE PRINCIPLE", (59, 130, 246), (147, 197, 253)),  # Blue for Concept
    2: ("📊 REAL CALCULATION", (16, 185, 129), (110, 231, 183)),# Green for Proof
    3: ("⚡ THE GOLDEN RULE", (245, 158, 11), (253, 224, 71)),  # Gold for Rule
    4: ("🎯 ACTION STEP", (6, 182, 212), (165, 243, 252)),     # Cyan for CTA
}


def render_scene_frame(
    scene_index: int,
    total_scenes: int,
    topic_id: str,
    topic_title: str,
    category: str,
    on_screen_text: str,
    scene_narration: str,
    output_path: Path,
    include_chart: bool = False,
    chart_type: str = "growth",
) -> Path:
    """
    Renders a high-retention 1080x1920 vertical scene frame image with:
    1. Elegant deep navy gradient with ambient center studio lighting.
    2. Dynamic header badge (Hook, Principle, Real Calculation, Golden Rule, Action).
    3. Glassmorphic content container card with illuminated glowing border.
    4. Punchy typography using Roboto Black with number highlight chips.
    5. Embedded financial illustration/chart for data scenes.
    6. Footer channel branding, keeping lower third clean for safe-zone subtitles.
    """
    width, height = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    badge_label, badge_fill, badge_outline = SCENE_BADGES.get(
        scene_index, ("💡 FINANCE TIPS", (59, 130, 246), (147, 197, 253))
    )

    img = create_vertical_gradient(width, height)
    draw = ImageDraw.Draw(img, "RGBA")

    # ── 1. Top Category & Scene Type Badge ─────────────────────────────────────
    font_badge = _get_font(28, bold=True)
    pill_text = f"  {badge_label}  •  {topic_id}  "
    pill_bbox = draw.textbbox((0, 0), pill_text, font=font_badge)
    pill_w = pill_bbox[2] - pill_bbox[0] + 32
    pill_h = 56
    pill_x = (width - pill_w) // 2
    pill_y = 110

    # Glow behind badge
    draw.rounded_rectangle(
        [pill_x - 3, pill_y - 3, pill_x + pill_w + 3, pill_y + pill_h + 3],
        radius=28,
        fill=(*badge_fill, 70),
    )
    # Badge body
    draw.rounded_rectangle(
        [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
        radius=28,
        fill=(*badge_fill, 230),
        outline=(*badge_outline, 210),
        width=2,
    )
    draw.text((pill_x + 16, pill_y + 12), pill_text, font=font_badge, fill=TEXT_WHITE)

    # ── 2. Scene Progress Track (Scene X of Y) ─────────────────────────────────
    track_w = 880
    track_h = 6
    track_x = (width - track_w) // 2
    track_y = pill_y + pill_h + 30

    # Inactive track
    draw.rounded_rectangle([track_x, track_y, track_x + track_w, track_y + track_h], radius=3, fill=(51, 65, 85, 180))
    # Active fill
    fill_ratio = (scene_index + 1) / max(total_scenes, 1)
    fill_w = int(track_w * fill_ratio)
    draw.rounded_rectangle([track_x, track_y, track_x + fill_w, track_y + track_h], radius=3, fill=(*badge_fill, 255))

    # ── 3. Main Topic Headline ────────────────────────────────────────────────
    font_topic = _get_font(44, black=True)
    topic_lines = _wrap_text(topic_title.upper(), font_topic, max_width=920)
    cur_y = track_y + 40
    for line in topic_lines[:2]:
        bbox = draw.textbbox((0, 0), line, font=font_topic)
        line_w = bbox[2] - bbox[0]
        line_x = (width - line_w) // 2
        # Subtle drop shadow
        draw.text((line_x + 2, cur_y + 2), line, font=font_topic, fill=(0, 0, 0, 190))
        draw.text((line_x, cur_y), line, font=font_topic, fill=TEXT_WHITE)
        cur_y += 56

    # ── 4. Main Glassmorphic Card Container ───────────────────────────────────
    card_x1 = 70
    card_x2 = width - 70
    card_y1 = cur_y + 35
    card_y2 = card_y1 + 840

    # Illuminated outer glow
    draw.rounded_rectangle([card_x1 - 4, card_y1 - 4, card_x2 + 4, card_y2 + 4], radius=36, fill=(30, 58, 138, 80))
    # Card surface
    draw.rounded_rectangle([card_x1, card_y1, card_x2, card_y2], radius=34, fill=CARD_BG, outline=CARD_BORDER, width=2)

    # Content inside card: Either dynamic chart or punchy typography callout
    if include_chart or (scene_index == 2):
        chart_img = render_financial_chart(chart_type=chart_type, output_size=(840, 500))
        chart_x = (width - chart_img.width) // 2
        chart_y = card_y1 + 40
        img.paste(chart_img, (chart_x, chart_y), chart_img)
        draw = ImageDraw.Draw(img, "RGBA")

        # Key takeaway under chart
        font_sub = _get_font(38, bold=True)
        sub_lines = _wrap_text(on_screen_text, font_sub, max_width=820)
        sub_y = chart_y + chart_img.height + 25
        for s_line in sub_lines[:2]:
            s_bbox = draw.textbbox((0, 0), s_line, font=font_sub)
            s_x = (width - (s_bbox[2] - s_bbox[0])) // 2
            draw.text((s_x, sub_y), s_line, font=font_sub, fill=ACCENT_GOLD)
            sub_y += 48
    else:
        # High impact typography callout with number highlight badge
        font_main = _get_font(58, black=True)
        main_lines = _wrap_text(on_screen_text.upper(), font_main, max_width=820)

        # Look for numbers/currency to highlight (e.g. ₹10,000, 12%, 50/30/20)
        num_match = re.search(r"([₹Rs\.]*\s*[\d,]+(?:\.\d+)?%?|\b\d+/\d+/\d+\b)", on_screen_text)

        total_text_h = len(main_lines) * 76 + (110 if num_match else 0)
        text_start_y = card_y1 + (card_y2 - card_y1 - total_text_h) // 2 - 20

        # Draw number highlight pill if present
        if num_match:
            stat_str = num_match.group(1).strip()
            font_stat = _get_font(68, black=True)
            stat_bbox = draw.textbbox((0, 0), stat_str, font=font_stat)
            stat_w = stat_bbox[2] - stat_bbox[0] + 50
            stat_h = 86
            stat_x = (width - stat_w) // 2

            # Glowing stat box
            draw.rounded_rectangle(
                [stat_x, text_start_y, stat_x + stat_w, text_start_y + stat_h],
                radius=20,
                fill=(15, 23, 42, 230),
                outline=ACCENT_GOLD,
                width=2,
            )
            draw.text((stat_x + 25, text_start_y + 8), stat_str, font=font_stat, fill=ACCENT_GOLD)
            text_start_y += stat_h + 35

        for line in main_lines:
            bbox = draw.textbbox((0, 0), line, font=font_main)
            lx = (width - (bbox[2] - bbox[0])) // 2
            draw.text((lx + 3, text_start_y + 3), line, font=font_main, fill=(0, 0, 0, 200))
            draw.text((lx, text_start_y), line, font=font_main, fill=TEXT_WHITE)
            text_start_y += 76

        # Accent decorative bar inside card
        dec_w = 140
        dec_x = (width - dec_w) // 2
        draw.rounded_rectangle([dec_x, text_start_y + 20, dec_x + dec_w, text_start_y + 26], radius=3, fill=(*badge_fill, 230))

    # ── 5. Bottom Channel Branding ─────────────────────────────────────────────
    # (Leaving lower third clean for YouTube subtitles overlay)
    footer_font = _get_font(30, bold=True)
    footer_text = f"{config.CHANNEL_NAME.upper()}  •  {config.CHANNEL_TAGLINE.upper()}"
    f_bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
    fx = (width - (f_bbox[2] - f_bbox[0])) // 2
    fy = height - 120

    f_pad_x, f_pad_y = 26, 10
    draw.rounded_rectangle(
        [fx - f_pad_x, fy - f_pad_y, fx + (f_bbox[2] - f_bbox[0]) + f_pad_x, fy + (f_bbox[3] - f_bbox[1]) + f_pad_y],
        radius=18,
        fill=(11, 17, 32, 200),
        outline=(51, 65, 85, 180),
        width=1,
    )
    draw.text((fx, fy), footer_text, font=footer_font, fill=TEXT_MUTED)

    # Save final PNG
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), format="PNG", quality=95)
    logger.info("Saved pro scene frame: %s", output_path.name)
    return output_path


def _wrap_text(text: str, font: Any, max_width: int) -> list[str]:
    """Wraps text to fit within max_width pixels."""
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current_line = words[0]

    dummy = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy)

    for word in words[1:]:
        test_line = current_line + " " + word
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word

    lines.append(current_line)
    return lines
