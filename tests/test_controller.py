import math

import pytest

from brainsolpi.config import Settings
from brainsolpi.controller import STUCK_TIME, AutoLoop, Tracker, aim_pose, linear
from brainsolpi.kinematics import angle_between, frame
from brainsolpi.motion import Motion
from brainsolpi.simmodel import GAMMA, RAW_MAX, divider

DT = 0.02
DARK, BRIGHT = 196.0, 7862.0
PAN = (-88.0, 88.0)
TILT = (4.0, 176.0)


def raw_for(level, dark=DARK, bright=BRIGHT):
    # the reading that gives this level, the inverse of the linear normalisation
    flip = dark > bright
    lo = linear(RAW_MAX - dark if flip else dark)
    hi = linear(RAW_MAX - bright if flip else bright)
    q = (lo + level * (hi - lo)) ** GAMMA
    x = RAW_MAX * q / (1 + q)
    return RAW_MAX - x if flip else x


def tracker(**over):
    params = dict(Settings().params)
    params.update(over)
    t = Tracker(params)
    t.calibrate([DARK] * 4, [BRIGHT] * 4)
    return t


def feed(t, l, r, u, d, n=1):
    for _ in range(n):
        t.sense([raw_for(l), raw_for(r), raw_for(u), raw_for(d)], DT)


def test_linear_undoes_the_divider():
    # a level made linear grows in proportion to lux
    a = linear(RAW_MAX * divider(100))
    b = linear(RAW_MAX * divider(400))
    assert b / a == pytest.approx(4, rel=1e-9)


def test_levels_for_either_polarity():
    t = tracker()
    t.sense([raw_for(x) for x in (0.0, 0.25, 0.5, 1.0)], DT)
    assert t.f == pytest.approx([0, 0.25, 0.5, 1], abs=1e-9)
    t.calibrate([BRIGHT] * 4, [DARK] * 4)
    t.reset_filter()
    t.sense([raw_for(x, BRIGHT, DARK) for x in (0.0, 0.25, 0.5, 1.0)], DT)
    assert t.f == pytest.approx([0, 0.25, 0.5, 1], abs=1e-9)
    t.calibrate([100] * 4, [100] * 4)
    t.reset_filter()
    t.sense([5000] * 4, DT)
    assert t.f == [0, 0, 0, 0]


def test_levels_clamp():
    t = tracker()
    t.sense([0, RAW_MAX, raw_for(0.5), BRIGHT + 100], DT)
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


def test_a_small_sideways_error_does_not_hold_off_the_lock_in_the_band():
    t = tracker()
    # ex 0.04 is about 3.5 degrees, less than the band
    feed(t, 0.48, 0.52, 0.5, 0.5)
    t.ax = True
    t.command(90)
    assert not t.ax and not t.blocked
    # a big one stays as an error pan cannot fix there
    feed(t, 0.3, 0.7, 0.5, 0.5, n=50)
    t.command(90)
    assert t.ax and t.blocked


def test_speed_is_capped_at_vmax():
    t = tracker(kp=300, vmax=20)
    feed(t, 0.0, 1.0, 1.0, 0.0)
    assert t.command(30) == (20, 20)


def test_learned_signs_flip_the_errors():
    t = tracker()
    t.calibrate([DARK] * 4, [BRIGHT] * 4, sx=-1, sy=1)
    feed(t, 0.4, 0.6, 0.5, 0.5)
    assert t.ex_raw > 0 > t.ex


def test_aim_pose_faces_the_estimated_light():
    pan, tilt = aim_pose(0, 90, 0.3, 0.0, PAN, TILT)
    # light off to the right of a flat panel, the aim tips toward the right side of the sky
    assert pan > 45 and tilt < 90
    n = frame(pan, tilt)[0]
    assert angle_between(n, frame(0, 90)[0]) > 20


def test_stuck_in_the_band_aims_after_half_a_second():
    t = tracker()
    loop = AutoLoop(t)
    m = Motion(0, 90)
    states = []
    for _ in range(int(STUCK_TIME / DT) + 3):
        feed(t, 0.3, 0.7, 0.5, 0.5)
        states.append(loop.step(m, DT, 240, 60, PAN, TILT)[0])
    assert loop.aim is not None
    assert states[-1] == "moving"
    assert "tracking" in states[:5]


def test_pressing_a_pan_limit_aims_over_the_top():
    t = tracker()
    loop = AutoLoop(t)
    m = Motion(88, 30)
    for _ in range(int(STUCK_TIME / DT) + 3):
        feed(t, 0.2, 0.8, 0.5, 0.5)
        loop.step(m, DT, 240, 60, PAN, TILT)
    assert loop.aim is not None
    # the light is past the right limit, the rear pose reaches it with pan on the left
    assert loop.aim[1] > 90
