"""Independently verify one successful retained pilot in the receiver ledger."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat

from coordinator_store import (
    OUTCOME_DELIVERY_CONSUMER,
    Store,
    _canonical_json,
    _sha256_text,
    canonical_scrape_outcome,
)


def verify_receiver_delivery(database, record, *, sender_receipt_sha256):
    """Read the pinned receiver ledger without using Store's writable entry points."""
    database = Path(database)
    if database.name != "tasks.sqlite3" or not database.is_absolute() or database.resolve(strict=True) != database:
        raise ValueError("Pilot receipt requires the canonical receiver database")
    initial = database.stat()
    if not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1 or initial.st_uid != os.geteuid():
        raise ValueError("Pilot receiver database has unsafe ownership or type")

    canonical = canonical_scrape_outcome(record)
    if (canonical != record or canonical["outcome"] != "COMPLETE"
            or "retained_reservation_sha256" not in canonical["identity"]):
        raise ValueError("Pilot receipt requires an exact completed retained outcome")
    record_sha256 = _sha256_text(_canonical_json(canonical))
    outcome_id = canonical["outcome_id"]
    request_id = canonical["identity"]["request_id"]
    consumer = OUTCOME_DELIVERY_CONSUMER
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
        db.execute("PRAGMA query_only = ON")
        db.execute("BEGIN")
        receipts = db.execute(
            "SELECT record_sha256, receipt_id, receipt, receipt_sha256, sink_status"
            " FROM scrape_outcome_delivery_receipts WHERE consumer=? AND outcome_id=?",
            (consumer, outcome_id),
        ).fetchall()
        intake = db.execute(
            "SELECT company_id, source_revision, outcome, payload"
            " FROM scrape_outcome_intake WHERE outcome_id=?",
            (outcome_id,),
        ).fetchall()
        if len(receipts) != 1 or len(intake) != 1:
            raise ValueError("Pilot receiver is missing one exact intake and receipt")
        row = receipts[0]
        receipt = Store._validate_delivery_receipt(
            row, consumer=consumer, canonical=canonical, record_sha256=record_sha256,
        )
        Store._validate_delivery_intake(
            intake[0], canonical=canonical, legacy_text=json.dumps(canonical, sort_keys=True, separators=(",", ":")),
            record_sha256=record_sha256,
        )
        if receipt["sink_status"] != "RECORDED_NO_REPAIR" or row[3] != sender_receipt_sha256:
            raise ValueError("Pilot receiver disposition or receipt differs from the sender")
        repair = db.execute(
            "SELECT 1 FROM repair_intake WHERE outcome_id=?"
            " UNION ALL SELECT 1 FROM repair_intake_evidence WHERE outcome_id=?"
            " UNION ALL SELECT 1 FROM repair_retry_lineage"
            " WHERE outcome_id=? OR failed_request_id=? OR successor_request_id=? LIMIT 1",
            (outcome_id, outcome_id, outcome_id, request_id, request_id),
        ).fetchone()
        if repair is not None:
            raise ValueError("Pilot receiver has contradictory repair or retry evidence")
        if database.resolve(strict=True) != database or not os.path.samestat(initial, database.stat()):
            raise ValueError("Pilot receiver database changed during verification")

    return {
        "consumer": consumer, "outcome_id": outcome_id, "record_sha256": record_sha256,
        "receipt_sha256": row[3], "sink_receipt_id": receipt["sink_receipt_id"],
        "sink_status": receipt["sink_status"],
    }


def verify_pilot_delivery(application, database):
    """Pair the sender's verified observation with independent receiver evidence."""
    receiver = verify_receiver_delivery(
        database, application["record"], sender_receipt_sha256=application["sender_receipt_sha256"],
    )
    fields = ("consumer", "outcome_id", "record_sha256", "sink_receipt_id", "sink_status")
    if any(application[key] != receiver[key] for key in fields):
        raise ValueError("Pilot application and receiver name different terminal evidence")
    return {"application": application, "receiver": receiver}
