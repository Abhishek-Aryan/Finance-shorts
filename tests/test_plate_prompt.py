import pytest
from visuals.plate_prompt import build_plate_prompt, TEMPLATE


def test_plate_prompt_deterministic():
    topic = {"topic_id": "T01", "visual_subject": "a lone silhouette standing on an overlook watching two elevated roads cross"}
    p1 = build_plate_prompt(topic)
    p2 = build_plate_prompt(topic)
    assert p1 == p2
    assert "Vertical 9:16 cinematic still" in p1
    assert "a lone silhouette standing on an overlook" in p1


def test_plate_prompt_contains_template():
    topic = {"topic_id": "T02", "visual_subject": "a lone silhouette standing beside a vault door"}
    prompt = build_plate_prompt(topic)
    assert "Palette: deep navy-black base" in prompt
    assert "Luxury silhouette style" in prompt
    assert "No text, letters, numbers, logos" in prompt


def test_plate_prompt_missing_visual_subject():
    with pytest.raises(ValueError, match="Missing required 'visual_subject'"):
        build_plate_prompt({"topic_id": "T03"})

    with pytest.raises(ValueError, match="Missing required 'visual_subject'"):
        build_plate_prompt({"topic_id": "T03", "visual_subject": "   "})


def test_plate_prompt_word_count_limit():
    long_subject = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twentyone twentytwo twentythree twentyfour twentyfive twentysix"
    assert len(long_subject.split()) == 26
    with pytest.raises(ValueError, match="exceeds maximum 25 words"):
        build_plate_prompt({"topic_id": "T04", "visual_subject": long_subject})


def test_plate_prompt_invalid_input():
    with pytest.raises(ValueError, match="Topic must be a dictionary"):
        build_plate_prompt("not a dict")  # type: ignore
