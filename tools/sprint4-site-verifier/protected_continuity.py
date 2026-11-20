"""Bind intermediate protected-file checks to a fully verified held generation."""
from hashlib import sha256
import json
import os
from pathlib import Path
from secrets import token_hex
import stat

from host_checkpoint import read_regular
from physical_protected_witness import physical_snapshot
from protected_state import WitnessHold


SCHEMA = "sprint-4-protected-continuity-v1"
RECEIPT_NAME = "protected-continuity.json"


def need(condition, diagnostic):
    if not condition:
        raise WitnessHold(diagnostic)


def private_snapshot(path):
    data, info = read_regular(path)
    need(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600,
         "Protected proof record is not private")
    return data, (info.st_dev, info.st_ino, info.st_ctime_ns, info.st_mtime_ns, info.st_size)


def replace_receipt(path, content, *, expected=None, approved_pin=None):
    parent = path.parent
    need(parent.resolve(strict=True) == parent, "Continuity record parent is not canonical")
    directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temp = ".continuity-" + token_hex(16)
    created = False
    try:
        info = os.fstat(directory)
        need(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
             "Continuity directory is not private")
        if os.path.lexists(path):
            private_snapshot(path)
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(content, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if expected is not None:
            need(private_snapshot(path) == expected, "Pending continuity record was replaced")
        if approved_pin is not None:
            pin_path, pin_snapshot = approved_pin
            need(private_snapshot(pin_path) == pin_snapshot,
                 "Approved protected-state pin changed before promotion")
        os.replace(temp, path.name, src_dir_fd=directory, dst_dir_fd=directory)
        created = False
        os.fsync(directory)
    finally:
        try:
            if created:
                os.unlink(temp, dir_fd=directory)
        finally:
            os.close(directory)


class ProtectedContinuity:
    """Create a usable short-check receipt only after complete site attestation."""

    def __init__(self, *, policy, protected_pin, pin_digest, executable_digest, request, owner, full_check):
        self.policy = policy
        self.protected_pin = protected_pin
        self.pin_digest = pin_digest
        self.request = request
        self.owner = owner
        self.full_check = full_check
        self.receipt = policy.maintenance_bundle / RECEIPT_NAME
        self.base = {
            "schema": SCHEMA, "project": str(policy.project), "maintenance_id": policy.maintenance_id,
            "target": request["target"], "source_manifest_sha256": policy.manifest_sha256,
            "protected_pin_sha256": pin_digest, "verifier_sha256": executable_digest,
        }
        self.pending = None

    def binding(self, stage, pin):
        current = self.owner(stage)
        need(current is not None, "Protected writer exclusion is unverified")
        boot, pid, started = current
        return {**self.base, "boot": boot, "controller_pid": pid, "controller_started": started,
                "protected_pin_identity": list(pin[1])}

    def __call__(self, stage, target):
        need(target == self.request["target"], "Protected proof release direction changed")
        pin = private_snapshot(self.protected_pin)
        need(sha256(pin[0]).hexdigest() == self.pin_digest,
             "Approved protected-state pin changed")
        binding = self.binding(stage, pin)
        checkpoint = self.request["checkpoint"]
        enroll = checkpoint == "held:controller"
        short = stage == "held" and not enroll
        receipt = None
        if enroll:
            # Any failed re-enrollment leaves no usable previous receipt.
            replace_receipt(self.receipt, {**binding, "state": "pending"})
            receipt = private_snapshot(self.receipt)
        physical = physical_snapshot(self.policy.project)
        if short:
            try:
                receipt = private_snapshot(self.receipt)
                record = json.loads(receipt[0])
            except (OSError, ValueError, TypeError):
                raise WitnessHold("A fresh held logical checkpoint is required") from None
            need(record == {**binding, "state": "verified", "physical": physical},
                 "Protected continuity evidence changed or belongs to a different hold")
        else:
            need(self.full_check(stage, target) is True, "Full protected-state verification refused")
        self.pending = (stage, binding, physical, enroll, pin, receipt)
        return True

    def finalize(self):
        need(self.pending is not None, "Protected checkpoint did not run")
        stage, binding, physical, enroll, pin, receipt = self.pending
        need(self.binding(stage, pin) == binding and physical_snapshot(self.policy.project) == physical,
             "Protected files or writer ownership changed during the checkpoint")
        need(private_snapshot(self.protected_pin) == pin, "Approved protected-state pin changed during the checkpoint")
        if receipt is not None:
            need(private_snapshot(self.receipt) == receipt, "Continuity record changed during the checkpoint")
        if enroll:
            replace_receipt(self.receipt, {**binding, "state": "verified", "physical": physical},
                            expected=receipt, approved_pin=(self.protected_pin, pin))
            need(private_snapshot(self.protected_pin) == pin,
                 "Approved protected-state pin changed during promotion")
