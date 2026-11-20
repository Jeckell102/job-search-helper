"""Offline crash and identity checks for the retained operator journal."""
import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper import retained_operator_journal as journal


_FETCH = {
    "status": "complete", "jobs": [{"Job Key": "job-fixture", "Description": "full text ✓"}],
    "ats": "Ashby", "source_url": "https://api.ashbyhq.com/posting-api/job-board/test",
    "requested_url": "https://jobs.ashbyhq.com/test",
    "fetched_at": "2026-11-20T17:00:00+00:00",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


class RetainedOperatorJournalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.journal = journal.RetainedOperatorJournal(self.root)
        self.runtime = {
            "state": "NO_RELEASE",
            "source_manifest_sha256": digest("source"),
            "config_sha256": digest("configuration"),
            "dependency_manifest_sha256": digest("dependencies"),
        }
        self.claims = {
            "action": "activate-retained-operator-membership-v2", "version": 2,
            "request_id": "operator-test-1", "company_id": "COMP-0739",
            "source_revision": digest("company source"), "cycle_id": "CYC-OLD",
            "expires_at": datetime(2026, 11, 21, tzinfo=timezone.utc).isoformat(),
            "runtime_sha256": digest(self.runtime),
            **{key: digest(key) for key in (
                "request_sha256", "receipt_sha256", "company_row_sha256", "cycle_scope_sha256",
                "historical_work_sha256", "historical_manifest_sha256", "workbook_controls_sha256",
            )},
        }
        self.authorization = {
            "authorization_digest": digest("verified authorization envelope"),
            "claims_digest": digest(self.claims), "key_id": "test-signer",
            "expires_at": self.claims["expires_at"],
        }
        self.binding = journal.operator_journal_binding(self.claims, self.runtime, self.authorization)
        self.consumption = {"request_sha256": self.claims["request_sha256"],
                            "state": "FIRST_PASS_RELEASED_CONSUMED"}
        self.evidence = {"state": "FIRST_PASS_RELEASED", "reservation_digest": self.binding["reservation_digest"],
                         "publication_sha256": digest("terminal downstream receipt")}

    def test_one_claim_freeze_readback_and_settlement_keep_the_normal_hold(self):
        journal.assert_no_unfinished_operator_journal(self.root)
        self.assertEqual(journal.PREPARED, self.journal.prepare(self.binding)["state"])
        self.assertEqual(journal.PREPARED, self.journal.prepare(self.binding)["state"])
        with self.assertRaisesRegex(ValueError, "holds_normal_lifecycle"):
            journal.assert_no_unfinished_operator_journal(self.root)
        token = self.journal.claim_fetch(self.binding)
        self.assertNotIn(token, self.journal.path.read_text())
        with self.assertRaisesRegex(ValueError, "already_claimed"):
            self.journal.claim_fetch(self.binding)
        with self.assertRaisesRegex(ValueError, "claim_invalid"):
            self.journal.freeze_inventory(self.binding, "0" * 64, _FETCH)
        frozen = self.journal.freeze_inventory(self.binding, token, _FETCH)
        self.assertEqual(journal.INVENTORY_FROZEN, frozen["state"])
        self.assertEqual(frozen, self.journal.freeze_inventory(self.binding, token, _FETCH))
        with self.assertRaisesRegex(ValueError, "inventory_changed"):
            self.journal.freeze_inventory(self.binding, token, dict(_FETCH, jobs=[]))
        reopened = journal.RetainedOperatorJournal(self.root)
        self.assertEqual(_FETCH, reopened.recover_inventory(self.binding))
        with self.assertRaisesRegex(ValueError, "holds_normal_lifecycle"):
            journal.assert_no_unfinished_operator_journal(self.root)
        with self.assertRaisesRegex(ValueError, "consumption_binding_changed"):
            reopened.release_after_settlement(self.binding, inventory_sha256=frozen["inventory_sha256"],
                                             consumption=self.consumption)
        with self.assertRaisesRegex(ValueError, "settlement_binding_changed"):
            reopened.record_settlement(self.binding, inventory_sha256="0" * 64, evidence=self.evidence)
        with self.assertRaisesRegex(ValueError, "evidence_binding_changed"):
            reopened.record_settlement(self.binding, inventory_sha256=frozen["inventory_sha256"],
                                       evidence=dict(self.evidence, reservation_digest="0" * 64))
        settled = reopened.record_settlement(self.binding, inventory_sha256=frozen["inventory_sha256"],
                                             evidence=self.evidence)
        self.assertEqual(journal.SETTLED, settled["state"])
        self.assertEqual(digest(self.evidence), settled["settlement_evidence_sha256"])
        with self.assertRaisesRegex(ValueError, "holds_normal_lifecycle"):
            journal.assert_no_unfinished_operator_journal(self.root)
        with self.assertRaisesRegex(ValueError, "consumption_binding_changed"):
            reopened.release_after_settlement(self.binding, inventory_sha256=frozen["inventory_sha256"],
                                             consumption=dict(self.consumption, request_sha256="0" * 64))
        consumed = reopened.release_after_settlement(self.binding, inventory_sha256=frozen["inventory_sha256"],
                                                    consumption=self.consumption)
        self.assertEqual(self.consumption, consumed["consumption"])
        self.assertEqual(consumed, reopened.release_after_settlement(
            self.binding, inventory_sha256=frozen["inventory_sha256"], consumption=self.consumption))
        self.assertIsNone(reopened.inspect())
        self.assertEqual(consumed, reopened.read_archived(self.binding))
        journal.assert_no_unfinished_operator_journal(self.root)

    def test_exact_fresh_binding_rejects_request_source_receipt_runtime_and_signer_drift(self):
        self.journal.prepare(self.binding)
        before = self.journal.path.read_bytes()
        for field, value in (
                ("request_id", "operator-test-2"), ("source_revision", digest("different source")),
                ("receipt_sha256", digest("different receipt")), ("company_id", "COMP-0001")):
            with self.subTest(field=field):
                claims = {**self.claims, field: value}
                authorization = {**self.authorization, "claims_digest": digest(claims)}
                binding = journal.operator_journal_binding(claims, self.runtime, authorization)
                with self.assertRaisesRegex(ValueError, "binding_changed"):
                    self.journal.prepare(binding)
        runtime = {**self.runtime, "state": "COMPLETE", "release_id": "REL-updated"}
        claims = {**self.claims, "runtime_sha256": digest(runtime)}
        authorization = {**self.authorization, "claims_digest": digest(claims)}
        with self.assertRaisesRegex(ValueError, "binding_changed"):
            self.journal.claim_fetch(journal.operator_journal_binding(claims, runtime, authorization))
        with self.assertRaisesRegex(ValueError, "runtime_invalid"):
            journal.operator_journal_binding(self.claims, runtime, self.authorization)
        with self.assertRaisesRegex(ValueError, "binding_changed"):
            self.journal.read(journal.operator_journal_binding(
                self.claims, self.runtime, {**self.authorization, "key_id": "other-signer"}))
        with self.assertRaisesRegex(ValueError, "authorization_invalid"):
            journal.operator_journal_binding(
                self.claims, self.runtime, {**self.authorization, "claims_digest": digest("not these claims")})
        self.assertEqual(before, self.journal.path.read_bytes())

    def test_before_atomic_claim_publication_no_fetch_can_be_authorized(self):
        self.journal.prepare(self.binding)
        with patch.object(journal.os, "replace", side_effect=OSError("injected before replacement")):
            with self.assertRaises(OSError):
                self.journal.claim_fetch(self.binding)
        self.assertEqual(journal.PREPARED, self.journal.read(self.binding)["state"])
        with self.assertRaisesRegex(ValueError, "not_frozen"):
            self.journal.recover_inventory(self.binding)
        self.assertIsInstance(self.journal.claim_fetch(self.binding), str)

    def test_failure_after_claim_replacement_remains_held(self):
        self.journal.prepare(self.binding)
        with patch.object(journal, "_sync_parent", side_effect=OSError("injected directory fsync")):
            with self.assertRaises(OSError):
                self.journal.claim_fetch(self.binding)
        reopened = journal.RetainedOperatorJournal(self.root)
        self.assertEqual(journal.FETCH_CLAIMED, reopened.read(self.binding)["state"])
        with self.assertRaisesRegex(ValueError, "fetch_ambiguous"):
            reopened.recover_inventory(self.binding)
        with self.assertRaisesRegex(ValueError, "settlement_binding_changed"):
            reopened.record_settlement(self.binding, inventory_sha256=digest(_FETCH), evidence=self.evidence)
        with self.assertRaisesRegex(ValueError, "holds_normal_lifecycle"):
            journal.assert_no_unfinished_operator_journal(self.root)

    def test_freeze_write_failure_keeps_claim_and_does_not_publish_bad_payload(self):
        self.journal.prepare(self.binding)
        token = self.journal.claim_fetch(self.binding)
        before = self.journal.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "inventory_invalid"):
            self.journal.freeze_inventory(self.binding, token, dict(_FETCH, unnormalized=("tuple",)))
        with patch.object(journal.os, "replace", side_effect=OSError("injected before replacement")):
            with self.assertRaises(OSError):
                self.journal.freeze_inventory(self.binding, token, _FETCH)
        self.assertEqual(before, self.journal.path.read_bytes())
        with self.assertRaisesRegex(ValueError, "fetch_ambiguous"):
            self.journal.recover_inventory(self.binding)
        with self.assertRaisesRegex(ValueError, "already_claimed"):
            self.journal.claim_fetch(self.binding)

    def test_corrupt_noncanonical_and_unsafe_journal_fail_closed(self):
        self.journal.prepare(self.binding)
        original = self.journal.path.read_bytes()
        bad_contents = [
            b'{"incomplete":',
            b' ' + original,
            original.replace(b"operator-test-1", b"operator-test-2"),
            original.replace(b'"inventory":null', b'"inventory":[]'),
        ]
        for broken in bad_contents:
            with self.subTest(broken=broken[:30]):
                self.journal.path.write_bytes(broken)
                with self.assertRaisesRegex(ValueError, "corrupt"):
                    self.journal.prepare(self.binding)
                with self.assertRaisesRegex(ValueError, "corrupt"):
                    journal.assert_no_unfinished_operator_journal(self.root)
                self.assertEqual(broken, self.journal.path.read_bytes())
        self.journal.path.write_bytes(original)
        self.journal.path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "corrupt"):
            journal.assert_no_unfinished_operator_journal(self.root)
        self.journal.path.unlink()
        unrelated = self.root / "unrelated"
        unrelated.write_bytes(original)
        unrelated.chmod(0o600)
        self.journal.path.symlink_to(unrelated)
        with self.assertRaisesRegex(ValueError, "unreadable"):
            journal.assert_no_unfinished_operator_journal(self.root)

    def test_record_is_detached_from_mutable_caller_data(self):
        original = copy.deepcopy(self.binding)
        self.journal.prepare(self.binding)
        self.binding["claims"]["request_id"] = "changed"
        self.assertEqual(original, self.journal.read(original)["binding"])

    def test_crash_after_consuming_request_reopens_verified_terminal_without_refetch(self):
        request = self.root / "next-scan.json"
        request.write_text('{"synthetic":true}')
        self.journal.prepare(self.binding)
        token = self.journal.claim_fetch(self.binding)
        frozen = self.journal.freeze_inventory(self.binding, token, _FETCH)
        inventory_sha256 = frozen["inventory_sha256"]
        with patch.object(journal, "_sync_parent", side_effect=OSError("lost settlement acknowledgement")):
            with self.assertRaises(OSError):
                self.journal.record_settlement(self.binding, inventory_sha256=inventory_sha256,
                                               evidence=self.evidence)
        settled_after_retry = self.journal.record_settlement(
            self.binding, inventory_sha256=inventory_sha256, evidence=self.evidence)
        request.unlink()

        reopened = journal.RetainedOperatorJournal(self.root)
        inspected = reopened.inspect()
        self.assertEqual(settled_after_retry, inspected)
        self.assertEqual(self.binding, inspected["binding"])
        self.assertEqual(journal.SETTLED, inspected["state"])
        self.assertEqual(self.evidence, inspected["settlement_evidence"])
        self.assertIsNone(inspected["consumption"])
        self.assertEqual(inspected, reopened.record_settlement(
            self.binding, inventory_sha256=inventory_sha256, evidence=self.evidence))
        with self.assertRaisesRegex(ValueError, "evidence_changed"):
            reopened.record_settlement(self.binding, inventory_sha256=inventory_sha256,
                                       evidence=dict(self.evidence, state="other"))
        with self.assertRaisesRegex(ValueError, "already_claimed"):
            reopened.claim_fetch(self.binding)
        with self.assertRaisesRegex(ValueError, "holds_normal_lifecycle"):
            journal.assert_no_unfinished_operator_journal(self.root)
        with patch.object(journal, "_sync_parent", side_effect=OSError("lost consumption acknowledgement")):
            with self.assertRaises(OSError):
                reopened.release_after_settlement(self.binding, inventory_sha256=inventory_sha256,
                                                  consumption=self.consumption)
        terminal = reopened.inspect()
        self.assertEqual(self.consumption, terminal["consumption"])
        self.assertEqual(terminal, reopened.release_after_settlement(
            self.binding, inventory_sha256=inventory_sha256, consumption=self.consumption))
        journal.assert_no_unfinished_operator_journal(self.root)

    def settled_record(self):
        self.journal.prepare(self.binding)
        token = self.journal.claim_fetch(self.binding)
        frozen = self.journal.freeze_inventory(self.binding, token, _FETCH)
        return self.journal.record_settlement(
            self.binding, inventory_sha256=frozen["inventory_sha256"], evidence=self.evidence)

    def fresh_binding(self):
        claims = dict(self.claims, request_id="operator-test-2", request_sha256=digest("new request"))
        authorization = dict(self.authorization, claims_digest=digest(claims))
        return journal.operator_journal_binding(claims, self.runtime, authorization)

    def test_archive_only_consumed_records_and_preserves_old_replay_during_new_admission(self):
        self.journal.prepare(self.binding)
        with self.assertRaisesRegex(ValueError, "archive_requires_consumption"):
            self.journal.archive_completed(self.binding)
        settled = self.settled_record()
        with self.assertRaisesRegex(ValueError, "archive_requires_consumption"):
            self.journal.archive_completed(self.binding)
        self.assertFalse(self.journal.archive_directory.exists())
        inventory_sha256 = settled["inventory_sha256"]
        archived = self.journal.release_after_settlement(
            self.binding, inventory_sha256=inventory_sha256, consumption=self.consumption)
        self.assertIsNone(self.journal.inspect())
        paths = list(self.journal.archive_directory.iterdir())
        self.assertEqual([f"{self.claims['request_sha256']}-{self.binding['reservation_digest']}.json"],
                         [path.name for path in paths])
        before = paths[0].read_bytes()
        fresh = self.fresh_binding()
        self.assertIsNone(self.journal.read(fresh))
        self.assertEqual(journal.PREPARED, self.journal.prepare(fresh)["state"])
        self.assertEqual(archived, self.journal.read(self.binding))
        self.assertEqual(archived, self.journal.release_after_settlement(
            self.binding, inventory_sha256=inventory_sha256, consumption=self.consumption))
        self.assertEqual(fresh, self.journal.inspect()["binding"])
        self.assertEqual(before, paths[0].read_bytes())
        with self.assertRaisesRegex(ValueError, "already_claimed"):
            self.journal.claim_fetch(self.binding)
        resigned = journal.operator_journal_binding(
            self.claims, self.runtime, dict(self.authorization, key_id="different signer"))
        with self.assertRaisesRegex(ValueError, "archive_binding_changed"):
            self.journal.prepare(resigned)

    def test_archive_write_failure_leaves_consumed_active_for_idempotent_rotation(self):
        settled = self.settled_record()
        write_record = journal._write_record

        def fail_archive(path, record):
            if path.parent == self.journal.archive_directory:
                raise OSError("interrupted before archive publication")
            return write_record(path, record)

        with patch.object(journal, "_write_record", side_effect=fail_archive):
            with self.assertRaises(OSError):
                self.journal.release_after_settlement(
                    self.binding, inventory_sha256=settled["inventory_sha256"], consumption=self.consumption)
        expected = self.journal.inspect()
        self.assertEqual(self.consumption, expected["consumption"])
        self.assertIsNone(self.journal.read_archived(self.binding))
        fresh = self.fresh_binding()
        self.assertIsNone(self.journal.read(fresh))
        self.assertEqual(journal.PREPARED, self.journal.prepare(fresh)["state"])
        self.assertEqual(expected, self.journal.read_archived(self.binding))

    def test_archive_before_unlink_and_lost_unlink_acknowledgement_recover(self):
        settled = self.settled_record()
        inventory_sha256 = settled["inventory_sha256"]
        with patch.object(Path, "unlink", side_effect=OSError("interrupted after archive publication")):
            with self.assertRaises(OSError):
                self.journal.release_after_settlement(
                    self.binding, inventory_sha256=inventory_sha256, consumption=self.consumption)
        archived = self.journal.read_archived(self.binding)
        self.assertEqual(archived, self.journal.inspect())
        sync_parent = journal._sync_parent

        def lose_unlink_ack(path):
            if path == self.journal.path and not path.exists():
                raise OSError("lost active unlink acknowledgement")
            return sync_parent(path)

        with patch.object(journal, "_sync_parent", side_effect=lose_unlink_ack):
            with self.assertRaises(OSError):
                self.journal.archive_completed(self.binding)
        self.assertIsNone(self.journal.inspect())
        self.assertEqual(archived, self.journal.archive_completed(self.binding))
        self.assertEqual(archived, self.journal.read(self.binding))

    def test_corrupt_archive_keeps_active_evidence_and_refuses_replacement(self):
        settled = self.settled_record()
        inventory_sha256 = settled["inventory_sha256"]
        with patch.object(Path, "unlink", side_effect=OSError("interrupted after archive publication")):
            with self.assertRaises(OSError):
                self.journal.release_after_settlement(
                    self.binding, inventory_sha256=inventory_sha256, consumption=self.consumption)
        active = self.journal.path.read_bytes()
        archive, = self.journal.archive_directory.iterdir()
        archive.write_text('{"corrupt":true}')
        with self.assertRaisesRegex(ValueError, "corrupt"):
            self.journal.read_archived(self.binding)
        with self.assertRaisesRegex(ValueError, "corrupt"):
            self.journal.prepare(self.fresh_binding())
        self.assertEqual(active, self.journal.path.read_bytes())
        self.assertEqual('{"corrupt":true}', archive.read_text())

    def test_verified_ed25519_receipt_can_bind_the_actual_claim_schema(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        from job_search_helper.retained_operator_authorization import verify_operator_membership_authorization
        from job_search_helper.selected_recovery_authorization import Ed25519AuthorizationVerifier, canonical

        signer = Ed25519PrivateKey.generate()
        key = signer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        envelope = {"key_id": "fixture", "payload": self.claims, "signature": base64.b64encode(
            signer.sign(canonical(self.claims))).decode("ascii")}
        authorization = verify_operator_membership_authorization(
            envelope, self.claims, Ed25519AuthorizationVerifier({"fixture": key}),
            now=datetime(2026, 11, 20, 18, tzinfo=timezone.utc))
        binding = journal.operator_journal_binding(self.claims, self.runtime, authorization)
        self.assertEqual(binding, self.journal.prepare(binding)["binding"])

    def test_process_death_reopens_only_the_recorded_provider_state(self):
        child = """
import fcntl, json, pathlib, sys
from job_search_helper.retained_operator_journal import RetainedOperatorJournal
root = pathlib.Path(sys.argv[1])
binding, inventory, freeze = json.loads(sys.stdin.readline())
with (root / 'scraper.lock').open('a') as lease:
    fcntl.flock(lease, fcntl.LOCK_EX)
    current = RetainedOperatorJournal(root)
    current.prepare(binding)
    claim = current.claim_fetch(binding)
    (root / 'synthetic-provider-call').write_text('one')
    if freeze:
        current.freeze_inventory(binding, claim, inventory)
    print('ready', flush=True)
    sys.stdin.readline()
"""
        for freeze in (False, True):
            with self.subTest(frozen=freeze), tempfile.TemporaryDirectory(dir=self.root) as root:
                proc = subprocess.Popen([sys.executable, "-B", "-c", child, root],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True)
                try:
                    proc.stdin.write(json.dumps([self.binding, _FETCH, freeze]) + "\n")
                    proc.stdin.flush()
                    self.assertTrue(select.select([proc.stdout], [], [], 10)[0])
                    self.assertEqual("ready", proc.stdout.readline().strip())
                finally:
                    proc.kill()
                    _, stderr = proc.communicate(timeout=10)
                self.assertEqual("", stderr)
                self.assertEqual("one", (Path(root) / "synthetic-provider-call").read_text())
                reopened = journal.RetainedOperatorJournal(root)
                with self.assertRaisesRegex(ValueError, "already_claimed"):
                    reopened.claim_fetch(self.binding)
                if freeze:
                    self.assertEqual(_FETCH, reopened.recover_inventory(self.binding))
                else:
                    with self.assertRaisesRegex(ValueError, "fetch_ambiguous"):
                        reopened.recover_inventory(self.binding)
                with self.assertRaisesRegex(ValueError, "holds_normal_lifecycle"):
                    journal.assert_no_unfinished_operator_journal(root)
