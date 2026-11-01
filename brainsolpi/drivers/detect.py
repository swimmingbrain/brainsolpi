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


def _scored() -> list[tuple[int, str, str]]:
    # 0 a known usb serial chip, 1 a usb serial name like ttyACM0, 2 anything else
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
    return found


def candidates() -> list[tuple[str, str]]:
    # serial ports that could be the board, likely ones first, as (device, description)
    return [(dev, desc) for _, dev, desc in _scored()]


def likely_ports() -> list[str]:
    # only the ports that look like a board, the watch never opens anything else
    return [dev for score, dev, _ in _scored() if score < 2]


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


class BoardWatch:
    # while the sim stands in for a missing board, this looks for one plugged in later. a look
    # only reads the port list, a port is opened when it shows up and looks like a board

    # a fresh port gets this many looks, the first open can come before the port is ready
    TRIES = 2

    def __init__(self, lister: Callable[[], list[str]] = likely_ports, opener: Callable = open_serial,
                 timeout: float = IDENT_TIMEOUT + 1.0):
        self.lister = lister
        self.opener = opener
        self.timeout = timeout
        self.halt = threading.Event()
        # ports that are done with until they go away, None before the first look
        self.seen: set[str] | None = None
        self.tries: dict[str, int] = {}

    def check(self) -> tuple | None:
        # one look, returns (port, serial, ident) of a board that answered, its port still open
        ports = list(self.lister())
        if self.seen is None:
            # what is there at the start already had its chance when auto looked for a board
            self.seen = set(ports)
            return None
        # a port that went away and comes back is a new plug
        self.seen &= set(ports)
        self.tries = {p: n for p, n in self.tries.items() if p in ports}
        for port in ports:
            if port in self.seen or self.halt.is_set():
                continue
            got = probe(port, self.opener, self.timeout, self.halt)
            if got is not None:
                return got
            self.tries[port] = self.tries.get(port, 0) + 1
            if self.tries[port] >= self.TRIES:
                # another device or a board without the bridge firmware, opening it again
                # would only reset it, so it stays alone until it is plugged in again
                del self.tries[port]
                self.seen.add(port)
        return None


__all__ = ["BoardWatch", "Ident", "candidates", "find_board", "likely_ports", "probe"]
