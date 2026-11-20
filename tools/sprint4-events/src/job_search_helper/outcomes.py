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
import re


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
    capability_identity = _capability_identity(facts)
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

    if category == 'same_provider_source_mapping':
        if facts.get('capability') == 'sealed':
            return _result(identity, failure, QUALIFIED_INTEGRATION_REPAIR,
                           'upsert_qualified_repair', repair_category=category,
                           capability_identity=capability_identity)
        return _result(identity, failure, UNKNOWN_CAPABILITY_HOLD, 'hold_for_engineering')

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
                "provider", "adapter_version", "release_version", "release_binding_sha256",
                "temporary_retry_outcome_id", "retained_reservation_sha256")
    identity.update({key: _text(facts.get(key), key) for key in optional if _text(facts.get(key), key)})
    if not valid_retained_outcome_identity(identity):
        raise OutcomeFactsError("retained outcome identity must bind the selected event and reservation")
    temporary = identity.get("temporary_retry_outcome_id")
    if temporary is not None:
        if (not re.fullmatch(r"OUT-[0-9a-f]{24}", temporary)
                or identity["request_id"] != "temporary-retry:" + temporary
                or any(key in identity for key in ("attempt_id", "failed_request_id",
                                                    "release_version", "release_binding_sha256"))):
            raise OutcomeFactsError("temporary retry outcome identity is invalid")
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


def valid_retained_outcome_identity(identity):
    """Bind the synthetic retained publication cycle without asserting repair lineage."""
    reservation = identity.get("retained_reservation_sha256")
    cycle = identity.get("cycle_id", "")
    if reservation is None:
        return not cycle.startswith("CYC-R")
    event = identity.get("company_event_id", "")
    return (re.fullmatch(r"[0-9a-f]{64}", reservation) is not None
            and re.fullmatch(r"CEV-[0-9a-f]{32}", event) is not None
            and re.fullmatch(r"[0-9a-f]{64}", identity["source_revision"]) is not None
            and identity["request_id"] == "company-event:" + event
            and cycle == "CYC-R" + _digest({"reservation_digest": reservation})[:12].upper()
            and not any(key in identity for key in (
                "attempt_id", "failed_request_id", "release_version", "release_binding_sha256",
                "temporary_retry_outcome_id")))


def _capability_identity(facts):
    """Validate the mapping identity while keeping it out of public identity."""
    identity_fields = ('capability_id', 'capability_digest', 'mapping_digest', 'configuration_digest')
    is_mapping = isinstance(facts.get('failure'), dict) and facts['failure'].get('category') == 'same_provider_source_mapping'
    # Public mapping identity is top-level only.  A second nested copy can
    # otherwise disagree after one boundary strips or ignores it.
    stack = list(facts.values())
    seen = set()
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            marker = id(value)
            if marker in seen:
                continue
            seen.add(marker)
            if any(key in value for key in identity_fields):
                raise OutcomeFactsError('capability identity fields must be top-level only')
            stack.extend(value.values())
        elif isinstance(value, (list, tuple)):
            stack.extend(value)
    present = [key for key in identity_fields if key in facts]
    if is_mapping:
        if len(present) != len(identity_fields):
            raise OutcomeFactsError('same_provider_source_mapping requires all capability identity fields')
        capability_id = facts['capability_id']
        if (not isinstance(capability_id, str)
                or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,95}', capability_id)):
            raise OutcomeFactsError('capability_id must be a bounded ASCII token')
        for key in identity_fields[1:]:
            value = facts[key]
            if not isinstance(value, str) or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
                raise OutcomeFactsError(f'{key} must be lowercase SHA-256')
        return {key: facts[key] for key in identity_fields}
    elif present:
        raise OutcomeFactsError('capability identity fields are reserved for same_provider_source_mapping')
    return None


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


def _result(identity, failure, outcome, action, *, repair_category=None, comparison=None,
            capability_identity=None):
    immutable = {"identity": identity, "failure_fingerprint": failure["fingerprint"], "outcome": outcome}
    if capability_identity is not None:
        immutable.update(capability_identity)
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
    if capability_identity is not None:
        result.update(capability_identity)
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


def validate_public_outcome_record(value):
    """Validate the canonical durable sender record before any delivery step.

    Capability identity is public only as four top-level mapping fields.  The
    classifier may use it in its private immutable-ID input, but nested copies
    in the persisted/public identity are forbidden.
    """
    if not isinstance(value, dict):
        return None
    required = {'outcome_id', 'outcome', 'action', 'identity', 'failure_fingerprint'}
    optional = {'repair_category', 'comparison'}
    mapping = value.get('repair_category') == 'same_provider_source_mapping'
    capability = {'capability_id', 'capability_digest', 'mapping_digest', 'configuration_digest'}
    expected = required | ({'repair_category'} if 'repair_category' in value else set()) | ({'comparison'} if 'comparison' in value else set())
    if mapping:
        expected |= capability
    if set(value) != expected:
        return None
    if (not isinstance(value['outcome_id'], str) or not re.fullmatch(r'OUT-[0-9a-f]{24}', value['outcome_id'])
            or not isinstance(value['failure_fingerprint'], str) or not re.fullmatch(r'[0-9a-f]{64}', value['failure_fingerprint'])
            or not isinstance(value['identity'], dict)
            or any(not isinstance(value['identity'].get(key), str) or not value['identity'][key]
                   for key in ('request_id', 'company_id', 'source_revision'))):
        return None
    if capability & set(value['identity']):
        return None
    identity_allowed = {'request_id', 'company_id', 'source_revision', 'company_event_id',
                        'cycle_id', 'attempt_id', 'failed_request_id', 'provider',
                        'adapter_version', 'release_version', 'release_binding_sha256', 'temporary_retry_outcome_id',
                        'retained_reservation_sha256'}
    if set(value['identity']) - identity_allowed:
        return None
    if any(not isinstance(item, str) or not item or item != item.strip() or len(item) > 256
           for item in value['identity'].values()):
        return None
    if not valid_retained_outcome_identity(value['identity']):
        return None
    retry = {'attempt_id', 'failed_request_id', 'release_version', 'release_binding_sha256'}
    if ({'failed_request_id', 'release_version', 'release_binding_sha256'} & set(value['identity'])
            and not retry <= set(value['identity'])):
        return None
    if 'release_binding_sha256' in value['identity'] and not re.fullmatch(r'[0-9a-f]{64}', value['identity']['release_binding_sha256']):
        return None
    if 'comparison' in value:
        comparison = value['comparison']
        if (not isinstance(comparison, dict) or set(comparison) != {'current_source_revision'}
                or not isinstance(comparison['current_source_revision'], str)
                or not comparison['current_source_revision']):
            return None
    if mapping:
        if (not isinstance(value['capability_id'], str)
                or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,95}', value['capability_id'])
                or any(not isinstance(value[key], str) or not re.fullmatch(r'[0-9a-f]{64}', value[key])
                       for key in capability - {'capability_id'})):
            return None
    elif capability & set(value):
        return None
    known_actions = {
        'STALE_OR_PAUSED': 'stop_stale_work', 'STORAGE_OR_SYNC_FAILURE': 'reconcile_storage_only',
        'COMPLETE': 'save_without_repair', 'BLOCKED': 'hold_for_policy_or_new_evidence',
        'TEMPORARY': 'retry_with_bounded_backoff', 'UNKNOWN_CAPABILITY_HOLD': 'hold_for_engineering',
        'UNCLASSIFIED_HOLD': 'hold_without_invented_repair',
        'QUALIFIED_INTEGRATION_REPAIR': 'upsert_qualified_repair',
    }
    if value['outcome'] not in known_actions or value['action'] != known_actions[value['outcome']]:
        return None
    repair = value.get('repair_category')
    if repair is not None and value['outcome'] != 'QUALIFIED_INTEGRATION_REPAIR':
        return None
    if mapping != (value['outcome'] == 'QUALIFIED_INTEGRATION_REPAIR' and repair == 'same_provider_source_mapping'):
        if repair == 'same_provider_source_mapping' or mapping:
            return None
    immutable = {'identity': value['identity'], 'failure_fingerprint': value['failure_fingerprint'],
                 'outcome': value['outcome']}
    if mapping:
        immutable.update({key: value[key] for key in capability})
    if repair is not None:
        if not isinstance(repair, str) or not re.fullmatch(r'[a-z_]{1,64}', repair):
            return None
        immutable['repair_category'] = repair
    if 'comparison' in value:
        immutable['comparison'] = value['comparison']
    if value['outcome_id'] != 'OUT-' + _digest(immutable)[:24]:
        return None
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    except (TypeError, ValueError):
        return None
