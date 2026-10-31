from __future__ import annotations

import copy
import math
from typing import TYPE_CHECKING, Generator

from .activities import Activity, ActivityError
from .drivers.protocol import RAW_MAX

if TYPE_CHECKING:
    from .engine import Engine

STEPS = ("dark", "bright", "zero", "polarity", "save", "reset")
# the steps that measure something, a first save without one of them keeps a default
MEASURED = ("dark", "bright", "zero", "polarity")
CAPTURE_S = 1.0
# less than this between dark and bright and the sensor cannot tell light from shade
MIN_SPAN = 50.0
WIGGLE = 4.0


class Capture(Activity):
    # averages the raw sums for a second, dark with the sensors covered, bright with a lamp on them

    kind = "calib"
    st = "calibrating"

    def __init__(self, eng: Engine, which: str):
        super().__init__(eng)
        self.which = which
        self.id = f"calib-{which}"

    def run(self) -> Generator:
        sums = [0.0, 0.0, 0.0, 0.0]
        n = 0
        for _ in range(int(round(CAPTURE_S / 0.02))):
            yield
            f = self.eng.frame
            if f is None:
                continue
            for k in range(4):
                sums[k] += f.raw[k]
            n += 1
        if n == 0:
            raise ActivityError("no frames from the board")
        values = [round(s / n, 1) for s in sums]
        calib = copy.deepcopy(self.eng.calib)
        calib[self.which] = values
        self.eng.set_calibration(calib, saved=False)
        self.eng.calib_done.add(self.which)
        return describe(calib) | {self.which: values}

    def finished(self) -> None:
        if self.ok:
            self.eng.event("info", f"calibration {self.which} captured, not saved yet")
        else:
            self.eng.event("warn", f"calibration {self.which} failed, {self.error}")


class Polarity(Activity):
    # turns each axis a few degrees each way under a fixed lamp and checks the error moves the
    # way the loop expects, a sensor pair wired the other way round flips that axis

    kind = "calib"
    st = "calibrating"

    def __init__(self, eng: Engine):
        super().__init__(eng)
        self.id = "calib-polarity"

    def run(self) -> Generator:
        eng = self.eng
        t = eng.tracker
        m = eng.motion
        if t.lowlight:
            raise ActivityError("needs light on the sensors, point a lamp at the head")
        band = eng.params["zenith_band"] + 5.0
        if abs(m.tilt - 90.0) < band:
            raise ActivityError(f"tilt the head at least {band:.0f} degrees away from flat first")
        lp, lt = eng.settings.pan_limits, eng.settings.tilt_limits
        p0 = min(max(m.pan, lp[0] + WIGGLE), lp[1] - WIGGLE)
        t0 = min(max(m.tilt, lt[0] + WIGGLE), lt[1] - WIGGLE)
        reads = []
        for dp, dt in ((WIGGLE, 0.0), (-WIGGLE, 0.0), (0.0, WIGGLE), (0.0, -WIGGLE)):
            yield from self.seek(p0 + dp, t0 + dt)
            yield from self.wait(0.5)
            ex = yield from self.average(0.3, lambda: t.ex_raw)
            ey = yield from self.average(0.3, lambda: t.ey_raw)
            reads.append((ex, ey))
        yield from self.seek(p0, t0)
        dx = reads[0][0] - reads[1][0]
        dy = reads[2][1] - reads[3][1]
        if abs(dx) < 0.005 or abs(dy) < 0.005:
            raise ActivityError("the sensors hardly changed, check the lamp and the wiring")
        c = math.cos(math.radians(t0))
        # turning right moves the lamp to the left of the panel, so ex should fall,
        # behind the zenith the pan direction is mirrored
        sx = 1 if dx * (1.0 if c > 0 else -1.0) < 0 else -1
        # tipping up moves the lamp below the panel centre, so ey should fall
        sy = 1 if dy < 0 else -1
        calib = copy.deepcopy(eng.calib)
        calib["sx"] = sx
        calib["sy"] = sy
        eng.set_calibration(calib, saved=False)
        eng.calib_done.add("polarity")
        return {"sx": sx, "sy": sy, "dx": round(dx, 4), "dy": round(dy, 4)}

    def finished(self) -> None:
        if self.ok:
            r = self.result
            self.eng.event("info", f"polarity learned, sx {r['sx']} sy {r['sy']}, not saved yet")
        else:
            self.eng.event("warn", f"polarity failed, {self.error}")


def describe(calib: dict) -> dict:
    dark, bright = calib["dark"], calib["bright"]
    span = [round(b - d, 1) for d, b in zip(dark, bright)]
    return {
        "dark": dark,
        "bright": bright,
        "span": span,
        # a sensor that reads lower in light than in shade, the normalisation handles it
        "inverted": [s < 0 for s in span],
        "weak": [abs(s) < MIN_SPAN for s in span],
    }


def set_values(eng: Engine, which: str, values) -> dict:
    if not isinstance(values, (list, tuple)) or len(values) != 4:
        raise ValueError("values must be four numbers")
    out = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= RAW_MAX:
            raise ValueError(f"values must be numbers from 0 to {RAW_MAX}")
        out.append(float(v))
    calib = copy.deepcopy(eng.calib)
    calib[which] = out
    eng.set_calibration(calib, saved=False)
    eng.calib_done.add(which)
    return describe(calib)


def zero(eng: Engine, pan_us=None, tilt_us=None) -> dict:
    # the pulses going out now become the centre, the head is meant to sit at pan 0 and flat
    if eng.servos_off and (pan_us is None or tilt_us is None):
        raise ValueError("the servos are still off, move the head to the front with the panel flat first")
    pm, tm = eng.pan_map, eng.tilt_map
    cur = (pm.to_us(eng.motion.pan), tm.to_us(eng.motion.tilt))
    pu = cur[0] if pan_us is None else pan_us
    tu = cur[1] if tilt_us is None else tilt_us
    for v in (pu, tu):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 500 <= v <= 2500:
            raise ValueError("pulses must be from 500 to 2500 us")
    calib = copy.deepcopy(eng.calib)
    calib["pan"]["centre_us"] = float(pu)
    calib["tilt"]["centre_us"] = float(tu)
    eng.set_calibration(calib, saved=False)
    eng.calib_done.add("zero")
    eng.event("info", f"servo centre set to {pu:.0f} and {tu:.0f} us, not saved yet")
    return {"pan_us": pu, "tilt_us": tu, "pan": round(eng.motion.pan, 1), "tilt": round(eng.motion.tilt, 1)}


def save(eng: Engine) -> dict:
    first = not eng.calib["saved"]
    eng.calib["saved"] = True
    eng.settings.set_calib(eng.profile, eng.calib)
    eng.settings.save()
    eng.calib_saved = True
    missing = [s for s in MEASURED if s not in eng.calib_done]
    if first and missing:
        # the defaults came from the simulated phone light, wrong signs would drive the head away
        eng.event("warn", f"calibration saved for the {eng.profile} profile, but {' and '.join(missing)} "
                          "did not run, those parts are still the defaults")
    else:
        eng.event("info", f"calibration saved for the {eng.profile} profile")
    eng.calibration_saved()
    return describe(eng.calib)


def reset(eng: Engine) -> dict:
    eng.set_calibration(eng.settings.calib_default(eng.profile), saved=False)
    eng.calib_done.clear()
    eng.event("info", "calibration back to the defaults, not saved yet")
    return describe(eng.calib)
