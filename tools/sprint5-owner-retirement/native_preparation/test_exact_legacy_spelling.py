import hashlib
import json
import sqlite3

import pytest

import protected_state as witness


@pytest.fixture
def ledgers(monkeypatch):
    jobs, peer = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
    for db in (jobs, peer):
        db.execute(
            "CREATE TABLE scrape_outcome_delivery_receipts "
            "(consumer,outcome_id,record_sha256,receipt,receipt_sha256)"
        )
    jobs.executescript("""
      CREATE TABLE scrape_outcomes (outcome_id,company_id,outcome,action,payload);
      CREATE TABLE scrape_outcome_deliveries (outcome_id, consumer, acknowledged_at);
    """)
    outcome, company = "fixture-outcome", "fixture-company"
    record = json.dumps({"fixture": "settled"})
    record_sha = hashlib.sha256(record.encode()).hexdigest()
    receipt = json.dumps({"disposition": "ACCEPTED", "outcome_id": outcome,
                          "consumer": "repair-coordinator", "record_sha256": record_sha,
                          "sink_status": "RECORDED_NO_REPAIR", "schema": "outcome-delivery-receipt-v1"})
    receipt_sha = hashlib.sha256(receipt.encode()).hexdigest()
    monkeypatch.setattr(witness, "FREEFORM_SETTLED", (
        outcome, company, "COMPLETE", "save_without_repair", record_sha, receipt_sha,
    ))
    jobs.execute("INSERT INTO scrape_outcomes VALUES (?,?,?,?,?)",
                 (outcome, company, "COMPLETE", "save_without_repair", record))
    jobs.execute("INSERT INTO scrape_outcome_deliveries VALUES (?,?,'verified')", (outcome,"repair-coordinator"))
    for db in (jobs, peer):
        db.execute("INSERT INTO scrape_outcome_delivery_receipts VALUES (?,?,?,?,?)",
                   ("repair-coordinator",outcome,record_sha,receipt,receipt_sha))
    try:
        yield jobs, peer
    finally:
        jobs.close()
        peer.close()


def test_verifies_exact_pair_without_creating_legacy_ack(ledgers):
    before = [tuple(db.iterdump()) for db in ledgers]
    witness.verify_legacy_restart_scope(*ledgers)
    assert [tuple(db.iterdump()) for db in ledgers] == before


@pytest.mark.parametrize(("where", "statement"), [
    (0, "UPDATE scrape_outcomes SET payload=payload || ' '"),
    (0, "UPDATE scrape_outcomes SET company_id='different'"),
    (0, "UPDATE scrape_outcomes SET outcome='PARTIAL'"),
    (0, "UPDATE scrape_outcomes SET action='repair'"),
    (0, "UPDATE scrape_outcome_delivery_receipts SET receipt_sha256='other'"),
    (0, "INSERT INTO scrape_outcomes VALUES ('other','unowned','COMPLETE','save_without_repair','{}')"),
    (0, "DELETE FROM scrape_outcome_deliveries"),
    (1, "DELETE FROM scrape_outcome_delivery_receipts"),
    (1, "UPDATE scrape_outcome_delivery_receipts SET receipt='{}'"),
])
def test_changed_or_outstanding_historical_work_holds(ledgers, where, statement):
    ledgers[where].execute(statement)
    with pytest.raises(witness.WitnessHold):
        witness.verify_legacy_restart_scope(*ledgers)
