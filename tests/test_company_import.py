import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.ats import Inventory
from job_search_helper.company_import import CompanyImporter, source_definition
from job_search_helper.database import Database
from job_search_helper.models import JobPosting
from job_search_helper.repositories import ApplicationRepository, CatalogRepository
from job_search_helper.scan_service import ScanService


class CompanyImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "catalog.sqlite3"
        self.database = Database.initialize(self.path)
        self.addCleanup(self.database.close)
        self.connection = self.database.connection
        self.importer = CompanyImporter(self.database)
        self.catalog = CatalogRepository(self.database)
        self.csv = self.root / "companies.csv"

    def write(self, rows, headers=None, *, bom=False):
        headers = headers or list(dict.fromkeys(key for row in rows for key in row))
        with self.csv.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

    def row(self, **fields):
        return {"Company Name": "Acme", "Careers URL": "https://boards.greenhouse.io/acme", **fields}

    def apply(self, rows=None, **options):
        if rows is not None:
            self.write(rows)
        result = self.importer.apply(self.csv, **options)
        self.assertTrue(result["ok"], result.get("errors"))
        return result

    def company(self, company_id):
        return dict(self.connection.execute("SELECT * FROM companies WHERE company_id=?", (company_id,)).fetchone())

    def source(self):
        return dict(self.connection.execute("SELECT * FROM job_sources WHERE is_current=1").fetchone())

    def count(self, table):
        return self.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def test_preview_is_read_only_apply_is_audited_and_repeat_is_noop(self):
        self.write([self.row(Notes="Keep this")])
        before = self.path.read_bytes()
        with Database(self.path, readonly=True) as reader:
            preview = CompanyImporter(reader).preview(self.csv)
        self.assertEqual(preview["counts"], {"add": 1, "update": 0, "unchanged": 0})
        self.assertEqual(self.path.read_bytes(), before)
        result = self.apply()
        identity = result["rows"][0]["company_id"]
        self.assertEqual(self.company(identity)["notes"], "Keep this")
        self.assertEqual(self.count("import_batches"), 1)
        self.assertEqual(self.count("legacy_records"), 1)
        before = self.path.read_bytes()
        repeated = self.apply()
        self.assertEqual(repeated["counts"]["unchanged"], 1)
        self.assertEqual(self.path.read_bytes(), before)
        audit = json.loads(self.connection.execute("SELECT raw_record_json FROM legacy_records").fetchone()[0])
        self.assertEqual(audit["input"]["Notes"], "Keep this")

    def test_bom_quotes_multiline_notes_and_text_ids_round_trip(self):
        row = self.row(**{"Company Name": 'Acme, "Systems"', "Company ID": "00123", "Notes": 'Line one, "quoted"\nLine two'})
        self.write([row], bom=True)
        result = self.importer.preview(self.csv)
        self.assertFalse(result["ok"])
        self.assertIn("preserve-ids", result["errors"][0]["error"])
        self.apply(preserve_ids=True)
        company = self.company("00123")
        self.assertEqual(company["company_name"], row["Company Name"])
        self.assertEqual(company["notes"], row["Notes"])

    def test_blank_and_omitted_optional_cells_preserve_notes_explicit_clear_removes_them(self):
        result = self.apply([self.row(Notes="Existing note", Priority="High")])
        identity = result["rows"][0]["company_id"]
        self.apply([self.row(Notes="", Priority="")])
        self.assertEqual(self.company(identity)["notes"], "Existing note")
        self.apply([self.row(Notes="[clear]")])
        self.assertEqual(self.company(identity)["notes"], "")
        self.assertEqual(self.company(identity)["priority"], "High")

    def test_existing_id_can_rename_company_without_changing_job_or_application(self):
        identity = self.apply([self.row()])["rows"][0]["company_id"]
        job = self.catalog.create_job(identity, JobPosting(posting_id="001", title="Engineer"), source_id=self.source()["source_id"])
        apps = ApplicationRepository(self.database)
        app = apps.add(job, status="applied", date_applied="2026-09-25", notes="Contacted", resume_used="v2")
        before = apps.get(app)
        self.apply([self.row(**{"Company ID": identity, "Company Name": "Renamed"})])
        self.assertEqual(self.catalog.get_job(job)["company_id"], identity)
        self.assertEqual(apps.get(app), before)

    def test_normalized_name_and_exact_scope_match_without_creating_duplicate(self):
        identity = self.apply([self.row()])["rows"][0]["company_id"]
        result = self.apply([self.row(**{"Company Name": "  ACME  ", "Careers URL": "https://job-boards.greenhouse.io/acme?utm_source=test"})])
        self.assertEqual(result["rows"][0]["company_id"], identity)
        self.assertEqual(self.count("companies"), 1)
        self.assertEqual(self.count("job_sources"), 1)

    def test_same_name_different_board_is_not_fuzzily_merged(self):
        self.apply([self.row()])
        self.apply([self.row(**{"Careers URL": "https://jobs.lever.co/unrelated"})])
        self.assertEqual(self.count("companies"), 2)

    def test_ambiguous_name_or_scope_requires_explicit_existing_id(self):
        self.apply([self.row()])
        other = self.catalog.add_company("Acme")
        self.catalog.add_source(other, "greenhouse", "other", "https://boards.greenhouse.io/acme")
        self.write([self.row()])
        result = self.importer.preview(self.csv)
        self.assertFalse(result["ok"])
        self.assertIn("ambiguously", result["errors"][0]["error"])
        result = self.apply([self.row(**{"Company ID": other, "Notes": "Explicit selection"})])
        self.assertEqual(result["rows"][0]["company_id"], other)

    def test_duplicate_rows_ids_invalid_status_and_unknown_id_abort_entire_import(self):
        cases = [
            [self.row(), self.row()],
            [self.row(**{"Company ID": "same"}), self.row(**{"Company ID": "same", "Careers URL": "https://jobs.lever.co/other"})],
            [self.row(), self.row(**{"Status": "invalid", "Careers URL": "https://jobs.lever.co/other"})],
            [self.row(**{"Company ID": "unknown"})],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                self.write(rows)
                result = self.importer.apply(self.csv)
                self.assertFalse(result["ok"])
                self.assertEqual(self.count("companies"), 0)
                self.assertEqual(self.count("import_batches"), 0)

    def test_late_write_error_rolls_back_company_source_and_ledger(self):
        self.write([self.row(), self.row(**{"Company Name": "Second", "Careers URL": "https://jobs.lever.co/second"})])
        original = self.importer._select_source
        def fail_second(row):
            if row["company_name"] == "Second":
                raise RuntimeError("Injected failure")
            original(row)
        with patch.object(self.importer, "_select_source", side_effect=fail_second), self.assertRaises(RuntimeError):
            self.importer.apply(self.csv)
        for table in ("companies", "job_sources", "source_scopes", "import_batches", "legacy_records"):
            self.assertEqual(self.count(table), 0)

    def test_source_switch_preserves_history_and_switch_back_does_not_duplicate_sources(self):
        identity = self.apply([self.row()])["rows"][0]["company_id"]
        first_source = self.source()["source_id"]
        job = self.catalog.create_job(identity, JobPosting(posting_id="001"), source_id=first_source)
        self.apply([self.row(**{"Company ID": identity, "Careers URL": "https://jobs.lever.co/acme"})])
        self.assertNotEqual(self.source()["source_id"], first_source)
        self.assertEqual(self.catalog.get_job(job)["source_id"], first_source)
        self.write([self.row()])
        self.assertFalse(self.importer.preview(self.csv)["ok"])
        self.apply([self.row(**{"Company ID": identity})])
        self.assertEqual(self.source()["source_id"], first_source)
        self.assertEqual(self.count("job_sources"), 2)

    def test_scope_revision_keeps_jobs_and_resets_missing_baseline(self):
        url = "https://acme.wd5.myworkdayjobs.com/External?q=systems"
        identity = self.apply([self.row(**{"Careers URL": url})])["rows"][0]["company_id"]
        source = self.source()["source_id"]
        service = ScanService(self.database)
        for jobs in ([{"posting_id": "001"}], []):
            cycle = service.start_cycle([identity])
            attempt = service.begin_attempt(cycle, identity)
            service.stage_inventory(attempt, Inventory("complete", jobs))
            service.apply_inventory(attempt)
        self.assertEqual(self.connection.execute("SELECT consecutive_missing FROM job_scope_state").fetchone()[0], 1)
        self.write([self.row(**{"Careers URL": url.replace("systems", "hardware")})])
        self.assertFalse(self.importer.preview(self.csv)["ok"])
        self.apply([self.row(**{"Company ID": identity, "Careers URL": url.replace("systems", "hardware")})])
        self.assertEqual(self.source()["source_id"], source)
        self.assertEqual(self.count("jobs"), 1)
        self.assertEqual(self.count("source_scopes"), 2)
        self.assertEqual(self.count("job_scope_state"), 0)
        self.assertEqual(self.count("job_observations"), 2)

    def test_source_change_is_refused_for_unfinished_cycle_but_notes_can_change(self):
        identity = self.apply([self.row()])["rows"][0]["company_id"]
        ScanService(self.database).start_cycle([identity])
        self.write([self.row(**{"Company ID": identity, "Careers URL": "https://jobs.lever.co/acme"})])
        result = self.importer.apply(self.csv)
        self.assertFalse(result["ok"])
        self.assertIn("unfinished", result["errors"][0]["error"])
        self.apply([self.row(Notes="Allowed note")])
        self.assertEqual(self.company(identity)["notes"], "Allowed note")

    def test_switching_back_cannot_publish_an_old_cancelled_inventory_as_current(self):
        identity = self.apply([self.row()])["rows"][0]["company_id"]
        service = ScanService(self.database)
        cycle = service.start_cycle([identity])
        attempt = service.begin_attempt(cycle, identity)
        service.stage_inventory(attempt, Inventory("complete", [{"posting_id": "001", "title": "Old retained title"}]))
        self.connection.execute("UPDATE scan_cycles SET status='cancelled' WHERE cycle_id=?", (cycle,))
        self.apply([self.row(**{"Company ID": identity, "Careers URL": "https://jobs.lever.co/acme"})])
        self.apply([self.row(**{"Company ID": identity})])
        self.assertTrue(service.apply_inventory(attempt))
        job = self.connection.execute("SELECT * FROM jobs").fetchone()
        self.assertEqual(job["lifecycle_status"], "unknown")
        observation = self.connection.execute("SELECT change_kind FROM job_observations").fetchone()[0]
        self.assertEqual(observation, "historical")

    def test_apply_revalidates_current_data_instead_of_replaying_stale_preview(self):
        identity = self.apply([self.row(Notes="Original")])["rows"][0]["company_id"]
        self.write([self.row(Priority="High")])
        self.importer.preview(self.csv)
        current = self.company(identity)
        self.catalog.update_company(identity, expected_version=current["row_version"], notes="Edited after preview")
        self.apply()
        self.assertEqual(self.company(identity)["notes"], "Edited after preview")

    def test_computed_columns_are_ignored_and_formula_like_notes_are_not_evaluated(self):
        result = self.apply([self.row(**{"Last Scan Result": "complete", "Jobs Found In Last Scan": "300", "Notes": "=HYPERLINK(test)"})])
        self.assertEqual(result["ignored_columns"], ["Jobs Found In Last Scan", "Last Scan Result"])
        self.assertEqual(self.count("scan_attempts"), 0)
        self.assertEqual(self.count("jobs"), 0)
        self.assertEqual(self.company(result["rows"][0]["company_id"])["notes"], "=HYPERLINK(test)")

    def test_private_invalid_or_mismatched_provider_urls_are_line_errors(self):
        for fields in ({"Careers URL": "http://example.com"}, {"Careers URL": "https://127.0.0.1/jobs"},
                       {"Careers URL": "https://user:pass@example.com"}, {"ATS Type": "Lever"},
                       {"Careers URL": "https://acme.wd5.myworkdayjobs.com"}, {"Website": "javascript:alert(1)"}):
            self.write([self.row(**fields)])
            result = self.importer.preview(self.csv)
            self.assertFalse(result["ok"], fields)
            self.assertEqual(result["errors"][0]["line"], 2)

    def test_generic_careers_url_is_saved_with_clear_scanning_warning_without_fetching(self):
        with patch("job_search_helper.ats.fetch_inventory", side_effect=AssertionError("Network call")):
            result = self.apply([self.row(**{"Careers URL": "https://example.com/careers"})])
        self.assertIn("needs a supported", result["rows"][0]["warning"])
        self.assertEqual(self.source()["provider"], "unknown")

    def test_omitting_optional_provider_does_not_duplicate_a_known_generic_source(self):
        first = self.apply([self.row(**{"Careers URL": "https://example.com/careers", "ATS Type": "workday"})])
        second = self.apply([self.row(**{"Careers URL": "https://example.com/careers"})])
        self.assertEqual(second["counts"]["unchanged"], 1)
        self.assertEqual(first["rows"][0]["company_id"], second["rows"][0]["company_id"])
        self.assertEqual(self.count("companies"), 1)
        self.assertEqual(self.count("job_sources"), 1)

    def test_malformed_header_row_count_and_quoting_are_rejected_before_writes(self):
        for data in ("Company Name,Company Name,Careers URL\nA,A,https://example.com\n",
                     "Company Name,Careers URL,Surprise\nA,https://example.com,test\n",
                     "Company Name,Careers URL\nA,https://example.com,extra\n",
                     'Company Name,Careers URL\n"unclosed,https://example.com\n',
                     "Company Name,Careers URL\n"):
            self.csv.write_text(data, encoding="utf-8")
            with self.assertRaises(ValueError):
                self.importer.apply(self.csv)
            self.assertEqual(self.count("companies"), 0)

    def test_multiline_rows_report_the_starting_physical_line(self):
        self.write([self.row(Notes="two\nlines"), self.row(**{"Company Name": "Second", "Careers URL": "bad", "Notes": ""})])
        self.assertEqual(self.importer.preview(self.csv)["errors"][0]["line"], 4)

    def test_provider_namespace_is_stable_across_filters_and_regions_stay_distinct(self):
        first = source_definition("https://acme.wd5.myworkdayjobs.com/External?q=systems")
        second = source_definition("https://acme.wd5.myworkdayjobs.com/External?q=hardware")
        self.assertEqual(first.namespace, second.namespace)
        self.assertNotEqual(first.scope_key, second.scope_key)
        self.assertNotEqual(source_definition("https://jobs.lever.co/acme").namespace,
                            source_definition("https://jobs.eu.lever.co/acme").namespace)
