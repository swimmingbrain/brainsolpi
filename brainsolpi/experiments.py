from __future__ import annotations

import math
import statistics
from typing import TYPE_CHECKING, Generator

from .activities import DT, Activity, ActivityError
from .derived import offset_deg
from .jsonio import r1, r2, r3
from .modes import AUTO

if TYPE_CHECKING:
    from .engine import Engine

SETTLE_S = 0.4
AVG_S = 0.3


def fit_cosine(points: list[tuple[float, float]]) -> dict:
    # lux = amb + peak * max(0, cos(delta - offset)), the offset absorbs the small pointing
    # error left by the lock so a lock a few degrees off does not spoil the cosine law
    def solve(offset: float) -> tuple[float, float, float]:
        xs = [max(0.0, math.cos(math.radians(d - offset))) for d, _ in points]
        ys = [y for _, y in points]
        n = len(xs)
        mx = sum(xs) / n
        my = sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        peak = sxy / sxx if sxx > 0 else 0.0
        amb = my - peak * mx
        sse = sum((y - amb - peak * x) ** 2 for x, y in zip(xs, ys))
        return sse, amb, peak

    best = None
    for k in range(-80, 81):
        off = k * 0.25
        res = solve(off)
        if best is None or res[0] < best[0][0]:
            best = (res, off)
    coarse = best[1]
    for k in range(-25, 26):
        off = coarse + k * 0.01
        res = solve(off)
        if res[0] < best[0][0]:
            best = (res, off)
    (sse, amb, peak), off = best
    ys = [y for _, y in points]
    my = sum(ys) / len(ys)
    sst = sum((y - my) ** 2 for y in ys)
    r2 = 1.0 - sse / sst if sst > 0 else None
    return {"amb": amb, "peak": peak, "offset": off, "r2": r2}


class Experiment(Activity):
    kind = "exp"
    st = "measuring"
    exp = ""

    def __init__(self, eng: Engine):
        super().__init__(eng)
        self.id = eng.store.new_id(self.exp, eng.wall())
        self.phase = "start"
        self.progress = 0.0
        self.ts = int(eng.wall() * 1000)

    def report(self, phase: str, progress: float, result: dict | None = None, extra: dict | None = None) -> None:
        self.phase = phase
        self.progress = progress
        msg = {
            "t": "exp",
            "id": self.id,
            "kind": self.exp,
            "phase": phase,
            "progress": round(min(max(progress, 0.0), 1.0), 3),
            "result": result,
        }
        if extra:
            msg.update(extra)
        self.eng.sink.publish(msg, "exp")

    def lux(self) -> float | None:
        return self.eng.lux

    def need_lux(self) -> None:
        if self.eng.lux is None:
            raise ActivityError("this experiment needs the BH1750 light sensor")

    def base(self) -> dict:
        return {"id": self.id, "kind": self.exp, "ts": self.ts}

    def finished(self) -> None:
        if self.ok and self.result is not None:
            self.eng.store.save(self.result)
            self.report("done", 1.0, self.result)
            self.eng.event("info", f"{self.exp} experiment done")
        else:
            self.report("error", self.progress, None, {"err": self.error})
            self.eng.event("warn", f"{self.exp} experiment ended early, {self.error}")


class Cosine(Experiment):
    exp = "cosine"
    SPAN = 60
    STEP = 5

    def run(self) -> Generator:
        self.need_lux()
        self.report("lock", 0.0)
        pan, tilt = yield from self.lock()
        lo, hi = self.eng.settings.tilt_limits
        deltas = [d for d in range(-self.SPAN, self.SPAN + 1, self.STEP) if lo <= tilt + d <= hi]
        if len(deltas) < 8:
            raise ActivityError("the lock sits too close to a tilt limit for a sweep")
        points = []
        for k, d in enumerate(deltas):
            self.report("sweep", 0.1 + 0.85 * k / len(deltas))
            yield from self.seek(pan, tilt + d)
            yield from self.wait(SETTLE_S)
            lux = yield from self.average(AVG_S, self.lux)
            points.append((float(d), lux))
        self.report("fit", 0.95)
        fit = fit_cosine(points)
        yield from self.seek(pan, tilt)
        rows = []
        for d, y in points:
            model = fit["amb"] + fit["peak"] * max(0.0, math.cos(math.radians(d - fit["offset"])))
            rows.append([d, r1(y), r1(model)])
        res = self.base()
        res.update(
            {
                "lock": {"pan": r1(pan), "tilt": r1(tilt)},
                "fit": {"amb": r1(fit["amb"]), "peak": r1(fit["peak"]), "offset": r2(fit["offset"]), "r2": r3(fit["r2"])},
                "summary": {"r2": r3(fit["r2"]), "peak": r1(fit["peak"]), "amb": r1(fit["amb"])},
                "cols": ["delta", "lux", "fit"],
                "rows": rows,
            }
        )
        return res


class Compare(Experiment):
    exp = "compare"
    ROUNDS = 3

    def run(self) -> Generator:
        self.need_lux()
        p = self.eng.params
        rounds = []
        last_lock = None
        for i in range(self.ROUNDS):
            self.report("ref", i / self.ROUNDS)
            yield from self.seek(p["ref_pan"], p["ref_tilt"])
            yield from self.wait(SETTLE_S)
            ref = yield from self.average(0.5, self.lux)
            self.report("track", (i + 0.5) / self.ROUNDS)
            if last_lock is not None:
                # straight back to the last lock, the loop then only has to fine tune
                yield from self.seek(*last_lock)
            last_lock = yield from self.lock()
            tracked = yield from self.average(0.5, self.lux)
            rounds.append([i + 1, r1(ref), r1(tracked), r3(tracked / max(ref, 0.1))])
        gains = [r[3] for r in rounds]
        mean = sum(gains) / len(gains)
        res = self.base()
        res.update(
            {
                "gain": r3(mean),
                "spread": r3(max(gains) - min(gains)),
                "sd": r3(statistics.pstdev(gains)),
                "ref": {"pan": p["ref_pan"], "tilt": p["ref_tilt"]},
                "summary": {"gain": r3(mean), "spread": r3(max(gains) - min(gains))},
                "cols": ["round", "ref", "track", "gain"],
                "rows": rounds,
            }
        )
        return res


class Step(Experiment):
    exp = "step"
    OFFSET = 20.0
    MAX_S = 8.0

    def run(self) -> Generator:
        self.report("lock", 0.0)
        pan, tilt = yield from self.lock()
        lo, hi = self.eng.settings.pan_limits
        offset = self.OFFSET if pan + self.OFFSET <= hi else -self.OFFSET
        self.report("offset", 0.15)
        yield from self.seek(pan + offset, tilt)
        yield from self.wait(0.3)
        self.report("release", 0.2)
        m = self.eng.motion
        t = self.eng.tracker
        start = m.pan
        self.req = AUTO
        rows = []
        settle = None
        elapsed = 0.0
        while elapsed < self.MAX_S:
            yield
            elapsed += DT
            off = None if t.lowlight else offset_deg(t.ex, t.ey)
            rows.append([round(elapsed, 2), r2(m.pan), r2(m.tilt), r3(t.ex), r3(t.ey), r2(off)])
            if self.eng.cstate == "locked":
                settle = elapsed
                break
            if len(rows) % 25 == 0:
                self.report("release", 0.2 + 0.8 * elapsed / self.MAX_S)
        final = m.pan
        travel = start - final
        sign = 1.0 if travel > 0 else -1.0
        past = max(sign * (final - r[1]) for r in rows) if rows else 0.0
        overshoot = max(0.0, past)
        res = self.base()
        res.update(
            {
                "settle": r2(settle),
                "overshoot": r2(overshoot),
                "overshoot_pct": r1(100.0 * overshoot / abs(travel)) if abs(travel) > 0.5 else None,
                "offset": offset,
                "lock": {"pan": r1(pan), "tilt": r1(tilt)},
                "final": {"pan": r1(final), "tilt": r1(m.tilt)},
                "summary": {"settle": r2(settle), "overshoot": r2(overshoot)},
                "cols": ["t", "pan", "tilt", "ex", "ey", "off"],
                "rows": rows,
            }
        )
        return res


KINDS = {c.exp: c for c in (Cosine, Compare, Step)}
