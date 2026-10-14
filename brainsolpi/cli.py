from __future__ import annotations

import argparse
import logging
import sys

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

    fl = sub.add_parser("flash", help="upload the bridge firmware to the board")
    fl.add_argument("--port", help="serial port of the board")
    fl.add_argument("--hex", help="firmware file, default firmware/brainsol_bridge.hex in the repo")

    sp = sub.add_parser("setpin", help="set the admin pin")
    sp.add_argument("--config-dir", help="folder for settings.json")

    ce = sub.add_parser("centre", help="hold both servos at 1500 us while mounting the horns")
    ce.add_argument("--port", help="serial port of the board")
    ce.add_argument("--config-dir", help="folder for state.json")
    return p


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
