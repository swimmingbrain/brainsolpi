import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from brainsolpi import paths, tools
from brainsolpi.auth import verify_pin
from brainsolpi.cli import build_parser
from brainsolpi.doctor import Doctor
from brainsolpi.drivers.fakeboard import FakeBoard


def test_run_defaults_match_the_service_unit():
    args = build_parser().parse_args(["run"])
    assert args.driver == "auto"
    assert args.host == "0.0.0.0"
    assert args.http_port == 8080
    args = build_parser().parse_args(["run", "--driver", "sim", "--http-port", "9000", "--pin", "2468"])
    assert (args.driver, args.http_port, args.pin) == ("sim", 9000, "2468")


def test_demo_runs_the_sim_on_this_computer_in_a_folder_that_goes_away(monkeypatch, capsys):
    from brainsolpi import app, cli

    seen = {}

    def fake_run(args):
        seen["args"] = args
        seen["dirs"] = (Path(args.config_dir), Path(args.data_dir))
        assert seen["dirs"][0].parent.exists()
        args.ready(None)
        return 0

    monkeypatch.setattr(app, "run", fake_run)
    assert cli.main(["demo"]) == 0
    a = seen["args"]
    assert (a.driver, a.host, a.http_port) == ("sim", "127.0.0.1", 8080)
    assert len(a.pin) == 4 and a.pin.isdigit()
    assert not seen["dirs"][0].parent.exists()
    out = capsys.readouterr().out
    assert "https://sol.swimmingbrain.dev/?pi=ws://localhost:8080" in out
    assert f"admin pin for this run: {a.pin}" in out
    assert cli.build_parser().parse_args(["demo", "--http-port", "9001"]).http_port == 9001


def test_repo_paths():
    root = paths.repo_root()
    assert (root / "pyproject.toml").is_file()
    assert paths.default_hex() == root / "firmware" / "brainsol_bridge.hex"


def test_version_from_the_module():
    out = subprocess.run([sys.executable, "-m", "brainsolpi", "--version"], capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.startswith("brainsolpi ")


def answers(*items):
    it = iter(items)
    return lambda prompt: next(it)


def test_setpin_stores_a_hash_and_ends_old_sessions(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"tokens": [["abc", 9e12]]}), encoding="utf-8")
    args = SimpleNamespace(config_dir=str(tmp_path))
    assert tools.setpin(args, ask=answers("2468", "2469")) == 1
    assert tools.setpin(args, ask=answers("12", "12")) == 1
    assert tools.setpin(args, ask=answers("2468", "2468")) == 0
    stored = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["auth"]["pin"]
    assert verify_pin("2468", stored)
    assert "2468" not in stored
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["tokens"] == []


def test_setpin_check_answers_by_exit_code_and_writes_nothing(tmp_path, capsys):
    from brainsolpi import cli

    args = ["setpin", "--check", "--config-dir", str(tmp_path)]
    assert cli.main(args) == 1
    assert "no admin pin" in capsys.readouterr().out
    # a fresh pi keeps its config folder empty until something really sets up a pin
    assert list(tmp_path.iterdir()) == []
    assert tools.setpin(SimpleNamespace(config_dir=str(tmp_path)), ask=answers("2468", "2468")) == 0
    capsys.readouterr()
    assert cli.main(args) == 0
    assert "an admin pin is set" in capsys.readouterr().out
    # a settings file without a pin, like the service writes it on its first start
    (tmp_path / "settings.json").write_text(json.dumps({"name": "brainsol"}), encoding="utf-8")
    assert cli.main(args) == 1


def test_flash_explains_a_missing_avrdude(monkeypatch, capsys):
    monkeypatch.setattr(tools.shutil, "which", lambda name: None)
    assert tools.flash(SimpleNamespace(port="COM3", hex=None)) == 1
    assert "apt install avrdude" in capsys.readouterr().out


def test_flash_needs_the_hex(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(tools.shutil, "which", lambda name: "/usr/bin/avrdude")
    assert tools.flash(SimpleNamespace(port="COM3", hex=str(tmp_path / "nope.hex"))) == 1
    assert "no firmware file" in capsys.readouterr().out


def test_flash_retries_once_at_57600(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(tools.shutil, "which", lambda name: "/usr/bin/avrdude")
    hexfile = tmp_path / "brainsol_bridge.hex"
    hexfile.write_text(":00000001FF\n", encoding="utf-8")
    calls = []

    def runner(cmd, cwd):
        calls.append((cmd, cwd))
        return 1 if len(calls) == 1 else 0

    assert tools.flash(SimpleNamespace(port="/dev/ttyACM0", hex=str(hexfile)), runner=runner) == 0
    first, second = calls[0][0], calls[1][0]
    assert first[1:] == ["-p", "atmega328p", "-c", "arduino", "-P", "/dev/ttyACM0", "-b", "115200", "-D",
                         "-U", "flash:w:brainsol_bridge.hex:i"]
    assert second[second.index("-b") + 1] == "57600"
    assert calls[0][1] == str(tmp_path)
    assert "57600" in capsys.readouterr().out


def test_doctor_walks_through_every_step_on_the_fake_board():
    lines = []
    doc = Doctor(fake=True, out=lambda *a, **k: lines.append(" ".join(str(x) for x in a)), live=False, quick=True)
    assert doc.run() == 0
    text = "\n".join(lines)
    assert "step 6 of 6" in text
    assert [ok for _, ok, _ in doc.results] == [True] * 6
    assert lines[-3] == "\nnext steps" and "brainsolpi demo" in lines[-1]
    for name in ("L ok", "R ok", "U ok", "D ok"):
        assert name in text


class SwappedBoard(FakeBoard):
    # the cables of L and R swapped inside the board

    @property
    def covered(self):
        return self._cov

    @covered.setter
    def covered(self, value):
        self._cov = {1 if k == 0 else 0 if k == 1 else k for k in value}


def test_doctor_spots_swapped_sensor_cables():
    lines = []
    doc = Doctor(fake=True, out=lambda *a, **k: lines.append(" ".join(str(x) for x in a)), live=False, quick=True)
    doc.board = SwappedBoard(boot_s=0.3, seed=4)
    assert doc.run() == 1
    text = "\n".join(lines)
    assert "R reacted instead of L" in text and "look swapped" in text
