from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Iterable, NamedTuple

from .bridge import IDENT_TIMEOUT, open_serial, wait_ident
from .protocol import Ident

log = logging.getLogger(__name__)

# usb serial chips an uno clone may carry, the keyestudio board has an atmega16u2 like the original
KNOWN_VIDS = {0x2341: "Arduino", 0x2A03: "Arduino", 0x1A86: "CH340", 0x0403: "FTDI", 0x10C4: "CP210x"}
# the pi uart and bluetooth ports, never a board
SKIP = ("/dev/ttyS", "/dev/ttyAMA", "/dev/serial", "/dev/ttyprintk")
# vendor and product ids of an uno r3 whose usb chip is an atmega16u2 with the arduino firmware,
# arduino cc, arduino org and the genuino uno. the keyestudio board of the kit is sold as an uno
# r3 with that chip. a ch340, ftdi or cp210x adapter can sit in front of anything, so none of
# them is here
UNO_IDS = frozenset({(0x2341, 0x0043), (0x2A03, 0x0043), (0x2341, 0x0243)})
# a port that opened and said nothing for this long counts as silent, a board with other code on it
SILENT_S = 4.0


class UsbInfo(NamedTuple):
    vid: int
    pid: int
    serial: str | None

    @property
    def ids(self) -> str:
        return f"{self.vid:04x}:{self.pid:04x}"

    @property
    def uno(self) -> bool:
        return (self.vid, self.pid) in UNO_IDS


def usb_info(port: str) -> UsbInfo | None:
    # the usb ids and the serial number behind a serial port, None for a port without usb
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    real = os.path.realpath(port)
    for p in list_ports.comports():
        if p.device in (port, real) and p.vid is not None and p.pid is not None:
            return UsbInfo(p.vid, p.pid, p.serial_number or None)
    return None


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
          halt: threading.Event | None = None, silent: set[str] | None = None) -> tuple | None:
    # opens a port and waits for the identity line, the port stays open when it answers.
    # a port that opened fine and stayed quiet for a while goes into silent
    try:
        ser = opener(port)
    except Exception as e:
        log.debug("cannot open %s: %s", port, e)
        return None
    start = time.monotonic()
    quiet = False
    try:
        ident = wait_ident(ser, timeout, halt)
        quiet = ident is None and time.monotonic() - start >= min(timeout, SILENT_S) * 0.95
    except Exception as e:
        log.debug("%s failed while waiting: %s", port, e)
        ident = None
    if ident is None:
        try:
            ser.close()
        except Exception:
            pass
        if quiet and silent is not None:
            silent.add(port)
        return None
    return port, ser, ident


def find_board(timeout: float = 6.0, opener: Callable = open_serial, ports: list[str] | None = None,
               silent: set[str] | None = None) -> tuple | None:
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
        got = probe(port, opener, min(timeout, IDENT_TIMEOUT + 1.0), halt, silent)
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
    # a probe gives up within one read after the halt, so silent is complete once it returns
    end = time.monotonic() + 0.5
    for t in threads:
        t.join(max(0.0, end - time.monotonic()))
    with lock:
        done[0] = True
        return result[0] if result else None


class BoardWatch:
    # while the sim stands in for a missing board, this looks for one plugged in later. a look
    # only reads the port list, a port is opened when it shows up and looks like a board

    # a fresh port gets this many looks, the first open can come before the port is ready
    TRIES = 2

    def __init__(self, lister: Callable[[], list[str]] = likely_ports, opener: Callable = open_serial,
                 timeout: float = IDENT_TIMEOUT + 1.0, start: Iterable[str] | None = None,
                 silent: Iterable[str] = (), info: Callable[[str], UsbInfo | None] = usb_info):
        self.lister = lister
        self.opener = opener
        self.timeout = timeout
        self.info = info
        self.halt = threading.Event()
        # ports that are done with until they go away, None before the first look. auto passes
        # the ports it already probed at the start
        self.seen: set[str] | None = set(start) if start is not None else None
        self.tries: dict[str, int] = {}
        # ports that opened fine and stayed quiet, a board with other code on it perhaps
        self.silent: set[str] = set(silent)
        # silent ports that were already handed out once, until they go away
        self.told: set[str] = set()

    def check(self) -> tuple | None:
        # one look, returns (port, serial, ident) of a board that answered, its port still open
        ports = list(self.lister())
        if self.seen is None:
            # what is there at the start already had its chance when auto looked for a board
            self.seen = set(ports)
            return None
        # a port that went away and comes back is a new plug
        present = set(ports)
        self.seen &= present
        self.silent &= present
        self.told &= present
        self.tries = {p: n for p, n in self.tries.items() if p in present}
        for port in ports:
            if port in self.seen or self.halt.is_set():
                continue
            quiet: set[str] = set()
            got = probe(port, self.opener, self.timeout, self.halt, quiet)
            if got is not None:
                return got
            self.tries[port] = self.tries.get(port, 0) + 1
            if self.tries[port] >= self.TRIES:
                # another device or a board without the bridge firmware, opening it again
                # would only reset it, so it stays alone until it is plugged in again
                del self.tries[port]
                self.seen.add(port)
                self.silent |= quiet
        return None

    def next_silent(self) -> tuple[str, UsbInfo | None] | None:
        # a silent port nobody was told about yet, with its usb ids. each one comes up once per plug
        for port in sorted(self.silent - self.told):
            self.told.add(port)
            return port, self.info(port)
        return None


__all__ = ["BoardWatch", "Ident", "UNO_IDS", "UsbInfo", "candidates", "find_board", "likely_ports", "probe", "usb_info"]
