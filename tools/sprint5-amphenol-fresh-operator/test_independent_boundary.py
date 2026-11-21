import json
import pytest
from test_operator_repair_successor import OperatorRepairSuccessorTests, outcome, OUTCOME_DELIVERY_CONSUMER

@pytest.fixture
def case():
    value=OperatorRepairSuccessorTests();value.setUp()
    try:yield value
    finally:value.doCleanups()

def logical(store):
    with store.connect() as db:return tuple(db.iterdump())

def test_generic_intake_is_not_acknowledgment(case):
    fresh=outcome("operator-request:generic-only")
    case.store.ingest_scrape_outcome_record(fresh)
    before=logical(case.store)
    with pytest.raises(ValueError,match="acknowledged"):
        case.store.reserve_operator_repair_successor(**{**case.pins,"outcome_id":fresh["outcome_id"]})
    assert logical(case.store)==before

def test_receipt_guard_precedes_reservation_replay(case):
    case.store.reserve_operator_repair_successor(**case.pins)
    with case.store.connect() as db:
        db.execute("DELETE FROM scrape_outcome_delivery_receipts WHERE outcome_id=?",(case.successor["outcome_id"],))
    before=logical(case.store)
    with pytest.raises(ValueError,match="acknowledged"):
        case.store.reserve_operator_repair_successor(**case.pins)
    assert logical(case.store)==before

def test_different_failure_cannot_reserve(case):
    fresh=outcome("operator-request:other-failure",fingerprint="b"*64)
    case.store.ingest_scrape_outcome_delivery_v1(OUTCOME_DELIVERY_CONSUMER,fresh)
    before=logical(case.store)
    with pytest.raises(ValueError,match="does not match"):
        case.store.reserve_operator_repair_successor(**{**case.pins,"outcome_id":fresh["outcome_id"]})
    assert logical(case.store)==before

@pytest.mark.parametrize("key",["queue_enabled","campaign_enabled","autopilot_enabled","pilot_task"])
def test_active_control_refuses_reservation(case,key):
    with case.store.connect() as db:db.execute("UPDATE settings SET value=? WHERE key=?",('"WRAP-aaaaaaaaaa"' if key=="pilot_task" else 'true',key))
    before=logical(case.store)
    with pytest.raises(ValueError,match="scheduler"):
        case.store.reserve_operator_repair_successor(**case.pins)
    assert logical(case.store)==before

def test_reservation_preserves_predecessor_and_tasks(case):
    def protected():
        with case.store.connect() as db:return (db.execute("SELECT * FROM tasks").fetchall(),db.execute("SELECT * FROM repair_intake WHERE repair_key=?",(case.repair_key,)).fetchall(),db.execute("SELECT * FROM scrape_outcome_delivery_receipts").fetchall())
    before=protected();case.store.reserve_operator_repair_successor(**case.pins);case.store.reserve_operator_repair_successor(**case.pins)
    assert protected()==before

def test_running_unrelated_task_refuses_reservation(case):
    with case.store.connect() as db:db.execute("INSERT INTO tasks VALUES (?,?)",("WRAP-aaaaaaaaaa",json.dumps({"id":"WRAP-aaaaaaaaaa","status":"RUNNING"})))
    before=logical(case.store)
    with pytest.raises(ValueError):case.store.reserve_operator_repair_successor(**case.pins)
    assert logical(case.store)==before
