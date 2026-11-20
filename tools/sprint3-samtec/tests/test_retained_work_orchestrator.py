from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.cli import WriterLockBusy, writer_lock
from job_search_helper.engine import Engine, State
from job_search_helper.exact_cycle_planner import _exact_plan_digest
from job_search_helper.exact_cycle_sync import _company_guard
from job_search_helper.repository import GoogleRepository, MemoryRepository, SCHEMAS, UncertainWriteError
from job_search_helper.retained_operator_authorization import operator_membership_claims
from job_search_helper.retained_operator_journal import RetainedOperatorJournal, operator_journal_binding
from job_search_helper.retained_session_store import RetainedSessionStore
from job_search_helper.retained_work_orchestrator import _run_retained_reservation_locked, run_retained_reservation
from job_search_helper.retained_work_publication import (
    _verify_operator_terminal_receipt, publish_retained_reservation,
)
from job_search_helper.retained_work_runner import (
    PreparedExceptionalStart, _StartJournal, _TOKEN, _request_provenance_id,
    assert_normal_lifecycle_not_held, digest,
)
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


def company():
    return {
        "Company ID": "COMP-NEW", "Company": "Fixture",
        "Company Status": "Active",
        "Official Careers URL": "https://jobs.example.test/fixture",
        "ATS / Source": "Greenhouse", "Scan State": "Queued",
        "Claimed By": "", "Claim Token": "", "Automatic Retry?": "",
    }


def frozen_inventory():
    return {
        "status": "complete", "reason": "", "source_url":
        "https://jobs.example.test/fixture", "ats": "Greenhouse",
        "browser_pending_urls": [], "browser_discovery_incomplete": False,
        "fetched_at": "2026-11-19T20:30:00+00:00",
        "requested_url": "https://jobs.example.test/fixture",
        "jobs": [{
            "title": "Implementation Manager", "posting_id": "42",
            "url": "https://jobs.example.test/fixture/jobs/42",
            "location": "Remote",
            "description": "Customer implementation and deployment work.",
            "ats": "Greenhouse",
        }],
    }


def prepared(reservation="reservation", request_id="REQ", event_id="EVT"):
    request = {
        "request_id": request_id, "company_ids": ["COMP-NEW"],
        "company_event": {"event_id": event_id},
    }
    snapshot = {
        "request": request, "source_revision": "SRC-1",
        "snapshot_digest": digest({"request": request, "source_revision": "SRC-1"}),
    }
    admission = {"reservation_digest": reservation, "manifest_digest": "manifest"}
    return PreparedExceptionalStart(
        _TOKEN, snapshot, company(), {"id": "CYC-OLD"},
        frozen_inventory(), admission, "2026-11-19T20:30:00+00:00")


class RetainedWorkOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.local = SQLiteRepository(
            self.root / "jobs.sqlite3", "fixture", initialize=True)
        self.addCleanup(self.local.close)
        with self.local.transaction():
            self.local.set_meta("ready", "yes")
            self.local.set_meta("sheets_profile", COMPACT_PROFILE)
        self.local.ensure_columns("Opportunities", ["Opportunity ID"])
        source = MemoryRepository({"Companies": [company()]}, schemas=self.local.schemas)
        for tab in SCHEMAS:
            self.local.import_rows(tab, enumerate(source.read(tab), 2))
        self.state = State()
        self.addCleanup(self.state.close)
        self.engine = Engine(
            self.local, self.state, error_log_path=self.root / "errors.jsonl")
        rows = {"Companies": [company()]}
        self.service = RangeSheets(rows, schemas=COMPACT_SCHEMAS)
        self.remote = GoogleRepository(
            self.service, "fixture", schemas=COMPACT_SCHEMAS,
            min_request_interval=0)
        self.store = RetainedSessionStore(self.root / "retained.sqlite3")
        self.addCleanup(self.store.close)

    def freeze_start(self, item):
        journal = _StartJournal(self.root / "retained-work-starts.sqlite3")
        try:
            _session, binding, binding_digest = journal.reserve(item)
        finally:
            journal.close()
        request = item.snapshot["request"]
        with self.local.transaction():
            self.local.db.execute("""CREATE TABLE IF NOT EXISTS retained_intake_holds (
                reservation_digest TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                event_id TEXT NOT NULL UNIQUE, company_id TEXT NOT NULL,
                manifest_digest TEXT NOT NULL, start_binding_digest TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state='FROZEN'))""")
            self.local.db.execute(
                "INSERT INTO retained_intake_holds VALUES (?,?,?,?,?,?,?)",
                (item.admission["reservation_digest"], request["request_id"],
                 _request_provenance_id(request), "COMP-NEW", item.admission["manifest_digest"],
                 binding_digest, "FROZEN"))
        return binding

    def freeze_operator(self, *, two_postings=False):
        selected = {**company(), "Active Cycle ID": "CYC-OLD"}
        self.local.import_rows("Companies", [(2, selected)])
        selected = self.local.matches("Companies", {"Company ID": "COMP-NEW"})[0][1]
        retained_cycle = {"id": "CYC-OLD", "status": "In Progress",
                          "companies": {"COMP-NEW": {"company": "Fixture", "stage": "queued"}}}
        self.state.save_cycle(retained_cycle)
        identity = {"schema": "operator-company-scan-request-v1", "request_id": "REQ-OPERATOR",
                    "company_id": "COMP-NEW", "source_revision": "SRC-1"}
        request = {"request_id": identity["request_id"], "company_ids": ["COMP-NEW"],
                   "mode": "company-only", "source_revision": "SRC-1", "operator_request": identity}
        receipt = {**identity, "request_sha256": digest(request), "state": "REQUEST_WRITTEN"}
        snapshot = {"request": request, "receipt": receipt, "source_revision": "SRC-1",
                    "company_row_digest": digest(selected), "manifest_digest": digest("manifest"),
                    "blocking_cycle_ids": ["CYC-OLD"]}
        snapshot["snapshot_digest"] = digest(snapshot)
        runtime = {
            "state": "NO_RELEASE", "source_manifest_sha256": digest("source"),
            "config_sha256": digest("config"), "dependency_manifest_sha256": digest("dependencies"),
        }
        controls = _company_guard(self.local, self.remote, "COMP-NEW", selected["Official Careers URL"])
        claims = operator_membership_claims(
            snapshot, {"company_id": "COMP-NEW", "cycle_id": "CYC-OLD"},
            historical_work_digest=digest("history"), runtime=runtime,
            workbook_controls={"controls": controls, "schemas_sha256": digest(self.remote.schemas)},
            expires_at="2026-11-22T00:00:00Z")
        binding = operator_journal_binding(claims, runtime, {
            "authorization_digest": digest("fixture approval"), "claims_digest": digest(claims),
            "key_id": "fixture", "expires_at": claims["expires_at"],
        })
        inventory = frozen_inventory()
        if two_postings:
            inventory["jobs"].append({**inventory["jobs"][0], "posting_id": "43",
                                      "url": "https://jobs.example.test/fixture/jobs/43"})
        journal = RetainedOperatorJournal(self.root)
        with writer_lock(self.root / "scraper.lock"):
            journal.prepare(binding)
            claim = journal.claim_fetch(binding)
            journal.freeze_inventory(binding, claim, inventory)
            item = PreparedExceptionalStart(
                _TOKEN, snapshot, selected, retained_cycle, journal.recover_inventory(binding),
                {"reservation_digest": binding["reservation_digest"],
                 "manifest_digest": snapshot["manifest_digest"],
                 "reservation_payload": {key: binding[key] for key in ("claims", "runtime", "authorization")}},
                inventory["fetched_at"])
            self.freeze_start(item)
        return item, runtime

    def run_operator(self, item, runtime, *, max_operations=100):
        with writer_lock(self.root / "scraper.lock"):
            return _run_retained_reservation_locked(
                item, self.engine, self.local, self.remote, self.store,
                membership_only=True, runtime_binding=runtime, max_operations=max_operations)

    def test_frozen_company_reaches_saved_job_and_first_pass_then_releases(self):
        item = prepared()
        self.freeze_start(item)
        result = run_retained_reservation(
            item, self.engine, self.local, self.remote, self.store)
        self.assertEqual("FIRST_PASS_RELEASED",
                         result["publication"]["state"])
        history = self.local.read("Job History")
        evidence = self.local.read("Job Evidence")
        self.assertEqual(1, len(history))
        self.assertEqual(1, len(evidence))
        self.assertEqual(history[0]["Job Key"], evidence[0]["Job Key"])
        queue = result["publication"]["first_pass"]
        self.assertEqual(1, len(queue["selected_jobs"]))
        self.assertEqual(history[0]["Job Key"], queue["selected_jobs"][0]["job_key"])
        with sqlite3.connect(self.root / "retained-work-starts.sqlite3") as db:
            self.assertEqual(0, db.execute(
                "SELECT count(*) FROM retained_work_starts").fetchone()[0])
        assert_normal_lifecycle_not_held(self.root, self.local.path)
        self.assertEqual([], self.state.cycles())
        batches = len(self.service.batches)
        recovered = run_retained_reservation(
            item, self.engine, self.local, self.remote, self.store)
        self.assertTrue(recovered["recovered"])
        self.assertEqual("FIRST_PASS_RELEASED",
                         recovered["publication"]["state"])
        self.assertEqual(batches, len(self.service.batches))

    def test_finished_journal_can_accept_a_later_retained_request(self):
        first = prepared()
        self.freeze_start(first)
        run_retained_reservation(
            first, self.engine, self.local, self.remote, self.store)
        second = prepared("reservation-2", "REQ-2", "EVT-2")
        binding = self.freeze_start(second)
        self.assertEqual("reservation-2", binding["reservation_digest"])
        with sqlite3.connect(self.root / "retained-work-starts.sqlite3") as db:
            rows = db.execute(
                "SELECT state FROM retained_work_starts").fetchall()
        self.assertEqual([("FROZEN",)], rows)

    def test_operator_lost_ack_uses_sealed_pin_inventory_and_original_claim(self):
        item, runtime = self.freeze_operator(two_postings=True)
        reservation = item.admission["reservation_digest"]
        state_before = self.state.cycles()
        company_before = self.local.read("Companies")
        remote_company_before = self.remote.read("Companies")
        unseen = {"Company": "Fixture", "Job Key": "OLD", "Job Title": "Unseen",
                  "Official Job URL": "https://jobs.example.test/fixture/jobs/old",
                  "Job Status": "Open and verified", "Consecutive Missing Scans": 2}
        self.local.import_rows("Job History", [(2, unseen)])
        old_before = self.local.matches("Job History", {"Job Key": "OLD"})
        request = self.root / "next-scan.json"
        request.write_text(json.dumps(item.snapshot["request"]))
        request_before = request.read_bytes()

        def verify_locks():
            for name in ("scraper.lock", "writer.lock", "retained-publication.lock"):
                with self.assertRaises(WriterLockBusy), writer_lock(self.root / name):
                    pass

        self.service.before_write = verify_locks
        self.service.lose_response = True
        with patch.object(self.engine, "fetcher", side_effect=AssertionError("unexpected fetch")) as fetch:
            with self.assertRaises(UncertainWriteError):
                self.run_operator(item, runtime)
            pending = self.store.load(reservation)
            self.assertEqual("SYNC_PENDING", pending["state"])
            self.assertEqual(2, pending["chunks"][0]["operation_count"])
            self.assertEqual("CLAIMED", pending["chunks"][0]["state"])
            self.assertEqual(digest(runtime), pending["plan"]["runtime_binding_sha256"])
            without_runtime = {key: value for key, value in pending["plan"].items()
                               if key != "runtime_binding_sha256"}
            self.assertNotEqual(_exact_plan_digest(without_runtime), pending["plan_digest"])
            self.assertEqual({"Job History", "Job Evidence"},
                             {operation["tab"] for operation in pending["plan"]["local_operations"]})
            batches = len(self.service.batches)
            store_path = self.store.path
            self.store.close()
            self.store = RetainedSessionStore(store_path)
            self.addCleanup(self.store.close)
            binding = {**item.admission["reservation_payload"], "reservation_digest": reservation}
            with writer_lock(self.root / "scraper.lock"):
                inventory = RetainedOperatorJournal(self.root).recover_inventory(binding)
            item = replace(item, inventory=inventory)
            with patch("job_search_helper.retained_work_orchestrator.freeze_retained_exact_plan",
                       side_effect=AssertionError("unexpected replan")):
                result = self.run_operator(item, runtime, max_operations=1)
            fetch.assert_not_called()
        self.assertEqual(batches, len(self.service.batches))
        self.assertEqual("SYNC_CONFIRMED", result["session"]["state"])
        self.assertEqual(digest(runtime), result["publication"]["runtime_binding_sha256"])
        self.assertEqual("FIRST_PASS_RELEASED", result["publication"]["state"])
        self.assertEqual(state_before, self.state.cycles())
        self.assertEqual(old_before, self.local.matches("Job History", {"Job Key": "OLD"}))
        self.assertEqual(company_before, self.local.read("Companies"))
        self.assertEqual(remote_company_before, self.remote.read("Companies"))
        self.assertEqual(request_before, request.read_bytes())
        terminal = self.run_operator(item, runtime)
        self.assertTrue(terminal["recovered"])
        self.assertEqual(batches, len(self.service.batches))

    def test_operator_mismatching_or_missing_pins_leave_pending_claim_held(self):
        item, runtime = self.freeze_operator()
        reservation = item.admission["reservation_digest"]
        self.service.lose_response = True
        with self.assertRaises(UncertainWriteError):
            self.run_operator(item, runtime)
        reads, batches = len(self.service.get_calls), len(self.service.batches)
        with self.assertRaisesRegex(ValueError, "retained_operator_runtime_binding_required"):
            self.run_operator(item, None)
        with self.assertRaisesRegex(ValueError, "retained_operator_reservation_runtime_changed"):
            self.run_operator(item, {**runtime, "config_sha256": digest("changed config")})
        with self.assertRaisesRegex(ValueError, "retained_operator_runtime_binding_required"):
            publish_retained_reservation(reservation, self.store, self.local, self.remote)

        plan = self.store.load(reservation)["plan"]
        plan["runtime_binding_sha256"] = digest("other runtime")
        plan["plan_digest"] = _exact_plan_digest(plan)
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE retained_sessions SET plan=?,plan_digest=? WHERE reservation_digest=?",
                (json.dumps(plan), plan["plan_digest"], reservation))
        with self.assertRaisesRegex(ValueError, "retained_operator_saved_plan_runtime_changed"):
            self.run_operator(item, runtime)
        self.assertEqual("CLAIMED", self.store.load(reservation)["chunks"][0]["state"])
        self.assertEqual((reads, batches), (len(self.service.get_calls), len(self.service.batches)))

    def test_operator_recovers_after_dirty_ack_without_reapplying_local_plan(self):
        item, runtime = self.freeze_operator()
        with patch("job_search_helper.retained_work_publication.confirm_remote_from_session",
                   side_effect=RuntimeError("fixture post-ack exit")):
            with self.assertRaisesRegex(RuntimeError, "fixture post-ack exit"):
                self.run_operator(item, runtime)
        self.assertEqual(0, self.local.db.execute("SELECT count(*) FROM dirty").fetchone()[0])
        batches = len(self.service.batches)
        with patch("job_search_helper.retained_work_orchestrator.commit_exact_local_plan",
                   side_effect=AssertionError("unexpected local replay")):
            recovered = self.run_operator(item, runtime)
        self.assertEqual("FIRST_PASS_RELEASED", recovered["publication"]["state"])
        self.assertEqual(batches, len(self.service.batches))

    def test_operator_refuses_changed_frozen_preparation(self):
        item, runtime = self.freeze_operator()
        changed = replace(item, started_at="2026-11-20T20:30:00+00:00")
        with self.assertRaisesRegex(ValueError, "retained_operator_frozen_preparation_changed"):
            self.run_operator(changed, runtime)
        item.company["Next Action"] = "not part of the frozen approval"
        with self.assertRaisesRegex(ValueError, "retained_operator_reservation_identity_changed"):
            self.run_operator(item, runtime)
        self.assertFalse(self.service.batches)
        self.assertFalse(self.local.read("Job History"))

    def test_v1_path_cannot_open_a_saved_operator_start_without_its_runtime_payload(self):
        item, _runtime = self.freeze_operator()
        legacy = replace(item, admission={key: item.admission[key]
                                         for key in ("reservation_digest", "manifest_digest")})
        with self.assertRaisesRegex(ValueError, "retained_operator_membership_binding_required"):
            run_retained_reservation(legacy, self.engine, self.local, self.remote, self.store)
        self.assertFalse(self.service.batches)
        self.assertIsNone(self.store.load_optional(item.admission["reservation_digest"]))

    def test_operator_refuses_company_owner_drift_before_local_application(self):
        item, runtime = self.freeze_operator()
        self.local.import_rows("Companies", [(2, {**item.company, "Active Cycle ID": "other-cycle"})])
        with self.assertRaisesRegex(ValueError, "retained_operator_company_row_changed"):
            self.run_operator(item, runtime)
        self.assertFalse(self.service.batches)
        self.assertFalse(self.local.read("Job History"))

    def test_operator_borrows_writer_lock_and_terminal_check_uses_other_receipts(self):
        item, runtime = self.freeze_operator()
        reservation = item.admission["reservation_digest"]
        with writer_lock(self.root / "scraper.lock"), writer_lock(self.root / "writer.lock"):
            result = _run_retained_reservation_locked(
                item, self.engine, self.local, self.remote, self.store, membership_only=True,
                runtime_binding=runtime, writer_already_held=True)
        self.assertEqual("FIRST_PASS_RELEASED", result["publication"]["state"])
        session = self.store.load(reservation)
        fields = ("request_id", "company_id", "source_revision", "cycle_id", "state", "plan", "plan_digest",
                  "projection_digest", "receipt_id", "intent_id", "acknowledgement_id")
        evidence = {key: session[key] for key in fields}
        with (writer_lock(self.root / "scraper.lock"),
              closing(SQLiteRepository(self.local.path, "fixture", readonly=True)) as reader):
            queue = _verify_operator_terminal_receipt(reservation, evidence, reader, runtime_binding=runtime)
            self.assertEqual(result["publication"]["first_pass"], queue)
            for field in ("receipt_id", "intent_id", "acknowledgement_id"):
                with self.subTest(field=field), self.assertRaisesRegex(
                        ValueError, "retained_operator_terminal_receipt_changed"):
                    _verify_operator_terminal_receipt(
                        reservation, {**evidence, field: digest("substituted")}, reader,
                        runtime_binding=runtime)
        with self.local.transaction():
            self.local.db.execute("DELETE FROM exact_local_acknowledgements")
        with (writer_lock(self.root / "scraper.lock"),
              closing(SQLiteRepository(self.local.path, "fixture", readonly=True)) as reader,
              self.assertRaisesRegex(ValueError, "retained_operator_terminal_local_acknowledgement_changed")):
            _verify_operator_terminal_receipt(reservation, evidence, reader, runtime_binding=runtime)


if __name__ == "__main__":
    unittest.main()
