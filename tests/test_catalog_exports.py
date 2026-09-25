from contextlib import redirect_stderr, redirect_stdout
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper import local_cli as cli
from job_search_helper.ats import Inventory
from job_search_helper.catalog_export import CatalogExporter, FILENAMES, HEADERS
from job_search_helper.company_import import CompanyImporter
from job_search_helper.csv_format import escape_cell, text_hash
from job_search_helper.database import Database
from job_search_helper.export_publish import publish_directory
from job_search_helper.models import JobPosting, new_id, utc_now
from job_search_helper.repositories import ApplicationRepository, CatalogRepository
from job_search_helper.scan_service import ScanService


POSTING = {"posting_id": "00123", "title": "Principal Engineer", "location": "Remote", "compensation": "USD 90000 annual base",
           "description": 'Full evidence, "quoted"\n' * 5000, "url": "https://example.com/jobs/00123",
           "updated_at": "2026-09-25T08:30:00-04:00", "req_id": "0009"}


class CatalogExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "data/job-search-helper.sqlite3"
        self.database = Database.initialize(self.path)
        self.addCleanup(self.database.close)
        self.connection = self.database.connection
        self.catalog = CatalogRepository(self.database)
        self.company = self.catalog.add_company('Acme, "Systems"', company_id="001")
        self.source = self.catalog.add_source(self.company, "Greenhouse", "acme", "https://boards.greenhouse.io/acme")
        self.service = ScanService(self.database)
        self.exporter = CatalogExporter(self.database)
        self.destination = self.root / "export"

    def scan(self, jobs=(), status="complete", **options):
        cycle = self.service.start_cycle([self.company], **options)
        attempt = self.service.begin_attempt(cycle, self.company)
        self.service.stage_inventory(attempt, Inventory(status, list(jobs)))
        self.assertTrue(self.service.apply_inventory(attempt))
        return cycle, attempt

    def job_id(self):
        return self.connection.execute("SELECT job_id FROM jobs WHERE source_job_id='00123'").fetchone()[0]

    def read(self, kind, destination=None):
        with ((destination or self.destination) / FILENAMES[kind]).open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def manifest(self):
        return json.loads((self.destination / "manifest.json").read_text(encoding="utf-8"))

    def command(self, arguments):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors), patch.dict(os.environ, {}, clear=True), \
                patch.dict("sys.modules", {"job_search_helper.cli": None, "job_search_helper.repository": None}):
            code = cli.main(["local", "export", *arguments, "--workspace", str(self.root), "--json"])
        return code, json.loads(output.getvalue())

    def test_four_views_have_human_first_contract_headers_and_full_evidence(self):
        self.scan([POSTING])
        ApplicationRepository(self.database).add(self.job_id(), notes="Interest, not an application")
        before = self.path.read_bytes()
        result = self.exporter.export(self.destination)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual({item["name"] for item in result["files"]}, {"Companies.csv", "Jobs.csv", "Applications.csv", "Scan Cycles.csv"})
        for kind, size in (("companies", 20), ("jobs", 30), ("applications", 17), ("cycles", 18)):
            self.assertEqual(len(self.read(kind)[0]), size)
            self.assertEqual(list(self.read(kind)[0]), list(HEADERS[kind]))
        job = self.read("jobs")[0]
        self.assertEqual(list(job)[:7], ["Job Title", "Company Name", "Location", "Work Arrangement", "Job Status", "Job URL", "Salary / Range"])
        self.assertEqual(job["Company Name"], 'Acme, "Systems"')
        self.assertEqual(job["Job Description"], POSTING["description"])
        self.assertEqual(job["Source Job ID"], "00123")
        self.assertEqual(job["Requisition ID"], "0009")
        self.assertEqual(job["Source Last Modified"], "2026-09-25 12:30:00 UTC")
        self.assertEqual(job["Screening Result"], "Not Evaluated")
        self.assertEqual(job["Fit Level"], "")
        app = self.read("applications")[0]
        self.assertEqual(app["Date Applied"], "")
        self.assertEqual(app["Job Title"], "Principal Engineer")

    def test_dates_keep_date_only_precision_and_unknown_source_dates_are_blank(self):
        self.scan([dict(POSTING, updated_at="2026-09-25")])
        self.exporter.export(self.destination, kinds=["jobs"])
        self.assertEqual(self.read("jobs")[0]["Source Last Modified"], "2026-09-25")
        self.scan([dict(POSTING, updated_at="taleo-job-id:987")])
        other = self.root / "opaque-date"
        self.exporter.export(other, kinds=["jobs"])
        self.assertEqual(self.read("jobs", other)[0]["Source Last Modified"], "")

    def test_every_status_and_all_application_attempts_are_included_by_default(self):
        self.scan([POSTING])
        apps = ApplicationRepository(self.database)
        first = apps.add(self.job_id(), status="rejected", date_applied="2026-09-24", notes="First attempt")
        second = apps.add(self.job_id(), status="applied", date_applied="2026-09-25", notes="Second attempt")
        self.scan([dict(POSTING, url="https://example.com/new-url")])
        self.scan()
        self.scan()
        self.catalog.update_company(self.company, expected_version=1, status="archived")
        manual = self.catalog.create_job(self.company, JobPosting(url="https://example.com/manual", title="Manual interest"))
        self.exporter.export(self.destination)
        self.assertEqual(self.read("companies")[0]["Status"], "archived")
        jobs = {row["Job ID"]: row for row in self.read("jobs")}
        self.assertEqual(jobs[self.job_id()]["Job Status"], "closed")
        self.assertEqual(jobs[manual]["Job Status"], "unknown")
        self.assertEqual(jobs[manual]["First Seen"], "")
        self.assertEqual(jobs[self.job_id()]["Application Status"], "applied")
        applications = {row["Application ID"]: row for row in self.read("applications")}
        self.assertEqual(set(applications), {first, second})
        self.assertEqual(applications[second]["Date Applied"], "2026-09-25")
        self.assertEqual(applications[second]["Job URL At Application"], POSTING["url"])
        self.assertEqual(applications[second]["Job URL"], "https://example.com/new-url")

    def test_company_last_attempt_is_not_confused_with_last_success_or_pending_counts(self):
        self.scan([POSTING])
        success = self.connection.execute("SELECT finished_at FROM scan_attempts").fetchone()[0]
        self.scan(status="blocked")
        self.exporter.export(self.destination, kinds=["companies"])
        company = self.read("companies")[0]
        self.assertEqual(company["Last Scan Result"], "blocked")
        self.assertEqual(company["Last Successful Scan"], success.replace("T", " ").replace("Z", " UTC"))
        cycle = self.service.start_cycle([self.company])
        self.service.begin_attempt(cycle, self.company)
        other = self.root / "pending"
        self.exporter.export(other, kinds=["companies", "cycles"])
        company = self.read("companies", other)[0]
        self.assertNotEqual(company["Last Scan"], "")
        self.assertEqual(company["Jobs Found In Last Scan"], "")
        self.assertEqual(company["Next Action"], "Resume unfinished cycle")
        self.assertEqual(self.read("cycles", other)[-1]["Companies Remaining"], "1")

    def test_cycle_metrics_deduplicate_retries_and_capture_changes_on_reopening(self):
        first, _ = self.scan([POSTING, POSTING])
        missing, attempt = self.scan()
        self.service.apply_inventory(attempt)
        retry = self.service.begin_attempt(missing, self.company, retry=True)
        self.service.stage_inventory(retry, Inventory("complete"))
        self.service.apply_inventory(retry)
        closed, _ = self.scan()
        reopened, _ = self.scan([dict(POSTING, title="Changed on reopening")])
        self.exporter.export(self.destination, kinds=["cycles"])
        rows = {row["Cycle ID"]: row for row in self.read("cycles")}
        self.assertEqual(rows[first]["Jobs Found"], "1")
        self.assertEqual(rows[first]["Jobs New"], "1")
        self.assertEqual(rows[missing]["Jobs Missing"], "1")
        self.assertEqual(rows[missing]["Jobs Closed"], "0")
        self.assertEqual(rows[closed]["Jobs Closed"], "1")
        self.assertEqual(rows[reopened]["Jobs Changed"], "1")
        self.assertEqual(rows[reopened]["Jobs New"], "0")

    def test_reopen_without_material_change_does_not_invent_a_changed_job(self):
        self.scan([POSTING])
        self.scan()
        self.scan()
        self.scan([POSTING])
        self.exporter.export(self.destination, kinds=["cycles"])
        self.assertEqual(self.read("cycles")[-1]["Jobs Changed"], "0")

    def test_exception_membership_and_company_filtered_cycle_counts(self):
        companies = [self.company]
        for index in range(4):
            company = self.catalog.add_company(f"Fixture {index}")
            self.catalog.add_source(company, "lever", f"fixture-{index}", f"https://jobs.lever.co/fixture-{index}")
            companies.append(company)
        cycle = self.service.start_cycle(all_companies=True)
        for company, status in zip(companies, ("complete", "partial", "blocked", "failed", "unsupported")):
            attempt = self.service.begin_attempt(cycle, company)
            self.service.stage_inventory(attempt, Inventory(status))
            self.service.apply_inventory(attempt)
        self.exporter.export(self.destination)
        row = self.read("cycles")[0]
        self.assertEqual([row[key] for key in ("Companies Total", "Companies Completed", "Companies Partial", "Companies Blocked", "Companies Failed", "Companies Remaining")], ["5", "1", "1", "1", "2", "0"])
        filtered = self.root / "filtered"
        self.exporter.export(filtered, company_ids=[self.company])
        self.assertEqual(len(self.read("companies", filtered)), 1)
        self.assertEqual(self.read("cycles", filtered)[0]["Companies Total"], "1")
        self.assertEqual(self.read("cycles", filtered)[0]["Companies Failed"], "0")
        self.assertEqual(json.loads((filtered / "manifest.json").read_text())["filters"]["company_ids"], [self.company])

    def test_unknown_historical_metrics_are_blank(self):
        self.connection.execute(
            "INSERT INTO scan_cycles(cycle_id, cycle_sequence, started_at, status, initiated_by, run_settings_json, application_version) "
            "VALUES (?, 1, ?, 'completed', 'import', '{}', 'unknown')", (new_id(), utc_now()))
        self.exporter.export(self.destination, kinds=["cycles"])
        row = self.read("cycles")[0]
        self.assertEqual(row["Companies Total"], "")
        self.assertEqual(row["Jobs Found"], "")
        self.assertEqual(row["Jobs Closed"], "")

    def test_manifest_records_checksums_encoding_and_reversible_escaped_cells(self):
        self.catalog.update_company(self.company, expected_version=1, notes="=HYPERLINK(\"example\")", personal_rationale="[clear]")
        self.exporter.export(self.destination)
        manifest = self.manifest()
        self.assertEqual(manifest["database_id"], self.database.database_id)
        self.assertEqual(manifest["encoding"], "utf-8-sig")
        for entry in manifest["files"]:
            data = (self.destination / entry["name"]).read_bytes()
            self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(entry["sha256"], hashlib.sha256(data).hexdigest())
        company = self.read("companies")[0]
        self.assertEqual(company["Notes"], 'text: =HYPERLINK("example")')
        cell = manifest["files"][0]["escaped_cells"][0]
        self.assertEqual(cell["row"], 2)
        self.assertEqual(cell["column"], "Notes")
        self.assertEqual(cell["original_sha256"], text_hash('=HYPERLINK("example")'))
        before = self.path.read_bytes()
        result = CompanyImporter(self.database).apply(self.destination / "Companies.csv")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["counts"]["unchanged"], 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_exported_reserved_tokens_and_whitespace_are_literal_on_reimport(self):
        self.catalog.update_company(self.company, expected_version=1, company_name="[clear]", category="  kept  ", notes="[clear]")
        self.exporter.export(self.destination, kinds=["companies"])
        result = CompanyImporter(self.database).apply(self.destination / "Companies.csv")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["counts"]["unchanged"], 1)

    def test_modified_export_or_broken_manifest_is_refused_before_import(self):
        self.exporter.export(self.destination, kinds=["companies"])
        path = self.destination / "Companies.csv"
        original = path.read_bytes()
        path.write_bytes(original.replace(b"Acme", b"Altered"))
        with self.assertRaisesRegex(ValueError, "Export file changed"):
            CompanyImporter(self.database).apply(path)
        path.write_bytes(original)
        (self.destination / "manifest.json").write_text('{"format_version": "unknown"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "manifest"):
            CompanyImporter(self.database).apply(path)

    def test_escaped_cell_checksums_are_verified_before_restoring_text(self):
        self.catalog.update_company(self.company, expected_version=1, notes="=1+1")
        self.exporter.export(self.destination, kinds=["companies"])
        manifest = self.manifest()
        manifest["files"][0]["escaped_cells"][0]["original_sha256"] = "corrupted"
        (self.destination / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Original-cell checksum"):
            CompanyImporter(self.database).apply(self.destination / "Companies.csv")
        self.assertEqual(self.path.read_bytes(), before)

    def test_formula_protection_covers_controls_whitespace_and_unicode_variants(self):
        for value in ("=SUM(1,2)", "+cmd", "-1+2", "@SUM(A1)", " \t=1+1", "\nplain text", "\ufeff=1", "\uff1d1+1", "\u22121+1", "\x1btext"):
            with self.subTest(value=value):
                escaped, changed = escape_cell(value)
                self.assertTrue(changed)
                self.assertEqual(escaped, "text: " + value)
        for value in ("00123", "Ordinary title", "Line one\nLine two", "text: =literal", "", "  ordinary"):
            self.assertEqual(escape_cell(value), (value, False))

    def test_utf8_without_bom_and_header_only_empty_views(self):
        self.exporter.export(self.destination, encoding="utf-8")
        self.assertFalse((self.destination / "Jobs.csv").read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(self.read("jobs"), [])
        self.assertEqual(self.read("applications"), [])
        self.assertEqual(self.read("cycles"), [])
        empty = self.root / "empty.sqlite3"
        with Database.initialize(empty) as database:
            target = self.root / "empty-export"
            CatalogExporter(database).export(target)
            result = CompanyImporter(database).apply(target / "Companies.csv")
            self.assertTrue(result["ok"])
            self.assertEqual(result["counts"], {"add": 0, "update": 0, "unchanged": 0})

    def test_export_is_not_limited_by_list_pagination(self):
        with self.database.transaction():
            for number in range(1001):
                self.catalog.create_job(self.company, JobPosting(posting_id=str(number), title=f"Role {number}"), source_id=self.source)
        self.exporter.export(self.destination, kinds=["jobs"])
        self.assertEqual(len(self.read("jobs")), 1001)

    def test_missing_current_version_is_not_silently_omitted(self):
        self.connection.execute("INSERT INTO jobs(job_id,company_id,origin,created_at,updated_at) VALUES ('incomplete',?,'imported',?,?)",
                                (self.company, utc_now(), utc_now()))
        self.exporter.export(self.destination, kinds=["jobs"])
        row = self.read("jobs")[0]
        self.assertEqual(row["Job ID"], "incomplete")
        self.assertEqual(row["Job Title"], "")
        self.assertEqual(row["Source Last Modified"], "")

    def test_destination_collision_and_last_moment_race_never_overwrite(self):
        for kind in ("directory", "file", "symlink"):
            if kind == "symlink" and os.name == "nt":
                continue
            target = self.root / kind
            if kind == "directory":
                target.mkdir()
            elif kind == "file":
                target.write_text("Existing")
            else:
                target.symlink_to(self.root / "file")
            before = target.lstat()
            with self.assertRaises(FileExistsError):
                self.exporter.export(target)
            self.assertEqual(target.lstat().st_ino, before.st_ino)
        def competing_export(source, target):
            target.mkdir()
            self.competing_inode = target.stat().st_ino
            publish_directory(source, target)
        with patch("job_search_helper.catalog_export.publish_directory", side_effect=competing_export), self.assertRaises(FileExistsError):
            self.exporter.export(self.destination)
        self.assertEqual(self.destination.stat().st_ino, self.competing_inode)
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assertEqual(list(self.root.glob(".jsh-export-*")), [])

    @unittest.skipIf(os.name == "nt", "Windows uses its native non-replacing rename")
    def test_unavailable_atomic_publication_fails_without_publishing(self):
        with patch("job_search_helper.export_publish.sys.platform", "unsupported"), self.assertRaises(OSError):
            self.exporter.export(self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.glob(".jsh-export-*")), [])

    def test_write_failure_or_interruption_publishes_nothing(self):
        for error in (OSError("Disk full"), KeyboardInterrupt()):
            with patch.object(self.exporter, "_write_manifest", side_effect=error), self.assertRaises(type(error)):
                self.exporter.export(self.destination)
            self.assertFalse(self.destination.exists())
            self.assertEqual(list(self.root.glob(".jsh-export-*")), [])
        self.assertTrue(self.database.check()["ok"])

    def test_one_read_snapshot_blocks_interleaved_commit_and_database_stays_unchanged(self):
        original = self.exporter._write_csv
        attempted = []
        def intercept(*args):
            result = original(*args)
            if not attempted:
                with Database(self.path) as writer:
                    writer.connection.execute("PRAGMA busy_timeout=10")
                    with self.assertRaises(sqlite3.OperationalError):
                        CatalogRepository(writer).add_company("Cannot commit inside the snapshot")
                attempted.append(True)
            return result
        with patch.object(self.exporter, "_write_csv", side_effect=intercept):
            self.exporter.export(self.destination)
        self.assertEqual(len(self.read("companies")), 1)
        self.catalog.add_company("Can commit afterward")

    def test_invalid_scope_or_uncommitted_database_does_not_publish(self):
        with self.assertRaisesRegex(ValueError, "Unknown company"):
            self.exporter.export(self.destination, company_ids=["missing"])
        self.assertFalse(self.destination.exists())
        with self.database.transaction(), self.assertRaisesRegex(ValueError, "transaction"):
            self.exporter.export(self.destination)

    def test_cli_default_unique_directories_and_explicit_subset(self):
        first_code, first = self.command([])
        second_code, second = self.command(["companies", "--encoding", "utf-8", "--company-id", self.company])
        self.assertEqual(first_code, 0, first)
        self.assertEqual(second_code, 0, second)
        self.assertNotEqual(first["directory"], second["directory"])
        self.assertEqual(len(first["files"]), 4)
        self.assertEqual(len(second["files"]), 1)
        code, result = self.command(["--output", first["directory"]])
        self.assertEqual(code, 2)
        self.assertIn("already exists", result["error"])

    def test_missing_database_does_not_create_export_path(self):
        output = io.StringIO()
        missing = self.root / "missing"
        with redirect_stdout(output):
            code = cli.main(["local", "export", "--workspace", str(missing), "--json"])
        self.assertEqual(code, 2)
        self.assertFalse(missing.exists())

    def test_new_export_files_have_private_permissions(self):
        self.exporter.export(self.destination)
        if os.name == "posix":
            self.assertEqual(self.destination.stat().st_mode & 0o777, 0o700)
            for file in self.destination.iterdir():
                self.assertEqual(file.stat().st_mode & 0o777, 0o600)

    def test_process_exit_while_staging_leaves_no_published_export(self):
        script = """
import os, sys
from job_search_helper.database import Database
from job_search_helper.catalog_export import CatalogExporter
with Database(sys.argv[1], readonly=True) as database:
    exporter = CatalogExporter(database)
    exporter._write_manifest = lambda *args: os._exit(0)
    exporter.export(sys.argv[2])
"""
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        completed = subprocess.run([sys.executable, "-c", script, str(self.path), str(self.destination)],
            env=environment, capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(self.destination.exists())
        self.assertTrue(self.database.check()["ok"])
