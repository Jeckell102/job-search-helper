"""Exact signed authorization for one queued historical Company membership."""

from .retained_work_exception import _timestamp, digest
from .selected_recovery_authorization import verify_authorization


ACTION = "activate-retained-operator-membership-v2"


def operator_membership_claims(snapshot, cycle_scope, *, historical_work_digest,
                               runtime, workbook_controls, expires_at):
    """Build signer input from measured local and workbook evidence."""
    request = snapshot["request"]
    receipt = snapshot["receipt"]
    company_id = cycle_scope["company_id"]
    request_identity = {
        "schema": "operator-company-scan-request-v1",
        "request_id": request.get("request_id"),
        "company_id": company_id,
        "source_revision": snapshot["source_revision"],
    }
    if (not isinstance(request_identity["request_id"], str) or not request_identity["request_id"]
            or request.get("mode") != "company-only" or request.get("company_ids") != [company_id]
            or request.get("operator_request") != request_identity
            or request.get("company_event") is not None or request.get("repair_retry") is not None
            or request.get("source_revision") != snapshot["source_revision"]):
        raise ValueError("retained_operator_request_changed")
    if (not isinstance(receipt, dict)
            or any(receipt.get(key) != value for key, value in request_identity.items())
            or receipt.get("request_sha256") != digest(request)
            or receipt.get("state") not in {"REQUEST_WRITTEN", "REQUEST_ALREADY_DURABLE"}):
        raise ValueError("retained_operator_receipt_changed")
    if snapshot["blocking_cycle_ids"] != [cycle_scope["cycle_id"]]:
        raise ValueError("retained_operator_effective_blocker_changed")
    if not runtime or not workbook_controls:
        raise ValueError("retained_operator_runtime_or_controls_missing")
    return {
        "action": ACTION,
        "version": 2,
        "request_id": request_identity["request_id"],
        "request_sha256": digest(request),
        "receipt_sha256": digest(receipt),
        "company_id": company_id,
        "source_revision": snapshot["source_revision"],
        "company_row_sha256": snapshot["company_row_digest"],
        "cycle_id": cycle_scope["cycle_id"],
        "cycle_scope_sha256": digest(cycle_scope),
        "historical_work_sha256": historical_work_digest,
        "historical_manifest_sha256": snapshot["manifest_digest"],
        "runtime_sha256": digest(runtime),
        "workbook_controls_sha256": digest(workbook_controls),
        "expires_at": _timestamp(expires_at),
    }


def verify_operator_membership_authorization(envelope, claims, verifier, *, now=None):
    if claims.get("version") != 2 or claims.get("action") != ACTION:
        raise ValueError("retained_operator_authorization_action_invalid")
    return verify_authorization(envelope, claims, verifier, now=now)
