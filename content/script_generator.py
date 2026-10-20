"""
Finance Shorts - Script Generator
Calls local Ollama LLM to generate educational finance scripts.
Produces structured JSON output validated against a schema.
Never calls paid APIs.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import ollama
from jsonschema import validate, ValidationError

import config
from storage import database

logger = logging.getLogger(__name__)

# ── Output JSON Schema ────────────────────────────────────────────────────────

SCRIPT_SCHEMA = {
    "type": "object",
    "required": [
        "hook", "explanation", "example", "takeaway", "closing",
        "full_script", "video_title", "video_description", "keywords",
        "scene_plan", "source_references", "unverified_claims",
        "estimated_word_count",
    ],
    "properties": {
        "hook":               {"type": "string", "minLength": 10},
        "explanation":        {"type": "string", "minLength": 20},
        "example":            {"type": "string", "minLength": 10},
        "takeaway":           {"type": "string", "minLength": 10},
        "closing":            {"type": "string", "minLength": 5},
        "full_script":        {"type": "string", "minLength": 50},
        "video_title":        {"type": "string", "minLength": 5, "maxLength": 100},
        "video_description":  {"type": "string", "minLength": 20, "maxLength": 5000},
        "keywords":           {"type": "array",  "items": {"type": "string"}, "minItems": 3},
        "scene_plan":         {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["scene_number", "duration_seconds", "visual", "on_screen_text", "narration"],
                "properties": {
                    "scene_number":      {"type": "integer"},
                    "duration_seconds":  {"type": "number"},
                    "visual":            {"type": "string"},
                    "on_screen_text":    {"type": "string"},
                    "narration":         {"type": "string"},
                },
            },
            "minItems": 3,
        },
        "source_references":  {"type": "array",  "items": {"type": "string"}},
        "unverified_claims":  {"type": "array",  "items": {"type": "string"}},
        "estimated_word_count": {"type": "integer", "minimum": 1},
    },
}

# ── Prompt Template ───────────────────────────────────────────────────────────

def _build_prompt(
    topic: str,
    category: str,
    difficulty: int,
    audience: str,
    objective: str,
    research_summary: str,
    min_words: int,
    max_words: int,
) -> str:
    difficulty_labels = {1: "absolute beginner", 2: "elementary", 3: "intermediate", 4: "advanced", 5: "expert"}
    level = difficulty_labels.get(difficulty, "beginner")

    return f"""You are an expert finance educator creating a YouTube Short script for Indian audiences.

TOPIC: {topic}
CATEGORY: {category}
DIFFICULTY: Level {difficulty} ({level})
TARGET AUDIENCE: {audience}
LEARNING OBJECTIVE: {objective}

RESEARCH SUMMARY:
{research_summary if research_summary else "Use your general finance knowledge. Be accurate and conservative."}

INSTRUCTIONS:
1. Write an educational script for a 30-60 second YouTube Short
2. Target EXACTLY {min_words}-{max_words} spoken words in full_script
3. Use simple language appropriate for {audience}
4. Include one clear Indian example (use INR amounts like Rs. 10,000)
5. Be factually accurate - do NOT invent statistics
6. Do NOT give personalized investment advice
7. Do NOT promise returns or recommend specific securities as guaranteed
8. Write in a warm, engaging, conversational tone
9. scene_plan MUST contain 4 to 5 scenes corresponding to the 5 script sections

OUTPUT FORMAT: Respond ONLY with valid JSON matching this exact structure:

{{
  "hook": "Opening line that grabs attention (1-2 sentences)",
  "explanation": "Core concept explained simply (2-4 sentences)",
  "example": "One concrete Indian example with numbers (2-3 sentences)",
  "takeaway": "The single most important lesson (1-2 sentences)",
  "closing": "Ending question or call to action (1 sentence)",
  "full_script": "Complete narration script combining all sections ({min_words}-{max_words} words)",
  "video_title": "Engaging YouTube title under 60 characters",
  "video_description": "YouTube description (150-300 words) with hashtags",
  "keywords": ["finance", "money", "investing", "india", "tips"],
  "scene_plan": [
    {{
      "scene_number": 1,
      "duration_seconds": 6,
      "visual": "Punchy hook graphic with high contrast bold title",
      "on_screen_text": "Did You Know This?",
      "narration": "Opening hook sentence"
    }},
    {{
      "scene_number": 2,
      "duration_seconds": 12,
      "visual": "Core concept diagram and explanation graphics",
      "on_screen_text": "The Real Meaning",
      "narration": "Explanation sentences"
    }},
    {{
      "scene_number": 3,
      "duration_seconds": 12,
      "visual": "Indian real-world calculation example card with numbers",
      "on_screen_text": "Real Life Example",
      "narration": "Example sentences"
    }},
    {{
      "scene_number": 4,
      "duration_seconds": 8,
      "visual": "Key summary takeaway card with glowing highlight",
      "on_screen_text": "The Big Lesson",
      "narration": "Takeaway sentence"
    }},
    {{
      "scene_number": 5,
      "duration_seconds": 6,
      "visual": "Channel branding card with follow call to action",
      "on_screen_text": "Save & Follow",
      "narration": "Closing sentence"
    }}
  ],
  "source_references": ["Reserve Bank of India / Standard Economics"],
  "unverified_claims": [],
  "estimated_word_count": 100
}}

IMPORTANT: Output ONLY the JSON object. No markdown, no explanation, no code fences."""


# ── Script Generation ─────────────────────────────────────────────────────────

def generate_script(
    topic_id: str,
    topic: str,
    category: str,
    difficulty_level: int,
    audience: str,
    key_learning_objective: str,
    research_summary: str = "",
    min_words: Optional[int] = None,
    max_words: Optional[int] = None,
) -> dict[str, Any]:
    """
    Generate a validated script for the given topic using the local Ollama LLM.
    Retries up to OLLAMA_RETRY_COUNT times on malformed output.
    Returns the validated script dict.
    Raises RuntimeError if all retries are exhausted.
    """
    min_words = min_words or config.SCRIPT_MIN_WORDS
    max_words = max_words or config.SCRIPT_MAX_WORDS

    prompt = _build_prompt(
        topic=topic,
        category=category,
        difficulty=difficulty_level,
        audience=audience,
        objective=key_learning_objective,
        research_summary=research_summary,
        min_words=min_words,
        max_words=max_words,
    )

    last_error: Optional[str] = None
    for attempt in range(1, config.OLLAMA_RETRY_COUNT + 1):
        logger.info("Script generation attempt %d/%d for %s", attempt, config.OLLAMA_RETRY_COUNT, topic_id)
        try:
            raw = _call_ollama(prompt)
            script = _parse_and_validate(raw)
            script["model_used"]  = config.OLLAMA_MODEL
            script["generated_at"] = _now()
            script["topic_id"]    = topic_id
            _store_script(topic_id, script)
            logger.info(
                "Script generated for %s — words: %d, scenes: %d",
                topic_id, script["estimated_word_count"], len(script["scene_plan"]),
            )
            return script

        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            last_error = str(e)
            logger.warning("Attempt %d failed for %s: %s", attempt, topic_id, last_error[:120])
            if attempt < config.OLLAMA_RETRY_COUNT:
                time.sleep(2 ** attempt)  # exponential backoff

        except Exception as e:
            last_error = str(e)
            logger.error("Unexpected error on attempt %d for %s: %s", attempt, topic_id, last_error)
            raise

    raise RuntimeError(
        f"Script generation failed after {config.OLLAMA_RETRY_COUNT} attempts for {topic_id}: {last_error}"
    )


def _call_ollama(prompt: str) -> str:
    """Call the local Ollama server with format='json' and return the raw response string."""
    client = ollama.Client(host=config.OLLAMA_HOST)
    response = client.chat(
        model=config.OLLAMA_MODEL,
        format="json",
        messages=[{"role": "user", "content": prompt}],
        options={
            "temperature": config.OLLAMA_TEMPERATURE,
            "num_predict": config.OLLAMA_MAX_TOKENS,
        },
    )
    return response["message"]["content"].strip()


def _parse_and_validate(raw: str) -> dict[str, Any]:
    """
    Parse the LLM response as JSON and validate against SCRIPT_SCHEMA.
    Strips markdown code fences and isolates outer JSON object.
    """
    text = raw.strip()

    # Extract JSON between outermost braces if extra text exists
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        text = text[first_brace:last_brace + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fallback with strict=False to allow raw control characters
        data = json.loads(text, strict=False)

    # Ensure scene_plan has at least 3 valid items matching the schema
    scene_plan = data.get("scene_plan")
    if not isinstance(scene_plan, list) or len(scene_plan) < 3:
        data["scene_plan"] = [
            {
                "scene_number": 1,
                "duration_seconds": 6.0,
                "visual": "Opening hook card with punchy question",
                "on_screen_text": data.get("hook", "Did You Know?")[:40],
                "narration": data.get("hook", ""),
            },
            {
                "scene_number": 2,
                "duration_seconds": 12.0,
                "visual": "Core concept explanation and animated diagram",
                "on_screen_text": data.get("video_title", "Key Concept")[:40],
                "narration": data.get("explanation", ""),
            },
            {
                "scene_number": 3,
                "duration_seconds": 12.0,
                "visual": "Real life Indian finance example with numbers",
                "on_screen_text": "Real Life Example",
                "narration": data.get("example", ""),
            },
            {
                "scene_number": 4,
                "duration_seconds": 8.0,
                "visual": "Golden takeaway summary highlight card",
                "on_screen_text": "Key Takeaway",
                "narration": data.get("takeaway", ""),
            },
            {
                "scene_number": 5,
                "duration_seconds": 6.0,
                "visual": "Call to action card with channel branding",
                "on_screen_text": "Follow For More",
                "narration": data.get("closing", ""),
            },
        ]
    else:
        for idx, scene in enumerate(data["scene_plan"], 1):
            scene.setdefault("scene_number", idx)
            scene.setdefault("duration_seconds", 8.0)
            scene.setdefault("visual", "Finance educational graphic")
            scene.setdefault("on_screen_text", "Key Insight")
            scene.setdefault("narration", "")

    data.setdefault("source_references", [])
    data.setdefault("unverified_claims", [])
    if not isinstance(data.get("keywords"), list) or len(data["keywords"]) < 3:
        data["keywords"] = ["finance", "money", "investing", "india", "tips"]

    validate(instance=data, schema=SCRIPT_SCHEMA)

    # Sanity check word count
    actual_words = len(data.get("full_script", "").split())
    data["estimated_word_count"] = actual_words

    return data


def _store_script(topic_id: str, script: dict[str, Any]) -> None:
    """Persist the generated script to SQLite."""
    now = _now()
    with database.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO scripts
                (topic_id, hook, body, example, takeaway, closing,
                 full_script, video_title, video_description, keywords,
                 scene_plan, source_references, unverified_claims,
                 word_count, model_used, validated, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)
            ON CONFLICT(topic_id) DO UPDATE SET
                hook=excluded.hook, body=excluded.body,
                example=excluded.example, takeaway=excluded.takeaway,
                closing=excluded.closing, full_script=excluded.full_script,
                video_title=excluded.video_title,
                video_description=excluded.video_description,
                keywords=excluded.keywords, scene_plan=excluded.scene_plan,
                source_references=excluded.source_references,
                unverified_claims=excluded.unverified_claims,
                word_count=excluded.word_count, model_used=excluded.model_used,
                validated=0, updated_at=excluded.updated_at
            """,
            (
                topic_id,
                script.get("hook", ""),
                script.get("explanation", ""),
                script.get("example", ""),
                script.get("takeaway", ""),
                script.get("closing", ""),
                script.get("full_script", ""),
                script.get("video_title", ""),
                script.get("video_description", ""),
                json.dumps(script.get("keywords", [])),
                json.dumps(script.get("scene_plan", [])),
                json.dumps(script.get("source_references", [])),
                json.dumps(script.get("unverified_claims", [])),
                script.get("estimated_word_count", 0),
                script.get("model_used", config.OLLAMA_MODEL),
                now, now,
            ),
        )


def get_script(topic_id: str) -> Optional[dict[str, Any]]:
    """Load a previously generated script from SQLite."""
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM scripts WHERE topic_id = ?", (topic_id,)
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    # Deserialise JSON fields
    for field in ("keywords", "scene_plan", "source_references", "unverified_claims"):
        if result.get(field) and isinstance(result[field], str):
            try:
                result[field] = json.loads(result[field])
            except json.JSONDecodeError:
                result[field] = []
    return result


def estimate_duration_seconds(word_count: int, speaking_rate_wpm: float = 140.0) -> float:
    """
    Estimate narration duration from word count.
    Default speaking rate: 140 WPM (measured for clear educational speech).
    """
    return (word_count / speaking_rate_wpm) * 60.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
