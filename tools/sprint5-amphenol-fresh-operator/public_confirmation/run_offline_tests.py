"""Run the evaluator's synthetic transport fixtures without outbound operations."""
import sys


def local_only(event, args):
    if event.startswith("socket.") or event in {"subprocess.Popen", "os.exec", "os.posix_spawn", "os.system"}:
        raise AssertionError("Offline fixture disallows process or network operations")
    if event == "open" and isinstance(args[0], str) and args[0].startswith("/home/chris/job-search-helper_old/"):
        raise AssertionError("Offline fixture disallows native project access")


sys.addaudithook(local_only)
import pytest

raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider", "tests/test_confirmation_observer.py"]))
