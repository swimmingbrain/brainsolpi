import asyncio
import json
import logging
import sys
from types import SimpleNamespace

import serial

from brainsolpi import app
from brainsolpi.autoflash import AutoFlash, board_key, run_logged
from brainsolpi.cli import build_parser
from brainsolpi.config import Settings
from brainsolpi.drivers.detect import BoardWatch, UsbInfo, find_board, probe
from brainsolpi.drivers.fakeboard import FakeBoard
from brainsolpi.engine import Engine
from brainsolpi.paths import repo_root
from brainsolpi.state import StateStore

from .conftest import RecSink

PORT = "/dev/ttyACM0"
UNO = UsbInfo(0x2341, 0x0043, "75735353038351E0A1A1")
CH340 = UsbInfo(0x1A86, 0x7523, None)


class KitBoard(FakeBoard):
    # the uno as it comes out of the kit: its own code prints now and then and never answers the
    # brainsol hello, until avrdude wrote the bridge firmware

    def __init__(self, **kw):
        super().__init__(boot_s=0.1, **kw)
        self.bridge = False

    def _run(self, port, halt):
        if self.bridge:
            return super()._run(port, halt)
        try:
            while not halt.wait(0.1):
                port.write(b"light 512\r\n")
        except serial.SerialException:
            return


class Avrdude:
    # stands in for avrdude: it puts the bridge firmware on the fake board, or fails like a bad cable

    def __init__(self, board=None, rc=0, sticks=True):
        self.board = board
        self.rc = rc
        self.sticks = sticks
        self.calls = []

    def __call__(self, cmd, cwd):
        self.calls.append(cmd)
        if self.rc == 0 and self.board is not None and self.sticks:
            self.board.bridge = True
        return self.rc


class EngineStub:
    # the two calls of the engine the watch makes, with what they said

    def __init__(self):
        self.events = []
        self.notes = []

    def event(self, lvl, msg):
        self.events.append((lvl, msg))

    def note(self, lvl, msg):
        self.notes.append((lvl, msg))


def hexfile(tmp_path):
    path = tmp_path / "brainsol_bridge.hex"
    path.write_text(":00000001FF\n", encoding="utf-8")
    return path


def flasher(tmp_path, runner, state=None):
    return AutoFlash(state or StateStore(None), avrdude="/usr/bin/avrdude", hexfile=hexfile(tmp_path), runner=runner)


async def watch_for(watch, flash, seconds, until=None):
    # the end of a watch halts it, a test that goes on with the same one starts it again
    watch.halt.clear()
    engine = EngineStub()
    stop = asyncio.Event()
    after = {"action": None}
    task = asyncio.create_task(app._watch_board(watch, engine, stop, after, True, every=0.05, flasher=flash))
    end = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < end and not task.done():
        if until is not None and until(engine):
            break
        await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return engine, after


def test_only_an_uno_r3_with_the_atmega16u2_counts_as_an_uno(monkeypatch):
    from serial.tools import list_ports

    from brainsolpi.drivers import detect

    fake = [
        SimpleNamespace(device="/dev/ttyACM0", vid=0x2341, pid=0x0043, serial_number="7573"),
        SimpleNamespace(device="/dev/ttyUSB0", vid=0x1A86, pid=0x7523, serial_number=None),
        SimpleNamespace(device="/dev/ttyAMA0", vid=None, pid=None, serial_number=None),
    ]
    monkeypatch.setattr(list_ports, "comports", lambda: fake)
    info = detect.usb_info("/dev/ttyACM0")
    assert info == UsbInfo(0x2341, 0x0043, "7573") and info.uno and info.ids == "2341:0043"
    assert not detect.usb_info("/dev/ttyUSB0").uno
    assert detect.usb_info("/dev/ttyAMA0") is None and detect.usb_info("/dev/ttyACM9") is None
    assert UsbInfo(0x2A03, 0x0043, None).uno and UsbInfo(0x2341, 0x0243, None).uno
    # an ftdi or cp210x adapter, or an older uno with another usb chip, is no candidate
    assert not any(UsbInfo(v, p, None).uno for v, p in ((0x0403, 0x6001), (0x10C4, 0xEA60), (0x2341, 0x0001)))


def test_probe_counts_a_port_as_silent_only_when_it_opened_and_stayed_quiet():
    kit = KitBoard()
    silent = set()
    assert probe(PORT, kit.opener, 0.4, silent=silent) is None
    assert silent == {PORT}
    # a port that cannot be opened, busy or gone, said nothing because it was never asked
    kit.unplug()
    silent.clear()
    assert probe(PORT, kit.opener, 0.4, silent=silent) is None
    assert silent == set()
    # a brainsol board answers, that is no silence either
    board = FakeBoard(boot_s=0.1)
    got = probe(PORT, board.opener, 2.0, silent=silent)
    assert got is not None and silent == set()
    got[1].close()
    board.close()


def test_the_look_at_the_start_names_the_silent_ports():
    kit = KitBoard()
    silent = set()
    assert find_board(0.5, opener=kit.opener, ports=[PORT], silent=silent) is None
    assert silent == {PORT}
    kit.close()


async def test_a_kit_uno_plugged_in_later_gets_the_firmware_once_and_the_service_restarts(tmp_path):
    kit = KitBoard()
    ports = []
    watch = BoardWatch(lister=lambda: list(ports), opener=kit.opener, timeout=0.4, start=[], info=lambda p: UNO)
    avrdude = Avrdude(kit)
    state = StateStore(tmp_path / "state.json")
    ports.append(PORT)
    engine, after = await watch_for(watch, flasher(tmp_path, avrdude, state), 10.0)
    # two looks that heard nothing, then avrdude once with the same command as brainsolpi flash
    assert len(avrdude.calls) == 1
    assert avrdude.calls[0][1:] == ["-p", "atmega328p", "-c", "arduino", "-P", PORT, "-b", "115200", "-D",
                                    "-U", "flash:w:brainsol_bridge.hex:i"]
    assert [lvl for lvl, _ in engine.notes] == ["info"]
    assert "does not answer the brainsol hello" in engine.notes[0][1] and "writing the bridge firmware" in engine.notes[0][1]
    assert "serial.autoflash false" in engine.notes[0][1]
    assert after["action"] == "restart"
    assert "a board answered on /dev/ttyACM0" in engine.events[-1][1]
    # the board is marked in the state file before the restart, so it never gets a second go
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["flashed"] == [board_key(PORT, UNO)]
    kit.close()


async def test_a_kit_uno_that_was_there_at_the_start_gets_the_firmware_at_the_first_look(tmp_path):
    kit = KitBoard()
    watch = BoardWatch(lister=lambda: [PORT], opener=kit.opener, timeout=0.4, start=[PORT], silent={PORT},
                       info=lambda p: UNO)
    avrdude = Avrdude(kit)
    engine, after = await watch_for(watch, flasher(tmp_path, avrdude), 10.0)
    assert len(avrdude.calls) == 1 and after["action"] == "restart"
    # the six seconds of auto at the start were the look, the watch did not open the port before
    assert kit.opens == 1
    kit.close()


async def test_a_failed_flash_goes_back_to_the_sim_and_tries_again_only_after_a_new_plug(tmp_path):
    kit = KitBoard()
    ports = [PORT]
    watch = BoardWatch(lister=lambda: list(ports), opener=kit.opener, timeout=0.3, start=[PORT], silent={PORT},
                       info=lambda p: UNO)
    avrdude = Avrdude(kit, rc=1)
    state = StateStore(None)
    flash = flasher(tmp_path, avrdude, state)
    engine, after = await watch_for(watch, flash, 2.0)
    # 115200 and then 57600 baud, like brainsolpi flash, and then nothing more
    assert [c[c.index("-b") + 1] for c in avrdude.calls] == ["115200", "57600"]
    assert after["action"] is None and state.flashed == []
    assert engine.notes[-1][0] == "warn" and "failed, the sim goes on" in engine.notes[-1][1]
    assert "brainsolpi flash" in engine.notes[-1][1]
    # the same plug never gets a second try, however long the watch runs
    engine, after = await watch_for(watch, flash, 1.5)
    assert len(avrdude.calls) == 2 and engine.notes == []
    # out and in again is a new plug, it gets one more try after two quiet looks
    ports.clear()
    watch.check()
    ports.append(PORT)
    engine, after = await watch_for(watch, flash, 6.0, until=lambda e: len(avrdude.calls) >= 4)
    assert len(avrdude.calls) == 4
    kit.close()


async def test_a_board_that_got_the_firmware_once_is_never_flashed_by_the_service_again(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "HELLO_S", 0.5)
    kit = KitBoard()
    ports = [PORT]
    watch = BoardWatch(lister=lambda: list(ports), opener=kit.opener, timeout=0.3, start=[PORT], silent={PORT},
                       info=lambda p: UNO)
    # avrdude says it worked, but the board still does not answer
    avrdude = Avrdude(kit, sticks=False)
    state = StateStore(None)
    flash = flasher(tmp_path, avrdude, state)
    engine, after = await watch_for(watch, flash, 10.0, until=lambda e: len(e.notes) >= 2)
    assert len(avrdude.calls) == 1 and after["action"] is None
    assert engine.notes[-1][0] == "warn" and "does not say hello" in engine.notes[-1][1]
    assert state.flashed == [board_key(PORT, UNO)]
    ports.clear()
    watch.check()
    ports.append(PORT)
    engine, after = await watch_for(watch, flash, 3.0, until=lambda e: e.notes)
    assert len(avrdude.calls) == 1
    assert "wrote the bridge firmware to this board once already" in engine.notes[-1][1]
    kit.close()


async def test_a_silent_ch340_is_never_flashed(tmp_path, caplog):
    kit = KitBoard()
    watch = BoardWatch(lister=lambda: [PORT], opener=kit.opener, timeout=0.3, start=[PORT], silent={PORT},
                       info=lambda p: CH340)
    avrdude = Avrdude(kit)
    with caplog.at_level(logging.INFO, logger="brainsolpi"):
        engine, after = await watch_for(watch, flasher(tmp_path, avrdude), 1.0)
    assert avrdude.calls == [] and engine.notes == [] and after["action"] is None
    assert any("usb 1a86:7523" in r.getMessage() and "left alone" in r.getMessage() for r in caplog.records)
    kit.close()


async def test_without_the_switch_the_watch_only_points_to_brainsolpi_flash(tmp_path):
    kit = KitBoard()
    watch = BoardWatch(lister=lambda: [PORT], opener=kit.opener, timeout=0.3, start=[PORT], silent={PORT},
                       info=lambda p: UNO)
    engine, after = await watch_for(watch, None, 1.0)
    assert engine.notes == [("info", "the uno on /dev/ttyACM0 (usb 2341:0043) does not answer the brainsol "
                                     "hello, it still runs other code. flash the bridge firmware with: brainsolpi flash")]
    assert after["action"] is None
    kit.close()


def test_avrdude_and_the_hex_have_to_be_there(tmp_path):
    state = StateStore(None)
    assert AutoFlash(state, avrdude="/usr/bin/avrdude", hexfile=hexfile(tmp_path)).refuse(PORT, UNO) is None
    no_avrdude = AutoFlash(state, avrdude="", hexfile=hexfile(tmp_path))
    no_avrdude.avrdude = None
    assert "sudo apt install avrdude" in no_avrdude.refuse(PORT, UNO)
    no_hex = AutoFlash(state, avrdude="/usr/bin/avrdude", hexfile=tmp_path / "gone.hex")
    assert "no firmware file" in no_hex.refuse(PORT, UNO)


def test_the_service_does_it_by_itself_a_run_by_hand_only_with_the_flag():
    settings, state = Settings(), StateStore(None)
    run = build_parser().parse_args(["run"])
    assert run.autoflash is False
    assert app.autoflash(run, settings, state, inside=lambda: False) is None
    assert isinstance(app.autoflash(run, settings, state, inside=lambda: True), AutoFlash)
    by_hand = build_parser().parse_args(["run", "--autoflash"])
    assert isinstance(app.autoflash(by_hand, settings, state, inside=lambda: False), AutoFlash)
    for driver in ("sim", "bridge", "fake"):
        args = build_parser().parse_args(["run", "--autoflash", "--driver", driver])
        assert app.autoflash(args, settings, state, inside=lambda: True) is None


def test_the_setting_turns_it_off_for_the_service_and_by_hand():
    assert Settings().data["serial"]["autoflash"] is True
    off = Settings(None, {"serial": {"autoflash": False}})
    assert off.data["serial"] == {"rate": 50, "slew": 30, "autoflash": False}
    for argv in (["run"], ["run", "--autoflash"]):
        assert app.autoflash(build_parser().parse_args(argv), off, StateStore(None), inside=lambda: True) is None


def test_the_service_unit_runs_auto_and_needs_no_new_line_for_it():
    # an installed unit stays as it is, so deploy/update.sh brings the step without sudo
    unit = (repo_root() / "deploy" / "brainsolpi.service").read_text(encoding="utf-8")
    line = next(x for x in unit.splitlines() if x.startswith("ExecStart="))
    args = build_parser().parse_args(line.split("/bin/brainsolpi ", 1)[1].split())
    assert (args.command, args.driver, args.autoflash) == ("run", "auto", False)


def test_the_boards_the_service_flashed_survive_a_restart(tmp_path):
    path = tmp_path / "state.json"
    st = StateStore.load(path)
    st.flashed.append(board_key(PORT, UNO))
    st.save(force=True)
    assert StateStore.load(path).flashed == ["2341:0043 75735353038351E0A1A1"]
    path.write_text(json.dumps({"simpose": None, "flashed": ["ok", 5, None, "x" * 500]}), encoding="utf-8")
    assert StateStore.load(path).flashed == ["ok"]
    # without a serial number the port and the ids have to do
    assert board_key(PORT, UsbInfo(0x2341, 0x0043, None)) == "2341:0043 /dev/ttyACM0"


def test_avrdude_output_goes_to_the_journal_when_it_fails(caplog):
    code = "import sys; print('avrdude: stk500_recv(): programmer is not responding'); sys.exit(1)"
    with caplog.at_level(logging.INFO, logger="brainsolpi"):
        assert run_logged([sys.executable, "-c", code], ".") == 1
    assert any("programmer is not responding" in r.getMessage() for r in caplog.records)


def test_an_admin_who_unlocks_later_still_reads_the_last_note_about_the_board():
    sink = RecSink()
    eng = Engine(Settings(), StateStore(None), app.SimDriver(seed=1), sink=sink)
    eng.note("warn", "writing the bridge firmware to the uno on /dev/ttyACM0 failed, the sim goes on")
    eng.note("info", "the uno on /dev/ttyACM0 does not answer the brainsol hello")
    sink.admin_msgs.clear()
    eng.remind()
    assert [m["msg"] for m in sink.admin_msgs] == ["the uno on /dev/ttyACM0 does not answer the brainsol hello"]


def test_auto_tells_the_watch_which_ports_it_probed(monkeypatch):
    kit = KitBoard()
    monkeypatch.setattr(app, "candidates", lambda: [(PORT, "Arduino")])
    monkeypatch.setattr(app, "AUTO_WAIT_S", 0.5)
    monkeypatch.setattr(app, "find_board", lambda t, ports, silent: find_board(t, kit.opener, ports, silent))
    looked = {}
    args = SimpleNamespace(driver="auto", port=None)
    driver = asyncio.run(app.open_driver(args, Settings(), looked))
    assert driver.name == "sim" and looked == {"ports": [PORT], "silent": {PORT}}
    watch = app.board_watch(args, looked)
    assert watch.seen == {PORT} and watch.silent == {PORT}
    kit.close()
