from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

from aiohttp import web

from . import paths
from .auth import Auth, hash_pin
from .autoflash import AutoFlash
from .commands import Commands
from .config import Settings
from .drivers.base import Driver
from .drivers.bridge import BridgeDriver
from .drivers.detect import BoardWatch, candidates, find_board, likely_ports, probe
from .drivers.fakeboard import FakeBoard
from .drivers.sim import SimDriver
from .engine import Engine
from .hub import Hub
from .jsonio import BackgroundWriter, read_json
from .server import make_app
from .state import StateStore
from .store import ExperimentStore
from .sysinfo import SysInfo

log = logging.getLogger("brainsolpi")

# exit code that tells a service manager to start us again
RESTART_CODE = 75


AUTO_WAIT_S = 6.0
# after a flash the board resets and boots, then it says hello like after any open
HELLO_S = 6.0


async def open_driver(args, settings: Settings, looked: dict | None = None) -> Driver:
    # looked gets the ports auto probed and the ones that stayed silent, the board watch goes on from there
    looked = looked if looked is not None else {}
    looked.setdefault("ports", [])
    looked.setdefault("silent", set())
    kind = args.driver
    serial_cfg = settings.data["serial"]
    rate, slew = serial_cfg["rate"], serial_cfg["slew"]
    if kind == "sim":
        return SimDriver(rate=rate)
    if kind == "fake":
        # the bridge code path end to end, against a board that lives in memory
        board = FakeBoard(boot_s=1.0)
        log.info("fake board on an in memory serial link")
        return BridgeDriver("fake", opener=board.opener, rate=rate, slew=slew, profile="sim")
    if kind == "bridge":
        finder = None if args.port else (lambda: find_board(AUTO_WAIT_S))
        return BridgeDriver(args.port, finder=finder, rate=rate, slew=slew)
    # auto: a board that answers wins, otherwise the sim keeps the demo going
    ports = [args.port] if args.port else [dev for dev, _ in candidates()]
    if not ports:
        log.warning("no serial port found, falling back to the sim driver")
        return SimDriver(rate=rate)
    log.info("looking for a board on %s for up to %.0f s", ", ".join(ports), AUTO_WAIT_S)
    looked["ports"] = list(ports)
    silent = looked["silent"]
    found = await asyncio.get_running_loop().run_in_executor(
        None, lambda: find_board(AUTO_WAIT_S, ports=ports, silent=silent))
    if found is not None:
        port, _, ident = found
        log.info("found the board on %s, firmware %s", port, ident.fw)
        return BridgeDriver(port, initial=found, rate=rate, slew=slew)
    log.warning("no board answered within %.0f s, falling back to the sim driver", AUTO_WAIT_S)
    return SimDriver(rate=rate)


BOARD_WATCH_S = 3.0


def board_watch(args, looked: dict | None = None) -> BoardWatch:
    # the watch goes on from the ports auto already probed at the start
    start = looked.get("ports") if looked else None
    silent = looked.get("silent", ()) if looked else ()
    if not args.port:
        return BoardWatch(start=start, silent=silent)
    # with a port given only that one counts, a /dev/serial/by-id link is not in the list
    port = args.port
    return BoardWatch(lister=lambda: [port] if port in likely_ports() or os.path.exists(port) else [],
                      start=start, silent=silent)


def autoflash(args, settings: Settings, state: StateStore) -> AutoFlash | None:
    # only the service asks for it with the autoflash flag, a run by hand on a computer with an arduino
    # for something else never writes to it. serial.autoflash false in the settings turns it off
    if args.driver != "auto" or not getattr(args, "autoflash", False) or not settings.data["serial"]["autoflash"]:
        return None
    return AutoFlash(state)


async def _silent_board(item, watch: BoardWatch, engine: Engine, flasher: AutoFlash | None) -> tuple | None:
    # a port that opened fine and never said hello, perhaps an uno that still runs other code.
    # returns the board when it answers after the firmware went on
    port, info = item
    what = f"{port} (usb {info.ids})" if info is not None else port
    if info is None or not info.uno:
        # a ch340 or ftdi adapter can sit in front of anything, that is no job for avrdude
        log.info("%s does not answer the brainsol hello and is no uno r3, it is left alone", what)
        return None
    hello = f"the uno on {what} does not answer the brainsol hello, it still runs other code"
    if flasher is None:
        engine.note("info", f"{hello}. flash the bridge firmware with: brainsolpi flash")
        return None
    why = flasher.refuse(port, info)
    if why is not None:
        engine.note("warn", f"{hello}. {why}, flash it by hand with: brainsolpi flash")
        return None
    engine.note("info", f"{hello}. writing the bridge firmware to it now, that takes about half a minute, "
                        "serial.autoflash false in the settings turns this off")
    loop = asyncio.get_running_loop()
    if not await loop.run_in_executor(None, flasher.flash, port, info):
        engine.note("warn", f"writing the bridge firmware to the uno on {port} failed, the sim goes on. "
                            "the journal has the output of avrdude, try again by hand with: brainsolpi flash")
        return None
    # the board is marked as flashed right away, a restart must not start it again
    flasher.state.save()
    found = await loop.run_in_executor(None, lambda: probe(port, watch.opener, HELLO_S, watch.halt))
    if found is None:
        engine.note("warn", f"the bridge firmware is on the uno on {port}, but it does not say hello, the sim "
                            "goes on. check it with: brainsolpi doctor")
        return None
    return found


async def _watch_board(watch: BoardWatch, engine: Engine, stop: asyncio.Event, after: dict,
                       can_restart: bool, every: float = BOARD_WATCH_S, flasher: AutoFlash | None = None) -> None:
    # auto started the sim because no board answered, a board plugged in later takes over
    loop = asyncio.get_running_loop()
    try:
        while not stop.is_set():
            await asyncio.sleep(every)
            found = await loop.run_in_executor(None, watch.check)
            if found is None:
                item = watch.next_silent()
                if item is None or stop.is_set():
                    continue
                found = await _silent_board(item, watch, engine, flasher)
                if found is None:
                    continue
            port, ser, ident = found
            # the new process opens it again, nothing may hold it meanwhile
            try:
                ser.close()
            except Exception:
                pass
            if can_restart:
                engine.event("info", f"a board answered on {port}, firmware {ident.fw}, restarting with the bridge driver")
                after["action"] = "restart"
                stop.set()
            else:
                engine.event(
                    "info",
                    f"a board answered on {port}, firmware {ident.fw}. stop this run with ctrl c and start "
                    "it again to use the board, the sim goes on until then",
                )
            return
    finally:
        # a probe still running in its thread gives up at once
        watch.halt.set()


PIN_WATCH_S = 3.0


async def _watch_pin(settings: Settings, auth: Auth, hub: Hub, engine: Engine) -> None:
    # brainsolpi setpin writes the settings file while the service runs, the new hash is
    # taken over here so a later save of the settings cannot bring the old pin back
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(PIN_WATCH_S)
        if settings.path is None:
            return
        try:
            raw = await loop.run_in_executor(None, read_json, settings.path)
        except Exception:
            continue
        pin = ((raw or {}).get("auth") or {}).get("pin")
        if not isinstance(pin, str) or not pin or pin == settings.pin_hash:
            continue
        settings.data["auth"]["pin"] = pin
        auth.pin_hash = pin
        auth.forget_all()
        for c in hub.clients:
            if c.admin:
                c.admin = False
                hub.send(c, {"t": "auth", "ok": False, "err": "token", "msg": "the pin changed, log in again", "wait": 0}, "auth")
        engine.event("info", "the admin pin changed, admins have to log in again")


def _install_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    sigs = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        # ctrl break on windows, the only signal another process can send a console app there
        sigs.append(signal.SIGBREAK)
    for sig in sigs:
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError, ValueError):
            # windows has no loop signal handlers, a plain handler hands over to the loop
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))


async def serve(args) -> int:
    cfg_dir = Path(args.config_dir) if args.config_dir else paths.config_dir()
    data_dir = Path(args.data_dir) if args.data_dir else paths.data_dir()
    writer = BackgroundWriter()
    settings = Settings.load(cfg_dir / "settings.json")
    settings.writer = writer
    state = StateStore.load(cfg_dir / "state.json")
    state.writer = writer

    pin_hash = settings.pin_hash
    if args.pin:
        if not getattr(args, "demo", False):
            log.warning("using the pin from the command line, that is meant for development only")
        pin_hash = await asyncio.get_running_loop().run_in_executor(None, hash_pin, args.pin)
    elif not pin_hash:
        log.warning("no admin pin is set, admin login is refused until you run brainsolpi setpin")

    looked: dict = {}
    driver = await open_driver(args, settings, looked)
    hub = Hub()
    store = ExperimentStore(data_dir / "experiments", writer)
    engine = Engine(settings, state, driver, store=store, data_dir=data_dir, sink=hub, sysinfo=SysInfo())
    hub.engine = engine

    def save_tokens(tokens: list) -> None:
        state.tokens = tokens
        state.save()

    auth = Auth(pin_hash, tokens=state.tokens, on_tokens=save_tokens)
    stop = asyncio.Event()
    after = {"action": None}

    def on_sys(action: str):
        if action in ("reboot", "shutdown") and not sys.platform.startswith("linux"):
            return f"{action} only works on the pi"
        engine.event("warn", f"{action} asked for by an admin")
        after["action"] = action
        stop.set()
        return None

    commands = Commands(engine, on_sys)
    web_dir = Path(args.web) if args.web else paths.default_web()
    if web_dir is not None and not (web_dir / "index.html").is_file():
        log.warning("no index.html in %s, the web app is not served from here", web_dir)
    elif web_dir is None and paths.repo_root() is not None and not getattr(args, "demo", False):
        log.info("no web app in %s, deploy/web.sh puts it there", paths.repo_root() / "web")
    app = make_app(engine, hub, auth, commands, web_dir)
    runner = web.AppRunner(app, access_log=None, handle_signals=False)
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.http_port)
    try:
        await site.start()
    except OSError as e:
        log.error("cannot listen on %s port %s, %s", args.host, args.http_port, e)
        await runner.cleanup()
        writer.close()
        return 1

    _install_signals(stop)
    await driver.start()
    log.info(
        "brainsolpi on http://%s:%s with the %s driver%s",
        args.host, args.http_port, driver.name, f", web app from {web_dir}" if web_dir else "",
    )
    if getattr(args, "ready", None) is not None:
        # the address is only worth printing once the port really listens
        args.ready(web_dir if web_dir is not None and (web_dir / "index.html").is_file() else None)
    loop_task = asyncio.create_task(engine.run(stop))
    stop_task = asyncio.create_task(stop.wait())
    watch_task = None
    if not args.pin:
        watch_task = asyncio.create_task(_watch_pin(settings, auth, hub, engine))
    board_task = None
    if args.driver == "auto" and isinstance(driver, SimDriver):
        # the in place restart only exists on linux, elsewhere the log says what to do
        can_restart = os.name == "posix"
        engine.event(
            "info",
            f"the sim runs until a board shows up, the tracker looks for one every {BOARD_WATCH_S:.0f} s",
        )
        flasher = autoflash(args, settings, state)
        if flasher is not None:
            log.info("an uno r3 that does not answer gets the bridge firmware by itself, "
                     "serial.autoflash false in %s turns that off", settings.path)
        board_task = asyncio.create_task(
            _watch_board(board_watch(args, looked), engine, stop, after, can_restart, flasher=flasher))
    try:
        await asyncio.wait({loop_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        stop.set()
        try:
            await asyncio.wait_for(loop_task, 5.0)
        except asyncio.TimeoutError:
            log.error("the control loop did not stop in time")
            loop_task.cancel()
    finally:
        stop_task.cancel()
        if watch_task is not None:
            watch_task.cancel()
        if board_task is not None:
            board_task.cancel()
        await hub.close_all()
        await runner.cleanup()
        await driver.stop()
        writer.close()
        log.info("stopped, pose and settings saved")
    return _after(after["action"])


def _after(action: str | None) -> int:
    if action == "restart":
        if os.name == "posix":
            log.info("restarting")
            os.execv(sys.executable, [sys.executable, "-m", "brainsolpi", *sys.argv[1:]])
        return RESTART_CODE
    if action in ("reboot", "shutdown"):
        verb = "reboot" if action == "reboot" else "poweroff"
        try:
            subprocess.run(["sudo", "-n", "systemctl", verb], check=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as e:
            log.error("%s failed, %s, the service user needs a sudoers rule for systemctl %s", action, e, verb)
            return 1
    return 0


def run(args) -> int:
    try:
        return asyncio.run(serve(args))
    except KeyboardInterrupt:
        return 0
