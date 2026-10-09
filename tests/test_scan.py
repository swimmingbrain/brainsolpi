import pytest

from brainsolpi.kinematics import angle_between, direction, frame
from brainsolpi.scan import Scan, axis


def test_grid_axes():
    assert axis(-90, 90, 15) == [-90 + 15 * i for i in range(13)]
    assert axis(15, 165, 15) == [15 + 15 * i for i in range(11)]
    assert axis(15, 165, 40) == [15, 55, 95, 135]


def visit_order(sink):
    seen = []
    prev = None
    for m in sink.of("scan"):
        for i, row in enumerate(m["v"]):
            for j, v in enumerate(row):
                if v is not None and (prev is None or prev["v"][i][j] is None):
                    seen.append((i, j))
        prev = m
    return seen


def run_scan(s, step, light):
    s.engine.set_simlight(**light)
    s.run(0.2)
    act = s.engine.start_activity(Scan(s.engine, step))
    assert s.run_until(lambda x: act.done, 600)
    return act


def test_serpentine_and_progress_messages(sim):
    s = sim(mode="hold")
    act = run_scan(s, 45, {"az": 30, "el": 50})
    assert act.ok
    order = visit_order(s.sink)
    cols = len(act.pans)
    assert order[:cols] == [(0, j) for j in range(cols)]
    assert order[cols:2 * cols] == [(1, j) for j in reversed(range(cols))]
    msgs = s.sink.of("scan")
    assert len(msgs) == act.cells + 2
    assert msgs[0]["done"] is False and msgs[-1]["done"] is True
    assert all(v is not None for row in msgs[-1]["v"] for v in row)


@pytest.mark.parametrize("az,el", [(30, 50), (-60, 25), (140, 40)])
def test_best_cell_lands_near_the_light(sim, az, el):
    s = sim(mode="hold")
    act = run_scan(s, 15, {"az": az, "el": el})
    best = s.sink.of("scan")[-1]["best"]
    n = frame(max(-88, min(88, best["pan"])), best["tilt"])[0]
    # the grid is 15 degrees, the best cell can be at most about half a diagonal away
    assert angle_between(n, direction(az, el)) < 12
    assert best["v"] > 800
    assert s.engine.st == "idle"
    assert s.engine.activity is None and act.ok


def test_after_a_scan_auto_starts_from_the_brightest_cell(sim):
    s = sim(mode="auto", pose=(0, 30), light={"az": 150, "el": 30})
    s.run(1)
    # the light is far behind, the tracker sees nothing
    assert s.engine.st == "lowlight"
    run_scan(s, 30, {"az": 150, "el": 30})
    assert s.run_until(lambda x: x.engine.st == "locked", 10)
    d = s.driver
    assert angle_between(frame(d.pan, d.tilt)[0], direction(150, 30)) < 9


def test_stop_ends_the_scan_and_returns_to_the_mode(sim):
    s = sim(mode="park")
    s.run(0.2)
    s.engine.start_activity(Scan(s.engine, 30))
    s.run(3)
    assert s.engine.st == "scanning"
    assert s.engine.sys_frame()["act"] == "scan"
    assert s.engine.stop_activity()
    last = s.sink.of("scan")[-1]
    assert last["done"] is True and last["stopped"] is True
    s.run(5)
    assert s.engine.mode.name == "park"
    assert (s.engine.motion.pan, s.engine.motion.tilt) == (0, 90)
    assert s.engine.sys_frame()["act"] is None
