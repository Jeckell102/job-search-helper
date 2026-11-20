import pytest

from coordinator_store import OUTCOME_DELIVERY_CONSUMER, Store, _canonical_json, _sha256_text
from job_search_helper.outcomes import classify_outcome, _digest
from retained_pilot_receiver import verify_pilot_delivery, verify_receiver_delivery


@pytest.fixture
def evidence(tmp_path):
    receiver = Store(tmp_path)
    reservation = "a" * 64
    event = "CEV-" + "c" * 32
    record = classify_outcome({
        "request_id": f"company-event:{event}", "company_event_id": event, "company_id": "COMP-0001",
        "cycle_id": "CYC-R" + _digest({"reservation_digest": reservation})[:12].upper(),
        "retained_reservation_sha256": reservation, "source_revision": "b" * 64,
        "provider": "Greenhouse", "adapter_version": "normal-scraper-v1",
        "source_current": True, "company_status": "Active", "storage_status": "confirmed",
        "inventory_status": "complete", "capability": "unknown", "failure": {"category": "none"},
    })
    receipt = receiver.ingest_scrape_outcome_delivery_v1(OUTCOME_DELIVERY_CONSUMER, record)
    return receiver, record, receipt, _sha256_text(_canonical_json(receipt))


def test_receiver_confirms_exact_sender_receipt_without_durable_changes(evidence):
    receiver, record, expected, receipt_digest = evidence
    before = receiver.path.read_bytes(), receiver.path.stat()
    result = verify_receiver_delivery(receiver.path, record, sender_receipt_sha256=receipt_digest)
    assert result == {
        "consumer": OUTCOME_DELIVERY_CONSUMER, "outcome_id": record["outcome_id"],
        "record_sha256": expected["record_sha256"], "receipt_sha256": receipt_digest,
        "sink_receipt_id": expected["sink_receipt_id"], "sink_status": "RECORDED_NO_REPAIR",
    }
    after = receiver.path.stat()
    assert before[0] == receiver.path.read_bytes()
    assert (before[1].st_ino, before[1].st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


def test_foreign_sender_digest_is_held(evidence):
    receiver, record, _, _ = evidence
    with pytest.raises(ValueError, match="differs from the sender"):
        verify_receiver_delivery(receiver.path, record, sender_receipt_sha256="f" * 64)


def test_two_sided_proof_requires_same_receiver_identity_even_with_same_digest(evidence):
    receiver, record, expected, receipt_digest = evidence
    application = {**expected, "record": record, "sender_receipt_sha256": receipt_digest}
    proof = verify_pilot_delivery(application, receiver.path)
    assert proof["application"] == application
    assert proof["receiver"]["sink_receipt_id"] == expected["sink_receipt_id"]
    with pytest.raises(ValueError, match="different terminal evidence"):
        verify_pilot_delivery({**application, "sink_receipt_id": "ODR-other"}, receiver.path)


def test_missing_or_changed_authority_is_held(evidence):
    receiver, record, _, receipt_digest = evidence
    with receiver.connect() as db:
        db.execute("UPDATE scrape_outcome_intake SET payload = '{}'")
    with pytest.raises(ValueError, match="intake conflicts"):
        verify_receiver_delivery(receiver.path, record, sender_receipt_sha256=receipt_digest)
    with receiver.connect() as db:
        db.execute("DELETE FROM scrape_outcome_delivery_receipts")
    with pytest.raises(ValueError, match="missing one exact"):
        verify_receiver_delivery(receiver.path, record, sender_receipt_sha256=receipt_digest)


def test_matching_receipt_with_repair_evidence_is_held(evidence):
    receiver, record, _, receipt_digest = evidence
    with receiver.connect() as db:
        db.execute("INSERT INTO repair_intake VALUES (?,?,?,?,?,?,?,?)",
                   ("repair", record["outcome_id"], "COMP-0001", "b" * 64, "HELD", None, "{}", 0))
    with pytest.raises(ValueError, match="contradictory repair"):
        verify_receiver_delivery(receiver.path, record, sender_receipt_sha256=receipt_digest)
