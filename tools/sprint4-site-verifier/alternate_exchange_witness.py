"""Read the exact checkout closure through the approved exchange controller."""
from dataclasses import dataclass
import os
from pathlib import Path

from host_exchange import Hold, HostExchange


@dataclass(frozen=True)
class ExchangeFence:
    policy_file: Path
    policy_sha256: str
    generation: str
    intent_sha256: str
    launch_uid: int
    pairs: tuple[tuple[Path, Path], ...]

    @property
    def control(self):
        return self.policy_file.parent

    def active_roots(self):
        return {canonical for canonical, _ in self.pairs}

    def parked_roots(self):
        return {parked for _, parked in self.pairs}


def verify_exchange(fence):
    """Verify live evidence against the closure approved in the site policy."""
    if fence.launch_uid <= 0 or fence.launch_uid != os.geteuid():
        raise ValueError("Wrong alternate writer account")
    try:
        witness = HostExchange(fence.policy_file, fence.policy_sha256).witness("closed")
    except Hold as exc:
        raise ValueError(f"Approved exchange is unavailable: {exc}") from exc
    pairs = tuple((pair.canonical, pair.parked) for pair in witness.pairs)
    if (witness.phase != "closed" or witness.terminal_proof_sha256 is not None
            or witness.policy_sha256 != fence.policy_sha256 or witness.control != fence.control
            or witness.generation != fence.generation or witness.intent_sha256 != fence.intent_sha256
            or pairs != fence.pairs):
        raise ValueError("Alternate exchange is outside the approved closed generation")
