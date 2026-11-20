from contextlib import contextmanager
from hashlib import sha256

import pytest

from host_exchange import Hold, encode
from pilot_restoration import SCHEMA, exchange_identity, restore_after_pilot
from test_host_exchange import fixture, states


class JointTerminal:
    release = {"source": "INSTALLED", "maintenance_id": "release-fixture"}

    def __init__(self):
        self.held = False

    @contextmanager
    def restoration_terminal(self):
        self.held = True
        try:
            yield self.release
        finally:
            self.held = False


@pytest.fixture
def restoration(fixture):
    exchange, _ = fixture
    exchange.prepare()
    witness = exchange.close()
    joint = JointTerminal()
    plan = {"schema": SCHEMA, "release": joint.release, "exchange": exchange_identity(witness),
            "pilot": {"outcome_id": "test-retained-pilot", "matching_receipt_sha256": "a" * 64}}
    return joint, exchange, plan


def run(joint, exchange, plan, read_pilot):
    approval = encode(plan)
    return restore_after_pilot(joint, exchange, approval, approved_sha256=sha256(approval).hexdigest(),
                               read_settled_pilot=read_pilot)


def test_restore_matches_settled_pilot_under_release_leases_and_replays(restoration):
    joint, exchange, plan = restoration

    def read_settlement():
        assert joint.held
        return plan["pilot"]

    def guarded_swap(*args):
        assert joint.held
        real_swap(*args)

    import host_exchange
    real_swap = host_exchange._exchange
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(host_exchange, "_exchange", guarded_swap)
        result = run(joint, exchange, plan, read_settlement)
    assert not joint.held
    assert states(exchange) == [True, True, True]
    assert run(joint, exchange, plan, read_settlement) == result


@pytest.mark.parametrize("wrong", ["release", "exchange", "pilot"])
def test_mismatched_terminal_evidence_leaves_all_routes_closed(restoration, wrong):
    joint, exchange, plan = restoration
    approved = {**plan, wrong: {**plan[wrong], "different": True}}
    with pytest.raises(Hold, match="differs from|proof refused"):
        run(joint, exchange, approved, lambda: plan["pilot"])
    assert not joint.held
    assert states(exchange) == [False, False, False]
    assert exchange.witness().phase == "closed"


def test_foreign_approval_pin_prevents_any_release_or_pilot_check(restoration):
    joint, exchange, plan = restoration
    with pytest.raises(Hold, match="trusted pin"):
        restore_after_pilot(joint, exchange, encode(plan), approved_sha256="f" * 64,
                            read_settled_pilot=lambda: pytest.fail("Out-of-scope pilot read"))
    assert not joint.held
    assert states(exchange) == [False, False, False]
