from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .kinematics import pose_for
from .sun import position, relative_az, sun_light

if TYPE_CHECKING:
    from .engine import Engine

# what a mode or an activity asks of the motion limiter for one tick
AUTO = ("auto",)
STOP = ("vel", 0.0, 0.0)

# joystick rates fade to zero when the browser stops refreshing them
RATE_TTL = 0.4


class Mode:
    name = ""

    def enter(self, eng: Engine, now: float) -> None:
        pass

    def leave(self, eng: Engine) -> None:
        pass

    def step(self, eng: Engine, now: float) -> tuple:
        return STOP


class Auto(Mode):
    name = "auto"

    def step(self, eng: Engine, now: float) -> tuple:
        return AUTO


class Hold(Mode):
    name = "hold"


class Park(Mode):
    name = "park"

    def step(self, eng: Engine, now: float) -> tuple:
        pan, tilt = eng.settings.park
        return ("seek", pan, tilt, None)


class Manual(Mode):
    name = "manual"

    def __init__(self) -> None:
        self.target: tuple[float, float] | None = None
        self.rate = (0.0, 0.0)
        self.rate_t = -1e9

    def set_target(self, pan: float, tilt: float) -> None:
        self.target = (pan, tilt)
        self.rate = (0.0, 0.0)

    def set_rate(self, pan: float, tilt: float, now: float) -> None:
        self.target = None
        self.rate = (pan, tilt)
        self.rate_t = now

    def step(self, eng: Engine, now: float) -> tuple:
        if self.target is not None:
            return ("seek", self.target[0], self.target[1], None)
        if now - self.rate_t > RATE_TTL:
            self.rate = (0.0, 0.0)
        vmax = eng.params["vmax"]
        return ("vel", self.rate[0] * vmax, self.rate[1] * vmax)


class Sun(Mode):
    name = "sun"
    # the sun crawls, ten updates a second is plenty even in time lapse
    UPDATE_S = 0.1

    def __init__(self) -> None:
        self.az = 0.0
        self.el = -90.0
        self._next = -1e9
        self._saved_light: dict | None = None

    def enter(self, eng: Engine, now: float) -> None:
        if eng.driver.has_simlight:
            self._saved_light = eng.driver.light_state()
        self._next = -1e9

    def leave(self, eng: Engine) -> None:
        if self._saved_light is not None:
            # the sim light goes back to where it was before the sun took it over
            eng.driver.set_light(**self._saved_light)
            self._saved_light = None
        eng.sun = None

    def update(self, eng: Engine) -> None:
        when = eng.sun_clock.now()
        site = eng.settings.site
        caz, el = position(site["lat"], site["lon"], when)
        self.az = relative_az(caz, site["heading"])
        self.el = el
        eng.sun = {"az": self.az, "el": el, "caz": caz, "t": int(when.timestamp() * 1000)}
        if eng.driver.has_simlight:
            lux, amb = sun_light(el)
            eng.driver.set_light(az=self.az, el=min(max(el, 0.0), 90.0), on=el > 0.0, lux=lux, amb=amb)

    def step(self, eng: Engine, now: float) -> tuple:
        if now >= self._next:
            self._next = now + self.UPDATE_S
            self.update(eng)
        if self.el > 0.0:
            pan, tilt = pose_for(self.az, self.el)
            return ("seek", pan, tilt, None)
        # below the horizon the head rests in the park pose
        pan, tilt = eng.settings.park
        return ("seek", pan, tilt, None)


class Demo(Mode):
    name = "demo"
    VMAX = 25.0

    def __init__(self) -> None:
        self.t0 = 0.0

    def enter(self, eng: Engine, now: float) -> None:
        self.t0 = now

    def step(self, eng: Engine, now: float) -> tuple:
        # two slow sines with periods that never line up, so the path keeps changing
        t = now - self.t0
        pan = 55.0 * math.sin(2.0 * math.pi * t / 37.0)
        tilt = 90.0 + 50.0 * math.sin(2.0 * math.pi * t / 23.0 + 0.6)
        return ("seek", pan, tilt, self.VMAX)


MODES = {m.name: m for m in (Auto, Manual, Sun, Hold, Park, Demo)}


def make_mode(name: str) -> Mode:
    return MODES[name]()
