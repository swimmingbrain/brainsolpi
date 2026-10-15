import asyncio
import json
import random

from brainsolpi.commands import Commands
from brainsolpi.config import PARAMS, Settings
from brainsolpi.drivers.sim import SimDriver
from brainsolpi.engine import DT, Engine
from brainsolpi.hub import Hub
from brainsolpi.state import StateStore
from brainsolpi.store import ExperimentStore

from .test_hub import FakeWs

MINUTES = 10
KEYS = [p.key for p in PARAMS] + ["pan_min", "pan_max", "tilt_max", "park_tilt", "nope"]


def random_command(rng: random.Random, i: int) -> dict:
    ops = [
        lambda: {"op": "mode", "mode": rng.choice(["auto", "manual", "sun", "hold", "park", "demo", "nap"])},
        lambda: {"op": "target", "pan": rng.uniform(-200, 200), "tilt": rng.uniform(-50, 250)},
        lambda: {"op": "rate", "pan": rng.uniform(-1.5, 1.5), "tilt": rng.uniform(-1.5, 1.5)},
        lambda: {"op": "set", "key": rng.choice(KEYS), "value": rng.choice([rng.uniform(-50, 400), "x", None, True])},
        lambda: {"op": "simlight", "az": rng.uniform(-180, 180), "el": rng.uniform(-10, 95),
                 "on": rng.random() > 0.2, "lux": rng.choice([None, 300, 900, 80000]),
                 "amb": rng.choice([None, 5, 60, 9000])},
        lambda: {"op": "scan", "step": rng.choice([30, 45, 3, "big"])},
        lambda: {"op": "exp", "kind": rng.choice(["cosine", "compare", "step", "dance"])},
        lambda: {"op": "stop"},
        lambda: {"op": "calib", "step": rng.choice(["zero", "reset", "save", "dark", "bright", "polarity", "oops"]),
                 "values": rng.choice([None, [7000, 7000, 7000, 7000], [1, 2]])},
        lambda: {"op": "rec", "on": rng.random() > 0.5},
        lambda: {"op": "sun", "speed": rng.choice([1, 60, 600, 3600, 0, 1e9]),
                 "date": rng.choice([None, "2026-06-21", "2026-12-21T06:00", "soon"])},
        lambda: {"op": "site", "lat": rng.uniform(-100, 100), "lon": rng.uniform(-200, 200), "heading": rng.uniform(-10, 370)},
        lambda: {"op": "ping"},
        lambda: {"op": "warp"},
        lambda: {"pan": 3},
    ]
    msg = rng.choice(ops)()
    msg["t"] = "cmd"
    msg["id"] = i
    return msg


async def test_long_run_with_random_commands_never_breaks(tmp_path):
    rng = random.Random(1234)
    settings = Settings(tmp_path / "settings.json")
    driver = SimDriver(seed=99)
    hub = Hub()
    t = [100.0]
    engine = Engine(
        settings, StateStore(tmp_path / "state.json"), driver,
        store=ExperimentStore(tmp_path / "exp"), data_dir=tmp_path, wall=lambda: 1.78e9 + t[0], sink=hub,
    )
    hub.engine = engine
    stuck, reader = FakeWs(stuck=True), FakeWs()
    c_stuck, c_reader = hub.add(stuck), hub.add(reader)
    c_stuck.admin = c_reader.admin = True
    cmds = Commands(engine, on_sys=lambda action: None)
    tasks = set()
    acks = []
    worst_queue = 0
    lp_all = (-90.0, 90.0)
    lt_all = (0.0, 180.0)

    async def send(msg):
        acks.append(await cmds.handle(msg, admin=True))

    ticks = int(MINUTES * 60 / DT)
    for i in range(ticks):
        engine.tick(t[0])
        t[0] += DT
        m = engine.motion
        assert lp_all[0] <= m.pan <= lp_all[1] and lt_all[0] <= m.tilt <= lt_all[1]
        assert abs(m.vp) <= 180 + 1e-6 and abs(m.vt) <= 180 + 1e-6
        if i % 20 == 0:
            task = asyncio.ensure_future(send(random_command(rng, i)))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        if i % 3000 == 1500:
            driver.fail(True)
        if i % 3000 == 1700:
            driver.fail(False)
        if i % 5 == 0:
            await asyncio.sleep(0)
        worst_queue = max(worst_queue, len(c_stuck.queue))
    # let the last commands finish, calibration steps need a few more ticks
    for _ in range(200):
        engine.tick(t[0])
        t[0] += DT
        await asyncio.sleep(0)
    for task in list(tasks):
        task.cancel()
    assert engine.errors == 0
    assert engine.ticks == ticks + 200
    assert worst_queue <= Hub.MAX_QUEUE
    assert len(reader.sent) > MINUTES * 60 * 15
    assert all(json.loads(x)["t"] for x in reader.sent[-50:])
    assert "NaN" not in "".join(reader.sent)
    assert sum(1 for a in acks if a["ok"]) > 100
    assert sum(1 for a in acks if not a["ok"]) > 50
    assert all("internal error" not in a.get("err", "") for a in acks)
    engine.shutdown()
    await hub.remove(c_stuck)
    await hub.remove(c_reader)
