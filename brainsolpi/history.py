from __future__ import annotations

import logging
import math
import queue
import threading
import time
from array import array
from pathlib import Path

log = logging.getLogger(__name__)

COLS = ("pan", "tilt", "lvl", "lux", "pmw", "off", "gain")
DIGITS = (1, 1, 3, 1, 2, 1, 3)
NAN = float("nan")


class History:
    # one row per second for the last six hours, flat float arrays keep it small on the pi

    def __init__(self, size: int = 6 * 3600):
        self.size = size
        self.cols = [array("d", [NAN]) * size for _ in COLS]
        self.count = 0
        self.head = 0
        self.last_t: int | None = None

    def push(self, t: float, values: tuple) -> None:
        sec = int(t)
        if self.last_t is not None:
            gap = sec - self.last_t
            if gap <= 0:
                # same second again, the newer value wins
                self._write((self.head - 1) % self.size, values)
                return
            # missed seconds stay empty so row i is always at t0 + i
            for _ in range(min(gap - 1, self.size)):
                self._append((None,) * len(COLS))
        self._append(values)
        self.last_t = sec

    def _append(self, values: tuple) -> None:
        self._write(self.head, values)
        self.head = (self.head + 1) % self.size
        if self.count < self.size:
            self.count += 1

    def _write(self, i: int, values: tuple) -> None:
        for col, v in zip(self.cols, values):
            col[i] = NAN if v is None else float(v)

    def span(self, seconds: float) -> dict:
        n = max(0, min(int(seconds), self.count))
        rows = []
        start = (self.head - n) % self.size
        for k in range(n):
            i = (start + k) % self.size
            row = []
            for col, d in zip(self.cols, DIGITS):
                x = col[i]
                row.append(None if math.isnan(x) else round(x, d))
            rows.append(row)
        t0 = None if self.last_t is None or n == 0 else self.last_t - n + 1
        return {"t0": t0, "dt": 1, "cols": list(COLS), "rows": rows}


REC_COLS = (
    "t", "mode", "st", "pan", "tilt", "vp", "vt", "L", "R", "U", "D",
    "raw_l", "raw_r", "raw_u", "raw_d", "ex", "ey", "lvl", "lux", "pmw", "off", "gain",
)


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if not math.isfinite(v):
            return ""
        return f"{v:.4g}" if abs(v) < 1e4 else f"{v:.1f}"
    return str(v)


class Recorder:
    # writes one csv row per tick while recording is on, a thread does the disk work

    MAX_SECONDS = 3600

    def __init__(self, folder: Path):
        self.folder = folder
        self.path: Path | None = None
        self.on = False
        self.rows = 0
        self._t0 = 0.0
        self._q: queue.SimpleQueue | None = None
        self._thread: threading.Thread | None = None

    def start(self, now: float) -> Path:
        if self.on:
            return self.path
        self.folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.path = self.folder / f"rec-{stamp}.csv"
        self._q = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._writer, args=(self.path, self._q), daemon=True, name="recorder")
        self._thread.start()
        self._q.put(",".join(REC_COLS))
        self._t0 = now
        self.rows = 0
        self.on = True
        return self.path

    def add(self, now: float, values: tuple) -> bool:
        # returns False once the recording hit its length cap and stopped
        if not self.on:
            return False
        t = now - self._t0
        if t > self.MAX_SECONDS:
            self.stop()
            return False
        self._q.put((t,) + values)
        self.rows += 1
        return True

    def stop(self) -> None:
        if not self.on:
            return
        self.on = False
        self._q.put(None)
        self._thread.join(timeout=2.0)

    def flush(self) -> None:
        # waits until the writer caught up, used before the file is served
        if self.on and self._q is not None:
            done = threading.Event()
            self._q.put(done)
            done.wait(timeout=2.0)

    @staticmethod
    def _writer(path: Path, q: queue.SimpleQueue) -> None:
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                while True:
                    item = q.get()
                    if item is None:
                        break
                    if isinstance(item, threading.Event):
                        f.flush()
                        item.set()
                        continue
                    if isinstance(item, str):
                        f.write(item + "\n")
                    else:
                        f.write(",".join(_cell(v) for v in item) + "\n")
        except OSError as e:
            log.warning("recording stopped, cannot write %s: %s", path, e)
            # keep draining so nobody waits on a dead writer
            while True:
                item = q.get()
                if item is None:
                    break
                if isinstance(item, threading.Event):
                    item.set()
