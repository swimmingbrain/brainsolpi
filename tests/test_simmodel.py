import random

import pytest

from brainsolpi.simmodel import (
    Light,
    divider,
    fractions,
    ideal_calibration,
    illuminate,
    panel_lux,
    raw_value,
    sample,
    servo_step,
)

# the expected numbers below were worked out by hand from the formulas in the blueprint


def test_light_straight_on_lights_every_sensor_fully():
    luxes, e = illuminate(Light(az=0, el=0), 0, 0)
    assert e == pytest.approx(900)
    assert luxes == pytest.approx([960, 960, 960, 960])
    assert raw_value(960, None) == 7862


def test_light_from_the_right_shades_the_left_sensor():
    luxes, e = illuminate(Light(az=20, el=0), 0, 0)
    # cn = cos 20 = 0.93969, cr = sin 20 = 0.34202, tx = 0.36397, fL = 1 - 1.2 tx = 0.56324
    assert e == pytest.approx(845.723, abs=1e-3)
    assert luxes[0] == pytest.approx(536.342, abs=1e-3)
    assert luxes[1:] == pytest.approx([905.723] * 3, abs=1e-3)
    assert raw_value(luxes[0], None) == 7709
    assert raw_value(luxes[1], None) == 7849


def test_light_from_above_shades_the_down_sensor():
    luxes, e = illuminate(Light(az=0, el=30), 0, 0)
    # cn = 0.86603, cv = 0.5, ty = 0.57735, fD = 0.30718
    assert e == pytest.approx(779.423, abs=1e-3)
    l, r, u, d = luxes
    assert d == pytest.approx(299.423, abs=1e-3)
    assert l == r == u == pytest.approx(839.423, abs=1e-3)


def test_light_behind_the_panel_leaves_only_ambient():
    luxes, e = illuminate(Light(az=180, el=0), 0, 0)
    assert e == 0
    assert luxes == [60, 60, 60, 60]
    assert raw_value(60, None) == 6367


def test_light_switched_off():
    luxes, e = illuminate(Light(az=0, el=0, on=False), 0, 0)
    assert e == 0
    assert luxes == [60] * 4


def test_grazing_light_counts_as_behind():
    assert fractions(0.02, 0.5, 0.0) == (0, 0, 0, 0)
    assert fractions(0.021, 0.0, 0.0) == (1, 1, 1, 1)


def test_fractions_clamp_at_zero():
    fl, fr, fu, fd = fractions(0.5, 0.5, -0.5)
    assert fl == 0 and fr == 1
    assert fu == 0 and fd == 1


def test_divider_floor_and_range():
    assert divider(0) == divider(0.05)
    assert raw_value(0, None) == 196
    assert divider(10) == pytest.approx(0.5)
    assert 0 < divider(1e6) < 1


def test_raw_noise_is_small_and_clamped():
    rng = random.Random(1)
    vals = [raw_value(960, rng) for _ in range(2000)]
    mean = sum(vals) / len(vals)
    sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
    assert mean == pytest.approx(7862, abs=0.5)
    assert sd == pytest.approx(6, abs=0.5)
    assert max(raw_value(1e9, rng) for _ in range(200)) == 8184


def test_panel_lux_noise_is_one_percent():
    rng = random.Random(2)
    vals = [panel_lux(900, 60, rng) for _ in range(2000)]
    mean = sum(vals) / len(vals)
    sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
    assert mean == pytest.approx(960, rel=0.002)
    assert sd == pytest.approx(9.6, rel=0.1)


def test_servo_moves_at_most_400_degrees_per_second():
    assert servo_step(0, 100, 0.02) == pytest.approx(8)
    assert servo_step(10, -100, 0.02) == pytest.approx(2)
    assert servo_step(10, 13, 0.02) == 13


def test_sample_without_noise_is_repeatable():
    raws, lux = sample(Light(az=0, el=0), 0, 0, None)
    assert raws == [7862] * 4
    assert lux == pytest.approx(960)


def test_ideal_calibration_for_the_phone_scene():
    dark, bright = ideal_calibration(900, 60)
    # dark at 60 + 900 / 4 = 285 lux, bright at 960 lux
    assert dark == [7468.0] * 4
    assert bright == [7862.0] * 4
