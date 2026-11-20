from dataclasses import replace
import errno
import os
from pathlib import Path

import pytest

from alternate_exchange_witness import ExchangeFence, verify_exchange
import host_checkpoint as checkpoint
import host_exchange as exchange
from launcher_witness import LAUNCH_FILES, LauncherPolicy
from site_policy import load_policy
from test_host_check_main import build_fixture_archive
from test_host_checkpoint import fake_process, site
from test_host_exchange import disk_journal, fixture, interrupt, loaded, states


pytestmark = pytest.mark.skipif(os.geteuid() == 0, reason="Requires a non-root release account")


def approve(controller, generation):
    policy = loaded(controller)
    return ExchangeFence(controller.policy_path, policy.sha256, policy.generation, generation,
                         os.geteuid(), tuple((pair.canonical, pair.parked) for pair in policy.pairs))


@pytest.fixture
def closed(fixture):
    controller, _ = fixture
    generation = controller.prepare()
    controller.close()
    return approve(controller, generation)


def test_exact_closed_exchange_accepts_without_updating_journal(fixture):
    controller, _ = fixture
    generation = controller.prepare()
    controller.close()
    approved = approve(controller, generation)
    journal = controller.policy_path.parent / "exchange.json"
    before = journal.stat(), journal.read_bytes()
    verify_exchange(approved)
    assert journal.read_bytes() == before[1]
    after = journal.stat()
    assert (after.st_ino, after.st_mtime_ns, after.st_ctime_ns) == (
        before[0].st_ino, before[0].st_mtime_ns, before[0].st_ctime_ns,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [("generation", "f" * 32), ("policy_sha256", "f" * 64), ("intent_sha256", "f" * 64)],
)
def test_foreign_approval_refuses(closed, field, value):
    with pytest.raises(ValueError, match="approved closed generation|policy seal mismatch"):
        verify_exchange(replace(closed, **{field: value}))


def test_reordered_routes_refuse_even_with_the_same_members(closed):
    with pytest.raises(ValueError, match="approved closed generation"):
        verify_exchange(replace(closed, pairs=tuple(reversed(closed.pairs))))


def test_interrupted_closure_requires_completed_replay(fixture, monkeypatch):
    controller, _ = fixture
    generation = controller.prepare()
    approved = approve(controller, generation)
    with pytest.raises(ValueError, match="phase is not durable"):
        verify_exchange(approved)
    interrupt(monkeypatch, controller.close, "_exchange")
    assert states(controller) == [False, True, True]
    before = disk_journal(controller)
    with pytest.raises(ValueError, match="phase is not durable"):
        verify_exchange(approved)
    assert disk_journal(controller) == before
    controller.close()
    verify_exchange(approved)


@pytest.mark.parametrize("phase", ["closed", exchange.CLOSED_ACKNOWLEDGED])
def test_closure_witness_requires_first_directory_sync(fixture, monkeypatch, phase):
    controller, _ = fixture
    generation = controller.prepare()
    approved = approve(controller, generation)
    control_inode = loaded(controller).control_pin.inode
    real_sync = exchange.os.fsync
    terminal_syncs = []

    def fail_after_visible_terminal_replace(fd):
        current = disk_journal(controller)["phase"] if os.fstat(fd).st_ino == control_inode else None
        if current == phase:
            raise OSError(errno.EIO, "fixture directory sync interruption")
        real_sync(fd)
        if current == "closed":
            terminal_syncs.append(current)

    with monkeypatch.context() as patch:
        patch.setattr(exchange.os, "fsync", fail_after_visible_terminal_replace)
        with pytest.raises(exchange.Hold, match="errno 5"):
            controller.close()
    assert disk_journal(controller)["phase"] == phase
    assert states(controller) == [False, False, False]

    if phase == "closed":
        with pytest.raises(ValueError, match="phase is not durable"):
            verify_exchange(approved)
        with pytest.raises(exchange.Hold, match="closure is incomplete"):
            controller.restore(b"synthetic terminal receipt", verify_terminal=lambda *_: True)
        assert terminal_syncs == []
    else:
        assert terminal_syncs == ["closed"]
        verify_exchange(approved)

    def unexpected_swap(*_):
        pytest.fail("A terminal closure replay must preserve the completed placements")

    monkeypatch.setattr(exchange, "_exchange", unexpected_swap)
    replay = exchange.HostExchange(controller.policy_path, controller.approved_sha256)
    replay.close()
    assert disk_journal(replay)["phase"] == exchange.CLOSED_ACKNOWLEDGED
    assert states(replay) == [False, False, False]
    verify_exchange(approved)


def test_restored_checkout_rejects_old_closure_approval(fixture):
    controller, _ = fixture
    generation = controller.prepare()
    closure = controller.close()
    approved = approve(controller, generation)
    verify_exchange(approved)
    evidence = b"synthetic completed maintenance"
    controller.restore(evidence, verify_terminal=lambda witness, data: witness == closure and data == evidence)
    with pytest.raises(ValueError, match="phase is not durable"):
        verify_exchange(approved)


def test_substituted_parked_directory_refuses(closed):
    _, parked = closed.pairs[0]
    parked.rename(parked.with_suffix(".moved"))
    parked.mkdir()
    with pytest.raises(ValueError, match="substituted exchange endpoint"):
        verify_exchange(closed)


def test_site_rejects_a_running_process_in_the_parked_checkout(site, closed, tmp_path):
    policy, _, _, _ = site
    governed = replace(policy, alternate_roots=tuple(closed.active_roots()), covers=(), exchange_fence=closed)
    checkpoint.verify_alternate_writers(governed)
    proc = tmp_path / "processes"
    (proc / "1").mkdir(parents=True)
    (proc / "1/comm").write_text("systemd\n")
    (proc / "1/cmdline").write_bytes(b"")
    _, parked = closed.pairs[0]
    fake_process(proc, 302, 1, ["/usr/bin/python3"], "/usr/bin/python3", parked)
    with pytest.raises(ValueError, match="Checkout process remains live"):
        checkpoint.verify_route_drain(governed, 0, proc)


def test_no_alternate_route_may_be_omitted(site, closed, tmp_path):
    policy, _, _, _ = site
    governed = replace(policy, alternate_roots=(*closed.active_roots(), tmp_path / "unheld"),
                       covers=(), exchange_fence=closed)
    with pytest.raises(ValueError, match="approved exchange"):
        checkpoint.verify_alternate_writers(governed)


def test_approved_archive_round_trips_controller_identity(site, closed, tmp_path):
    policy, _, _, _ = site
    policy = replace(policy, marker=policy.project / ".state/integration-release-journal.json",
                     lock_paths=(policy.project / ".state/scraper.lock",), exchange_fence=closed,
                     alternate_roots=tuple(canonical for canonical, _ in closed.pairs), covers=())
    pin = tmp_path / "protected-pin"
    pins = {name: "a" * 64 for name in LAUNCH_FILES}
    launcher = LauncherPolicy(policy.project / ".venv/bin/python", Path("/usr/bin/python3"),
                              Path("/usr/bin/bash"), (), pins, pins)
    bundle = build_fixture_archive(policy, pin, "b" * 64, launcher)
    assert load_policy(bundle) == (policy, pin, "b" * 64, launcher)
