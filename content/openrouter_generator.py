"""
Finance Shorts Pro - OpenRouter Script Generator
Uses MiniMax M3.1 Flash (via OpenRouter) to generate cinematic storyboard scripts
for each finance topic, including HeyGen video scene prompts.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Optional

import requests
import config

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = getattr(config, "OPENROUTER_API_KEY", "") or os.environ.get("OPENROUTER_API_KEY", "")
GEMINI_API_KEY = getattr(config, "GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
OR_BASE = "https://openrouter.ai/api/v1"
OR_CHAT_URL = f"{OR_BASE}/chat/completions"
SCRIPT_MODEL = getattr(config, "SCRIPT_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
# Fallback: MiniMax M3.1 Flash - confirmed working free model
FALLBACK_MODEL = "minimax/minimax-m3.1-flash:free"

# Character description for all prompts - consistent across all scenes
CHARACTER_DESC = (
    "A sleek faceless humanoid silhouette man in a tailored black suit with brilliant gold rim lighting "
    "along his outline, no face details, standing confidently in a dark cinematic studio with ambient amber glow."
)

SYSTEM_PROMPT = """You are a senior finance video director creating scripts for 45-second YouTube Shorts.
Audience: Indian millennials and investors.
Tone: authoritative, crisp, and high-retention.
Always return ONLY valid, well-formed JSON."""


def _clean_json_str(raw: str) -> str:
    """Cleans up raw LLM text to extract valid JSON."""
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())

    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]

    # Remove trailing commas before } or ]
    raw = re.sub(r",\s*([}\]])", r"\1", raw)
    return raw


def _extract_json_from_text(text: str) -> Optional[dict]:
    """Try to extract a valid JSON object from anywhere in a text block."""
    # Find all potential JSON blobs (greedy from first { to last })
    candidates = []
    depth = 0
    start_idx = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start_idx = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start_idx is not None:
                candidates.append(text[start_idx:i + 1])
                start_idx = None

    for candidate in reversed(candidates):  # Try largest block first
        try:
            candidate = re.sub(r",\s*([}\]])", r"\1", candidate)  # fix trailing commas
            data = json.loads(candidate)
            if "scenes" in data or "video_title" in data:  # Must look like a script
                return data
        except json.JSONDecodeError:
            pass
    return None


def _enrich_script_data(script_data: dict, topic: str) -> dict:
    """Enriches scenes with mentor character prompt and unifies voiceover."""
    scenes = script_data.get("scenes", [])
    for s in scenes:
        vis = s.get("visual_scene", "Mentor explaining financial charts in dark studio")
        s["heygen_video_prompt"] = (
            f"{CHARACTER_DESC} {vis}. "
            "Cinematic lighting, dark atmospheric studio, glowing gold accents, vertical 9:16."
        )

    fv = script_data.get("full_voiceover")
    if isinstance(fv, list):
        script_data["full_voiceover"] = " ".join(
            item.get("voiceover", str(item)) if isinstance(item, dict) else str(item)
            for item in fv
        )
    elif not fv or not isinstance(fv, str):
        script_data["full_voiceover"] = " ".join(
            s.get("voiceover", "") for s in scenes
        )
    return script_data


def _generate_script_gemini(topic: str, category: str, objective: str, prompt: str) -> Optional[dict]:
    """Generates structured script JSON via Gemini API."""
    if not GEMINI_API_KEY:
        return None
    headers = {"Content-Type": "application/json", "X-goog-api-key": GEMINI_API_KEY}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 4096}
    }
    candidate_models = [
        "gemini-flash-lite-latest",
        "gemini-3.1-flash-lite",
        "gemini-flash-latest",
        "gemini-3.8-flash",
        "gemini-pro-latest",
    ]
    for model in candidate_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            logger.info("Attempting script generation with Gemini model: %s...", model)
            resp = requests.post(url, json=payload, headers=headers, timeout=35)
            if resp.status_code == 200:
                data = resp.json()
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                raw_text = "".join(p.get("text", "") for p in parts).strip()
                cleaned = _clean_json_str(raw_text)
                script_data = None
                try:
                    script_data = json.loads(cleaned)
                except json.JSONDecodeError:
                    script_data = _extract_json_from_text(raw_text)

                if script_data and ("scenes" in script_data or "video_title" in script_data):
                    logger.info("Script successfully generated using Gemini: %s", model)
                    return _enrich_script_data(script_data, topic)
            else:
                logger.warning("Gemini model %s returned status %d", model, resp.status_code)
        except Exception as e:
            logger.warning("Gemini model %s failed: %s", model, e)
    return None


def generate_pro_script(
    topic: str,
    category: str,
    key_learning_objective: str,
) -> dict[str, Any]:
    """
    Generates a full pro-level storyboard script.
    Tries Gemini API first, then OpenRouter models, with graceful fallback.
    """
    user_prompt = f"""Write a YouTube Short script for:
Topic: {topic}
Category: {category}
Learning Objective: {key_learning_objective}

CRITICAL RULES:
1. Return valid JSON only.
2. NEVER use double quotes inside string values. Use single quotes if needed (e.g. 'yield curve').
3. Keep each scene voiceover between 18 and 25 words.
4. Keep visual_scene concise (under 15 words).
5. The very last scene voiceover MUST end with the exact sentence: 'Follow the journey to improve your financial knowledge.'

Return ONLY this JSON structure:
{{
  "video_title": "Punchy 7-word title with power word",
  "voiceover_hook": "Visceral hook starting with 'Did you know' or 'Most investors don't realize'",
  "scenes": [
    {{
      "scene_number": 1,
      "scene_type": "hook",
      "duration_sec": 7,
      "voiceover": "Narrator text for this scene (20-25 words)",
      "on_screen_text": "BOLD TEXT OVERLAY (max 5 words)",
      "data_callout": "Key number or null",
      "visual_scene": "Cinematic visual description (15 words max)"
    }},
    {{
      "scene_number": 2,
      "scene_type": "concept",
      "duration_sec": 8,
      "voiceover": "Explaining the core concept clearly (20-25 words)",
      "on_screen_text": "KEY CONCEPT TEXT",
      "data_callout": "Statistic or ratio",
      "visual_scene": "Visual description (15 words max)"
    }},
    {{
      "scene_number": 3,
      "scene_type": "proof",
      "duration_sec": 8,
      "voiceover": "Proof or market data with real numbers (20-25 words)",
      "on_screen_text": "MARKET PROOF TEXT",
      "data_callout": "Data point",
      "visual_scene": "Visual description (15 words max)"
    }},
    {{
      "scene_number": 4,
      "scene_type": "india_context",
      "duration_sec": 8,
      "voiceover": "Application to Indian markets NSE/RBI/rupees (20-25 words)",
      "on_screen_text": "INDIAN MARKET IMPACT",
      "data_callout": "INR amount or metric",
      "visual_scene": "Visual description (15 words max)"
    }},
    {{
      "scene_number": 5,
      "scene_type": "rule",
      "duration_sec": 8,
      "voiceover": "The takeaway investor rule to remember (20-25 words)",
      "on_screen_text": "GOLDEN RULE",
      "data_callout": null,
      "visual_scene": "Visual description (15 words max)"
    }},
    {{
      "scene_number": 6,
      "scene_type": "cta",
      "duration_sec": 6,
      "voiceover": "Follow the journey to improve your financial knowledge. Drop your questions below.",
      "on_screen_text": "FOLLOW THE JOURNEY",
      "data_callout": null,
      "visual_scene": "Silhouette mentor standing confidently with expanding golden halo"
    }}
  ],
  "full_voiceover": "Join all 6 scene voiceovers into one cohesive paragraph (100-120 words total)",
  "video_description": "Short 2-sentence description with hashtags #Finance #Investing #India #Shorts",
  "tags": ["finance", "investing", "india", "shorts", "{category.lower()}"],
  "key_stat": "The most memorable stat from this topic"
}}"""

    # 1. Primary: Gemini API (ultra-fast, consistent valid JSON)
    gemini_script = _generate_script_gemini(topic, category, key_learning_objective, user_prompt)
    if gemini_script:
        return gemini_script

    # 2. Secondary: OpenRouter models
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    model_attempts = [
        (SCRIPT_MODEL, 2),
        (FALLBACK_MODEL, 2),
    ]

    for model_name, max_tries in model_attempts:
        logger.info("Using OpenRouter model: %s", model_name)
        for attempt in range(max_tries):
            try:
                resp = requests.post(
                    OR_CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                        "X-Title": "FinanceShortsChannel",
                    },
                    json={
                        "model": model_name,
                        "messages": messages,
                        "max_tokens": 3000,
                        "temperature": 0.6,
                    },
                    timeout=180,
                )
                resp.raise_for_status()
                resp_json = resp.json()

                if "error" in resp_json:
                    err_msg = resp_json["error"].get("message", str(resp_json["error"]))
                    logger.warning("Attempt %d API error from %s: %s", attempt + 1, model_name, err_msg)
                    time.sleep(2)
                    continue

                choice = resp_json.get("choices", [{}])[0]
                msg = choice.get("message", {})
                raw = (msg.get("content") or "").strip()
                reasoning_raw = (msg.get("reasoning") or "").strip()

                script_data = None
                if raw:
                    try:
                        cleaned = _clean_json_str(raw)
                        script_data = json.loads(cleaned)
                    except json.JSONDecodeError:
                        script_data = _extract_json_from_text(raw)

                if not script_data and reasoning_raw:
                    script_data = _extract_json_from_text(reasoning_raw)

                if not script_data:
                    combined = raw + " " + reasoning_raw
                    script_data = _extract_json_from_text(combined)

                if not script_data:
                    logger.warning("Attempt %d: No valid JSON from %s", attempt + 1, model_name)
                    time.sleep(2)
                    continue

                logger.info("Script generated via %s: %s", model_name, topic[:40])
                return _enrich_script_data(script_data, topic)

            except Exception as e:
                logger.error("Attempt %d error (%s): %s", attempt + 1, model_name, e)
                time.sleep(2)

    logger.warning("All LLM attempts failed for topic: %s. Using fallback.", topic)
    return _fallback_script(topic, category, key_learning_objective)


def _fallback_script(topic: str, category: str, objective: str) -> dict[str, Any]:
    """Graceful fallback script if API fails."""
    scenes_info = [
        ("hook", 7, f"Did you know why {topic} is watched closely by the world's best investors?", topic.upper(), None, "Standing in front of market data terminal"),
        ("concept", 8, f"{objective} When this happens, smart money repositions immediately.", "CORE CONCEPT", None, "Analyzing financial curve graphics"),
        ("proof", 8, "Historically, every major shift in this metric has triggered major moves in equity markets.", "HISTORICAL DATA", "85% Correlation", "Pointing to glowing golden trendlines"),
        ("india_context", 8, "In the Indian market, this directly impacts Nifty volatility and corporate debt costs.", "INDIAN MARKETS", "NSE & RBI", "Reviewing macroeconomic indicators"),
        ("rule", 8, "The golden rule: Never fight the macro trend. Protect your capital first.", "GOLDEN RULE", None, "Confident mentor stance"),
        ("cta", 6, "Follow for daily finance intelligence. Share this with an investor friend.", "FOLLOW FOR MORE", None, "Mentor gesturing forward"),
    ]

    scenes = []
    for i, (stype, dur, vo, ost, callout, vis) in enumerate(scenes_info, 1):
        scenes.append({
            "scene_number": i,
            "scene_type": stype,
            "duration_sec": dur,
            "voiceover": vo,
            "on_screen_text": ost,
            "data_callout": callout,
            "visual_scene": vis,
            "heygen_video_prompt": f"{CHARACTER_DESC} {vis}. Cinematic dark studio, gold rim glow.",
        })

    full_vo = " ".join(s["voiceover"] for s in scenes)
    return {
        "video_title": f"{topic[:50]} Explained",
        "voiceover_hook": f"Did you know why {topic} is watched closely by top investors?",
        "scenes": scenes,
        "full_voiceover": full_vo,
        "video_description": f"{topic} explained. {objective} #Finance #Investing #India #Shorts",
        "tags": ["finance", "investing", "india", "shorts", category.lower()],
        "key_stat": f"{topic} macro insight",
    }
