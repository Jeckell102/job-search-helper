"""Signer-bound authorization for selected legacy recovery.

Production callers receive only an Ed25519 public key.  The deliberately
small test verifier is injectable by tests and cannot be constructed by the
runner from an on-disk approval file.  Private material is never accepted by
this module or persisted in a recovery journal.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Mapping


AUTHORIZATION_VERSION = 1
ACTION = "selected-legacy-local-adopt-v1"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _require_digest(value, label):
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise ValueError("selected_recovery_authorization_%s_invalid" % label)
    return value


def required_claims(*, cycle_id, company_id, plan, recovery, expires_at):
    """Derive the complete approved scope from frozen local evidence."""
    if not isinstance(recovery, Mapping):
        raise ValueError("selected_recovery_authorization_recovery_missing")
    if not isinstance(expires_at, str) or not expires_at.strip():
        raise ValueError("selected_recovery_authorization_expiry_missing")
    claims = {
        "version": AUTHORIZATION_VERSION,
        "action": ACTION,
        "cycle_id": cycle_id,
        "company_id": company_id,
        "workbook_id_digest": recovery.get("workbook_id_digest"),
        "legacy_plan_digest": recovery.get("legacy_plan_digest"),
        "inventory_payload_digest": recovery.get("inventory_payload_digest"),
        "verified_prefix_cursor": recovery.get("verified_prefix_cursor"),
        "prefix_records_digest": recovery.get("prefix_records_digest"),
        "current_local_snapshot_digest": recovery.get("current_local_snapshot_digest"),
        "successor_plan_digest": plan.get("plan_digest"),
        "remote_projection_digest": plan.get("remote_projection_digest"),
        "expires_at": expires_at.strip(),
    }
    if (not isinstance(claims["cycle_id"], str) or not claims["cycle_id"]
            or not isinstance(claims["company_id"], str) or not claims["company_id"]
            or type(claims["verified_prefix_cursor"]) is not int
            or claims["verified_prefix_cursor"] < 1):
        raise ValueError("selected_recovery_authorization_scope_invalid")
    for label in ("workbook_id_digest", "legacy_plan_digest",
                  "inventory_payload_digest", "prefix_records_digest",
                  "current_local_snapshot_digest", "successor_plan_digest",
                  "remote_projection_digest"):
        _require_digest(claims[label], label)
    return claims


def _expiry(value, now):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError("selected_recovery_authorization_expiry_invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("selected_recovery_authorization_expiry_timezone_missing")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("selected_recovery_authorization_clock_timezone_missing")
    if parsed <= current:
        raise ValueError("selected_recovery_authorization_expired")


class Ed25519AuthorizationVerifier:
    """Verify externally issued envelopes against explicit public keys."""
    def __init__(self, public_keys):
        if not isinstance(public_keys, Mapping) or not public_keys:
            raise ValueError("selected_recovery_authorization_public_keys_required")
        self._public_keys = dict(public_keys)

    def verify(self, key_id, payload, signature):
        if key_id not in self._public_keys:
            raise ValueError("selected_recovery_authorization_key_unknown")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            key = Ed25519PublicKey.from_public_bytes(self._public_keys[key_id])
            key.verify(signature, canonical(payload))
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("selected_recovery_authorization_signature_invalid") from error


class TestAuthorizationVerifier:
    """Test-only deterministic verifier; never use it in a production runner."""
    __test__ = False
    test_only = True

    def __init__(self, token="selected-recovery-test-token"):
        self._token = token

    def issue(self, payload, *, key_id="test", signature="test-signature"):
        return {"key_id": key_id, "payload": payload, "signature": signature,
                "test_token": self._token}

    def verify(self, key_id, payload, signature, *, test_token=None):
        if key_id != "test" or signature != "test-signature" or test_token != self._token:
            raise ValueError("selected_recovery_authorization_signature_invalid")


def verify_authorization(envelope, expected_claims, verifier, *, now=None,
                         allow_test_verifier=False):
    """Validate a signed, exact-scope authorization before any writable open."""
    if not isinstance(envelope, Mapping) or set(envelope) - {"key_id", "payload", "signature", "test_token"}:
        raise ValueError("selected_recovery_authorization_envelope_invalid")
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping) or dict(payload) != dict(expected_claims):
        raise ValueError("selected_recovery_authorization_scope_mismatch")
    if not isinstance(envelope.get("key_id"), str) or not envelope["key_id"]:
        raise ValueError("selected_recovery_authorization_key_missing")
    signature_text = envelope.get("signature")
    if not isinstance(signature_text, str) or not signature_text:
        raise ValueError("selected_recovery_authorization_signature_missing")
    _expiry(payload["expires_at"], now)
    if getattr(verifier, "test_only", False):
        if not allow_test_verifier:
            raise ValueError("selected_recovery_authorization_test_verifier_forbidden")
        verifier.verify(envelope["key_id"], payload, signature_text,
                        test_token=envelope.get("test_token"))
    else:
        try:
            signature = base64.b64decode(signature_text.encode("ascii"), validate=True)
        except Exception as error:
            raise ValueError("selected_recovery_authorization_signature_encoding_invalid") from error
        verifier.verify(envelope["key_id"], payload, signature)
    return {"authorization_digest": digest(dict(envelope)),
            "claims_digest": digest(dict(payload)), "key_id": envelope["key_id"],
            # This is verified signed claim material, not a caller-selected
            # timestamp.  The durable journal needs it so the later exact-v2
            # publisher can refuse an authorization that has expired since
            # local adoption.
            "expires_at": payload["expires_at"]}
