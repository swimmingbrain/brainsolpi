from types import SimpleNamespace

import pytest

from brainsolpi import service, tools


class Runner:
    # records the commands and answers with the return codes it was given
    def __init__(self, codes=None):
        self.calls = []
        self.codes = codes or {}

    def __call__(self, cmd, **kw):
        self.calls.append(" ".join(cmd))
        return SimpleNamespace(returncode=self.codes.get(" ".join(cmd), 0))


def test_paused_stops_and_starts_a_running_service(monkeypatch):
    monkeypatch.setattr(service, "active", lambda run: True)
    run = Runner()
    lines = []
    with service.Paused("testing", out=lines.append, run=run) as p:
        assert p.stopped
        assert run.calls == ["sudo systemctl stop brainsolpi"]
    assert run.calls[-1] == "sudo systemctl start brainsolpi"
    assert "sudo may ask for your password" in lines[0]


def test_paused_does_nothing_without_a_service(monkeypatch):
    monkeypatch.setattr(service, "active", lambda run: False)
    run = Runner()
    with service.Paused("testing", out=lambda *a: None, run=run):
        pass
    assert run.calls == []


def test_a_service_that_cannot_be_stopped_is_said_plainly(monkeypatch):
    monkeypatch.setattr(service, "active", lambda run: True)
    run = Runner({"sudo systemctl stop brainsolpi": 1})
    with pytest.raises(service.ServiceBusy, match="sudo systemctl stop brainsolpi"):
        with service.Paused("testing", out=lambda *a: None, run=run):
            pass
    assert "sudo systemctl start brainsolpi" not in run.calls


def test_not_on_linux_there_is_no_service(monkeypatch):
    monkeypatch.setattr(service.sys, "platform", "win32")
    assert not service.active(Runner())
    assert not service.installed()


def test_flash_runs_avrdude_between_stop_and_start_and_waits_for_hello(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(tools.shutil, "which", lambda name: "/usr/bin/avrdude")
    monkeypatch.setattr(service, "active", lambda run: True)
    hexfile = tmp_path / "brainsol_bridge.hex"
    hexfile.write_text(":00000001FF\n", encoding="utf-8")
    order = []
    run = Runner()

    def svc(cmd, **kw):
        order.append(cmd[2])
        return run(cmd, **kw)

    def avrdude(cmd, cwd):
        order.append("avrdude")
        return 0

    def hello(port):
        order.append("hello")
        return "I,brainsol,1.0.0,1"

    pause = service.Paused("flashing", run=svc)
    args = SimpleNamespace(port="/dev/ttyACM0", hex=str(hexfile))
    assert tools.flash(args, runner=avrdude, hello=hello, pause=pause) == 0
    # the identity check runs while the service still rests, it would take the port back
    assert order == ["stop", "avrdude", "hello", "start"]
    assert "the board answers: I,brainsol,1.0.0,1" in capsys.readouterr().out


def test_flash_without_an_answer_points_to_the_doctor(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(tools.shutil, "which", lambda name: "/usr/bin/avrdude")
    hexfile = tmp_path / "brainsol_bridge.hex"
    hexfile.write_text(":00000001FF\n", encoding="utf-8")
    args = SimpleNamespace(port="/dev/ttyACM0", hex=str(hexfile))
    # the real pause would stop a service that runs on this machine
    monkeypatch.setattr(service, "active", lambda run: False)
    assert tools.flash(args, runner=lambda cmd, cwd: 0, hello=lambda port: None) == 0
    assert "brainsolpi doctor" in capsys.readouterr().out


def test_flash_names_the_dialout_group_without_port_access(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(tools.shutil, "which", lambda name: "/usr/bin/avrdude")
    monkeypatch.setattr(tools, "_no_access", lambda port: True)
    hexfile = tmp_path / "brainsol_bridge.hex"
    hexfile.write_text(":00000001FF\n", encoding="utf-8")
    calls = []
    args = SimpleNamespace(port="/dev/ttyACM0", hex=str(hexfile))
    assert tools.flash(args, runner=lambda cmd, cwd: calls.append(cmd) or 0) == 1
    assert calls == []
    assert "usermod -aG dialout" in capsys.readouterr().out
