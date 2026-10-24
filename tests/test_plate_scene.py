import json
import logging
import pytest
from pathlib import Path
from visuals.plate_scene import plate_scene


def test_plate_scene_existing_and_passed(tmp_path, caplog):
    # Setup test directory
    plates_dir = tmp_path / "plates"
    plates_dir.mkdir()
    fallback_file = tmp_path / "fallback.png"
    fallback_file.write_bytes(b"fallback_data")

    plate_file = plates_dir / "T01.jpg"
    plate_file.write_bytes(b"dummy_image_data")

    manifest_file = plates_dir / "manifest.json"
    manifest_data = {
        "version": 1,
        "topics": {
            "T01": {
                "file": str(plate_file),
                "passes_gate": True,
                "status": "ok",
            }
        }
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    res = plate_scene("T01", manifest_path=manifest_file, plate_dir=plates_dir, fallback_path=fallback_file)
    assert res == plate_file


def test_plate_scene_missing_returns_fallback_and_warns(tmp_path, caplog):
    plates_dir = tmp_path / "plates"
    plates_dir.mkdir()
    fallback_file = tmp_path / "fallback.png"
    fallback_file.write_bytes(b"fallback_data")
    manifest_file = plates_dir / "manifest.json"
    manifest_file.write_text(json.dumps({"version": 1, "topics": {}}), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        res = plate_scene("T99", manifest_path=manifest_file, plate_dir=plates_dir, fallback_path=fallback_file)

    assert res == fallback_file
    assert any("PLATE FALLBACK" in rec.message and "T99" in rec.message for rec in caplog.records)


def test_plate_scene_failed_gate_returns_fallback(tmp_path, caplog):
    plates_dir = tmp_path / "plates"
    plates_dir.mkdir()
    fallback_file = tmp_path / "fallback.png"
    fallback_file.write_bytes(b"fallback_data")

    plate_file = plates_dir / "T02.jpg"
    plate_file.write_bytes(b"dummy_image_data")

    manifest_file = plates_dir / "manifest.json"
    manifest_data = {
        "version": 1,
        "topics": {
            "T02": {
                "file": str(plate_file),
                "passes_gate": False,
                "status": "flagged",
            }
        }
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        res = plate_scene("T02", manifest_path=manifest_file, plate_dir=plates_dir, fallback_path=fallback_file)

    assert res == fallback_file
    assert any("failed quality gate" in rec.message for rec in caplog.records)


def test_plate_scene_never_raises():
    # Pass completely non-existent / broken paths
    res = plate_scene(
        "invalid",
        manifest_path=Path("/does/not/exist/manifest.json"),
        plate_dir=Path("/does/not/exist/plates"),
        fallback_path=Path("/fallback.png")
    )
    assert res == Path("/fallback.png")
