from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .bridge import IDENT_TIMEOUT, open_serial, wait_ident
from .protocol import Ident

log = logging.getLogger(__name__)

# usb serial chips an uno clone may carry, the keyestudio board has an atmega16u2 like the original
KNOWN_VIDS = {0x2341: "Arduino", 0x2A03: "Arduino", 0x1A86: "CH340", 0x0403: "FTDI", 0x10C4: "CP210x"}
# the pi uart and bluetooth ports, never a board
SKIP = ("/dev/ttyS", "/dev/ttyAMA", "/dev/serial", "/dev/ttyprintk")


def candidates() -> list[tuple[str, str]]:
    # serial ports that could be the board, likely ones first, as (device, description)
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    found = []
    for p in list_ports.comports():
        dev = p.device
        if dev.startswith(SKIP) or "bluetooth" in (p.description or "").lower():
            continue
        vid = getattr(p, "vid", None)
        known = vid in KNOWN_VIDS
        score = 0 if known else 1 if ("ACM" in dev or "USB" in dev) else 2
        desc = KNOWN_VIDS.get(vid) or p.description or ""
        found.append((score, dev, desc))
    found.sort()
    return [(dev, desc) for _, dev, desc in found]


def probe(port: str, opener: Callable = open_serial, timeout: float = IDENT_TIMEOUT,
          halt: threading.Event | None = None) -> tuple | None:
    # opens a port and waits for the identity line, the port stays open when it answers
    try:
        ser = opener(port)
    except Exception as e:
        log.debug("cannot open %s: %s", port, e)
        return None
    try:
        ident = wait_ident(ser, timeout, halt)
    except Exception as e:
        log.debug("%s failed while waiting: %s", port, e)
        ident = None
    if ident is None:
        try:
            ser.close()
        except Exception:
            pass
        return None
    return port, ser, ident


def find_board(timeout: float = 6.0, opener: Callable = open_serial, ports: list[str] | None = None) -> tuple | None:
    # probes every candidate at the same time, the first brainsol board wins
    if ports is None:
        ports = [dev for dev, _ in candidates()]
    if not ports:
        return None
    halt = threading.Event()
    result: list[tuple] = []
    lock = threading.Lock()
    done = [False]

    def worker(port: str) -> None:
        got = probe(port, opener, min(timeout, IDENT_TIMEOUT + 1.0), halt)
        if got is None:
            return
        with lock:
            if result or done[0]:
                # someone else won, or the caller stopped waiting
                got[1].close()
                return
            result.append(got)
            halt.set()

    threads = [threading.Thread(target=worker, args=(p,), daemon=True) for p in ports]
    for t in threads:
        t.start()
    end = time.monotonic() + timeout
    for t in threads:
        t.join(max(0.0, end - time.monotonic()))
    halt.set()
    with lock:
        done[0] = True
        return result[0] if result else None


__all__ = ["Ident", "candidates", "find_board", "probe"]
