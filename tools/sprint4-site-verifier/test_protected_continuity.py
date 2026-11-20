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
