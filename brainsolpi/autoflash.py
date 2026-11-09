from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from . import paths, tools
from .drivers.detect import UsbInfo
from .state import StateStore

log = logging.getLogger(__name__)

# avrdude needs a few seconds per try, a hung one must not keep the service busy forever
AVRDUDE_TIMEOUT_S = 120.0
# the last lines of a failed avrdude run go to the journal, they say why
TAIL = 12


def board_key(port: str, info: UsbInfo | None) -> str:
    # the usb serial number of the atmega16u2 tells one board from another, without one the
    # port and the ids have to do
    if info is not None and info.serial:
        return f"{info.ids} {info.serial}"
    return f"{info.ids if info is not None else 'no usb'} {port}"


def run_logged(cmd: list[str], cwd: str) -> int:
    # runs avrdude without a terminal and puts its last lines into the journal
    try:
        p = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=AVRDUDE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        log.warning("avrdude took longer than %.0f s and was stopped", AVRDUDE_TIMEOUT_S)
        return 1
    except OSError as e:
        log.warning("avrdude did not start: %s", e)
        return 1
    lines = [line.strip() for line in (p.stdout + "\n" + p.stderr).splitlines() if line.strip()]
    for line in lines[-TAIL:] if p.returncode != 0 else lines[-2:]:
        log.info("avrdude: %s", line)
    return p.returncode


class AutoFlash:
    # writes the bridge firmware to an uno that still runs other code, the kit board comes with
    # code of its own and would never answer the brainsol hello. it uses the same avrdude step
    # as brainsolpi flash, and a board it flashed once is never flashed by it again

    def __init__(
        self,
        state: StateStore,
        avrdude: str | None = None,
        hexfile: Path | None = None,
        runner: Callable[..., int] = run_logged,
    ):
        self.state = state
        self.avrdude = avrdude if avrdude is not None else shutil.which("avrdude")
        self.hexfile = hexfile if hexfile is not None else paths.default_hex()
        self.runner = runner

    def refuse(self, port: str, info: UsbInfo | None) -> str | None:
        # why this board does not get the firmware by itself, None when it may
        if self.avrdude is None:
            return "avrdude is not installed, install it with: sudo apt install avrdude"
        if self.hexfile is None or not self.hexfile.is_file():
            return f"there is no firmware file at {self.hexfile or 'firmware/brainsol_bridge.hex'}"
        if board_key(port, info) in self.state.flashed:
            return "the service wrote the bridge firmware to this board once already and does not do it again"
        return None

    def flash(self, port: str, info: UsbInfo | None) -> bool:
        # true when avrdude wrote the hex, the board is then marked so it never gets a second go,
        # the caller saves the state file from the event loop
        log.info("writing %s to the board on %s", self.hexfile, port)
        rc = tools._avrdude(self.avrdude, port, self.hexfile, self.runner, out=log.info)
        if rc != 0:
            return False
        key = board_key(port, info)
        if key not in self.state.flashed:
            self.state.flashed.append(key)
        return True
