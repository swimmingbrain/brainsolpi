import json

import pytest

from brainsolpi.engine import DT, CommandError
from brainsolpi.jsonio import dumps
from brainsolpi.kinematics import angle_between, frame, pose_for

S_FIELDS = {
    "t", "ts", "mode", "st", "pan", "tilt", "vp", "vt", "ldr", "raw", "ex", "ey", "lvl", "lux",
    "pmw", "pv", "gain", "off", "tgt", "sun", "sim",
}
SYS_FIELDS = {
    "t", "viewers", "admins", "cpu", "temp", "mem", "up", "hz", "jit", "drv", "link", "fw", "rec", "act", "drop",
}


def off(s):
    d = s.driver
    return angle_between(frame(d.pan, d.tilt)[0], d.light.vector())


def test_first_command_is_the_saved_pose(sim):
    s = sim(pose=(30.0, 60.0), mode="hold")
    moves = []
    real = s.driver.move
    s.driver.move = lambda p, t: (moves.append((p, t)), real(p, t))
    s.run(DT)
    assert moves[0] == (s.engine.pan_map.to_us(30), s.engine.tilt_map.to_us(60))
    # one microsecond is about 0.09 degrees
    assert (s.driver.pan, s.driver.tilt) == pytest.approx((30, 60), abs=0.06)


def test_auto_locks_on_the_light(sim):
    s = sim(light={"az": 25, "el": 40}, pose=(0, 90))
    assert s.run_until(lambda x: x.engine.st == "locked", 10)
    assert off(s) < 9
    frame_ = s.engine.state_frame()
    assert frame_["st"] == "locked" and frame_["mode"] == "auto"
    assert frame_["off"] is not None and frame_["gain"] > 1


def test_frames_go_out_at_the_configured_rate(sim):
    s = sim(rate=10)
    s.run(3)
    assert len(s.sink.of("s")) == pytest.approx(30, abs=1)
    assert len(s.sink.of("sys")) == pytest.approx(3, abs=1)
    s.engine.set_value("rate", 25)
    s.sink.msgs.clear()
    s.run(2)
    assert len(s.sink.of("s")) == pytest.approx(50, abs=1)
    assert len(s.sink.of("cfg")) == 1


def test_state_frame_has_every_field_and_no_nan(sim):
    s = sim()
    s.run(1.2)
    f = s.sink.of("s")[-1]
    assert set(f) == S_FIELDS
    assert set(s.sink.of("sys")[-1]) == SYS_FIELDS
    text = dumps(f)
    assert "NaN" not in text
    assert json.loads(text)["sim"] == {"az": 25.0, "el": 40.0, "on": True, "lux": 900.0, "amb": 60.0}
    assert len(f["ldr"]) == 4 and len(f["raw"]) == 4
    assert f["pv"] is None
    sysf = s.sink.of("sys")[-1]
    assert sysf["drv"] == "sim" and sysf["link"] == "ok" and sysf["fw"] is None
    assert sysf["hz"] == pytest.approx(50, abs=0.1)


def test_rounding_one_decimal_for_angles_three_for_levels(sim):
    s = sim(pose=(12.3456, 45.6789), mode="hold")
    s.run(0.2)
    f = s.engine.state_frame()
    assert f["pan"] == 12.3 and f["tilt"] == 45.7
    for v in f["ldr"] + [f["ex"], f["ey"], f["lvl"]]:
        assert v == round(v, 3)


def test_hold_stops_with_the_normal_deceleration(sim):
    s = sim(pose=(-60, 60), mode="hold")
    s.engine.set_target(60, 60)
    s.run(0.6)
    v0 = s.engine.motion.vp
    assert abs(v0) > 10
    s.engine.set_mode("hold")
    prev = v0
    for _ in range(40):
        s.run(DT)
        assert abs(s.engine.motion.vp - prev) <= 240 * DT + 1e-6
        prev = s.engine.motion.vp
    assert s.engine.st == "idle"


def test_park_goes_flat_and_rests(sim):
    s = sim(pose=(-50, 30), mode="park")
    s.run(0.5)
    assert s.engine.st == "moving"
    assert s.engine.state_frame()["tgt"] == {"pan": 0.0, "tilt": 90.0}
    s.run(4)
    assert s.engine.st == "idle"
    assert (s.engine.motion.pan, s.engine.motion.tilt) == (0, 90)


def test_manual_target_and_joystick(sim):
    s = sim(mode="hold")
    s.engine.set_target(40, 120)
    assert s.engine.mode.name == "manual"
    s.run(4)
    assert (s.engine.motion.pan, s.engine.motion.tilt) == (40, 120)
    s.engine.set_rate(1, 0)
    s.run(0.3)
    assert s.engine.motion.vp > 0
    # no refresh for longer than 400 ms, the head coasts to a stop
    s.run(1.5)
    assert s.engine.motion.vp == 0
    assert s.engine.st == "idle"
    p = s.engine.motion.pan
    # about 0.4 s of push plus the ramps up and down
    assert 50 < p < 75
    # targets outside the limits are clamped
    assert s.engine.set_target(120, -5) == (88, 4)


def test_mode_changes_keep_the_running_speed(sim):
    s = sim(pose=(-60, 90), mode="hold")
    s.engine.set_target(60, 90)
    s.run(0.8)
    v = s.engine.motion.vp
    assert v > 30
    for mode in ("park", "demo", "auto", "sun", "hold"):
        s.engine.set_mode(mode)
        before = s.engine.motion.vp
        s.run(DT)
        assert abs(s.engine.motion.vp - before) <= 240 * DT + 1e-6


def test_link_loss_becomes_fault_and_heals(sim):
    s = sim(light={"az": 25, "el": 40})
    s.run(1)
    s.driver.fail(True)
    s.run(1)
    assert s.engine.st == "fault"
    assert s.engine.sys_frame()["link"] == "down"
    pose = (s.engine.motion.pan, s.engine.motion.tilt)
    s.run(1)
    assert (s.engine.motion.pan, s.engine.motion.tilt) == pose
    s.driver.fail(False)
    s.run(DT)
    assert s.engine.link
    # the fresh board attached right at the held pose, one tick of motion at most
    assert (s.driver.pan, s.driver.tilt) == pytest.approx(pose, abs=0.15)
    assert s.run_until(lambda x: x.engine.st == "locked", 10)
    msgs = [e["msg"] for e in s.sink.admin_msgs]
    assert any("link down" in m for m in msgs)
    assert any("link up" in m for m in msgs)


def test_no_exception_escapes_a_tick(sim, monkeypatch):
    s = sim()
    s.run(0.2)

    def boom(*a):
        raise RuntimeError("boom")

    monkeypatch.setattr(s.engine.mode, "step", boom)
    s.run(0.5)
    assert s.engine.errors > 0
    assert s.engine.st == "fault"
    monkeypatch.undo()
    s.run(0.5)
    assert s.engine.st != "fault"


def test_sun_mode_points_at_the_sun_and_moves_the_sim_light(sim):
    s = sim(pose=(0, 90), mode="hold")
    before = s.driver.light_state()
    s.engine.set_mode("sun")
    s.run(5)
    sun = s.engine.sun
    assert sun is not None and sun["el"] > 0
    want = pose_for(sun["az"], sun["el"])
    assert s.engine.motion.pan == pytest.approx(want[0], abs=0.5)
    assert s.engine.motion.tilt == pytest.approx(want[1], abs=0.5)
    assert s.driver.light.lux > 10000
    f = s.engine.state_frame()
    assert set(f["sun"]) == {"az", "el", "caz", "t"}
    with pytest.raises(CommandError):
        s.engine.set_simlight(az=10)
    s.engine.set_mode("auto")
    s.run(DT)
    assert s.driver.light_state() == before
    assert s.engine.state_frame()["sun"] is None


def test_sun_mode_parks_at_night(sim):
    from datetime import datetime, timezone

    s = sim(pose=(30, 40), mode="hold")
    s.engine.set_sun(1, datetime(2026, 6, 19, 23, 0, tzinfo=timezone.utc))
    s.run(5)
    assert s.engine.sun["el"] < 0
    assert (s.engine.motion.pan, s.engine.motion.tilt) == (0, 90)
    assert not s.driver.light.on


def test_time_lapse_moves_the_sun(sim):
    s = sim(mode="hold")
    s.engine.set_sun(3600)
    s.run(0.2)
    a = s.engine.sun["caz"]
    s.run(2)
    # two seconds at 3600 times real speed are two hours, the sun moves about 30 degrees
    assert s.engine.sun["caz"] - a > 15


def test_demo_moves_smoothly(sim):
    s = sim(mode="demo")
    peak = 0.0

    def watch(x):
        nonlocal peak
        peak = max(peak, abs(x.engine.motion.vp), abs(x.engine.motion.vt))

    s.run(30, each=watch)
    assert peak <= 25 + 1e-9
    assert peak > 5


def test_history_fills_once_per_second(sim):
    s = sim()
    s.run(10)
    h = s.engine.history.span(900)
    assert len(h["rows"]) in (9, 10)
    assert h["rows"][-1][3] is not None


def test_simlight_command(sim):
    s = sim()
    s.engine.set_simlight(az=-30, el=10, on=False, amb=1)
    assert s.engine.state_frame()["sim"]["az"] == -30
    s.run(1)
    assert s.engine.st == "lowlight"


def test_recording(sim, tmp_path):
    s = sim()
    out = s.engine.set_rec(True)
    s.run(1)
    assert s.engine.sys_frame()["rec"] is True
    s.engine.set_rec(False)
    text = (tmp_path / "recordings" / out["file"]).read_text(encoding="utf-8")
    assert len(text.splitlines()) == 51


def test_shutdown_saves_the_pose(sim, tmp_path):
    s = sim(pose=(10, 50), mode="hold")
    s.state.path = tmp_path / "state.json"
    s.engine.set_target(-20, 70)
    s.run(3)
    s.engine.shutdown()
    saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert (saved["pan"], saved["tilt"], saved["mode"]) == (-20, 70, "manual")
