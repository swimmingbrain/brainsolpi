from __future__ import annotations

import argparse
import logging
import secrets
import sys
import tempfile
from pathlib import Path

from . import __version__

DRIVERS = ("auto", "sim", "bridge", "fake")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="brainsolpi",
        description="brainSOL tracker service for the Raspberry Pi",
    )
    p.add_argument("--version", action="version", version=f"brainsolpi {__version__}")
    sub = p.add_subparsers(dest="command", metavar="command")

    run = sub.add_parser("run", help="run the tracker and the web server")
    run.add_argument(
        "--driver",
        choices=DRIVERS,
        default="auto",
        help="auto uses the board when one answers within 6 s, else the sim, "
        "fake runs a simulated board behind the serial protocol",
    )
    run.add_argument("--port", help="serial port of the board, found by itself when left out")
    run.add_argument("--host", default="0.0.0.0", help="address to listen on, default 0.0.0.0")
    run.add_argument("--http-port", type=int, default=8080, help="http port, default 8080")
    run.add_argument("--pin", help="admin pin for development, the hash in the settings is used otherwise")
    run.add_argument("--web", help="folder with the built web app, default web in the repo when it exists")
    run.add_argument("--config-dir", help="folder for settings.json and state.json")
    run.add_argument("--data-dir", help="folder for experiments and recordings")
    run.add_argument("-v", "--verbose", action="store_true", help="more log output")

    doc = sub.add_parser("doctor", help="check the hardware step by step")
    doc.add_argument("--port", help="serial port of the board")
    doc.add_argument("--fake", action="store_true", help="talk to a simulated board, to try the checks")
    doc.add_argument("--yes", action="store_true", help="answer yes to every question, no waiting for keys")
    doc.add_argument("--config-dir", help="folder for settings.json and state.json")

    fl = sub.add_parser("flash", help="upload the bridge firmware to the board")
    fl.add_argument("--port", help="serial port of the board")
    fl.add_argument("--hex", help="firmware file, default firmware/brainsol_bridge.hex in the repo")

    sp = sub.add_parser("setpin", help="set the admin pin")
    sp.add_argument("--config-dir", help="folder for settings.json")
    sp.add_argument("--check", action="store_true",
                    help="only tell whether a pin is set, exit code 0 when one is set and 1 when not")

    ce = sub.add_parser("centre", help="hold both servos at 1500 us while mounting the horns")
    ce.add_argument("--port", help="serial port of the board")
    ce.add_argument("--config-dir", help="folder for state.json")

    de = sub.add_parser("demo", help="try the whole tracker simulated on this computer, nothing is kept")
    de.add_argument("--http-port", type=int, default=8080, help="http port, default 8080")
    return p


def demo_args(args) -> argparse.Namespace:
    # run with the sim, only on this computer, a fresh pin and a folder that goes away at the end
    pin = f"{secrets.randbelow(10000):04d}"
    port = args.http_port

    def ready(web_dir) -> None:
        print("brainSOL demo, the whole tracker simulated on this computer")
        hosted = f"https://sol.swimmingbrain.dev/?pi=ws://localhost:{port}"
        if web_dir is not None:
            print(f"  open http://localhost:{port} in a browser, or the hosted page {hosted}")
        else:
            print(f"  open the hosted page in a browser: {hosted}")
        print(f"  admin pin for this run: {pin}")
        print("  nothing is kept, stop it with ctrl c", flush=True)

    return argparse.Namespace(
        driver="sim", port=None, host="127.0.0.1", http_port=port, pin=pin, web=None,
        config_dir=None, data_dir=None, verbose=False, demo=True, ready=ready,
    )


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    if not verbose:
        logging.getLogger("aiohttp").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "run":
        setup_logging(args.verbose)
        from .app import run

        return run(args)
    if args.command == "demo":
        # only warnings in the log, the few lines of the demo say the rest
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
        from .app import run

        run_args = demo_args(args)
        with tempfile.TemporaryDirectory(prefix="brainsolpi-demo-", ignore_cleanup_errors=True) as tmp:
            run_args.config_dir = str(Path(tmp) / "config")
            run_args.data_dir = str(Path(tmp) / "data")
            return run(run_args)
    # the helper commands talk to people, warnings only in the log
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        if args.command == "doctor":
            from .doctor import doctor

            return doctor(args)
        from . import tools

        return {"flash": tools.flash, "setpin": tools.setpin, "centre": tools.centre}[args.command](args)
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
        return 130
