import math

import pytest

from brainsolpi.config import Settings
from brainsolpi.controller import Tracker

DT = 0.02


def tracker(**over):
    params = dict(Settings().params)
    params.update(over)
    t = Tracker(params)
    t.calibrate([0] * 4, [1000] * 4)
    return t


def feed(t, l, r, u, d, n=1):
    for _ in range(n):
        t.sense([l * 1000, r * 1000, u * 1000, d * 1000], DT)


def test_normalisation_works_for_either_polarity():
    t = tracker()
    t.calibrate([1000] * 4, [0] * 4)
    t.sense([250, 500, 750, 1000], DT)
    assert t.f == pytest.approx([0.75, 0.5, 0.25, 0.0])
    t.calibrate([100] * 4, [100] * 4)
    t.reset_filter()
    t.sense([5000] * 4, DT)
    assert t.f == [0, 0, 0, 0]


def test_normalisation_clamps():
    t = tracker()
    t.sense([-50, 2000, 500, 1000], DT)
    assert t.f == pytest.approx([0, 1, 0.5, 1])


def test_filter_follows_with_the_time_constant():
    t = tracker(tau=0.1)
    feed(t, 0, 0, 0, 0)
    feed(t, 1, 1, 1, 1, n=5)
    # five steps of 20 ms are one time constant
    assert t.lvl == pytest.approx(1 - math.exp(-1), abs=1e-9)


def test_errors_and_level():
    t = tracker()
    feed(t, 0.2, 0.6, 0.5, 0.5)
    assert t.ex == pytest.approx(0.5, abs=1e-5)
    assert t.ey == pytest.approx(0, abs=1e-9)
    assert t.lvl == pytest.approx(0.45)


def test_low_light_holds_both_axes():
    t = tracker()
    feed(t, 0.0, 0.1, 0.0, 0.0)
    assert t.lowlight
    assert t.command(45) == (0, 0)
    assert not t.active


def test_hysteresis_starts_at_dead_out_and_rests_at_dead_in():
    t = tracker()
    # ex of 0.04 sits between dead_in and dead_out, an idle axis stays idle
    feed(t, 0.48, 0.52, 0.5, 0.5)
    assert t.ex == pytest.approx(0.04, abs=1e-4)
    assert t.command(45) == (0, 0)
    t.reset_filter()
    feed(t, 0.45, 0.55, 0.5, 0.5)
    vx, vy = t.command(45)
    assert t.ax and vx > 0 and vy == 0
    # back to 0.04, the moving axis keeps going
    t.reset_filter()
    feed(t, 0.48, 0.52, 0.5, 0.5)
    assert t.command(45)[0] > 0
    # only below dead_in it comes to rest
    t.reset_filter()
    feed(t, 0.495, 0.505, 0.5, 0.5)
    assert t.command(45) == (0, 0)
    assert not t.ax


def test_pan_gain_grows_with_tilt_and_is_capped():
    t = tracker(kp=10, vmax=180)
    feed(t, 0.4, 0.6, 0.5, 0.5)
    ex = t.ex
    assert t.command(0)[0] == pytest.approx(10 * ex)
    assert t.command(60)[0] == pytest.approx(10 * ex / 0.5)
    assert t.command(80)[0] == pytest.approx(10 * ex / 0.35)


def test_pan_flips_behind_the_zenith():
    t = tracker()
    feed(t, 0.4, 0.6, 0.5, 0.5)
    assert t.command(45)[0] > 0
    assert t.command(135)[0] < 0


def test_zenith_band_freezes_pan_only():
    t = tracker()
    feed(t, 0.4, 0.6, 0.6, 0.4)
    vx, vy = t.command(93)
    assert vx == 0 and vy > 0
    assert t.command(97)[0] < 0


def test_speed_is_capped_at_vmax():
    t = tracker(kp=300, vmax=20)
    feed(t, 0.0, 1.0, 1.0, 0.0)
    assert t.command(30) == (20, 20)


def test_learned_signs_flip_the_errors():
    t = tracker()
    t.calibrate([0] * 4, [1000] * 4, sx=-1, sy=1)
    feed(t, 0.4, 0.6, 0.5, 0.5)
    assert t.ex_raw > 0 > t.ex
