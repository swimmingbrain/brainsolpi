import pytest

from brainsolpi import calibration
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
