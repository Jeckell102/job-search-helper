import hashlib
import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path

import pytest


MODULE = Path(__file__).parents[1] / "deploy_host_forward.py"
SPEC = importlib.util.spec_from_file_location("host_forward", MODULE)
forward = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(forward)


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Controller:
    @contextmanager
    def restoration_terminal(self):
        yield {"source": "INSTALLED", "maintenance_id": "s5-operator-trigger-20261121-03",
               "installer_receipt_sha256": self.receipt, "source_manifest_sha256": "d" * 64,
               "controller_journal_sha256": "e" * 64}


def make_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "dev/wrapper-coder/tools").mkdir(parents=True)
    (project / "dev/wrapper-coder/repairs").mkdir(parents=True)
    (project / "dev/wrapper-coder/repairs/deployment.lock").write_bytes(b"")
    host = project / forward.HOST_RELATIVE
    before = b"before-host"
    after = b"after-host"
    monkeypatch.setattr(forward, "BEFORE_SHA256", digest(before))
    monkeypatch.setattr(forward, "AFTER_SHA256", digest(after))
    host.write_bytes(before)
    host.chmod(0o640)
    scope = {}
    for index, relative in enumerate(sorted(forward.REMAINING_SCOPE)):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"scope-{index}".encode()
        path.write_bytes(payload)
        scope[relative] = digest(payload)
    receipts = tmp_path / "receipts"
    receipts.mkdir(mode=0o700)
    idle = {"task_sha256": forward.TERMINAL_TASK_SHA256, "receipt_sha256": forward.TERMINAL_RECEIPT_SHA256,
            "open_inference": 0, "service": forward.SERVICE_NAME,
            "controls": {"queue": False, "campaign": False, "autopilot": False, "unqualified_release": False}}
    return project, host, before, after, scope, receipts, idle


def controller(receipt):
    result = Controller()
    result.receipt = receipt
    return result


def exchange(receipt):
    return lambda _: {"restored_exchange": True, "predecessor_receipt_sha256": receipt}


def test_installs_only_host_and_keeps_predecessor_as_history(tmp_path, monkeypatch):
    project, host, before, after, scope, receipts, idle = make_project(tmp_path, monkeypatch)
    calls = []
    receipt = forward.apply_host_forward(
        project=project, controller=controller("a" * 64), candidate=after, predecessor_receipt_sha256="a" * 64,
        remaining_scope=scope, idle_probe=lambda: idle, exchange_probe=exchange("a" * 64), restart_probe=lambda: idle,
        stop_service=lambda unit: calls.append(("stop", unit)), start_service=lambda unit: calls.append(("start", unit)),
        stopped_probe=lambda: True,
        receipt_directory=receipts)
    assert host.read_bytes() == after
    assert calls == [("stop", forward.SERVICE_NAME), ("start", forward.SERVICE_NAME)]
    assert receipt["status"] == "HOST_FORWARD_INSTALLED"
    persisted = json.loads((receipts / "host-forward-receipt.json").read_text())
    assert persisted["predecessor"]["receipt_sha256"] == "a" * 64
    assert (receipts / "host_server.py.before").read_bytes() == before


def test_restart_failure_restores_actual_before_contents_and_records_rollback(tmp_path, monkeypatch):
    project, host, before, after, scope, receipts, idle = make_project(tmp_path, monkeypatch)
    calls = []
    running = {"bytes": before}
    stopped = {"value": False}
    probes = {"count": 0}
    def stops(unit):
        calls.append(("stop", unit))
        stopped["value"] = True
    def starts(unit):
        calls.append(("start", unit))
        running["bytes"] = host.read_bytes()  # emulate idempotent systemd start consuming current file.
        stopped["value"] = False
    def restart_probe():
        probes["count"] += 1
        if probes["count"] == 1:
            raise RuntimeError("restart failed")
        return idle
    with pytest.raises(RuntimeError, match="restart failed"):
        forward.apply_host_forward(
            project=project, controller=controller("b" * 64), candidate=after, predecessor_receipt_sha256="b" * 64,
            remaining_scope=scope, idle_probe=lambda: idle,
            exchange_probe=exchange("b" * 64),
            restart_probe=restart_probe,
            stop_service=stops, start_service=starts, stopped_probe=lambda: stopped["value"], receipt_directory=receipts)
    assert host.read_bytes() == before
    assert running["bytes"] == before
    assert calls == [("stop", forward.SERVICE_NAME), ("start", forward.SERVICE_NAME),
                     ("stop", forward.SERVICE_NAME), ("start", forward.SERVICE_NAME)]
    assert probes["count"] == 2  # original source had to pass readback before rollback receipt.
    assert json.loads((receipts / "host-forward-receipt.json").read_text())["status"] == "HOST_FORWARD_ROLLED_BACK"


def test_rejects_open_inference_before_service_stop(tmp_path, monkeypatch):
    project, host, before, after, scope, receipts, idle = make_project(tmp_path, monkeypatch)
    idle = dict(idle, open_inference=1)
    with pytest.raises(forward.HostForwardError, match="Inference is open"):
        forward.apply_host_forward(
            project=project, controller=controller("c" * 64), candidate=after, predecessor_receipt_sha256="c" * 64,
            remaining_scope=scope, idle_probe=lambda: idle, exchange_probe=exchange("c" * 64), restart_probe=lambda: idle,
            stop_service=lambda _: pytest.fail("must not stop"), start_service=lambda _: pytest.fail("must not start"),
            stopped_probe=lambda: pytest.fail("must not probe"),
            receipt_directory=receipts)
    assert host.read_bytes() == before


def test_initial_stop_refusal_never_rewrites_host(tmp_path, monkeypatch):
    project, host, before, after, scope, receipts, idle = make_project(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="stop refused"):
        forward.apply_host_forward(
            project=project, controller=controller("d" * 64), candidate=after, predecessor_receipt_sha256="d" * 64,
            remaining_scope=scope, idle_probe=lambda: idle, exchange_probe=exchange("d" * 64), restart_probe=lambda: idle,
            stop_service=lambda _: (_ for _ in ()).throw(RuntimeError("stop refused")),
            start_service=lambda _: pytest.fail("must not start"), stopped_probe=lambda: pytest.fail("must not probe"),
            receipt_directory=receipts)
    assert host.read_bytes() == before


def test_post_rename_write_error_measures_candidate_then_restores(tmp_path, monkeypatch):
    project, host, before, after, scope, receipts, idle = make_project(tmp_path, monkeypatch)
    original_write = forward._write_atomic
    calls, stopped = [], {"value": False}
    def write_then_fail(path, data, mode):
        original_write(path, data, mode)
        if data == after:
            raise OSError("directory fsync reported late failure")
    monkeypatch.setattr(forward, "_write_atomic", write_then_fail)
    def stops(unit):
        calls.append(("stop", unit))
        stopped["value"] = True
    def starts(unit):
        calls.append(("start", unit))
        stopped["value"] = False
    with pytest.raises(OSError, match="late failure"):
        forward.apply_host_forward(
            project=project, controller=controller("e" * 64), candidate=after, predecessor_receipt_sha256="e" * 64,
            remaining_scope=scope, idle_probe=lambda: idle, exchange_probe=exchange("e" * 64), restart_probe=lambda: idle,
            stop_service=stops, start_service=starts, stopped_probe=lambda: stopped["value"], receipt_directory=receipts)
    assert host.read_bytes() == before
    assert calls == [("stop", forward.SERVICE_NAME), ("start", forward.SERVICE_NAME)]


def test_post_start_error_stops_after_process_then_restores(tmp_path, monkeypatch):
    project, host, before, after, scope, receipts, idle = make_project(tmp_path, monkeypatch)
    calls, stopped, running = [], {"value": False}, {"bytes": before}
    def stops(unit):
        calls.append(("stop", unit))
        stopped["value"] = True
    def starts_then_error(unit):
        calls.append(("start", unit))
        running["bytes"] = host.read_bytes()
        stopped["value"] = False
        if len([event for event in calls if event[0] == "start"]) == 1:
            raise RuntimeError("started then status failed")
    with pytest.raises(RuntimeError, match="started then status failed"):
        forward.apply_host_forward(
            project=project, controller=controller("f" * 64), candidate=after, predecessor_receipt_sha256="f" * 64,
            remaining_scope=scope, idle_probe=lambda: idle, exchange_probe=exchange("f" * 64), restart_probe=lambda: idle,
            stop_service=stops, start_service=starts_then_error, stopped_probe=lambda: stopped["value"], receipt_directory=receipts)
    assert host.read_bytes() == before
    assert running["bytes"] == before
    assert calls == [("stop", forward.SERVICE_NAME), ("start", forward.SERVICE_NAME),
                     ("stop", forward.SERVICE_NAME), ("start", forward.SERVICE_NAME)]


def test_visible_success_receipt_with_directory_sync_failure_keeps_candidate_running(tmp_path, monkeypatch):
    project, host, before, after, scope, receipts, idle = make_project(tmp_path, monkeypatch)
    receipt_path = receipts / "host-forward-receipt.json"
    real_fsync = forward.os.fsync
    fired, stopped, running = [], {"value": False}, {"bytes": before}
    def sync(fd):
        if not fired and receipt_path.exists() and Path(f"/proc/self/fd/{fd}").resolve() == receipts:
            fired.append(True)
            raise OSError("injected receipt directory fsync failure")
        real_fsync(fd)
    def stops(_):
        stopped["value"] = True
    def starts(_):
        running["bytes"] = host.read_bytes()
        stopped["value"] = False
    monkeypatch.setattr(forward.os, "fsync", sync)
    with pytest.raises(forward.HostForwardDurabilityUncertain, match="durability is uncertain"):
        forward.apply_host_forward(
            project=project, controller=controller("g" * 64), candidate=after, predecessor_receipt_sha256="g" * 64,
            remaining_scope=scope, idle_probe=lambda: idle, exchange_probe=exchange("g" * 64), restart_probe=lambda: idle,
            stop_service=stops, start_service=starts, stopped_probe=lambda: stopped["value"], receipt_directory=receipts)
    assert fired
    assert host.read_bytes() == after
    assert running["bytes"] == after
    assert json.loads(receipt_path.read_text())["status"] == "HOST_FORWARD_INSTALLED"

