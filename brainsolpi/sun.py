from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from astral import Observer
from astral.sun import azimuth, elevation

from .kinematics import wrap180
from .simmodel import SUN_SCENE

SPEEDS = (1, 60, 600, 3600)


def position(lat: float, lon: float, when: datetime) -> tuple[float, float]:
    # compass azimuth (north 0, east 90) and elevation in degrees
    obs = Observer(latitude=lat, longitude=lon)
    return azimuth(obs, when), elevation(obs, when)


def relative_az(compass_az: float, heading: float) -> float:
    # azimuth seen from the device, clockwise from its front
    return wrap180(compass_az - heading)


def parse_when(text: str, now: datetime) -> datetime:
    # a date alone keeps the time of day, a time without zone is local time on the pi
    text = text.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if len(text) == 10:
        day = datetime.fromisoformat(text)
        local = now.astimezone()
        when = local.replace(year=day.year, month=day.month, day=day.day)
        return when.astimezone(timezone.utc)
    when = datetime.fromisoformat(text)
    if when.tzinfo is None:
        when = when.astimezone()
    return when.astimezone(timezone.utc)


class SunClock:
    # real time or time lapse, the simulated clock never jumps when only the speed changes

    def __init__(self, wall=time.time):
        self.wall = wall
        self.speed = 1.0
        self._base_sim: float | None = None
        self._base_real = 0.0

    def set(self, speed: float, start: datetime | None = None) -> None:
        now_real = self.wall()
        current = self.now_ts()
        self.speed = float(speed)
        self._base_real = now_real
        if start is not None:
            self._base_sim = start.timestamp()
        elif self.speed == 1:
            # speed 1 without a date means back to the real clock
            self._base_sim = None
        else:
            self._base_sim = current

    @property
    def live(self) -> bool:
        return self._base_sim is None

    def now_ts(self) -> float:
        real = self.wall()
        if self._base_sim is None:
            return real
        return self._base_sim + (real - self._base_real) * self.speed

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.now_ts(), tz=timezone.utc)


def sun_light(el: float) -> tuple[float, float]:
    # direct and ambient lux for the sun scene, thinner near the horizon through more air
    if el <= 0.0:
        return 0.0, min(SUN_SCENE[1], max(5.0, SUN_SCENE[1] * (1.0 + el / 6.0)))
    air = 1.0 / max(math.sin(math.radians(el)), 0.02)
    direct = SUN_SCENE[0] * 0.7 ** (air**0.678) / 0.7
    amb = SUN_SCENE[1] * min(1.0, 0.3 + el / 30.0)
    return direct, amb
