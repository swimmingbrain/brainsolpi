from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from .kinematics import Vec, direction, dot, frame

# the same formulas run in the browser simulation, keep both in step

# shade wall height over sensor width, shared with the controller and the ui
BAFFLE = 1.2

PHONE_SCENE = (900.0, 60.0)
SUN_SCENE = (80000.0, 9000.0)

SERVO_RATE = 400.0  # degrees per second
RAW_MAX = 8184
RAW_NOISE = 6.0
LUX_NOISE = 0.01
DARK_SHARE = 0.25


@dataclass
class Light:
    az: float = 25.0
    el: float = 40.0
    on: bool = True
    lux: float = PHONE_SCENE[0]
    amb: float = PHONE_SCENE[1]

    def as_dict(self) -> dict:
        return asdict(self)

    def vector(self) -> Vec:
        return direction(self.az, self.el)


def fractions(cn: float, cr: float, cv: float, k: float = BAFFLE) -> tuple[float, float, float, float]:
    # how much of each sensor the shade walls leave lit, order L R U D
    if cn <= 0.02:
        return 0.0, 0.0, 0.0, 0.0
    tx = cr / cn
    ty = cv / cn
    fl = _clamp01(1.0 - k * max(0.0, tx))
    fr = _clamp01(1.0 - k * max(0.0, -tx))
    fd = _clamp01(1.0 - k * max(0.0, ty))
    fu = _clamp01(1.0 - k * max(0.0, -ty))
    return fl, fr, fu, fd


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def illuminate(light: Light, pan: float, tilt: float) -> tuple[list[float], float]:
    # lux on each sensor and the direct part on the panel plane
    n, r, v = frame(pan, tilt)
    s = light.vector()
    cn, cr, cv = dot(s, n), dot(s, r), dot(s, v)
    lux0 = light.lux if light.on else 0.0
    e = lux0 * max(0.0, cn)
    f = fractions(cn, cr, cv)
    return [e * fk + light.amb for fk in f], e


def divider(lux: float) -> float:
    # photoresistor of 10 k at 10 lux over a 10 k resistor, brighter reads higher
    r = 10000.0 * (max(lux, 0.05) / 10.0) ** -0.7
    return 10000.0 / (r + 10000.0)


def raw_value(lux: float, rng: random.Random | None) -> int:
    noise = rng.gauss(0.0, RAW_NOISE) if rng is not None else 0.0
    raw = round(RAW_MAX * divider(lux) + noise)
    return 0 if raw < 0 else RAW_MAX if raw > RAW_MAX else int(raw)


def panel_lux(e: float, amb: float, rng: random.Random | None) -> float:
    noise = rng.gauss(0.0, LUX_NOISE) if rng is not None else 0.0
    return (e + amb) * (1.0 + noise)


def servo_step(angle: float, cmd: float, dt: float) -> float:
    step = SERVO_RATE * dt
    d = cmd - angle
    if d > step:
        d = step
    elif d < -step:
        d = -step
    return angle + d


def sample(light: Light, pan: float, tilt: float, rng: random.Random | None) -> tuple[list[int], float]:
    luxes, e = illuminate(light, pan, tilt)
    raws = [raw_value(x, rng) for x in luxes]
    return raws, panel_lux(e, light.amb, rng)


def ideal_calibration(lux0: float, amb: float) -> tuple[list[float], list[float]]:
    # the dividers squeeze bright light into the top few percent of the range, so the dark end
    # sits at a quarter of the lamp instead of full shade, that keeps the lock within a few
    # degrees and still sees a lamp up to about 75 degrees off the panel normal
    dark = float(round(RAW_MAX * divider(amb + DARK_SHARE * lux0)))
    bright = float(round(RAW_MAX * divider(lux0 + amb)))
    return [dark] * 4, [bright] * 4
