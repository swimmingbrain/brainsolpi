from datetime import datetime, timezone

import pytest

from brainsolpi.sun import SunClock, parse_when, position, relative_az, sun_light


def test_sun_position_at_a_known_moment():
    # summer solstice, solar noon in munich is about 11:15 utc, the sun stands due south
    when = datetime(2026, 6, 21, 11, 15, tzinfo=timezone.utc)
    az, el = position(48.14, 11.58, when)
    assert az == pytest.approx(180, abs=2)
    assert el == pytest.approx(65.3, abs=0.5)


def test_sun_is_below_the_horizon_at_midnight():
    when = datetime(2026, 12, 21, 23, 0, tzinfo=timezone.utc)
    assert position(48.14, 11.58, when)[1] < -30


def test_relative_azimuth_uses_the_device_heading():
    assert relative_az(180, 180) == 0
    assert relative_az(90, 180) == -90
    assert relative_az(350, 10) == -20
    assert relative_az(10, 350) == 20


def test_time_lapse_clock():
    t = [1000.0]
    clock = SunClock(wall=lambda: t[0])
    assert clock.live and clock.now_ts() == 1000
    clock.set(600)
    t[0] += 2
    assert clock.now_ts() == pytest.approx(1000 + 1200)
    # changing the speed continues from where the clock is
    clock.set(60)
    t[0] += 1
    assert clock.now_ts() == pytest.approx(2200 + 60)
    start = datetime(2026, 6, 21, 4, 0, tzinfo=timezone.utc)
    clock.set(3600, start)
    t[0] += 1
    assert clock.now() == datetime(2026, 6, 21, 5, 0, tzinfo=timezone.utc)
    clock.set(1)
    assert clock.live and clock.now_ts() == t[0]


def test_parse_when():
    now = datetime(2026, 11, 14, 10, 30, tzinfo=timezone.utc)
    assert parse_when("2026-06-21T05:00Z", now) == datetime(2026, 6, 21, 5, 0, tzinfo=timezone.utc)
    assert parse_when("2026-06-21T07:00+02:00", now) == datetime(2026, 6, 21, 5, 0, tzinfo=timezone.utc)
    day = parse_when("2026-06-21", now)
    assert day.astimezone().date().isoformat() == "2026-06-21"
    with pytest.raises(ValueError):
        parse_when("tomorrow", now)


def test_sun_scene_light():
    lux, amb = sun_light(90)
    assert lux == pytest.approx(80000)
    assert amb == pytest.approx(9000)
    low, _ = sun_light(5)
    assert 0 < low < lux
    assert sun_light(-10)[0] == 0
