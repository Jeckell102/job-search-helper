import base64
import copy
from datetime import datetime, timezone
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from job_search_helper.retained_operator_authorization import (
    operator_membership_claims, verify_operator_membership_authorization,
)
from job_search_helper.retained_work_exception import digest
from job_search_helper.selected_recovery_authorization import Ed25519AuthorizationVerifier, canonical


class RetainedOperatorAuthorizationTest(unittest.TestCase):
    def setUp(self):
        identity = {"schema": "operator-company-scan-request-v1", "request_id": "request-1",
                    "company_id": "COMP-0739", "source_revision": "revision-1"}
        request = {"request_id": "request-1", "company_ids": ["COMP-0739"], "mode": "company-only",
                   "source_revision": "revision-1", "operator_request": identity}
        self.snapshot = {
            "request": request, "receipt": {**identity, "request_sha256": digest(request),
                                               "state": "REQUEST_WRITTEN"},
            "company_row_digest": digest("company"), "manifest_digest": digest("historical"),
            "source_revision": "revision-1", "blocking_cycle_ids": ["CYC-OLD"],
        }
        self.scope = {"company_id": "COMP-0739", "cycle_id": "CYC-OLD", "membership_sha256": digest("queued")}
        self.runtime = {"state": "NO_RELEASE", "source_manifest_sha256": digest("source")}
        self.workbook = {"profile": "compact-v1", "company_id": "COMP-0739"}
        self.expiry = "2026-11-21T00:00:00Z"
        self.now = datetime(2026, 11, 20, tzinfo=timezone.utc)
        self.private_key = Ed25519PrivateKey.generate()
        self.verify = Ed25519AuthorizationVerifier({
            "fixture": self.private_key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw),
        })

    def claims(self):
        return operator_membership_claims(self.snapshot, self.scope, historical_work_digest=digest("work"),
                                          runtime=self.runtime, workbook_controls=self.workbook,
                                          expires_at=self.expiry)

    def envelope(self, claims):
        return {"payload": claims, "key_id": "fixture",
                "signature": base64.b64encode(self.private_key.sign(canonical(claims))).decode("ascii")}

    def test_exact_signed_claims_and_scope_drift(self):
        original = self.claims()
        signed = self.envelope(original)
        self.assertEqual(verify_operator_membership_authorization(
            signed, original, self.verify, now=self.now)["key_id"], "fixture")
        for mapping, field in ((self.scope, "membership_sha256"), (self.runtime, "source_manifest_sha256"),
                               (self.workbook, "profile"), (self.snapshot, "company_row_digest")):
            with self.subTest(field=field):
                before = mapping[field]
                mapping[field] = "changed"
                with self.assertRaisesRegex(ValueError, "scope_mismatch"):
                    verify_operator_membership_authorization(signed, self.claims(), self.verify, now=self.now)
                mapping[field] = before

    def test_rejects_mixed_request_unmatched_receipt_and_expiry(self):
        claims = self.claims()
        with self.assertRaisesRegex(ValueError, "expired"):
            verify_operator_membership_authorization(
                self.envelope(claims), claims, self.verify, now=datetime(2026, 11, 21, tzinfo=timezone.utc))
        original = copy.deepcopy(self.snapshot)
        self.snapshot["request"]["company_event"] = {"event_id": "unapproved"}
        with self.assertRaisesRegex(ValueError, "request_changed"):
            self.claims()
        self.snapshot = original
        self.snapshot["receipt"]["request_sha256"] = "different"
        with self.assertRaisesRegex(ValueError, "receipt_changed"):
            self.claims()
