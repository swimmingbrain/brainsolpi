import math

import pytest

from brainsolpi.derived import gain, light_estimate, measured_mw, offset_deg, panel_mw, tangents
from brainsolpi.kinematics import angle_between, frame


def test_offset_is_zero_when_balanced():
    assert offset_deg(0, 0) == 0


def test_offset_follows_the_blueprint_formula():
    ex, ey = 0.2, -0.1
    tx = 2 * ex / (1.2 * (1 + ex))
    ty = 2 * ey / (1.2 * (1 + abs(ey)))
    assert offset_deg(ex, ey) == pytest.approx(math.degrees(math.atan(math.hypot(tx, ty))))
    assert tangents(ex, ey) == pytest.approx((tx, ty))


def test_gain_against_the_flat_reference():
    # a panel facing the horizon against a flat one sees the horizon light ten times better, capped
    assert gain(0, 0, 0, 90) == pytest.approx(10)
    assert gain(0, 90, 0, 90) == pytest.approx(1)
    assert gain(0, 30, 0, 90) == pytest.approx(2)


def test_gain_with_a_light_estimate():
    n = frame(20, 40)[0]
    assert gain(20, 40, 0, 90, light=n) == pytest.approx(gain(20, 40, 0, 90))
    behind = (-n[0], -n[1], -n[2])
    assert gain(20, 40, 0, 90, light=behind) == 0


def test_light_estimate_leans_toward_the_brighter_side():
    s = light_estimate(0, 0, 0.3, 0.0)
    assert s[0] > 0
    assert angle_between(s, frame(0, 0)[0]) == pytest.approx(offset_deg(0.3, 0), abs=1e-9)


def test_panel_power():
    # 1100 lux is 10 W per square metre, on 0.01 square metres at 15 percent that is 15 mW
    assert panel_mw(1100, 100, 100, 0.15) == pytest.approx(15)
    assert panel_mw(None, 100, 100, 0.15) is None
    assert measured_mw(5000, 20000) == pytest.approx(100)
