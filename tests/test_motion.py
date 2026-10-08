import pytest

from brainsolpi.motion import LIMIT_PAN, LIMIT_TILT, Motion

DT = 0.02
PAN = (-88.0, 88.0)
TILT = (4.0, 176.0)


def test_acceleration_is_capped():
    m = Motion(0, 90)
    m.step(60, -60, DT, 240, PAN, TILT)
    assert m.vp == pytest.approx(4.8)
    assert m.vt == pytest.approx(-4.8)
    for _ in range(20):
        m.step(60, -60, DT, 240, PAN, TILT)
    assert m.vp == pytest.approx(60)
    assert m.vt == pytest.approx(-60)


def test_speed_changes_smoothly_when_the_command_flips():
    m = Motion(0, 90)
    for _ in range(50):
        m.step(60, 0, DT, 240, PAN, TILT)
    prev = m.vp
    for _ in range(30):
        m.step(-60, 0, DT, 240, PAN, TILT)
        assert abs(m.vp - prev) <= 240 * DT + 1e-9
        prev = m.vp


def test_soft_limits_stop_the_head_and_report_pushing():
    m = Motion(80, 170)
    peak_decel = 0.0
    last = 0.0
    for _ in range(200):
        flags = m.step(60, 60, DT, 240, PAN, TILT)
        peak_decel = max(peak_decel, (last - m.vp) / DT)
        last = m.vp
    assert m.pan == 88 and m.tilt == 176
    assert m.vp == 0 and m.vt == 0
    assert flags == LIMIT_PAN | LIMIT_TILT
    # braking ahead of the limit keeps the stop gentle
    assert peak_decel <= 240 + 1e-6


def test_leaving_a_limit_is_possible():
    m = Motion(88, 90)
    assert m.step(-30, 0, DT, 240, PAN, TILT) == 0
    assert m.pan < 88


def test_seek_lands_without_overshoot():
    m = Motion(-60, 30)
    trace = []
    for _ in range(400):
        done = m.seek(40, 150, 60, DT, 240, PAN, TILT)
        trace.append((m.pan, m.tilt))
        assert abs(m.vp) <= 60 + 1e-9 and abs(m.vt) <= 60 + 1e-9
        if done:
            break
    assert done
    assert m.pan == 40 and m.tilt == 150
    assert max(p for p, _ in trace) <= 40 + 1e-9
    assert max(t for _, t in trace) <= 150 + 1e-9


def test_seek_clamps_the_target_to_the_limits():
    m = Motion(0, 90)
    for _ in range(500):
        if m.seek(95, -10, 60, DT, 240, PAN, TILT):
            break
    assert (m.pan, m.tilt) == (88, 4)


def test_seek_keeps_the_running_speed_on_handover():
    m = Motion(0, 90)
    for _ in range(40):
        m.step(60, 0, DT, 240, PAN, TILT)
    v = m.vp
    # a new target behind the head brakes at amax instead of reversing at once
    m.seek(-50, 90, 60, DT, 240, PAN, TILT)
    assert m.vp == pytest.approx(v - 240 * DT)
    assert LIMIT_TILT == 2
