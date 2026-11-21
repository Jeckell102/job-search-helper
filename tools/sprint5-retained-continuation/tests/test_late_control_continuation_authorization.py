import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from job_search_helper.late_control_continuation_authorization import (
    ACTION, BINDING_FIELDS, DIGEST_FIELDS, DIRECTION, SCOPE, SIGNED_PARENT, PREVIEW_PARENT,
    required_late_control_continuation_claims,
    verify_late_control_continuation_authorization,
)
from job_search_helper.selected_recovery_authorization import (
    Ed25519AuthorizationVerifier, TestAuthorizationVerifier, canonical, digest,
)


class LateControlContinuationAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.binding = {key: digest({"fixture": key}) for key in DIGEST_FIELDS}
        self.binding.update(cycle_id="CYC-B639C6D864EC", company_id="COMP-0054",
                            destination_id="disposable-workbook",
                            original_verified_prefix_cursor=67, parent_kind=SIGNED_PARENT)
        self.issued = "2026-11-21T11:00:00Z"
        self.expires = "2026-11-21T12:00:00Z"
        self.now = datetime(2026, 11, 21, 11, 30, tzinfo=timezone.utc)
        self.claims = self.claims_for(self.binding)
        self.private = Ed25519PrivateKey.generate()
        public = self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.verifier = Ed25519AuthorizationVerifier({"fixture-key": public})

    def claims_for(self, binding):
        return required_late_control_continuation_claims(
            binding=binding, issued_at=self.issued, expires_at=self.expires)

    def sign(self, claims=None):
        claims = copy.deepcopy(self.claims if claims is None else claims)
        return {"key_id": "fixture-key", "payload": claims,
                "signature": base64.b64encode(self.private.sign(canonical(claims))).decode("ascii")}

    def verify(self, envelope=None, claims=None, **kwargs):
        return verify_late_control_continuation_authorization(
            self.sign() if envelope is None else envelope,
            self.claims if claims is None else claims,
            self.verifier, now=kwargs.pop("now", self.now), **kwargs)

    def test_real_ed25519_exact_approval_has_stable_evidence_and_no_input_mutation(self):
        envelope = self.sign()
        original = copy.deepcopy((self.binding, self.claims, envelope))
        result = self.verify(envelope)
        self.assertEqual(result, {"authorization_digest": digest(envelope),
                                 "claims_digest": digest(self.claims), "key_id": "fixture-key",
                                 "issued_at": self.issued, "expires_at": self.expires})
        self.assertEqual(result, self.verify(envelope))
        self.assertEqual(original, (self.binding, self.claims, envelope))

    def test_each_target_and_evidence_pin_is_bound_even_with_a_valid_signature(self):
        for field in sorted(BINDING_FIELDS - {"parent_kind"}):
            with self.subTest(field=field):
                changed = dict(self.binding)
                changed[field] = (68 if field == "original_verified_prefix_cursor" else
                                  "f" * 64 if field in DIGEST_FIELDS else "different-target")
                signed_other = self.sign(self.claims_for(changed))
                with self.assertRaisesRegex(ValueError, "scope_mismatch"):
                    self.verify(signed_other)

    def test_preview_parent_uses_one_signature_with_explicit_absent_prior_authority(self):
        preview_binding = dict(self.binding, parent_kind=PREVIEW_PARENT,
                               parent_authorization_digest=None)
        preview = self.claims_for(preview_binding)
        result = self.verify(self.sign(preview), preview)
        self.assertEqual(result["claims_digest"], digest(preview))
        with self.assertRaisesRegex(ValueError, "scope_mismatch"):
            self.verify(self.sign(preview))
        for changes in ({"parent_kind": SIGNED_PARENT, "parent_authorization_digest": None},
                        {"parent_kind": PREVIEW_PARENT}, {"parent_kind": "unspecified"}):
            with self.assertRaises(ValueError):
                self.claims_for(dict(self.binding, **changes))

    def test_remote_proof_and_pending_baseline_are_separately_required_not_cursor_defaults(self):
        for field in ("remote_prefix_observation_digest", "pending_write_baseline_digest"):
            for invalid in (None, 67, "67", "", "a" * 63, "A" * 64):
                with self.subTest(field=field, invalid=invalid):
                    binding = dict(self.binding, **{field: invalid})
                    with self.assertRaises(ValueError):
                        self.claims_for(binding)
            binding = dict(self.binding)
            del binding[field]
            with self.assertRaises(ValueError):
                self.claims_for(binding)

    def test_original_raw_text_is_bound_separately_from_semantic_json(self):
        raw = '{"label":"caf\u00e9","value":1}'
        reformatted = '{ "value": 1, "label": "caf\u00e9" }'
        self.assertEqual(digest(json.loads(raw)), digest(json.loads(reformatted)))
        raw_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        other_hash = hashlib.sha256(reformatted.encode("utf-8")).hexdigest()
        self.assertNotEqual(raw_hash, other_hash)
        for raw_field, semantic_field in (
                ("original_legacy_plan_raw_sha256", "original_legacy_plan_digest"),
                ("original_inventory_payload_raw_sha256", "inventory_payload_digest")):
            with self.subTest(field=raw_field):
                binding = dict(self.binding, **{raw_field: raw_hash,
                                               semantic_field: digest(json.loads(raw))})
                approved = self.claims_for(binding)
                self.verify(self.sign(approved), approved)
                changed = self.claims_for(dict(binding, **{raw_field: other_hash}))
                with self.assertRaisesRegex(ValueError, "scope_mismatch"):
                    self.verify(self.sign(approved), changed)
                del binding[raw_field]
                with self.assertRaisesRegex(ValueError, "binding_fields_invalid"):
                    self.claims_for(binding)

    def test_all_digest_fields_and_closed_binding_are_checked(self):
        for field in DIGEST_FIELDS:
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.claims_for(dict(self.binding, **{field: "not-a-digest"}))
        with self.assertRaises(ValueError):
            self.claims_for(dict(self.binding, automatic_release=True))
        for cursor in (True, False, 0, -1, "67"):
            with self.assertRaises(ValueError):
                self.claims_for(dict(self.binding, original_verified_prefix_cursor=cursor))
        for field in ("cycle_id", "company_id", "destination_id"):
            for value in ("", " leading", None):
                with self.assertRaises(ValueError):
                    self.claims_for(dict(self.binding, **{field: value}))

    def test_wrong_action_scope_direction_and_schema_cannot_be_self_approved(self):
        for field, value in (("action", "selected-legacy-control-before-prefix-local-adopt-v2"),
                             ("scope", "all-companies"), ("direction", "remote-then-local"),
                             ("version", 2), ("version", True)):
            with self.subTest(field=field, value=value):
                wrong = dict(self.claims, **{field: value})
                with self.assertRaises(ValueError):
                    self.verify(self.sign(wrong), wrong)
        self.assertEqual((self.claims["action"], self.claims["scope"], self.claims["direction"]),
                         (ACTION, SCOPE, DIRECTION))

    def test_expected_claims_are_revalidated_not_trusted_as_a_freeform_payload(self):
        cases = [dict(self.claims, parent_hold_digest="bad"),
                 dict(self.claims, permit_broad_sync=True)]
        missing = dict(self.claims)
        del missing["remote_prefix_observation_digest"]
        cases.append(missing)
        for wrong in cases:
            with self.assertRaises(ValueError):
                self.verify(self.sign(wrong), wrong)

    def test_expiry_and_issuance_boundaries(self):
        self.verify(now=datetime(2026, 11, 21, 11, 0, tzinfo=timezone.utc))
        for current in (datetime(2026, 11, 21, 10, 59, tzinfo=timezone.utc),
                        datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc),
                        datetime(2026, 11, 21, 12, 1, tzinfo=timezone.utc),
                        datetime(2026, 11, 21, 11, 30)):
            with self.assertRaises(ValueError):
                self.verify(now=current)
        for issued, expires in ((self.expires, self.issued), (self.issued, self.issued),
                                ("2026-11-21T11:00:00", self.expires),
                                (self.issued, "2026-11-21T12:00:00"), ("bad", self.expires)):
            with self.assertRaises(ValueError):
                required_late_control_continuation_claims(
                    binding=self.binding, issued_at=issued, expires_at=expires)

    def test_bad_signature_unknown_key_and_bad_encoding_refuse(self):
        envelope = self.sign()
        for change in ({"signature": base64.b64encode(b"x" * 64).decode("ascii")},
                       {"key_id": "other-key"}, {"signature": "not base64"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify(dict(envelope, **change))
        changed = copy.deepcopy(envelope)
        changed["payload"]["parent_hold_digest"] = "e" * 64
        with self.assertRaises(ValueError):
            self.verify(changed, changed["payload"])

    def test_test_verifier_is_explicit_and_generic_callbacks_are_refused(self):
        fixture_verifier = TestAuthorizationVerifier()
        envelope = fixture_verifier.issue(self.claims)
        with self.assertRaisesRegex(ValueError, "test_verifier_forbidden"):
            verify_late_control_continuation_authorization(
                envelope, self.claims, fixture_verifier, now=self.now)
        result = verify_late_control_continuation_authorization(
            envelope, self.claims, fixture_verifier, now=self.now, allow_test_verifier=True)
        self.assertEqual(result["claims_digest"], digest(self.claims))

        class AcceptAnything:
            def verify(self, *args, **kwargs):
                raise AssertionError("untyped verifier must never be called")

        with self.assertRaisesRegex(ValueError, "public_key_verifier_required"):
            verify_late_control_continuation_authorization(
                self.sign(), self.claims, AcceptAnything(), now=self.now, allow_test_verifier=True)


if __name__ == "__main__":
    unittest.main()
