from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from .jsonio import read_json, write_atomic

log = logging.getLogger(__name__)

MODES = ("auto", "manual", "sun", "hold", "park", "demo", "plan")

DEFAULT_SIM = {"az": 25.0, "el": 40.0, "on": True, "lux": 900.0, "amb": 60.0}
# a handful of boards is plenty, the list stays small
FLASHED_MAX = 20


def _is_num(v: Any) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)


def _num(v: Any, lo: float, hi: float, default: float) -> float:
    if not _is_num(v):
        return default
    return float(min(max(v, lo), hi))


class StateStore:
    # what the tracker remembers between runs, small and written rarely to spare the sd card

    def __init__(self, path: Path | None):
        self.path = path
        # the pose of the real head, only a board, brainsolpi centre and the doctor write it
        self.pan = 0.0
        self.tilt = 90.0
        # true once the servos really were at this pose, the tracker or brainsolpi centre sent it,
        # setpin also writes this file and must not make up a pose
        self.known = False
        # the sim keeps its own pose, where it left the simulated head says nothing about the real one
        self.simpose: tuple[float, float] | None = None
        self.mode = "auto"
        self.sim = dict(DEFAULT_SIM)
        self.tokens: list[list] = []
        # the boards the service wrote the bridge firmware to by itself, by usb ids and serial number
        self.flashed: list[str] = []
        self._saved: dict | None = None
        # set by the service so saves never block the control loop
        self.writer = None

    @classmethod
    def load(cls, path: Path | None) -> StateStore:
        s = cls(path)
        raw = read_json(path) if path is not None else None
        if raw:
            s.pan = _num(raw.get("pan"), -90.0, 90.0, 0.0)
            s.tilt = _num(raw.get("tilt"), 0.0, 180.0, 90.0)
            sp = raw.get("simpose")
            if "simpose" not in raw:
                # older files took the pose from whichever driver ran, mostly the sim, so it says
                # nothing about the real head. the sim goes on from there
                s.simpose = (s.pan, s.tilt)
            else:
                known = raw.get("known")
                s.known = known if isinstance(known, bool) else False
                if isinstance(sp, dict):
                    s.simpose = (_num(sp.get("pan"), -90.0, 90.0, 0.0), _num(sp.get("tilt"), 0.0, 180.0, 90.0))
            mode = raw.get("mode")
            s.mode = mode if mode in MODES else "auto"
            sim = raw.get("sim")
            if isinstance(sim, dict):
                s.sim = {
                    "az": _num(sim.get("az"), -180.0, 180.0, DEFAULT_SIM["az"]),
                    "el": _num(sim.get("el"), 0.0, 90.0, DEFAULT_SIM["el"]),
                    "on": bool(sim.get("on", True)),
                    "lux": _num(sim.get("lux"), 0.0, 200000.0, DEFAULT_SIM["lux"]),
                    "amb": _num(sim.get("amb"), 0.0, 100000.0, DEFAULT_SIM["amb"]),
                }
            toks = raw.get("tokens")
            if isinstance(toks, list):
                s.tokens = [
                    [t[0], float(t[1])]
                    for t in toks
                    if isinstance(t, list) and len(t) == 2 and isinstance(t[0], str)
                    and isinstance(t[1], (int, float))
                ]
            flashed = raw.get("flashed")
            if isinstance(flashed, list):
                s.flashed = [k for k in flashed if isinstance(k, str) and len(k) <= 200][-FLASHED_MAX:]
        s._saved = s.as_dict()
        return s

    def as_dict(self) -> dict:
        return {
            "pan": round(self.pan, 2),
            "tilt": round(self.tilt, 2),
            "known": self.known,
            "simpose": {"pan": round(self.simpose[0], 2), "tilt": round(self.simpose[1], 2)}
            if self.simpose is not None else None,
            "mode": self.mode,
            "sim": dict(self.sim),
            "tokens": [list(t) for t in self.tokens],
            "flashed": list(self.flashed[-FLASHED_MAX:]),
        }

    @property
    def changed(self) -> bool:
        return self.as_dict() != self._saved

    def save(self, force: bool = False) -> bool:
        data = self.as_dict()
        if not force and data == self._saved:
            return False
        if self.path is not None:
            if self.writer is not None:
                self.writer.write(self.path, data)
            else:
                try:
                    write_atomic(self.path, data)
                except OSError as e:
                    log.warning("cannot write %s: %s", self.path, e)
                    return False
        self._saved = data
        return True
