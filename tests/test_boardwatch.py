import asyncio
from types import SimpleNamespace

from brainsolpi import app
from brainsolpi.drivers import detect
from brainsolpi.drivers.detect import BoardWatch
from brainsolpi.drivers.fakeboard import FakeBoard, pipe_pair


class Opener:
    # counts the opens per port and keeps the host ends, so a test sees what was closed

    def __init__(self, board=None):
        self.board = board
        self.opened: list[str] = []
        self.ends = []

    def __call__(self, port):
        self.opened.append(port)
        if self.board is not None:
            end = self.board.opener(port)
        else:
            # a port with nothing behind it that ever speaks
            end = pipe_pair()[0]
        self.ends.append(end)
        return end


def test_the_watch_skips_the_ports_of_the_start_and_finds_a_board_plugged_in_later():
    ports = ["/dev/ttyUSB0"]
    opener = Opener(FakeBoard(boot_s=0.2))
    w = BoardWatch(lister=lambda: list(ports), opener=opener, timeout=3.0)
    assert w.check() is None
    assert w.check() is None
    # the port that was there at the start had its chance already, a look only reads the list
    assert opener.opened == []
    ports.append("/dev/ttyACM0")
    got = w.check()
    assert got is not None
    port, ser, ident = got
    assert port == "/dev/ttyACM0" and ident.fw == "1.0.0"
    assert opener.opened == ["/dev/ttyACM0"]
    ser.close()
    opener.board.close()


def test_a_port_that_never_answers_is_left_alone_until_it_is_plugged_in_again():
    ports = []
    opener = Opener()
    w = BoardWatch(lister=lambda: list(ports), opener=opener, timeout=0.2)
    assert w.check() is None
    ports.append("/dev/ttyACM0")
    for _ in range(5):
        assert w.check() is None
    # a second look in case the first open came too early, then never again
    assert opener.opened == ["/dev/ttyACM0"] * BoardWatch.TRIES
    assert all(not end.is_open for end in opener.ends)
    ports.clear()
    assert w.check() is None
    ports.append("/dev/ttyACM0")
    assert w.check() is None
    assert len(opener.opened) == BoardWatch.TRIES + 1


def test_the_watch_opens_only_ports_that_look_like_a_board(monkeypatch):
    from serial.tools import list_ports

    fake = [
        SimpleNamespace(device="/dev/ttyAMA0", description="uart of the pi", vid=None),
        SimpleNamespace(device="/dev/ttyS0", description="console", vid=None),
        SimpleNamespace(device="/dev/rfcomm0", description="Bluetooth link", vid=None),
        SimpleNamespace(device="/dev/ttyACM0", description="Arduino Uno", vid=0x2341),
        SimpleNamespace(device="/dev/ttyUSB0", description="some usb serial", vid=0x9999),
        SimpleNamespace(device="COM7", description="a modem", vid=None),
        SimpleNamespace(device="COM5", description="USB-SERIAL CH340", vid=0x1A86),
    ]
    monkeypatch.setattr(list_ports, "comports", lambda: fake)
    assert detect.likely_ports() == ["/dev/ttyACM0", "COM5", "/dev/ttyUSB0"]
    # the probe of auto at the start still tries everything that is not the uart or bluetooth
    assert [dev for dev, _ in detect.candidates()] == ["/dev/ttyACM0", "COM5", "/dev/ttyUSB0", "COM7"]


async def _watch(can_restart: bool):
    ports = []
    opener = Opener(FakeBoard(boot_s=0.2))
    w = BoardWatch(lister=lambda: list(ports), opener=opener, timeout=3.0)
    events = []
    engine = SimpleNamespace(event=lambda lvl, msg: events.append((lvl, msg)))
    stop = asyncio.Event()
    after = {"action": None}
    task = asyncio.create_task(app._watch_board(w, engine, stop, after, can_restart, every=0.05))
    await asyncio.sleep(0.2)
    assert not task.done() and events == []
    ports.append("/dev/ttyACM0")
    await asyncio.wait_for(task, 10.0)
    # the new process opens the port again, so the watch let go of it
    assert opener.ends and not opener.ends[-1].is_open
    assert w.halt.is_set()
    opener.board.close()
    return events, stop.is_set(), after["action"]


async def test_a_board_plugged_in_later_restarts_the_service_on_linux():
    events, stopped, action = await _watch(can_restart=True)
    assert stopped and action == "restart"
    assert len(events) == 1 and events[0][0] == "info"
    assert "a board answered on /dev/ttyACM0" in events[0][1] and "restarting with the bridge driver" in events[0][1]


async def test_a_board_plugged_in_later_is_only_reported_where_there_is_no_restart():
    events, stopped, action = await _watch(can_restart=False)
    assert not stopped and action is None
    assert len(events) == 1 and "start it again to use the board" in events[0][1]


async def test_stopping_the_service_ends_the_watch_and_a_running_look():
    ports = []
    w = BoardWatch(lister=lambda: list(ports), opener=Opener(), timeout=5.0)
    engine = SimpleNamespace(event=lambda lvl, msg: None)
    stop = asyncio.Event()
    task = asyncio.create_task(app._watch_board(w, engine, stop, {"action": None}, True, every=0.05))
    await asyncio.sleep(0.1)
    ports.append("/dev/ttyACM0")
    await asyncio.sleep(0.2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert w.halt.is_set()


def test_a_given_port_is_the_only_one_the_watch_looks_at(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "likely_ports", lambda: ["/dev/ttyACM0", "/dev/ttyACM1"])
    w = app.board_watch(SimpleNamespace(port="/dev/ttyACM1"))
    assert w.lister() == ["/dev/ttyACM1"]
    link = tmp_path / "usb-Arduino_Uno-if00"
    w = app.board_watch(SimpleNamespace(port=str(link)))
    assert w.lister() == []
    link.write_text("", encoding="utf-8")
    assert w.lister() == [str(link)]
    assert app.board_watch(SimpleNamespace(port=None)).lister is detect.likely_ports
