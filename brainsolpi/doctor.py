from __future__ import annotations

import contextlib
import socket
import sys
import time
from pathlib import Path
from typing import Callable

from . import paths, service
from .config import Settings
from .drivers.bridge import BridgeDriver, open_serial, wait_ident
from .drivers.detect import candidates, find_board
from .drivers.fakeboard import FakeBoard
from .drivers.protocol import FLAG_ATTACHED, RAW_MAX
from .jsonio import read_json
from .kinematics import ServoMap
from .state import StateStore
from .sysinfo import low_voltage, supply
from .tools import BUSY_HINT

POWER_NOTE = ("the pi reports low voltage since it started. it powers the uno and both servos "
              "through usb, so it needs {supply} or a better one")
POWER_STEP = ("use {supply} or a better one with a short cable, "
              "a phone charger or a pc port sags when the servos move, then reboot the pi")

NAMES = ("L", "R", "U", "D")
WHERE = {"L": "left", "R": "right", "U": "top", "D": "bottom"}
PINS = {"L": "A0", "R": "A1", "U": "A2", "D": "A3"}
# a covered sensor has to move at least this share of its open reading
MIN_CHANGE = 0.08
WIGGLE = 5


def bar(value: float, width: int = 12) -> str:
    n = int(round(max(0.0, min(1.0, value / RAW_MAX)) * width))
    return "#" * n + "." * (width - n)


class Doctor:
    # a friendly check for the day the hardware arrives, plain text and one step at a time

    def __init__(
        self,
        port: str | None = None,
        fake: bool = False,
        yes: bool = False,
        out: Callable[..., None] = print,
        ask: Callable[[str], str] = input,
        config_dir: Path | None = None,
        live: bool = True,
        quick: bool = False,
        power: Callable[[], bool | None] = low_voltage,
        supply: Callable[[], str] = supply,
    ):
        self.port = port
        self.fake = fake
        self.yes = yes or fake
        self.out = out
        self.ask = ask
        self.live = live
        # shorter waits for the tests, people get the full time to react
        self.pace = 0.3 if quick else 1.0
        self.cfg_dir = config_dir or paths.config_dir()
        self.board: FakeBoard | None = FakeBoard(boot_s=0.5, seed=4) if fake else None
        # the service would answer in between, so it rests while the doctor talks to the board
        self.paused = None if fake else service.Paused("the doctor checks the board", out=self.out)
        self.drv: BridgeDriver | None = None
        self.results: list[tuple[str, bool | None, str]] = []
        self.power = power
        self.supply = supply
        # true when the pi saw its supply sag, None when nobody asked or it cannot tell
        self.low_voltage: bool | None = None

    # helpers

    def confirm(self, question: str, default: bool = False) -> bool:
        if self.yes:
            self.out(f"{question} yes")
            return True
        try:
            answer = self.ask(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
        except EOFError:
            return default
        if not answer:
            return default
        return answer.startswith("y")

    def pause(self, text: str) -> None:
        if self.yes:
            self.out(text)
            return
        try:
            self.ask(f"{text}, then press enter ")
        except EOFError:
            pass

    def watch(self, seconds: float) -> list[float]:
        # live bars while it measures, the mean of the second half is the answer
        seconds *= self.pace
        sums = [0.0] * 4
        n = 0
        start = time.monotonic()
        last_draw = 0.0
        while time.monotonic() - start < seconds:
            f = self.drv.latest()
            now = time.monotonic()
            if f is not None and now - start > seconds / 2:
                for k in range(4):
                    sums[k] += f.raw[k]
                n += 1
            if f is not None and self.live and now - last_draw > 0.1:
                last_draw = now
                line = "  ".join(f"{name} {bar(f.raw[k])} {f.raw[k]:4d}" for k, name in enumerate(NAMES))
                self.out(f"\r  {line}", end="", flush=True)
            time.sleep(0.02)
        if self.live:
            self.out("")
        return [s / max(n, 1) for s in sums]

    def record(self, title: str, ok: bool | None, note: str) -> bool | None:
        self.results.append((title, ok, note))
        return ok

    # steps

    def step_port(self) -> bool:
        title = "serial port"
        if self.fake:
            self.out("  using a simulated board, nothing is sent to real hardware")
            d = BridgeDriver("fake", opener=self.board.opener)
        else:
            ports = candidates()
            for dev, desc in ports:
                self.out(f"  seen {dev} {desc}")
            if self.port:
                try:
                    ser = open_serial(self.port)
                except Exception as e:
                    self.out(f"  cannot open {self.port}: {e}")
                    self.out(f"  {BUSY_HINT}")
                    return self.record(title, False, f"cannot open {self.port}")
                ident = wait_ident(ser)
                if ident is None:
                    ser.close()
                    self.out("  the port opened but no brainsol board answered within 5 s")
                    self.out("  flash the bridge firmware with: brainsolpi flash")
                    return self.record(title, False, "no answer")
                found = (self.port, ser, ident)
            else:
                if not ports:
                    self.out("  no serial port at all, plug the usb cable into the pi and the board")
                    return self.record(title, False, "no port")
                self.out("  waiting for the board to say hello, opening the port restarts it ...")
                found = find_board(6.0)
                if found is None:
                    self.out("  no port answered with the brainsol identity line")
                    self.out("  flash the bridge firmware with: brainsolpi flash")
                    self.out(f"  {BUSY_HINT}")
                    return self.record(title, False, "no board answered")
            d = BridgeDriver(found[0], initial=found)
        self.drv = d
        d.start_sync()
        end = time.monotonic() + 8.0
        while not (d.link_ok and d.latest() is not None) and time.monotonic() < end:
            time.sleep(0.02)
        if not d.link_ok:
            self.out("  the board did not answer")
            return self.record(title, False, "no answer")
        self.out(f"  ok, board on {d.port}")
        return self.record(title, True, d.port or "")

    def step_firmware(self) -> bool:
        ident = self.drv.ident
        self.out(f"  bridge firmware {ident.fw}")
        self.out(f"  BH1750 light sensor {'found' if ident.lux else 'not found'}")
        self.out(f"  INA219 current sensor {'found' if ident.pv else 'not found, that is fine, it is an optional extra'}")
        return self.record("firmware", True, ident.fw)

    def step_frames(self) -> bool:
        n0 = self.drv.frames
        d0 = self.drv.dropped
        span = 2.0 * max(self.pace, 0.5)
        time.sleep(span)
        rate = (self.drv.frames - n0) / span
        lost = self.drv.dropped - d0
        self.out(f"  {rate:.1f} frames per second, {lost} lost")
        ok = 45.0 <= rate <= 55.0
        if not ok:
            self.out("  the board should send 50 frames per second, check the usb cable and the firmware")
        return self.record("sample frames", ok, f"{rate:.0f} per second")

    def step_sensors(self) -> bool | None:
        if not self.yes and not self.confirm("  check the four light sensors now, you need a free hand?", True):
            return self.record("light sensors", None, "skipped")
        self.out("  open readings, keep the sensors uncovered:")
        base = self.watch(2.0)
        all_ok = True
        for k, name in enumerate(NAMES):
            if self.board is not None:
                self.board.covered = {k}
            self.pause(f"  cover the {name} sensor on the {WHERE[name]} with a finger and keep it there")
            vals = self.watch(3.0)
            if self.board is not None:
                self.board.covered = set()
            change = [(vals[i] - base[i]) / max(base[i], 1.0) for i in range(4)]
            top = max(range(4), key=lambda i: abs(change[i]))
            if top != k and abs(change[top]) >= MIN_CHANGE:
                other = NAMES[top]
                self.out(f"  {other} reacted instead of {name}, the cables on {PINS[name]} and {PINS[other]} look swapped")
                all_ok = False
            elif abs(change[k]) < MIN_CHANGE:
                self.out(f"  {name} did not react, check its cable on {PINS[name]} and the 5 V switch on the board")
                all_ok = False
            else:
                way = "higher" if change[k] > 0 else "lower"
                self.out(f"  {name} ok, it reads {abs(change[k]) * 100:.0f} percent {way} when covered")
                if change[k] > 0:
                    self.out("  this module reads higher in the dark, the dark and bright calibration takes care of it")
            self.pause("  take the finger away")
            time.sleep(0.3)
        return self.record("light sensors", all_ok, "")

    def step_lux(self) -> bool:
        ident = self.drv.ident
        if not ident.lux:
            self.out("  no BH1750 found, check the 4 pin cable: VCC to 5 V, GND, SDA to A4, SCL to A5")
            return self.record("BH1750", False, "not found")
        time.sleep(0.3)
        f = self.drv.latest()
        lux = f.lux10 / 10.0 if f is not None else 0.0
        self.out(f"  {lux:.1f} lux on the panel plane")
        if lux <= 0:
            self.out("  it reads zero, that only happens in a dark room, otherwise check the cable")
        return self.record("BH1750", lux > 0, f"{lux:.0f} lux")

    def step_servos(self) -> bool | None:
        if not self.confirm("  wiggle both servos by a few degrees? the head must be free to move"):
            return self.record("servos", None, "skipped")
        settings = Settings.load(self.cfg_dir / "settings.json") if not self.fake else Settings()
        cal = settings.calib("bridge")
        pm, tm = ServoMap.from_dict(cal["pan"]), ServoMap.from_dict(cal["tilt"])
        st = StateStore.load(self.cfg_dir / "state.json") if not self.fake else StateStore(None)
        pan, tilt = st.pan, st.tilt
        lp, lt = settings.pan_limits, settings.tilt_limits
        pan = min(max(pan, lp[0] + WIGGLE), lp[1] - WIGGLE)
        tilt = min(max(tilt, lt[0] + WIGGLE), lt[1] - WIGGLE)

        def go(p, t, steps=1):
            for _ in range(steps):
                self.drv.move(pm.to_us(p), tm.to_us(t))
                time.sleep(0.05)

        if st.known:
            self.out(f"  starting at the saved pose, pan {pan:.0f} tilt {tilt:.0f}")
        else:
            # the first pulse is a jump at full servo speed from wherever the head sits now
            self.out(f"  no pose is saved yet, the servos start at pan {pan:.0f} tilt {tilt:.0f}, the head may turn there quickly")
        go(pan, tilt, 10)
        f = self.drv.latest()
        if f is None or not f.flags & FLAG_ATTACHED:
            self.out("  the board does not report attached servos")
            return self.record("servos", False, "not attached")
        for axis in ("pan", "tilt"):
            self.out(f"  moving {axis}")
            for d in list(range(1, WIGGLE + 1)) + list(range(WIGGLE, -WIGGLE - 1, -1)) + list(range(-WIGGLE, 1)):
                go(pan + d, tilt) if axis == "pan" else go(pan, tilt + d)
        go(pan, tilt, 5)
        moved = self.confirm("  did both servos move a little and come back?", True)
        if not moved:
            self.out("  check the servo cables on D9 and D10, brown on G, and that the slide switch of the board stands on 5 V")
        elif not self.fake:
            # the head now really sits here, the tracker starts from this pose without a jump
            st.pan, st.tilt, st.known = pan, tilt, True
            st.save(force=True)
        return self.record("servos", moved, "")

    def run(self) -> int:
        steps = [
            ("serial port", self.step_port),
            ("firmware", self.step_firmware),
            ("sample frames", self.step_frames),
            ("light sensors", self.step_sensors),
            ("BH1750 light sensor", self.step_lux),
            ("servos", self.step_servos),
        ]
        self.out("brainSOL doctor, a step by step check of the board, the sensors and the servos")
        if not self.fake:
            self.check_power()
        try:
            with self.paused or contextlib.nullcontext():
                try:
                    for i, (title, fn) in enumerate(steps, 1):
                        self.out(f"\nstep {i} of {len(steps)}, {title}")
                        ok = fn()
                        if ok is False and i <= 1:
                            break
                finally:
                    # the port has to be free before the service starts again
                    if self.drv is not None:
                        self.drv.stop_sync()
                    if self.board is not None:
                        self.board.close()
        except KeyboardInterrupt:
            self.out("\nstopped")
        except service.ServiceBusy as e:
            self.out(f"  {e}")
            self.record("serial port", False, "the service holds the board")
        self.out("\nsummary")
        for title, ok, note in self.results:
            mark = "ok  " if ok else "skip" if ok is None else "FAIL"
            self.out(f"  {mark} {title}{', ' + note if note else ''}")
        self.out("\nnext steps")
        for i, step in enumerate(self.next_steps(), 1):
            self.out(f"  {i}. {step}")
        return 0 if all(ok is not False for _, ok, _ in self.results) else 1

    def check_power(self) -> None:
        # the pi feeds the uno and both servos through usb, a weak supply shows here first
        self.low_voltage = self.power()
        if self.low_voltage:
            self.out(f"  warning: {POWER_NOTE.format(supply=self.supply())}")

    def next_steps(self) -> list[str]:
        # what to do now, as exact as the results allow, the first failure comes first
        steps = self._next_steps()
        if self.low_voltage and not self.fake:
            # a sagging supply explains resets and jitter, so it goes before everything else
            steps.insert(0, POWER_STEP.format(supply=self.supply()))
        return steps

    def _next_steps(self) -> list[str]:
        ok = {title: (good, note) for title, good, note in self.results}
        again = "then run brainsolpi doctor again"
        if self.fake:
            return [
                "this was a simulated board. on the pi, plug the board in and run: brainsolpi doctor",
                "to try the whole tracker on this computer run: brainsolpi demo",
            ]
        port, note = ok.get("serial port", (False, ""))
        if not port:
            if "service" in note:
                return [f"stop the tracker service with: {service.STOP_HINT}", again,
                        f"start it afterwards with: {service.START_HINT}"]
            if note == "no port":
                return ["plug the usb cable into the pi and into the board", again]
            return ["flash the bridge firmware with: brainsolpi flash", again]
        steps = []
        if ok.get("sample frames", (True, ""))[0] is False:
            steps.append("use a short usb cable straight into the pi, not through a hub")
        if ok.get("light sensors", (True, ""))[0] is False:
            steps.append("fix the sensor cables as step 4 says")
        if ok.get("servos", (True, ""))[0] is False:
            steps.append("check the servo cables on D9 and D10, brown on G, and that the slide switch stands on 5 V")
        if steps:
            return steps + [again]
        skipped = [t for t, (good, _) in ok.items() if good is None]
        if skipped:
            steps.append(f"the {' and the '.join(skipped)} were skipped, run brainsolpi doctor again to check them")
        if ok.get("BH1750", (True, ""))[0] is False:
            steps.append("plug in the BH1750 as step 5 says. the tracker works without it, "
                         "but lux, the power figure and the cosine and compare experiments need it")
        # read only, the doctor does not write the settings of the service
        settings = Settings(None, read_json(self.cfg_dir / "settings.json"))
        if not settings.pin_hash:
            steps.append("set the admin pin with: brainsolpi setpin")
        if not StateStore.load(self.cfg_dir / "state.json").known:
            steps.append("if the servo horns are not on yet, mount them with the head facing forward and "
                         "the panel flat while this holds the servos in the middle: brainsolpi centre")
        # a service the doctor paused runs again by now
        if not (self.paused is not None and self.paused.stopped):
            if service.installed():
                steps.append(f"start the tracker with: {service.START_HINT}")
            else:
                steps.append("start the tracker with: brainsolpi run")
        steps.append(f"open {address()} in a browser and unlock the admin tools with the pin")
        if settings.calib("bridge")["saved"]:
            steps.append("the calibration is saved, pick a mode in the control tab")
        else:
            steps.append(
                "in the calibrate tab: capture dark with all four sensors covered, capture bright with the "
                "lamp close in front, nudge the head until it faces forward with the panel flat and store "
                "it as centre, tilt it up, keep the lamp still and find the directions, then save the calibration"
            )
            steps.append("the tracker holds until the calibration is saved, then it tracks the light in auto")
        return steps


def address() -> str:
    # the name the install script gives the pi, it answers as name.local
    if sys.platform.startswith("linux"):
        return f"http://{socket.gethostname()}.local:8080"
    return "http://localhost:8080"


def doctor(args) -> int:
    cfg = Path(args.config_dir) if getattr(args, "config_dir", None) else None
    return Doctor(port=args.port, fake=args.fake, yes=args.yes, config_dir=cfg).run()
