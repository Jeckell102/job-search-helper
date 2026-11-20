"""Offline containment tests for the retained Company-event entry point."""
from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from job_search_helper import retained_company_event as subject


class RetainedCompanyEventTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ro, self.local, self.remote = MagicMock(), MagicMock(), MagicMock()
        self.prepared = MagicMock()
        self.prepared.admission = {"reservation_digest": "r"}
        self.prepared.snapshot = {"request": {"mode": "company-only", "request_id": "company-event:E",
            "company_ids": ["COMP-NEW"], "source_revision": "S", "enqueued_at": "2026-01-01T00:00:00Z",
            "start_last": [], "company_event": {"event_id": "E", "company_id": "COMP-NEW", "revision": 1,
            "source_revision": "S", "schema": "company-event-scan-request-v1"}}}
        self.result = {"publication": {"state": "FIRST_PASS_RELEASED", "settlement": {"settled": True}},
                       "company_id": "COMP-NEW", "reservation_digest": "r"}
        self.state = MagicMock(); self.state.cycles.return_value = [{"id": "CYC-OLD", "status": "In Progress"}]

    def _patches(self, *, journal=False):
        return [
            patch("job_search_helper.cli.scraper_lock_name", return_value="scraper.lock"),
            patch("job_search_helper.cli.writer_lock", return_value=nullcontext()),
            patch("job_search_helper.integration_release.assert_release_settled"),
            patch("job_search_helper.retained_work_runner.assert_normal_lifecycle_not_held"),
            patch("job_search_helper.engine.State", return_value=self.state),
            patch("job_search_helper.retained_work_exception._active_record", return_value={"manifest": {"cycle_id": "CYC-OLD"}}),
            patch("job_search_helper.retained_work_runner.recover_prepared_exceptional_start",
                  side_effect=ValueError("retained_runner_recovery_journal_missing") if not journal else [self.prepared]),
            patch("job_search_helper.retained_work_runner.prepare_exceptional_start", return_value=self.prepared),
            patch("job_search_helper.retained_work_runner.commit_exceptional_start"),
            patch("job_search_helper.retained_session_store.RetainedSessionStore"),
            patch("job_search_helper.engine.Engine", return_value=MagicMock()),
            patch("job_search_helper.retained_work_orchestrator.run_retained_reservation", return_value=self.result),
        ]

    def _request(self, suffix="E"):
        return {"mode": "company-only", "request_id": "company-event:" + suffix,
                "company_ids": ["COMP-NEW"], "source_revision": "S",
                "enqueued_at": "2026-01-01T00:00:00Z", "start_last": [],
                "company_event": {"event_id": suffix, "company_id": "COMP-NEW",
                "revision": 1, "source_revision": "S",
                "schema": "company-event-scan-request-v1"}}

    def _archive(self, request):
        from job_search_helper.retained_work_runner import digest
        path = self.root / "company-event-bridge" / "consumed-requests" / (digest(request) + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(request, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        return path

    def _settled_proof(self, request, *, mutate_payload=None, publication=True):
        """Create the minimal exact durable admission/release proof."""
        from job_search_helper.retained_work_runner import digest
        event, company = request["company_event"], request["company_ids"][0]
        payload = {"request_id": request["request_id"], "event_id": event["event_id"],
                   "exception_cycle": "CYC-OLD", "company_id": company,
                   "manifest_digest": "M", "company_identity_digest": "I",
                   "request_digest": digest(request), "event_receipt_digest": "R",
                   "defer_sync": True}
        if mutate_payload: mutate_payload(payload)
        reservation = digest(payload)
        import sqlite3
        with sqlite3.connect(self.root / "retained-work-exceptions.sqlite3") as db:
            db.execute("CREATE TABLE retained_work_exceptions (cycle TEXT,manifest_digest TEXT,state TEXT)")
            db.execute("INSERT INTO retained_work_exceptions VALUES (?,?,?)", ("CYC-OLD", "M", "ACTIVE"))
            db.execute("CREATE TABLE retained_work_admissions (request_id TEXT,event_id TEXT,exception_cycle TEXT,company_id TEXT,manifest_digest TEXT,company_identity_digest TEXT,payload TEXT,payload_digest TEXT,state TEXT)")
            db.execute("INSERT INTO retained_work_admissions VALUES (?,?,?,?,?,?,?,?,?)",
                       (request["request_id"], event["event_id"], "CYC-OLD", company, "M", "I",
                        json.dumps(payload, sort_keys=True, separators=(",", ":")), reservation, "FROZEN"))
        with sqlite3.connect(self.root / "jobs.sqlite3") as db:
            db.execute("CREATE TABLE retained_publications (reservation_digest TEXT,request_id TEXT,event_id TEXT,exception_cycle TEXT,company TEXT,manifest_digest TEXT,queue_evidence TEXT,queue_evidence_digest TEXT,state TEXT)")
            if publication:
                evidence = {"reservation_digest": reservation, "queue": [], "files": {}}
                db.execute("INSERT INTO retained_publications VALUES (?,?,?,?,?,?,?,?,?)",
                           (reservation, request["request_id"], event["event_id"], "CYC-OLD", company,
                            "M", json.dumps(evidence, sort_keys=True, separators=(",", ":")),
                            digest(evidence), "FIRST_PASS_RELEASED"))
        return reservation

    def test_happy_path_is_one_retained_reservation_without_normal_lifecycle(self):
        patches = self._patches()
        with patches[0] as lock, patches[1], patches[2], patches[3] as lifecycle, patches[4], patches[5], patches[6], patches[7] as prepare, patches[8] as commit, patches[9], patches[10], patches[11] as run:
            outcome = subject.run_retained_company_event(
                state_directory=self.root, local_factory=lambda readonly: self.ro if readonly else self.local,
                remote_factory=lambda: self.remote, verifier=object(), fetcher=object())
        self.assertEqual("FIRST_PASS_RELEASED", outcome["state"])
        self.assertEqual("COMP-NEW", outcome["company_id"])
        lifecycle.assert_called_once(); prepare.assert_called_once(); commit.assert_called_once(); run.assert_called_once()
        self.assertEqual(2, lock.call_count)  # early recovery + final consume
        self.ro.close.assert_called_once(); self.local.close.assert_called_once()

    def test_frozen_start_recovers_without_refetch_or_new_commit(self):
        (self.root / "retained-work-starts.sqlite3").touch()
        patches = self._patches(journal=True)
        with patches[0], patches[1], patches[2], patches[3] as lifecycle, patches[4], patches[5], patches[6], patches[7] as prepare, patches[8] as commit, patches[9], patches[10], patches[11]:
            result = subject.run_retained_company_event(
                state_directory=self.root, local_factory=lambda readonly: self.ro if readonly else self.local,
                remote_factory=lambda: self.remote, verifier=object(), fetcher=object())
        self.assertTrue(result["recovered"]); lifecycle.assert_not_called(); prepare.assert_not_called(); commit.assert_not_called()

    def test_multiple_or_changed_blockers_fail_before_local_or_remote_factories(self):
        self.state.cycles.return_value = [{"id": "CYC-OLD", "status": "In Progress"}, {"id": "CYC-OTHER", "status": "In Progress"}]
        local_factory = MagicMock()
        patches = self._patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], self.assertRaisesRegex(ValueError, "blocker_scope"):
            subject.run_retained_company_event(state_directory=self.root, local_factory=local_factory,
                                               remote_factory=MagicMock(), verifier=object(), fetcher=object())
        local_factory.assert_not_called()

    def test_preflight_admission_drift_never_constructs_remote_or_publisher(self):
        patches = self._patches()
        remote_factory = MagicMock()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch("job_search_helper.retained_work_runner.prepare_exceptional_start", side_effect=ValueError("retained_exception_company_revision_changed")), self.assertRaisesRegex(ValueError, "revision"):
            subject.run_retained_company_event(state_directory=self.root,
                local_factory=lambda readonly: self.ro if readonly else self.local,
                remote_factory=remote_factory, verifier=object(), fetcher=object())
        remote_factory.assert_not_called(); self.local.close.assert_not_called()

    def test_invalid_key_material_fails_closed_without_factory(self):
        with self.assertRaisesRegex(ValueError, "public_key"):
            subject._verifier("reviewer", "not-base64")

    def test_unsettled_publication_is_not_reported_as_completed(self):
        self.result["publication"]["state"] = "SYNC_PENDING"
        patches = self._patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11]:
            result = subject.run_retained_company_event(state_directory=self.root,
                local_factory=lambda readonly: self.ro if readonly else self.local,
                remote_factory=lambda: self.remote, verifier=object(), fetcher=object())
        self.assertEqual("SYNC_PENDING", result["state"])

    def test_recovery_after_unlink_writes_receipt_without_factories(self):
        request = self._request(); self._archive(request); self._settled_proof(request)
        self.assertEqual("FIRST_PASS_RELEASED", subject.run_retained_company_event(
            state_directory=self.root, local_factory=MagicMock(), remote_factory=MagicMock(),
            verifier=object(), fetcher=object())["state"])
        self.assertFalse((self.root / "next-scan.json").exists())
        self.assertTrue(list((self.root / "company-event-bridge" / "consumption-receipts").glob("*.json")))

    def test_recovery_preserves_differing_newer_request_and_receipts_old(self):
        old, newer = self._request("E"), self._request("NEW")
        self._archive(old); self._settled_proof(old)
        (self.root / "next-scan.json").write_text(json.dumps(newer), encoding="utf-8")
        result = subject._recover_settled_consumption(self.root)
        self.assertEqual("FIRST_PASS_RELEASED_CONSUMED", result["consumption"]["state"])
        self.assertEqual(newer, json.loads((self.root / "next-scan.json").read_text(encoding="utf-8")))

    def test_recovery_refuses_forged_archive_with_same_ids_but_changed_fields(self):
        request = self._request(); forged = dict(request); forged["source_revision"] = "FORGED"
        forged["company_event"] = dict(request["company_event"], source_revision="FORGED")
        self._archive(forged); self._settled_proof(request)
        with self.assertRaisesRegex(ValueError, "admission_changed"):
            subject._recover_settled_consumption(self.root)

    def test_recovery_requires_valid_archive_digest_admission_and_release(self):
        request = self._request(); path = self._archive(request); self._settled_proof(request)
        path.rename(path.with_name("not-the-request-digest.json"))
        with self.assertRaisesRegex(ValueError, "archive_corrupt"):
            subject._recover_settled_consumption(self.root)
        # A valid archive still cannot consume without durable FIRST PASS proof.
        (self.root / "retained-work-exceptions.sqlite3").unlink()
        (self.root / "jobs.sqlite3").unlink()
        path.with_name("not-the-request-digest.json").unlink()
        request = self._request("NO-PASS"); self._archive(request); self._settled_proof(request, publication=False)
        with self.assertRaisesRegex(ValueError, "release_missing"):
            subject._recover_settled_consumption(self.root)

    def test_recovery_rejects_admission_payload_digest_or_event_drift(self):
        request = self._request(); self._archive(request); self._settled_proof(request)
        import sqlite3
        with sqlite3.connect(self.root / "retained-work-exceptions.sqlite3") as db:
            db.execute("UPDATE retained_work_admissions SET payload_digest='forged'")
        with self.assertRaisesRegex(ValueError, "admission_changed"):
            subject._recover_settled_consumption(self.root)

    def test_recovery_rejects_admission_event_drift_and_bad_completed_receipt(self):
        request = self._request(); self._archive(request); self._settled_proof(request)
        import sqlite3
        with sqlite3.connect(self.root / "retained-work-exceptions.sqlite3") as db:
            db.execute("UPDATE retained_work_admissions SET event_id='other-event'")
        with self.assertRaisesRegex(ValueError, "admission_changed"):
            subject._recover_settled_consumption(self.root)
        # A receipt is itself immutable audit evidence; a corrupted completed
        # archive must hold rather than be silently ignored.
        root = Path(tempfile.mkdtemp()); self.addCleanup(lambda: __import__("shutil").rmtree(root))
        request = self._request("RECEIPT")
        subject._consume_request(root, request)
        receipt = next((root / "company-event-bridge" / "consumption-receipts").glob("*.json"))
        receipt.write_text('{"state":"forged"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "receipt_changed"):
            subject._recover_settled_consumption(root)

    def test_completed_archives_are_ignored_but_multiple_pending_are_held(self):
        completed = self._request(); subject._consume_request(self.root, completed)
        self.assertIsNone(subject._recover_settled_consumption(self.root))
        self._archive(self._request("ONE")); self._archive(self._request("TWO"))
        with self.assertRaisesRegex(ValueError, "archive_ambiguous"):
            subject._recover_settled_consumption(self.root)

    def test_consume_crash_after_archive_or_after_unlink_converges_idempotently(self):
        request = self._request()
        # Archive-before-unlink is a safe retry: it removes only the exact current request.
        self._archive(request)
        (self.root / "next-scan.json").write_text(json.dumps(request), encoding="utf-8")
        result = subject._consume_request(self.root, request)
        self.assertEqual("FIRST_PASS_RELEASED_CONSUMED", result["state"])
        # This is the post-unlink/pre-receipt shape; retry writes just the receipt.
        receipt = next((self.root / "company-event-bridge" / "consumption-receipts").glob("*.json"))
        receipt.unlink()
        self.assertEqual(result, subject._consume_request(self.root, request))
        self.assertEqual(result, subject._consume_request(self.root, request))

    def test_consume_receipt_write_failure_after_unlink_converges_on_retry(self):
        request = self._request()
        (self.root / "next-scan.json").write_text(json.dumps(request), encoding="utf-8")
        real_replace = __import__("os").replace
        def fail_receipt(source, destination):
            if "consumption-receipts" in str(destination):
                raise OSError("simulated receipt crash")
            return real_replace(source, destination)
        with patch("job_search_helper.retained_company_event.os.replace", side_effect=fail_receipt):
            with self.assertRaisesRegex(OSError, "receipt crash"):
                subject._consume_request(self.root, request)
        self.assertFalse((self.root / "next-scan.json").exists())
        self.assertEqual("FIRST_PASS_RELEASED_CONSUMED", subject._consume_request(self.root, request)["state"])

    def test_first_pass_string_without_settlement_never_consumes_request(self):
        self.result["publication"] = {"state": "FIRST_PASS_RELEASED"}
        patches = self._patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], self.assertRaisesRegex(ValueError, "publication_unsettled"):
            subject.run_retained_company_event(state_directory=self.root,
                local_factory=lambda readonly: self.ro if readonly else self.local,
                remote_factory=lambda: self.remote, verifier=object(), fetcher=object())

    def test_real_flock_is_not_nested_by_event_entrypoint(self):
        """Old outer-lock implementation raises WriterLockBusy in this commit hook."""
        from job_search_helper.cli import writer_lock
        patches = self._patches()
        def commit_with_real_lock(*args, **kwargs):
            with writer_lock(self.root / "scraper.lock"):
                pass
        with patches[0], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], \
                patch("job_search_helper.retained_work_runner.commit_exceptional_start", side_effect=commit_with_real_lock), \
                patches[9], patches[10], patches[11]:
            result = subject.run_retained_company_event(
                state_directory=self.root, local_factory=lambda readonly: self.ro if readonly else self.local,
                remote_factory=lambda: self.remote, verifier=object(), fetcher=object())
        self.assertEqual("FIRST_PASS_RELEASED", result["state"])

    def test_activation_lock_contention_fails_before_any_state_or_store_write(self):
        from job_search_helper.cli import WriterLockBusy, writer_lock
        with patch("job_search_helper.cli.scraper_lock_name", return_value="scraper.lock"):
            with writer_lock(self.root / "scraper.lock"):
                with self.assertRaises(WriterLockBusy):
                    subject.activate_signed_exception(
                        state_directory=self.root, cycle_id="CYC-OLD",
                        approval={"manifest": {}, "envelope": {}}, verifier=object())
        self.assertFalse((self.root / "retained-work-exceptions.sqlite3").exists())


if __name__ == "__main__": unittest.main()
