import pytest
import numpy as np
from PIL import Image
from visuals.plate_gate import evaluate_plate, GateResult


def test_plate_gate_small_image_rejected():
    img = Image.new("RGB", (800, 1200), color=(20, 20, 30))
    res, proc = evaluate_plate(img)
    assert not res.passed
    assert "smaller than required 1080x1920" in res.reason


def test_plate_gate_flat_image_rejected_stddev():
    # Solid flat grey 1080x1920
    img = Image.new("RGB", (1080, 1920), color=(40, 40, 40))
    res, proc = evaluate_plate(img)
    assert not res.passed
    assert "stddev" in res.reason


def test_plate_gate_bright_top_band_rejected():
    # Create an image that has dark bottom and middle, but bright white top band
    arr = np.zeros((1920, 1080, 3), dtype=np.uint8)
    # Give some texture overall so stddev > 6
    arr[400:1500, :, 0] = np.random.randint(10, 50, (1100, 1080), dtype=np.uint8)
    # Bright top 20% (rows 0 to 384)
    arr[0:384, :, :] = 255
    img = Image.fromarray(arr)
    res, proc = evaluate_plate(img, max_luma=90)
    assert not res.passed
    assert "Top band luminance too high" in res.reason
    assert res.luma_top > 90


def test_plate_gate_dark_textured_passes():
    # Dark textured luxury palette image
    arr = np.zeros((1920, 1080, 3), dtype=np.uint8)
    # Navy black base with warm gold accents and grain
    for y in range(1920):
        for x in range(1080):
            noise = (x * 7 + y * 13) % 25
            arr[y, x, 0] = 12 + noise // 2
            arr[y, x, 1] = 16 + noise // 2
            arr[y, x, 2] = 26 + noise

    # Add a glowing gold accent in the middle 50%
    arr[800:1100, 400:680, 0] = 160
    arr[800:1100, 400:680, 1] = 130
    arr[800:1100, 400:680, 2] = 40

    img = Image.fromarray(arr)
    res, proc = evaluate_plate(img, max_luma=90)
    assert res.passed
    assert res.luma_top < 90
    assert res.luma_bottom < 90
    assert res.stddev >= 6.0
    assert proc is not None
    assert proc.size == (1080, 1920)
