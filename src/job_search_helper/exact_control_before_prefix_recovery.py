"""Strict local-only successor for a late Company control (protocol v2).

Unlike v1, this exceptional protocol models an *unapplied* suffix row that is
absent locally because it was supposed to be appended. Missing rows are never
silently treated as settled: they are allowed only after the original cursor,
only with literal ``append_if_missing is True``, and their full manifest is
part of the externally signed scope.
"""
from __future__ import annotations

import copy
from typing import Mapping

from .exact_cycle_planner import _control_evidence, _digest, _exact_plan_digest, _seal_exact_plan_v2
from .exact_legacy_migration import (MIGRATION_VERSION, PROTECTED_DRIFT_FIELDS,
                                     _reconcile_local_operations)
from .exact_local_plan import _final_identity
from .exact_selected_legacy_recovery import (_PREVIEW, _protected_guard_digest,
                                             _reconcile_suffix_protected_fields,
                                             _prune_suffix_noops, _shape)
from .publication_receipts import record_fingerprints
from .repository import _equivalent

CONTROL_BEFORE_PREFIX_VERSION = "selected-legacy-control-before-prefix-recovery-v3"


def _read_presence(repository, operations):
    """Read final identities once and retain an explicit absent marker."""
    schemas = getattr(repository, "schemas", None)
    if not isinstance(schemas, Mapping):
        raise ValueError("control_before_prefix_local_schema_missing")
    rows, records, seen = [], [], set()
    for index, operation in enumerate(operations):
        tab, identity = operation.get("tab"), _final_identity(operation)
        if not isinstance(tab, str) or tab not in schemas:
            raise ValueError("control_before_prefix_operation_tab_invalid")
        matches = repository.matches(tab, identity)
        if len(matches) > 1:
            raise ValueError("control_before_prefix_identity_ambiguous")
        if matches:
            row_id, row = matches[0]
            if (tab, row_id) in seen:
                raise ValueError("control_before_prefix_duplicate_local_target")
            seen.add((tab, row_id))
            normalized = {str(header): copy.deepcopy(row.get(header, "")) for header in schemas[tab]}
            rows.append(normalized)
            records.append({"original_index": index, "tab": tab, "identity": copy.deepcopy(identity),
                            "present": True, "record": normalized})
        else:
            rows.append(None)
            records.append({"original_index": index, "tab": tab, "identity": copy.deepcopy(identity),
                            "present": False})
    return rows, _digest(records)


def _operation_value(operation, header):
    value = operation.get("identity", {}).get(header)
    for name in ("on_insert", "values"):
        mapping = operation.get(name, {})
        if not isinstance(mapping, Mapping):
            raise ValueError("control_before_prefix_operation_mapping_invalid")
        if header in mapping:
            value = mapping[header]
    return value


def _require_late_target_control(plan, company_id, cursor):
    _shape(plan, {"requested_url": plan.get("requested_url")}, cursor)
    controls = [(i, op) for i, op in enumerate(plan["operations"]) if op.get("tab") == "Companies"]
    if len(controls) != 1:
        raise ValueError("control_before_prefix_company_missing_or_ambiguous")
    index, control = controls[0]
    if index < cursor:
        raise ValueError("control_before_prefix_requires_late_company_control")
    if control.get("identity") != {"Company ID": company_id}:
        raise ValueError("control_before_prefix_company_control_foreign")
    return index, control


def _absent_manifest(operations, rows, cursor, control_index):
    absent = []
    for index, (operation, row) in enumerate(zip(operations, rows)):
        if row is not None:
            continue
        if index < cursor or index == control_index:
            raise ValueError("control_before_prefix_required_row_missing")
        # ``is`` rejects truthy values supplied by a caller or decoder.
        if operation.get("append_if_missing") is not True:
            raise ValueError("control_before_prefix_absent_suffix_not_append_only")
        absent.append({"original_index": index, "tab": operation.get("tab"),
                       "final_identity": _final_identity(operation),
                       "operation_digest": _digest(operation)})
    return absent


def _explicit_ownership(operation):
    """Return legacy-owned company/source fields, never treating a guard as a write."""
    values = {}
    for name in ("identity", "on_insert", "values"):
        mapping = operation.get(name, {})
        if not isinstance(mapping, Mapping):
            raise ValueError("control_before_prefix_operation_mapping_invalid")
        for header in ("Company", "Source Hash"):
            if header in mapping:
                value = str(mapping[header] or "").strip()
                if header in values and values[header] != value:
                    raise ValueError("control_before_prefix_job_ownership_mismatch")
                values[header] = value
    return values


def _derived_guard(operation, row, company_name):
    """Accept only a present, non-append metadata update and freeze its owner."""
    if row is None or operation.get("append_if_missing") is not False:
        raise ValueError("control_before_prefix_job_ownership_mismatch")
    key = str(_operation_value(operation, "Job Key") or "").strip()
    source = str(row.get("Source Hash", "")).strip()
    if (not key or str(row.get("Job Key", "")).strip() != key
            or not source or str(row.get("Company", "")).strip() != company_name):
        raise ValueError("control_before_prefix_job_ownership_mismatch")
    expected = operation.get("expected", {})
    if not isinstance(expected, Mapping):
        raise ValueError("control_before_prefix_operation_mapping_invalid")
    for header, value in (("Company", company_name), ("Source Hash", source)):
        existing = expected.get(header)
        if existing not in (None, "", value):
            raise ValueError("control_before_prefix_job_ownership_mismatch")
    return key, source


def _validate_ownership(company_id, operations, rows):
    """Validate materialized ownership, including absent append-only records."""
    company = [(op, row) for op, row in zip(operations, rows) if op.get("tab") == "Companies"]
    if (len(company) != 1 or company[0][0].get("identity") != {"Company ID": company_id}
            or company[0][1] is None or str(company[0][1].get("Company ID", "")).strip() != company_id):
        raise ValueError("control_before_prefix_company_missing_or_ambiguous")
    company_name = str(company[0][1].get("Company", "")).strip()
    if not company_name:
        raise ValueError("control_before_prefix_company_name_missing")
    history, manifest = set(), []
    for index, (op, row) in enumerate(zip(operations, rows)):
        if op.get("tab") != "Job History":
            continue
        explicit = _explicit_ownership(op)
        if not explicit:
            key, source = _derived_guard(op, row, company_name)
            mode = "derived_current_guard"
        else:
            key = str(_operation_value(op, "Job Key") or "").strip()
            source = explicit.get("Source Hash", "")
            valid = (key and source and explicit.get("Company", "") == company_name)
            if row is not None:
                valid = valid and (str(row.get("Job Key", "")).strip(), str(row.get("Source Hash", "")).strip(),
                                   str(row.get("Company", "")).strip()) == (key, source, company_name)
            if not valid:
                raise ValueError("control_before_prefix_job_ownership_mismatch")
            mode = "explicit_operation"
        history.add((key, source))
        manifest.append({"original_index": index, "final_identity": _final_identity(op),
                         "present": row is not None, "ownership_mode": mode,
                         "job_key": key, "company": company_name,
                         "source_hash": source, "operation_digest": _digest(op),
                         "successor_expected_guard": (
                             {"Company": company_name, "Source Hash": source}
                             if mode == "derived_current_guard" else {})})
    for op, row in zip(operations, rows):
        tab = op.get("tab")
        if tab in {"Companies", "Job History"}:
            continue
        if tab == "Job Evidence":
            key, source = str(_operation_value(op, "Job Key") or "").strip(), str(_operation_value(op, "Source Hash") or "").strip()
            valid = (key, source) in history and str(_operation_value(op, "Company") or "").strip() == company_name
            if row is not None:
                valid = valid and (str(row.get("Job Key", "")).strip(), str(row.get("Source Hash", "")).strip(),
                                   str(row.get("Company", "")).strip()) == (key, source, company_name)
            if not valid:
                raise ValueError("control_before_prefix_evidence_ownership_mismatch")
        elif (str(_operation_value(op, "Company") or "").strip() != company_name
              or (row is not None and str(row.get("Company", "")).strip() != company_name)):
            raise ValueError("control_before_prefix_operation_ownership_mismatch")
    return company[0][1], manifest


def _install_derived_job_guards(operations, manifest):
    """Materialize only v3's signed metadata-owner guards in the successor."""
    for item in (entry for entry in manifest
                 if entry["ownership_mode"] == "derived_current_guard"):
        matches = [operation for operation in operations
                   if (operation.get("tab") == "Job History"
                       and _final_identity(operation) == item["final_identity"])]
        if len(matches) != 1 or matches[0].get("append_if_missing") is not False:
            raise ValueError("control_before_prefix_derived_guard_target_invalid")
        expected = matches[0].setdefault("expected", {})
        if not isinstance(expected, Mapping):
            raise ValueError("control_before_prefix_operation_mapping_invalid")
        for header, value in item["successor_expected_guard"].items():
            existing = expected.get(header)
            if existing not in (None, "", value):
                raise ValueError("control_before_prefix_derived_guard_changed")
            expected[header] = value


def _validate_controls(row, controls):
    for key, header in (("company_id", "Company ID"), ("official_careers_url", "Official Careers URL"),
                        ("company_status", "Company Status"), ("claimed_by", "Claimed By"),
                        ("claim_token", "Claim Token")):
        if not _equivalent(header, controls.get(key, ""), row.get(header, "")):
            raise ValueError("control_before_prefix_local_controls_mismatch")


def _reconcile_present_suffix(operations, rows):
    result, conflicts = [], []
    for operation, row in zip(operations, rows):
        if row is None:
            result.append(copy.deepcopy(operation))
            continue
        current, found = _reconcile_suffix_protected_fields([operation], [row])
        result.extend(_prune_suffix_noops(current, [row]))
        conflicts.extend(found)
    return result, conflicts


def _order_projection_with_absent(repository, operations):
    """Use normal tab order while making planned inserts deterministic.

    The generic publisher never accepts this protocol, but its frozen remote
    projection still needs canonical order. Present rows retain normal row-id
    ordering; a missing append-only row is placed after present rows in its
    tab, then by its sealed stream index.
    """
    from .sheets_sync import ORDER
    ordered = []
    for index, operation in enumerate(operations):
        tab = operation.get("tab")
        if tab not in ORDER:
            raise ValueError("control_before_prefix_remote_tab_unresolvable")
        matches = repository.matches(tab, _final_identity(operation))
        if len(matches) > 1:
            raise ValueError("control_before_prefix_remote_identity_ambiguous")
        rank = matches[0][0] if matches else 2 ** 63 - 1
        ordered.append((ORDER[tab], rank, index, copy.deepcopy(operation)))
    return [item[3] for item in sorted(ordered, key=lambda item: item[:3])]


def _binding(repository, *, cycle_id, company_id, payload, legacy_plan, cursor, controls):
    control_index, control = _require_late_target_control(legacy_plan, company_id, cursor)
    rows, snapshot = _read_presence(repository, legacy_plan["operations"])
    company_row, ownership_manifest = _validate_ownership(company_id, legacy_plan["operations"], rows)
    _validate_controls(company_row, controls)
    absent = _absent_manifest(legacy_plan["operations"], rows, cursor, control_index)
    return {"version": CONTROL_BEFORE_PREFIX_VERSION, "cycle_id": cycle_id, "company_id": company_id,
            "workbook_id_digest": _digest(str(getattr(repository, "spreadsheet_id", "") or "")),
            "original_legacy_plan_digest": _digest(legacy_plan), "all_operations_digest": _digest(legacy_plan["operations"]),
            "inventory_payload_digest": _digest(payload), "controls_digest": _digest(controls),
            "original_verified_prefix_cursor": cursor, "original_prefix_operation_digest": _digest(legacy_plan["operations"][:cursor]),
            "control_original_index": control_index, "control_operation_digest": _digest(control),
            "current_local_presence_snapshot_digest": snapshot, "absent_suffix_manifest": absent,
            "absent_suffix_count": len(absent), "absent_suffix_manifest_digest": _digest(absent),
            "job_ownership_manifest": ownership_manifest,
            "job_ownership_manifest_digest": _digest(ownership_manifest)}


def build_control_before_prefix_v2_plan(repository, *, cycle_id, company_id, payload, legacy_plan, cursor, controls, binding):
    if not isinstance(cycle_id, str) or not cycle_id.strip() or not isinstance(company_id, str) or not company_id.strip():
        raise ValueError("control_before_prefix_identity_invalid")
    if (not isinstance(payload, Mapping) or payload.get("inventory_status") not in {"complete", "partial"}
            or not isinstance(payload.get("jobs"), list) or not str(payload.get("requested_url") or "").strip()):
        raise ValueError("control_before_prefix_inventory_invalid")
    cycle_id, company_id = cycle_id.strip(), company_id.strip()
    exact = _binding(repository, cycle_id=cycle_id, company_id=company_id, payload=payload, legacy_plan=legacy_plan,
                     cursor=cursor, controls=controls)
    if binding is _PREVIEW:
        return copy.deepcopy(exact)
    if not isinstance(binding, Mapping) or dict(binding) != exact:
        raise ValueError("control_before_prefix_binding_mismatch")
    rows, snapshot = _read_presence(repository, legacy_plan["operations"])
    if snapshot != exact["current_local_presence_snapshot_digest"]:
        raise ValueError("control_before_prefix_local_snapshot_changed")
    original, index = legacy_plan["operations"], exact["control_original_index"]
    prefix, prefix_conflicts = _reconcile_local_operations(original[:cursor], rows[:cursor])
    before_control, before_conflicts = _reconcile_present_suffix(
        original[cursor:index], rows[cursor:index])
    after_control, after_conflicts = _reconcile_present_suffix(
        original[index + 1:], rows[index + 1:])
    # Company is moved only in the successor representation; its original
    # index/digest remains in the signed binding. The original Company entry is
    # removed from the tail without changing any other tail order.
    operations = [copy.deepcopy(original[index])] + prefix + before_control + after_control
    _install_derived_job_guards(operations, exact["job_ownership_manifest"])
    evidence, evidence_digest = _control_evidence(controls, company_id, payload["requested_url"])
    sealed = _seal_exact_plan_v2({"operations": operations, "final": copy.deepcopy(legacy_plan["final"]),
                                  "requested_url": legacy_plan["requested_url"], "control_evidence": evidence,
                                  "control_evidence_version": 1, "control_evidence_digest": evidence_digest},
                                 payload, repository, cycle_id, company_id)
    sealed["record_fingerprint_version"] = 2
    sealed["local_expected_records"] = record_fingerprints(sealed["local_operations"], include_guard_only=True)
    sealed["local_expected_records_digest"] = _digest(sealed["local_expected_records"])
    sealed["remote_projection"] = _order_projection_with_absent(repository, sealed["remote_projection"])
    sealed["remote_projection_digest"] = _digest(sealed["remote_projection"])
    sealed["remote_records"] = record_fingerprints(sealed["remote_projection"], include_guard_only=True)
    sealed["remote_records_digest"] = _digest(sealed["remote_records"])
    recovery = {**exact, "transformed_verified_prefix_cursor": cursor + 1,
                "transformed_prefix_operation_digest": _digest(sealed["local_operations"][:cursor + 1]),
                "protected_conflicts": prefix_conflicts + before_conflicts + after_conflicts,
                "protected_guard_digest": _protected_guard_digest(sealed["local_operations"]),
                "local_only": True, "remote_release_authorized": False}
    sealed["legacy_migration"] = {"version": MIGRATION_VERSION, "cycle_id": cycle_id, "company_id": company_id,
                                  "protected_fields": sorted(PROTECTED_DRIFT_FIELDS)}
    sealed["selected_legacy_control_before_prefix_recovery"] = recovery
    sealed["plan_digest"] = _exact_plan_digest(sealed)
    return sealed, {"version": CONTROL_BEFORE_PREFIX_VERSION, "cycle_id": cycle_id, "company_id": company_id,
                    "original_verified_prefix_cursor": cursor, "control_original_index": index,
                    "absent_suffix_count": len(exact["absent_suffix_manifest"]), "plan_digest": sealed["plan_digest"],
                    "remote_projection_digest": sealed["remote_projection_digest"], "mutation_performed": False,
                    "remote_write_performed": False, "receipt_created": False}


def preview_control_before_prefix_binding(repository, **kwargs):
    return build_control_before_prefix_v2_plan(repository, binding=_PREVIEW, **kwargs)
