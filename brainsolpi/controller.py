from __future__ import annotations

import math

from .config import PARAM_BY_KEY

# floor for |cos tilt| in the pan gain, keeps pan responsive at steep tilt without blowing up
MIN_COS = 0.35
# below this the tilt error does not say which way to leave the zenith band
ESCAPE_EY = 0.002
# how far past the band edge an escape goes before normal control takes over, degrees
ESCAPE_MARGIN = 3.0


class Tracker:
    # the closed loop of the blueprint: normalise, filter, error, hysteresis, axis speeds

    def __init__(self, params: dict | None = None):
        self.dark = [0.0, 0.0, 0.0, 0.0]
        self.bright = [8184.0, 8184.0, 8184.0, 8184.0]
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
        self.escape = 0
        self._alpha_key: tuple[float, float] | None = None
        self._alpha = 0.0
        self.configure(params or {k: p.default for k, p in PARAM_BY_KEY.items()})

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
        self.sx = 1 if sx >= 0 else -1
        self.sy = 1 if sy >= 0 else -1

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
            span = self.bright[k] - self.dark[k]
            # works for either polarity, a dead sensor with no span reads as dark
            x = (raw[k] - self.dark[k]) / span if span != 0.0 else 0.0
            x = 0.0 if x < 0.0 else 1.0 if x > 1.0 else x
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
        if self.lowlight:
            self.ax = False
            self.ay = False
            self.escape = 0
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
        dz = abs(tilt - 90.0)
        in_band = dz < self.zenith_band
        if self.escape and (not self.ax or dz >= self.zenith_band + ESCAPE_MARGIN):
            self.escape = 0
        if not self.escape and self.ax and in_band and not self.ay:
            # pan cannot fix a sideways error at the zenith, so the panel tips out of the
            # band first, the side is kept until it is clear of the band or it would turn back
            if abs(ey) > ESCAPE_EY:
                self.escape = 1 if ey > 0.0 else -1
            else:
                self.escape = 1 if tilt > 90.0 else -1
        if self.ax and not in_band:
            # behind the zenith the pan direction flips, near it pan is undefined
            c = math.cos(math.radians(tilt))
            gx = math.copysign(1.0, c) / max(abs(c), MIN_COS) if c != 0.0 else 0.0
            vx = max(-vmax, min(vmax, self.kp * ex * gx))
        if self.escape:
            vy = self.escape * min(vmax, self.kp * abs(ex))
        elif self.ay:
            vy = max(-vmax, min(vmax, self.kp * ey))
        return vx, vy

    @property
    def active(self) -> bool:
        return self.ax or self.ay
