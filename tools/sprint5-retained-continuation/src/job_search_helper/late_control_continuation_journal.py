"""Freeze an approved late-control delta and preserve the original Inbox rows.

This is the admission boundary. The generic exact publisher still holds the
delta. A remote read is evidence supplied to, and signed by, the operator;
the journal has no remote client and cannot turn a cursor into that evidence.
"""
from __future__ import annotations

import hashlib
import json
from typing import Mapping

from .exact_control_before_prefix_recovery import preview_control_before_prefix_source_transition
from .exact_cycle_planner import _digest
from .exact_local_plan import _canonical, _validate_plan
from .late_control_continuation_authorization import (
    PREVIEW_PARENT,
    required_late_control_continuation_claims,
    verify_late_control_continuation_authorization,
)
from .late_control_pending_plan import build_late_control_pending_plan
from .selected_recovery_authorization import _require_digest


_JOURNAL = "late_control_continuations"
_COMPETING_JOURNALS = (
    "exact_sync_chunks",
    "exact_plan_local_state",
    "exact_selected_legacy_recoveries",
    "exact_selected_legacy_recovery_archive",
    "exact_control_before_prefix_recoveries",
    "exact_legacy_plan_migrations",
    "exact_legacy_plan_migration_archive",
    "exact_legacy_delivery_evidence",
    "exact_legacy_delivery_evidence_archive",
    "exact_remote_plans",
)


def _read_original(connection, identity):
    plan = connection.execute(
        "SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?", identity
    ).fetchone()
    inventory = connection.execute(
        "SELECT payload,blocked FROM inventories WHERE cycle=? AND company=?", identity
    ).fetchone()
    destination = connection.execute("SELECT id FROM destination").fetchall()
    if plan is None or inventory is None or inventory[1] != 0 or len(destination) != 1:
        raise ValueError("late_control_continuation_original_unavailable")
    for table in _COMPETING_JOURNALS:
        if connection.execute(
            f"SELECT 1 FROM {table} WHERE cycle=? AND company=? LIMIT 1", identity
        ).fetchone():
            raise ValueError(f"late_control_continuation_competing_journal:{table}")
    if connection.execute(
        "SELECT 1 FROM publication_receipts WHERE json_extract(binding,'$.company_id')=? "
        "AND (json_extract(binding,'$.cycle_id')=? OR json_extract(binding,'$.request_id')=?) LIMIT 1",
        (identity[1], identity[0], identity[0]),
    ).fetchone():
        raise ValueError("late_control_continuation_competing_receipt")
    return plan[0], plan[1], inventory[0], destination[0][0]


def _remote_evidence(artifact, *, identity, destination, kind, indices):
    if (not isinstance(artifact, Mapping)
            or set(artifact) != {"version", "cycle_id", "company_id", "destination_id",
                                 "original_indices", "readback_digest"}
            or artifact["version"] != kind
            or (artifact["cycle_id"], artifact["company_id"]) != identity
            or artifact["destination_id"] != destination
            or artifact["original_indices"] != indices
            or not isinstance(indices, list) or not indices
            or any(type(index) is not int for index in artifact["original_indices"])):
        raise ValueError("late_control_continuation_remote_evidence_scope_mismatch")
    _require_digest(artifact["readback_digest"], "readback_digest")
    return _digest(dict(artifact))


def _prepare(connection, repository, *, cycle_id, company_id, controls, disposition,
             remote_prefix, pending_baseline):
    if not isinstance(disposition, Mapping):
        raise ValueError("late_control_continuation_disposition_missing")
    identity = cycle_id, company_id
    original_raw, cursor, inventory_raw, destination = _read_original(connection, identity)
    if not destination or destination != repository.spreadsheet_id:
        raise ValueError("late_control_continuation_destination_mismatch")
    remote_prefix_digest = _remote_evidence(
        remote_prefix, identity=identity, destination=destination,
        kind="late-control-verified-prefix-observation-v1",
        indices=disposition.get("observed_prefix_indices"),
    )
    pending_baseline_digest = _remote_evidence(
        pending_baseline, identity=identity, destination=destination,
        kind="late-control-pending-write-baseline-v1",
        indices=disposition.get("pending_original_indices"),
    )
    if (remote_prefix["readback_digest"] == pending_baseline["readback_digest"]
            or remote_prefix_digest != disposition.get("remote_prefix_observation_digest")
            or pending_baseline_digest != disposition.get("pending_write_baseline_digest")):
        raise ValueError("late_control_continuation_remote_evidence_digest_mismatch")
    legacy, payload = json.loads(original_raw), json.loads(inventory_raw)
    inputs = dict(cycle_id=cycle_id, company_id=company_id, payload=payload,
                  legacy_plan=legacy, cursor=cursor, controls=controls)
    preview = preview_control_before_prefix_source_transition(repository, **inputs)
    plan, _ = build_late_control_pending_plan(
        repository, **inputs, accepted_preview=preview, authorization=disposition,
    )
    _validate_plan(plan, *identity)
    parent = preview["plan"]["binding"]
    metadata = plan["late_control_pending_plan"]
    binding = {
        "cycle_id": cycle_id, "company_id": company_id, "destination_id": destination,
        "original_legacy_plan_digest": _digest(legacy), "inventory_payload_digest": _digest(payload),
        "original_legacy_plan_raw_sha256": hashlib.sha256(original_raw.encode("utf-8")).hexdigest(),
        "original_inventory_payload_raw_sha256": hashlib.sha256(inventory_raw.encode("utf-8")).hexdigest(),
        "original_verified_prefix_cursor": cursor,
        "original_prefix_operation_digest": _digest(legacy["operations"][:cursor]),
        "parent_kind": PREVIEW_PARENT, "parent_hold_digest": _digest(parent),
        "parent_authorization_digest": None,
        "delta_plan_digest": plan["plan_digest"],
        "successor_plan_digest": parent["successor_operations_digest"],
        "local_operations_digest": plan["local_operations_digest"],
        "remote_projection_digest": plan["remote_projection_digest"],
        "remote_prefix_observation_digest": remote_prefix_digest,
        "pending_write_baseline_digest": pending_baseline_digest,
        "local_scope_digest": metadata["local_scope_digest"],
        "remote_scope_digest": metadata["remote_scope_digest"],
    }
    return binding, _canonical({
        "plan": plan, "parent": parent, "disposition": disposition,
        "remote_prefix": remote_prefix, "pending_baseline": pending_baseline,
        "original_plan": original_raw, "original_inventory": inventory_raw,
        "original_cursor": cursor,
    })


def late_control_continuation_claims(inbox, repository, *, issued_at, expires_at, **scope):
    """Prepare the exact claims for signing. No schema or row is written."""
    with inbox.lock:
        binding, _ = _prepare(inbox.connection, repository, **scope)
    return required_late_control_continuation_claims(
        binding=binding, issued_at=issued_at, expires_at=expires_at,
    )


def freeze_late_control_continuation(inbox, repository, *, envelope, verifier, now=None, **scope):
    """Rebuild and authenticate the exact current delta before archiving it."""
    supplied = envelope.get("payload") if isinstance(envelope, Mapping) else None
    if not isinstance(supplied, Mapping):
        raise ValueError("late_control_continuation_authorization_missing")
    connection = inbox.connection
    with inbox.lock, connection:
        connection.execute("BEGIN IMMEDIATE")
        binding, archive = _prepare(connection, repository, **scope)
        claims = required_late_control_continuation_claims(
            binding=binding, issued_at=supplied.get("issued_at"), expires_at=supplied.get("expires_at"),
        )
        verified = verify_late_control_continuation_authorization(
            envelope, claims, verifier, now=now,
        )
        connection.execute(f"""CREATE TABLE IF NOT EXISTS {_JOURNAL} (
            cycle TEXT NOT NULL, company TEXT NOT NULL,
            archive TEXT NOT NULL, authorization TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state='FROZEN'),
            PRIMARY KEY(cycle,company)
        )""")
        identity = binding["cycle_id"], binding["company_id"]
        approval = _canonical({"claims": claims, "envelope": envelope, "verification": verified})
        stored = connection.execute(
            f"SELECT archive,authorization,state FROM {_JOURNAL} WHERE cycle=? AND company=?",
            identity,
        ).fetchone()
        if stored is None:
            connection.execute(
                f"INSERT INTO {_JOURNAL} VALUES (?,?,?,?,'FROZEN')", (*identity, archive, approval),
            )
        elif stored != (archive, approval, "FROZEN"):
            raise ValueError("late_control_continuation_frozen_record_changed")
    return {
        "cycle_id": identity[0], "company_id": identity[1], "state": "FROZEN",
        "plan_digest": binding["delta_plan_digest"],
        "authorization_digest": verified["authorization_digest"],
        "recovered": stored is not None,
    }
