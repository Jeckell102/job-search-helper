"""Public helper dispatch shared by checkout and installed console launchers."""
from __future__ import annotations
import sys


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Treat the short resume forms as the automated runner's explicit resume
    # mode.  The legacy CLI's `resume` subcommand requires a cycle ID, while
    # this shorthand intentionally selects the newest incomplete scan.
    if arguments and arguments[0] in {'resume', '-resume'} and '--cycle' not in arguments:
        arguments = ['start', '--resume', *arguments[1:]]
    if arguments and arguments[0] == 'start':
        from .runner import main as run
    else:
        from .cli import main as run
    return run(arguments)


if __name__ == '__main__':
    raise SystemExit(main())
