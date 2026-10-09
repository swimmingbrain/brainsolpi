from __future__ import annotations

import random

from ..kinematics import ServoMap, default_pan_map, default_tilt_map
from ..simmodel import Light, sample, servo_step
from .base import Driver
from .protocol import CAP_LUX, FLAG_ATTACHED, FLAG_SLEWING, FLAG_WATCHDOG, Frame, Ident, clamp_us

WATCHDOG_S = 1.5


class SimDriver(Driver):
    # a board that only exists in memory, it produces the same raw frames as the real one

    name = "sim"
    profile = "sim"
    has_simlight = True

    def __init__(
        self,
        light: Light | None = None,
        seed: int | None = None,
        rate: int = 50,
        pan_map: ServoMap | None = None,
        tilt_map: ServoMap | None = None,
    ):
        super().__init__()
        self.light = light or Light()
        self.rng = random.Random(seed)
        self.rate = rate
        # how the simulated servos really turn, the calibration in the settings may disagree
        self.pan_map = pan_map or default_pan_map()
        self.tilt_map = tilt_map or default_tilt_map()
        self.ident = Ident("sim", CAP_LUX)
        self.port = None
        self.attached = False
        self.pan = 0.0
        self.tilt = 90.0
        self.cmd_pan = 0.0
        self.cmd_tilt = 90.0
        self.cmd_us = (0, 0)
        self.seq = 0
        self.failed = False
        self._last_t: float | None = None
        self._next_frame: float | None = None
        self._last_move: float | None = None
        self._now = 0.0

    @property
    def link_ok(self) -> bool:
        return not self.failed

    def fail(self, failed: bool) -> None:
        # lets tests pull the plug on the sim, a replug boots a fresh board
        if failed and not self.failed:
            self.event("warn", "sim board unplugged")
        if not failed and self.failed:
            self.attached = False
            self._last_move = None
            self.event("info", "sim board back")
        self.failed = failed

    def move(self, pan_us: int, tilt_us: int) -> None:
        if self.failed:
            return
        pan_us, tilt_us = clamp_us(pan_us), clamp_us(tilt_us)
        self.cmd_us = (pan_us, tilt_us)
        self.cmd_pan = self.pan_map.to_angle(pan_us)
        self.cmd_tilt = self.tilt_map.to_angle(tilt_us)
        if not self.attached:
            # the first command attaches right at the commanded pulse, nothing twitches
            self.pan = self.cmd_pan
            self.tilt = self.cmd_tilt
            self.attached = True
        self._last_move = self._now

    def detach(self) -> None:
        self.attached = False

    def set_rate(self, hz: int) -> None:
        self.rate = max(1, min(100, int(hz)))

    def set_light(self, az=None, el=None, on=None, lux=None, amb=None) -> None:
        if az is not None:
            self.light.az = float(az)
        if el is not None:
            self.light.el = float(el)
        if on is not None:
            self.light.on = bool(on)
        if lux is not None:
            self.light.lux = float(lux)
        if amb is not None:
            self.light.amb = float(amb)

    def poll(self, now: float) -> Frame | None:
        self._now = now
        if self.failed:
            self._last_t = now
            return None
        dt = 0.0 if self._last_t is None else min(max(now - self._last_t, 0.0), 0.1)
        self._last_t = now
        if self.attached:
            self.pan = servo_step(self.pan, self.cmd_pan, dt)
            self.tilt = servo_step(self.tilt, self.cmd_tilt, dt)
        period = 1.0 / self.rate
        if self._next_frame is not None and now < self._next_frame - 0.25 * period:
            return None
        # keep the frame clock in step with the caller even when it runs a little late
        base = now if self._next_frame is None else max(self._next_frame, now - period)
        self._next_frame = base + period
        return self._frame(now)

    def _frame(self, now: float) -> Frame:
        raws, lux = sample(self.light, self.pan, self.tilt, self.rng)
        flags = 0
        pan_us = tilt_us = 0
        if self.attached:
            flags |= FLAG_ATTACHED
            pan_us = self.pan_map.to_us(self.pan)
            tilt_us = self.tilt_map.to_us(self.tilt)
            if abs(self.pan - self.cmd_pan) > 0.05 or abs(self.tilt - self.cmd_tilt) > 0.05:
                flags |= FLAG_SLEWING
        if self._last_move is not None and now - self._last_move > WATCHDOG_S:
            flags |= FLAG_WATCHDOG
        self.seq = (self.seq + 1) & 0xFFFF
        self.frames += 1
        lux10 = int(round(max(lux, 0.0) * 10.0))
        return Frame(self.seq, (raws[0], raws[1], raws[2], raws[3]), lux10, 0, 0, pan_us, tilt_us, flags, now)

    def light_state(self) -> dict:
        return self.light.as_dict()
