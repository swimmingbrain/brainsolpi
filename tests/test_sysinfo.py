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
