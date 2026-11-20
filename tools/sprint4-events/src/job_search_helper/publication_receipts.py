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
    # Retry-originated receipts additionally bind the full reviewed release,
    # rather than trusting the release ID as a shorthand for its manifests.
    if "release_binding_sha256" in binding:
        value = binding["release_binding_sha256"]
        if not isinstance(value, str) or len(value) != 64 or any(
                character not in "0123456789abcdef" for character in value):
            raise ValueError("Receipt release_binding_sha256 must be lowercase SHA-256")
        values["release_binding_sha256"] = value
    return hashlib.sha256(_canonical(values).encode("utf-8")).hexdigest()


def _records(records):
    if not isinstance(records, Mapping) or not records:
        raise ValueError("Receipt requires one or more exact record identities")
    result = {str(key).strip(): str(value).strip() for key, value in records.items()}
    if not all(result) or not all(result.values()):
        raise ValueError("Record identities and fingerprints must be non-empty")
    return dict(sorted(result.items()))


def record_fingerprints(operations, rows_by_tab=None, *, include_guard_only=False):
    """Fingerprint the final guarded values for each frozen remote record.

    With no ``rows_by_tab`` this returns the fingerprint of the frozen plan.
    With rows supplied it projects only the exact identities and fields owned by
    that plan.  Thus an unrelated edit cannot manufacture a receipt, while a
    manual field that the plan deliberately does not own is left untouched.
    """
    grouped = {}
    for operation in operations:
        tab = str(operation.get("tab", "")).strip()
        identity = operation.get("identity")
        if not tab or not isinstance(identity, Mapping) or not identity:
            raise ValueError("Receipt records require exact tab and identity")
        identity = {str(key): value for key, value in sorted(identity.items())}
        fields = {}
        for values in (operation.get("on_insert", {}), operation.get("values", {})):
            if not isinstance(values, Mapping):
                raise ValueError("Receipt operation values must be mappings")
            fields.update({str(key): value for key, value in values.items()})
        notes_source = operation.get("append_notes", {})
        expected = operation.get("expected", {})
        if not isinstance(notes_source, Mapping) or not isinstance(expected, Mapping):
            raise ValueError("Receipt operation guards and notes must be mappings")
        # A guarded legacy-key migration can legitimately alter an identity
        # column.  The post-commit readback must locate its final identity,
        # while the repository itself still validates the original one.
        final_identity = dict(identity)
        final_identity.update({key: value for key, value in fields.items() if key in final_identity})
        if include_guard_only:
            mutated = set(fields) | {str(key) for key in notes_source}
            fields.update({str(key): value for key, value in expected.items()
                           if str(key) not in mutated})
        label = tab + ":" + _canonical(final_identity)
        target = grouped.setdefault(label, {"tab": tab, "identity": final_identity,
                                            "fields": {}, "notes": {}})
        target["fields"].update(fields)
        for field, note in notes_source.items():
            notes = target["notes"].setdefault(str(field), [])
            if note not in notes:
                notes.append(note)

    records = {}
    for label, target in sorted(grouped.items()):
        projected = {"tab": target["tab"], "identity": target["identity"],
                     "fields": target["fields"], "notes": target["notes"]}
        if rows_by_tab is not None:
            matches = [row for row in rows_by_tab.get(target["tab"], [])
                       if all(str(row.get(key, "")) == str(value) for key, value in target["identity"].items())]
            if len(matches) != 1:
                projected["missing_or_ambiguous"] = len(matches)
            else:
                row = matches[0]
                projected["fields"] = {key: row.get(key, "") for key in target["fields"]}
                projected["notes"] = {
                    key: [note if note in str(row.get(key, "")) else "__missing_note__" for note in notes]
                    for key, notes in target["notes"].items()
                }
        records[label] = hashlib.sha256(_canonical(projected).encode("utf-8")).hexdigest()
    return _records(records)


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
    if _is_company_event_request(binding):
        _require_ordinary_event_plan(connection, binding, records)
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


def _is_company_event_request(binding):
    return str(binding.get('request_id', '')).strip().startswith('company-event:')


def _require_ordinary_event_plan(connection, binding, records):
    from .exact_cycle_planner import _exact_plan_digest

    if (binding.get('authority') != 'ordinary-company-event-exact-v2'
            or not isinstance(binding.get('cycle_id'), str)
            or connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sync_plans'").fetchone() is None):
        raise ValueError('Ordinary event receipts require their exact publication plan.')
    row = connection.execute(
        'SELECT payload FROM sync_plans WHERE cycle=? AND company=?',
        (binding['cycle_id'], binding['company_id']),
    ).fetchone()
    plan = json.loads(row[0]) if row is not None else None
    if (not isinstance(plan, dict)
            or plan.get('exact_plan_version') != 2 or plan.get('plan_digest') != _exact_plan_digest(plan)
            or plan.get('ordinary_company_event') != binding or plan.get('remote_records') != records):
        raise ValueError('Ordinary event receipts require their exact publication plan.')


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
    if _is_company_event_request(binding):
        raise ValueError('Exact remote receipts require trusted Sheets confirmation.')
    has_exact_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='exact_remote_plans'"
    ).fetchone()
    if has_exact_table and connection.execute(
            'SELECT 1 FROM exact_remote_plans WHERE receipt_id=?',
            (receipt_id,)).fetchone():
        raise ValueError('Exact remote receipts require trusted Sheets confirmation.')
    has_exact_local = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='exact_plan_local_state'").fetchone()
    if has_exact_local and connection.execute(
            'SELECT 1 FROM exact_plan_local_state WHERE cycle=? AND company=?',
            (binding.get('request_id'), binding.get('company_id'))).fetchone():
        raise ValueError('Exact remote receipts require trusted Sheets confirmation.')
    row = connection.execute(
        "SELECT records,state,binding FROM publication_receipts WHERE receipt_id=?", (receipt_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Cannot reconcile an unknown receipt")
    if json.loads(row[2]).get('authority') == 'ordinary-company-event-exact-v2':
        raise ValueError('Exact remote receipts require trusted Sheets confirmation.')
    if row[1] == SYNC_CONFIRMED:
        return True
    if row[1] != SYNC_PENDING:
        raise ValueError("Receipt must be SYNC_PENDING before reconciliation")
    if not str(acknowledgement_id).strip() or _records(observed_records) != json.loads(row[0]):
        return False
    connection.execute("UPDATE publication_receipts SET state=?, acknowledgement_id=?, updated_at=? WHERE receipt_id=?",
                       (SYNC_CONFIRMED, str(acknowledgement_id), timestamp, receipt_id))
    return True


def discard_preflight_rejected(connection, binding, expected_records, *, cursor):
    """Remove only a never-started receipt after a typed no-write rejection.

    The caller supplies the frozen plan cursor. Any prior acknowledged slice
    makes replacement unsafe, so a partially published repair stays pending
    for operator reconciliation instead of silently acquiring new records.
    """
    if cursor != 0:
        raise ValueError("Cannot replace a receipt after partial publication")
    receipt_id = _receipt_id(binding)
    if _is_company_event_request(binding):
        raise ValueError('Ordinary event receipts require their exact publication plan.')
    row = connection.execute(
        "SELECT records,state,binding FROM publication_receipts WHERE receipt_id=?", (receipt_id,)
    ).fetchone()
    if row is None:
        raise ValueError("Cannot discard an unknown publication receipt")
    if json.loads(row[2]).get('authority') == 'ordinary-company-event-exact-v2':
        raise ValueError('Ordinary event receipts require their exact publication plan.')
    if row[1] == SYNC_CONFIRMED:
        raise ValueError("Cannot discard a confirmed publication receipt")
    if _records(expected_records) != json.loads(row[0]):
        raise ValueError("Cannot discard a receipt for different frozen records")
    connection.execute("DELETE FROM publication_receipts WHERE receipt_id=?", (receipt_id,))
    return receipt_id


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
