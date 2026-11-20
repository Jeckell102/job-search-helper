from dataclasses import replace
import os
from pathlib import Path
import socket
import time

import pytest

import ancillary_process_witness as witness
import host_checkpoint as checker
from test_host_checkpoint import fake_process, site


@pytest.fixture
def inaccessible(site, tmp_path, monkeypatch):
    policy, _, _, _ = site
    proc = tmp_path / "proc"
    init = proc / "1"
    init.mkdir(parents=True)
    (init / "comm").write_text("systemd\n")
    (init / "cmdline").write_bytes(b"")
    boot = proc / "sys/kernel/random/boot_id"
    boot.parent.mkdir(parents=True)
    boot.write_text("fixture-boot\n")
    process = fake_process(proc, 201, 1, ["/usr/bin/ssh-agent"], "/usr/bin/ssh-agent", tmp_path)
    (process / "comm").write_text("ssh-agent\n")
    (process / "root").symlink_to("/")
    (process / "cgroup").write_text("0::/fixture/session.scope\n")
    original = os.readlink

    def readlink(path, *args, **kwargs):
        if Path(path) == process / "cwd":
            raise PermissionError("fixture protected process")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "readlink", readlink)
    path = Path("/run/approved-maintenance/process-observer.sock")
    equipped = replace(policy, ancillary_process_evidence=path)
    return policy, equipped, proc, process


def test_inaccessible_helper_requires_a_new_exact_observation_each_time(inaccessible, monkeypatch):
    original, approved, proc, process = inaccessible
    with pytest.raises(ValueError, match="metadata is unavailable"):
        checker.verify_route_drain(original, 0, proc)
    requests = []

    def observe(path, request):
        assert path == approved.ancillary_process_evidence
        requests.append(request)
        assert request["scope"] == witness.scope(
            proc, approved.launch_uid, approved.maintenance_id, (approved.project, *approved.alternate_roots),
        )
        return {"request": request, "process": witness.process_identity(process)}

    monkeypatch.setattr(witness, "request_privileged", observe)
    checker.verify_route_drain(approved, 0, proc)
    checker.verify_route_drain(approved, 0, proc)
    assert len(requests) == 2
    assert requests[0]["challenge"] != requests[1]["challenge"]


@pytest.mark.parametrize("field", ["challenge", "boot", "route", "start", "role"])
def test_stale_foreign_or_changed_helper_is_held(inaccessible, field, monkeypatch):
    _, approved, proc, process = inaccessible

    def foreign(path, request):
        import json
        different = json.loads(witness.encoded(request))
        observed = witness.process_identity(process)
        if field == "challenge":
            different["challenge"] = "0" * 32
        elif field == "boot":
            different["scope"]["boot"] = "other"
        elif field == "route":
            different["scope"]["routes"].pop()
        elif field == "start":
            observed["started"] += 1
        else:
            (process / "comm").write_text("node_repl\n")
            observed = witness.process_identity(process)
        return {"request": different, "process": observed}

    monkeypatch.setattr(witness, "request_privileged", foreign)
    with pytest.raises(ValueError, match="Administrator evidence"):
        checker.verify_route_drain(approved, 0, proc)


def test_never_skips_readable_checkout_descriptor_when_cwd_unreadable(inaccessible, monkeypatch):
    _, approved, proc, process = inaccessible
    (process / "fd/4").symlink_to(approved.project / "worker")
    monkeypatch.setattr(witness, "request_privileged", lambda *_: pytest.fail("Already-visible writer"))
    with pytest.raises(ValueError, match="Checkout descriptor remains open"):
        checker.verify_route_drain(approved, 0, proc)


def test_missing_administrator_observer_holds(inaccessible, monkeypatch):
    _, approved, proc, _ = inaccessible

    def disconnected(*_):
        raise FileNotFoundError()

    monkeypatch.setattr(witness, "request_privileged", disconnected)
    with pytest.raises(ValueError, match="observation is unavailable"):
        checker.verify_route_drain(approved, 0, proc)


def test_existing_process_cannot_be_skipped_when_metadata_is_missing(inaccessible):
    _, approved, proc, process = inaccessible
    (process / "root").unlink()
    with pytest.raises(ValueError, match="process metadata is incomplete"):
        checker.verify_route_drain(approved, 0, proc)


def test_transport_reads_exact_bytes_and_kernel_peer_credentials():
    client, server = socket.socketpair()
    with client, server:
        assert witness.peer_uid(client) == os.geteuid()
        client.sendall(witness.encoded({"example": "disposable"}))
        client.shutdown(socket.SHUT_WR)
        assert witness.receive(server, time.monotonic() + 1) == {"example": "disposable"}


def test_expired_receive_deadline_cannot_accept_an_available_message():
    client, server = socket.socketpair()
    with client, server:
        client.sendall(witness.encoded({"example": "disposable"}))
        client.shutdown(socket.SHUT_WR)
        with pytest.raises(ValueError, match="exceeded its deadline"):
            witness.receive(server, time.monotonic() - 1)


def test_user_writable_directory_cannot_supply_administrator_observer(tmp_path):
    with pytest.raises(ValueError, match="under /run"):
        witness.trusted_directory(tmp_path)
