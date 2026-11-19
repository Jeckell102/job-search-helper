"""Construct a bounded v2 successor for a verified legacy local prefix.

This is intentionally a *local* recovery primitive.  It never reads Google,
opens an inbox, starts a scraper, publishes, or replaces a saved plan.  The
caller must separately obtain approval and persist the returned immutable
successor through the normal exact-plan boundary.

It covers the one important case that ``exact_legacy_migration`` deliberately
rejects: a retained legacy plan whose first N operations are known to have
settled locally, while the remaining operations were never applied.  The
prefix is read back and journaled as VERIFIED without replay; the ordinary
exact-local chunk runner can then apply only the suffix.
"""
from __future__ import annotations

import copy
from typing import Mapping

from .exact_cycle_planner import (
    _control_evidence, _digest, _exact_plan_digest, _require_independent_targets,
    _seal_exact_plan_v2,
)
from .exact_legacy_migration import (
    MIGRATION_VERSION, PROTECTED_DRIFT_FIELDS, _capture_full_snapshot,
    _identity_digest, _order_remote_projection, _reconcile_local_operations,
)
from .exact_local_plan import _final_identity
from .publication_receipts import record_fingerprints
from .repository import _equivalent


SELECTED_RECOVERY_VERSION = "selected-legacy-prefix-recovery-v1"
_PREVIEW = object()


def _shape(plan, payload, cursor):
    if (not isinstance(plan, Mapping)
            or set(plan) != {"operations", "final", "requested_url"}
            or not isinstance(plan.get("operations"), list)
            or not plan["operations"]
            or not isinstance(plan.get("final"), Mapping)
            or plan.get("requested_url") != payload.get("requested_url")):
        raise ValueError("selected_legacy_plan_shape_invalid")
    if type(cursor) is not int or cursor < 1 or cursor > len(plan["operations"]):
        raise ValueError("selected_legacy_prefix_cursor_invalid")
    _require_independent_targets(plan["operations"])


def _controls(repository, cycle_id, company_id, payload, legacy, cursor):
    workbook = str(getattr(repository, "spreadsheet_id", "") or "").strip()
    if not workbook:
        raise ValueError("selected_legacy_workbook_identity_missing")
    return {
        "cycle_id": cycle_id,
        "company_id": company_id,
        "workbook_id_digest": _digest(workbook),
        "legacy_plan_digest": _digest(legacy),
        "inventory_payload_digest": _digest(payload),
        "legacy_operation_count": len(legacy["operations"]),
        "verified_prefix_cursor": cursor,
        "remaining_operation_count": len(legacy["operations"]) - cursor,
    }


def _operation_value(operation, header):
    """Materialize one legacy operation's final value without applying it."""
    value = operation.get("identity", {}).get(header)
    for mapping_name in ("on_insert", "values"):
        mapping = operation.get(mapping_name, {})
        if not isinstance(mapping, Mapping):
            raise ValueError("selected_legacy_operation_mapping_invalid")
        if header in mapping:
            value = mapping[header]
    return value


def _validate_all_ownership(company_id, operations, rows):
    """Bind every retained operation to the selected Company before sealing.

    Suffix operations are not allowed to evade the prefix's Company guard.
    Job Evidence is bound through the exact Job Key/Source Hash pair of a
    selected Job History operation; an evidence-only foreign record therefore
    fails before a candidate can be reviewed or journaled.
    """
    company = [(operation, row) for operation, row in zip(operations, rows)
               if operation.get("tab") == "Companies"]
    if (len(company) != 1
            or company[0][0].get("identity") != {"Company ID": company_id}
            or str(company[0][1].get("Company ID", "")).strip() != company_id):
        raise ValueError("selected_legacy_company_missing_or_ambiguous")
    company_name = str(company[0][1].get("Company", "")).strip()
    if not company_name:
        raise ValueError("selected_legacy_company_name_missing")
    history_sources = set()
    for operation, row in zip(operations, rows):
        tab = operation.get("tab")
        if tab == "Companies":
            continue
        if tab == "Job History":
            job_key = str(_operation_value(operation, "Job Key") or "").strip()
            source_hash = str(_operation_value(operation, "Source Hash") or "").strip()
            if (not job_key or not source_hash
                    or str(_operation_value(operation, "Company") or "").strip() != company_name
                    or str(row.get("Company", "")).strip() != company_name
                    or str(row.get("Job Key", "")).strip() != job_key
                    or str(row.get("Source Hash", "")).strip() != source_hash):
                raise ValueError("selected_legacy_job_ownership_mismatch")
            history_sources.add((job_key, source_hash))
    for operation, row in zip(operations, rows):
        tab = operation.get("tab")
        if tab in {"Companies", "Job History"}:
            continue
        if tab == "Job Evidence":
            job_key = str(_operation_value(operation, "Job Key") or "").strip()
            source_hash = str(_operation_value(operation, "Source Hash") or "").strip()
            if (not job_key or not source_hash
                    or (job_key, source_hash) not in history_sources
                    or str(_operation_value(operation, "Company") or "").strip() != company_name
                    or str(row.get("Job Key", "")).strip() != job_key
                    or str(row.get("Source Hash", "")).strip() != source_hash
                    or str(row.get("Company", "")).strip() != company_name):
                raise ValueError("selected_legacy_evidence_ownership_mismatch")
            continue
        # Remaining record types must carry their Company directly.  Cycle
        # aggregates and unknown tab operations have no record-level Company
        # authority and are deliberately outside selected recovery.
        if (str(_operation_value(operation, "Company") or "").strip() != company_name
                or str(row.get("Company", "")).strip() != company_name):
            raise ValueError("selected_legacy_operation_ownership_mismatch")
    return company[0][1]


def _validate_local_controls(company_row, controls):
    expected = {
        "company_id": company_row.get("Company ID", ""),
        "official_careers_url": company_row.get("Official Careers URL", ""),
        "company_status": company_row.get("Company Status", ""),
        "claimed_by": company_row.get("Claimed By", ""),
        "claim_token": company_row.get("Claim Token", ""),
    }
    for key, header in (("company_id", "Company ID"),
                        ("official_careers_url", "Official Careers URL"),
                        ("company_status", "Company Status"),
                        ("claimed_by", "Claimed By"),
                        ("claim_token", "Claim Token")):
        if not _equivalent(header, controls.get(key, ""), expected[key]):
            raise ValueError("selected_legacy_local_controls_mismatch")


def _protected_guard_digest(operations):
    guards = []
    for operation in operations:
        fields = {header: copy.deepcopy(value)
                  for header, value in operation.get("expected", {}).items()
                  if header in PROTECTED_DRIFT_FIELDS}
        if fields:
            guards.append({"tab": operation["tab"],
                           "identity": _final_identity(operation),
                           "guards": fields})
    return _digest(guards)


def _reconcile_suffix_protected_fields(operations, rows):
    """Keep current manual review fields as guards for unapplied suffix rows."""
    reconciled, conflicts = [], []
    for source, row in zip(operations, rows):
        operation = copy.deepcopy(source)
        changed = {}
        if operation.get("tab") == "Job History":
            for mapping_name in ("on_insert", "values"):
                mapping = operation.get(mapping_name, {})
                if not isinstance(mapping, Mapping):
                    raise ValueError("selected_legacy_operation_mapping_invalid")
                for header in tuple(mapping):
                    if header not in PROTECTED_DRIFT_FIELDS:
                        continue
                    if _equivalent(header, row.get(header, ""), mapping[header]):
                        continue
                    changed[header] = {
                        "legacy_digest": _digest(mapping[header]),
                        "current_digest": _digest(row.get(header, "")),
                    }
                    mapping.pop(header)
                    operation.setdefault("expected", {})[header] = copy.deepcopy(
                        row.get(header, ""))
        if changed:
            if not any(operation.get(key) for key in
                       ("values", "on_insert", "append_notes")):
                raise ValueError("selected_legacy_suffix_protected_removal_emptied_operation")
            conflicts.append({
                "identity_digest": _identity_digest(operation),
                "fields": sorted(changed),
                "legacy_values_digest": _digest(
                    {key: changed[key]["legacy_digest"] for key in sorted(changed)}),
                "current_values_digest": _digest(
                    {key: changed[key]["current_digest"] for key in sorted(changed)}),
            })
        reconciled.append(operation)
    return reconciled, conflicts


def _prune_suffix_noops(operations, rows):
    """Remove update values that already equal the untouched local row.

    Legacy update plans commonly repeat stable context such as ``Company``
    alongside the field that actually changed.  Such context never becomes
    dirty and therefore cannot be part of the exact Sheets mutation scope.
    Inserts and final-identity fields retain their original sealed semantics.
    """
    result = []
    for source, row in zip(operations, rows):
        operation = copy.deepcopy(source)
        if not operation.get("append_if_missing"):
            identity_fields = set(_final_identity(operation))
            values = operation.get("values", {})
            if not isinstance(values, Mapping):
                raise ValueError("selected_legacy_operation_mapping_invalid")
            for header, value in tuple(values.items()):
                if (header not in identity_fields
                        and _equivalent(header, row.get(header, ""), value)):
                    values.pop(header)
        if not any(operation.get(key) for key in
                   ("values", "on_insert", "append_notes")):
            raise ValueError("selected_legacy_suffix_noop_emptied_operation")
        result.append(operation)
    return result


def build_selected_legacy_v2_plan(repository, *, cycle_id, company_id, payload,
                                  legacy_plan, cursor, controls, binding):
    """Return a frozen full successor plus evidence for its settled prefix.

    ``cursor`` is a legacy local cursor, not a request to replay anything.  A
    caller can only feed the result to ``adopt_verified_legacy_prefix`` after
    the returned binding has been independently approved.
    """
    if (not isinstance(cycle_id, str) or not cycle_id.strip()
            or not isinstance(company_id, str) or not company_id.strip()):
        raise ValueError("selected_legacy_identity_invalid")
    if (not isinstance(payload, Mapping)
            or payload.get("inventory_status") not in {"complete", "partial"}
            or not isinstance(payload.get("jobs"), list)
            or not str(payload.get("requested_url") or "").strip()):
        raise ValueError("selected_legacy_inventory_invalid")
    _shape(legacy_plan, payload, cursor)
    cycle_id, company_id = cycle_id.strip(), company_id.strip()
    prefix = legacy_plan["operations"][:cursor]
    suffix = legacy_plan["operations"][cursor:]
    # The Company operation must have settled in the prefix.  A later control
    # operation cannot establish authority for previously applied job rows.
    if sum(operation.get("tab") == "Companies" for operation in prefix) != 1:
        raise ValueError("selected_legacy_company_must_be_in_verified_prefix")
    if sum(operation.get("tab") == "Companies"
           and operation.get("identity") == {"Company ID": company_id}
           for operation in legacy_plan["operations"]) != 1:
        raise ValueError("selected_legacy_company_operation_mismatch")
    base = _controls(repository, cycle_id, company_id, payload, legacy_plan, cursor)
    evidence, evidence_digest = _control_evidence(
        controls, company_id, payload["requested_url"])
    first_rows, first_snapshot = _capture_full_snapshot(
        repository, legacy_plan["operations"])
    company_row = _validate_all_ownership(
        company_id, legacy_plan["operations"], first_rows)
    _validate_local_controls(company_row, controls)
    reconciled_prefix, prefix_conflicts = _reconcile_local_operations(
        prefix, first_rows[:cursor])
    reconciled_suffix, suffix_conflicts = _reconcile_suffix_protected_fields(
        suffix, first_rows[cursor:])
    final_rows, final_snapshot = _capture_full_snapshot(
        repository, legacy_plan["operations"])
    if first_snapshot != final_snapshot:
        raise ValueError("selected_legacy_local_snapshot_changed")
    # The compact remote projection intentionally omits Source Hash, but the
    # exact publisher must still bind every Job History mutation to the local
    # source record it reviewed.  Preserve that guard in the full local row
    # scope before the successor is sealed; it is not a remote field and does
    # not widen the eventual Sheets write.
    for operation, row in zip(reconciled_prefix + reconciled_suffix, final_rows):
        if operation.get("tab") != "Job History":
            continue
        source_hash = str(row.get("Source Hash", "")).strip()
        if not source_hash:
            raise ValueError("selected_legacy_job_source_hash_missing")
        expected = operation.setdefault("expected", {})
        existing = expected.get("Source Hash")
        if existing not in (None, "", source_hash):
            raise ValueError("selected_legacy_job_source_hash_changed")
        expected["Source Hash"] = source_hash
    reconciled_suffix = _prune_suffix_noops(
        reconciled_suffix, first_rows[cursor:])
    observed = record_fingerprints(
        reconciled_prefix,
        {tab: [row for operation, row in zip(prefix, final_rows[:cursor])
               if operation.get("tab") == tab]
         for tab in {operation.get("tab") for operation in prefix}},
        include_guard_only=True)
    expected = record_fingerprints(reconciled_prefix, include_guard_only=True)
    if observed != expected:
        raise ValueError("selected_legacy_prefix_readback_mismatch")
    operations = reconciled_prefix + reconciled_suffix
    sealed = _seal_exact_plan_v2({
        "operations": operations,
        "final": copy.deepcopy(legacy_plan["final"]),
        "requested_url": legacy_plan["requested_url"],
        "control_evidence": evidence,
        "control_evidence_version": 1,
        "control_evidence_digest": evidence_digest,
    }, payload, repository, cycle_id, company_id)
    # Match the established exact legacy migration contract: guards are part
    # of the receipt fingerprints, and the remote projection uses the same
    # deterministic tab/row order as exact Sheets scope planning.
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
    # Preserve the existing migration guard contract while adding a distinct
    # prefix proof.  No inbox or remote receipt is created here.
    exact_binding = {
        **base,
        "current_local_snapshot_digest": final_snapshot,
        "current_prefix_snapshot_digest": _digest([
            {"tab": operation["tab"], "identity": operation.get("identity", {}),
             "record": row}
            for operation, row in zip(prefix, final_rows[:cursor])]),
        "prefix_records_digest": _digest(observed),
        "protected_guard_digest": _protected_guard_digest(operations),
        "approved_prefix_conflicts": copy.deepcopy(prefix_conflicts),
        "approved_suffix_conflicts": copy.deepcopy(suffix_conflicts),
        "publication_profile": sealed["publication_profile"],
        "publication_schema_digest": sealed["publication_schema_digest"],
    }
    if binding is _PREVIEW:
        return copy.deepcopy(exact_binding)
    if not isinstance(binding, Mapping) or dict(binding) != exact_binding:
        raise ValueError("selected_legacy_binding_mismatch")
    sealed["legacy_migration"] = {
        "version": MIGRATION_VERSION,
        "cycle_id": cycle_id,
        "company_id": company_id,
        "protected_fields": sorted(PROTECTED_DRIFT_FIELDS),
    }
    sealed["selected_legacy_recovery"] = {
        "version": SELECTED_RECOVERY_VERSION,
        **exact_binding,
        "protected_conflicts": prefix_conflicts + suffix_conflicts,
        "prefix_operation_digest": _digest(reconciled_prefix),
        "prefix_expected_records": observed,
    }
    sealed["plan_digest"] = _exact_plan_digest(sealed)
    report = {
        "version": SELECTED_RECOVERY_VERSION,
        "cycle_id": cycle_id,
        "company_id": company_id,
        "verified_prefix_cursor": cursor,
        "legacy_operation_count": len(operations),
        "remaining_operation_count": len(operations) - cursor,
        "local_snapshot_digest": final_snapshot,
        "prefix_records_digest": _digest(observed),
        "protected_conflict_count": len(prefix_conflicts) + len(suffix_conflicts),
        "prefix_identity_digests": [_identity_digest(item) for item in reconciled_prefix],
        "plan_digest": sealed["plan_digest"],
        "remote_projection_digest": sealed["remote_projection_digest"],
        "mutation_performed": False,
    }
    return sealed, report


def preview_selected_legacy_binding(repository, **kwargs):
    return build_selected_legacy_v2_plan(repository, binding=_PREVIEW, **kwargs)
