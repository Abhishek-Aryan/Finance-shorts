import pytest
from visuals.cinematic_composer import get_zoom_direction, build_zoompan_filter


def test_compose_motion_parity_alternates():
    # Odd topic number -> 1 (zoom-out)
    assert get_zoom_direction("T01") == 1
    assert get_zoom_direction("T03") == 1
    assert get_zoom_direction("T15") == 1
    assert get_zoom_direction("D05-15:00") == 1  # 5 % 2 = 1

    # Even topic number -> 0 (zoom-in)
    assert get_zoom_direction("T02") == 0
    assert get_zoom_direction("T04") == 0
    assert get_zoom_direction("T16") == 0
    assert get_zoom_direction("D04-20:00") == 0  # 4 % 2 = 0


def test_compose_motion_unparseable_fallback_zero():
    assert get_zoom_direction("") == 0
    assert get_zoom_direction("no_digits_here") == 0
    assert get_zoom_direction("finance_short") == 0
    assert get_zoom_direction(None) == 0  # type: ignore


def test_compose_motion_filter_expressions():
    # Zoom-in expression (direction 0)
    f_in = build_zoompan_filter(direction=0, total_frames=900, fps=30, max_zoom=1.06)
    assert "scale=2160:3840" in f_in
    assert "zoompan=z='if(eq(on,1),1.0,min(max(zoom,1.0)+0.0008,1.06))'" in f_in
    assert "d=900" in f_in
    assert "s=1080x1920" in f_in
    assert "fps=30" in f_in

    # Zoom-out expression (direction 1)
    f_out = build_zoompan_filter(direction=1, total_frames=900, fps=30, max_zoom=1.06)
    assert "scale=2160:3840" in f_out
    assert "zoompan=z='if(eq(on,1),1.06,max(zoom-0.0008,1.0))'" in f_out
    assert "d=900" in f_out
