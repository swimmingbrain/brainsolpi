import statistics

import pytest

from brainsolpi.config import Settings
from brainsolpi.controller import Tracker
from brainsolpi.drivers.sim import SimDriver
from brainsolpi.kinematics import ServoMap, angle_between, frame
from brainsolpi.motion import Motion
from brainsolpi.simmodel import Light

DT = 0.02


class Loop:
    # the controller closed over the sim driver, nothing else in between

    def __init__(self, light, start, seed=7, **over):
        self.settings = Settings()
        self.params = dict(self.settings.params)
        self.params.update(over)
        cal = self.settings.calib("sim")
        self.tracker = Tracker(self.params)
        self.tracker.calibrate(cal["dark"], cal["bright"])
        self.motion = Motion(*start)
        self.driver = SimDriver(light=light, seed=seed)
        self.pan_map = ServoMap.from_dict(cal["pan"])
        self.tilt_map = ServoMap.from_dict(cal["tilt"])
        self.t = 0.0
        self.frame = None
        self.poses = []
        self.flags = 0

    def run(self, seconds):
        for _ in range(int(round(seconds / DT))):
            f = self.driver.poll(self.t)
            if f is not None:
                self.frame = f
            if self.frame is not None:
                self.tracker.sense(self.frame.raw, DT)
                vx, vy = self.tracker.command(self.motion.tilt)
                self.flags = self.motion.step(
                    vx, vy, DT, self.params["amax"], self.settings.pan_limits, self.settings.tilt_limits
                )
            self.driver.move(self.pan_map.to_us(self.motion.pan), self.tilt_map.to_us(self.motion.tilt))
            self.poses.append((self.motion.pan, self.motion.tilt))
            self.t += DT
        return self

    @property
    def off(self):
        return angle_between(frame(self.driver.pan, self.driver.tilt)[0], self.driver.light.vector())

    @property
    def locked(self):
        return not self.tracker.active and self.motion.still and not self.tracker.lowlight


CASES = [
    # light az, el, start pan, tilt
    (25, 40, 0, 90),
    (25, 40, 0, 45),
    (25, 40, -40, 30),
    (-60, 20, 0, 90),
    (-60, 20, 0, 45),
    (70, 60, 0, 90),
    (70, 60, -40, 30),
    (0, 5, 0, 45),
    (45, 10, 0, 45),
    (-20, 70, 0, 45),
    (-75, 35, -30, 60),
    (60, 15, 20, 20),
    # behind the zenith, the head goes over the top
    (150, 60, 0, 90),
    (150, 60, 30, 120),
    (-130, 30, 0, 90),
    (-130, 30, 30, 120),
    (100, 45, 0, 90),
    (170, 20, 0, 150),
    # close to the zenith
    (10, 88, 0, 45),
    (100, 85, 0, 60),
    (-90, 80, 0, 90),
]


@pytest.mark.parametrize("az,el,pan,tilt", CASES)
def test_converges_and_locks(az, el, pan, tilt):
    loop = Loop(Light(az=az, el=el), (pan, tilt)).run(12)
    assert loop.locked, (loop.motion.pan, loop.motion.tilt, loop.tracker.ex, loop.tracker.ey)
    assert loop.off < 9.0


@pytest.mark.parametrize("az,el,pan,tilt", [(25, 40, 0, 90), (150, 60, 0, 90), (-20, 70, 0, 45)])
def test_no_hunting_once_locked(az, el, pan, tilt):
    loop = Loop(Light(az=az, el=el), (pan, tilt)).run(10)
    assert loop.locked
    loop.poses.clear()
    loop.run(5)
    pans = [p for p, _ in loop.poses]
    tilts = [t for _, t in loop.poses]
    assert statistics.pstdev(pans) < 0.1
    assert statistics.pstdev(tilts) < 0.1
    assert max(pans) - min(pans) < 0.5
    assert max(tilts) - min(tilts) < 0.5


def test_a_moving_light_is_followed():
    loop = Loop(Light(az=-40, el=30), (-40, 30)).run(2)
    for step in range(60):
        loop.driver.light.az = -40 + step
        loop.run(0.25)
    loop.run(3)
    assert loop.locked
    assert loop.off < 9.0


def test_limits_are_respected():
    # a light at pan 95 lies past the soft limit, the head waits at the limit
    loop = Loop(Light(az=95, el=5), (60, 20)).run(10)
    pans = [p for p, _ in loop.poses]
    tilts = [t for _, t in loop.poses]
    assert max(pans) <= 88.0
    assert min(tilts) >= 4.0
    assert loop.motion.pan == 88.0
    assert loop.flags != 0


def test_low_light_holds_the_pose():
    loop = Loop(Light(az=60, el=30, on=False), (0, 45)).run(5)
    assert loop.tracker.lowlight
    assert loop.poses[-1] == (0, 45)
    # switching the lamp on wakes the tracker up
    loop.driver.light.on = True
    loop.run(10)
    assert loop.locked
    assert loop.off < 9.0


def test_a_light_far_behind_the_panel_is_not_chased():
    loop = Loop(Light(az=180, el=10), (0, 30)).run(5)
    assert loop.tracker.lowlight
    assert loop.poses[-1] == (0, 30)


@pytest.mark.parametrize("az", [-90, -60, 90, 120, 0, 180])
@pytest.mark.parametrize("el", [70, 78, 83])
def test_sideways_lights_near_the_zenith_from_the_park_pose(az, el):
    loop = Loop(Light(az=az, el=el), (0, 90)).run(15)
    assert loop.locked, (loop.motion.pan, loop.motion.tilt, loop.tracker.ex, loop.tracker.ey)
    assert loop.off < 9.0
