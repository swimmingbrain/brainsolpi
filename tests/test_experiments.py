import math

import pytest

from brainsolpi.experiments import KINDS, fit_cosine


def run_exp(s, kind, timeout=120):
    s.run(0.2)
    act = s.engine.start_activity(KINDS[kind](s.engine))
    assert s.run_until(lambda x: act.done, timeout)
    return act


def test_fit_recovers_a_clean_cosine():
    pts = [(d, 60 + 900 * max(0.0, math.cos(math.radians(d - 3)))) for d in range(-60, 61, 5)]
    fit = fit_cosine(pts)
    assert fit["amb"] == pytest.approx(60, abs=0.5)
    assert fit["peak"] == pytest.approx(900, abs=0.5)
    assert fit["offset"] == pytest.approx(3, abs=0.02)
    assert fit["r2"] == pytest.approx(1, abs=1e-6)


def test_fit_of_flat_data_has_no_r2():
    assert fit_cosine([(d, 100.0) for d in range(-10, 11, 5)])["r2"] is None


@pytest.mark.parametrize("az,el,pose", [(20, 60, (0, 90)), (-30, 70, (0, 60)), (160, 70, (0, 120))])
def test_cosine_law_in_the_sim(sim, az, el, pose):
    s = sim(light={"az": az, "el": el}, pose=pose)
    act = run_exp(s, "cosine")
    assert act.ok, act.error
    res = act.result
    assert res["fit"]["r2"] > 0.98
    assert res["fit"]["peak"] == pytest.approx(900, rel=0.08)
    assert res["fit"]["amb"] == pytest.approx(60, abs=40)
    assert len(res["rows"]) >= 15
    msgs = s.sink.of("exp")
    assert msgs[0]["phase"] == "lock"
    assert msgs[-1]["phase"] == "done" and msgs[-1]["result"]["id"] == res["id"]
    # the head is handed back to auto and locks again
    assert s.run_until(lambda x: x.engine.st == "locked", 10)
    assert s.engine.store.get(res["id"])["kind"] == "cosine"
    csv = s.engine.store.csv(res["id"])
    assert csv.splitlines()[0] == "delta,lux,fit"


def test_compare_shows_a_gain_for_a_low_light(sim):
    s = sim(light={"az": 30, "el": 20}, pose=(30, 20))
    act = run_exp(s, "compare")
    assert act.ok, act.error
    res = act.result
    # a flat panel sees a light 20 degrees over the horizon at about cos 70, about 2.6 times less
    assert res["gain"] > 1.5
    assert len(res["rows"]) == 3
    assert res["spread"] < 0.3


def test_step_reports_settle_time_and_overshoot(sim):
    s = sim(light={"az": 10, "el": 35}, pose=(0, 40))
    act = run_exp(s, "step")
    assert act.ok, act.error
    res = act.result
    assert res["settle"] is not None and 0.1 < res["settle"] < 8
    assert res["overshoot"] >= 0
    assert res["offset"] in (20, -20)
    assert res["rows"][0][0] == 0.02
    assert res["summary"] == {"settle": res["settle"], "overshoot": res["overshoot"]}


def test_experiments_fail_cleanly_without_light(sim):
    s = sim(light={"az": 10, "el": 35, "on": False, "amb": 1})
    act = run_exp(s, "cosine", timeout=30)
    assert not act.ok
    assert "light" in act.error
    last = s.sink.of("exp")[-1]
    assert last["phase"] == "error" and last["result"] is None


def test_only_one_activity_at_a_time(sim):
    from brainsolpi.engine import CommandError

    s = sim()
    s.run(0.2)
    s.engine.start_activity(KINDS["step"](s.engine))
    with pytest.raises(CommandError):
        s.engine.start_activity(KINDS["cosine"](s.engine))
