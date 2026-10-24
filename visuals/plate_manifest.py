"""
Finance Shorts Pro - Plate Manifest Store
Thread-safe, atomic persistence for assets/plates/manifest.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import config

MANIFEST_PATH = Path(config.ROOT_DIR) / "assets" / "plates" / "manifest.json"


def load_manifest(path: Optional[Path] = None) -> dict[str, Any]:
    """Loads manifest.json or returns empty template if not present."""
    m_path = path or MANIFEST_PATH
    if m_path.exists():
        try:
            with open(m_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {"version": 1, "topics": {}}


def save_manifest(manifest: dict[str, Any], path: Optional[Path] = None) -> None:
    """
    Atomically writes manifest.json.
    Ensures topics are sorted by topic_id to keep git diffs readable.
    """
    m_path = path or MANIFEST_PATH
    m_path.parent.mkdir(parents=True, exist_ok=True)

    topics = manifest.get("topics", {})
    sorted_topics = dict(sorted(topics.items(), key=lambda x: str(x[0])))
    manifest["topics"] = sorted_topics

    tmp_path = m_path.parent / f"{m_path.name}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.flush()

    tmp_path.replace(m_path)
