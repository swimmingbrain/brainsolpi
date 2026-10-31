from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import paths, service
from .auth import hash_pin, pin_problem
from .config import Settings
from .kinematics import ServoMap
from .state import StateStore

BUSY_HINT = "if the tracker service is running it holds the port, stop it first with: sudo systemctl stop brainsolpi"


def _cfg_dir(args) -> Path:
    return Path(args.config_dir) if getattr(args, "config_dir", None) else paths.config_dir()


# setpin


def setpin(args, ask=getpass.getpass) -> int:
    path = _cfg_dir(args) / "settings.json"
    try:
        pin = ask("new admin pin: ")
        again = ask("the same pin again: ")
    except (EOFError, KeyboardInterrupt):
        print("\nnothing changed")
        return 1
    problem = pin_problem(pin)
    if problem:
        print(f"{problem}, nothing changed")
        return 1
    if pin != again:
        print("the two pins differ, nothing changed")
        return 1
    settings = Settings.load(path)
    settings.pin_hash = hash_pin(pin)
    settings.save()
    # old admin sessions end with the old pin
    state = StateStore.load(_cfg_dir(args) / "state.json")
    state.tokens = []
    state.save(force=True)
    print(f"pin saved in {path}")
    print("a running tracker picks it up within a few seconds, open admin sessions are logged out")
    return 0


# centre


def _connect(port: str | None):
    from .drivers.bridge import BridgeDriver, open_serial, wait_ident
    from .drivers.detect import find_board

    if port:
        try:
            ser = open_serial(port)
        except Exception as e:
            print(f"cannot open {port}: {e}")
            print(BUSY_HINT)
            return None
        ident = wait_ident(ser)
        if ident is None:
            ser.close()
            print(f"{port} opened, but no brainsol board answered, flash it with: brainsolpi flash")
            return None
        found = (port, ser, ident)
    else:
        print("looking for the board ...")
        found = find_board(6.0)
        if found is None:
            print("no board answered on any serial port")
            print("check the usb cable, then flash the firmware with: brainsolpi flash")
            print(BUSY_HINT)
            return None
    d = BridgeDriver(found[0], initial=found)
    d.start_sync()
    end = time.monotonic() + 3.0
    while not d.link_ok and time.monotonic() < end:
        time.sleep(0.02)
    if not d.link_ok or d.ident is None:
        d.stop_sync()
        print("the board stopped answering, check the usb cable")
        return None
    return d


def centre(args) -> int:
    try:
        # the state file is written before the service starts again, so it starts at this pose
        with service.Paused("the servos are centred"):
            return _centre(args)
    except service.ServiceBusy as e:
        print(e)
        return 1


def _centre(args) -> int:
    d = _connect(args.port)
    if d is None:
        return 1
    print(f"board on {d.port}, firmware {d.ident.fw}")
    print("both servos now hold 1500 us, the middle of their range")
    print("mount the horns so the head faces forward and the panel lies flat, then press ctrl c")
    try:
        while True:
            d.move(1500, 1500)
            time.sleep(0.2)
            f = d.latest()
            state = "holding" if f is not None and f.flags & 1 else "waiting for the board"
            print(f"\r{state}, pan {f.pan_us if f else 0} us, tilt {f.tilt_us if f else 0} us   ", end="", flush=True)
    except KeyboardInterrupt:
        print()
    finally:
        d.stop_sync()
    # the next run starts right at this pose so the head does not jump
    cfg = _cfg_dir(args)
    settings = Settings.load(cfg / "settings.json")
    cal = settings.calib("bridge")
    st = StateStore.load(cfg / "state.json")
    st.pan = ServoMap.from_dict(cal["pan"]).to_angle(1500)
    st.tilt = ServoMap.from_dict(cal["tilt"]).to_angle(1500)
    st.known = True
    st.save(force=True)
    print(f"done, the tracker will start at pan {st.pan:.0f} tilt {st.tilt:.0f}")
    return 0


# flash


INSTALL_HINT = """avrdude is not installed.
  raspberry pi or debian: sudo apt install avrdude
  windows: get avrdude from https://github.com/avrdudes/avrdude/releases and put it on the PATH
  mac: brew install avrdude"""


def _flash_port(args) -> str | None:
    if args.port:
        return args.port
    from .drivers.detect import candidates

    ports = candidates()
    if not ports:
        return None
    dev, desc = ports[0]
    print(f"using {dev} ({desc}), pass --port to pick another one")
    return dev


HELLO_S = 6.0


def _hello(port: str) -> str | None:
    # opening the port resets the uno, after the bootloader the sketch says who it is
    from .drivers.bridge import open_serial, wait_ident

    try:
        ser = open_serial(port)
    except Exception:
        return None
    try:
        ident = wait_ident(ser, HELLO_S)
    except Exception:
        ident = None
    finally:
        ser.close()
    return None if ident is None else f"I,brainsol,{ident.fw},{ident.caps}"


def _no_access(port: str) -> bool:
    return os.name == "posix" and os.path.exists(port) and not os.access(port, os.R_OK | os.W_OK)


def flash(args, runner=subprocess.call, hello=_hello, pause=None) -> int:
    avrdude = shutil.which("avrdude")
    if avrdude is None:
        print(INSTALL_HINT)
        return 1
    hexfile = Path(args.hex) if args.hex else paths.default_hex()
    if hexfile is None or not hexfile.is_file():
        where = hexfile if hexfile is not None else "firmware/brainsol_bridge.hex"
        print(f"no firmware file at {where}")
        print("build it from firmware/brainsol_bridge or pass --hex with the path to a .hex file")
        return 1
    port = _flash_port(args)
    if port is None:
        print("no serial port found, plug the board in with the usb cable")
        return 1
    if _no_access(port):
        print(f"no access to {port}. add your user to the dialout group with: sudo usermod -aG dialout $USER")
        print("then log out and in again")
        return 1
    try:
        # the service keeps the port open and its commands would land in the bootloader
        with pause or service.Paused("flashing"):
            rc = _avrdude(avrdude, port, hexfile, runner)
            if rc != 0:
                return rc
            print("flash done, waiting for the board to say hello")
            line = hello(port)
    except service.ServiceBusy as e:
        print(e)
        return 1
    if line:
        print(f"the board answers: {line}")
    else:
        print(f"the board did not answer within {HELLO_S:.0f} s. that can be fine, check it with: brainsolpi doctor")
    return 0


def _avrdude(avrdude: str, port: str, hexfile: Path, runner) -> int:
    rc = 1
    for baud in (115200, 57600):
        # avrdude reads a drive letter as a field separator, so it gets the bare file name
        cmd = [avrdude, "-p", "atmega328p", "-c", "arduino", "-P", port, "-b", str(baud),
               "-D", "-U", f"flash:w:{hexfile.name}:i"]
        print(" ".join(cmd))
        rc = runner(cmd, cwd=str(hexfile.parent))
        if rc == 0:
            return 0
        if baud == 115200:
            print("avrdude could not sync at 115200 baud, trying once more at 57600 for an older bootloader")
    print("flashing failed")
    print("check the usb cable and close every other program that uses the port, a serial monitor perhaps")
    print("if it still fails, press the reset button on the board right when avrdude starts")
    return rc


def interactive() -> bool:
    return sys.stdin is not None and sys.stdin.isatty() and os.environ.get("TERM") != "dumb"
