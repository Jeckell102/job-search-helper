"""Deterministic scrape-outcome classification for integration automation.

This module is deliberately pure: it neither starts work nor changes a
Company, inventory, request, or release.  It makes a bounded, auditable
decision from facts already captured by the normal scraper.  The coordinator
can later persist and schedule the resulting action without letting an
ambiguous failure silently become an integration-repair request.
"""
from __future__ import annotations

from hashlib import sha256
import json


STALE_OR_PAUSED = "STALE_OR_PAUSED"
STORAGE_OR_SYNC_FAILURE = "STORAGE_OR_SYNC_FAILURE"
COMPLETE = "COMPLETE"
BLOCKED = "BLOCKED"
TEMPORARY = "TEMPORARY"
QUALIFIED_INTEGRATION_REPAIR = "QUALIFIED_INTEGRATION_REPAIR"
UNKNOWN_CAPABILITY_HOLD = "UNKNOWN_CAPABILITY_HOLD"
UNCLASSIFIED_HOLD = "UNCLASSIFIED_HOLD"


class OutcomeFactsError(ValueError):
    """Outcome facts are incomplete or unsafe to classify."""


def classify_outcome(facts):
    """Classify one immutable scrape outcome with the contract's precedence.

    Required identity fields are ``request_id``, ``company_id`` and
    ``source_revision``.  A caller may supply ``company_event_id`` for M2
    provenance.  The result contains no raw exception/body text; callers keep
    that material behind bounded evidence references.
    """
    if not isinstance(facts, dict):
        raise OutcomeFactsError("outcome facts must be an object")
    identity = _identity(facts)
    comparison = _comparison(facts)
    failure = _failure(facts)
    inventory = _text(facts.get("inventory_status")).casefold()

    source_current = facts.get("source_current")
    if not isinstance(source_current, bool):
        return _result(identity, failure, UNCLASSIFIED_HOLD, "hold_for_source_freshness")
    if (not source_current
            or _text(facts.get("company_status"), "company_status").casefold()
            in {"pause", "paused", "remove", "removed", "withdrawn"}):
        return _result(identity, failure, STALE_OR_PAUSED, "stop_stale_work", comparison=comparison)

    if _text(facts.get("storage_status"), "storage_status").casefold() in {
        "failed", "local_failed", "sync_failed", "sync_pending", "reconciliation_required",
    }:
        return _result(identity, failure, STORAGE_OR_SYNC_FAILURE, "reconcile_storage_only")

    if inventory == "complete" or (inventory == "zero" and facts.get("zero_openings_verified") is True):
        return _result(identity, failure, COMPLETE, "save_without_repair")

    category = _text(failure.get("category"), "failure category").casefold()
    if category in {"authentication", "captcha", "access_denied", "uncertain_employer", "ambiguous_identity"}:
        return _result(identity, failure, BLOCKED, "hold_for_policy_or_new_evidence")

    if category in {"timeout", "rate_limit", "temporary_transport", "temporary_provider", "server_error"}:
        return _result(identity, failure, TEMPORARY, "retry_with_bounded_backoff")

    capability = _text(facts.get("capability"), "capability").casefold()
    if category in {"adapter_regression", "full_description_regression", "pagination_regression"}:
        if capability == "qualified":
            return _result(identity, failure, QUALIFIED_INTEGRATION_REPAIR, "upsert_qualified_repair",
                           repair_category=category)
        return _result(identity, failure, UNKNOWN_CAPABILITY_HOLD, "hold_for_engineering")

    if capability in {"unknown", "unqualified", "new_provider", "new_executor"}:
        return _result(identity, failure, UNKNOWN_CAPABILITY_HOLD, "hold_for_engineering")

    return _result(identity, failure, UNCLASSIFIED_HOLD, "hold_without_invented_repair")


def _identity(facts):
    required = ("request_id", "company_id", "source_revision")
    identity = {key: _required_text(facts, key) for key in required}
    optional = ("company_event_id", "cycle_id", "attempt_id", "failed_request_id",
                "provider", "adapter_version", "release_version", "release_binding_sha256")
    identity.update({key: _text(facts.get(key), key) for key in optional if _text(facts.get(key), key)})
    # Non-retry cycles may have their own attempt IDs.  But once an outcome
    # claims release-to-retry lineage, retain all its immutable components;
    # otherwise a release ID alone could merge outcomes from distinct
    # source/dependency/configuration installations.
    retry_fields = ("attempt_id", "failed_request_id", "release_version", "release_binding_sha256")
    if any(key in identity for key in ("failed_request_id", "release_version", "release_binding_sha256")):
        missing = [key for key in retry_fields if key not in identity]
        if missing:
            raise OutcomeFactsError("retry outcome identity requires " + ", ".join(missing))
        digest = identity["release_binding_sha256"]
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise OutcomeFactsError("retry outcome release_binding_sha256 must be lowercase SHA-256")
    return identity


def _failure(facts):
    value = facts.get("failure", {})
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise OutcomeFactsError("failure facts must be an object")
    # Never put raw exception text or response bodies in the durable identity.
    result = {
        "category": _text(value.get("category"), "failure category"),
        "exception_type": _text(value.get("exception_type"), "failure exception_type"),
        "http_status": _http_status(value.get("http_status")),
        "provider_code": _text(value.get("provider_code"), "failure provider_code"),
    }
    result["fingerprint"] = _digest(result)
    return result


def _comparison(facts):
    """Bounded post-run evidence, deliberately separate from identity."""
    current = _text(facts.get("current_source_revision"), "current_source_revision")
    return {"current_source_revision": current} if current else {}


def _result(identity, failure, outcome, action, *, repair_category=None, comparison=None):
    immutable = {"identity": identity, "failure_fingerprint": failure["fingerprint"], "outcome": outcome}
    if repair_category is not None:
        immutable["repair_category"] = repair_category
    if comparison:
        immutable["comparison"] = comparison
    result = {
        "outcome_id": "OUT-" + _digest(immutable)[:24],
        "outcome": outcome,
        "action": action,
        "identity": identity,
        "failure_fingerprint": failure["fingerprint"],
    }
    if repair_category is not None:
        result["repair_category"] = repair_category
    if comparison:
        result["comparison"] = comparison
    return result


def _required_text(facts, key):
    value = _text(facts.get(key), key)
    if not value:
        raise OutcomeFactsError(f"{key} is required for immutable outcome identity")
    return value


def _text(value, field="value"):
    """Accept only small explicit text facts; never stringify opaque input."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise OutcomeFactsError(f"{field} must be text")
    value = value.strip()
    if len(value) > 256:
        raise OutcomeFactsError(f"{field} exceeds the 256-character evidence bound")
    return value


def _http_status(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 599:
        raise OutcomeFactsError("failure http_status must be an HTTP status code")
    return value


def _digest(value):
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return sha256(encoded).hexdigest()
