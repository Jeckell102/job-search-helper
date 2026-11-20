"""Reopen alternate checkouts after one approved, fully settled pilot."""
from hashlib import sha256
import json

from host_exchange import Hold, encode, require


SCHEMA = "sprint-4-pilot-restoration-v1"


def exchange_identity(witness):
    return {
        "generation": witness.generation, "intent_sha256": witness.intent_sha256,
        "policy_sha256": witness.policy_sha256, "mount_namespace": witness.mount_namespace,
        "control": str(witness.control),
        "routes": [[str(pair.canonical), str(pair.parked)] for pair in witness.pairs],
    }


def restore_after_pilot(controller, exchange, approval, *, approved_sha256, read_settled_pilot):
    """Hold the joint release leases through the exchange and exact settlement check."""
    require(type(approval) is bytes and sha256(approval).hexdigest() == approved_sha256,
            "Pilot restoration approval differs from its trusted pin")
    try:
        plan = json.loads(approval)
    except (ValueError, UnicodeError) as exc:
        raise Hold("Pilot restoration approval is unreadable") from exc
    require(isinstance(plan, dict) and set(plan) == {"schema", "release", "exchange", "pilot"}
            and plan["schema"] == SCHEMA and approval == encode(plan)
            and all(isinstance(plan[key], dict) and plan[key] for key in ("release", "exchange", "pilot")),
            "Pilot restoration approval is incomplete or not canonical")

    with controller.restoration_terminal() as release:
        require(release == plan["release"] and release["source"] == "INSTALLED",
                "Pilot restoration release differs from the approved installed target")

        def verified(witness, evidence):
            return (witness.phase == "closed" and witness.terminal_proof_sha256 is None
                    and exchange_identity(witness) == plan["exchange"] and evidence == approval
                    and read_settled_pilot() == plan["pilot"])

        return exchange.restore(approval, verify_terminal=verified)
