import json
from pathlib import Path
import sqlite3
import stat
import tempfile
import threading
import unittest
from datetime import datetime, timezone

from job_search_helper.retained_work_exception import (
    RetainedWorkExceptionStore, activate_exception,
    admit_disjoint_company_request, build_manifest, digest, required_claims,
    revalidate_manifest,
)
from job_search_helper.selected_recovery_authorization import TestAuthorizationVerifier


CYCLE = "CYC-OLD"
OLD = "COMP-OLD"
NEW = "COMP-NEW"
NOW = "2026-11-19T20:00:00+00:00"
EXPIRES = "2026-11-19T21:00:00+00:00"


class RetainedWorkExceptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inbox = self.root / "inventories.sqlite3"
        self.jobs = self.root / "jobs.sqlite3"
        self.store_path = self.root / "retained-work-exceptions.sqlite3"
        with sqlite3.connect(self.inbox) as db:
            db.execute("CREATE TABLE destination(id TEXT NOT NULL)")
            db.execute("INSERT INTO destination VALUES ('sheet-1')")
            db.execute("CREATE TABLE inventories(cycle TEXT,company TEXT,payload TEXT,blocked INTEGER)")
            db.execute("CREATE TABLE sync_plans(cycle TEXT,company TEXT,payload TEXT,cursor INTEGER)")
            db.execute("CREATE TABLE exact_sync_chunks(cycle TEXT,company TEXT,cursor INTEGER,count INTEGER,digest TEXT,state TEXT)")
            db.execute("CREATE TABLE exact_remote_plans(cycle TEXT,company TEXT,receipt_id TEXT,state TEXT)")
            db.execute("CREATE TABLE publication_receipts(receipt_id TEXT,binding TEXT,records TEXT,schedule TEXT,state TEXT,acknowledgement_id TEXT,created_at TEXT,updated_at TEXT)")
            db.execute("INSERT INTO inventories VALUES (?,?,?,0)",
                       (CYCLE, OLD, json.dumps({"jobs": [{"id": "one"}]})))
            db.execute("INSERT INTO sync_plans VALUES (?,?,?,67)",
                       (CYCLE, OLD, json.dumps({"operations": [{"tab": "Job History"}] * 208})))
            db.execute("INSERT INTO exact_sync_chunks VALUES (?,?,?,?,?,?)",
                       (CYCLE, OLD, 0, 67, "a" * 64, "CONFIRMED"))
            db.execute("INSERT INTO exact_remote_plans VALUES (?,?,?,?)",
                       (CYCLE, OLD, "r-1", "SYNC_PENDING"))
            db.execute("INSERT INTO publication_receipts VALUES (?,?,?,?,?,?,?,?)",
                       ("r-1", json.dumps({"cycle_id": CYCLE, "company_id": OLD}),
                        "[]", "{}", "LOCAL_COMMITTED", None, NOW, NOW))
        with sqlite3.connect(self.jobs) as db:
            db.execute("CREATE TABLE dirty(tab TEXT,row_id INTEGER,header TEXT)")
            db.execute("CREATE TABLE exact_local_applications(apply_id TEXT,cycle TEXT,company TEXT,plan_digest TEXT,inventory_payload_digest TEXT,local_operations_digest TEXT,remote_projection_digest TEXT,row_scope TEXT,created_at TEXT,verified_at TEXT,state TEXT)")
            db.execute("CREATE TABLE exact_local_acknowledgements(acknowledgement_id TEXT,apply_id TEXT,receipt_id TEXT,selected_fields_digest TEXT,created_at TEXT)")
            db.execute("CREATE TABLE exact_local_apply_chunks(apply_id TEXT,start_cursor INTEGER,operation_count INTEGER,operations_digest TEXT,state TEXT)")
            db.execute("INSERT INTO exact_local_applications VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       ("apply-1", CYCLE, OLD, "p", "i", "l", "r", "[]", NOW, NOW, "VERIFIED"))
            db.execute("INSERT INTO exact_local_acknowledgements VALUES (?,?,?,?,?)",
                       ("ack-1", "apply-1", "r-1", "s", NOW))
            db.execute("INSERT INTO exact_local_apply_chunks VALUES (?,?,?,?,?)",
                       ("apply-1", 0, 67, "chunk", "VERIFIED"))
        self.cycle = {"id": CYCLE, "status": "In Progress", "companies": {
            OLD: {"stage": "inventory", "company": "Old Company",
                  "requested_url": "https://jobs.example.com/old",
                  "source_url": "https://api.example.com/old"},
            "COMP-QUEUED": {"stage": "queued", "company": "Queued Company"}}}
        self.manifest = build_manifest(self.cycle, self.inbox, self.jobs,
                                       reason="historical containment", created_at=NOW)
        self.verifier = TestAuthorizationVerifier()

    def tearDown(self):
        self.temp.cleanup()

    def request(self, company=NEW):
        return {"mode": "company-only", "request_id": "company-event:event-1",
                "company_ids": [company],
                "source_revision": "rev-1",
                "company_event": {"schema": "company-event-scan-request-v1",
                                  "event_id": "event-1", "company_id": company,
                                  "revision": 1, "source_revision": "rev-1"}}

    def receipt(self, request=None):
        request = request or self.request()
        event = request["company_event"]
        return {"schema": "company-event-scan-request-v1",
                "event_id": event["event_id"], "company_id": event["company_id"],
                "revision": event["revision"],
                "source_revision": event["source_revision"],
                "state": "REQUEST_WRITTEN",
                "request_sha256": digest(request)}

    def company(self, company=NEW, *, name="New Company",
                url="https://jobs.example.com/new",
                source_url="https://api.new-example.com/board/new",
                ats="ExampleATS"):
        return {"company_id": company, "company_name": name,
                "official_careers_url": url, "source_url": source_url,
                "ats": ats, "source_revision": "rev-1",
                "company_status": "Active", "claimed_by": "", "claim_token": ""}

    def envelope(self, manifest=None):
        claims = required_claims(manifest or self.manifest, expires_at=EXPIRES)
        return self.verifier.issue(claims)

    def activate(self):
        return activate_exception(
            self.manifest, self.envelope(), self.verifier, self.store_path,
            now=datetime(2026, 11, 19, 20, 30, tzinfo=timezone.utc),
            allow_test_verifier=True)

    def admit(self, request=None, *, company=None, receipt=None,
              blockers=None, operation="start-company-only", defer_sync=True,
              current_time=None):
        self.activate()
        request = request or self.request()
        return admit_disjoint_company_request(
            self.store_path, self.verifier, self.cycle, self.inbox, self.jobs,
            request, receipt or self.receipt(request), company or self.company(),
            blockers or [CYCLE], operation=operation, defer_sync=defer_sync,
            now=current_time or datetime(2026, 11, 19, 20, 30,
                                         tzinfo=timezone.utc),
            allow_test_verifier=True)

    def test_manifest_is_deterministic_and_read_only(self):
        before_inbox = self.inbox.read_bytes()
        before_jobs = self.jobs.read_bytes()
        again = build_manifest(self.cycle, self.inbox, self.jobs,
                               reason="historical containment", created_at=NOW)
        self.assertEqual(self.manifest, again)
        self.assertEqual(before_inbox, self.inbox.read_bytes())
        self.assertEqual(before_jobs, self.jobs.read_bytes())
        self.assertEqual(1, self.manifest["inventory_evidence"][
            "publication_receipts"]["row_count"])
        self.assertFalse(self.manifest["settlement_authorized"])
        self.assertFalse(self.manifest["publication_authorized"])

    def test_dirty_cells_refuse_manifest(self):
        with sqlite3.connect(self.jobs) as db:
            db.execute("INSERT INTO dirty VALUES ('Companies',1,'Last Checked')")
        with self.assertRaisesRegex(ValueError, "dirty_cells_present"):
            build_manifest(self.cycle, self.inbox, self.jobs,
                           reason="historical containment", created_at=NOW)

    def test_authorization_precedes_writable_store(self):
        called = []
        envelope = self.envelope()
        envelope["payload"] = dict(envelope["payload"], cycle_id="wrong")
        with self.assertRaises(ValueError):
            activate_exception(
                self.manifest, envelope, self.verifier,
                self.store_path,
                now=datetime(2026, 11, 19, 20, 30, tzinfo=timezone.utc),
                allow_test_verifier=True)
        self.assertEqual([], called)
        self.assertFalse(self.store_path.exists())

    def test_activation_is_immutable_idempotent_and_mode_0600(self):
        first = activate_exception(
            self.manifest, self.envelope(), self.verifier, self.store_path,
            now=datetime(2026, 11, 19, 20, 30, tzinfo=timezone.utc),
            allow_test_verifier=True)
        second = activate_exception(
            self.manifest, self.envelope(), self.verifier, self.store_path,
            now=datetime(2026, 11, 19, 20, 30, tzinfo=timezone.utc),
            allow_test_verifier=True)
        self.assertEqual(first, second)
        self.assertEqual(0o600, stat.S_IMODE(self.store_path.stat().st_mode))
        changed = dict(self.manifest, reason="different")
        changed["manifest_digest"] = self.manifest["manifest_digest"]
        with self.assertRaises(ValueError):
            activate_exception(
                changed, self.envelope(changed), self.verifier, self.store_path,
                now=datetime(2026, 11, 19, 20, 30, tzinfo=timezone.utc),
                allow_test_verifier=True)

    def test_concurrent_identical_activation_is_idempotent(self):
        envelope = self.envelope()
        barrier = threading.Barrier(2)
        results, errors = [], []

        def activate():
            try:
                barrier.wait()
                results.append(activate_exception(
                    self.manifest, envelope, self.verifier, self.store_path,
                    now=datetime(2026, 11, 19, 20, 30, tzinfo=timezone.utc),
                    allow_test_verifier=True))
            except BaseException as error:
                errors.append(error)

        threads = [threading.Thread(target=activate) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([], errors)
        self.assertEqual(2, len(results))
        self.assertEqual(results[0], results[1])

    def test_expired_authorization_refuses_before_store(self):
        with self.assertRaisesRegex(ValueError, "expired"):
            activate_exception(
                self.manifest, self.envelope(), self.verifier,
                self.store_path,
                now=datetime(2026, 11, 19, 22, 0, tzinfo=timezone.utc),
                allow_test_verifier=True)
        self.assertFalse(self.store_path.exists())

    def test_disjoint_company_only_request_is_admitted_without_settlement(self):
        result = self.admit()
        self.assertEqual([CYCLE], result["discounted_cycle_ids"])
        self.assertEqual(NEW, result["company_id"])
        self.assertFalse(result["settlement_authorized"])
        self.assertFalse(result["publication_authorized"])

    def test_unsigned_manifest_cannot_be_used_for_admission(self):
        with self.assertRaisesRegex(ValueError, "store_missing"):
            admit_disjoint_company_request(
                self.store_path, self.verifier, self.cycle, self.inbox, self.jobs,
                self.request(), self.receipt(), self.company(), [CYCLE],
                operation="start-company-only", defer_sync=True,
                now=datetime(2026, 11, 19, 20, 30, tzinfo=timezone.utc),
                allow_test_verifier=True)

    def test_forged_active_store_cannot_admit(self):
        self.activate()
        with sqlite3.connect(self.store_path) as db:
            envelope = json.loads(db.execute(
                "SELECT envelope FROM retained_work_exceptions WHERE cycle=?",
                (CYCLE,)).fetchone()[0])
            envelope["signature"] = "forged-signature"
            db.execute(
                "UPDATE retained_work_exceptions SET envelope=?,"
                "authorization_digest=? WHERE cycle=?",
                (json.dumps(envelope, sort_keys=True, separators=(",", ":")),
                 digest(envelope), CYCLE))
        with self.assertRaises(ValueError):
            admit_disjoint_company_request(
                self.store_path, self.verifier, self.cycle, self.inbox, self.jobs,
                self.request(), self.receipt(), self.company(), [CYCLE],
                operation="start-company-only", defer_sync=True,
                now=datetime(2026, 11, 19, 20, 30, tzinfo=timezone.utc),
                allow_test_verifier=True)

    def test_store_must_be_exact_and_colocated(self):
        wrong = self.root / "wrong.sqlite3"
        activate_exception(
            self.manifest, self.envelope(), self.verifier, wrong,
            now=datetime(2026, 11, 19, 20, 30, tzinfo=timezone.utc),
            allow_test_verifier=True)
        with self.assertRaisesRegex(ValueError, "store_path_invalid"):
            admit_disjoint_company_request(
                wrong, self.verifier, self.cycle, self.inbox, self.jobs,
                self.request(), self.receipt(), self.company(), [CYCLE],
                operation="start-company-only", defer_sync=True,
                now=datetime(2026, 11, 19, 20, 30, tzinfo=timezone.utc),
                allow_test_verifier=True)

    def test_global_run_synchronizer_is_forbidden(self):
        with self.assertRaisesRegex(ValueError, "deferred_sync_required"):
            self.admit(defer_sync=False)

    def test_overlap_and_broadened_request_refuse(self):
        with self.assertRaisesRegex(ValueError, "company_overlap"):
            old_request = self.request(OLD)
            self.admit(old_request, receipt=self.receipt(old_request),
                       company=self.company(OLD, name="Old Company",
                                            url="https://jobs.example.com/old"))
        widened = self.request()
        widened["company_ids"] = [NEW, "COMP-OTHER"]
        with self.assertRaisesRegex(ValueError, "request_invalid"):
            self.admit(widened, receipt=self.receipt(widened))

    def test_duplicate_employer_and_source_aliases_refuse(self):
        with self.assertRaisesRegex(ValueError, "company_alias"):
            self.admit(company=self.company(name=" Old   Company "))
        with self.assertRaisesRegex(ValueError, "source_alias"):
            self.admit(company=self.company(
                name="Different Name", url="https://jobs.example.com/old/"))
        with self.assertRaisesRegex(ValueError, "source_alias"):
            self.admit(company=self.company(
                name="Different Name", url="https://careers.example.net/new",
                source_url="HTTPS://API.EXAMPLE.COM:443/%6Fld?tracking=new"))

    def test_provider_board_alias_across_endpoint_aliases_refuses(self):
        cycle = json.loads(json.dumps(self.cycle))
        cycle["companies"][OLD].update({
            "ats": "Ashby",
            "requested_url": "https://careers.example.com/old",
            "source_url": "https://api.ashbyhq.com/posting-api/job-board/saronic?includeCompensation=true",
        })
        self.manifest = build_manifest(
            cycle, self.inbox, self.jobs,
            reason="historical containment", created_at=NOW)
        self.cycle = cycle
        with self.assertRaisesRegex(ValueError, "provider_alias"):
            self.admit(company=self.company(
                name="Different Name", url="https://careers.example.net/new",
                source_url="https://jobs.ashbyhq.com/saronic?utm_source=alias",
                ats="Ashby"))

    def test_full_scan_resume_sync_and_extra_blocker_refuse(self):
        self.activate()
        for operation in ("start-full", "resume", "sync"):
            with self.subTest(operation=operation), self.assertRaisesRegex(
                    ValueError, "operation_forbidden"):
                admit_disjoint_company_request(
                    self.store_path, self.verifier, self.cycle, self.inbox, self.jobs,
                    self.request(), self.receipt(), self.company(), [CYCLE],
                    operation=operation, defer_sync=True,
                    now=datetime(2026, 11, 19, 20, 30, tzinfo=timezone.utc),
                    allow_test_verifier=True)
        with self.assertRaisesRegex(ValueError, "blocker_scope_changed"):
            self.admit(blockers=[CYCLE, "CYC-OTHER"])

    def test_authorization_expiry_is_rechecked_at_admission(self):
        self.activate()
        with self.assertRaisesRegex(ValueError, "expired"):
            self.admit(current_time=datetime(2026, 11, 19, 22, 0,
                                             tzinfo=timezone.utc))

    def test_request_and_event_reuse_are_durable(self):
        first = self.admit()
        self.assertTrue(first["reservation_digest"])
        self.assertEqual(first, self.admit())
        changed = self.request("COMP-NEWER")
        changed["source_revision"] = "rev-2"
        changed["company_event"]["source_revision"] = "rev-2"
        changed_company = self.company("COMP-NEWER", name="Newer Company",
                                       url="https://jobs.example.com/newer")
        changed_company["source_revision"] = "rev-2"
        with self.assertRaisesRegex(ValueError, "request_reused"):
            self.admit(changed, receipt=self.receipt(changed),
                       company=changed_company)

        same_event_changed_company = self.request("COMP-THIRD")
        third_company = self.company(
            "COMP-THIRD", name="Third Company",
            url="https://jobs.example.com/third")
        with self.assertRaisesRegex(ValueError, "request_reused"):
            self.admit(same_event_changed_company,
                       receipt=self.receipt(same_event_changed_company),
                       company=third_company)

    def test_changed_source_identity_on_exact_retry_refuses(self):
        self.admit()
        changed = self.company(
            source_url="https://api.new-example.com/board/changed")
        with self.assertRaisesRegex(ValueError, "request_reused"):
            self.admit(company=changed)

    def test_event_receipt_and_current_company_mismatches_refuse(self):
        request = self.request()
        receipt_changes = {
            "event_id": "event-other",
            "company_id": "COMP-OTHER",
            "revision": 2,
            "source_revision": "rev-other",
            "request_sha256": "0" * 64,
            "state": "UNCONFIRMED",
        }
        for field, value in receipt_changes.items():
            with self.subTest(receipt_field=field):
                receipt = self.receipt(request)
                receipt[field] = value
                with self.assertRaisesRegex(ValueError, "event_receipt_invalid"):
                    self.admit(request, receipt=receipt)
        company_changes = {
            "company_id": "COMP-OTHER",
            "source_revision": "rev-other",
            "company_status": "Inactive",
            "claimed_by": "worker-1",
            "claim_token": "claim-1",
            "company_name": "  ",
            "official_careers_url": "not-a-url",
            "source_url": "not-a-url",
        }
        for field, value in company_changes.items():
            with self.subTest(company_field=field):
                company = self.company()
                company[field] = value
                with self.assertRaisesRegex(ValueError, "current_company_invalid"):
                    self.admit(request, company=company)

    def test_all_bound_inventory_and_job_evidence_drift_refuses(self):
        mutations = [
            ("inbox", "UPDATE inventories SET payload='{}' WHERE cycle=?", (CYCLE,)),
            ("inbox", "UPDATE inventories SET blocked=1 WHERE cycle=?", (CYCLE,)),
            ("inbox", "UPDATE sync_plans SET payload='{}' WHERE cycle=?", (CYCLE,)),
            ("inbox", "UPDATE sync_plans SET cursor=68 WHERE cycle=?", (CYCLE,)),
            ("inbox", "UPDATE exact_sync_chunks SET state='CHANGED' WHERE cycle=?", (CYCLE,)),
            ("inbox", "UPDATE exact_remote_plans SET state='CHANGED' WHERE cycle=?", (CYCLE,)),
            ("inbox", "UPDATE publication_receipts SET state='SYNC_CONFIRMED' WHERE receipt_id='r-1'", ()),
            ("jobs", "UPDATE exact_local_applications SET state='CHANGED' WHERE cycle=?", (CYCLE,)),
            ("jobs", "UPDATE exact_local_acknowledgements SET selected_fields_digest='changed' WHERE apply_id='apply-1'", ()),
            ("jobs", "UPDATE exact_local_apply_chunks SET state='CHANGED' WHERE apply_id='apply-1'", ()),
        ]
        for database, statement, parameters in mutations:
            with self.subTest(database=database, statement=statement):
                path = self.inbox if database == "inbox" else self.jobs
                with sqlite3.connect(path) as connection:
                    connection.execute(statement, parameters)
                with self.assertRaisesRegex(ValueError, "evidence_changed"):
                    revalidate_manifest(self.manifest, self.cycle,
                                        self.inbox, self.jobs)
                self.tearDown()
                self.setUp()
        with sqlite3.connect(self.jobs) as connection:
            connection.execute("INSERT INTO dirty VALUES ('Companies',1,'Last Checked')")
        with self.assertRaisesRegex(ValueError, "dirty_cells_present"):
            revalidate_manifest(self.manifest, self.cycle,
                                self.inbox, self.jobs)
        self.tearDown()
        self.setUp()
        changed_cycle = json.loads(json.dumps(self.cycle))
        changed_cycle["companies"][OLD]["stage"] = "blocked"
        with self.assertRaisesRegex(ValueError, "evidence_changed"):
            revalidate_manifest(self.manifest, changed_cycle, self.inbox, self.jobs)

    def test_manifest_corruption_is_detected_on_read(self):
        self.activate()
        store = RetainedWorkExceptionStore(self.store_path)
        try:
            with store.db:
                store.db.execute("UPDATE retained_work_exceptions SET manifest='{}'")
            with self.assertRaisesRegex(ValueError, "store_corrupt"):
                store.read(CYCLE)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
