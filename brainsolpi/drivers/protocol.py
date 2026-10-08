from __future__ import annotations

from dataclasses import dataclass

# serial line protocol between the pi and the bridge firmware on the uno

BAUD = 115200
MAX_LINE = 96
RAW_MAX = 8184

CAP_LUX = 1
CAP_PV = 2

FLAG_ATTACHED = 1
FLAG_WATCHDOG = 2
FLAG_SLEWING = 4

US_MIN = 500
US_MAX = 2500


@dataclass(slots=True)
class Ident:
    fw: str
    caps: int

    @property
    def lux(self) -> bool:
        return bool(self.caps & CAP_LUX)

    @property
    def pv(self) -> bool:
        return bool(self.caps & CAP_PV)


@dataclass(slots=True)
class Frame:
    seq: int
    raw: tuple[int, int, int, int]
    lux10: int
    mv: int
    ua: int
    pan_us: int
    tilt_us: int
    flags: int
    t: float = 0.0

    def line(self) -> str:
        l, r, u, d = self.raw
        return (
            f"S,{self.seq},{l},{r},{u},{d},{self.lux10},{self.mv},{self.ua},"
            f"{self.pan_us},{self.tilt_us},{self.flags}"
        )


@dataclass(slots=True)
class Pong:
    n: int


@dataclass(slots=True)
class Notice:
    code: int
    text: str


Message = Ident | Frame | Pong | Notice


def _int(s: str) -> int:
    # int() would also take spaces, underscores and signs the firmware never sends
    if not s or not (s.isdigit() or (s[0] == "-" and s[1:].isdigit())):
        raise ValueError(s)
    return int(s)


def parse_line(line: str) -> Message | None:
    # one line from the board, None when it is not a line we understand
    if not line:
        return None
    parts = line.split(",")
    kind = parts[0]
    try:
        if kind == "S" and len(parts) == 12:
            v = [_int(p) for p in parts[1:]]
            if not 0 <= v[0] <= 65535:
                return None
            raw = (v[1], v[2], v[3], v[4])
            if any(x < 0 or x > RAW_MAX for x in raw):
                return None
            if v[5] < 0 or v[6] < 0:
                return None
            return Frame(v[0], raw, v[5], v[6], v[7], v[8], v[9], v[10])
        if kind == "I" and len(parts) == 4 and parts[1] == "brainsol":
            return Ident(parts[2], _int(parts[3]))
        if kind == "P" and len(parts) == 2:
            return Pong(_int(parts[1]))
        if kind == "E" and len(parts) >= 2:
            return Notice(_int(parts[1]), ",".join(parts[2:]))
    except ValueError:
        return None
    return None


def clamp_us(us: float) -> int:
    us = int(round(us))
    return US_MIN if us < US_MIN else US_MAX if us > US_MAX else us


def cmd_move(pan_us: float, tilt_us: float) -> bytes:
    return f"M,{clamp_us(pan_us)},{clamp_us(tilt_us)}\n".encode("ascii")


def cmd_detach() -> bytes:
    return b"D\n"


def cmd_rate(hz: int) -> bytes:
    hz = max(1, min(100, int(hz)))
    return f"R,{hz}\n".encode("ascii")


def cmd_slew(us: int) -> bytes:
    us = max(1, min(200, int(us)))
    return f"L,{us}\n".encode("ascii")


def cmd_ping(n: int) -> bytes:
    return f"P,{int(n) & 0xFFFF}\n".encode("ascii")


def cmd_query() -> bytes:
    return b"?\n"


class LineReader:
    # splits the byte stream into lines, drops overlong ones and stray bytes

    def __init__(self, limit: int = MAX_LINE):
        self.limit = limit
        self.buf = bytearray()
        self.skipping = False
        self.dropped = 0

    def feed(self, data: bytes) -> list[str]:
        out: list[str] = []
        start = 0
        while True:
            i = data.find(b"\n", start)
            if i < 0:
                break
            chunk = data[start:i]
            start = i + 1
            if self.skipping:
                self.skipping = False
                self.buf.clear()
                continue
            self.buf += chunk
            line = self._take()
            if line is not None:
                out.append(line)
        rest = data[start:]
        if rest and not self.skipping:
            self.buf += rest
            if len(self.buf) > self.limit + 1:
                # a line that long is noise or a lost newline, wait for the next one
                self.buf.clear()
                self.skipping = True
                self.dropped += 1
        return out

    def _take(self) -> str | None:
        raw = bytes(self.buf)
        self.buf.clear()
        if raw.endswith(b"\r"):
            raw = raw[:-1]
        if len(raw) > self.limit:
            self.dropped += 1
            return None
        try:
            return raw.decode("ascii")
        except UnicodeDecodeError:
            self.dropped += 1
            return None


def parse_command(line: str) -> tuple | None:
    # the board side of the protocol, used by the fake board in tests and demos
    parts = line.split(",")
    kind = parts[0]
    try:
        if kind == "?" and len(parts) == 1:
            return ("?",)
        if kind == "D" and len(parts) == 1:
            return ("D",)
        if kind == "M" and len(parts) == 3:
            return ("M", _int(parts[1]), _int(parts[2]))
        if kind == "R" and len(parts) == 2:
            hz = _int(parts[1])
            return ("R", hz) if 1 <= hz <= 100 else None
        if kind == "L" and len(parts) == 2:
            us = _int(parts[1])
            return ("L", us) if 1 <= us <= 200 else None
        if kind == "P" and len(parts) == 2:
            return ("P", _int(parts[1]))
    except ValueError:
        return None
    return None
