import json
import time
from types import SimpleNamespace

import pytest

from brainsolpi import calibration, tools
from brainsolpi.config import Settings
from brainsolpi.drivers.bridge import BridgeDriver
from brainsolpi.drivers.fakeboard import FakeBoard
from brainsolpi.drivers.sim import SimDriver
from brainsolpi.engine import DT, Engine
from brainsolpi.state import StateStore

from .conftest import RecSink


class BoardStandIn(SimDriver):
    # the sim in simulated time, but seen by the engine as a real board: its own calibration
    # profile, no simlight, and a head that sits wherever it was left before the first pulse
    name = "bridge"
    profile = "bridge"
    has_simlight = False

    def __init__(self, rest=(40.0, 30.0), **kw):
        super().__init__(seed=5, **kw)
        self.pan, self.tilt = rest
        self.moves = []

    def settle_at(self, pan_us, tilt_us):
        pass

    def move(self, pan_us, tilt_us):
        self.moves.append((pan_us, tilt_us))
        super().move(pan_us, tilt_us)


class Rig:
    def __init__(self, calibrated=False, pose=None, mode="auto"):
        self.settings = Settings()
        if calibrated:
            cal = self.settings.calib("bridge")
            cal["saved"] = True
            self.settings.set_calib("bridge", cal)
        self.state = StateStore(None)
        self.state.mode = mode
        if pose is not None:
            self.state.pan, self.state.tilt = pose
            self.state.known = True
        self.driver = BoardStandIn()
        self.sink = RecSink()
        self.t = 50.0
        self.engine = Engine(self.settings, self.state, self.driver, wall=lambda: 1.78e9 + self.t, sink=self.sink)

    def run(self, seconds):
        for _ in range(int(round(seconds / DT))):
            self.engine.tick(self.t)
            self.t += DT
        return self

    def events(self):
        return [m["msg"] for m in self.sink.admin_msgs]


def test_a_fresh_board_holds_with_the_servos_off_and_says_why():
    r = Rig().run(3)
    eng = r.engine
    assert eng.mode.name == "hold" and eng.st == "idle"
    assert eng.state_frame()["mode"] == "hold"
    # nothing went to the servos, the head still sits where it was left
    assert r.driver.moves == []
    assert (r.driver.pan, r.driver.tilt) == (40.0, 30.0)
    text = " ".join(r.events())
    assert "no calibration is saved" in text and "calibrate tab" in text
    assert "servos stay off" in text


def test_the_first_command_goes_to_the_centre_once_a_mode_is_picked():
    r = Rig().run(1)
    r.engine.set_mode("auto")
    r.run(0.4)
    # the servos run to the centre at their own speed, the limiter waits for them
    assert set(r.driver.moves) == {(1500, 1500)}
    assert r.engine.st == "moving"
    assert any("the servos start at pan 0 tilt 90, 1500 and 1500 us" in m for m in r.events())
    assert r.state.known
    assert r.engine.first_start == []


def test_a_capture_keeps_the_servos_off_and_zero_waits_for_a_pose():
    r = Rig().run(1)
    act = calibration.Capture(r.engine, "dark")
    r.engine.start_activity(act)
    r.run(1.5)
    assert act.ok and r.driver.moves == []
    with pytest.raises(ValueError, match="servos are still off"):
        calibration.zero(r.engine)
    # nudging the head is a move, it switches to manual and the servos come on
    r.engine.set_target(0, 90)
    r.run(0.5)
    assert r.driver.moves and r.engine.mode.name == "manual"
    assert calibration.zero(r.engine)["pan_us"] == 1500


def test_a_known_pose_without_calibration_attaches_there_and_saving_goes_on_in_auto():
    r = Rig(pose=(20.0, 60.0)).run(1)
    eng = r.engine
    assert eng.mode.name == "hold"
    assert r.driver.moves[0] == (eng.pan_map.to_us(20), eng.tilt_map.to_us(60))
    assert not any("servos stay off" in m for m in r.events())
    calibration.save(eng)
    assert eng.mode.name == "auto"
    assert any("goes on in auto" in m for m in r.events())
    assert eng.settings.calib("bridge")["saved"] is True


def test_a_first_save_names_the_steps_that_did_not_run():
    r = Rig(pose=(20.0, 60.0)).run(0.5)
    calibration.set_values(r.engine, "dark", [200, 200, 200, 200])
    calibration.set_values(r.engine, "bright", [7800, 7800, 7800, 7800])
    calibration.save(r.engine)
    msg = [m for m in r.events() if "calibration saved for" in m][-1]
    assert "zero and polarity did not run" in msg
    # later saves of a calibrated board say nothing of the kind
    calibration.save(r.engine)
    assert [m for m in r.events() if "calibration saved for" in m][-1] == "calibration saved for the bridge profile"


def test_a_calibrated_board_without_a_pose_holds_too():
    r = Rig(calibrated=True).run(1)
    assert r.engine.mode.name == "hold" and r.engine.first_start == ["pose"]
    assert r.driver.moves == []
    text = " ".join(r.events())
    assert "no calibration" not in text and "servos stay off" in text


def test_a_calibrated_board_with_a_pose_starts_as_saved():
    r = Rig(calibrated=True, pose=(10.0, 50.0), mode="demo").run(1)
    assert r.engine.mode.name == "demo" and r.engine.first_start == []
    assert r.events() == [m for m in r.events() if "link up" in m]


def test_the_first_start_hold_is_not_saved_as_a_choice(tmp_path):
    r = Rig(pose=(0.0, 90.0))
    r.state.path = tmp_path / "state.json"
    r.run(1)
    r.engine.shutdown()
    saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert saved["mode"] == "auto" and saved["known"] is True


def test_an_admin_who_unlocks_later_reads_the_notes_again():
    r = Rig().run(1)
    r.sink.admin_msgs.clear()
    r.engine.remind()
    assert len(r.sink.admin_msgs) == 2
    r.engine.set_mode("hold")
    r.sink.admin_msgs.clear()
    r.engine.remind()
    # the pick ended the first start, only the note about the servos is left
    assert [m["msg"] for m in r.sink.admin_msgs] == [m for m in r.events() if "servos stay off" in m]


def test_the_sim_starts_right_away():
    s = Engine(Settings(), StateStore(None), SimDriver(seed=1), sink=RecSink())
    assert s.mode.name == "auto" and s.first_start == [] and not s.servos_off


def test_setpin_writes_no_pose_and_older_state_files_count_as_driven(tmp_path):
    args = SimpleNamespace(config_dir=str(tmp_path))
    answers = iter(["2468", "2468"])
    assert tools.setpin(args, ask=lambda prompt: next(answers)) == 0
    assert StateStore.load(tmp_path / "state.json").known is False
    (tmp_path / "state.json").write_text(json.dumps({"pan": 12, "tilt": 70, "mode": "auto"}), encoding="utf-8")
    st = StateStore.load(tmp_path / "state.json")
    assert st.known and (st.pan, st.tilt) == (12, 70)


ALL_OK = [("serial port", True, "/dev/ttyACM0"), ("firmware", True, "1.0.0"), ("sample frames", True, ""),
          ("light sensors", True, ""), ("BH1750", True, "300 lux"), ("servos", True, "")]


def doctor_steps(tmp_path, results, monkeypatch, installed=True):
    from brainsolpi import doctor, service

    monkeypatch.setattr(service, "installed", lambda: installed)
    monkeypatch.setattr(doctor, "address", lambda: "http://brainsol.local:8080")
    doc = doctor.Doctor(config_dir=tmp_path, out=lambda *a, **k: None, live=False)
    doc.results = list(results)
    return doc.next_steps()


def test_the_doctor_ends_a_fresh_setup_with_every_step_in_order(tmp_path, monkeypatch):
    steps = doctor_steps(tmp_path, ALL_OK, monkeypatch)
    assert steps[0] == "set the admin pin with: brainsolpi setpin"
    assert "brainsolpi centre" in steps[1]
    assert steps[2] == "start the tracker with: sudo systemctl start brainsolpi"
    assert steps[3] == "open http://brainsol.local:8080 in a browser and unlock the admin tools with the pin"
    assert "calibrate tab" in steps[4] and "capture dark" in steps[4] and "save the calibration" in steps[4]
    assert "holds until the calibration is saved" in steps[5]
    # the doctor only read the folder, it wrote nothing of its own
    assert list(tmp_path.iterdir()) == []


def test_the_doctor_on_a_set_up_pi_only_points_to_the_page(tmp_path, monkeypatch):
    s = Settings(tmp_path / "settings.json")
    s.pin_hash = "pbkdf2_sha256$1000$00$00"
    cal = s.calib("bridge")
    cal["saved"] = True
    s.set_calib("bridge", cal)
    s.save()
    st = StateStore(tmp_path / "state.json")
    st.known = True
    st.save(force=True)
    steps = doctor_steps(tmp_path, ALL_OK, monkeypatch, installed=False)
    assert steps == [
        "start the tracker with: brainsolpi run",
        "open http://brainsol.local:8080 in a browser and unlock the admin tools with the pin",
        "the calibration is saved, pick a mode in the control tab",
    ]


@pytest.mark.parametrize("note,first", [
    ("no port", "plug the usb cable into the pi and into the board"),
    ("no board answered", "flash the bridge firmware with: brainsolpi flash"),
    ("the service holds the board", "stop the tracker service with: sudo systemctl stop brainsolpi"),
])
def test_the_doctor_names_the_fix_for_a_missing_board(tmp_path, monkeypatch, note, first):
    steps = doctor_steps(tmp_path, [("serial port", False, note)], monkeypatch)
    assert steps[0] == first
    assert "then run brainsolpi doctor again" in steps


def test_the_doctor_puts_broken_cables_before_everything_else(tmp_path, monkeypatch):
    results = [r if r[0] != "light sensors" else ("light sensors", False, "") for r in ALL_OK]
    steps = doctor_steps(tmp_path, results, monkeypatch)
    assert steps == ["fix the sensor cables as step 4 says", "then run brainsolpi doctor again"]


def test_a_fresh_fake_board_gets_no_pulse_until_a_mode_is_picked():
    board = FakeBoard(boot_s=0.2, seed=2, rest=(35.0, 25.0))
    d = BridgeDriver("fake", opener=board.opener, profile="bridge")
    eng = Engine(Settings(), StateStore(None), d, sink=RecSink())
    d.start_sync()
    try:
        def run(seconds):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                eng.tick(time.monotonic())
                time.sleep(0.02)

        run(1.5)
        assert eng.link and eng.mode.name == "hold"
        assert board.first_move is None and not board.attached
        assert board.angles() == (35.0, 25.0)
        eng.set_mode("auto")
        run(0.5)
        assert board.first_move == (1500, 1500)
        assert board.attached
    finally:
        d.stop_sync()
        board.close()
