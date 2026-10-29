import pytest

from brainsolpi import calibration
from brainsolpi.engine import DT
from brainsolpi.kinematics import angle_between, frame


def run_act(s, act, timeout=30):
    s.engine.start_activity(act)
    assert s.run_until(lambda x: act.done, timeout)
    assert act.ok, act.error
    return act.result


def test_dark_and_bright_capture_in_the_sim(sim):
    s = sim(mode="hold", pose=(25, 40), light={"az": 25, "el": 40})
    s.engine.set_simlight(on=False)
    s.run(0.5)
    res = run_act(s, calibration.Capture(s.engine, "dark"))
    assert res["dark"] == pytest.approx([6367] * 4, abs=3)
    assert s.engine.st == "idle"
    s.engine.set_simlight(on=True)
    s.run(0.5)
    res = run_act(s, calibration.Capture(s.engine, "bright"))
    assert res["bright"] == pytest.approx([7862] * 4, abs=3)
    assert res["inverted"] == [False] * 4
    assert res["weak"] == [False] * 4
    assert not s.engine.calib_saved
    # nothing is written until save
    assert s.settings.calib("sim")["dark"] != res["dark"]
    calibration.save(s.engine)
    assert s.settings.calib("sim")["dark"] == res["dark"]
    assert s.engine.calib_saved


def moving_head(sim, amax=50):
    # a low acceleration makes the braking last longer than the one second capture
    s = sim(mode="hold", pose=(-80, 60), amax=amax)
    s.engine.set_target(80, 120)
    s.run(1.4)
    assert abs(s.engine.motion.vp) > 40 and abs(s.engine.motion.vt) > 10
    return s


def watch_accel(s, seconds, amax):
    m = s.engine.motion
    prev = (m.vp, m.vt)
    for _ in range(int(round(seconds / DT))):
        s.run(DT)
        assert abs(m.vp - prev[0]) <= amax * DT + 1e-6
        assert abs(m.vt - prev[1]) <= amax * DT + 1e-6
        prev = (m.vp, m.vt)


def test_a_capture_brakes_through_the_limiter_and_never_jolts(sim):
    s = moving_head(sim)
    act = calibration.Capture(s.engine, "dark")
    s.engine.start_activity(act)
    # the capture, its end while the head still brakes, and the way back to the target
    watch_accel(s, 3.0, 50)
    assert act.done and act.ok


def test_typed_in_values_keep_the_speed(sim):
    s = moving_head(sim)
    before = (s.engine.motion.vp, s.engine.motion.vt)
    calibration.set_values(s.engine, "bright", [7800, 7800, 7800, 7800])
    assert (s.engine.motion.vp, s.engine.motion.vt) == before
    watch_accel(s, 1.0, 50)


def test_a_new_servo_centre_zeroes_the_speeds(sim):
    s = moving_head(sim)
    calibration.zero(s.engine, pan_us=1520, tilt_us=1480)
    assert (s.engine.motion.vp, s.engine.motion.vt) == (0, 0)


def test_values_can_be_given_directly(sim):
    s = sim()
    s.run(0.1)
    out = calibration.set_values(s.engine, "bright", [100, 100, 100, 100])
    assert out["inverted"] == [False] * 4 or out["inverted"] == [True] * 4
    with pytest.raises(ValueError):
        calibration.set_values(s.engine, "dark", [1, 2, 3])
    with pytest.raises(ValueError):
        calibration.set_values(s.engine, "dark", [1, 2, 3, 9000])


def test_polarity_learns_the_signs(sim):
    s = sim(light={"az": 20, "el": 40}, pose=(20, 40), mode="hold")
    s.run(0.5)
    res = run_act(s, calibration.Polarity(s.engine))
    assert (res["sx"], res["sy"]) == (1, 1)


def test_polarity_fixes_swapped_sensors(sim):
    s = sim(light={"az": 20, "el": 40}, pose=(20, 40), mode="hold")
    real = s.driver._frame

    def swapped(now):
        f = real(now)
        l, r, u, d = f.raw
        f.raw = (r, l, d, u)
        return f

    s.driver._frame = swapped
    s.run(0.5)
    res = run_act(s, calibration.Polarity(s.engine))
    assert (res["sx"], res["sy"]) == (-1, -1)
    # with the learned signs the loop locks on again from somewhere else
    s.engine.set_target(-20, 60)
    s.run(3)
    s.engine.set_mode("auto")
    assert s.run_until(lambda x: x.engine.st == "locked", 15)
    d = s.driver
    assert angle_between(frame(d.pan, d.tilt)[0], d.light.vector()) < 9


def test_polarity_refuses_near_the_zenith(sim):
    s = sim(light={"az": 0, "el": 85}, pose=(0, 88), mode="hold")
    s.run(0.5)
    act = calibration.Polarity(s.engine)
    s.engine.start_activity(act)
    s.run(0.1)
    assert act.done and not act.ok
    assert "flat" in act.error


def test_zero_keeps_the_pulses_and_moves_the_centre(sim):
    s = sim(mode="hold", pose=(10, 80))
    s.run(0.2)
    before = s.engine._last_us
    out = calibration.zero(s.engine)
    s.run(0.1)
    assert s.engine._last_us == before
    assert (out["pan"], out["tilt"]) == (0, 90)
    assert s.engine.calib["pan"]["centre_us"] == before[0]
    calibration.reset(s.engine)
    s.run(0.1)
    assert s.engine._last_us == before
    assert s.engine.calib["pan"]["centre_us"] == 1500
    with pytest.raises(ValueError):
        calibration.zero(s.engine, pan_us=3000)
