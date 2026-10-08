from __future__ import annotations

import math
from dataclasses import dataclass

Vec = tuple[float, float, float]

D2R = math.pi / 180.0
R2D = 180.0 / math.pi


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(a: Vec) -> Vec:
    m = math.sqrt(dot(a, a))
    if m == 0.0:
        return (0.0, 0.0, 0.0)
    return (a[0] / m, a[1] / m, a[2] / m)


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def wrap180(a: float) -> float:
    a = (a + 180.0) % 360.0 - 180.0
    if a == -180.0:
        return 180.0
    # adding zero turns a negative zero into a plain one
    return a + 0.0


def frame(pan: float, tilt: float) -> tuple[Vec, Vec, Vec]:
    # normal, right and up of the panel, one set of sin and cos for all three
    sp, cp = math.sin(pan * D2R), math.cos(pan * D2R)
    st, ct = math.sin(tilt * D2R), math.cos(tilt * D2R)
    n = (sp * ct, cp * ct, st)
    r = (cp, -sp, 0.0)
    v = (-sp * st, -cp * st, ct)
    return n, r, v


def normal(pan: float, tilt: float) -> Vec:
    return frame(pan, tilt)[0]


def direction(az: float, el: float) -> Vec:
    sa, ca = math.sin(az * D2R), math.cos(az * D2R)
    se, ce = math.sin(el * D2R), math.cos(el * D2R)
    return (sa * ce, ca * ce, se)


def az_el(s: Vec) -> tuple[float, float]:
    x, y, z = norm(s)
    el = math.asin(clamp(z, -1.0, 1.0)) * R2D
    az = math.atan2(x, y) * R2D if (x or y) else 0.0
    return az, el


def angle_between(a: Vec, b: Vec) -> float:
    return math.acos(clamp(dot(norm(a), norm(b)), -1.0, 1.0)) * R2D


def pose_for(az: float, el: float) -> tuple[float, float]:
    # front half of the sky directly, the rear half by tilting over the top
    az = wrap180(az)
    if abs(az) <= 90.0:
        return az, el
    pan = az - 180.0 if az > 0 else az + 180.0
    return pan, 180.0 - el


def pose_toward(s: Vec) -> tuple[float, float]:
    return pose_for(*az_el(s))


@dataclass
class ServoMap:
    centre_us: float = 1500.0
    angle0: float = 0.0
    us_per_deg: float = 2000.0 / 180.0
    dir: int = 1

    @classmethod
    def from_dict(cls, d: dict) -> ServoMap:
        return cls(float(d["centre_us"]), float(d["angle0"]), float(d["us_per_deg"]), int(d["dir"]))

    def to_us(self, angle: float) -> int:
        us = self.centre_us + self.dir * (angle - self.angle0) * self.us_per_deg
        return int(round(clamp(us, 500.0, 2500.0)))

    def to_angle(self, us: float) -> float:
        return self.angle0 + (us - self.centre_us) / (self.dir * self.us_per_deg)


def default_pan_map() -> ServoMap:
    return ServoMap(1500.0, 0.0, 2000.0 / 180.0, 1)


def default_tilt_map() -> ServoMap:
    return ServoMap(1500.0, 90.0, 2000.0 / 180.0, 1)
