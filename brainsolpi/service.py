from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

# the systemd unit deploy/install.sh sets up
UNIT = "brainsolpi"
UNIT_FILE = Path("/etc/systemd/system/brainsolpi.service")
STOP_HINT = "sudo systemctl stop brainsolpi"
START_HINT = "sudo systemctl start brainsolpi"


class ServiceBusy(Exception):
    pass


def inside() -> bool:
    # true when this process runs as part of the service, stopping it would end us too
    try:
        return "brainsolpi.service" in Path("/proc/self/cgroup").read_text(encoding="utf-8")
    except OSError:
        return False


def installed() -> bool:
    return sys.platform.startswith("linux") and UNIT_FILE.is_file()


def active(run: Callable = subprocess.run) -> bool:
    if not sys.platform.startswith("linux") or shutil.which("systemctl") is None or inside():
        return False
    try:
        return run(["systemctl", "is-active", "--quiet", UNIT], timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class Paused:
    # the board answers only one program at a time, so a helper that needs it stops the tracker
    # service first and starts it again at the end, the same as firmware/flash.sh

    def __init__(self, why: str, out: Callable[..., None] = print, run: Callable = subprocess.run):
        self.why = why
        self.out = out
        self.run = run
        self.stopped = False

    def __enter__(self) -> Paused:
        if not active(self.run):
            return self
        self.out(f"stopping the brainsolpi service while {self.why}, sudo may ask for your password")
        try:
            rc = self.run(["sudo", "systemctl", "stop", UNIT]).returncode
        except (OSError, subprocess.SubprocessError):
            rc = 1
        if rc != 0:
            raise ServiceBusy(f"the brainsolpi service still runs and holds the board, stop it with: {STOP_HINT}")
        self.stopped = True
        return self

    def __exit__(self, *exc) -> None:
        if not self.stopped:
            return
        self.out("starting the brainsolpi service again")
        try:
            rc = self.run(["sudo", "systemctl", "start", UNIT]).returncode
        except (OSError, subprocess.SubprocessError):
            rc = 1
        if rc != 0:
            self.out(f"could not start the service, start it with: {START_HINT}")
