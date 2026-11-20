from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path

import pytest

import alternate_exchange_witness as witness
import host_checkpoint as checkpoint
from test_host_checkpoint import fake_process, site


def identity(path):
    fd = os.open(path, os.O_PATH | os.O_NOFOLLOW)
    try:
        return witness.directory_identity(fd)
    finally:
        os.close(fd)


@pytest.fixture
def closed(tmp_path):
    parent = tmp_path / "checkouts"
    parent.mkdir(mode=0o700)
    control = tmp_path / "control"
    control.mkdir(mode=0o700)
    source = parent / "alternate"
    parked = parent / ".exchange-park-fixture"
    source.mkdir(mode=0o500)
    parked.mkdir()
    (parked / "job-search-scraper").write_text("disposable source")
    lock = control / "exchange.lock"
    lock.touch(mode=0o600)
    journal_path = control / "exchange.json"
    pairs = [{"names": [source.name, parked.name], "sentinel": identity(source), "original": identity(parked)}]
    intent = {"schema": "test-exchange", "generation": "e" * 32, "pairs": pairs}
    checksum = sha256(json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    journal = {"phase": "closed", "completed": 1, "terminal_proof_sha256": None,
               "intent_sha256": checksum, "intent": intent}
    journal_path.write_text(json.dumps(journal))
    journal_path.chmod(0o600)
    ns = Path("/proc/self/ns/mnt").stat()
    return witness.ExchangeFence(parent, control, (ns.st_dev, ns.st_ino), intent["generation"], checksum,
                                 intent["schema"], os.geteuid(), identity(parent), identity(control), identity(lock),
                                 ((source.name, parked.name),))


def test_exact_closed_exchange_accepts_and_foreign_generation_refuses(closed):
    witness.verify_exchange(closed)
    with pytest.raises(ValueError, match="approved closed generation"):
        witness.verify_exchange(replace(closed, generation="f" * 32))


def test_substituted_parked_directory_refuses(closed):
    [parked] = closed.parked_roots()
    parked.rename(parked.with_suffix(".moved"))
    parked.mkdir()
    with pytest.raises(ValueError, match="approved identity"):
        witness.verify_exchange(closed)


def test_site_rejects_a_running_process_in_the_parked_checkout(site, closed, tmp_path):
    policy, _, _, _ = site
    governed = replace(policy, alternate_roots=tuple(closed.active_roots()), covers=(), exchange_fence=closed)
    checkpoint.verify_alternate_writers(governed)
    proc = tmp_path / "processes"
    (proc / "1").mkdir(parents=True)
    (proc / "1/comm").write_text("systemd\n")
    (proc / "1/cmdline").write_bytes(b"")
    [parked] = closed.parked_roots()
    fake_process(proc, 302, 1, ["/usr/bin/python3"], "/usr/bin/python3", parked)
    with pytest.raises(ValueError, match="Checkout process remains live"):
        checkpoint.verify_route_drain(governed, 0, proc)


def test_no_alternate_route_may_be_omitted(site, closed, tmp_path):
    policy, _, _, _ = site
    governed = replace(policy, alternate_roots=(*closed.active_roots(), tmp_path / "unheld"),
                       covers=(), exchange_fence=closed)
    with pytest.raises(ValueError, match="approved exchange"):
        checkpoint.verify_alternate_writers(governed)
