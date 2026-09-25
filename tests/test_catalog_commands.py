from contextlib import redirect_stderr, redirect_stdout
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper import local_cli as cli
from job_search_helper.ats import Inventory
from job_search_helper.catalog_queries import CatalogQueries
from job_search_helper.database import Database
from job_search_helper.models import JobPosting
from job_search_helper.repositories import ApplicationRepository, CatalogRepository
from job_search_helper.scan_lock import scan_lock


class CatalogCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "data/job-search-helper.sqlite3"
        self.database = Database.initialize(self.path)
        self.addCleanup(self.database.close)
        self.catalog = CatalogRepository(self.database)
        self.company = self.catalog.add_company("Acme", company_id="001")
        self.source = self.catalog.add_source(self.company, "Greenhouse", "acme", "https://boards.greenhouse.io/acme")
        self.job = self.catalog.create_job(self.company, JobPosting(posting_id="001", title="Systems Engineer",
            url="https://example.com/job/001", description="Full description\n" * 4000,
            source_created_raw="2026-09-25T08:30:00-04:00"), source_id=self.source)

    def run_command(self, arguments, *, machine=True):
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(output), redirect_stderr(errors), \
                patch.dict("sys.modules", {"job_search_helper.cli": None, "job_search_helper.repository": None}):
            result = cli.main([*arguments, "--workspace", str(self.root), *(["--json"] if machine else [])])
        return result, json.loads(output.getvalue()) if machine else output.getvalue(), errors.getvalue()

    def app(self):
        code, result, _ = self.run_command(["local", "applications", "add", "--job-id", self.job, "--notes", "Saved note", "--resume-used", "v2"])
        self.assertEqual(code, 0, result)
        return result["application"]

    def test_application_add_update_show_and_clear_preserve_unspecified_fields(self):
        app = self.app()
        self.assertEqual(app["application_status"], "interested")
        self.assertIsNone(app["date_applied"])
        code, result, _ = self.run_command(["local", "applications", "update", app["application_id"],
            "--expected-version", "1", "--status", "applied", "--date-applied", "2026-09-25"])
        self.assertEqual(code, 0, result)
        updated = result["application"]
        self.assertEqual(updated["notes"], "Saved note")
        self.assertEqual(updated["resume_used"], "v2")
        self.assertEqual(updated["company_name"], "Acme")
        self.assertEqual(updated["title"], "Systems Engineer")
        self.assertEqual(len(updated["events"]), 2)
        code, result, _ = self.run_command(["local", "applications", "update", app["application_id"],
            "--expected-version", "2", "--clear-date-applied", "--clear-notes"])
        self.assertEqual(code, 0, result)
        self.assertIsNone(result["application"]["date_applied"])
        self.assertEqual(result["application"]["notes"], "")
        self.assertEqual(result["application"]["resume_used"], "v2")
        code, result, _ = self.run_command(["local", "applications", "show", app["application_id"]])
        self.assertEqual(len(result["application"]["events"]), 3)

    def test_stale_application_edits_and_invalid_dates_leave_records_and_history_unchanged(self):
        app = self.app()
        for arguments in (["--expected-version", "9", "--notes", "Stale"],
                          ["--expected-version", "1", "--date-applied", "2026-02-30"],
                          ["--expected-version", "1", "--date-applied", "09/25/2026"],
                          ["--expected-version", "1"]):
            code, result, _ = self.run_command(["local", "applications", "update", app["application_id"], *arguments])
            self.assertEqual(code, 2, result)
        self.assertEqual(CatalogQueries(self.database).application(app["application_id"]), app)

    def test_duplicate_open_application_gives_existing_id_and_terminal_attempts_remain(self):
        app = self.app()
        code, result, _ = self.run_command(["local", "applications", "add", "--job-id", self.job])
        self.assertEqual(code, 2)
        self.assertIn(app["application_id"], result["error"])
        self.run_command(["local", "applications", "update", app["application_id"], "--expected-version", "1", "--status", "withdrawn"])
        second = self.app()
        self.assertNotEqual(app["application_id"], second["application_id"])
        code, result, _ = self.run_command(["local", "applications", "update", app["application_id"],
            "--expected-version", "2", "--status", "interviewing"])
        self.assertEqual(code, 2)
        self.assertIn(second["application_id"], result["error"])

    def test_applied_status_does_not_invent_application_date(self):
        code, result, _ = self.run_command(["local", "applications", "add", "--job-id", self.job, "--status", "applied"])
        self.assertEqual(code, 0)
        self.assertIsNone(result["application"]["date_applied"])

    def test_company_edits_preserve_source_and_use_optimistic_versions(self):
        code, result, _ = self.run_command(["local", "companies", "update", self.company, "--expected-version", "1",
            "--status", "paused", "--notes", "Follow up later", "--name", "Renamed"])
        self.assertEqual(code, 0, result)
        company = result["company"]
        self.assertEqual(company["source_id"], self.source)
        self.assertEqual(company["company_name"], "Renamed")
        self.assertEqual(company["status"], "paused")
        code, result, _ = self.run_command(["local", "companies", "update", self.company, "--expected-version", "1", "--notes", "Stale"])
        self.assertEqual(code, 2)
        self.assertEqual(CatalogQueries(self.database).company(self.company), company)
        code, result, _ = self.run_command(["local", "companies", "update", self.company, "--expected-version", "2", "--clear-notes"])
        self.assertEqual(code, 0)
        self.assertEqual(result["company"]["notes"], "")

    def test_lists_include_closed_paused_and_archived_records_unless_filtered(self):
        self.catalog.update_company(self.company, expected_version=1, status="paused")
        self.database.connection.execute("UPDATE jobs SET lifecycle_status='closed' WHERE job_id=?", (self.job,))
        ApplicationRepository(self.database).add(self.job, status="archived")
        for kind in ("companies", "jobs", "applications"):
            code, result, _ = self.run_command(["local", kind, "list"])
            self.assertEqual(code, 0, result)
            self.assertEqual(result["total"], 1)
        code, result, _ = self.run_command(["local", "jobs", "list", "--status", "active"])
        self.assertEqual(result["items"], [])
        code, result, _ = self.run_command(["local", "jobs", "list", "--status", "closed", "--search", "Systems", "--company-id", "001"])
        self.assertEqual(result["items"][0]["job_id"], self.job)

    def test_pagination_totals_and_search_are_predictable(self):
        self.catalog.add_company("Second", company_id="002")
        code, result, _ = self.run_command(["local", "companies", "list", "--limit", "1", "--offset", "1"])
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["items"][0]["company_id"], "002")
        code, result, _ = self.run_command(["local", "companies", "list", "--limit", "0"])
        self.assertEqual(code, 2)
        code, result, _ = self.run_command(["local", "jobs", "list", "--search", "% OR 1=1"])
        self.assertEqual(result["total"], 0)

    def test_show_keeps_full_evidence_and_text_output_displays_readable_dates(self):
        code, result, _ = self.run_command(["local", "jobs", "show", self.job])
        self.assertEqual(code, 0)
        self.assertEqual(result["job"]["description"], "Full description\n" * 4000)
        code, output, _ = self.run_command(["local", "jobs", "show", self.job], machine=False)
        self.assertIn("2026-09-25 12:30:00 UTC", output)
        self.assertIn("Systems Engineer", output)
        self.assertIn("Acme", output)

    def test_queries_and_status_are_read_only_and_latest_application_is_deterministic(self):
        app = self.app()
        before = self.path.read_bytes()
        for arguments in (["companies", "list"], ["companies", "show", self.company],
                          ["jobs", "list"], ["jobs", "show", self.job],
                          ["applications", "list"], ["applications", "show", app["application_id"]]):
            code, result, _ = self.run_command(["local", *arguments])
            self.assertEqual(code, 0, result)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(CatalogQueries(self.database).job(self.job)["application_id"], app["application_id"])

    def test_missing_records_and_empty_edit_have_clear_errors(self):
        for kind in ("companies", "jobs", "applications"):
            code, result, _ = self.run_command(["local", kind, "show", "missing"])
            self.assertEqual(code, 2)
            self.assertIn("not found", result["error"])
        code, result, _ = self.run_command(["local", "companies", "update", self.company, "--expected-version", "1"])
        self.assertEqual(code, 2)

    def test_import_cli_preview_apply_conflicts_and_coordinator_lock(self):
        path = self.root / "companies.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Company Name", "Careers URL", "Notes"])
            writer.writerow(["New Company", "https://jobs.lever.co/new-company", "Imported"])
        before = self.path.read_bytes()
        code, preview, _ = self.run_command(["local", "import-companies", "companies.csv"])
        self.assertEqual(code, 0, preview)
        self.assertFalse(preview["applied"])
        self.assertEqual(before, self.path.read_bytes())
        with scan_lock(self.path):
            code, result, _ = self.run_command(["local", "import-companies", "companies.csv", "--apply"])
        self.assertEqual(code, 3, result)
        code, result, _ = self.run_command(["local", "import-companies", "companies.csv", "--apply"])
        self.assertEqual(code, 0, result)
        self.assertTrue(result["applied"])
        code, result, _ = self.run_command(["local", "import-companies", "companies.csv", "--apply"])
        self.assertEqual(result["counts"]["unchanged"], 1)
        path.write_text("Company Name,Careers URL\nBad,http://localhost\n", encoding="utf-8")
        code, result, _ = self.run_command(["local", "import-companies", "companies.csv", "--apply"])
        self.assertEqual(code, 2)
        self.assertFalse(result["applied"])

    def test_import_scan_application_workflow_end_to_end_without_legacy_state(self):
        path = self.root / "new.csv"
        path.write_text("Company Name,Careers URL\nNew Co,https://jobs.lever.co/new-co\n", encoding="utf-8")
        code, imported, _ = self.run_command(["local", "import-companies", "new.csv", "--apply"])
        company = imported["rows"][0]["company_id"]
        with patch("job_search_helper.local_scanner.fetch_inventory", return_value=Inventory("complete", [
            {"posting_id": "002", "title": "Imported Company Role", "created_at": "2026-09-25", "url": "https://example.com/jobs/002"}])):
            code, result, _ = self.run_command(["local", "scan", "--company-id", company])
        self.assertEqual(code, 0, result)
        code, result, _ = self.run_command(["local", "jobs", "list", "--company-id", company])
        job = result["items"][0]["job_id"]
        code, result, _ = self.run_command(["local", "applications", "add", "--job-id", job, "--status", "applied", "--date-applied", "2026-09-25"])
        self.assertEqual(code, 0, result)
        self.assertEqual(result["application"]["company_name"], "New Co")
        self.assertFalse((self.root / ".state").exists())

    def test_terminal_controls_are_visible_text_not_executed(self):
        self.catalog.update_company(self.company, expected_version=1, notes="before\x1b[2Jafter")
        code, output, _ = self.run_command(["local", "companies", "show", self.company], machine=False)
        self.assertEqual(code, 0)
        self.assertNotIn("\x1b", output)
        self.assertIn("\\x1b[2J", output)

    def test_company_view_distinguishes_last_attempt_from_last_success(self):
        with patch("job_search_helper.local_scanner.fetch_inventory", return_value=Inventory("complete", [{"posting_id": "001"}])):
            self.run_command(["local", "scan", "--company-id", self.company])
        first = CatalogQueries(self.database).company(self.company)
        with patch("job_search_helper.local_scanner.fetch_inventory", return_value=Inventory("blocked", reason="Access denied")):
            self.run_command(["local", "scan", "--company-id", self.company])
        second = CatalogQueries(self.database).company(self.company)
        self.assertEqual(second["last_scan_result"], "blocked")
        self.assertEqual(second["last_scan_reason"], "Access denied")
        self.assertEqual(second["last_successful_scan_at"], first["last_successful_scan_at"])
        self.assertGreaterEqual(second["last_scan_at"], second["last_successful_scan_at"])

    def test_views_do_not_create_a_missing_catalog(self):
        missing = self.root / "missing"
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli.main(["local", "jobs", "list", "--workspace", str(missing), "--json"])
        self.assertEqual(code, 2)
        self.assertFalse(missing.exists())
