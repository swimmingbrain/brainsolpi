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
from .drivers.sim import SimDriver
from .engine import Engine
from .hub import Hub
from .jsonio import BackgroundWriter
from .server import make_app
from .state import StateStore
from .store import ExperimentStore
from .sysinfo import SysInfo

log = logging.getLogger("brainsolpi")

# exit code that tells a service manager to start us again
RESTART_CODE = 75


async def open_driver(args, settings: Settings) -> Driver:
    kind = args.driver
    if kind == "sim":
        return SimDriver()
    raise SystemExit(f"the {kind} driver is not available")


def _install_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
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
