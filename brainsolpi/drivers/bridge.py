from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from typing import Callable

from .base import Driver
from .protocol import (
    Frame,
    Ident,
    LineReader,
    Notice,
    cmd_move,
    cmd_query,
    cmd_rate,
    cmd_slew,
    parse_line,
)

log = logging.getLogger(__name__)

# opening the port resets the uno, it boots and says who it is within about two seconds
IDENT_TIMEOUT = 5.0
QUERY_AFTER = 2.5
# a question without an answer is asked again after this long
REASK_S = 1.0
# caps only show in answers to ?, so ask now and then to see a sensor plugged in later
QUERY_EVERY = 5.0
# no bytes at all for this long and the board is gone even if the port still looks open
SILENT_S = 2.0
# after a reconnect a half line from before can still come back as one E,1
GRACE_S = 2.0
BACKOFF = (0.5, 1.0, 2.0, 4.0, 5.0)
READ_TIMEOUT = 0.02


class NoBoard(Exception):
    pass


def open_serial(port: str):
    import serial

    return serial.Serial(port, 115200, timeout=READ_TIMEOUT, write_timeout=0.5)


def wait_ident(ser, timeout: float = IDENT_TIMEOUT, halt: threading.Event | None = None) -> Ident | None:
    # reads until the identity line shows up, asks with ? when the board stays quiet
    reader = LineReader()
    start = time.monotonic()
    asked_at: float | None = None
    while time.monotonic() - start < timeout:
        if halt is not None and halt.is_set():
            return None
        data = ser.read(ser.in_waiting or 1)
        now = time.monotonic()
        ask = False
        for line in reader.feed(data):
            msg = parse_line(line)
            if isinstance(msg, Ident):
                return msg
            if isinstance(msg, Frame) and asked_at is None:
                # frames without an identity, the board did not reset on open, just ask
                ask = True
            elif isinstance(msg, Notice) and asked_at is not None:
                # our ? was glued to a half line left from an earlier session and came back
                # as E,1, the board takes the next full line
                ask = True
        if asked_at is None and now - start > QUERY_AFTER:
            ask = True
        elif asked_at is not None and now - asked_at > REASK_S:
            ask = True
        if ask:
            ser.write(cmd_query())
            asked_at = now
    return None


class BridgeDriver(Driver):
    # talks to the uno from one thread, the event loop only swaps references with it,
    # so a slow or vanished serial port can never block the control loop

    name = "bridge"

    def __init__(
        self,
        port: str | None = None,
        *,
        opener: Callable = open_serial,
        finder: Callable | None = None,
        initial: tuple | None = None,
        rate: int = 50,
        slew: int = 30,
        profile: str = "bridge",
    ):
        super().__init__()
        self.want_port = port
        self.port = port
        self.opener = opener
        self.finder = finder
        self.profile = profile
        self._initial = initial
        self.rate = rate
        self.slew = slew
        self._link = False
        self._latest: Frame | None = None
        self._given: Frame | None = None
        self._move: tuple[int, int] | None = None
        self._move_n = 0
        self._cmds: deque[bytes] = deque()
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self.dropped = 0
        self.bad = 0
        self.reconnects = 0
        self.connected_at = 0.0
        self._last_seq: int | None = None
        self._last_notice = 0.0

    # the loop side

    async def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="bridge")
        self._thread.start()

    async def stop(self) -> None:
        self._halt.set()
        if self._thread is not None:
            await asyncio.get_running_loop().run_in_executor(None, self._thread.join, 3.0)

    def stop_sync(self) -> None:
        self._halt.set()
        if self._thread is not None:
            self._thread.join(3.0)

    def start_sync(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="bridge")
        self._thread.start()

    @property
    def link_ok(self) -> bool:
        return self._link

    def poll(self, now: float) -> Frame | None:
        f = self._latest
        if f is None or f is self._given:
            return None
        self._given = f
        return f

    def latest(self) -> Frame | None:
        return self._latest

    def move(self, pan_us: int, tilt_us: int) -> None:
        self._move = (int(pan_us), int(tilt_us))
        self._move_n += 1

    def detach(self) -> None:
        self._cmds.append(b"D\n")

    def set_rate(self, hz: int) -> None:
        self.rate = max(1, min(100, int(hz)))
        self._cmds.append(cmd_rate(self.rate))

    def set_slew(self, us: int) -> None:
        self.slew = max(1, min(200, int(us)))
        self._cmds.append(cmd_slew(self.slew))

    def send_raw(self, data: bytes) -> None:
        self._cmds.append(data)

    # the thread side

    def _sleep(self, s: float) -> bool:
        return self._halt.wait(s)

    def _run(self) -> None:
        attempt = 0
        quiet = False
        while not self._halt.is_set():
            ser = None
            try:
                if self._initial is not None:
                    port, ser, ident = self._initial
                    self._initial = None
                else:
                    port = self.want_port
                    if port is None and self.finder is not None:
                        found = self.finder()
                        if found is None:
                            raise NoBoard("no board found on any serial port")
                        port, ser, ident = found
                    elif port is None:
                        raise NoBoard("no serial port given")
                    else:
                        ser = self.opener(port)
                        ident = wait_ident(ser, halt=self._halt)
                        if ident is None:
                            raise NoBoard(f"{port} opened but no brainsol identity line came")
                self.port = port
                attempt = 0
                quiet = False
                self._session(ser, ident)
            except Exception as e:
                if not self._halt.is_set():
                    # say it once, not every few seconds while the board is unplugged
                    if not quiet:
                        log.warning("board: %s", e)
                        quiet = True
            finally:
                if self._link:
                    self._link = False
                    self.event("warn", "board disconnected, trying again")
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass
            if self._halt.is_set():
                break
            self._sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
            attempt += 1

    def _session(self, ser, ident: Ident) -> None:
        self.ident = ident
        self.reconnects += 1
        self._last_seq = None
        reader = LineReader()
        now = time.monotonic()
        self.connected_at = now
        self._cmds.clear()
        ser.write(cmd_rate(self.rate) + cmd_slew(self.slew))
        sent_n = -1
        last_rx = now
        last_query = now
        self._link = True
        self.event("info", f"board on {self.port}, firmware {ident.fw}, {_caps_text(ident.caps)}")
        while not self._halt.is_set():
            # the newest servo target first, the first one after a connect is the held pose
            n = self._move_n
            if self._move is not None and n != sent_n:
                ser.write(cmd_move(*self._move))
                sent_n = n
            while self._cmds:
                ser.write(self._cmds.popleft())
            data = ser.read(ser.in_waiting or 1)
            now = time.monotonic()
            if data:
                last_rx = now
                for line in reader.feed(data):
                    self._handle(line, now)
            if now - last_query >= QUERY_EVERY:
                last_query = now
                ser.write(cmd_query())
            if now - last_rx > SILENT_S:
                raise NoBoard(f"no data from the board for {SILENT_S:.0f} s")

    def _handle(self, line: str, now: float) -> None:
        msg = parse_line(line)
        if isinstance(msg, Frame):
            msg.t = now
            if self._last_seq is not None:
                gap = (msg.seq - self._last_seq - 1) & 0xFFFF
                # the firmware counts frames it had to skip, a gap is lost frames, not an error
                if 0 < gap < 1000:
                    self.dropped += gap
            self._last_seq = msg.seq
            self.frames += 1
            self._latest = msg
        elif isinstance(msg, Ident):
            if self.ident is None or msg.caps != self.ident.caps:
                self.event("info", f"board sensors changed, {_caps_text(msg.caps)}")
            self.ident = msg
        elif isinstance(msg, Notice):
            if now - self.connected_at < GRACE_S and msg.code == 1:
                return
            if now - self._last_notice > 5.0:
                self._last_notice = now
                self.event("warn", f"board says {msg.text or 'error'} (code {msg.code})")
        elif msg is None and line:
            self.bad += 1


def _caps_text(caps: int) -> str:
    parts = ["BH1750 found" if caps & 1 else "no BH1750", "INA219 found" if caps & 2 else "no INA219"]
    return ", ".join(parts)
