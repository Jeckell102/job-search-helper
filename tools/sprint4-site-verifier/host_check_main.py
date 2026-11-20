"""Entrypoint stored as __main__.py in the exact host-check executable."""
import json
import os
from pathlib import Path
import sys

from host_checkpoint import attest, authenticated_maintenance
from launcher_witness import probe_launchers
from protected_state import WitnessHold, bind_host_witness, verify_release_lease
from site_policy import load_policy


def main():
    policy, protected_pin, pin_digest, launchers = load_policy(sys.argv[0])
    request_data = sys.stdin.buffer.read(16385)
    if not request_data or len(request_data) > 16384:
        raise ValueError("Site request size is invalid")
    request = json.loads(request_data)

    def verify_hold(stage, target):
        owners = authenticated_maintenance(policy, request, stage, Path("/proc"), os.getppid())
        [controller] = [pid for pid, (_, role) in owners.items() if role == "controller.py"]
        return verify_release_lease(policy.project, controller)

    protected = bind_host_witness(policy.project, protected_pin, pin_digest,
                                  maintenance_id=policy.maintenance_id,
                                  verify_release_hold=verify_hold)
    def verify_launcher(stage, target):
        probe_launchers(policy.project, launchers, stage, target)

    print(json.dumps(attest(request, policy, protected, verify_launcher=verify_launcher),
                     separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except WitnessHold:
        sys.exit("Site checkpoint held. Protected release evidence could not be verified.")
    except Exception:
        sys.exit("Site checkpoint held. Approved policy or host evidence could not be verified.")
