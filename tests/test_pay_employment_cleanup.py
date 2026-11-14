import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.core import material_hash, pack_snapshot
from job_search_helper.location_cleanup import plan_cleanup, publish_cleanup
from job_search_helper.screening_cleanup import saved_screening_evidence, screening_reason, MARKER
from job_search_helper.repository import MemoryRepository, GoogleRepository, SCHEMAS
from job_search_helper.sheet_profile import COMPACT_SCHEMAS, COMPACT_PROFILE
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


def job(key="hourly", **changes):
    posting = {"title": "Data Collection Quality Support - Pilot Support Team", "posting_id": key,
               "url": "https://example.com/jobs/" + key, "location": "San Jose, CA", "compensation": "",
               "description": "The US base salary range starts at $32/hr day shift, $34/hr night shift.",
               "ats": "Greenhouse"}
    source = material_hash(posting)
    return {"Company": "Fixture", "Job Key": key, "Job Title": posting["title"],
            "Official Job URL": posting["url"], "Location": posting["location"], "Salary / Range": "",
            "Source Hash": source, "Current Snapshot": pack_snapshot({"v": 1, "pending": posting, "evaluated": None, "evaluations": []}),
            "Job Status": "Open and verified", "Added to Opportunities?": "Pending", "Review Status": "Needs Review",
            "Review Notes": "Keep notes", **changes}


def plan(repo, **kwargs):
    return plan_cleanup(repo, evidence=saved_screening_evidence(repo), reason_fn=screening_reason, marker=MARKER, **kwargs)


class ScreeningCleanupTests(unittest.TestCase):
    def test_command_loads_config_before_read_only_preview(self):
        from job_search_helper.screening_cleanup import main
        from job_search_helper.cli import PROJECT_ROOT
        with patch("sys.argv", ["screening_cleanup"]), patch("job_search_helper.cli.load_environment", autospec=True) as load, patch("job_search_helper.screening_cleanup.execute_cleanup") as execute:
            main()
        load.assert_called_once_with(PROJECT_ROOT / ".env")
        self.assertFalse(execute.call_args.args[0].apply)

    def test_exact_saved_source_becomes_no_with_audit_note(self):
        repo = MemoryRepository({"Job History": [job()]})
        before = copy.deepcopy(repo.tables)
        operations, _, _ = plan(repo)
        self.assertEqual(repo.tables, before)
        self.assertEqual(len(operations), 1)
        repo.commit(operations)
        row = repo.read("Job History")[0]
        self.assertEqual(row["Added to Opportunities?"], "No")
        self.assertEqual(row["Description Hash"], row["Source Hash"])
        self.assertIn("$70,720", row["Rejection Reason"])
        self.assertIn("Keep notes", row["Review Notes"])
        self.assertIn(MARKER, row["Review Notes"])
        self.assertEqual(plan(repo)[0], [])

    def test_choices_claims_opportunities_and_changed_source_are_protected(self):
        for changes in ({"Added to Opportunities?": "Yes"}, {"Added to Opportunities?": "No"},
                        {"Added to Opportunities?": "Manual Review"}, {"Review Started At": "claimed"},
                        {"Review Status": "Reviewed"}, {"Source Hash": "changed"},
                        {"Official Job URL": "https://example.com/changed"}, {"Reconsideration Count": 2},
                        {"Current Snapshot": ""}, {"Job Status": "Closed"}):
            with self.subTest(changes=changes):
                self.assertEqual(plan(MemoryRepository({"Job History": [job(**changes)]}))[0], [])
        self.assertEqual(plan(MemoryRepository({"Job History": [job()]}), protected_keys={"hourly"})[0], [])
        self.assertEqual(plan(MemoryRepository({"Job History": [job(), job()]}))[0], [])
        repo = MemoryRepository({"Job History": [job()], "Opportunities": [{"Company": "Fixture", "Job URL": job()["Official Job URL"]}]})
        self.assertEqual(plan(repo)[0], [])

    def test_live_source_change_invalidates_plan(self):
        repo = MemoryRepository({"Job History": [job()]})
        operations, _, _ = plan(repo)
        repo.commit([{"tab": "Job History", "identity": {"Job Key": "hourly"}, "values": {"Source Hash": "new"}}])
        with self.assertRaises(Exception):
            repo.commit(operations)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.local = SQLiteRepository(Path(self.temp.name) / "jobs.sqlite3", "fixture", initialize=True)
        self.addCleanup(self.local.close)
        full = MemoryRepository({"Job History": [job(), job("protected", **{"Added to Opportunities?": "Yes"})]})
        for tab in SCHEMAS:
            self.local.import_rows(tab, enumerate(full.read(tab), 2))
        with self.local.transaction():
            self.local.set_meta("ready", "yes")
            self.local.set_meta("sheets_profile", COMPACT_PROFILE)
        service = RangeSheets(full.tables, schemas=COMPACT_SCHEMAS)
        self.remote = GoogleRepository(service, "fixture", min_request_interval=0, schemas=COMPACT_SCHEMAS)
        self.evidence = saved_screening_evidence(self.local)

    def publish(self):
        self.evidence = saved_screening_evidence(self.local)
        return publish_cleanup(self.local, self.remote, evidence=self.evidence, reason_fn=screening_reason, marker=MARKER)

    def test_verified_scoped_delivery_and_idempotence(self):
        before = self.remote.read("Job History")[1]
        report = self.publish()
        self.assertEqual((report["changed"], report["verified"]), (1, 1))
        self.assertEqual(self.remote.read("Job History")[1], before)
        self.assertEqual(self.publish()["verified"], 0)

    def test_lost_response_reconciles_own_write(self):
        original = self.remote.commit
        def lost(operations):
            original(operations)
            raise RuntimeError("response lost")
        with patch.object(self.remote, "commit", side_effect=lost):
            self.assertEqual(self.publish()["verified"], 1)
        self.assertEqual(self.local.db.execute("select count(*) from manual_choices").fetchone()[0], 0)

    def test_failed_publication_rebuilds_evidence_and_retries_once(self):
        with patch.object(self.remote, "commit", side_effect=RuntimeError("offline")):
            self.assertEqual(self.publish()["verified"], 0)
        self.assertEqual(self.publish()["verified"], 1)
        self.assertEqual(self.remote.read("Job History")[0]["Review Notes"].count(MARKER), 1)

    def test_concurrent_yes_is_preserved(self):
        original = self.remote.commit
        def race(operations):
            original([{"tab": "Job History", "identity": {"Job Key": "hourly"}, "values": {"Added to Opportunities?": "Yes"}}])
            return original(operations)
        with patch.object(self.remote, "commit", side_effect=race):
            self.assertEqual(self.publish()["verified"], 0)
        self.assertEqual(self.remote.read("Job History")[0]["Added to Opportunities?"], "Yes")
