from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from job_search_helper.engine import Engine, State
from job_search_helper.repository import GoogleRepository, MemoryRepository, SCHEMAS
from job_search_helper.retained_session_store import RetainedSessionStore
from job_search_helper.retained_work_orchestrator import run_retained_reservation
from job_search_helper.retained_work_runner import (
    PreparedExceptionalStart, _StartJournal, _TOKEN,
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
                 request["company_event"]["event_id"], "COMP-NEW", "manifest",
                 binding_digest, "FROZEN"))
        return binding

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


if __name__ == "__main__":
    unittest.main()
