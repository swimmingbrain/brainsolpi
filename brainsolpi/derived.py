from __future__ import annotations

import math

from .kinematics import Vec, dot, frame, norm
from .simmodel import BAFFLE

# panel power without a current sensor, 1 W per square metre of sunlight is about 110 lux
LUX_PER_WM2 = 110.0


def tangents(ex: float, ey: float, k: float = BAFFLE) -> tuple[float, float]:
    # inverts the shade wall model for small offsets, light from the right gives a positive tx
    tx = 2.0 * ex / (k * (1.0 + abs(ex)))
    ty = 2.0 * ey / (k * (1.0 + abs(ey)))
    return tx, ty


def offset_deg(ex: float, ey: float, k: float = BAFFLE) -> float:
    tx, ty = tangents(ex, ey, k)
    return math.degrees(math.atan(math.hypot(tx, ty)))


def light_estimate(pan: float, tilt: float, ex: float, ey: float) -> Vec:
    n, r, v = frame(pan, tilt)
    tx, ty = tangents(ex, ey)
    return norm((n[0] + tx * r[0] + ty * v[0], n[1] + tx * r[1] + ty * v[1], n[2] + tx * r[2] + ty * v[2]))


def gain(pan: float, tilt: float, ref_pan: float, ref_tilt: float, light: Vec | None = None) -> float:
    # ratio of light on the panel against a fixed panel at the reference pose,
    # without a light estimate the light is taken to be along the normal
    n = frame(pan, tilt)[0]
    n_ref = frame(ref_pan, ref_tilt)[0]
    if light is None:
        return 1.0 / max(dot(n, n_ref), 0.1)
    return max(dot(light, n), 0.0) / max(dot(light, n_ref), 0.1)


def panel_mw(lux: float | None, w_mm: float, h_mm: float, eff: float) -> float | None:
    if lux is None:
        return None
    area = (w_mm / 1000.0) * (h_mm / 1000.0)
    return lux / LUX_PER_WM2 * area * eff * 1000.0


def measured_mw(mv: int, ua: int) -> float:
    return mv * ua / 1e6
