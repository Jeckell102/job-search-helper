"""Public command line for the local catalog, without legacy integrations."""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .local_commands import add_commands, execute


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="job-search-helper", description="Collect job postings and track applications locally.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")
    add_commands(commands)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        return execute(args)
    except KeyboardInterrupt:
        print("Interrupted. Use local status to inspect saved progress.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
