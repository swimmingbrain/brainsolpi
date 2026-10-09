from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def clean(obj: Any) -> Any:
    # browsers cannot parse NaN or Infinity, missing numbers become null
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    return obj


def dumps(obj: Any) -> str:
    # the fast path covers almost every frame, the cleanup only runs when needed
    try:
        return json.dumps(obj, separators=(",", ":"), allow_nan=False)
    except ValueError:
        return json.dumps(clean(obj), separators=(",", ":"), allow_nan=False)


def r1(x: float | None) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return round(x, 1)


def r2(x: float | None) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return round(x, 2)


def r3(x: float | None) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return round(x, 3)


def read_json(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as e:
        log.warning("cannot read %s: %s", path, e)
        return None
    try:
        data = json.loads(text)
    except ValueError:
        # keep the broken file for a look later and start fresh
        bad = path.with_suffix(path.suffix + ".bad")
        try:
            os.replace(path, bad)
        except OSError:
            pass
        log.warning("%s was not valid json, moved it to %s", path, bad.name)
        return None
    return data if isinstance(data, dict) else None


def to_text(data: Any, indent: int | None = 2) -> str:
    return json.dumps(clean(data), indent=indent, allow_nan=False, ensure_ascii=False) + "\n"


def write_atomic(path: Path, data: Any, indent: int | None = 2) -> None:
    write_text_atomic(path, to_text(data, indent))


def write_text_atomic(path: Path, text: str) -> None:
    # write next to the target and swap, a power cut leaves the old or the new file, never half
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    try:
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                # windows refuses the swap while another process has the file open
                if attempt == 4:
                    raise
                time.sleep(0.05)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


class BackgroundWriter:
    # fsync on an sd card can take a long while, so the control loop hands files to a thread
    # and only the newest version of each file gets written

    def __init__(self) -> None:
        self._pending: dict[Path, str] = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="writer")
        self._thread.start()

    def write(self, path: Path, data: Any) -> None:
        text = to_text(data)
        with self._lock:
            self._pending[path] = text
            self._idle.clear()
        self._wake.set()

    def _run(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            while True:
                with self._lock:
                    if not self._pending:
                        self._idle.set()
                        break
                    path, text = self._pending.popitem()
                try:
                    write_text_atomic(path, text)
                except OSError as e:
                    log.warning("cannot write %s: %s", path, e)
            if self._stop:
                return

    def flush(self, timeout: float = 5.0) -> bool:
        return self._idle.wait(timeout)

    def close(self, timeout: float = 5.0) -> None:
        self._stop = True
        self._wake.set()
        self._thread.join(timeout)
