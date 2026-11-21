"""Bounded local preview/adoption for one reviewed retained legacy plan.

This module never opens Google, starts scraping, creates a publication receipt,
or advances cycle state.  The public runner supplies the normal writer lock for
the apply path; preview opens both SQLite databases read-only.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from .exact_legacy_migration import (
    build_legacy_v2_plan, capture_legacy_delivery_evidence,
    preview_legacy_migration_binding, validate_legacy_delivery_evidence,
)
from .inbox import InventoryInbox
from .sqlite_repository import SQLiteRepository, timestamp


def _required(value, label):
    value = str(value or "").strip()
    if not value or any(character.isspace() for character in value):
        raise ValueError(f"Exact legacy migration requires one {label}.")
    return value


def _read_retained(inventory_path, cycle_id, company_id, *, immutable=False):
    location = Path(inventory_path).resolve()
    if not location.is_file():
        raise ValueError("Saved-inventory database is missing.")
    uri = location.as_uri() + "?mode=ro"
    if immutable:
        uri += "&immutable=1"
    with sqlite3.connect(uri, uri=True) as connection:
        destination = connection.execute("SELECT id FROM destination").fetchall()
        inventory = connection.execute(
            "SELECT payload,blocked FROM inventories WHERE cycle=? AND company=?",
            (cycle_id, company_id)).fetchone()
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(exact_legacy_plan_migrations)")}
        migration = None
        if {"legacy_plan", "original_local_cursor", "state"} <= columns:
            migration = connection.execute(
                "SELECT legacy_plan,original_local_cursor,state "
                "FROM exact_legacy_plan_migrations WHERE cycle=? AND company=?",
                (cycle_id, company_id)).fetchone()
        stored = connection.execute(
            "SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?",
            (cycle_id, company_id)).fetchone()
    if len(destination) != 1 or not str(destination[0][0]).strip():
        raise ValueError("Saved-inventory destination is missing or ambiguous.")
    if inventory is None or bool(inventory[1]):
        raise ValueError("Exact retained inventory is missing or blocked.")
    if migration is not None and migration[0]:
        plan_text, cursor, state = migration
    elif stored is not None:
        plan_text, cursor, state = stored[0], stored[1], None
    else:
        raise ValueError("Exact retained legacy plan is missing.")
    try:
        payload = json.loads(inventory[0])
        legacy_plan = json.loads(plan_text)
    except (TypeError, ValueError) as error:
        raise ValueError("Exact retained legacy JSON is invalid.") from error
    return str(destination[0][0]).strip(), payload, legacy_plan, cursor, state


def _controls(local, company_id, requested_url):
    matches = local.matches("Companies", {"Company ID": company_id})
    if len(matches) != 1:
        raise ValueError("Exact migration Company is missing or ambiguous locally.")
    row = matches[0][1]
    return {
        "company_id": company_id,
        "requested_url": requested_url,
        "official_careers_url": str(row.get("Official Careers URL", "")),
        "company_status": str(row.get("Company Status", "")),
        "claimed_by": str(row.get("Claimed By", "")),
        "claim_token": str(row.get("Claim Token", "")),
    }


def preview_retained_legacy_migration(inventory_path, local_path, cycle_id,
                                      company_id):
    """Return sanitized approval pins; perform no database or remote write."""
    cycle_id = _required(cycle_id, "cycle ID")
    company_id = _required(company_id, "Company ID")
    destination, payload, legacy, cursor, state = _read_retained(
        inventory_path, cycle_id, company_id)
    local = SQLiteRepository(local_path, destination, readonly=True)
    try:
        controls = _controls(local, company_id, legacy.get("requested_url"))
        binding = preview_legacy_migration_binding(
            local, cycle_id=cycle_id, company_id=company_id, payload=payload,
            legacy_plan=legacy, cursor=cursor, controls=controls)
        plan, report = build_legacy_v2_plan(
            local, cycle_id=cycle_id, company_id=company_id, payload=payload,
            legacy_plan=legacy, cursor=cursor, controls=controls,
            binding=binding)
        delivery_evidence = capture_legacy_delivery_evidence(
            local, plan["remote_projection"])
    finally:
        local.close()
    return {
        "cycle_id": cycle_id,
        "company_id": company_id,
        "migration_state": state,
        "binding": binding,
        "delivery_evidence": delivery_evidence,
        "plan_digest": plan["plan_digest"],
        "local_operation_count": report["local_operation_count"],
        "remote_operation_count": report["remote_operation_count"],
        "local_only_operation_count": report["local_only_operation_count"],
        "protected_conflict_count": report["protected_conflict_count"],
        "remote_projection_digest": report["remote_projection_digest"],
        "mutation_performed": False,
    }


def adopt_retained_legacy_migration(inventory_path, local_path, cycle_id,
                                    company_id, approved):
    """Adopt one exact reviewed legacy plan locally; never publish it."""
    cycle_id = _required(cycle_id, "cycle ID")
    company_id = _required(company_id, "Company ID")
    if (not isinstance(approved, dict)
            or not isinstance(approved.get("binding"), dict)
            or not isinstance(approved.get("delivery_evidence"), dict)):
        raise ValueError("Exact legacy adoption requires reviewed approval JSON.")
    from .retained_cycle_retirement_control import assert_cycle_path_not_retired
    assert_cycle_path_not_retired(Path(inventory_path).parent / "state.db", cycle_id)
    approved_binding = approved["binding"]
    approved_delivery = approved["delivery_evidence"]
    destination, payload, legacy, cursor, _state = _read_retained(
        inventory_path, cycle_id, company_id)
    local = SQLiteRepository(local_path, destination, readonly=False)
    inbox = InventoryInbox(inventory_path, destination)
    try:
        controls = _controls(local, company_id, legacy.get("requested_url"))
        current = preview_legacy_migration_binding(
            local, cycle_id=cycle_id, company_id=company_id, payload=payload,
            legacy_plan=legacy, cursor=cursor, controls=controls)
        if current != approved_binding:
            raise ValueError("Exact legacy approval pins no longer match current evidence.")
        plan, report = build_legacy_v2_plan(
            local, cycle_id=cycle_id, company_id=company_id, payload=payload,
            legacy_plan=legacy, cursor=cursor, controls=controls,
            binding=approved_binding)
        delivery = validate_legacy_delivery_evidence(
            local, plan["remote_projection"], approved_delivery)
        stamp = timestamp()
        begun = inbox.begin_exact_legacy_migration(
            cycle_id, company_id, plan, approved_binding, timestamp=stamp)
        delivery_bound = inbox.bind_exact_legacy_delivery_evidence(
            cycle_id, company_id, plan, delivery, timestamp=timestamp())
        adopted = local.adopt_verified_legacy_local_plan(
            cycle_id, company_id, plan, timestamp_value=timestamp(),
            delivery_evidence=delivery)
        local_done = inbox.mark_exact_legacy_local_complete(
            cycle_id, company_id, plan, local, timestamp=timestamp())
        frozen = inbox.freeze_exact_legacy_successor(
            cycle_id, company_id, plan, local, timestamp=timestamp())
        return {
            "cycle_id": cycle_id,
            "company_id": company_id,
            "plan_digest": plan["plan_digest"],
            "remote_projection_digest": plan["remote_projection_digest"],
            "local_operation_count": report["local_operation_count"],
            "remote_operation_count": report["remote_operation_count"],
            "protected_conflict_count": report["protected_conflict_count"],
            "journal_started": begun["state"],
            "delivery_evidence_state": delivery_bound["state"],
            "delivery_mode": delivery["delivery_mode"],
            "local_adoption_state": adopted["state"],
            "local_completion_state": local_done["state"],
            "successor_state": frozen["state"],
            "receipt_created": False,
            "remote_write_performed": False,
        }
    finally:
        inbox.close()
        local.close()
