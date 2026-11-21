"""Exact external approval for one late-control pending-suffix continuation.

This module validates claims and signatures only. The durable owner must derive
``binding`` independently from its frozen journals and current observations. A
local cursor is never converted into evidence of remote delivery here. A valid
signature does not open a store, apply a plan, publish, or release a cycle.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from .selected_recovery_authorization import (
    Ed25519AuthorizationVerifier,
    TestAuthorizationVerifier,
    _require_digest,
    verify_authorization,
)


AUTHORIZATION_VERSION = 1
ACTION = "selected-legacy-late-control-continue-v1"
SCOPE = "one-company-exact-pending-suffix"
DIRECTION = "verified-local-then-exact-remote"
SIGNED_PARENT = "signed-local-only-hold-v1"
PREVIEW_PARENT = "bound-source-transition-preview-v1"
DIGEST_FIELDS = frozenset({
    "original_legacy_plan_digest", "inventory_payload_digest",
    "original_legacy_plan_raw_sha256", "original_inventory_payload_raw_sha256",
    "original_prefix_operation_digest", "parent_hold_digest",
    "parent_authorization_digest", "delta_plan_digest", "successor_plan_digest",
    "local_operations_digest", "remote_projection_digest",
    "remote_prefix_observation_digest", "pending_write_baseline_digest",
    "local_scope_digest", "remote_scope_digest",
})
BINDING_FIELDS = DIGEST_FIELDS | {
    "cycle_id", "company_id", "destination_id", "original_verified_prefix_cursor",
    "parent_kind",
}
CLAIM_FIELDS = BINDING_FIELDS | {
    "version", "action", "scope", "direction", "issued_at", "expires_at",
}


def _time(value, label):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"late_control_continuation_{label}_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"late_control_continuation_{label}_invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"late_control_continuation_{label}_timezone_missing")
    return parsed


def required_late_control_continuation_claims(*, binding, issued_at, expires_at):
    """Validate the closed, independently derived binding and return signed claims.

    The remote observation and first pending-write baseline are distinct required
    digests supplied by the owner. Neither has a cursor-based default. Scope
    digests bind the owner's exact field/row manifests, not merely a Company ID.
    """
    if not isinstance(binding, Mapping) or set(binding) != BINDING_FIELDS:
        raise ValueError("late_control_continuation_binding_fields_invalid")
    values = dict(binding)
    for label in ("cycle_id", "company_id", "destination_id"):
        value = values[label]
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"late_control_continuation_{label}_invalid")
    cursor = values["original_verified_prefix_cursor"]
    if type(cursor) is not int or cursor < 1:
        raise ValueError("late_control_continuation_cursor_invalid")
    for label in DIGEST_FIELDS - {"parent_authorization_digest"}:
        _require_digest(values[label], label)
    if values["parent_kind"] == SIGNED_PARENT:
        _require_digest(values["parent_authorization_digest"], "parent_authorization_digest")
    elif values["parent_kind"] == PREVIEW_PARENT:
        # This signature also authorizes archiving the independently derived
        # exact preview. It must not imply that an earlier signed hold exists.
        if values["parent_authorization_digest"] is not None:
            raise ValueError("late_control_continuation_preview_parent_authority_invalid")
    else:
        raise ValueError("late_control_continuation_parent_kind_invalid")
    if _time(issued_at, "issued_at") >= _time(expires_at, "expires_at"):
        raise ValueError("late_control_continuation_time_order_invalid")
    return {
        **values, "version": AUTHORIZATION_VERSION, "action": ACTION,
        "scope": SCOPE, "direction": DIRECTION,
        "issued_at": issued_at, "expires_at": expires_at,
    }


def verify_late_control_continuation_authorization(
        envelope, expected_claims, verifier, *, now=None, allow_test_verifier=False):
    """Authenticate exact current continuation claims with an explicit public key.

    Expected claims must come from the durable owner, never from the envelope.
    Generic duck-typed callbacks cannot substitute for the production verifier.
    Existing tests may explicitly opt into the existing deterministic verifier.
    """
    if not isinstance(expected_claims, Mapping) or set(expected_claims) != CLAIM_FIELDS:
        raise ValueError("late_control_continuation_claim_fields_invalid")
    canonical_claims = required_late_control_continuation_claims(
        binding={key: expected_claims[key] for key in BINDING_FIELDS},
        issued_at=expected_claims["issued_at"], expires_at=expected_claims["expires_at"],
    )
    if (type(expected_claims["version"]) is not int
            or dict(expected_claims) != canonical_claims):
        raise ValueError("late_control_continuation_scope_or_direction_invalid")
    if isinstance(verifier, TestAuthorizationVerifier):
        if not allow_test_verifier:
            raise ValueError("late_control_continuation_test_verifier_forbidden")
    elif not isinstance(verifier, Ed25519AuthorizationVerifier):
        raise ValueError("late_control_continuation_public_key_verifier_required")
    current = datetime.now(timezone.utc) if now is None else now
    if (not isinstance(current, datetime) or current.tzinfo is None
            or current.utcoffset() is None):
        raise ValueError("late_control_continuation_clock_timezone_missing")
    if _time(canonical_claims["issued_at"], "issued_at") > current:
        raise ValueError("late_control_continuation_not_yet_issued")
    verified = verify_authorization(
        envelope, canonical_claims, verifier, now=current,
        allow_test_verifier=allow_test_verifier,
    )
    return {**verified, "issued_at": canonical_claims["issued_at"]}
