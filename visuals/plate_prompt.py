"""
Finance Shorts Pro - Plate Prompt Builder
Generates deterministic 9:16 vertical luxury cinematic prompts for topic plates.
"""

from __future__ import annotations

TEMPLATE = (
    "Vertical 9:16 cinematic still, full-bleed background, no text. {visual_subject}. "
    "Palette: deep navy-black base (#0B0F1A to #151B2B), warm gold accents (#C9A227 to #E6C35C), "
    "soft ivory highlights; no other hue dominant. Single soft key light from upper left, gold rim light, "
    "light volumetric haze, shallow depth of field. Luxury silhouette style: dark figure or abstract "
    "object seen from behind or in profile, no visible faces. Subtle film grain, gentle vignette. "
    "Keep the top 20% and bottom 30% visually calm and uncluttered. Premium, serious, documentary tone. "
    "No text, letters, numbers, logos, watermarks, charts, or people's faces."
)


def build_plate_prompt(topic: dict) -> str:
    """
    Constructs a deterministic prompt for a curriculum topic plate.
    Raises ValueError if visual_subject is missing, empty, or exceeds 25 words.
    """
    if not isinstance(topic, dict):
        raise ValueError("Topic must be a dictionary")

    visual_subject = str(topic.get("visual_subject", "")).strip()
    if not visual_subject:
        raise ValueError(f"Missing required 'visual_subject' for topic: {topic.get('topic_id', topic.get('topic'))}")

    words = visual_subject.split()
    if len(words) > 25:
        raise ValueError(
            f"visual_subject exceeds maximum 25 words ({len(words)} words): '{visual_subject}'"
        )

    return TEMPLATE.format(visual_subject=visual_subject)
