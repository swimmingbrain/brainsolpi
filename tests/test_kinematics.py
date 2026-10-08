import math

import pytest

from brainsolpi.kinematics import (
    ServoMap,
    angle_between,
    az_el,
    default_pan_map,
    default_tilt_map,
    direction,
    dot,
    frame,
    pose_for,
    wrap180,
)


def close(a, b, tol=1e-9):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def test_frame_matches_the_shared_formulas():
    p, t = 30.0, 50.0
    n, r, v = frame(p, t)
    sp, cp = math.sin(math.radians(p)), math.cos(math.radians(p))
    st, ct = math.sin(math.radians(t)), math.cos(math.radians(t))
    assert close(n, (sp * ct, cp * ct, st))
    assert close(r, (cp, -sp, 0.0))
    assert close(v, (-sp * st, -cp * st, ct))


@pytest.mark.parametrize("pan", [-90, -45, 0, 33, 90])
@pytest.mark.parametrize("tilt", [0, 20, 90, 135, 180])
def test_frame_is_orthonormal(pan, tilt):
    n, r, v = frame(pan, tilt)
    for a in (n, r, v):
        assert abs(dot(a, a) - 1) < 1e-12
    assert abs(dot(n, r)) < 1e-12
    assert abs(dot(n, v)) < 1e-12
    assert abs(dot(r, v)) < 1e-12


def test_known_poses():
    assert close(frame(0, 0)[0], (0, 1, 0))
    assert close(frame(0, 90)[0], (0, 0, 1))
    assert close(frame(90, 0)[0], (1, 0, 0))
    assert close(frame(0, 180)[0], (0, -1, 0))
    # the up vector of a vertical panel facing forward points to the sky
    assert close(frame(0, 0)[2], (0, 0, 1))


@pytest.mark.parametrize("az", [-180, -135, -91, -90, -30, 0, 25, 89, 90, 91, 150, 179])
@pytest.mark.parametrize("el", [0, 10, 40, 75, 89, 90])
def test_pose_for_points_the_normal_at_the_light(az, el):
    pan, tilt = pose_for(az, el)
    assert -90 <= pan <= 90
    assert 0 <= tilt <= 180
    assert angle_between(frame(pan, tilt)[0], direction(az, el)) < 1e-6


def test_rear_lights_tilt_over_the_top():
    assert pose_for(150, 30) == pytest.approx((-30, 150))
    assert pose_for(-120, 60) == pytest.approx((60, 120))
    assert pose_for(25, 40) == (25, 40)


@pytest.mark.parametrize("az", [-170, -60, 0, 45, 120])
@pytest.mark.parametrize("el", [0, 30, 80])
def test_az_el_round_trip(az, el):
    a, e = az_el(direction(az, el))
    assert a == pytest.approx(az, abs=1e-9)
    assert e == pytest.approx(el, abs=1e-9)


def test_wrap180():
    assert wrap180(190) == -170
    assert wrap180(-190) == 170
    assert wrap180(-180) == 180
    assert wrap180(540) == 180
    assert str(wrap180(-360)) == "0.0"


def test_default_servo_mapping():
    pm, tm = default_pan_map(), default_tilt_map()
    assert pm.to_us(0) == 1500
    assert pm.to_us(90) == 2500
    assert pm.to_us(-90) == 500
    assert tm.to_us(90) == 1500
    assert tm.to_us(0) == 500
    assert tm.to_us(180) == 2500


def test_servo_mapping_clamps_and_inverts():
    m = ServoMap(1480, 0, 10, -1)
    assert m.to_us(10) == 1380
    assert m.to_angle(1380) == pytest.approx(10)
    assert m.to_us(500) == 500
    assert m.to_us(-500) == 2500
    for a in (-40.0, -3.3, 0.0, 12.7, 60.0):
        assert m.to_angle(m.to_us(a)) == pytest.approx(a, abs=0.06)


def test_servo_map_from_settings_dict():
    m = ServoMap.from_dict({"centre_us": 1510, "angle0": 90, "us_per_deg": 11, "dir": 1})
    assert m.to_us(91) == 1521
