from hashlib import sha256
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import protected_continuity as continuity
from protected_state import WitnessHold


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    bundle = tmp_path / "private-bundle"
    bundle.mkdir(mode=0o700)
    pin = tmp_path / "protected-pin.json"
    pin.write_bytes(b"reviewed synthetic protected state")
    pin.chmod(0o600)
    policy = SimpleNamespace(maintenance_bundle=bundle, project=tmp_path / "project",
                             manifest_sha256="1" * 64, maintenance_id="test-hold")
    physical = Mock(return_value="a" * 64)
    monkeypatch.setattr(continuity, "physical_snapshot", physical)
    owner = Mock(return_value=("boot", 8, "137"))
    full = Mock(return_value=True)

    def checkpoint(label, *, target="INSTALLED"):
        return continuity.ProtectedContinuity(
            policy=policy, protected_pin=pin, pin_digest=sha256(b"reviewed synthetic protected state").hexdigest(),
            executable_digest="2" * 64, request={"checkpoint": label, "target": target},
            owner=owner, full_check=full,
        )

    return checkpoint, full, physical, owner


def test_no_short_receipt_until_complete_site_attestation(evidence):
    checkpoint, full, _, _ = evidence
    enroll = checkpoint("held:controller")
    assert enroll("held", "INSTALLED")
    assert json.loads(enroll.receipt.read_bytes())["state"] == "pending"
    with pytest.raises(WitnessHold, match="different hold"):
        checkpoint("held:INSTALLING:source.py")("held", "INSTALLED")
    enroll.finalize()
    short = checkpoint("held:INSTALLING:source.py")
    assert short("held", "INSTALLED")
    short.finalize()
    full.assert_called_once_with("held", "INSTALLED")


def test_restarted_controller_or_rollback_cannot_use_preceding_short_receipt(evidence):
    checkpoint, full, _, owner = evidence
    enroll = checkpoint("held:controller")
    enroll("held", "INSTALLED")
    enroll.finalize()
    with pytest.raises(WitnessHold, match="different hold"):
        checkpoint("held:ROLLING_BACK:source.py", target="ROLLED_BACK")("held", "ROLLED_BACK")
    owner.return_value = ("boot", 8, "141")
    with pytest.raises(WitnessHold, match="different hold"):
        checkpoint("held:entry")("held", "INSTALLED")
    full.assert_called_once()


def test_drift_at_end_does_not_authorize_using_a_previous_receipt(evidence):
    checkpoint, _, physical, _ = evidence
    before = checkpoint("held:controller")
    before("held", "INSTALLED")
    before.finalize()
    after = checkpoint("held:controller")
    after("held", "INSTALLED")
    physical.return_value = "b" * 64
    with pytest.raises(WitnessHold, match="changed during"):
        after.finalize()
    assert json.loads(after.receipt.read_bytes())["state"] == "pending"
    with pytest.raises(WitnessHold, match="different hold"):
        checkpoint("held:entry")("held", "INSTALLED")


def test_protected_state_checkpoint_remains_full_at_publication_and_restoration(evidence):
    checkpoint, full, _, _ = evidence
    for stage in ("preflight", "host-fenced", "pre-publish", "published", "admitted", "restoring", "restored"):
        full_checkpoint = checkpoint(stage)
        full_checkpoint(stage, "INSTALLED")
        full_checkpoint.finalize()
    assert full.call_count == 7
    assert not full_checkpoint.receipt.exists()


def test_short_ack_requires_same_verified_receipt_at_finalization(evidence):
    checkpoint, _, _, _ = evidence
    first = checkpoint('held:controller')
    first('held', 'INSTALLED')
    first.finalize()
    short = checkpoint('held:entry')
    short('held', 'INSTALLED')
    interrupted = checkpoint('held:controller')
    interrupted('held', 'INSTALLED')
    with pytest.raises(WitnessHold, match='record changed'):
        short.finalize()


def test_full_checkpoint_never_promotes_receipt_after_pin_changes(evidence):
    checkpoint, _, _, _ = evidence
    candidate = checkpoint('held:controller')
    candidate('held', 'INSTALLED')
    candidate.protected_pin.write_text('changed approval')
    with pytest.raises(WitnessHold, match='pin changed'):
        candidate.finalize()
    assert json.loads(candidate.receipt.read_bytes())['state'] == 'pending'


def test_identical_pending_bytes_at_a_replaced_inode_do_not_authorize_close(evidence):
    checkpoint, _, _, _ = evidence
    candidate = checkpoint('held:controller')
    candidate('held', 'INSTALLED')
    payload = candidate.receipt.read_bytes()
    candidate.receipt.rename(candidate.receipt.with_suffix('.moved'))
    candidate.receipt.write_bytes(payload)
    candidate.receipt.chmod(0o600)
    with pytest.raises(WitnessHold, match='record changed'):
        candidate.finalize()


@pytest.mark.parametrize("new_content", [None, b"different approved contents"])
def test_pin_replacement_during_promotion_sync_refuses(evidence, monkeypatch, new_content):
    checkpoint, _, _, _ = evidence
    enrollment = checkpoint("held:controller")
    enrollment("held", "INSTALLED")
    original_sync = continuity.os.fsync
    replaced = False

    def sync_then_replace(descriptor):
        nonlocal replaced
        original_sync(descriptor)
        if replaced:
            return
        replaced = True
        prior = enrollment.protected_pin.read_bytes()
        replacement = enrollment.protected_pin.with_suffix(".replacement")
        replacement.write_bytes(prior if new_content is None else new_content)
        replacement.chmod(0o600)
        replacement.replace(enrollment.protected_pin)

    monkeypatch.setattr(continuity.os, "fsync", sync_then_replace)
    with pytest.raises(WitnessHold, match="changed before promotion"):
        enrollment.finalize()
    assert json.loads(enrollment.receipt.read_bytes())["state"] == "pending"


def test_short_check_refuses_pin_on_new_inode_even_if_approved_bytes_match(evidence):
    checkpoint, _, _, _ = evidence
    enrollment = checkpoint("held:controller")
    enrollment("held", "INSTALLED")
    enrollment.finalize()
    replacement = enrollment.protected_pin.with_suffix(".replacement")
    replacement.write_bytes(enrollment.protected_pin.read_bytes())
    replacement.chmod(0o600)
    replacement.replace(enrollment.protected_pin)
    with pytest.raises(WitnessHold, match="different hold"):
        checkpoint("held:entry")("held", "INSTALLED")
