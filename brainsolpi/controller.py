from __future__ import annotations

import math

from .config import PARAM_BY_KEY
from .derived import light_estimate, tangents
from .kinematics import clamp, pose_toward
from .motion import Motion
from .simmodel import GAMMA, RAW_MAX

# floor for |cos tilt| in the pan gain, keeps pan responsive at steep tilt without blowing up
MIN_COS = 0.35
# how long the loop may hold an error it cannot act on before it aims at the light, seconds
STUCK_TIME = 0.5


def linear(raw: float) -> float:
    # undoes the photoresistor divider so the reading grows in step with the light, a plain
    # (raw - dark) / (bright - dark) squeezes the last 20 degrees of error into a few counts
    x = min(max(raw, 1.0), RAW_MAX - 1.0)
    return (x / (RAW_MAX - x)) ** (1.0 / GAMMA)


class Tracker:
    # the closed loop of the blueprint: normalise, filter, error, hysteresis, axis speeds.
    # the levels are made linear in light first, the same as the browser simulation does

    def __init__(self, params: dict | None = None):
        self.dark = [0.0, 0.0, 0.0, 0.0]
        self.bright = [8184.0, 8184.0, 8184.0, 8184.0]
        self._lo = [0.0] * 4
        self._span = [0.0] * 4
        self._flip = [False] * 4
        self.sx = 1
        self.sy = 1
        self.f = [0.0, 0.0, 0.0, 0.0]
        self.seeded = False
        self.lvl = 0.0
        self.ex = 0.0
        self.ey = 0.0
        self.ex_raw = 0.0
        self.ey_raw = 0.0
        self.lowlight = True
        self.ax = False
        self.ay = False
        # a sideways error bigger than the zenith band, pan cannot act on it there
        self.blocked = False
        self._alpha_key: tuple[float, float] | None = None
        self._alpha = 0.0
        self.configure(params or {k: p.default for k, p in PARAM_BY_KEY.items()})
        self.calibrate(self.dark, self.bright)

    def configure(self, params: dict) -> None:
        self.kp = float(params["kp"])
        self.vmax = float(params["vmax"])
        self.dead_in = float(params["dead_in"])
        self.dead_out = float(params["dead_out"])
        self.tau = float(params["tau"])
        self.min_light = float(params["min_light"])
        self.zenith_band = float(params["zenith_band"])

    def calibrate(self, dark: list[float], bright: list[float], sx: int = 1, sy: int = 1) -> None:
        self.dark = [float(x) for x in dark]
        self.bright = [float(x) for x in bright]
        for k in range(4):
            # a module wired the other way round reads lower in light, it is mirrored first
            flip = self.dark[k] > self.bright[k]
            lo = linear(RAW_MAX - self.dark[k] if flip else self.dark[k])
            hi = linear(RAW_MAX - self.bright[k] if flip else self.bright[k])
            self._flip[k] = flip
            self._lo[k] = lo
            self._span[k] = hi - lo if self.dark[k] != self.bright[k] else 0.0
        self.sx = 1 if sx >= 0 else -1
        self.sy = 1 if sy >= 0 else -1

    def level(self, k: int, raw: float) -> float:
        span = self._span[k]
        if span == 0.0:
            return 0.0
        x = (linear(RAW_MAX - raw if self._flip[k] else raw) - self._lo[k]) / span
        return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x

    def reset_filter(self) -> None:
        self.seeded = False

    def _alpha_for(self, dt: float) -> float:
        key = (dt, self.tau)
        if key != self._alpha_key:
            self._alpha_key = key
            self._alpha = 1.0 - math.exp(-dt / self.tau)
        return self._alpha

    def sense(self, raw, dt: float) -> None:
        a = self._alpha_for(dt)
        f = self.f
        for k in range(4):
            x = self.level(k, raw[k])
            if self.seeded:
                f[k] += (x - f[k]) * a
            else:
                # the first sample seeds the filter so the start does not look like a dark room
                f[k] = x
        self.seeded = True
        lft, rgt, up, dn = f
        self.lvl = (lft + rgt + up + dn) * 0.25
        self.ex_raw = (rgt - lft) / (rgt + lft + 1e-6)
        self.ey_raw = (up - dn) / (up + dn + 1e-6)
        self.ex = self.sx * self.ex_raw
        self.ey = self.sy * self.ey_raw
        self.lowlight = self.lvl < self.min_light

    def command(self, tilt: float) -> tuple[float, float]:
        self.blocked = False
        if self.lowlight:
            self.ax = False
            self.ay = False
            return 0.0, 0.0
        ex, ey = self.ex, self.ey
        aex, aey = abs(ex), abs(ey)
        if self.ax:
            self.ax = aex >= self.dead_in
        else:
            self.ax = aex > self.dead_out
        if self.ay:
            self.ay = aey >= self.dead_in
        else:
            self.ay = aey > self.dead_out
        vmax = self.vmax
        vx = vy = 0.0
        if self.ay:
            vy = max(-vmax, min(vmax, self.kp * ey))
        if abs(tilt - 90.0) >= self.zenith_band:
            if self.ax:
                # behind the zenith the pan direction flips
                c = math.cos(math.radians(tilt))
                gx = math.copysign(1.0, c) / max(abs(c), MIN_COS) if c != 0.0 else 0.0
                vx = max(-vmax, min(vmax, self.kp * ex * gx))
        else:
            # pan rests in the band, an x error smaller than the band does not hold off the
            # lock, a bigger one is a light off to the side that tilt alone never finds
            tx, _ = tangents(ex, 0.0)
            self.blocked = math.degrees(math.atan(abs(tx))) > self.zenith_band
            if not self.blocked:
                self.ax = False
        return vx, vy

    @property
    def active(self) -> bool:
        return self.ax or self.ay


class AutoLoop:
    # the tracker on top of the shared motion limiter, plus one way out when the loop cannot
    # act on its error: pan pressed against a soft limit, or a light off to the side while the
    # panel lies in the zenith band. after half a second it aims once at where the errors say
    # the light is, the same rule as in the browser simulation, then it tracks on from there

    def __init__(self, tracker: Tracker):
        self.tracker = tracker
        self.stuck = 0.0
        self.aim: tuple[float, float] | None = None

    def reset(self) -> None:
        self.stuck = 0.0
        self.aim = None

    def step(self, m: Motion, dt: float, amax: float, vmax: float, lp, lt) -> tuple[str, int]:
        t = self.tracker
        if self.aim is not None:
            if m.seek(self.aim[0], self.aim[1], vmax, dt, amax, lp, lt):
                self.aim = None
                t.ax = t.ay = False
                return "tracking", 0
            return "moving", 0
        vx, vy = t.command(m.tilt)
        pushing = m.step(vx, vy, dt, amax, lp, lt)
        c = math.cos(math.radians(m.tilt))
        push = t.ex * (1.0 if c >= 0.0 else -1.0)
        pressing = (
            not t.lowlight
            and abs(t.ex) > t.dead_out
            and ((m.pan <= lp[0] and push < 0.0) or (m.pan >= lp[1] and push > 0.0))
        )
        self.stuck = self.stuck + dt if (pressing or t.blocked) else 0.0
        if self.stuck >= STUCK_TIME:
            self.stuck = 0.0
            self.aim = aim_pose(m.pan, m.tilt, t.ex, t.ey, lp, lt)
            t.ax = t.ay = False
            return "moving", pushing
        if t.lowlight:
            return "lowlight", pushing
        if pushing:
            return "limit", pushing
        if not t.active and m.still:
            return "locked", pushing
        return "tracking", pushing


def aim_pose(pan: float, tilt: float, ex: float, ey: float, lp, lt) -> tuple[float, float]:
    # the pose facing where the errors say the light is, far off the axis the shade model
    # saturates and the guess falls short, the loop does the rest from there
    p, t = pose_toward(light_estimate(pan, tilt, ex, ey))
    return clamp(p, *lp), clamp(t, *lt)
