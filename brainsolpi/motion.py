from __future__ import annotations

import math

LIMIT_PAN = 1
LIMIT_TILT = 2

# a seek uses a bit less than the full deceleration so it never needs a hard stop
SEEK_DECEL = 0.8
# below this distance a seek slows down in proportion, seconds
SEEK_T = 0.1
# the last bit of a soft tail is skipped by putting the head right on the spot
SNAP_DEG = 0.05
SNAP_SPEED = 1.0
# a seek counts as there when it is this close and this slow
ARRIVE_DEG = SNAP_DEG
ARRIVE_SPEED = 0.5


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def seek_speed(err: float, vmax: float, amax: float) -> float:
    # the fastest speed that still stops at the target, with a soft tail at the end
    d = abs(err)
    if d < 1e-9:
        return 0.0
    v = min(vmax, math.sqrt(2.0 * SEEK_DECEL * amax * d), d / SEEK_T)
    return v if err > 0.0 else -v


def _brake(v: float, pos: float, lo: float, hi: float, amax: float) -> float:
    # cap the speed toward a soft limit so the head can still stop in time
    if v > 0.0:
        return min(v, seek_speed(hi - pos, v, amax)) if pos < hi else 0.0
    if v < 0.0:
        return max(v, seek_speed(lo - pos, -v, amax)) if pos > lo else 0.0
    return v


class Motion:
    # one limiter for every mode, so speed and acceleration caps hold everywhere
    # and a mode change keeps the current speed instead of jumping

    def __init__(self, pan: float = 0.0, tilt: float = 90.0):
        self.pan = pan
        self.tilt = tilt
        self.vp = 0.0
        self.vt = 0.0
        self.pushing = 0

    def step(
        self,
        vx: float,
        vy: float,
        dt: float,
        amax: float,
        pan_lim: tuple[float, float],
        tilt_lim: tuple[float, float],
    ) -> int:
        plo, phi = pan_lim
        tlo, thi = tilt_lim
        want_x, want_y = vx, vy
        vx = _brake(vx, self.pan, plo, phi, amax)
        vy = _brake(vy, self.tilt, tlo, thi, amax)
        dv = amax * dt
        self.vp += _clamp(vx - self.vp, -dv, dv)
        self.vt += _clamp(vy - self.vt, -dv, dv)
        pushing = 0
        p = self.pan + self.vp * dt
        # the braking tail ends a hair before the limit, snap onto it there
        if p <= plo + SNAP_DEG and self.vp <= 0.0:
            if p < plo or abs(self.vp) < SNAP_SPEED:
                p = plo
                self.vp = 0.0
            if p == plo and want_x < 0.0:
                pushing |= LIMIT_PAN
        elif p >= phi - SNAP_DEG and self.vp >= 0.0:
            if p > phi or abs(self.vp) < SNAP_SPEED:
                p = phi
                self.vp = 0.0
            if p == phi and want_x > 0.0:
                pushing |= LIMIT_PAN
        t = self.tilt + self.vt * dt
        if t <= tlo + SNAP_DEG and self.vt <= 0.0:
            if t < tlo or abs(self.vt) < SNAP_SPEED:
                t = tlo
                self.vt = 0.0
            if t == tlo and want_y < 0.0:
                pushing |= LIMIT_TILT
        elif t >= thi - SNAP_DEG and self.vt >= 0.0:
            if t > thi or abs(self.vt) < SNAP_SPEED:
                t = thi
                self.vt = 0.0
            if t == thi and want_y > 0.0:
                pushing |= LIMIT_TILT
        self.pan = p
        self.tilt = t
        self.pushing = pushing
        return pushing

    def seek(
        self,
        pan: float,
        tilt: float,
        vmax: float,
        dt: float,
        amax: float,
        pan_lim: tuple[float, float],
        tilt_lim: tuple[float, float],
    ) -> bool:
        pan = _clamp(pan, *pan_lim)
        tilt = _clamp(tilt, *tilt_lim)
        vx = seek_speed(pan - self.pan, vmax, amax)
        vy = seek_speed(tilt - self.tilt, vmax, amax)
        self.step(vx, vy, dt, amax, pan_lim, tilt_lim)
        # settle exactly on the target once the tail is tiny, saves an endless crawl
        if abs(pan - self.pan) < SNAP_DEG and abs(self.vp) < SNAP_SPEED:
            self.pan = pan
            self.vp = 0.0
        if abs(tilt - self.tilt) < SNAP_DEG and abs(self.vt) < SNAP_SPEED:
            self.tilt = tilt
            self.vt = 0.0
        return self.arrived(pan, tilt)

    def arrived(self, pan: float, tilt: float) -> bool:
        return (
            abs(pan - self.pan) < ARRIVE_DEG
            and abs(tilt - self.tilt) < ARRIVE_DEG
            and abs(self.vp) < ARRIVE_SPEED
            and abs(self.vt) < ARRIVE_SPEED
        )

    @property
    def still(self) -> bool:
        return abs(self.vp) < 0.5 and abs(self.vt) < 0.5

    def stop_now(self) -> None:
        self.vp = 0.0
        self.vt = 0.0
