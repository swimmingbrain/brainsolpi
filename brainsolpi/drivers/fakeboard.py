from __future__ import annotations

import random
import threading
import time
from collections import deque

import serial

from ..kinematics import default_pan_map, default_tilt_map
from ..simmodel import Light, illuminate, panel_lux, raw_value
from .protocol import (
    CAP_LUX,
    CAP_PV,
    FLAG_ATTACHED,
    FLAG_SLEWING,
    FLAG_WATCHDOG,
    US_MAX,
    US_MIN,
    CommandReader,
    parse_command,
)

# a simulated uno with the bridge firmware, it speaks the serial protocol over an in memory
# pipe, used by the tests and by `brainsolpi run --driver fake`


class _Buf:
    def __init__(self) -> None:
        self.data = bytearray()
        self.cond = threading.Condition()


class _Link:
    def __init__(self) -> None:
        self.alive = True


class PipeEnd:
    # the part of the pyserial api the bridge driver uses

    def __init__(self, rx: _Buf, tx: _Buf, link: _Link, timeout: float = 0.02):
        self._rx = rx
        self._tx = tx
        self._link = link
        self.timeout = timeout
        self.write_timeout = 0.5
        self.is_open = True
        self.port = "fake"

    def _check(self) -> None:
        if not self.is_open:
            raise serial.SerialException("port is closed")
        if not self._link.alive:
            raise serial.SerialException("device disconnected")

    @property
    def in_waiting(self) -> int:
        self._check()
        return len(self._rx.data)

    def read(self, size: int = 1) -> bytes:
        self._check()
        with self._rx.cond:
            if not self._rx.data and self.timeout:
                self._rx.cond.wait(self.timeout)
            self._check()
            out = bytes(self._rx.data[:size])
            del self._rx.data[:size]
            return out

    def write(self, data: bytes) -> int:
        self._check()
        with self._tx.cond:
            self._tx.data += data
            self._tx.cond.notify_all()
        return len(data)

    def reset_input_buffer(self) -> None:
        with self._rx.cond:
            self._rx.data.clear()

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.is_open = False
        with self._rx.cond:
            self._rx.cond.notify_all()


def pipe_pair(timeout: float = 0.02) -> tuple[PipeEnd, PipeEnd, _Link]:
    a, b, link = _Buf(), _Buf(), _Link()
    return PipeEnd(a, b, link, timeout), PipeEnd(b, a, link, timeout), link


class FakeBoard:
    SLEW_TICK = 0.01
    WATCHDOG_S = 1.5

    def __init__(
        self,
        boot_s: float = 1.6,
        fw: str = "1.0.0",
        lux: bool = True,
        pv: bool = False,
        light: Light | None = None,
        seed: int | None = None,
        rest: tuple[float, float] = (0.0, 90.0),
    ):
        self.boot_s = boot_s
        self.fw = fw
        self.has_lux = lux
        self.has_pv = pv
        self.light = light or Light()
        self.rng = random.Random(seed)
        self.plugged = True
        self.opens = 0
        self.boots = 0
        # the command lines it took and the lines it sent besides frames, the newest ones
        self.received: deque[str] = deque(maxlen=2000)
        self.sent: deque[str] = deque(maxlen=2000)
        self.skip_every = 0
        # sensors with a finger on them, by index L R U D, the doctor uses this in its demo
        self.covered: set[int] = set()
        # where the head sits, pan and tilt, before the first pulse a real one may sit anywhere,
        # a detached head stays where it went limp
        self.head = rest
        self._thread: threading.Thread | None = None
        self._halt = threading.Event()
        self._link: _Link | None = None
        self._port: PipeEnd | None = None
        self.pan_map = default_pan_map()
        self.tilt_map = default_tilt_map()
        self._reset_state()

    def _reset_state(self) -> None:
        # the variables of the sketch after a reset
        self.attached = False
        self.pan_now = self.tilt_now = 0
        self.pan_target = self.tilt_target = 0
        self.slew = 30
        self.rate = 50
        self.seq = 0
        self.watchdog = False
        self.next_frame = 0.0
        # the first M after this boot, so a test can see what the head was sent to first
        self.first_move: tuple[int, int] | None = None

    @property
    def caps(self) -> int:
        return (CAP_LUX if self.has_lux else 0) | (CAP_PV if self.has_pv else 0)

    # the usb side

    def opener(self, port: str = "fake", **_kw) -> PipeEnd:
        if not self.plugged:
            raise serial.SerialException(f"could not open port {port}")
        # opening the port pulls dtr, the uno resets and boots again
        host, board, link = pipe_pair()
        self._link = link
        self.opens += 1
        self._boot(board)
        return host

    def reset(self) -> None:
        # the board restarts by itself, a weak supply does that when the servos pull hard,
        # the usb link stays open and the pi only sees a new identity line
        if self._port is not None and self.plugged:
            self._boot(self._port)

    def unplug(self) -> None:
        self.plugged = False
        if self._link is not None:
            self._link.alive = False
        self._stop_thread()

    def replug(self) -> None:
        self.plugged = True

    def close(self) -> None:
        self.unplug()

    def _boot(self, port: PipeEnd) -> None:
        self._stop_thread()
        self._port = port
        self.boots += 1
        self._reset_state()
        self._halt = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(port, self._halt), daemon=True, name="fakeboard")
        self._thread.start()

    def _stop_thread(self) -> None:
        if self._thread is not None:
            self._halt.set()
            self._thread.join(timeout=2.0)
            self._thread = None

    # the firmware side, the same steps as setup and loop of the sketch

    def _send(self, port: PipeEnd, line: str) -> None:
        if line[0] != "S":
            self.sent.append(line)
        port.write((line + "\n").encode("ascii"))

    def _identity(self, port: PipeEnd) -> None:
        self._send(port, f"I,brainsol,{self.fw},{self.caps}")

    def _run(self, port: PipeEnd, halt: threading.Event) -> None:
        try:
            # the bootloader runs first, bytes sent meanwhile are lost
            if halt.wait(self.boot_s):
                return
            port.reset_input_buffer()
            self._identity(port)
            reader = CommandReader()
            start = time.monotonic()
            self.last_move = start
            next_slew = start + self.SLEW_TICK
            # the first frame is due one period after setup
            self.next_frame = start + 1.0 / self.rate
            while not halt.is_set():
                now = time.monotonic()
                port.timeout = 0
                data = port.read(4096) if port.in_waiting else b""
                for line, error in reader.feed(data):
                    if error is not None:
                        self._send(port, error)
                    else:
                        self._command(port, line, now)
                if not self.watchdog and now - self.last_move >= self.WATCHDOG_S:
                    self.watchdog = True
                while now >= next_slew:
                    next_slew += self.SLEW_TICK
                    self._slew()
                if now >= self.next_frame:
                    self.next_frame += 1.0 / self.rate
                    if now - self.next_frame > 0.5:
                        self.next_frame = now
                    self._frame(port)
                halt.wait(0.004)
        except serial.SerialException:
            return

    def _command(self, port: PipeEnd, line: str, now: float) -> None:
        self.received.append(line)
        cmd = parse_command(line)
        kind = cmd[0]
        if kind == "E":
            self._send(port, f"E,{cmd[1]},{cmd[2]}")
        elif kind == "?":
            self._identity(port)
        elif kind == "P":
            self._send(port, f"P,{cmd[1]}")
        elif kind == "R":
            self.rate = max(1, min(100, cmd[1]))
            # the next frame comes one new period from now
            self.next_frame = now + 1.0 / self.rate
        elif kind == "L":
            self.slew = max(1, min(200, cmd[1]))
        elif kind == "D":
            self.attached = False
        elif kind == "M":
            self.pan_target = max(US_MIN, min(US_MAX, cmd[1]))
            self.tilt_target = max(US_MIN, min(US_MAX, cmd[2]))
            self.last_move = now
            self.watchdog = False
            if not self.attached:
                # attach right at the commanded pulse, after boot and after a detach, the servo
                # itself gets there at its own full speed from wherever the head was
                if self.first_move is None:
                    self.first_move = (self.pan_target, self.tilt_target)
                self.pan_now, self.tilt_now = self.pan_target, self.tilt_target
                self.attached = True
                self._follow()

    def _slew(self) -> None:
        if not self.attached:
            return
        cap = self.slew
        self.pan_now += max(-cap, min(cap, self.pan_target - self.pan_now))
        self.tilt_now += max(-cap, min(cap, self.tilt_target - self.tilt_now))
        self._follow()

    def _follow(self) -> None:
        # the servos follow the pulse, the slew cap already limits their speed
        self.head = (self.pan_map.to_angle(self.pan_now), self.tilt_map.to_angle(self.tilt_now))

    def angles(self) -> tuple[float, float]:
        return self.head

    def _frame(self, port: PipeEnd) -> None:
        seq = self.seq
        self.seq = (self.seq + 1) & 0xFFFF
        if self.skip_every and seq % self.skip_every == 0:
            # a full transmit buffer, the frame is skipped and the gap in seq shows it
            return
        pan, tilt = self.angles()
        luxes, e = illuminate(self.light, pan, tilt)
        raws = [raw_value(x * 0.03 if k in self.covered else x, self.rng) for k, x in enumerate(luxes)]
        lux = panel_lux(e, self.light.amb, self.rng)
        lux10 = int(round(lux * 10)) if self.has_lux else 0
        mv = ua = 0
        if self.has_pv:
            # a small panel model, voltage settles quickly, current grows with the light
            mv = int(5500 * min(1.0, lux / 200.0)) if lux > 5 else 0
            ua = int(lux / 110.0 * 0.0106 * 0.15 / 5.5 * 1e6) if mv else 0
        flags = 0
        p_out = t_out = 0
        if self.attached:
            flags |= FLAG_ATTACHED
            p_out, t_out = self.pan_now, self.tilt_now
            if self.pan_now != self.pan_target or self.tilt_now != self.tilt_target:
                flags |= FLAG_SLEWING
        if self.watchdog:
            flags |= FLAG_WATCHDOG
        self._send(port, f"S,{seq},{raws[0]},{raws[1]},{raws[2]},{raws[3]},{lux10},{mv},{ua},{p_out},{t_out},{flags}")
