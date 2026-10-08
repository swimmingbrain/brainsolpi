from __future__ import annotations

import json
import logging
import math
import os
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


def write_atomic(path: Path, data: Any, indent: int | None = 2) -> None:
    # write next to the target and swap, a power cut leaves the old or the new file, never half
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    text = json.dumps(clean(data), indent=indent, allow_nan=False, ensure_ascii=False)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.write("\n")
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
