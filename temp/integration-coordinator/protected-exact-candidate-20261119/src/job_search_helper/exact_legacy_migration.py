"""Build an immutable v2 candidate from one explicitly reviewed legacy plan.

This module is local-only planning. It never opens Google, writes either
database, replaces a plan, creates a receipt, publishes, or cleans up work.
"""
from __future__ import annotations

import copy
from typing import Mapping

from .exact_cycle_planner import (
    _control_evidence,
    _digest,
    _exact_plan_digest,
    _require_independent_targets,
    _seal_exact_plan_v2,
)
from .exact_local_plan import _final_identity
from .publication_receipts import record_fingerprints
from .repository import _equivalent


MIGRATION_VERSION = "legacy-exact-plan-migration-v1"
PROTECTED_DRIFT_FIELDS = frozenset({"Review Status", "Decision"})
_BINDING_PREVIEW = object()


def _legacy_shape(plan, payload, cursor):
    if (not isinstance(plan, Mapping)
            or set(plan) != {"operations", "final", "requested_url"}
            or not isinstance(plan.get("operations"), list)
            or not plan["operations"]
            or not isinstance(plan.get("final"), Mapping)
            or plan.get("requested_url") != payload.get("requested_url")):
        raise ValueError("legacy_plan_shape_invalid")
    if type(cursor) is not int or cursor != len(plan["operations"]):
        raise ValueError("legacy_plan_local_cursor_not_complete")
    _require_independent_targets(plan["operations"])


def _identity_digest(operation):
    return _digest({
        "tab": operation.get("tab"),
        "identity": operation.get("identity"),
    })


def _base_binding(repository, cycle_id, company_id, payload, legacy_plan, cursor):
    """Return immutable identity pins supplied by the authoritative adopter."""
    workbook = str(getattr(repository, "spreadsheet_id", "") or "").strip()
    if not workbook:
        raise ValueError("legacy_migration_workbook_identity_missing")
    return {
        "cycle_id": cycle_id,
        "company_id": company_id,
        "workbook_id_digest": _digest(workbook),
        "legacy_plan_digest": _digest(legacy_plan),
        "inventory_payload_digest": _digest(payload),
        "legacy_operation_count": len(legacy_plan["operations"]),
        "original_local_cursor": cursor,
    }


def _capture_full_snapshot(repository, operations):
    """Read every selected row and digest its complete current local schema."""
    schemas = getattr(repository, "schemas", None)
    if not isinstance(schemas, Mapping):
        raise ValueError("legacy_migration_local_schema_missing")
    records, rows, seen = [], [], set()
    for operation in operations:
        tab = operation.get("tab")
        identity = _final_identity(operation)
        matches = repository.matches(tab, identity)
        if len(matches) != 1:
            raise ValueError("legacy_migration_identity_missing_or_ambiguous")
        row_id, row = matches[0]
        label = (tab, row_id)
        if label in seen:
            raise ValueError("legacy_migration_duplicate_local_target")
        headers = schemas.get(tab)
        if not isinstance(headers, (list, tuple)) or not headers:
            raise ValueError("legacy_migration_local_schema_invalid")
        normalized = {str(header): copy.deepcopy(row.get(header, ""))
                      for header in headers}
        records.append({"tab": tab, "identity": copy.deepcopy(identity),
                        "record": normalized})
        rows.append(normalized)
        seen.add(label)
    return rows, _digest(records)


def _validate_operation_ownership(company_id, operations, rows):
    company_rows = [(operation, row) for operation, row in zip(operations, rows)
                    if operation.get("tab") == "Companies"]
    if (len(company_rows) != 1
            or company_rows[0][0].get("identity") != {"Company ID": company_id}
            or str(company_rows[0][1].get("Company ID", "")).strip() != company_id):
        raise ValueError("legacy_migration_company_operation_mismatch")
    company_name = str(company_rows[0][1].get("Company", "")).strip()
    history_keys, evidence_keys = set(), set()
    for operation, row in zip(operations, rows):
        if operation.get("tab") == "Job History":
            if not company_name or str(row.get("Company", "")).strip() != company_name:
                raise ValueError("legacy_migration_job_company_mismatch")
            history_keys.add(str(row.get("Job Key", "")).strip())
        elif operation.get("tab") == "Job Evidence":
            evidence_keys.add(str(row.get("Job Key", "")).strip())
    if "" in history_keys | evidence_keys or evidence_keys - history_keys:
        raise ValueError("legacy_migration_job_evidence_ownership_mismatch")
    return company_rows[0][1]


def _validate_local_controls(company_row, controls):
    expected = {
        "company_id": company_row.get("Company ID", ""),
        "official_careers_url": company_row.get("Official Careers URL", ""),
        "company_status": company_row.get("Company Status", ""),
        "claimed_by": company_row.get("Claimed By", ""),
        "claim_token": company_row.get("Claim Token", ""),
    }
    if any(not _equivalent(header, controls.get(key, ""), value)
           for key, header, value in (
               ("company_id", "Company ID", expected["company_id"]),
               ("official_careers_url", "Official Careers URL",
                expected["official_careers_url"]),
               ("company_status", "Company Status", expected["company_status"]),
               ("claimed_by", "Claimed By", expected["claimed_by"]),
               ("claim_token", "Claim Token", expected["claim_token"]),
           )):
        raise ValueError("legacy_migration_local_controls_mismatch")


def _reconcile_local_operations(operations, rows):
    """Preserve recognized later review decisions and reject all other drift."""
    migrated, conflicts = [], []
    for source, row in zip(operations, rows):
        operation = copy.deepcopy(source)
        changed = {}
        for mapping_name in ("on_insert", "values"):
            mapping = operation.get(mapping_name, {})
            if not isinstance(mapping, Mapping):
                raise ValueError("legacy_operation_mapping_invalid")
            for header, old_value in tuple(mapping.items()):
                if _equivalent(header, row.get(header, ""), old_value):
                    continue
                if (operation.get("tab") != "Job History"
                        or header not in PROTECTED_DRIFT_FIELDS):
                    raise ValueError("legacy_local_nonprotected_drift")
                changed[header] = {
                    "legacy_digest": _digest(old_value),
                    "current_digest": _digest(row.get(header, "")),
                }
                mapping.pop(header)
                operation.setdefault("expected", {})[header] = copy.deepcopy(
                    row.get(header, ""))
        if changed:
            if not any(operation.get(key) for key in
                       ("values", "on_insert", "append_notes")):
                raise ValueError("legacy_conflict_removal_emptied_operation")
            conflicts.append({
                "identity_digest": _identity_digest(operation),
                "fields": sorted(changed),
                "legacy_values_digest": _digest({
                    key: changed[key]["legacy_digest"] for key in sorted(changed)}),
                "current_values_digest": _digest({
                    key: changed[key]["current_digest"] for key in sorted(changed)}),
            })
        migrated.append(operation)
    return migrated, conflicts


def _protected_guard_digest(operations):
    guards = []
    for operation in operations:
        protected = {header: copy.deepcopy(value)
                     for header, value in operation.get("expected", {}).items()
                     if header in PROTECTED_DRIFT_FIELDS}
        if protected:
            guards.append({"tab": operation["tab"],
                           "identity": _final_identity(operation),
                           "guards": protected})
    return _digest(guards)


def _order_remote_projection(repository, operations):
    """Freeze the same tab/row order used by exact Sheets scope planning."""
    from .sheets_sync import ORDER
    ordered = []
    for operation in operations:
        matches = repository.matches(operation["tab"], _final_identity(operation))
        if len(matches) != 1 or operation["tab"] not in ORDER:
            raise ValueError("legacy_migration_remote_order_unresolvable")
        ordered.append((ORDER[operation["tab"]], matches[0][0], operation))
    return [copy.deepcopy(operation) for _tab_order, _row_id, operation
            in sorted(ordered, key=lambda item: (item[0], item[1]))]


def build_legacy_v2_plan(repository, *, cycle_id, company_id, payload,
                         legacy_plan, cursor, controls, binding):
    """Return a sealed, non-persisted v2 candidate and sanitized evidence."""
    if (not isinstance(cycle_id, str) or not cycle_id.strip()
            or not isinstance(company_id, str) or not company_id.strip()):
        raise ValueError("legacy_migration_identity_invalid")
    if (not isinstance(payload, Mapping)
            or payload.get("inventory_status") not in {"complete", "partial"}
            or not isinstance(payload.get("jobs"), list)
            or not str(payload.get("requested_url") or "").strip()):
        raise ValueError("legacy_migration_inventory_invalid")
    _legacy_shape(legacy_plan, payload, cursor)
    cycle_id, company_id = cycle_id.strip(), company_id.strip()
    base_binding = _base_binding(
        repository, cycle_id, company_id, payload, legacy_plan, cursor)
    evidence, evidence_digest = _control_evidence(
        controls, company_id, payload["requested_url"])
    first_rows, first_snapshot_digest = _capture_full_snapshot(
        repository, legacy_plan["operations"])
    company_row = _validate_operation_ownership(
        company_id, legacy_plan["operations"], first_rows)
    _validate_local_controls(company_row, controls)
    operations, conflicts = _reconcile_local_operations(
        legacy_plan["operations"], first_rows)
    final_rows, final_snapshot_digest = _capture_full_snapshot(
        repository, legacy_plan["operations"])
    if first_snapshot_digest != final_snapshot_digest:
        raise ValueError("legacy_migration_local_snapshot_changed")
    observed = record_fingerprints(
        operations, {tab: [row for operation, row in zip(legacy_plan["operations"], final_rows)
                           if operation.get("tab") == tab]
                     for tab in {operation.get("tab") for operation in legacy_plan["operations"]}},
        include_guard_only=True)
    expected = record_fingerprints(operations, include_guard_only=True)
    if observed != expected:
        raise ValueError("legacy_migrated_selected_fields_mismatch")
    base = {
        "operations": operations,
        "final": copy.deepcopy(legacy_plan["final"]),
        "requested_url": legacy_plan["requested_url"],
        "control_evidence": evidence,
        "control_evidence_version": 1,
        "control_evidence_digest": evidence_digest,
    }
    sealed = _seal_exact_plan_v2(
        base, payload, repository, cycle_id, company_id)
    sealed["record_fingerprint_version"] = 2
    sealed["local_expected_records"] = record_fingerprints(
        sealed["local_operations"], include_guard_only=True)
    sealed["local_expected_records_digest"] = _digest(
        sealed["local_expected_records"])
    sealed["remote_projection"] = _order_remote_projection(
        repository, sealed["remote_projection"])
    sealed["remote_projection_digest"] = _digest(sealed["remote_projection"])
    sealed["remote_records"] = record_fingerprints(
        sealed["remote_projection"], include_guard_only=True)
    sealed["remote_records_digest"] = _digest(sealed["remote_records"])
    guard_digest = _protected_guard_digest(operations)
    exact_binding = {
        **base_binding,
        "inventory_blocked": False,
        "current_local_snapshot_digest": final_snapshot_digest,
        "selected_fields_readback_digest": _digest(observed),
        "protected_guard_digest": guard_digest,
        "approved_conflicts": copy.deepcopy(conflicts),
        "publication_profile": sealed["publication_profile"],
        "publication_schema_digest": sealed["publication_schema_digest"],
    }
    if binding is _BINDING_PREVIEW:
        return copy.deepcopy(exact_binding)
    if not isinstance(binding, Mapping) or dict(binding) != exact_binding:
        raise ValueError("legacy_migration_binding_mismatch")
    migration = {
        "version": MIGRATION_VERSION,
        **exact_binding,
        "protected_fields": sorted(PROTECTED_DRIFT_FIELDS),
        "protected_conflicts": conflicts,
    }
    sealed["legacy_migration"] = migration
    sealed["plan_digest"] = _exact_plan_digest(sealed)
    report = {
        "version": MIGRATION_VERSION,
        "cycle_id": cycle_id,
        "company_id": company_id,
        "legacy_plan_digest": migration["legacy_plan_digest"],
        "inventory_payload_digest": migration["inventory_payload_digest"],
        "current_local_snapshot_digest": final_snapshot_digest,
        "selected_fields_readback_digest": migration["selected_fields_readback_digest"],
        "protected_guard_digest": guard_digest,
        "legacy_operation_count": migration["legacy_operation_count"],
        "local_operation_count": len(sealed["local_operations"]),
        "remote_operation_count": len(sealed["remote_projection"]),
        "local_only_operation_count": (
            len(sealed["local_operations"]) - len(sealed["remote_projection"])),
        "protected_conflict_count": len(conflicts),
        "protected_conflict_identity_digests": [
            item["identity_digest"] for item in conflicts],
        "plan_digest": sealed["plan_digest"],
        "remote_projection_digest": sealed["remote_projection_digest"],
        "mutation_performed": False,
    }
    return sealed, report


def preview_legacy_migration_binding(repository, *, cycle_id, company_id,
                                     payload, legacy_plan, cursor, controls):
    """Return sanitized current pins for a separate human review/approval."""
    return build_legacy_v2_plan(
        repository, cycle_id=cycle_id, company_id=company_id, payload=payload,
        legacy_plan=legacy_plan, cursor=cursor, controls=controls,
        binding=_BINDING_PREVIEW)
