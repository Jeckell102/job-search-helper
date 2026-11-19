"""Durable Milestone-1 local-storage and synchronization receipt contract.

This module intentionally does not dispatch scraping or write to Sheets.  The
company-only intake worker owns scheduling; the normal storage writer owns the
atomic transaction that calls these helpers.  Keeping the contract here makes
the required acknowledgement boundary explicit without introducing a second
queue or a parallel writer.

Receipt lifecycle:

``LOCAL_COMMITTED -> SYNC_PENDING -> SYNC_CONFIRMED``

`SYNC_CONFIRMED` requires a live readback for every exact record identity and
fingerprint.  A lost remote acknowledgement therefore remains
`SYNC_PENDING`; the frozen local payload can be reconciled or safely replayed
without fetching the company again or replacing intervening manual choices.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Mapping


LOCAL_COMMITTED = "LOCAL_COMMITTED"
SYNC_PENDING = "SYNC_PENDING"
SYNC_CONFIRMED = "SYNC_CONFIRMED"
_STATES = {LOCAL_COMMITTED, SYNC_PENDING, SYNC_CONFIRMED}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _receipt_id(binding):
    """Return a stable receipt key for one requested company/source/release."""
    required = ("request_id", "company_id", "source_revision", "release_id")
    values = {name: str(binding.get(name, "")).strip() for name in required}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError("Receipt binding requires " + ", ".join(missing))
    return hashlib.sha256(_canonical(values).encode("utf-8")).hexdigest()


def _records(records):
    if not isinstance(records, Mapping) or not records:
        raise ValueError("Receipt requires one or more exact record identities")
    result = {str(key).strip(): str(value).strip() for key, value in records.items()}
    if not all(result) or not all(result.values()):
        raise ValueError("Record identities and fingerprints must be non-empty")
    return dict(sorted(result.items()))


def initialize(connection: sqlite3.Connection):
    """Create the receipt table in the storage writer's existing database."""
    connection.execute("""CREATE TABLE IF NOT EXISTS publication_receipts (
        receipt_id TEXT PRIMARY KEY,
        binding TEXT NOT NULL,
        records TEXT NOT NULL,
        schedule TEXT NOT NULL,
        state TEXT NOT NULL,
        acknowledgement_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")


def local_committed(connection, binding, records, schedule, *, timestamp):
    """Persist an immutable local receipt before a remote write is attempted.

    `schedule` must make a queued request observable: it includes the safe
    boundary (`idle` or `after_cycle`), the blocking cycle when applicable,
    and the original enqueue timestamp.  The caller must use its existing
    transaction with the frozen inventory/plan; this helper never starts work.
    """
    receipt_id = _receipt_id(binding)
    records = _records(records)
    required_schedule = ("boundary", "enqueued_at")
    if not isinstance(schedule, Mapping) or any(not str(schedule.get(key, "")).strip()
                                                for key in required_schedule):
        raise ValueError("Schedule requires boundary and enqueued_at")
    if schedule["boundary"] not in {"idle", "after_cycle"}:
        raise ValueError("Schedule boundary must be idle or after_cycle")
    if schedule["boundary"] == "after_cycle" and not str(schedule.get("blocking_cycle_id", "")).strip():
        raise ValueError("Queued schedule requires blocking_cycle_id")
    payload = (_canonical(dict(binding)), _canonical(records), _canonical(dict(schedule)))
    row = connection.execute("SELECT binding,records,schedule,state FROM publication_receipts WHERE receipt_id=?",
                             (receipt_id,)).fetchone()
    if row:
        if row[:3] != payload:
            raise ValueError("Receipt binding already exists with different records or scheduling")
        return receipt_id
    connection.execute("INSERT INTO publication_receipts VALUES (?,?,?,?,?,?,?,?)",
                       (receipt_id, *payload, LOCAL_COMMITTED, None, timestamp, timestamp))
    return receipt_id


def mark_sync_pending(connection, binding, *, timestamp):
    """Record that the frozen local plan is ready for the single normal writer."""
    receipt_id = _receipt_id(binding)
    updated = connection.execute(
        "UPDATE publication_receipts SET state=?, updated_at=? WHERE receipt_id=? AND state=?",
        (SYNC_PENDING, timestamp, receipt_id, LOCAL_COMMITTED)).rowcount
    if not updated:
        row = connection.execute("SELECT state FROM publication_receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
        if row is None:
            raise ValueError("Cannot mark sync pending without LOCAL_COMMITTED receipt")
        if row[0] != SYNC_PENDING:
            raise ValueError("Cannot move confirmed receipt back to pending")
    return receipt_id


def reconcile_sync(connection, binding, observed_records, acknowledgement_id, *, timestamp):
    """Confirm only an exact live readback; otherwise retain the pending plan.

    A false result is deliberately non-destructive: callers keep the request,
    frozen records and manual-decision guards for later reconciliation.
    """
    receipt_id = _receipt_id(binding)
    row = connection.execute("SELECT records,state FROM publication_receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
    if row is None:
        raise ValueError("Cannot reconcile an unknown receipt")
    if row[1] == SYNC_CONFIRMED:
        return True
    if row[1] != SYNC_PENDING:
        raise ValueError("Receipt must be SYNC_PENDING before reconciliation")
    if not str(acknowledgement_id).strip() or _records(observed_records) != json.loads(row[0]):
        return False
    connection.execute("UPDATE publication_receipts SET state=?, acknowledgement_id=?, updated_at=? WHERE receipt_id=?",
                       (SYNC_CONFIRMED, str(acknowledgement_id), timestamp, receipt_id))
    return True


def receipt(connection, binding):
    """Return the visible receipt, including queue/recovery facts, or ``None``."""
    receipt_id = _receipt_id(binding)
    row = connection.execute("SELECT binding,records,schedule,state,acknowledgement_id,created_at,updated_at "
                             "FROM publication_receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
    if row is None:
        return None
    return {"receipt_id": receipt_id, "binding": json.loads(row[0]), "records": json.loads(row[1]),
            "schedule": json.loads(row[2]), "state": row[3], "acknowledgement_id": row[4],
            "created_at": row[5], "updated_at": row[6]}
