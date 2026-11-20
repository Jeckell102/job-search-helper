"""Public helper dispatch shared by checkout and installed console launchers."""
from __future__ import annotations
import os
from pathlib import Path
import sys


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Treat the short resume forms as the automated runner's explicit resume
    # mode.  The legacy CLI's `resume` subcommand requires a cycle ID, while
    # this shorthand intentionally selects the newest incomplete scan.
    if arguments and arguments[0] in {'resume', '-resume'} and not any(
            arg == '--cycle' or arg.startswith('--cycle=') for arg in arguments[1:]):
        arguments = ['start', '--resume', *arguments[1:]]
    if arguments and arguments[0] == 'start':
        bootstrap = Path(__file__).resolve().parents[2] / 'release_admission_bootstrap.py'
        if not bootstrap.is_file():
            print('Start requires the release admission launcher from a project checkout.', file=sys.stderr)
            return 2
        os.execv(sys.executable, [sys.executable, '-I', '-S', str(bootstrap), *arguments])
    from .cli import main as run
    return run(arguments)


if __name__ == '__main__':
    raise SystemExit(main())
