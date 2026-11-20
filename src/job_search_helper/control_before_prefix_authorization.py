"""Signed approval for the exceptional control-before-prefix recovery.

This is deliberately separate from ``selected_recovery_authorization``.  It
does not authorize the ordinary selected-prefix recovery and cannot be used by
that runner.  A caller must provide an independently signed envelope which
pins the old operation ordering as well as the local-only successor.
"""
from __future__ import annotations

from typing import Mapping

from .selected_recovery_authorization import _require_digest, verify_authorization


AUTHORIZATION_VERSION = 2
ACTION = "selected-legacy-control-before-prefix-local-adopt-v2"


def required_control_before_prefix_claims(*, cycle_id, company_id, plan, recovery,
                                          expires_at):
    """Derive the complete signed scope for this one exceptional ordering."""
    if not isinstance(recovery, Mapping):
        raise ValueError("control_before_prefix_authorization_recovery_missing")
    if not isinstance(expires_at, str) or not expires_at.strip():
        raise ValueError("control_before_prefix_authorization_expiry_missing")
    claims = {
        "version": AUTHORIZATION_VERSION,
        "action": ACTION,
        "cycle_id": cycle_id,
        "company_id": company_id,
        "workbook_id_digest": recovery.get("workbook_id_digest"),
        "original_legacy_plan_digest": recovery.get("original_legacy_plan_digest"),
        "all_operations_digest": recovery.get("all_operations_digest"),
        "original_prefix_operation_digest": recovery.get("original_prefix_operation_digest"),
        "current_local_presence_snapshot_digest": recovery.get("current_local_presence_snapshot_digest"),
        "control_operation_digest": recovery.get("control_operation_digest"),
        "control_original_index": recovery.get("control_original_index"),
        "original_verified_prefix_cursor": recovery.get("original_verified_prefix_cursor"),
        "absent_suffix_count": recovery.get("absent_suffix_count"),
        "absent_suffix_manifest": recovery.get("absent_suffix_manifest"),
        "absent_suffix_manifest_digest": recovery.get("absent_suffix_manifest_digest"),
        "job_ownership_manifest": recovery.get("job_ownership_manifest"),
        "job_ownership_manifest_digest": recovery.get("job_ownership_manifest_digest"),
        "successor_plan_digest": plan.get("plan_digest"),
        "remote_projection_digest": plan.get("remote_projection_digest"),
        "expires_at": expires_at.strip(),
    }
    if (not isinstance(cycle_id, str) or not cycle_id.strip()
            or not isinstance(company_id, str) or not company_id.strip()
            or type(claims["control_original_index"]) is not int
            or type(claims["original_verified_prefix_cursor"]) is not int
            or claims["original_verified_prefix_cursor"] < 1
            or claims["control_original_index"] < claims["original_verified_prefix_cursor"]):
        raise ValueError("control_before_prefix_authorization_scope_invalid")
    for label in ("workbook_id_digest", "original_legacy_plan_digest",
                  "all_operations_digest", "original_prefix_operation_digest",
                  "current_local_presence_snapshot_digest",
                  "control_operation_digest", "successor_plan_digest",
                  "remote_projection_digest", "job_ownership_manifest_digest"):
        _require_digest(claims[label], label)
    if (type(claims["absent_suffix_count"]) is not int or claims["absent_suffix_count"] < 0
            or not isinstance(claims["absent_suffix_manifest"], list)
            or len(claims["absent_suffix_manifest"]) != claims["absent_suffix_count"]
            or not isinstance(claims["job_ownership_manifest"], list)
            or not claims["job_ownership_manifest"]):
        raise ValueError("control_before_prefix_authorization_absent_scope_invalid")
    return claims


def verify_control_before_prefix_authorization(envelope, expected_claims, verifier,
                                                *, now=None,
                                                allow_test_verifier=False):
    """Verify the exceptional scope using the existing public-key verifier."""
    if (not isinstance(expected_claims, Mapping)
            or expected_claims.get("action") != ACTION
            or expected_claims.get("version") != AUTHORIZATION_VERSION):
        raise ValueError("control_before_prefix_authorization_action_invalid")
    return verify_authorization(
        envelope, expected_claims, verifier, now=now,
        allow_test_verifier=allow_test_verifier)
