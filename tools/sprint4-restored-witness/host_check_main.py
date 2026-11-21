"""Entrypoint stored as __main__.py in the exact host-check executable."""
import json
import os
from pathlib import Path
import sys
import time

from host_checkpoint import attest, authenticated_maintenance
from launcher_witness import probe_launchers
from hashlib import sha256
from physical_protected_witness import physical_snapshot
from protected_continuity import ProtectedContinuity
from protected_state import WitnessHold, bind_host_witness, verify_release_lease
from site_policy import load_policy


def protected_refusal(error):
    reason = error.args[0] if len(error.args) == 1 and type(error.args[0]) is str else None
    category = {
        'database changed during read': 'SQLITE_CONTINUITY',
        'nonempty WAL needs read-only view': 'SQLITE_WAL',
        'rollback journal needs reconciliation': 'SQLITE_ROLLBACK_JOURNAL',
        'protected state differs from private pin': 'PROTECTED_BASELINE',
        'Protected files or writer ownership changed during the checkpoint': 'PROTECTED_CONTINUITY',
        'release lease not owned by controller': 'WRITER_LEASE',
        'automatic release closure unverified': 'WRITER_LEASE',
        'Restored service did not reach a stable protected checkpoint': 'RESTORED_STABILITY_TIMEOUT',
    }.get(reason, 'UNCLASSIFIED')
    return f'Site checkpoint held. Protected release evidence could not be verified. [{category}]'


def wait_for_restored_stability(project, verify_owner, verify_once):
    """Wait for startup activity to settle, then require a fresh complete attestation."""
    deadline = time.monotonic() + 70
    interval = 1.5
    retryable = {
        'database changed during read',
        'Protected physical evidence unavailable',
        'Protected directory changed during observation',
        'Protected file is substituted or changed',
        'Protected files or writer ownership changed during the checkpoint',
        'protected evidence unavailable or malformed',
    }
    original_owner = verify_owner()
    if original_owner is None:
        raise WitnessHold('Protected writer exclusion is unverified')

    def require_owner():
        if verify_owner() != original_owner:
            raise WitnessHold('Protected writer exclusion is unverified')

    while time.monotonic() + interval < deadline:
        require_owner()
        try:
            before = physical_snapshot(project)
            time.sleep(interval)
            require_owner()
            if physical_snapshot(project) != before:
                continue
            result = verify_once()
            require_owner()
            if physical_snapshot(project) == before:
                require_owner()
                if time.monotonic() < deadline:
                    return result
        except WitnessHold as error:
            if len(error.args) != 1 or type(error.args[0]) is not str or error.args[0] not in retryable:
                raise
            if time.monotonic() + interval < deadline:
                time.sleep(interval)
    raise WitnessHold('Restored service did not reach a stable protected checkpoint')


def main():
    policy, protected_pin, pin_digest, launchers = load_policy(sys.argv[0])
    request_data = sys.stdin.buffer.read(16385)
    if not request_data or len(request_data) > 16384:
        raise ValueError("Site request size is invalid")
    request = json.loads(request_data)

    def exclusion_owner(stage):
        owners = authenticated_maintenance(policy, request, stage, Path("/proc"), os.getppid())
        [controller] = [pid for pid, (_, role) in owners.items() if role == "controller.py"]
        if verify_release_lease(policy.project, controller) is not True:
            return None
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return boot, controller, owners[controller][0]

    protected = bind_host_witness(policy.project, protected_pin, pin_digest,
                                  maintenance_id=policy.maintenance_id,
                                  verify_release_hold=lambda stage, target: exclusion_owner(stage) is not None)
    executable = Path(sys.argv[0])
    with executable.open("rb") as source:
        executable_digest = sha256(source.read()).hexdigest()
    def verify_launcher(stage, target):
        probe_launchers(policy.project, launchers, stage, target)

    def verify_once():
        continuity = ProtectedContinuity(policy=policy, protected_pin=protected_pin, pin_digest=pin_digest,
                                         executable_digest=executable_digest, request=request,
                                         owner=exclusion_owner, full_check=protected)
        result = attest(request, policy, continuity, verify_launcher=verify_launcher)
        continuity.finalize()
        return result

    if request.get('checkpoint') == 'restored':
        result = wait_for_restored_stability(policy.project, lambda: exclusion_owner('restored'), verify_once)
    else:
        result = verify_once()
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except WitnessHold as error:
        sys.exit(protected_refusal(error))
    except Exception:
        sys.exit("Site checkpoint held. Approved policy or host evidence could not be verified.")
