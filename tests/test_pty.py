import os
import select
import sys
import threading
import time

import pytest

from brainsolpi.drivers.bridge import BridgeDriver, open_serial
from brainsolpi.drivers.detect import probe
from brainsolpi.drivers.fakeboard import FakeBoard

from .test_autoflash import KitBoard

# the serial code on a real tty device, the way the pi opens the usb port of the uno
pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs a pseudo terminal")


class PtyBoard:
    # a fake board behind a pseudo terminal, pyserial opens its path like /dev/ttyACM0. a pty has
    # no dtr line, so opening it does not reset the board, the driver has to ask with ?

    def __init__(self, board):
        import tty

        self.board = board
        self.master, self.slave = os.openpty()
        tty.setraw(self.slave)
        self.path = os.ttyname(self.slave)
        self.end = board.opener(self.path)
        self.halt = threading.Event()
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()

    def _pump(self):
        while not self.halt.is_set():
            ready, _, _ = select.select([self.master], [], [], 0.005)
            try:
                if ready:
                    self.end.write(os.read(self.master, 4096))
                n = self.end.in_waiting
                if n:
                    os.write(self.master, self.end.read(n))
            except OSError:
                return

    def close(self):
        self.halt.set()
        self.thread.join(1.0)
        self.board.close()
        os.close(self.master)
        os.close(self.slave)


def test_the_probe_finds_a_board_on_a_tty_that_did_not_reset():
    pty = PtyBoard(FakeBoard(boot_s=0.1))
    try:
        got = probe(pty.path, open_serial, timeout=5.0)
        assert got is not None and got[2].fw == "1.0.0"
        # the port is locked, a second program cannot open it while the tracker holds it
        with pytest.raises(Exception):
            open_serial(pty.path)
        got[1].close()
    finally:
        pty.close()


def test_a_kit_board_on_a_tty_counts_as_silent():
    pty = PtyBoard(KitBoard())
    try:
        silent = set()
        assert probe(pty.path, open_serial, timeout=4.5, silent=silent) is None
        assert silent == {pty.path}
    finally:
        pty.close()


def test_the_bridge_streams_fifty_frames_a_second_through_a_tty():
    pty = PtyBoard(FakeBoard(boot_s=0.1))
    d = BridgeDriver(pty.path)
    d.start_sync()
    try:
        end = time.monotonic() + 8.0
        while not d.link_ok and time.monotonic() < end:
            time.sleep(0.05)
        assert d.link_ok
        n0, t0 = d.frames, time.monotonic()
        time.sleep(2.0)
        rate = (d.frames - n0) / (time.monotonic() - t0)
        assert 45 <= rate <= 55 and d.dropped == 0
    finally:
        d.stop_sync()
        pty.close()
