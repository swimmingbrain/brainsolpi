import pytest

from brainsolpi.config import Settings
from brainsolpi.drivers.sim import SimDriver
from brainsolpi.engine import DT, Engine, Sink
from brainsolpi.simmodel import Light
from brainsolpi.state import StateStore
from brainsolpi.store import ExperimentStore

# a quiet afternoon, so sun mode has the sun up
WALL0 = 1781870400.0  # 2026-06-19 12:00 utc


class RecSink(Sink):
    def __init__(self):
        self.msgs = []
        self.admin_msgs = []
        self.caps = 0

    def publish(self, msg, kind):
        self.msgs.append(msg)

    def publish_admins(self, msg):
        self.admin_msgs.append(msg)

    def caps_changed(self):
        self.caps += 1

    def of(self, t):
        return [m for m in self.msgs if m["t"] == t]


class Sim:
    # an engine on the sim driver that runs in simulated time, many times faster than real time

    def __init__(self, tmp_path=None, light=None, pose=(0.0, 90.0), mode="auto", seed=3, **params):
        self.settings = Settings()
        for k, v in params.items():
            self.settings.set_value(k, v)
        self.state = StateStore(None)
        self.state.pan, self.state.tilt = pose
        self.state.mode = mode
        if light is not None:
            self.state.sim = Light(**light).as_dict() if isinstance(light, dict) else light.as_dict()
        self.driver = SimDriver(seed=seed)
        self.sink = RecSink()
        self.t = 100.0
        store = ExperimentStore(tmp_path / "experiments" if tmp_path else None)
        self.engine = Engine(
            self.settings,
            self.state,
            self.driver,
            store=store,
            data_dir=tmp_path,
            wall=lambda: WALL0 + self.t,
            sink=self.sink,
        )

    def run(self, seconds, each=None):
        for _ in range(int(round(seconds / DT))):
            self.engine.tick(self.t)
            if each is not None:
                each(self)
            self.t += DT
        return self

    def run_until(self, cond, timeout):
        for _ in range(int(round(timeout / DT))):
            self.engine.tick(self.t)
            self.t += DT
            if cond(self):
                return True
        return False


@pytest.fixture
def sim(tmp_path):
    def make(**kw):
        return Sim(tmp_path, **kw)

    return make
