"""Disposable unit checks for the outer controller's host-check deadline."""
from contextlib import nullcontext
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import controller


def fixture_controller(tmp_path):
    worker = object.__new__(controller.Controller)
    worker.project = tmp_path / "checkout"
    worker.marker = worker.project / ".state/integration-release-journal.json"
    worker.backend = "sqlite"
    worker.hold_id = "disposable"
    worker.locks = []
    worker.prefixes = []
    worker.manifest = SimpleNamespace(sha256="1" * 64)
    worker.checker = tmp_path / "host-check"
    worker.checker.write_bytes(b"fixture")
    worker.binding = {"files": {str(worker.checker): controller.ref(worker.checker)}}
    return worker


@pytest.mark.parametrize("checkpoint,timeout", [("held:entry", 5), ("held:controller", 180), ("restored", 180)])
def test_exact_checkpoint_selects_bounded_budget_and_new_session(tmp_path, monkeypatch, checkpoint, timeout):
    worker = fixture_controller(tmp_path)

    def echo(data, *, timeout):
        return json.dumps({**json.loads(data), "verified": True}).encode(), None

    process = SimpleNamespace(returncode=0, communicate=Mock(side_effect=echo))
    launched = Mock(return_value=nullcontext(process))
    monkeypatch.setattr(controller.subprocess, "Popen", launched)
    worker.hook(checkpoint, package=worker.project / "src/job_search_helper", target="INSTALLED")
    assert process.communicate.call_args.kwargs["timeout"] == timeout
    assert launched.call_args.kwargs["start_new_session"] is True


def test_timeout_kills_and_reaps_only_the_new_child_group(tmp_path, monkeypatch):
    worker = fixture_controller(tmp_path)
    timer = controller.subprocess.TimeoutExpired("fixture", 5)
    process = SimpleNamespace(pid=817, communicate=Mock(side_effect=[timer, (b"", None)]))
    monkeypatch.setattr(controller.subprocess, "Popen", Mock(return_value=nullcontext(process)))
    kill = Mock()
    monkeypatch.setattr(controller.os, "killpg", kill)
    with pytest.raises(ValueError, match="exceeded its checkpoint deadline"):
        worker.hook("held:entry", package=Path("/unused/fixture/package"), target="INSTALLED")
    kill.assert_called_once_with(process.pid, controller.signal.SIGKILL)
    assert process.communicate.call_count == 2
