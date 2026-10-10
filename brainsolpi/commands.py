from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from . import calibration
from .engine import CommandError
from .experiments import KINDS
from .kinematics import wrap180
from .modes import MODES
from .scan import Scan
from .sun import parse_when

if TYPE_CHECKING:
    from .auth import Auth
    from .engine import Engine

log = logging.getLogger(__name__)

OPEN_OPS = {"ping"}
ADMIN_OPS = {
    "mode", "target", "rate", "set", "site", "sun", "scan", "exp", "stop", "calib", "simlight", "rec", "sys",
}
CALIB_WAIT_S = 60.0


def _num(msg: dict, key: str, lo: float, hi: float, default: Any = ...) -> float:
    if key not in msg or msg[key] is None:
        if default is ...:
            raise CommandError(f"{key} is missing")
        return default
    v = msg[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise CommandError(f"{key} must be a number")
    if v < lo or v > hi:
        raise CommandError(f"{key} must be from {lo:g} to {hi:g}")
    return float(v)


def _bool(msg: dict, key: str, default: Any = ...) -> bool:
    if key not in msg or msg[key] is None:
        if default is ...:
            raise CommandError(f"{key} is missing")
        return default
    v = msg[key]
    if not isinstance(v, bool):
        raise CommandError(f"{key} must be true or false")
    return v


def _str(msg: dict, key: str) -> str:
    v = msg.get(key)
    if not isinstance(v, str) or not v:
        raise CommandError(f"{key} is missing")
    return v


class Commands:
    def __init__(self, engine: Engine, on_sys: Callable[[str], Any] | None = None):
        self.engine = engine
        self.on_sys = on_sys

    async def handle(self, msg: dict, admin: bool) -> dict:
        cid = msg.get("id")
        op = msg.get("op")
        try:
            if not isinstance(op, str):
                raise CommandError("op is missing")
            if op not in OPEN_OPS and op not in ADMIN_OPS:
                raise CommandError(f"unknown op {op}")
            if op in ADMIN_OPS and not admin:
                raise CommandError("admin only, unlock with the pin first")
            data = getattr(self, f"op_{op}")(msg)
            if asyncio.iscoroutine(data):
                data = await data
        except CommandError as e:
            return {"t": "ack", "id": cid, "ok": False, "err": str(e)}
        except ValueError as e:
            return {"t": "ack", "id": cid, "ok": False, "err": str(e)}
        except Exception:
            log.exception("command %s failed", op)
            return {"t": "ack", "id": cid, "ok": False, "err": "internal error, see the log"}
        out = {"t": "ack", "id": cid, "ok": True}
        if data is not None:
            out["data"] = data
        return out

    # open to everyone

    def op_ping(self, msg: dict) -> dict:
        return {"ts": int(self.engine.wall() * 1000)}

    # admin only

    def op_mode(self, msg: dict) -> dict:
        mode = msg.get("mode")
        if mode not in MODES:
            raise CommandError(f"mode must be one of {', '.join(MODES)}")
        self.engine.set_mode(mode)
        return {"mode": mode}

    def op_target(self, msg: dict) -> dict:
        pan = _num(msg, "pan", -180, 180)
        tilt = _num(msg, "tilt", -90, 270)
        pan, tilt = self.engine.set_target(pan, tilt)
        return {"pan": round(pan, 1), "tilt": round(tilt, 1)}

    def op_rate(self, msg: dict) -> None:
        # joystick packets come often, no data in the answer keeps them small
        pan = _num(msg, "pan", -1e6, 1e6)
        tilt = _num(msg, "tilt", -1e6, 1e6)
        self.engine.set_rate(pan, tilt)
        return None

    def op_set(self, msg: dict) -> dict:
        key = _str(msg, "key")
        if "value" not in msg:
            raise CommandError("value is missing")
        v = self.engine.set_value(key, msg["value"])
        return {"key": key, "value": v}

    def op_site(self, msg: dict) -> dict:
        lat = _num(msg, "lat", -90, 90)
        lon = _num(msg, "lon", -180, 180)
        heading = _num(msg, "heading", 0, 360)
        return self.engine.set_site(lat, lon, heading)

    def op_sun(self, msg: dict) -> dict:
        speed = _num(msg, "speed", 1, 3600, 1)
        start = None
        if msg.get("date"):
            if not isinstance(msg["date"], str):
                raise CommandError("date must be an iso date")
            try:
                start = parse_when(msg["date"], datetime.now(timezone.utc))
            except ValueError:
                raise CommandError("date must be an iso date like 2026-06-21 or 2026-06-21T06:00") from None
        self.engine.set_sun(speed, start)
        return {"speed": speed, "t": int(self.engine.sun_clock.now_ts() * 1000)}

    def op_scan(self, msg: dict) -> dict:
        step = _num(msg, "step", 5, 45, 15.0)
        act = self.engine.start_activity(Scan(self.engine, step))
        return {"id": act.id, "cells": act.cells}

    def op_exp(self, msg: dict) -> dict:
        kind = msg.get("kind")
        if kind not in KINDS:
            raise CommandError(f"kind must be one of {', '.join(KINDS)}")
        act = self.engine.start_activity(KINDS[kind](self.engine))
        return {"id": act.id, "kind": kind}

    def op_stop(self, msg: dict) -> dict:
        return {"stopped": self.engine.stop_activity()}

    def op_calib(self, msg: dict):
        step = msg.get("step")
        eng = self.engine
        if step not in calibration.STEPS:
            raise CommandError(f"step must be one of {', '.join(calibration.STEPS)}")
        if step in ("dark", "bright"):
            if msg.get("values") is not None:
                return calibration.set_values(eng, step, msg["values"])
            return self._wait_for(eng.start_activity(calibration.Capture(eng, step)))
        if step == "polarity":
            return self._wait_for(eng.start_activity(calibration.Polarity(eng)))
        if eng.activity is not None:
            raise CommandError(f"a {eng.activity.kind} is running, stop it first")
        if step == "zero":
            pan_us = _num(msg, "pan_us", 500, 2500, None)
            tilt_us = _num(msg, "tilt_us", 500, 2500, None)
            return calibration.zero(eng, pan_us, tilt_us)
        if step == "save":
            return calibration.save(eng)
        return calibration.reset(eng)

    async def _wait_for(self, act) -> dict:
        fut = asyncio.get_running_loop().create_future()

        def done(a):
            if not fut.done():
                fut.set_result(a)

        act.on_done(done)
        try:
            a = await asyncio.wait_for(fut, CALIB_WAIT_S)
        except asyncio.TimeoutError:
            raise CommandError("the calibration step took too long") from None
        if not a.ok:
            raise CommandError(a.error or "calibration failed")
        return a.result

    def op_simlight(self, msg: dict) -> dict:
        az = msg.get("az")
        az = wrap180(_num(msg, "az", -1e4, 1e4)) if az is not None else None
        el = _num(msg, "el", -90, 90, None)
        el = min(max(el, 0.0), 90.0) if el is not None else None
        on = _bool(msg, "on", None)
        lux = _num(msg, "lux", 0, 200000, None)
        amb = _num(msg, "amb", 0, 100000, None)
        return self.engine.set_simlight(az=az, el=el, on=on, lux=lux, amb=amb)

    def op_rec(self, msg: dict) -> dict:
        return self.engine.set_rec(_bool(msg, "on"))

    def op_sys(self, msg: dict) -> dict:
        action = msg.get("action")
        if action not in ("restart", "reboot", "shutdown"):
            raise CommandError("action must be restart, reboot or shutdown")
        if self.on_sys is None:
            raise CommandError("not available here")
        result = self.on_sys(action)
        if isinstance(result, str):
            raise CommandError(result)
        return {"action": action}
