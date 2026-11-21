import json
import re
import time
from types import SimpleNamespace

import pytest

from brainsolpi import cli, service, tools
from brainsolpi.cli import build_parser
from brainsolpi.config import Settings
from brainsolpi.jsonio import read_json
from brainsolpi.derived import pin_pv
from brainsolpi.doctor import Doctor
from brainsolpi.drivers.bridge import BridgeDriver
from brainsolpi.drivers.fakeboard import FakeBoard, pin_mv
from brainsolpi.drivers.protocol import CAP_PV, CAP_PV_PIN, Ident
from brainsolpi.drivers.sim import SimDriver
from brainsolpi.engine import DT, Engine
from brainsolpi.state import StateStore

from .conftest import RecSink

# the bridge variant with the panel on a4: the board sends the voltage at the pin, the pi turns it
# into the panel voltage, the current through the load resistor and the power


class PanelBoard(SimDriver):
    # the sim in simulated time, seen by the engine as a real board with the given caps,
    # every frame carries the given panel fields
    name = "bridge"
    profile = "bridge"
    has_simlight = False

    def __init__(self, caps=CAP_PV_PIN, mv=0, ua=0):
        super().__init__(seed=5)
        self.ident = Ident("1.0.0", caps)
        self.mv, self.ua = mv, ua

    def poll(self, now):
        f = super().poll(now)
        if f is not None:
            f.lux10, f.mv, f.ua = 0, self.mv, self.ua
        return f


class Rig:
    def __init__(self, driver, tmp_path=None):
        self.settings = Settings()
        self.driver = driver
        self.sink = RecSink()
        self.t = 50.0
        self.engine = Engine(self.settings, StateStore(None), driver, data_dir=tmp_path,
                             wall=lambda: 1.78e9 + self.t, sink=self.sink)

    def run(self, seconds):
        for _ in range(int(round(seconds / DT))):
            self.engine.tick(self.t)
            self.t += DT
        return self


def test_the_pin_voltage_becomes_volts_milliamps_and_power(tmp_path):
    # 1250 mV at the pin behind a divider of 2 are 2.5 V, on 33 ohm that is 75.76 mA and 189.39 mW
    r = Rig(PanelBoard(mv=1250), tmp_path).run(1.2)
    eng = r.engine
    assert eng.caps() == {"lux": False, "pv": True, "simlight": False}
    f = eng.state_frame()
    assert f["pv"] == {"v": 2.5, "ma": 75.76}
    assert f["pmw"] == 189.39
    # no BH1750 on this board, so no lux, the frame says null
    assert f["lux"] is None and eng.lux is None


def test_history_and_recorder_get_the_same_power(tmp_path):
    r = Rig(PanelBoard(mv=1250), tmp_path)
    out = r.engine.set_rec(True)
    r.run(3)
    r.engine.set_rec(False)
    row = r.engine.history.span(10)["rows"][-1]
    cols = r.engine.history.span(10)["cols"]
    assert row[cols.index("pmw")] == 189.39
    assert row[cols.index("lux")] is None
    lines = (tmp_path / "recordings" / out["file"]).read_text(encoding="utf-8").splitlines()
    head = lines[0].split(",")
    last = lines[-1].split(",")
    assert last[head.index("pmw")] == "189.4"
    assert last[head.index("lux")] == ""


def test_a_new_divider_or_load_counts_at_once():
    r = Rig(PanelBoard(mv=1250)).run(0.5)
    r.engine.set_value("panel_ohm", 50)
    assert r.engine.state_frame()["pv"] == {"v": 2.5, "ma": 50.0}
    assert r.engine.state_frame()["pmw"] == 125.0
    r.engine.set_value("panel_div", 3)
    assert r.engine.state_frame()["pv"] == {"v": 3.75, "ma": 75.0}
    # the page hears about it through the cfg message
    r.run(0.5)
    assert r.sink.of("cfg")[-1]["cfg"]["panel"]["ohm"] == 50.0


def test_the_ina219_numbers_stay_as_they_were():
    r = Rig(PanelBoard(caps=CAP_PV, mv=5000, ua=20000)).run(0.5)
    f = r.engine.state_frame()
    assert r.engine.caps()["pv"] is True
    assert f["pv"] == {"v": 5.0, "ma": 20.0} and f["pmw"] == 100.0
    # the divider and the load resistor are only for the panel on a4
    r.engine.set_value("panel_ohm", 10)
    assert r.engine.state_frame()["pv"] == {"v": 5.0, "ma": 20.0}


def test_without_a_panel_sensor_nothing_is_measured():
    r = Rig(PanelBoard(caps=0, mv=1250)).run(0.5)
    f = r.engine.state_frame()
    assert r.engine.caps()["pv"] is False
    # no lux either, so not even the estimate from the light
    assert f["pv"] is None and f["pmw"] is None


def test_the_fake_board_rounds_like_the_sketch():
    # the cases of the host test of the sketch, firmware/test/bridge_test.cpp
    assert pin_mv(2.5) == 2500
    assert pin_mv(5.0) == 4995
    assert pin_mv(9.0) == 4995
    assert pin_mv(5.0 / 1024) == 5
    assert pin_mv(0.0) == 0 and pin_mv(-1.0) == 0


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_the_fake_board_plays_the_variant_over_the_serial_protocol():
    board = FakeBoard(boot_s=0.2, seed=1, pv_pin=True)
    d = BridgeDriver("fake", opener=board.opener, profile="sim")
    eng = Engine(Settings(), StateStore(None), d, sink=RecSink())
    d.start_sync()
    try:
        assert wait_for(lambda: d.link_ok and d.latest() is not None)
        assert "I,brainsol,1.0.0,4" in board.sent
        assert d.ident.pv_pin and not d.ident.lux and not d.ident.pv
        assert any("panel on A4, nothing on I2C" in m for _, m in d.drain_events())
        f = d.latest()
        assert f.mv > 0 and f.ua == 0 and f.lux10 == 0
        end = time.monotonic() + 0.6
        while time.monotonic() < end:
            eng.tick(time.monotonic())
            time.sleep(0.02)
        assert eng.link and eng.caps()["pv"] and eng.lux is None
        v, ma = pin_pv(eng.frame.mv, 2.0, 33.0)
        assert eng.state_frame()["pv"] == {"v": round(v, 3), "ma": round(ma, 2)}
        assert eng.state_frame()["pmw"] == round(v * ma, 2)
    finally:
        d.stop_sync()
        board.close()


def test_the_doctor_reports_the_panel_on_a4():
    lines = []
    doc = Doctor(fake=True, out=lambda *a, **k: lines.append(" ".join(str(x) for x in a)), live=False, quick=True)
    doc.board = FakeBoard(boot_s=0.3, seed=4, pv_pin=True)
    assert doc.run() == 0
    text = "\n".join(lines)
    assert "step 5 of 6, panel on A4" in text
    assert "the variant with the panel on A4, it has nothing on I2C" in text
    assert "panel on A4 behind a divider of 2, load resistor 33 ohm" in text
    assert re.search(r"\d\.\d\d V at the pin, so the panel gives \d+\.\d\d V, \d+\.\d mA, \d+\.\d mW", text)
    assert "no BH1750 found" not in text
    results = {title: (ok, note) for title, ok, note in doc.results}
    assert "BH1750" not in results
    ok, note = results["panel on A4"]
    assert ok and note.endswith("divider 2, load 33 ohm")
    assert all(ok is True for ok, _ in results.values())


def test_the_doctor_flags_a_pin_at_the_top_of_its_range(monkeypatch):
    lines = []
    doc = Doctor(fake=True, out=lambda *a, **k: lines.append(" ".join(str(x) for x in a)), live=False, quick=True)
    # a panel of 12 V behind a divider of 2, the pin would see 6 V and reads its top
    doc.board = FakeBoard(boot_s=0.3, seed=4, pv_pin=True)
    monkeypatch.setattr(doc.board, "panel_volts", lambda lux: 12.0)
    assert doc.run() == 1
    text = "\n".join(lines)
    assert "top of its range" in text and "bigger ratio" in text
    assert dict((t, ok) for t, ok, _ in doc.results)["panel on A4"] is False


def test_setpanel_alone_shows_the_two_values_and_nothing_else(tmp_path, capsys):
    args = ["setpanel", "--config-dir", str(tmp_path)]
    assert cli.main(args) == 0
    assert capsys.readouterr().out == "panel on A4: divider 2, load resistor 33 ohm\n"
    # a look writes nothing, a fresh pi keeps its config folder empty
    assert list(tmp_path.iterdir()) == []
    (tmp_path / "settings.json").write_text(json.dumps({
        "auth": {"pin": "pbkdf2_sha256$1000$00$00"}, "brain": "http://jetson:8000",
        "panel": {"w": 120, "div": 3, "ohm": 47.5},
    }), encoding="utf-8")
    text = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert cli.main(args) == 0
    assert capsys.readouterr().out == "panel on A4: divider 3, load resistor 47.5 ohm\n"
    assert (tmp_path / "settings.json").read_text(encoding="utf-8") == text


def test_setpanel_keeps_ohm_and_div_in_the_settings(tmp_path, capsys):
    cfg = tmp_path / "cfg"
    assert tools.setpanel(SimpleNamespace(ohm=47.0, div=None, config_dir=str(cfg))) == 0
    out = capsys.readouterr().out
    assert out.startswith("panel on A4: divider 2, load resistor 47 ohm, saved in ")
    assert "brainsolpi doctor" in out
    assert read_json(cfg / "settings.json")["panel"]["ohm"] == 47.0
    # one value at a time, the other one stays
    args = build_parser().parse_args(["setpanel", "--div", "2.5", "--config-dir", str(cfg)])
    assert tools.setpanel(args) == 0
    assert Settings.load(cfg / "settings.json").panel["div"] == 2.5
    assert Settings.load(cfg / "settings.json").panel["ohm"] == 47.0
    args = build_parser().parse_args(["setpanel", "--ohm", "100", "--div", "2", "--config-dir", str(cfg)])
    assert tools.setpanel(args) == 0
    panel = read_json(cfg / "settings.json")["panel"]
    assert (panel["div"], panel["ohm"], panel["w"]) == (2.0, 100.0, 137.0)
    capsys.readouterr()
    assert cli.main(["setpanel", "--config-dir", str(cfg)]) == 0
    assert capsys.readouterr().out == "panel on A4: divider 2, load resistor 100 ohm\n"


@pytest.mark.parametrize("option,value", [
    ("--ohm", "0"), ("--ohm", "-5"), ("--ohm", "200000"), ("--ohm", "abc"), ("--ohm", "nan"),
    ("--div", "0.5"), ("--div", "101"), ("--div", "inf"),
])
def test_setpanel_refuses_values_outside_the_limits(tmp_path, capsys, option, value):
    with pytest.raises(SystemExit) as e:
        build_parser().parse_args(["setpanel", option, value, "--config-dir", str(tmp_path)])
    assert e.value.code == 2
    assert f"argument {option}: must be" in capsys.readouterr().err
    key = option[2:]
    called = SimpleNamespace(ohm=None, div=None, config_dir=str(tmp_path))
    setattr(called, key, float(value) if value != "abc" else "abc")
    assert tools.setpanel(called) == 1
    assert "nothing changed" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


class Runner:
    # records the service commands and answers with the return codes it was given
    def __init__(self, codes=None):
        self.calls = []
        self.codes = codes or {}

    def __call__(self, cmd, **kw):
        self.calls.append(" ".join(cmd))
        return SimpleNamespace(returncode=self.codes.get(" ".join(cmd), 0))


def test_setpanel_writes_while_the_service_rests(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(service, "active", lambda run: True)
    order = []

    def run(cmd, **kw):
        # what the settings file says at the moment the service stops and starts
        panel = (read_json(tmp_path / "settings.json") or {}).get("panel", {})
        order.append((" ".join(cmd), panel.get("ohm")))
        return SimpleNamespace(returncode=0)

    real = service.Paused
    monkeypatch.setattr(service, "Paused", lambda why, **kw: real(why, run=run, **kw))
    assert tools.setpanel(SimpleNamespace(ohm=47.0, div=None, config_dir=str(tmp_path))) == 0
    assert order == [("sudo systemctl stop brainsolpi", None), ("sudo systemctl start brainsolpi", 47.0)]
    out = capsys.readouterr().out
    assert "stopping the brainsolpi service while the panel values are written" in out
    assert "starting the brainsolpi service again" in out
    assert read_json(tmp_path / "settings.json")["panel"]["ohm"] == 47.0


def test_setpanel_changes_nothing_while_the_service_cannot_be_stopped(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(service, "active", lambda run: True)
    run = Runner({"sudo systemctl stop brainsolpi": 1})
    real = service.Paused
    monkeypatch.setattr(service, "Paused", lambda why, **kw: real(why, run=run, **kw))
    assert tools.setpanel(SimpleNamespace(ohm=47.0, div=None, config_dir=str(tmp_path))) == 1
    out = capsys.readouterr().out
    assert "nothing changed. stop it with: sudo systemctl stop brainsolpi" in out
    assert not (tmp_path / "settings.json").exists()
    assert "sudo systemctl start brainsolpi" not in run.calls
