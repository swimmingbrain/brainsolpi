from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Generator

from .modes import AUTO, STOP

if TYPE_CHECKING:
    from .engine import Engine

log = logging.getLogger(__name__)

DT = 0.02


class ActivityError(Exception):
    pass


class Activity:
    # borrows the head for a while, written as a generator that yields once per tick
    # so the steps read top to bottom and run just as well in fast simulated time

    kind = ""
    st = ""

    def __init__(self, eng: Engine):
        self.eng = eng
        self.id = ""
        self.req: tuple = STOP
        self.done = False
        self.ok = False
        self.error: str | None = None
        self.result = None
        self._gen: Generator | None = None
        self._callbacks: list[Callable[[Activity], None]] = []

    def run(self) -> Generator:
        yield

    def start(self) -> None:
        self._gen = self.run()

    def on_done(self, cb: Callable[[Activity], None]) -> None:
        self._callbacks.append(cb)

    def step(self) -> tuple:
        if self.done:
            return self.req
        try:
            next(self._gen)
        except StopIteration as e:
            self._finish(True, e.value, None)
        except ActivityError as e:
            self._finish(False, None, str(e))
        except Exception:
            log.exception("%s failed", self.kind)
            self._finish(False, None, "internal error, see the log")
        return self.req

    def cancel(self, why: str) -> None:
        if self.done:
            return
        if self._gen is not None:
            self._gen.close()
        self._finish(False, None, why)

    def _finish(self, ok: bool, result, error: str | None) -> None:
        self.done = True
        self.ok = ok
        self.result = result
        self.error = error
        self.req = STOP
        try:
            self.finished()
        except Exception:
            log.exception("%s finish failed", self.kind)
        for cb in self._callbacks:
            try:
                cb(self)
            except Exception:
                log.exception("%s callback failed", self.kind)

    def finished(self) -> None:
        pass

    # building blocks for the generators

    def wait(self, seconds: float) -> Generator:
        for _ in range(max(1, int(round(seconds / DT)))):
            yield

    def seek(self, pan: float, tilt: float, vmax: float | None = None, timeout: float = 30.0) -> Generator:
        lp, lt = self.eng.settings.pan_limits, self.eng.settings.tilt_limits
        pan = min(max(pan, lp[0]), lp[1])
        tilt = min(max(tilt, lt[0]), lt[1])
        self.req = ("seek", pan, tilt, vmax)
        waited = 0.0
        while True:
            yield
            if self.eng.motion.arrived(pan, tilt):
                return pan, tilt
            waited += DT
            if waited > timeout:
                raise ActivityError(f"could not reach pan {pan:.0f} tilt {tilt:.0f}")

    def lock(self, timeout: float = 20.0, hold: float = 0.6) -> Generator:
        # tracks with the closed loop until it has stayed locked for a moment
        self.req = AUTO
        held = 0.0
        dark = 0.0
        waited = 0.0
        while True:
            yield
            waited += DT
            cs = self.eng.cstate
            if cs == "lowlight":
                dark += DT
                if dark > 3.0:
                    raise ActivityError("not enough light to lock on")
            else:
                dark = 0.0
            if cs == "locked":
                held += DT
                if held >= hold:
                    return self.eng.motion.pan, self.eng.motion.tilt
            else:
                held = 0.0
            if waited > timeout:
                raise ActivityError(f"no lock within {timeout:.0f} s")

    def average(self, seconds: float, getter: Callable[[], float | None]) -> Generator:
        vals = []
        for _ in range(max(1, int(round(seconds / DT)))):
            yield
            v = getter()
            if v is not None:
                vals.append(v)
        if not vals:
            raise ActivityError("no readings")
        return sum(vals) / len(vals)
