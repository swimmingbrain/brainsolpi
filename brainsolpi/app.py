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
from .commands import Commands
from .config import Settings
from .drivers.base import Driver
from .drivers.bridge import BridgeDriver
from .drivers.detect import candidates, find_board
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


async def open_driver(args, settings: Settings) -> Driver:
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
    found = await asyncio.get_running_loop().run_in_executor(None, lambda: find_board(AUTO_WAIT_S, ports=ports))
    if found is not None:
        port, _, ident = found
        log.info("found the board on %s, firmware %s", port, ident.fw)
        return BridgeDriver(port, initial=found, rate=rate, slew=slew)
    log.warning("no board answered within %.0f s, falling back to the sim driver", AUTO_WAIT_S)
    return SimDriver(rate=rate)


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
        log.warning("using the pin from the command line, that is meant for development only")
        pin_hash = await asyncio.get_running_loop().run_in_executor(None, hash_pin, args.pin)
    elif not pin_hash:
        log.warning("no admin pin is set, admin login is refused until you run brainsolpi setpin")

    driver = await open_driver(args, settings)
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
    loop_task = asyncio.create_task(engine.run(stop))
    stop_task = asyncio.create_task(stop.wait())
    watch_task = None
    if not args.pin:
        watch_task = asyncio.create_task(_watch_pin(settings, auth, hub, engine))
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
