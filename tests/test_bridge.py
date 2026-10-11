import time

import pytest

from brainsolpi.drivers import bridge as bridge_mod
from brainsolpi.drivers.bridge import BridgeDriver
from brainsolpi.drivers.detect import find_board, probe
from brainsolpi.drivers.fakeboard import FakeBoard
from brainsolpi.drivers.protocol import FLAG_ATTACHED, FLAG_SLEWING, FLAG_WATCHDOG


def wait_for(cond, timeout=5.0, step=0.01):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return False


@pytest.fixture
def board():
    b = FakeBoard(boot_s=0.2, seed=1)
    yield b
    b.close()


@pytest.fixture
def drv(board):
    d = BridgeDriver("fake", opener=board.opener)
    d.start_sync()
    yield d
    d.stop_sync()


def ready(d, timeout=5.0):
    return wait_for(lambda: d.link_ok and d.latest() is not None, timeout)


def frames_for(d, seconds):
    out = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        f = d.poll(time.monotonic())
        if f is not None:
            out.append(f)
        time.sleep(0.005)
    return out


def test_connects_after_the_boot_delay_and_streams_at_50_hz(board, drv):
    assert not drv.link_ok
    assert wait_for(lambda: drv.link_ok)
    assert drv.ident.fw == "1.0.0" and drv.ident.lux
    assert wait_for(lambda: "R,50" in board.received and "L,30" in board.received)
    seqs = [f.seq for f in frames_for(drv, 1.0)]
    # the driver hands out only the newest frame, the counter shows all of them
    assert 40 <= len(seqs) <= 55
    assert drv.dropped == 0
    assert all(b > a for a, b in zip(seqs, seqs[1:]))


def test_first_move_attaches_at_the_pulse_then_slews(board, drv):
    assert ready(drv)
    f = drv.latest()
    assert f.pan_us == 0 and not f.flags & FLAG_ATTACHED
    drv.move(1700, 1200)
    assert wait_for(lambda: drv.latest().flags & FLAG_ATTACHED)
    f = drv.latest()
    assert (f.pan_us, f.tilt_us) == (1700, 1200)
    drv.move(2300, 1200)
    assert wait_for(lambda: drv.latest().flags & FLAG_SLEWING)
    t0 = time.monotonic()
    assert wait_for(lambda: drv.latest().pan_us == 2300)
    # 600 us at 30 us per 10 ms take about 200 ms
    assert 0.12 < time.monotonic() - t0 < 0.5
    assert not drv.latest().flags & FLAG_SLEWING


def test_watchdog_flag_when_commands_stop(board, drv):
    assert ready(drv)
    drv.move(1500, 1500)
    assert wait_for(lambda: drv.latest().flags & FLAG_ATTACHED)
    assert not drv.latest().flags & FLAG_WATCHDOG
    assert wait_for(lambda: drv.latest().flags & FLAG_WATCHDOG, timeout=3)
    drv.move(1500, 1500)
    assert wait_for(lambda: not drv.latest().flags & FLAG_WATCHDOG)


def test_unplug_and_replug(board, drv):
    assert ready(drv)
    drv.move(1600, 1400)
    assert wait_for(lambda: drv.latest().flags & FLAG_ATTACHED)
    board.unplug()
    assert wait_for(lambda: not drv.link_ok, timeout=3)
    events = [m for _, m in drv.drain_events()]
    assert any("disconnected" in m for m in events)
    time.sleep(1.0)
    assert not drv.link_ok
    board.replug()
    assert wait_for(lambda: drv.link_ok, timeout=8)
    # the fresh board got the held pose first and attached right there
    assert wait_for(lambda: drv.latest() is not None and drv.latest().flags & FLAG_ATTACHED)
    f = drv.latest()
    assert (f.pan_us, f.tilt_us) == (1600, 1400)
    assert board.opens >= 2
    assert drv.reconnects == 2


def test_a_sensor_plugged_in_later_shows_in_the_caps(board, monkeypatch):
    monkeypatch.setattr(bridge_mod, "QUERY_EVERY", 0.3)
    board.has_pv = False
    d = BridgeDriver("fake", opener=board.opener)
    d.start_sync()
    try:
        assert wait_for(lambda: d.link_ok)
        assert not d.ident.pv
        board.has_pv = True
        assert wait_for(lambda: d.ident.pv, timeout=2)
        f = frames_for(d, 0.2)[-1]
        assert f.mv > 0 and f.ua > 0
    finally:
        d.stop_sync()


def test_skipped_frames_are_counted(board, drv):
    board.skip_every = 10
    assert wait_for(lambda: drv.link_ok)
    assert wait_for(lambda: drv.dropped >= 3, timeout=2)
    assert drv.link_ok


def test_notices_and_garbage(board, drv):
    assert wait_for(lambda: drv.link_ok)
    drv.drain_events()
    # inside the grace time after a connect a stray E,1 is ignored
    drv.send_raw(b"bogus\n")
    time.sleep(0.2)
    assert not [m for _, m in drv.drain_events() if "board says" in m]
    drv.connected_at -= 10
    drv.send_raw(b"bogus\n")
    assert wait_for(lambda: any("board says" in m for _, m in list(drv._events)))
    drv.send_raw(b"P,123456789012345\n")
    assert wait_for(lambda: "P,123456789012345" in board.received)


def test_a_dead_port_never_blocks_poll(board):
    board.unplug()
    d = BridgeDriver("fake", opener=board.opener)
    d.start_sync()
    try:
        t0 = time.perf_counter()
        for _ in range(1000):
            d.poll(time.monotonic())
            d.move(1500, 1500)
        assert time.perf_counter() - t0 < 0.2
        assert not d.link_ok
    finally:
        d.stop_sync()


def test_probe_and_find_board(board):
    got = probe("fake", board.opener, timeout=2)
    assert got is not None and got[2].fw == "1.0.0"
    got[1].close()
    other = FakeBoard(boot_s=0.1)
    other.unplug()

    def opener(port):
        return board.opener(port) if port == "COM9" else other.opener(port)

    found = find_board(timeout=3, opener=opener, ports=["COM3", "COM9"])
    assert found is not None and found[0] == "COM9"
    found[1].close()
    assert find_board(timeout=1, opener=other.opener, ports=["COM3"]) is None


def test_engine_on_the_bridge_heals_after_a_replug(board):
    from brainsolpi.config import Settings
    from brainsolpi.engine import Engine
    from brainsolpi.state import StateStore

    d = BridgeDriver("fake", opener=board.opener, profile="sim")
    state = StateStore(None)
    state.pan, state.tilt = 20.0, 50.0
    eng = Engine(Settings(), state, d)
    d.start_sync()
    try:
        def run(seconds):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                eng.tick(time.monotonic())
                time.sleep(0.02)

        run(0.8)
        assert eng.link and eng.st != "fault"
        f = d.latest()
        # the board attached at the saved pose
        assert abs(eng.pan_map.to_angle(f.pan_us) - 20) < 3
        assert eng.sys_frame()["fw"] == "1.0.0" and eng.sys_frame()["drv"] == "bridge"
        board.unplug()
        run(1.0)
        assert eng.st == "fault" and eng.sys_frame()["link"] == "down"
        held = (eng.motion.pan, eng.motion.tilt)
        board.replug()
        run(3.0)
        assert eng.link and eng.st != "fault"
        assert eng.ticks > 100
        assert abs(eng.motion.pan - held[0]) < 20
    finally:
        d.stop_sync()
