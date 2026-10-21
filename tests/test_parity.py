import math

import pytest

from brainsolpi.kinematics import angle_between, az_el, direction, dot, frame, pose_for
from brainsolpi.simmodel import Light

from .test_tracking import Loop

# the same scenarios and the same limits as the loop tests of the browser simulation,
# so both sides are held to one bar. the noise comes from a different generator, so the
# runs match in setup and tolerance, not number for number

LIGHTS = [(az, el) for az in range(-165, 181, 30) for el in (8, 30, 55, 75)]
STARTS = [(pan, tilt) for pan in (-75, -30, 0, 30, 75) for tilt in (12, 50, 88, 130, 168)]


def test_converges_on_every_visible_light_from_many_poses():
    runs = behind = 0
    worst = 0.0
    for az, el in LIGHTS:
        target = pose_for(az, el)
        # a light just outside the pan range can only be reached up to the limit
        reachable = abs(target[0]) <= 88 - 2
        for pan, tilt in STARTS:
            if dot(frame(pan, tilt)[0], direction(az, el)) < 0.15:
                continue
            loop = Loop(Light(az=az, el=el), (pan, tilt), seed=runs + 1).run(12)
            runs += 1
            if target[1] > 90 or tilt > 90:
                behind += 1
            assert loop.off < (7 if reachable else 8), f"light {az}/{el} from {pan}/{tilt}, {loop.off:.1f}"
            assert loop.state in ("locked", "limit"), f"light {az}/{el} from {pan}/{tilt}, {loop.state}"
            worst = max(worst, loop.off)
    assert runs > 400
    assert behind > 150


def test_gets_close_to_a_light_high_over_the_panel_inside_the_zenith_band():
    for az in (-120, -45, 10, 80, 160):
        loop = Loop(Light(az=az, el=86), (0, 60)).run(12)
        assert loop.off < 8
        assert loop.state == "locked"


def test_finds_a_light_off_to_the_side_of_the_flat_parked_panel():
    loop = Loop(Light(az=-80, el=20), (0, 90)).run(12)
    assert loop.off < 6


def test_turns_over_the_top_when_the_light_is_beyond_the_pan_range():
    seen = set()
    loop = Loop(Light(az=-150, el=35), (-60, 40))
    for _ in range(int(15 / 0.02)):
        loop.run(0.02)
        seen.add(loop.state)
    assert "moving" in seen
    assert loop.motion.tilt > 90
    assert loop.off < 6


def test_follows_a_light_over_the_top_at_5_degrees_per_second():
    start = pose_for(-60, 20)
    loop = Loop(Light(az=-60, el=20), start, seed=3)
    h = direction(-60, 0)
    worst = 0.0
    seen = set()
    for i in range(50 * 28):
        phi = math.radians(20 + 5 * i * 0.02)
        az, el = az_el((h[0] * math.cos(phi), h[1] * math.cos(phi), math.sin(phi)))
        loop.driver.light.az, loop.driver.light.el = az, el
        loop.run(0.02)
        seen.add(loop.state)
        if i * 0.02 > 2:
            worst = max(worst, loop.off)
    assert loop.motion.tilt > 140
    assert "moving" not in seen
    assert worst < 9


def test_holds_when_the_lamp_goes_out_and_the_room_is_dark():
    loop = Loop(Light(az=25, el=40, on=False, amb=5), (20, 30)).run(3)
    assert loop.state == "lowlight"
    assert loop.motion.pan == 20 and loop.motion.tilt == 30


def test_aim_estimate_matches_the_light_near_the_axis():
    # the same inverse of the shade wall model as offAngle and aimPose in the browser
    from brainsolpi.controller import aim_pose

    pan, tilt = aim_pose(0, 45, 0.0, 0.0, (-88, 88), (4, 176))
    assert pan == pytest.approx(0, abs=1e-9) and tilt == pytest.approx(45)
    pan, tilt = aim_pose(0, 60, 0.4, 0.0, (-88, 88), (4, 176))
    assert angle_between(frame(pan, tilt)[0], frame(0, 60)[0]) > 20
