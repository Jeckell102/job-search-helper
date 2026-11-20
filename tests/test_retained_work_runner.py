import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest
from datetime import datetime, timezone

from job_search_helper.company_events import source_revision
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.selected_recovery_authorization import TestAuthorizationVerifier
from job_search_helper.retained_work_exception import (
    activate_exception, build_manifest, digest, required_claims,
)
from job_search_helper.retained_work_runner import (
    assert_normal_lifecycle_not_held, commit_exceptional_start, prepare_exceptional_start,
    recover_prepared_exceptional_start, settle_retained_start,
)


CYCLE = "CYC-OLD"
OLD = "COMP-OLD"
NEW = "COMP-NEW"
NOW = datetime(2026, 11, 19, 20, 30, tzinfo=timezone.utc)


class FakeReadOnlyRepository:
    is_local = True
    readonly = True

    def __init__(self, company):
        self.company = company
        self.write_calls = 0

    def matches(self, tab, identity):
        if tab == "Companies" and identity == {"Company ID": self.company["Company ID"]}:
            return [(1, dict(self.company))]
        return []

    def read_columns(self, tab, columns):
        if tab == "Scan Cycles":
            return [(1, {"Cycle ID": CYCLE, "Cycle Status": "In Progress",
                         "Notes": "{}"})]
        raise AssertionError("unexpected read")

    def write(self, *args, **kwargs):
        self.write_calls += 1
        raise AssertionError("exceptional start must never write repository")


class RetainedWorkRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inbox_path = self.root / "inventories.sqlite3"
        self.jobs_path = self.root / "jobs.sqlite3"
        self.state_path = self.root / "state.db"
        self.store_path = self.root / "retained-work-exceptions.sqlite3"
        self.journal_path = self.root / "retained-work-starts.sqlite3"
        with sqlite3.connect(self.inbox_path) as db:
            db.execute("CREATE TABLE destination(id TEXT NOT NULL)")
            db.execute("INSERT INTO destination VALUES ('sheet-1')")
            db.execute("CREATE TABLE inventories(cycle TEXT,company TEXT,payload TEXT,blocked INTEGER,PRIMARY KEY(cycle,company))")
            db.execute("CREATE TABLE sync_plans(cycle TEXT,company TEXT,payload TEXT,cursor INTEGER,PRIMARY KEY(cycle,company))")
            db.execute("INSERT INTO inventories VALUES (?,?,?,0)",
                       (CYCLE, OLD, json.dumps({"jobs": [{"id": "one"}]})))
            db.execute("INSERT INTO sync_plans VALUES (?,?,?,67)",
                       (CYCLE, OLD, json.dumps({"operations": [1, 2]})))
        with sqlite3.connect(self.jobs_path) as db:
            db.execute("CREATE TABLE dirty(tab TEXT,row_id INTEGER,header TEXT)")
            db.execute("CREATE TABLE exact_local_applications(apply_id TEXT,cycle TEXT,company TEXT,plan_digest TEXT,inventory_payload_digest TEXT,local_operations_digest TEXT,remote_projection_digest TEXT,row_scope TEXT,created_at TEXT,verified_at TEXT,state TEXT)")
            db.execute("CREATE TABLE exact_local_acknowledgements(acknowledgement_id TEXT,apply_id TEXT,receipt_id TEXT,selected_fields_digest TEXT,created_at TEXT)")
            db.execute("CREATE TABLE exact_local_apply_chunks(apply_id TEXT,start_cursor INTEGER,operation_count INTEGER,operations_digest TEXT,state TEXT)")
        # Match the already-initialized production inbox schema before the
        # historical manifest is frozen.  Constructing the writer later must
        # not appear to add historical evidence tables.
        initialized = InventoryInbox(self.inbox_path, "sheet-1")
        initialized.close()
        self.old_cycle = {
            "id": CYCLE, "status": "In Progress", "started_at": "old",
            "companies": {OLD: {
                "stage": "inventory", "company": "Old Company",
                "requested_url": "https://jobs.example.com/old",
                "source_url": "https://api.example.com/old", "ats": "OldATS",
            }},
        }
        initial_state = State(str(self.state_path))
        initial_state.save_cycle(self.old_cycle)
        initial_state.close()
        self.state = State(str(self.state_path), readonly=True)
        self.manifest = build_manifest(
            self.old_cycle, self.inbox_path, self.jobs_path,
            reason="historical containment",
            created_at="2026-11-19T20:00:00+00:00")
        self.verifier = TestAuthorizationVerifier()
        envelope = self.verifier.issue(required_claims(
            self.manifest, expires_at="2026-11-19T21:00:00+00:00"))
        activate_exception(
            self.manifest, envelope, self.verifier, self.store_path,
            now=NOW, allow_test_verifier=True)
        self.company = {
            "Company ID": NEW, "Company": "New Company",
            "Company Status": "Active",
            "Official Careers URL": "https://jobs.new-example.com/board/new",
            "ATS / Source": "ExampleATS", "Claimed By": "", "Claim Token": "",
        }
        self.revision = source_revision(self.company)
        self.event = {
            "schema": "company-event-scan-request-v1", "event_id": "event-1",
            "company_id": NEW, "revision": 1,
            "source_revision": self.revision,
        }
        self.request = {
            "mode": "company-only", "request_id": "company-event:event-1",
            "company_ids": [NEW], "source_revision": self.revision,
            "enqueued_at": "2026-11-19T20:00:00Z", "start_last": [],
            "company_event": self.event,
        }
        (self.root / "next-scan.json").write_text(
            json.dumps(self.request), encoding="utf-8")
        receipt_dir = self.root / "company-event-bridge" / "receipts"
        receipt_dir.mkdir(parents=True)
        self.receipt = {
            **self.event, "state": "REQUEST_WRITTEN",
            "request_sha256": digest(self.request),
        }
        (receipt_dir / "event-1.json").write_text(
            json.dumps(self.receipt), encoding="utf-8")
        self.repo = FakeReadOnlyRepository(self.company)
        self.fetch_count = 0
        self.state_factory_calls = 0
        self.inbox_factory_calls = 0

    def tearDown(self):
        self.state.close()
        self.temp.cleanup()

    def prefetch(self, ats, url, company_id, company):
        self.fetch_count += 1
        self.assertEqual(("ExampleATS", self.company["Official Careers URL"],
                          NEW, "New Company"),
                         (ats, url, company_id, company))
        return SimpleNamespace(
            status="complete", jobs=[{"id": "new-job", "title": "Engineer"}],
            reason="", source_url="https://api.new-example.com/board/new",
            ats="ExampleATS", browser_pending_urls=[],
            browser_discovery_incomplete=False)

    def prepare(self):
        return prepare_exceptional_start(
            self.repo, self.state, self.root, self.inbox_path, self.jobs_path,
            self.store_path, self.manifest, self.verifier, self.prefetch,
            now=NOW, allow_test_verifier=True)

    def writable_state(self):
        self.state_factory_calls += 1
        return State(str(self.state_path))

    def writable_inbox(self):
        self.inbox_factory_calls += 1
        return InventoryInbox(self.inbox_path, "sheet-1")

    def commit(self, prepared, *, crash_after=None):
        return commit_exceptional_start(
            prepared, self.repo, self.state, self.root,
            self.journal_path, self.manifest, self.inbox_path,
            self.jobs_path, self.store_path, self.verifier, now=NOW,
            allow_test_verifier=True, state_factory=self.writable_state,
            inbox_factory=self.writable_inbox, crash_after=crash_after)

    def test_journal_only_freeze_leaves_ordinary_state_and_inbox_unchanged(self):
        prepared = self.prepare()
        self.assertEqual(1, self.fetch_count)
        state_before = self.state_path.read_bytes()
        inbox_before = self.inbox_path.read_bytes()
        result = self.commit(prepared)
        self.assertEqual("RETAINED_WORK_FROZEN", result["state"])
        self.assertTrue(result["publication_deferred"])
        self.assertEqual(0, self.repo.write_calls)
        self.assertEqual(0, self.state_factory_calls)
        self.assertEqual(0, self.inbox_factory_calls)
        self.assertEqual(state_before, self.state_path.read_bytes())
        self.assertEqual(inbox_before, self.inbox_path.read_bytes())
        self.assertEqual(self.old_cycle, self.state.cycle(CYCLE))
        self.assertIsNone(self.state.cycle(result["session_id"]))
        self.assertTrue((self.root / "next-scan.json").exists())
        self.assertFalse((self.root / "last-scan-request.json").exists())
        with sqlite3.connect(self.journal_path) as db:
            row = db.execute(
                "SELECT cycle_id,prepared,state FROM retained_work_starts").fetchone()
        self.assertEqual(result["session_id"], row[0])
        self.assertEqual(prepared.inventory, json.loads(row[1])["inventory"])
        self.assertEqual("FROZEN", row[2])

    def test_crash_after_journal_freeze_recovers_without_refetch_or_lifecycle_write(self):
        for crash_after in ("reserve",):
            with self.subTest(crash_after=crash_after):
                prepared = self.prepare()
                state_before = self.state_path.read_bytes()
                inbox_before = self.inbox_path.read_bytes()
                with self.assertRaisesRegex(RuntimeError, "injected_crash"):
                    self.commit(prepared, crash_after=crash_after)
                # Simulate a cold process.  Recovery has no prefetcher argument.
                self.state.close()
                self.state = State(str(self.state_path), readonly=True)
                recovered = recover_prepared_exceptional_start(
                    self.repo, self.state, self.root,
                    self.journal_path, self.inbox_path, self.jobs_path,
                    self.store_path, self.manifest, self.verifier,
                    now=NOW, allow_test_verifier=True)
                result = self.commit(recovered)
                self.assertEqual(1, self.fetch_count)
                self.assertTrue(result["session_id"].startswith("RWS-"))
                self.assertEqual(state_before, self.state_path.read_bytes())
                self.assertEqual(inbox_before, self.inbox_path.read_bytes())
                self.assertEqual([CYCLE], [cycle["id"] for cycle in self.state.cycles()])
                # Restore a fresh isolated fixture for the next crash point.
                self.tearDown()
                self.setUp()

    def test_company_change_during_prefetch_refuses_before_cycle(self):
        def changing_prefetch(*args):
            result = self.prefetch(*args)
            self.repo.company = dict(self.repo.company, Company="Changed Company")
            return result
        with self.assertRaisesRegex(ValueError, "trusted_snapshot_changed"):
            prepare_exceptional_start(
                self.repo, self.state, self.root, self.inbox_path, self.jobs_path,
                self.store_path, self.manifest, self.verifier,
                changing_prefetch, now=NOW, allow_test_verifier=True)
        self.assertEqual([CYCLE], [cycle["id"] for cycle in self.state.cycles()])
        with sqlite3.connect(self.store_path) as db:
            self.assertEqual(
                0, db.execute(
                    "SELECT COUNT(*) FROM retained_work_admissions").fetchone()[0])

    def test_source_alias_refuses_before_cycle(self):
        def alias_prefetch(*args):
            result = self.prefetch(*args)
            result.source_url = "https://api.example.com/old?tracking=new"
            return result
        with self.assertRaisesRegex(ValueError, "source_alias"):
            prepare_exceptional_start(
                self.repo, self.state, self.root, self.inbox_path, self.jobs_path,
                self.store_path, self.manifest, self.verifier,
                alias_prefetch, now=NOW, allow_test_verifier=True)
        self.assertEqual([CYCLE], [cycle["id"] for cycle in self.state.cycles()])

    def test_readonly_local_repository_is_mandatory(self):
        self.repo.readonly = False
        with self.assertRaisesRegex(ValueError, "readonly_local_repository_required"):
            self.prepare()

    def test_existing_mismatched_cycle_binding_refuses(self):
        prepared = self.prepare()
        bad = {
            "id": "CYC-BAD", "status": "In Progress", "companies": {},
            "start_request_id": self.request["request_id"],
        }
        writable = State(str(self.state_path))
        writable.save_cycle(bad)
        writable.close()
        with self.assertRaisesRegex(ValueError, "trusted_snapshot_changed"):
            self.commit(prepared)

    def test_request_change_before_rename_refuses(self):
        prepared = self.prepare()
        changed = dict(self.request, enqueued_at="2026-11-19T20:01:00Z")
        (self.root / "next-scan.json").write_text(
            json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "request_changed"):
            self.commit(prepared)
        self.assertTrue((self.root / "next-scan.json").exists())

    def test_exact_state_layout_is_required(self):
        prepared = self.prepare()
        with self.assertRaisesRegex(ValueError, "state_layout_invalid"):
            commit_exceptional_start(
                prepared, self.repo, self.state, self.root,
                self.root / "wrong.sqlite3", self.manifest,
                self.inbox_path, self.jobs_path, self.store_path,
                self.verifier, now=NOW, allow_test_verifier=True,
                state_factory=self.writable_state,
                inbox_factory=self.writable_inbox)

    def test_final_trusted_reread_refuses_before_journal_or_new_writes(self):
        def company_change():
            self.repo.company = dict(self.repo.company, Company="Changed")

        def receipt_change():
            path = self.root / "company-event-bridge" / "receipts" / "event-1.json"
            changed = dict(self.receipt, state="UNCONFIRMED")
            path.write_text(json.dumps(changed), encoding="utf-8")

        def request_change():
            changed = dict(self.request, enqueued_at="2026-11-19T20:02:00Z")
            (self.root / "next-scan.json").write_text(
                json.dumps(changed), encoding="utf-8")

        def blocker_change():
            writable = State(str(self.state_path))
            writable.save_cycle({
                "id": "CYC-OTHER", "status": "In Progress",
                "started_at": "later", "companies": {},
            })
            writable.close()

        def historical_change():
            with sqlite3.connect(self.inbox_path) as db:
                db.execute("UPDATE inventories SET payload='{}' WHERE cycle=?",
                           (CYCLE,))

        for name, mutation in (
                ("company", company_change), ("receipt", receipt_change),
                ("request", request_change), ("blocker", blocker_change),
                ("historical", historical_change)):
            with self.subTest(mutation=name):
                prepared = self.prepare()
                store_before = self.store_path.read_bytes()
                mutation()
                with self.assertRaises(ValueError):
                    self.commit(prepared)
                self.assertFalse(self.journal_path.exists())
                self.assertEqual(store_before, self.store_path.read_bytes())
                self.assertEqual(0, self.state_factory_calls)
                self.assertEqual(0, self.inbox_factory_calls)
                with sqlite3.connect(self.inbox_path) as db:
                    self.assertEqual(
                        [(CYCLE, OLD)],
                        db.execute("SELECT cycle,company FROM inventories ORDER BY cycle,company").fetchall())
                self.tearDown()
                self.setUp()

    def test_final_reservation_gate_is_readonly_and_refuses_tampering(self):
        def missing(db):
            db.execute("DELETE FROM retained_work_admissions")

        def corrupt_payload(db):
            db.execute(
                "UPDATE retained_work_admissions SET payload='not-json'")

        def different_event(db):
            db.execute(
                "UPDATE retained_work_admissions SET event_id='different-event'")

        def different_digest(db):
            db.execute(
                "UPDATE retained_work_admissions SET payload_digest=?",
                ("0" * 64,))

        for name, mutation in (
                ("missing", missing), ("corrupt-payload", corrupt_payload),
                ("different-event", different_event),
                ("different-digest", different_digest)):
            with self.subTest(mutation=name):
                prepared = self.prepare()
                with sqlite3.connect(self.store_path) as db:
                    mutation(db)
                tampered_bytes = self.store_path.read_bytes()
                with self.assertRaises(ValueError):
                    self.commit(prepared)
                self.assertEqual(tampered_bytes, self.store_path.read_bytes())
                self.assertFalse(self.journal_path.exists())
                self.assertEqual(0, self.state_factory_calls)
                self.assertEqual(0, self.inbox_factory_calls)
                self.assertEqual([CYCLE], [cycle["id"] for cycle in self.state.cycles()])
                with sqlite3.connect(self.inbox_path) as db:
                    self.assertEqual(
                        [(CYCLE, OLD)],
                        db.execute(
                            "SELECT cycle,company FROM inventories "
                            "ORDER BY cycle,company").fetchall())
                self.tearDown()
                self.setUp()

    def test_fresh_preflight_identity_mutation_refuses_before_any_local_write(self):
        prepared = self.prepare()
        # PreparedExceptionalStart is frozen only at its outer dataclass layer.
        # This models a caller mutating its nested inventory before commit.
        prepared.inventory["source_url"] = "https://api.example.com/old"
        with self.assertRaisesRegex(ValueError, "admitted_identity_changed"):
            self.commit(prepared)
        self.assertFalse(self.journal_path.exists())
        self.assertEqual([CYCLE], [cycle["id"] for cycle in self.state.cycles()])

    def test_recovery_rederives_identity_after_complete_journal_tampering(self):
        prepared = self.prepare()
        with self.assertRaisesRegex(RuntimeError, "injected_crash_after_reserve"):
            self.commit(prepared, crash_after="reserve")
        # A digest is an integrity check, not an authority boundary.  Simulate
        # a repair tool that changes every journal self-digest but leaves the
        # immutable admission reservation untouched.
        with sqlite3.connect(self.journal_path) as db:
            binding_text, prepared_text = db.execute(
                "SELECT binding,prepared FROM retained_work_starts").fetchone()
            binding = json.loads(binding_text)
            payload = json.loads(prepared_text)
            payload["inventory"]["source_url"] = "https://api.example.com/old"
            binding["inventory_digest"] = digest(payload["inventory"])
            db.execute(
                "UPDATE retained_work_starts SET binding=?,binding_digest=?,"
                "prepared=?,prepared_digest=?",
                (json.dumps(binding, sort_keys=True, separators=(",", ":")),
                 digest(binding),
                 json.dumps(payload, sort_keys=True, separators=(",", ":")),
                 digest(payload)))
        self.state.close()
        self.state = State(str(self.state_path), readonly=True)
        with self.assertRaisesRegex(ValueError, "admitted_identity_changed"):
            recover_prepared_exceptional_start(
                self.repo, self.state, self.root, self.journal_path,
                self.inbox_path, self.jobs_path, self.store_path,
                self.manifest, self.verifier, now=NOW, allow_test_verifier=True)
        self.assertEqual([CYCLE], [cycle["id"] for cycle in self.state.cycles()])

    def test_recovery_refuses_full_preflight_rewrite_before_lifecycle_write(self):
        prepared = self.prepare()
        with self.assertRaisesRegex(RuntimeError, "injected_crash_after_reserve"):
            self.commit(prepared, crash_after="reserve")
        # Model a sufficiently capable bad repair tool: it rewrites every
        # journal digest after substituting the provider result and the
        # matching preflight Company/source snapshot.  It cannot rewrite the
        # separate immutable admission store, which must remain authoritative.
        with sqlite3.connect(self.journal_path) as db:
            binding_text, prepared_text = db.execute(
                "SELECT binding,prepared FROM retained_work_starts").fetchone()
            binding = json.loads(binding_text)
            payload = json.loads(prepared_text)
            payload["inventory"]["source_url"] = "https://evil.example.test/api"
            payload["inventory"]["ats"] = "OtherATS"
            payload["company"]["Company"] = "Substituted Company"
            payload["company"]["Official Careers URL"] = "https://evil.example.test/jobs"
            payload["snapshot"]["company_fact"]["official_careers_url"] = (
                "https://evil.example.test/jobs")
            binding["inventory_digest"] = digest(payload["inventory"])
            db.execute(
                "UPDATE retained_work_starts SET binding=?,binding_digest=?,"
                "prepared=?,prepared_digest=?",
                (json.dumps(binding, sort_keys=True, separators=(",", ":")),
                 digest(binding),
                 json.dumps(payload, sort_keys=True, separators=(",", ":")),
                 digest(payload)))
        self.state.close()
        self.state = State(str(self.state_path), readonly=True)
        before_inbox = self.inbox_path.read_bytes()
        with self.assertRaises(ValueError):
            recover_prepared_exceptional_start(
                self.repo, self.state, self.root, self.journal_path,
                self.inbox_path, self.jobs_path, self.store_path,
                self.manifest, self.verifier, now=NOW, allow_test_verifier=True)
        self.assertEqual(before_inbox, self.inbox_path.read_bytes())
        self.assertEqual(0, self.repo.write_calls)
        self.assertEqual([CYCLE], [cycle["id"] for cycle in self.state.cycles()])

    def test_frozen_session_cannot_be_mistaken_for_a_normal_cycle(self):
        result = self.commit(self.prepare())
        self.assertTrue(result["session_id"].startswith("RWS-"))
        self.assertIsNone(self.state.cycle(result["session_id"]))
        self.assertEqual([CYCLE], [cycle["id"] for cycle in self.state.cycles()])

    def test_frozen_session_holds_normal_lifecycle_before_it_can_start(self):
        with self.assertRaisesRegex(RuntimeError, "injected_crash_after_reserve"):
            self.commit(self.prepare(), crash_after="reserve")
        with self.assertRaisesRegex(ValueError, "normal lifecycle and generic sync"):
            assert_normal_lifecycle_not_held(self.root)
        self.assertEqual([CYCLE], [cycle["id"] for cycle in self.state.cycles()])

    def test_crash_after_intake_hold_still_blocks_normal_lifecycle(self):
        with self.assertRaisesRegex(RuntimeError, "injected_crash_after_intake_hold"):
            self.commit(self.prepare(), crash_after="intake_hold")
        with sqlite3.connect(self.journal_path) as db:
            self.assertEqual(0, db.execute(
                "SELECT count(*) FROM retained_work_starts").fetchone()[0])
        with self.assertRaisesRegex(ValueError, "Retained intake hold"):
            assert_normal_lifecycle_not_held(self.root, self.jobs_path)

    def test_frozen_session_creates_a_synchronizer_visible_intake_hold(self):
        result = self.commit(self.prepare())
        with sqlite3.connect(self.jobs_path) as db:
            row = db.execute(
                "SELECT request_id,event_id,company_id,manifest_digest,"
                "start_binding_digest,state FROM retained_intake_holds "
                "WHERE reservation_digest=?", (result["reservation_digest"],)).fetchone()
        self.assertEqual(row[:4], (self.request["request_id"],
                                   self.event["event_id"], NEW,
                                   self.manifest["manifest_digest"]))
        self.assertEqual(len(row[4]), 64)
        self.assertEqual(row[5], "FROZEN")

    def test_durable_first_pass_settlement_releases_normal_lifecycle(self):
        result = self.commit(self.prepare())
        with self.assertRaisesRegex(ValueError, "normal lifecycle and generic sync"):
            assert_normal_lifecycle_not_held(self.root, self.jobs_path)
        evidence = {"reservation_digest": result["reservation_digest"],
                    "queue": [], "files": {}}
        with sqlite3.connect(self.jobs_path) as db:
            db.execute("DROP TABLE retained_intake_holds")
            db.execute("""CREATE TABLE retained_publications (
                reservation_digest TEXT PRIMARY KEY,state TEXT NOT NULL,
                queue_evidence TEXT,queue_evidence_digest TEXT)""")
            db.execute(
                "INSERT INTO retained_publications VALUES (?,?,?,?)",
                (result["reservation_digest"], "FIRST_PASS_RELEASED",
                 json.dumps(evidence, sort_keys=True, separators=(",", ":")),
                 digest(evidence)))
        settled = settle_retained_start(
            self.root, self.jobs_path, result["reservation_digest"])
        self.assertTrue(settled["settled"])
        self.assertFalse(settled["recovered"])
        assert_normal_lifecycle_not_held(self.root, self.jobs_path)
        self.assertEqual("journal_empty", settle_retained_start(
            self.root, self.jobs_path,
            result["reservation_digest"])["reason"])
        with sqlite3.connect(self.journal_path) as db:
            self.assertEqual(0, db.execute(
                "SELECT count(*) FROM retained_work_starts").fetchone()[0])

    def test_forged_terminal_journal_state_stays_blocked(self):
        self.commit(self.prepare())
        with sqlite3.connect(self.journal_path) as db:
            db.execute("UPDATE retained_work_starts SET state='SETTLED'")
        with self.assertRaisesRegex(ValueError, "lifecycle_journal_invalid"):
            assert_normal_lifecycle_not_held(self.root, self.jobs_path)


if __name__ == "__main__":
    unittest.main()
