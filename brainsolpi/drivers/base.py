from __future__ import annotations

from collections import deque

from .protocol import Frame, Ident


class Driver:
    # what the engine sees of the hardware, the sim and the bridge look the same from here

    name = "base"
    # calibration profile in the settings, the sim keeps its own so it never spoils the real one
    profile = "bridge"
    # true when the light can be moved with the simlight command
    has_simlight = False

    def __init__(self) -> None:
        self.ident: Ident | None = None
        self.port: str | None = None
        self.frames = 0
        self._events: deque[tuple[str, str]] = deque(maxlen=64)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    @property
    def link_ok(self) -> bool:
        return False

    def poll(self, now: float) -> Frame | None:
        # the newest frame since the last call, or None when nothing new arrived
        return None

    def move(self, pan_us: int, tilt_us: int) -> None:
        pass

    def detach(self) -> None:
        pass

    def set_rate(self, hz: int) -> None:
        pass

    def set_slew(self, us: int) -> None:
        pass

    def event(self, lvl: str, msg: str) -> None:
        self._events.append((lvl, msg))

    def drain_events(self) -> list[tuple[str, str]]:
        out = []
        while self._events:
            out.append(self._events.popleft())
        return out
