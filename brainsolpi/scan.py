from __future__ import annotations

from typing import TYPE_CHECKING, Generator

from .activities import Activity

if TYPE_CHECKING:
    from .engine import Engine

PAN_RANGE = (-90.0, 90.0)
TILT_RANGE = (15.0, 165.0)
# the sensor filter needs about three time constants after a move, then a short average
SETTLE_S = 0.35
AVG_S = 0.2


def axis(lo: float, hi: float, step: float) -> list[float]:
    n = int((hi - lo) / step + 1e-9)
    return [lo + i * step for i in range(n + 1)]


class Scan(Activity):
    # visits a grid of poses in a serpentine and maps how bright the sky is along each normal

    kind = "scan"
    st = "scanning"

    def __init__(self, eng: Engine, step: float = 15.0):
        super().__init__(eng)
        self.step_deg = step
        self.pans = axis(*PAN_RANGE, step)
        self.tilts = axis(*TILT_RANGE, step)
        self.v: list[list[float | None]] = [[None] * len(self.pans) for _ in self.tilts]
        self.best: tuple[float, float, float] | None = None
        self.id = eng.store.new_id("scan", eng.wall())
        self.digits = 1 if eng.lux is not None else 3

    @property
    def cells(self) -> int:
        return len(self.pans) * len(self.tilts)

    def run(self) -> Generator:
        self.publish(False)
        for i, tilt in enumerate(self.tilts):
            cols = range(len(self.pans)) if i % 2 == 0 else range(len(self.pans) - 1, -1, -1)
            for j in cols:
                yield from self.seek(self.pans[j], tilt)
                yield from self.wait(SETTLE_S)
                val = yield from self.average(AVG_S, self.eng.light_value)
                self.v[i][j] = val
                if self.best is None or val > self.best[2]:
                    self.best = (self.pans[j], tilt, val)
                self.publish(False)
        if self.best is not None and self.eng.mode.name == "auto":
            # hand the head back facing the brightest cell so tracking starts right there
            yield from self.seek(self.best[0], self.best[1])
        return self.message(True)

    def message(self, done: bool) -> dict:
        d = self.digits
        best = None
        if self.best is not None:
            best = {"pan": self.best[0], "tilt": self.best[1], "v": round(self.best[2], d)}
        return {
            "t": "scan",
            "id": self.id,
            "pan": self.pans,
            "tilt": self.tilts,
            "v": [[None if x is None else round(x, d) for x in row] for row in self.v],
            "done": done,
            "best": best,
        }

    def publish(self, done: bool, extra: dict | None = None) -> None:
        msg = self.message(done)
        if extra:
            msg.update(extra)
        self.eng.last_scan = msg
        self.eng.sink.publish(msg, "scan")

    def finished(self) -> None:
        if self.ok:
            self.publish(True)
            b = self.best
            if b is not None:
                self.eng.event("info", f"scan done, brightest at pan {b[0]:.0f} tilt {b[1]:.0f}")
        else:
            self.publish(True, {"stopped": True, "err": self.error})
            self.eng.event("warn", f"scan ended early, {self.error}")
