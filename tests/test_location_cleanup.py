import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.location_cleanup import MARKER, plan_cleanup, publish_cleanup
from job_search_helper.repository import MemoryRepository, GoogleRepository, SCHEMAS
from job_search_helper.sheet_profile import COMPACT_SCHEMAS, COMPACT_PROFILE
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


def job(key="foreign", **changes):
    return {"Company": "Fixture", "Job Key": key, "Job Title": "Field Service Engineer",
            "Official Job URL": "https://example.com/jobs/" + key, "Location": "Hachioji, Japan",
            "Source Hash": "source-" + key, "Job Status": "Open and verified",
            "Added to Opportunities?": "Pending", "Review Status": "Needs Review",
            "Review Notes": "Keep personal notes", "First Seen": "2026-01-01", **changes}


class CleanupTests(unittest.TestCase):
    def test_dry_run_then_idempotent_auditable_rejection(self):
        repo = MemoryRepository({"Job History": [job()]})
        before = copy.deepcopy(repo.tables)
        operations, targets, _ = plan_cleanup(repo)
        self.assertEqual(repo.tables, before)
        self.assertEqual(len(targets), 1)
        repo.commit(operations)
        row = repo.read("Job History")[0]
        self.assertEqual(row["Added to Opportunities?"], "No")
        self.assertEqual(row["Decision"], "Reject")
        self.assertIn("Japan", row["Rejection Reason"])
        self.assertIn("Keep personal notes", row["Review Notes"])
        self.assertEqual(row["Review Notes"].count(MARKER), 1)
        self.assertEqual(row["First Seen"], "2026-01-01")
        self.assertEqual(row["Job Status"], "Open and verified")
        self.assertEqual(plan_cleanup(repo)[0], [])

    def test_preserve_choices_locks_territories_unknowns_and_us_alternatives(self):
        cases = [{"Added to Opportunities?": v} for v in ("Yes", "No", "Manual Review", "")]
        cases += [{"Review Status": "In Progress"}, {"Review Status": "Manual Review"},
                  {"Review Started At": "claimed"}, {"Location": "Remote"}, {"Location": "Guam"},
                  {"Location": "Hachioji, Japan; Austin, TX"}, {"Source Hash": ""}]
        for changes in cases:
            with self.subTest(changes=changes):
                repo = MemoryRepository({"Job History": [job(**changes)]})
                self.assertEqual(plan_cleanup(repo)[0], [])
        repo = MemoryRepository({"Job History": [job()]})
        self.assertEqual(plan_cleanup(repo, protected_keys={"foreign"})[0], [])

    def test_existing_opportunities_and_duplicate_keys_are_protected(self):
        repo = MemoryRepository({"Job History": [job()], "Opportunities": [{
            "Company": "Fixture", "Job URL": job()["Official Job URL"], "Application Status": "Applied"}]})
        self.assertEqual(plan_cleanup(repo)[0], [])
        repo = MemoryRepository({"Job History": [job(), job()]})
        self.assertEqual(plan_cleanup(repo)[0], [])

    def test_a_concurrent_location_or_choice_edit_invalidates_plan(self):
        for changes in ({"Location": "Austin, TX"}, {"Added to Opportunities?": "Yes"}, {"Source Hash": "new"}):
            repo = MemoryRepository({"Job History": [job()]})
            operations, _, _ = plan_cleanup(repo)
            repo.commit([{"tab": "Job History", "identity": {"Job Key": "foreign"}, "values": changes}])
            with self.assertRaises(Exception):
                repo.commit(operations)
            self.assertEqual(repo.read("Job History")[0]["Review Status"], "Needs Review")


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.local = SQLiteRepository(Path(self.temp.name) / "jobs.sqlite3", "fixture", initialize=True)
        self.addCleanup(self.local.close)
        full = MemoryRepository({"Job History": [job(), job("us", Location="Austin, TX")]})
        for tab in SCHEMAS:
            self.local.import_rows(tab, enumerate(full.read(tab), 2))
        with self.local.transaction():
            self.local.set_meta("ready", "yes")
            self.local.set_meta("sheets_profile", COMPACT_PROFILE)
        self.service = RangeSheets(full.tables, schemas=COMPACT_SCHEMAS)
        self.remote = GoogleRepository(self.service, "fixture", min_request_interval=0, schemas=COMPACT_SCHEMAS)

    def test_compact_publication_changes_only_target_job_and_verifies(self):
        before = copy.deepcopy(self.remote.read("Job History")[1])
        result = publish_cleanup(self.local, self.remote)
        self.assertEqual((result["changed"], result["verified"]), (1, 1))
        self.assertIsNone(result["error"])
        after = self.remote.read("Job History")
        self.assertEqual(after[0]["Added to Opportunities?"], "No")
        self.assertIn("Japan", after[0]["Rejection Reason"])
        self.assertEqual(after[1], before)
        self.assertEqual(publish_cleanup(self.local, self.remote)["verified"], 0)

    def test_live_manual_yes_or_new_location_prevents_local_change(self):
        for field, value in (("Added to Opportunities?", "Yes"), ("Location", "Austin, TX")):
            with patch.object(self.remote, "read_columns", wraps=self.remote.read_columns) as read:
                original = read._mock_wraps
                def changed(tab, fields):
                    rows = original(tab, fields)
                    if tab == "Job History":
                        rows[0][1][field] = value
                    return rows
                read.side_effect = changed
                self.assertEqual(publish_cleanup(self.local, self.remote)["changed"], 0)
            self.assertEqual(self.local.read("Job History")[0]["Added to Opportunities?"], "Pending")

    def test_failed_delivery_retries_without_duplicate_notes(self):
        with patch.object(self.remote, "commit", side_effect=RuntimeError("offline")):
            self.assertEqual(publish_cleanup(self.local, self.remote)["verified"], 0)
        result = publish_cleanup(self.local, self.remote)
        self.assertEqual(result["verified"], 1)
        self.assertEqual(self.remote.read("Job History")[0]["Review Notes"].count(MARKER), 1)

    def test_us_location_edit_during_delivery_invalidates_cleanup_guard(self):
        original = self.remote.commit
        def race(operations):
            original([{"tab": "Job History", "identity": {"Job Key": "foreign"},
                       "values": {"Location": "Austin, TX"}}])
            return original(operations)
        with patch.object(self.remote, "commit", side_effect=race):
            report = publish_cleanup(self.local, self.remote)
        row = self.remote.read("Job History")[0]
        self.assertEqual(row["Location"], "Austin, TX")
        self.assertEqual(row["Added to Opportunities?"], "Pending")
        self.assertEqual(row["Review Status"], "Needs Review")
        self.assertEqual(report["verified"], 0)
        self.assertIsNotNone(report["error"])

    def test_lost_response_is_verified_without_creating_manual_decision(self):
        original = self.remote.commit
        def lost(operations):
            original(operations)
            raise RuntimeError("response lost")
        with patch.object(self.remote, "commit", side_effect=lost):
            self.assertEqual(publish_cleanup(self.local, self.remote)["verified"], 1)
        self.assertEqual(self.local.db.execute("SELECT count(*) FROM manual_choices").fetchone()[0], 0)

    def test_concurrent_live_yes_is_not_overwritten(self):
        original = self.remote.commit
        def race(operations):
            original([{"tab": "Job History", "identity": {"Job Key": "foreign"},
                       "values": {"Added to Opportunities?": "Yes"}}])
            return original(operations)
        with patch.object(self.remote, "commit", side_effect=race):
            self.assertEqual(publish_cleanup(self.local, self.remote)["verified"], 0)
        self.assertEqual(self.remote.read("Job History")[0]["Added to Opportunities?"], "Yes")


if __name__ == "__main__":
    unittest.main()
