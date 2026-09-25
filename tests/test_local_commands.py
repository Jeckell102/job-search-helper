from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper import local_cli as cli
from job_search_helper.database import Database
from job_search_helper.ats import Inventory
from job_search_helper.repositories import CatalogRepository
from job_search_helper.scan_service import ScanService


class LocalCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_command(self, arguments):
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(output), redirect_stderr(errors), \
                patch.dict("sys.modules", {"job_search_helper.cli": None, "job_search_helper.repository": None}):
            result = cli.main([*arguments, "--workspace", str(self.root), "--json"])
        return result, json.loads(output.getvalue()), errors.getvalue()

    def test_init_doctor_backup_and_migrate_without_profiles_or_google(self):
        for arguments in (["init"], ["doctor"], ["backup", "backups/first.sqlite3"], ["db", "migrate"]):
            with self.subTest(arguments=arguments):
                status, value, error = self.run_command(arguments)
                self.assertEqual(status, 0, error or value)
                self.assertTrue(value["ok"])
        with Database(self.root / "backups/first.sqlite3", readonly=True) as backup:
            self.assertTrue(backup.check()["ok"])
        self.assertFalse((self.root / "config").exists())
        self.assertFalse((self.root / ".state").exists())

    def test_doctor_missing_workspace_is_read_only(self):
        self.root = self.root / "does-not-exist"
        status, result, _ = self.run_command(["doctor"])
        self.assertEqual(status, 2)
        self.assertFalse(result["ok"])
        self.assertFalse(self.root.exists())

    def test_init_refuses_legacy_recovery_database(self):
        path = self.root / "old.db"
        path.write_bytes(b"existing recovery data")
        status, result, _ = self.run_command(["init", "--database", "old.db"])
        self.assertEqual(status, 2)
        self.assertFalse(result["ok"])
        self.assertEqual(path.read_bytes(), b"existing recovery data")

    def test_backup_missing_database_does_not_create_output(self):
        status, _, _ = self.run_command(["backup", "backups/missing.sqlite3"])
        self.assertEqual(status, 2)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_backup_existing_destination_is_preserved(self):
        self.run_command(["init"])
        self.run_command(["backup", "backups/first.sqlite3"])
        path = self.root / "backups/first.sqlite3"
        before = path.read_bytes()
        status, _, _ = self.run_command(["backup", "backups/first.sqlite3"])
        self.assertEqual(status, 2)
        self.assertEqual(path.read_bytes(), before)

    def test_explicit_missing_settings_returns_actionable_error(self):
        status, result, _ = self.run_command(["init", "--settings", "missing.toml"])
        self.assertEqual(status, 2)
        self.assertIn("Cannot read settings", result["error"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_custom_database_path_is_workspace_relative(self):
        status, result, _ = self.run_command(["init", "--database", "custom/catalog.sqlite3"])
        self.assertEqual(status, 0)
        self.assertEqual(result["database"], str(self.root / "custom/catalog.sqlite3"))

    def test_text_output_is_clear_without_json(self):
        output = io.StringIO()
        with redirect_stdout(output), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cli.main(["init", "--workspace", str(self.root)]), 0)
        self.assertIn("Local catalog ready", output.getvalue())

    def add_fixture_company(self):
        self.run_command(["init"])
        with Database(self.root / "data/job-search-helper.sqlite3") as database:
            catalog = CatalogRepository(database)
            company = catalog.add_company("Fixture", company_id="001")
            catalog.add_source(company, "Greenhouse", "fixture", "https://boards.greenhouse.io/fixture")

    def test_local_scan_status_and_resume_use_local_database_only(self):
        self.add_fixture_company()
        with patch("job_search_helper.local_scanner.fetch_inventory", return_value=Inventory("complete", [{"posting_id": "001"}])) as fetch:
            code, result, _ = self.run_command(["local", "scan", "--company-id", "001"])
        self.assertEqual(code, 0, result)
        self.assertEqual(fetch.call_count, 1)
        cycle = result["cycle"]["cycle_id"]
        before = (self.root / "data/job-search-helper.sqlite3").read_bytes()
        code, result, _ = self.run_command(["local", "status", "--cycle", cycle])
        self.assertEqual(code, 0, result)
        self.assertEqual(before, (self.root / "data/job-search-helper.sqlite3").read_bytes())
        with patch("job_search_helper.local_scanner.fetch_inventory", side_effect=AssertionError("Refetched complete cycle")):
            code, result, _ = self.run_command(["local", "resume", "--cycle", cycle])
        self.assertEqual(code, 0, result)
        self.assertFalse((self.root / ".state").exists())

    def test_partial_scan_exit_code_and_explicit_retry(self):
        self.add_fixture_company()
        with patch("job_search_helper.local_scanner.fetch_inventory", return_value=Inventory("blocked", reason="Access denied")):
            code, result, _ = self.run_command(["local", "scan", "--all"])
        self.assertEqual(code, 1)
        cycle = result["cycle"]["cycle_id"]
        with patch("job_search_helper.local_scanner.fetch_inventory", return_value=Inventory("complete")):
            code, result, _ = self.run_command(["local", "resume", "--cycle", cycle, "--retry-exceptions"])
        self.assertEqual(code, 0, result)

    def test_local_status_missing_database_does_not_create_it(self):
        code, result, _ = self.run_command(["local", "status"])
        self.assertEqual(code, 2)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_doctor_reports_pending_work(self):
        self.add_fixture_company()
        with Database(self.root / "data/job-search-helper.sqlite3") as database:
            service = ScanService(database)
            cycle = service.start_cycle(["001"])
            attempt = service.begin_attempt(cycle, "001")
            service.stage_inventory(attempt, Inventory("complete"))
        code, result, _ = self.run_command(["doctor"])
        self.assertEqual(code, 0)
        self.assertEqual(result["scan_recovery"], {"pending": 1, "quarantined": 0, "unfinished_cycles": 1})
