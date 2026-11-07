import time

from brainsolpi import sysinfo
from brainsolpi.sysinfo import SysInfo


def test_sample_has_the_three_keys_and_sane_values():
    s = SysInfo()
    first = s.sample()
    assert set(first) == {"cpu", "temp", "mem"}
    assert first["cpu"] is None
    time.sleep(0.05)
    second = s.sample()
    for key in ("cpu", "mem"):
        v = second[key]
        assert v is None or 0 <= v <= 100
    assert second["temp"] is None or -40 < second["temp"] < 130


def test_linux_files_are_parsed(tmp_path, monkeypatch):
    stat = tmp_path / "stat"
    mem = tmp_path / "meminfo"
    therm = tmp_path / "temp"
    stat.write_text("cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 1 2 3 4\n", encoding="utf-8")
    mem.write_text("MemTotal:  1000 kB\nMemFree: 100 kB\nMemAvailable:   250 kB\n", encoding="utf-8")
    therm.write_text("48312\n", encoding="utf-8")
    monkeypatch.setattr(sysinfo, "PROC_STAT", stat)
    monkeypatch.setattr(sysinfo, "MEMINFO", mem)
    monkeypatch.setattr(sysinfo, "THERMAL", therm)
    s = SysInfo()
    s._win = None
    assert s.sample() == {"cpu": None, "temp": 48.312, "mem": 75.0}
    stat.write_text("cpu  150 0 150 900 0 0 0 0 0 0\n", encoding="utf-8")
    # 100 busy out of 200 ticks
    assert s.cpu() == 50.0


def test_missing_files_give_none(tmp_path, monkeypatch):
    monkeypatch.setattr(sysinfo, "PROC_STAT", tmp_path / "nope")
    monkeypatch.setattr(sysinfo, "MEMINFO", tmp_path / "nope")
    monkeypatch.setattr(sysinfo, "THERMAL", tmp_path / "nope")
    s = SysInfo()
    s._win = None
    assert s.sample() == {"cpu": None, "temp": None, "mem": None}


def test_the_supply_hint_fits_the_model_of_the_pi(tmp_path, monkeypatch):
    model = tmp_path / "model"
    monkeypatch.setattr(sysinfo, "MODEL", model)
    model.write_bytes(b"Raspberry Pi 3 Model B Plus Rev 1.3\x00")
    assert sysinfo.supply() == "the official 5.1 V 2.5 A micro usb supply of the pi 3b+"
    model.write_bytes(b"Raspberry Pi 4 Model B Rev 1.5\x00")
    assert sysinfo.supply() == "the official 5.1 V 3 A usb c supply of the pi 4"
    # another computer, or a model it does not know, gets both
    model.unlink()
    both = sysinfo.supply()
    assert "5.1 V 2.5 A micro usb supply for a pi 3b+" in both and "5.1 V 3 A usb c supply for a pi 4" in both


def test_a_board_restart_names_the_supply_of_this_pi(monkeypatch):
    from brainsolpi.drivers import bridge

    monkeypatch.setattr(bridge, "supply", lambda: "the official 5.1 V 3 A usb c supply of the pi 4")
    d = bridge.BridgeDriver("fake")
    d._restarted(100.0)
    (lvl, msg), = d.drain_events()
    assert lvl == "warn" and "restarted by itself" in msg
    assert msg.endswith("it needs the official 5.1 V 3 A usb c supply of the pi 4 or a better one")


def test_low_voltage_reads_the_throttled_bits_of_the_pi(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(sysinfo.shutil, "which", lambda name: None)
    assert sysinfo.low_voltage() is None
    monkeypatch.setattr(sysinfo.shutil, "which", lambda name: "/usr/bin/vcgencmd")

    def answer(text):
        return lambda cmd, **kw: SimpleNamespace(stdout=text)

    assert sysinfo.low_voltage(answer("throttled=0x0\n")) is False
    # low voltage right now, and low voltage at some point since boot, both count
    assert sysinfo.low_voltage(answer("throttled=0x50005\n")) is True
    assert sysinfo.low_voltage(answer("throttled=0x50000\n")) is True
    # only throttling from heat is no power problem
    assert sysinfo.low_voltage(answer("throttled=0x80008\n")) is False
    assert sysinfo.low_voltage(answer("error=2 error_msg=\"no such command\"\n")) is None

    def broken(cmd, **kw):
        raise OSError("vcgencmd failed")

    assert sysinfo.low_voltage(broken) is None
