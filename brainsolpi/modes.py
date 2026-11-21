from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from .brain import LOST_S
from .derived import LUX_PER_WM2
from .jsonio import r1
from .kinematics import clamp, pose_for, wrap180
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
        eng.sun = {"az": self.az, "el": el, "caz": caz, "t": round(when.timestamp(), 3)}
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


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _part(d: Any, key: str) -> dict:
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, dict) else {}


class Plan(Mode):
    # the pi decides nothing, the head does what the simulation of the planner on the brain
    # server does. the brain is asked about once a second, see brain.py
    name = "plan"
    # what the simlight command takes, a clear noon sun stays well below
    LUX_MAX = 200000.0
    AMB_MAX = 100000.0

    def __init__(self) -> None:
        self.seq = 0
        # tick time of the newest answer, or of the start before the first one
        self.since = 0.0
        self.pose: tuple[float, float] | None = None
        self.got = False
        self.up = False
        self.lost = False
        self.info: dict = {}
        self._saved_light: dict | None = None

    def enter(self, eng: Engine, now: float) -> None:
        if eng.driver.has_simlight:
            self._saved_light = eng.driver.light_state()
        # only answers from now on count, an old one may be from minutes ago
        self.seq = eng.brain.seq
        self.since = now
        eng.brain.wake()

    def leave(self, eng: Engine) -> None:
        if self._saved_light is not None:
            # the sim light goes back to where it was before the plan took it over
            eng.driver.set_light(**self._saved_light)
            self._saved_light = None
        eng.sun = None

    def take(self, eng: Engine, st: dict) -> None:
        # every field may be missing or null, what is there counts
        sun, pose, meas = _part(st, "sun"), _part(st, "pose"), _part(st, "meas")
        az, el = _num(sun.get("az_rel")), _num(sun.get("el"))
        up = sun.get("up")
        self.up = up if isinstance(up, bool) else (el is not None and el > 0.0)
        pan, tilt = _num(pose.get("pan")), _num(pose.get("tilt"))
        if pan is not None and tilt is not None:
            # the planner models a wider head than this one
            lp, lt = eng.settings.pan_limits, eng.settings.tilt_limits
            self.pose = (clamp(pan, *lp), clamp(tilt, *lt))
        now = _num(st.get("now"))
        if az is not None and el is not None:
            caz = _num(sun.get("az"))
            if caz is None:
                caz = (az + eng.settings.site["heading"]) % 360.0
            eng.sun = {"az": wrap180(az), "el": el, "caz": caz, "t": now if now is not None else eng.wall()}
        if eng.driver.has_simlight:
            # without the kit the lamp of the sim becomes the sun of the simulated moment, with the
            # real kit only the pose is mirrored
            light: dict = {"on": self.up}
            if az is not None:
                light["az"] = wrap180(az)
            if el is not None:
                light["el"] = clamp(el, 0.0, 90.0)
            dni, dhi = _num(meas.get("dni")), _num(meas.get("dhi"))
            if dni is not None:
                light["lux"] = clamp(dni * LUX_PER_WM2, 0.0, self.LUX_MAX)
            if dhi is not None:
                light["amb"] = clamp(dhi * LUX_PER_WM2, 0.0, self.AMB_MAX)
            eng.driver.set_light(**light)
        self.info = {
            "date": None, "time": None,
            "offset": r1(_num(pose.get("offset"))),
            "why": pose.get("why") if isinstance(pose.get("why"), str) else None,
            "speed": _num(st.get("speed")),
            "paused": st.get("paused") if isinstance(st.get("paused"), bool) else None,
        }
        day = _part(st, "day").get("date")
        if now is not None:
            off = _num(_part(st, "site").get("utc_offset_h")) or 0.0
            when = datetime.fromtimestamp(now, timezone(timedelta(hours=clamp(off, -23.0, 23.0))))
            self.info["time"] = when.strftime("%H:%M")
            self.info["date"] = when.date().isoformat()
        if isinstance(day, str) and day:
            self.info["date"] = day

    def step(self, eng: Engine, now: float) -> tuple:
        brain = eng.brain
        if brain.seq != self.seq:
            self.seq = brain.seq
            self.since = now
            self.take(eng, brain.plan or {})
            self.got = True
        self.lost = now - self.since > LOST_S
        if self.lost or (self.got and not self.up):
            # no answer for too long, or night in the simulation
            pan, tilt = eng.settings.park
            return ("seek", pan, tilt, None)
        if self.pose is None:
            # nothing known yet, the head holds where it is
            return STOP
        # between two answers and while the brain is away the head holds the last pose of the plan
        return ("seek", self.pose[0], self.pose[1], None)

    def frame(self, eng: Engine) -> dict:
        # what the page needs to explain the picture
        return {"ok": eng.brain.answers is True, "lost": self.lost, "up": self.up if self.got else None,
                "date": None, "time": None, "offset": None, "why": None, "speed": None, "paused": None, **self.info}


MODES = {m.name: m for m in (Auto, Manual, Sun, Hold, Park, Demo, Plan)}


def make_mode(name: str) -> Mode:
    return MODES[name]()
