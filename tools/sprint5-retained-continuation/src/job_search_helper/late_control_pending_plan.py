"""Construct a sealed, non-executable delta plan for a held late-control suffix."""
from __future__ import annotations

import copy
from typing import Mapping

from .exact_cycle_planner import _digest, _exact_plan_digest, _seal_exact_plan_v2
from .exact_control_before_prefix_recovery import preview_control_before_prefix_source_transition
from .publication_receipts import record_fingerprints
from .sqlite_repository import REVIEW_FIELDS


PENDING_VERSION = "late-control-pending-plan-v1"


def _required(value, label):
    if not isinstance(value, Mapping):
        raise ValueError("late_control_pending_%s_invalid" % label)
    return value


def build_late_control_pending_plan(repository, *, cycle_id, company_id, payload,
                                    legacy_plan, cursor, accepted_preview,
                                    authorization, controls):
    """Seal only the held suffix; this function grants no local or remote authority."""
    if (not isinstance(cycle_id, str) or not cycle_id or not isinstance(company_id, str)
            or not company_id or type(cursor) is not int):
        raise ValueError("late_control_pending_identity_invalid")
    if (not isinstance(legacy_plan, Mapping) or not isinstance(legacy_plan.get("operations"), list)
            or not 1 <= cursor < len(legacy_plan["operations"])):
        raise ValueError("late_control_pending_legacy_invalid")
    preview = _required(accepted_preview, "accepted_preview")
    preview_plan, preview_report = _required(preview.get("plan"), "preview_plan"), _required(preview.get("report"), "preview_report")
    binding = _required(preview_plan.get("binding"), "preview_binding")
    if (binding.get("version") != "selected-legacy-control-before-prefix-source-transition-preview-v1"
            or binding.get("cycle_id") != cycle_id or binding.get("company_id") != company_id
            or binding.get("legacy_plan_digest") != _digest(legacy_plan)
            or binding.get("original_verified_prefix_cursor") != cursor
            or preview_report.get("successor_operations_digest") != binding.get("successor_operations_digest")):
        raise ValueError("late_control_pending_preview_binding_mismatch")
    # Never accept a caller-fresh preview merely because its own digest is
    # internally consistent.  Re-derive the full local snapshot/control/manual
    # pin from the current repository before selecting any pending operation.
    current = preview_control_before_prefix_source_transition(
        repository, cycle_id=cycle_id, company_id=company_id, payload=payload,
        legacy_plan=legacy_plan, cursor=cursor, controls=controls)
    if (current.get("plan", {}).get("binding") != binding
            or current.get("report") != preview_report):
        raise ValueError("late_control_pending_preview_not_current")
    successor = preview_plan.get("operations")
    if (not isinstance(successor, list) or len(successor) != len(legacy_plan["operations"])
            or _digest(successor) != binding.get("successor_operations_digest")):
        raise ValueError("late_control_pending_preview_operations_mismatch")
    transition = _required(binding.get("transition"), "transition")
    history_index, evidence_index = transition.get("history_index"), transition.get("evidence_index")
    if (type(history_index) is not int or type(evidence_index) is not int
            or not cursor <= history_index < len(successor)
            or not cursor <= evidence_index < len(successor)
            or history_index == evidence_index):
        raise ValueError("late_control_pending_selected_indexes_invalid")
    # Only the selected History operation may differ, and it must be the exact
    # transformation that the accepted preview bound.
    for index, (before, after) in enumerate(zip(legacy_plan["operations"], successor)):
        if index != history_index and before != after:
            raise ValueError("late_control_pending_unselected_manual_transformation")
    if legacy_plan["operations"][history_index] == successor[history_index]:
        raise ValueError("late_control_pending_selected_transformation_missing")
    auth = _required(authorization, "authorization")
    suffix = list(range(cursor, len(successor)))
    pending = auth.get("pending_original_indices")
    held = auth.get("held_original_indices")
    observed = auth.get("observed_prefix_indices")
    if (not isinstance(pending, list) or not isinstance(held, list)
            or not isinstance(observed, list)
            or pending != sorted(set(pending)) or held != sorted(set(held))
            or observed != sorted(set(observed)) or not pending):
        raise ValueError("late_control_pending_disposition_invalid")
    if any(type(index) is not int or index < 0 or index >= len(successor)
           for index in pending + held + observed):
        raise ValueError("late_control_pending_disposition_invalid")
    if (set(pending) | set(held) != set(suffix)
            or set(pending).intersection(held)
            or history_index not in pending or evidence_index not in pending
            or set(observed).intersection(pending)
            or set(observed).intersection(held)):
        raise ValueError("late_control_pending_disposition_invalid")
    if (auth.get("version") != "late-control-pending-disposition-v1"
            or auth.get("preview_binding_digest") != _digest(binding)
            or not observed):
        raise ValueError("late_control_pending_disposition_invalid")
    for label in ("remote_prefix_observation_digest", "pending_write_baseline_digest"):
        value = auth.get(label)
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError("late_control_pending_%s_invalid" % label)
    delta_operations = [copy.deepcopy(successor[index]) for index in pending]
    # The normal SQLite writer removes protected review fields from both
    # values and expected guards when this exact row has a manual-choice pin.
    # Preserve those guards in the accepted-preview binding/manual snapshot,
    # but freeze the effective local operation exactly as the existing writer
    # will read it back; otherwise v2 fingerprints can never verify.
    for original_index, operation in zip(pending, delta_operations):
        if original_index == history_index and operation.get("tab") == "Job History":
            operation["expected"] = {
                header: value for header, value in operation.get("expected", {}).items()
                if header not in REVIEW_FIELDS}
    mapping = [{"original_index": index, "delta_index": delta,
                "original_operation_digest": _digest(legacy_plan["operations"][index]),
                "delta_operation_digest": _digest(operation)}
               for delta, (index, operation) in enumerate(zip(pending, delta_operations))]
    final = {"stage": "held_pending_late_control", "original_stage": legacy_plan.get("final", {}).get("stage", "")}
    sealed = _seal_exact_plan_v2({
        "operations": delta_operations, "final": final,
        "requested_url": legacy_plan.get("requested_url"),
        "control_evidence": {"company_id": company_id, "requested_url": legacy_plan.get("requested_url")},
        "control_evidence_version": 1,
        "control_evidence_digest": _digest({"company_id": company_id, "requested_url": legacy_plan.get("requested_url")}),
    }, payload, repository, cycle_id, company_id)
    sealed["record_fingerprint_version"] = 2
    sealed["local_expected_records"] = record_fingerprints(sealed["local_operations"], include_guard_only=True)
    sealed["local_expected_records_digest"] = _digest(sealed["local_expected_records"])
    sealed["remote_records"] = record_fingerprints(sealed["remote_projection"], include_guard_only=True)
    sealed["remote_records_digest"] = _digest(sealed["remote_records"])
    sealed["late_control_pending_plan"] = {
        "version": PENDING_VERSION, "original_legacy_plan_digest": _digest(legacy_plan),
        "original_verified_prefix_cursor": cursor, "original_to_delta": mapping,
        "accepted_preview_binding_digest": _digest(binding),
        "disposition_digest": _digest(auth), "local_only": True,
        "remote_release_authorized": False, "whole_suffix_terminal": False,
        "original_prefix_operation_digest": _digest(legacy_plan["operations"][:cursor]),
        "destination_digest": _digest(str(getattr(repository, "spreadsheet_id", "") or "")),
        "local_scope_digest": _digest(sealed["local_operations"]),
        "remote_scope_digest": _digest(sealed["remote_projection"]),
        "remote_prefix_observation_digest": auth["remote_prefix_observation_digest"],
        "pending_write_baseline_digest": auth["pending_write_baseline_digest"],
    }
    # This recognized marker keeps the generic exact publisher on its explicit
    # hold branch even if a later caller overlooks the dedicated metadata.
    sealed["selected_legacy_control_before_prefix_recovery"] = {
        "version": PENDING_VERSION, "local_only": True,
        "remote_release_authorized": False,
        "selected_indices": [history_index, evidence_index],
        "original_to_delta": mapping,
        "remote_prefix_observation_digest": auth["remote_prefix_observation_digest"],
        "pending_write_baseline_digest": auth["pending_write_baseline_digest"],
    }
    sealed["plan_digest"] = _exact_plan_digest(sealed)
    report = {"version": PENDING_VERSION, "cycle_id": cycle_id, "company_id": company_id,
              "original_verified_prefix_cursor": cursor, "delta_operation_count": len(delta_operations),
              "mapping_digest": _digest(mapping), "plan_digest": sealed["plan_digest"],
              "local_write_performed": False, "remote_write_performed": False,
              "receipt_created": False, "whole_suffix_terminal": False}
    return sealed, report
