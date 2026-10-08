from __future__ import annotations

import argparse
import sys

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="brainsolpi",
        description="brainSOL tracker service for the Raspberry Pi",
    )
    p.add_argument("--version", action="version", version=f"brainsolpi {__version__}")
    sub = p.add_subparsers(dest="command", metavar="command")
    sub.add_parser("run", help="run the tracker and the web server")
    sub.add_parser("doctor", help="check the hardware step by step")
    sub.add_parser("flash", help="upload the bridge firmware to the board")
    sub.add_parser("setpin", help="set the admin pin")
    sub.add_parser("centre", help="hold both servos at 1500 us while mounting the horns")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    print(f"{args.command} is not ready yet", file=sys.stderr)
    return 1
