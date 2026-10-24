import json
import pytest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import numpy as np

from tools.generate_plates import generate_plates


@pytest.fixture
def mock_curriculum(tmp_path):
    curr_file = tmp_path / "curriculum.json"
    data = [
        {"topic_id": f"T{i:02d}", "topic": f"Topic {i}", "visual_subject": f"a silhouette of figure number {i}"}
        for i in range(1, 6)
    ]
    curr_file.write_text(json.dumps(data), encoding="utf-8")
    return curr_file


def _create_valid_plate_image(path: Path):
    arr = np.zeros((1920, 1080, 3), dtype=np.uint8)
    for y in range(1920):
        for x in range(1080):
            noise = (x * 7 + y * 13) % 25
            arr[y, x, 0] = 12 + noise // 2
            arr[y, x, 1] = 16 + noise // 2
            arr[y, x, 2] = 26 + noise
    # Add gold highlight
    arr[800:1100, 400:680, 0] = 160
    arr[800:1100, 400:680, 1] = 130
    arr[800:1100, 400:680, 2] = 40
    img = Image.fromarray(arr)
    img.save(path, "PNG")


def test_generate_plates_skips_existing(tmp_path, mock_curriculum):
    plates_dir = tmp_path / "plates"
    plates_dir.mkdir()
    manifest_file = plates_dir / "manifest.json"

    # Pre-create T01.jpg
    (plates_dir / "T01.jpg").write_bytes(b"existing_jpg")

    with patch("tools.generate_plates.run_node_generator") as mock_run:
        code = generate_plates(
            curriculum_path=mock_curriculum,
            plates_dir=plates_dir,
            manifest_path=manifest_file,
            only_ids=["T01"],
            force=False,
            max_per_run=5,
        )
        assert code == 0
        mock_run.assert_not_called()


def test_generate_plates_auth_error_stops_and_returns_2(tmp_path, mock_curriculum):
    plates_dir = tmp_path / "plates"
    plates_dir.mkdir()
    manifest_file = plates_dir / "manifest.json"

    with patch("tools.generate_plates.run_node_generator", return_value=(1, "", "Auth Error: Refresh credentials")):
        code = generate_plates(
            curriculum_path=mock_curriculum,
            plates_dir=plates_dir,
            manifest_path=manifest_file,
            only_ids=["T01"],
            force=True,
            max_per_run=5,
            gen_script="mock_gen.js",
        )
        assert code == 2


def test_generate_plates_429_exhausts_and_stops(tmp_path, mock_curriculum):
    plates_dir = tmp_path / "plates"
    plates_dir.mkdir()
    manifest_file = plates_dir / "manifest.json"

    with patch("tools.generate_plates.run_node_generator", return_value=(1, "", "429 Resource Exhausted")), \
         patch("time.sleep") as mock_sleep:
        code = generate_plates(
            curriculum_path=mock_curriculum,
            plates_dir=plates_dir,
            manifest_path=manifest_file,
            only_ids=["T01"],
            force=True,
            max_per_run=5,
            backoff_delays=(0.01, 0.02, 0.03),
            gen_script="mock_gen.js",
        )
        assert code == 1
        assert mock_sleep.call_count == 3


def test_generate_plates_max_per_run_stops(tmp_path, mock_curriculum):
    plates_dir = tmp_path / "plates"
    plates_dir.mkdir()
    manifest_file = plates_dir / "manifest.json"

    def side_effect(script, prompt, output_png, aspect_ratio="9:16"):
        _create_valid_plate_image(Path(output_png))
        return 0, "MEDIA: generated image successfully", ""

    with patch("tools.generate_plates.run_node_generator", side_effect=side_effect):
        code = generate_plates(
            curriculum_path=mock_curriculum,
            plates_dir=plates_dir,
            manifest_path=manifest_file,
            force=True,
            max_per_run=2,  # Stop after 2 topics
            gen_script="mock_gen.js",
        )
        assert code == 0
        assert (plates_dir / "T01.jpg").exists()
        assert (plates_dir / "T02.jpg").exists()
        assert not (plates_dir / "T03.jpg").exists()

        # Check manifest
        with open(manifest_file, "r", encoding="utf-8") as f:
            m = json.load(f)
        assert "T01" in m["topics"]
        assert "T02" in m["topics"]
        assert m["topics"]["T01"]["passes_gate"] is True
