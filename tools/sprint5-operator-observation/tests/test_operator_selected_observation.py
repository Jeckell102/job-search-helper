from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from job_search_helper.engine import Engine, State
from job_search_helper.operator_company_request import _digest, queue_operator_company_request
from job_search_helper.operator_selected_observation import read_operator_selected_observation
from job_search_helper.repository import SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.scan_request import requested_scan


RUNTIME = {"state": "NO_RELEASE", "source_manifest_sha256": "a" * 64}


def company(**changes):
    row = {
        "Company": "Amphenol Aerospace", "Company ID": "COMP-0490", "Company Status": "Active",
        "Official Careers URL": "https://amphenol-aerospace.acquiretm.com/home.aspx",
        "ATS / Source": "AcquireTM",
    }
    row.update(changes)
    return row


class OperatorSelectedObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.jobs = self.root / "jobs.sqlite3"
        self.repo = SQLiteRepository(self.jobs, "test-sheet", initialize=True)
        self.addCleanup(self.repo.close)
        self.repo.set_meta("ready", "yes")
        for tab in SCHEMAS:
            self.repo.import_rows(tab, enumerate([company()] if tab == "Companies" else [], 2))
        self.request_id = "operator-amphenol-owned"
        queue_operator_company_request(
            self.repo, self.root, "COMP-0490", self.request_id,
            now=datetime(2026, 11, 21, tzinfo=timezone.utc),
        )
        self.request = json.loads((self.root / "next-scan.json").read_text())
        self.digest = _digest(self.request)
        initial_state = State(self.root / "state.db")
        initial_state.close()

    def readers(self):
        repo = SQLiteRepository(self.jobs, "test-sheet", readonly=True)
        state = State(self.root / "state.db", readonly=True)
        self.addCleanup(repo.close)
        self.addCleanup(state.close)
        return repo, state

    def observe(self):
        repo, state = self.readers()
        return read_operator_selected_observation(repo, state, RUNTIME, request_sha256=self.digest)

    def admit(self):
        state = State(self.root / "state.db")
        try:
            return requested_scan(Engine(self.repo, state, runtime_binding=RUNTIME), state, self.root / "state.db")
        finally:
            state.close()

    def test_queued_receipt_and_current_company_are_read_back(self):
        result = self.observe()
        self.assertEqual(result["state"], "QUEUED")
        self.assertEqual(result["company_id"], "COMP-0490")
        self.assertEqual(result["request_sha256"], self.digest)

    def test_admitted_cycle_and_mirror_are_exact(self):
        cycle_id = self.admit()
        result = self.observe()
        self.assertEqual(result["state"], "ADMITTED")
        self.assertEqual(result["cycle"]["id"], cycle_id)
        self.assertEqual(result["mirror"]["Cycle ID"], cycle_id)

    def test_rejects_receipt_digest_and_source_drift(self):
        with self.assertRaisesRegex(ValueError, "request_ambiguous"):
            self.observe_with("b" * 64)
        path = next((self.root / "operator-company-requests" / "receipts").glob("*.json"))
        receipt = json.loads(path.read_text())
        receipt["source_revision"] = "c" * 64
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "receipt_invalid"):
            self.observe()
        self.repo.import_rows("Companies", enumerate([company(**{"Official Careers URL": "https://changed.example.test"})], 2))
        path.write_text(json.dumps({**receipt, "source_revision": self.request["source_revision"]}))
        with self.assertRaisesRegex(ValueError, "company_not_current"):
            self.observe()

    def test_ignores_foreign_malformed_receipt(self):
        foreign = self.root / "operator-company-requests" / "receipts" / ("f" * 64 + ".json")
        foreign.write_text("not-json")
        self.assertEqual(self.observe()["state"], "QUEUED")

    def test_rejects_foreign_or_non_normal_admitted_scope(self):
        cycle_id = self.admit()
        state = State(self.root / "state.db")
        try:
            cycle = state.cycle(cycle_id)
            cycle["companies"]["COMP-OTHER"] = {"company": "Other", "stage": "queued"}
            state.save_cycle(cycle)
        finally:
            state.close()
        with self.assertRaisesRegex(ValueError, "cycle_scope_invalid"):
            self.observe()

    def test_rejects_state_symlink_alias(self):
        alias = self.root / "state-alias.db"
        alias.symlink_to(self.root / "state.db")
        repo = SQLiteRepository(self.jobs, "test-sheet", readonly=True)
        state = State(alias, readonly=True)
        self.addCleanup(repo.close)
        self.addCleanup(state.close)
        with self.assertRaisesRegex(ValueError, "canonical_stores_required"):
            read_operator_selected_observation(repo, state, RUNTIME, request_sha256=self.digest)

    def test_transient_settlement_mirror_requires_explicit_opt_in(self):
        cycle_id = self.admit()
        self.repo.commit([{
            "tab": "Scan Cycles", "identity": {"Cycle ID": cycle_id},
            "values": {"Cycle Status": "Complete with exceptions"},
        }])
        with self.assertRaisesRegex(ValueError, "mirror_invalid"):
            self.observe()
        repo, state = self.readers()
        result = read_operator_selected_observation(
            repo, state, RUNTIME, request_sha256=self.digest, settlement_recovery=True)
        self.assertEqual(result["state"], "ADMITTED")

    def observe_with(self, digest):
        repo, state = self.readers()
        return read_operator_selected_observation(repo, state, RUNTIME, request_sha256=digest)


if __name__ == "__main__":
    unittest.main()
