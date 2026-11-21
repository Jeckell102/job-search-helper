"""Entrypoint stored as __main__.py in the exact host-check executable."""
import json
import os
from pathlib import Path
import sys

from host_checkpoint import attest, authenticated_maintenance
from launcher_witness import probe_launchers
from hashlib import sha256
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
    }.get(reason, 'UNCLASSIFIED')
    return f'Site checkpoint held. Protected release evidence could not be verified. [{category}]'


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
    continuity = ProtectedContinuity(policy=policy, protected_pin=protected_pin, pin_digest=pin_digest,
                                     executable_digest=executable_digest, request=request,
                                     owner=exclusion_owner, full_check=protected)
    def verify_launcher(stage, target):
        probe_launchers(policy.project, launchers, stage, target)

    result = attest(request, policy, continuity, verify_launcher=verify_launcher)
    continuity.finalize()
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except WitnessHold as error:
        sys.exit(protected_refusal(error))
    except Exception:
        sys.exit("Site checkpoint held. Approved policy or host evidence could not be verified.")
