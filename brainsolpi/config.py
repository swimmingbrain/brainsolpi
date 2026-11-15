from __future__ import annotations

import copy
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .jsonio import read_json, write_atomic
from .simmodel import BAFFLE, PHONE_SCENE, ideal_calibration

log = logging.getLogger(__name__)

US_PER_DEG = 2000.0 / 180.0


@dataclass(frozen=True)
class Param:
    key: str
    default: float
    lo: float
    hi: float
    step: float
    integer: bool = False


# the tunables of the tracking controller, admins change them live
PARAMS: tuple[Param, ...] = (
    Param("kp", 90.0, 10.0, 300.0, 1.0),
    Param("vmax", 60.0, 5.0, 180.0, 1.0),
    Param("amax", 240.0, 20.0, 1000.0, 10.0),
    Param("dead_in", 0.025, 0.005, 0.2, 0.005),
    Param("dead_out", 0.05, 0.01, 0.3, 0.005),
    Param("tau", 0.12, 0.02, 1.0, 0.01),
    # the ambient light of a lit room alone gives a mean level of about 0.06, that counts as dark
    Param("min_light", 0.08, 0.0, 0.5, 0.01),
    Param("zenith_band", 6.0, 0.0, 20.0, 0.5),
    Param("ref_pan", 0.0, -90.0, 90.0, 1.0),
    Param("ref_tilt", 90.0, 0.0, 180.0, 1.0),
    Param("rate", 20, 5, 30, 1, integer=True),
)
PARAM_BY_KEY = {p.key: p for p in PARAMS}


class Num:
    def __init__(self, default: float, lo: float, hi: float, integer: bool = False):
        self.default = default
        self.lo = lo
        self.hi = hi
        self.integer = integer

    def check(self, v: Any) -> float | int:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError("must be a number")
        if v < self.lo or v > self.hi:
            raise ValueError(f"must be from {_fmt(self.lo)} to {_fmt(self.hi)}")
        if self.integer:
            return int(round(v))
        return float(v)


class Sign:
    def __init__(self, default: int = 1):
        self.default = default

    def check(self, v: Any) -> int:
        if v in (1, -1) and not isinstance(v, bool):
            return int(v)
        raise ValueError("must be 1 or -1")


class Flag:
    def __init__(self, default: bool = False):
        self.default = default

    def check(self, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        raise ValueError("must be true or false")


class Quad:
    def __init__(self, default: list[float], lo: float, hi: float):
        self.default = list(default)
        self.lo = lo
        self.hi = hi

    def check(self, v: Any) -> list[float]:
        if not isinstance(v, (list, tuple)) or len(v) != 4:
            raise ValueError("must be a list of four numbers")
        item = Num(0, self.lo, self.hi)
        return [float(item.check(x)) for x in v]


class Span:
    # a [lo, hi] pair that keeps some room between both ends
    def __init__(self, default: list[float], lo: float, hi: float, gap: float):
        self.default = list(default)
        self.lo = lo
        self.hi = hi
        self.gap = gap

    def check(self, v: Any) -> list[float]:
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            raise ValueError("must be a pair of numbers")
        item = Num(0, self.lo, self.hi)
        a, b = float(item.check(v[0])), float(item.check(v[1]))
        if b - a < self.gap:
            raise ValueError(f"needs at least {_fmt(self.gap)} degrees between both ends")
        return [a, b]


class Text:
    def __init__(self, default: str, maxlen: int):
        self.default = default
        self.maxlen = maxlen

    def check(self, v: Any) -> str:
        if not isinstance(v, str) or len(v) > self.maxlen:
            raise ValueError(f"must be text up to {self.maxlen} characters")
        return v


def _fmt(x: float) -> str:
    return f"{x:g}"


def servo_schema(angle0: float, lo: float, hi: float) -> dict:
    return {
        "centre_us": Num(1500.0, 500.0, 2500.0),
        "angle0": Num(angle0, lo, hi),
        "us_per_deg": Num(US_PER_DEG, 2.0, 30.0),
        "dir": Sign(1),
    }


def calib_schema(dark: list[float], bright: list[float]) -> dict:
    return {
        "dark": Quad(dark, 0.0, 8184.0),
        "bright": Quad(bright, 0.0, 8184.0),
        # loop signs learned by the polarity step, 1 when the wiring matches the docs
        "sx": Sign(1),
        "sy": Sign(1),
        "pan": servo_schema(0.0, -90.0, 90.0),
        "tilt": servo_schema(90.0, 0.0, 180.0),
        # true once someone saved the steps for this board, a real board without it starts in hold
        "saved": Flag(False),
    }


PROFILES = ("sim", "bridge")


def calib_defaults_for(profile: str) -> tuple[list[float], list[float]]:
    # both profiles start as if dark and bright had been taken under a phone light, that fits
    # a typical module well enough until the real steps run on the day the hardware arrives
    return ideal_calibration(*PHONE_SCENE)


def build_schema() -> dict:
    calib = {}
    for prof in PROFILES:
        dark, bright = calib_defaults_for(prof)
        calib[prof] = calib_schema(dark, bright)
    return {
        "name": Text("brainsol", 32),
        "params": {p.key: Num(p.default, p.lo, p.hi, p.integer) for p in PARAMS},
        "limits": {
            "pan": Span([-88.0, 88.0], -90.0, 90.0, 10.0),
            "tilt": Span([4.0, 176.0], 0.0, 180.0, 10.0),
        },
        "park": {"pan": Num(0.0, -90.0, 90.0), "tilt": Num(90.0, 0.0, 180.0)},
        "site": {
            # vienna with the front facing south, the same as the browser simulation
            "lat": Num(48.21, -90.0, 90.0),
            "lon": Num(16.37, -180.0, 180.0),
            "heading": Num(180.0, 0.0, 360.0),
        },
        "panel": {"w": Num(137.0, 10.0, 1000.0), "h": Num(85.0, 10.0, 1000.0), "eff": Num(0.15, 0.01, 0.5)},
        "serial": {
            "rate": Num(50, 1, 100, integer=True),
            "slew": Num(30, 1, 200, integer=True),
            # the service writes the bridge firmware to an uno r3 that does not answer, false stops that
            "autoflash": Flag(True),
        },
        "calib": calib,
        "auth": {"pin": Text("", 256)},
    }


def default_of(spec: Any) -> Any:
    if isinstance(spec, dict):
        return {k: default_of(v) for k, v in spec.items()}
    return copy.deepcopy(spec.default)


def validate(spec: Any, value: Any, where: str, problems: list[str]) -> Any:
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            if value is not None:
                problems.append(f"{where or 'settings'} is not an object, using defaults")
            return default_of(spec)
        out = {}
        for key, sub in spec.items():
            path = f"{where}.{key}" if where else key
            if key in value:
                out[key] = validate(sub, value[key], path, problems)
            else:
                out[key] = default_of(sub)
        return out
    try:
        return spec.check(value)
    except ValueError as e:
        problems.append(f"{where} {e}, using {spec.default!r}")
        return copy.deepcopy(spec.default)


# keys besides the params that the set command accepts
EXTRA_KEYS = {
    "pan_min": ("limits", "pan", 0),
    "pan_max": ("limits", "pan", 1),
    "tilt_min": ("limits", "tilt", 0),
    "tilt_max": ("limits", "tilt", 1),
    "park_pan": ("park", "pan", None),
    "park_tilt": ("park", "tilt", None),
    "panel_w": ("panel", "w", None),
    "panel_h": ("panel", "h", None),
    "panel_eff": ("panel", "eff", None),
}


class Settings:
    def __init__(self, path: Path | None = None, data: dict | None = None):
        self.path = path
        self.schema = build_schema()
        problems: list[str] = []
        self.data = validate(self.schema, data if data is not None else {}, "", problems)
        self._fix_relations(problems)
        self.problems = problems
        self.dirty = False
        # set by the service so saves never block the control loop
        self.writer = None

    @classmethod
    def load(cls, path: Path) -> Settings:
        raw = read_json(path)
        s = cls(path, raw)
        for p in s.problems:
            log.warning("settings: %s", p)
        if raw is None:
            # first start, write the defaults so people can see and edit them
            try:
                s.save()
            except OSError as e:
                log.warning("cannot write %s: %s", path, e)
        return s

    def save(self) -> None:
        if self.path is None:
            self.dirty = False
            return
        if self.writer is not None:
            self.writer.write(self.path, copy.deepcopy(self.data))
        else:
            write_atomic(self.path, self.data)
        self.dirty = False

    def flush(self) -> None:
        if self.dirty:
            self.save()

    def _fix_relations(self, problems: list[str]) -> None:
        p = self.data["params"]
        if p["dead_in"] >= p["dead_out"]:
            problems.append("params.dead_in must stay below dead_out, using defaults for both")
            p["dead_in"] = PARAM_BY_KEY["dead_in"].default
            p["dead_out"] = PARAM_BY_KEY["dead_out"].default
        lp = self.data["limits"]["pan"]
        lt = self.data["limits"]["tilt"]
        p["ref_pan"] = min(max(p["ref_pan"], lp[0]), lp[1])
        p["ref_tilt"] = min(max(p["ref_tilt"], lt[0]), lt[1])
        park = self.data["park"]
        park["pan"] = min(max(park["pan"], lp[0]), lp[1])
        park["tilt"] = min(max(park["tilt"], lt[0]), lt[1])

    # reading

    def param(self, key: str) -> float:
        return self.data["params"][key]

    @property
    def params(self) -> dict:
        return self.data["params"]

    @property
    def pan_limits(self) -> tuple[float, float]:
        a, b = self.data["limits"]["pan"]
        return a, b

    @property
    def tilt_limits(self) -> tuple[float, float]:
        a, b = self.data["limits"]["tilt"]
        return a, b

    @property
    def park(self) -> tuple[float, float]:
        return self.data["park"]["pan"], self.data["park"]["tilt"]

    @property
    def site(self) -> dict:
        return self.data["site"]

    @property
    def panel(self) -> dict:
        return self.data["panel"]

    @property
    def pin_hash(self) -> str:
        return self.data["auth"]["pin"]

    @pin_hash.setter
    def pin_hash(self, value: str) -> None:
        self.data["auth"]["pin"] = value
        self.dirty = True

    def calib(self, profile: str) -> dict:
        return copy.deepcopy(self.data["calib"][profile])

    def set_calib(self, profile: str, value: dict) -> None:
        problems: list[str] = []
        clean = validate(self.schema["calib"][profile], value, f"calib.{profile}", problems)
        if problems:
            raise ValueError("; ".join(problems))
        self.data["calib"][profile] = clean
        self.dirty = True

    def calib_default(self, profile: str) -> dict:
        return default_of(self.schema["calib"][profile])

    def params_info(self) -> dict:
        lp, lt = self.pan_limits, self.tilt_limits
        out = {}
        for p in PARAMS:
            lo, hi = p.lo, p.hi
            if p.key == "ref_pan":
                lo, hi = lp
            elif p.key == "ref_tilt":
                lo, hi = lt
            out[p.key] = {"v": self.data["params"][p.key], "min": lo, "max": hi, "step": p.step}
        return out

    def cfg(self) -> dict:
        d = self.data
        return {
            "limits": {"pan": list(d["limits"]["pan"]), "tilt": list(d["limits"]["tilt"])},
            "park": dict(d["park"]),
            "site": dict(d["site"]),
            "panel": dict(d["panel"]),
            "baffle": BAFFLE,
            "params": self.params_info(),
        }

    # changing

    def set_value(self, key: str, value: Any) -> float:
        if key in PARAM_BY_KEY:
            return self._set_param(key, value)
        if key in EXTRA_KEYS:
            return self._set_extra(key, value)
        raise ValueError(f"unknown setting {key}")

    def _set_param(self, key: str, value: Any) -> float:
        p = PARAM_BY_KEY[key]
        lo, hi = p.lo, p.hi
        if key == "ref_pan":
            lo, hi = self.pan_limits
        elif key == "ref_tilt":
            lo, hi = self.tilt_limits
        try:
            v = Num(p.default, lo, hi, p.integer).check(value)
        except ValueError as e:
            raise ValueError(f"{key} {e}") from None
        params = self.data["params"]
        if key == "dead_in" and v >= params["dead_out"]:
            raise ValueError("dead_in must stay below dead_out")
        if key == "dead_out" and v <= params["dead_in"]:
            raise ValueError("dead_out must stay above dead_in")
        params[key] = v
        self.dirty = True
        return v

    def _set_extra(self, key: str, value: Any) -> float:
        section, field, idx = EXTRA_KEYS[key]
        spec = self.schema[section][field]
        if idx is None:
            try:
                v = spec.check(value)
            except ValueError as e:
                raise ValueError(f"{key} {e}") from None
            if section == "park":
                lo, hi = self.pan_limits if field == "pan" else self.tilt_limits
                if not lo <= v <= hi:
                    raise ValueError(f"{key} must sit inside the limits {_fmt(lo)} to {_fmt(hi)}")
            self.data[section][field] = v
        else:
            pair = list(self.data[section][field])
            pair[idx] = value
            try:
                pair = spec.check(pair)
            except ValueError as e:
                raise ValueError(f"{key} {e}") from None
            self.data[section][field] = pair
            self._fix_relations([])
            v = pair[idx]
        self.dirty = True
        return v

    def set_site(self, lat: Any, lon: Any, heading: Any) -> dict:
        spec = self.schema["site"]
        try:
            site = {
                "lat": spec["lat"].check(lat),
                "lon": spec["lon"].check(lon),
                "heading": spec["heading"].check(heading),
            }
        except ValueError as e:
            raise ValueError(f"site {e}") from None
        self.data["site"] = site
        self.dirty = True
        return dict(site)
