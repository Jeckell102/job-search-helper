"""Run local SQLite/workspace fixtures with socket and external process guards."""

from pathlib import Path
import sys

root = Path.cwd()


def permitted(event, args):
    if event.startswith("socket.") or event in {"os.exec", "os.posix_spawn", "os.system"}:
        raise AssertionError(f"Local fixture disallows {event}")
    if event == "subprocess.Popen":
        executable, arguments, _, _ = args
        if executable != "git" or "-C" not in arguments:
            raise AssertionError(f"Unexpected fixture subprocess {executable}")
        index = arguments.index("-C")
        location, action = Path(arguments[index + 1]), arguments[index + 2]
        if not location.is_relative_to(root) or action not in {"init", "add", "commit", "status", "rev-parse", "diff", "ls-files"}:
            raise AssertionError(f"Unexpected fixture Git scope/action {location} {action}")
    if event == "open" and isinstance(args[0], str) and args[0].startswith("/home/chris/job-search-helper_old/"):
        raise AssertionError("Local fixture disallows native checkout reads")


sys.addaudithook(permitted)
import pytest

raise SystemExit(pytest.main(["-q", "-s", "-p", "no:cacheprovider", "--basetemp", str(root / "pytest-work"),
                              "tests/test_successor_composed.py"]))
