from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.ats import HTTPResponse, Inventory
from job_search_helper.config import Settings
from job_search_helper.database import Database
from job_search_helper.local_scanner import run_cycle, scan_options
from job_search_helper.models import JobPosting
from job_search_helper.repositories import ApplicationRepository, CatalogRepository
from job_search_helper.scan_lock import ScanBusyError, scan_lock
from job_search_helper.scan_service import ScanService


POSTING = {"posting_id": "001", "title": "Principal Engineer", "description": "Full evidence\n" * 6000,
           "url": "https://example.com/jobs/001", "created_at": "2026-09-25T08:30:00-04:00",
           "updated_at": "taleo-job-id:987", "ats": "Greenhouse"}


class LocalScanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "catalog.sqlite3"
        self.database = Database.initialize(self.path)
        self.addCleanup(self.database.close)
        self.connection = self.database.connection
        self.catalog = CatalogRepository(self.database)
        self.company = self.catalog.add_company("Acme", company_id="COMP-001")
        self.source = self.catalog.add_source(self.company, "Greenhouse", "acme", "https://boards.greenhouse.io/acme")
        self.service = ScanService(self.database)

    def scan(self, jobs=(), status="complete", **options):
        cycle = self.service.start_cycle([self.company], **options)
        attempt = self.service.begin_attempt(cycle, self.company)
        self.service.stage_inventory(attempt, Inventory(status, list(jobs), ats="Greenhouse"))
        self.assertTrue(self.service.apply_inventory(attempt))
        return cycle, attempt

    def job(self, posting_id="001"):
        row = self.connection.execute("SELECT job_id FROM jobs WHERE source_job_id=?", (posting_id,)).fetchone()
        return self.catalog.get_job(row[0])

    def count(self, table):
        return self.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def test_full_evidence_and_readable_dates_reach_catalog_without_policy(self):
        cycle, attempt = self.scan([dict(POSTING, is_listed=False)])
        job = self.job()
        self.assertEqual(job["description"], POSTING["description"])
        self.assertEqual(job["title"], "Principal Engineer")
        self.assertEqual(job["source_created_at"], "2026-09-25T12:30:00Z")
        self.assertEqual(job["source_modified_raw"], "taleo-job-id:987")
        self.assertIsNone(job["source_modified_at"])
        self.assertEqual(job["lifecycle_status"], "active")
        self.assertEqual(self.service.status(cycle)["cycle"]["status"], "completed")
        payload = json.loads(self.connection.execute("SELECT payload_json FROM inventory_batches").fetchone()[0])
        self.assertEqual(payload["inventory"]["jobs"][0]["description"], POSTING["description"])
        self.assertTrue(self.database.check()["ok"])

    def test_missing_requires_two_distinct_complete_cycles_and_reopens(self):
        self.scan([POSTING])
        cycle, attempt = self.scan()
        self.assertEqual(self.job()["lifecycle_status"], "missing")
        self.service.apply_inventory(attempt)
        retry = self.service.begin_attempt(cycle, self.company, retry=True)
        self.service.stage_inventory(retry, Inventory("complete"))
        self.service.apply_inventory(retry)
        self.assertEqual(self.connection.execute("SELECT consecutive_missing FROM job_scope_state").fetchone()[0], 1)
        self.scan()
        self.assertEqual(self.job()["lifecycle_status"], "closed")
        self.assertEqual(self.job()["closure_basis"], "comparable_complete_absence")
        self.scan([POSTING], status="partial")
        self.assertEqual(self.job()["lifecycle_status"], "active")
        self.assertIsNone(self.job()["closed_at"])

    def test_partial_blocked_failed_unsupported_never_count_absence(self):
        self.scan([POSTING])
        for status in ("partial", "blocked", "failed", "unsupported"):
            cycle, _ = self.scan(status=status)
            self.assertEqual(self.job()["lifecycle_status"], "active")
            self.assertEqual(self.service.status(cycle)["cycle"]["status"], "completed_with_exceptions")
        self.assertEqual(self.connection.execute("SELECT consecutive_missing FROM job_scope_state").fetchone()[0], 0)

    def test_seen_then_absent_in_same_cycle_is_not_a_missing_cycle(self):
        cycle, _ = self.scan([POSTING])
        attempt = self.service.begin_attempt(cycle, self.company, retry=True)
        self.service.stage_inventory(attempt, Inventory("complete"))
        self.service.apply_inventory(attempt)
        self.assertEqual(self.job()["lifecycle_status"], "active")

    def test_changed_scope_and_return_to_old_scope_reset_comparison(self):
        self.scan([POSTING], adapter_version="A")
        self.scan(adapter_version="A")
        self.scan([POSTING], adapter_version="B")
        self.scan(adapter_version="A")
        self.assertEqual(self.job()["lifecycle_status"], "active")
        self.scan([POSTING], adapter_version="A")
        self.scan(adapter_version="A")
        self.assertEqual(self.job()["lifecycle_status"], "missing")

    def test_application_fields_and_history_survive_changes_and_closure(self):
        self.scan([POSTING])
        apps = ApplicationRepository(self.database)
        app = apps.add(self.job()["job_id"], status="applied", date_applied="2026-09-25", notes="Follow up", resume_used="v2")
        before = apps.get(app)
        self.scan([dict(POSTING, title="Updated title")])
        self.scan()
        self.scan()
        self.assertEqual(apps.get(app), before)
        self.assertEqual(self.count("application_events"), 1)

    def test_failure_rolls_back_all_projection_and_can_resume_without_refetch(self):
        cycle = self.service.start_cycle([self.company])
        attempt = self.service.begin_attempt(cycle, self.company)
        self.service.stage_inventory(attempt, Inventory("complete", [POSTING]))
        with patch.object(self.service, "_finish_member", side_effect=RuntimeError("crash before commit")):
            with self.assertRaises(RuntimeError):
                self.service.apply_inventory(attempt)
        self.assertEqual(self.count("jobs"), 0)
        self.assertEqual(self.count("job_versions"), 0)
        self.assertEqual(self.count("job_observations"), 0)
        self.assertEqual(self.connection.execute("SELECT apply_state FROM inventory_batches").fetchone()[0], "pending")
        result = run_cycle(self.database, cycle, fetcher=lambda _: self.fail("Saved work was refetched"))
        self.assertEqual(result["cycle"]["status"], "completed")
        before = dict(self.job())
        self.service.apply_inventory(attempt)
        self.assertEqual(self.job(), before)
        self.assertEqual(self.count("job_observations"), 1)

    def test_raw_malformed_inventory_is_preserved_and_quarantined_atomically(self):
        cycle = self.service.start_cycle([self.company])
        attempt = self.service.begin_attempt(cycle, self.company)
        raw = Inventory("complete", [POSTING, {"title": "No identity"}])
        self.service.stage_inventory(attempt, raw)
        self.assertFalse(self.service.apply_inventory(attempt))
        self.assertEqual(self.count("jobs"), 0)
        batch = self.connection.execute("SELECT * FROM inventory_batches").fetchone()
        self.assertEqual(batch["apply_state"], "quarantined")
        self.assertEqual(json.loads(batch["payload_json"])["inventory"], asdict(raw))
        result = run_cycle(self.database, cycle, retry_exceptions=True, fetcher=lambda _: self.fail("Quarantine refetched"))
        self.assertEqual(result["cycle"]["status"], "completed_with_exceptions")

    def test_duplicate_rows_are_deduplicated_and_conflicting_duplicates_quarantine(self):
        self.scan([POSTING, POSTING])
        self.assertEqual(self.count("jobs"), 1)
        self.assertEqual(self.count("job_observations"), 1)
        cycle = self.service.start_cycle([self.company])
        attempt = self.service.begin_attempt(cycle, self.company)
        self.service.stage_inventory(attempt, Inventory("complete", [POSTING, dict(POSTING, title="Conflict")]))
        self.assertFalse(self.service.apply_inventory(attempt))
        self.assertEqual(self.job()["title"], POSTING["title"])
        self.assertEqual(self.count("job_versions"), 1)

    def test_reused_url_with_different_provider_id_remains_two_jobs(self):
        self.scan([POSTING])
        self.scan([dict(POSTING, posting_id="002")])
        self.assertEqual(self.count("jobs"), 2)
        self.assertEqual(self.job("001")["lifecycle_status"], "missing")
        self.assertEqual(self.job("002")["lifecycle_status"], "active")

    def test_older_retained_result_cannot_overwrite_newer_evidence_or_close_jobs(self):
        cycle = self.service.start_cycle([self.company])
        attempt = self.service.begin_attempt(cycle, self.company)
        self.service.stage_inventory(attempt, Inventory("complete", [dict(POSTING, title="Old title")]))
        # Simulate an explicitly cancelled cycle whose payload was retained.
        self.connection.execute("UPDATE scan_cycles SET status='cancelled' WHERE cycle_id=?", (cycle,))
        self.scan([POSTING, dict(POSTING, posting_id="002", url="https://example.com/jobs/002")])
        before = dict(self.job())
        self.service.apply_inventory(attempt)
        self.assertEqual(self.job(), before)
        self.assertEqual(self.job("002")["lifecycle_status"], "active")
        self.assertEqual(self.count("job_versions"), 3)
        observation = self.connection.execute("SELECT change_kind FROM job_observations WHERE attempt_id=?", (attempt,)).fetchone()[0]
        self.assertEqual(observation, "historical")
        with self.assertRaisesRegex(ValueError, "newer cycle"):
            self.service.begin_attempt(cycle, self.company, retry=True)

    def test_cycle_membership_names_and_settings_are_frozen(self):
        cycle = self.service.start_cycle(all_companies=True, missing_threshold=3)
        self.catalog.rename_company(self.company, "Renamed", expected_version=1)
        other = self.catalog.add_company("Newly added")
        self.catalog.add_source(other, "Lever", "other", "https://jobs.lever.co/other")
        members = self.service.members(cycle)
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0]["company_name_at_start"], "Acme")
        with self.assertRaisesRegex(ValueError, "unfinished"):
            self.service.start_cycle(all_companies=True)

    def test_retired_source_saved_inventory_is_quarantined(self):
        cycle = self.service.start_cycle([self.company])
        attempt = self.service.begin_attempt(cycle, self.company)
        self.service.stage_inventory(attempt, Inventory("complete", [POSTING]))
        self.catalog.add_source(self.company, "Lever", "new", "https://jobs.lever.co/new")
        self.assertFalse(self.service.apply_inventory(attempt))
        self.assertEqual(self.count("jobs"), 0)

    def test_attempt_without_durable_result_is_recorded_as_interrupted_then_refetched(self):
        cycle = self.service.start_cycle([self.company])
        attempt = self.service.begin_attempt(cycle, self.company)
        self.service.interrupt(cycle)
        result = run_cycle(self.database, cycle, fetcher=lambda _: Inventory("complete", [POSTING]))
        self.assertEqual(result["cycle"]["status"], "completed")
        self.assertEqual(self.service._attempt(attempt)["fetch_status"], "interrupted")
        self.assertEqual(self.count("scan_attempts"), 2)

    def test_exception_retries_are_explicit_and_use_same_cycle(self):
        cycle, _ = self.scan(status="blocked")
        run_cycle(self.database, cycle, fetcher=lambda _: self.fail("Blocked site retried implicitly"))
        result = run_cycle(self.database, cycle, retry_exceptions=True, fetcher=lambda _: Inventory("complete", [POSTING]))
        self.assertEqual(result["cycle"]["cycle_id"], cycle)
        self.assertEqual(result["cycle"]["status"], "completed")
        self.assertEqual(self.count("scan_cycles"), 1)

    def test_adapter_runs_outside_sql_transaction_and_errors_are_saved(self):
        cycle = self.service.start_cycle([self.company])
        def fetch(_):
            self.assertFalse(self.connection.in_transaction)
            raise RuntimeError("arbitrary response text")
        result = run_cycle(self.database, cycle, fetcher=fetch)
        self.assertEqual(result["companies"][0]["fetch_status"], "failed")
        self.assertNotIn("arbitrary response text", result["companies"][0]["reason"])

    def test_default_bridge_uses_actual_official_adapter_offline(self):
        cycle = self.service.start_cycle([self.company])
        body = json.dumps({"meta": {"total": 1}, "jobs": [{"id": 123, "title": "Principal Engineer", "absolute_url": POSTING["url"],
                                     "content": "<p>Full description</p>", "location": {"name": "Remote"}}]}).encode()
        with patch("job_search_helper.local_scanner.HTTPTransport.get", return_value=HTTPResponse(200, body)):
            result = run_cycle(self.database, cycle)
        self.assertEqual(result["cycle"]["status"], "completed")
        self.assertEqual(self.job("123")["description"], "Full description")

    def test_process_exit_after_stage_recovers_exact_saved_result(self):
        cycle = self.service.start_cycle([self.company])
        script = """
import os, sys
from job_search_helper.database import Database
from job_search_helper.scan_service import ScanService
from job_search_helper.ats import Inventory
with Database(sys.argv[1]) as db:
    service = ScanService(db)
    attempt = service.begin_attempt(sys.argv[2], 'COMP-001')
    service.stage_inventory(attempt, Inventory('complete', [{'posting_id': '001', 'title': 'Saved before exit'}]))
    os._exit(0)
"""
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        result = subprocess.run([sys.executable, "-c", script, str(self.path), cycle], env=environment,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        run_cycle(self.database, cycle, fetcher=lambda _: self.fail("Result lost after exit"))
        self.assertEqual(self.job()["title"], "Saved before exit")

    def test_batch_and_observation_evidence_are_immutable_and_parent_links_enforced(self):
        self.scan([POSTING])
        for sql in ("UPDATE inventory_batches SET payload_json='{}'", "DELETE FROM inventory_batches",
                    "DELETE FROM job_observations", "UPDATE job_observations SET presence='absent'",
                    "UPDATE scan_attempts SET company_id='different'"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.connection.execute(sql)

    def test_incompatible_or_corrupted_payload_is_quarantined_without_projection(self):
        for corruption in ("version", "checksum"):
            cycle = self.service.start_cycle([self.company])
            attempt = self.service.begin_attempt(cycle, self.company)
            self.service.stage_inventory(attempt, Inventory("complete", [POSTING]))
            if corruption == "version":
                with patch("job_search_helper.scan_service.INVENTORY_PAYLOAD_VERSION", 99):
                    self.assertFalse(self.service.apply_inventory(attempt))
            else:
                self.connection.execute("DROP TRIGGER inventory_payload_immutable")
                self.connection.execute("UPDATE inventory_batches SET payload_hash='damaged' WHERE attempt_id=?", (attempt,))
                self.assertFalse(self.service.apply_inventory(attempt))
            self.assertEqual(self.count("jobs"), 0)

    def test_stage_replay_is_idempotent_but_replacement_is_refused(self):
        cycle = self.service.start_cycle([self.company])
        attempt = self.service.begin_attempt(cycle, self.company)
        result = Inventory("complete", [POSTING])
        self.service.stage_inventory(attempt, result)
        self.service.stage_inventory(attempt, result)
        with self.assertRaisesRegex(ValueError, "cannot be replaced"):
            self.service.stage_inventory(attempt, Inventory("complete"))
        self.assertEqual(self.count("inventory_batches"), 1)

    def test_failed_attempt_in_changed_scope_also_resets_old_baseline(self):
        self.scan([POSTING], adapter_version="A")
        self.scan(adapter_version="A")
        self.scan(status="blocked", adapter_version="B")
        self.scan(adapter_version="A")
        self.assertNotEqual(self.job()["lifecycle_status"], "closed")
        self.assertEqual(self.count("job_scope_state"), 0)

    def test_source_change_before_resume_does_not_fetch_retired_source(self):
        cycle = self.service.start_cycle([self.company])
        self.catalog.add_source(self.company, "Lever", "new", "https://jobs.lever.co/new")
        result = run_cycle(self.database, cycle, fetcher=lambda _: self.fail("Retired source fetched"))
        self.assertEqual(result["companies"][0]["apply_status"], "quarantined")
        self.assertEqual(result["cycle"]["status"], "completed_with_exceptions")

    def test_pending_inventory_is_in_backup_and_recoverable_after_restore(self):
        cycle = self.service.start_cycle([self.company])
        attempt = self.service.begin_attempt(cycle, self.company)
        self.service.stage_inventory(attempt, Inventory("complete", [POSTING]))
        backup = self.database.backup(self.path.parent / "backup.sqlite3")
        with Database(backup) as restored:
            self.assertEqual(restored.check()["scan_recovery"]["pending"], 1)
            run_cycle(restored, cycle, fetcher=lambda _: self.fail("Backup lost saved inventory"))
            self.assertEqual(restored.check()["counts"]["jobs"], 1)
        self.assertEqual(self.count("jobs"), 0)

    def test_interrupt_during_fetch_leaves_recoverable_attempt(self):
        cycle = self.service.start_cycle([self.company])
        def stop(_):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            run_cycle(self.database, cycle, fetcher=stop)
        self.assertEqual(self.service.status(cycle)["cycle"]["status"], "interrupted")
        self.assertEqual(self.count("inventory_batches"), 0)
        run_cycle(self.database, cycle, fetcher=lambda _: Inventory("complete", [POSTING]))
        self.assertEqual(self.count("jobs"), 1)

    def test_job_without_id_can_gain_a_provider_id_without_losing_application(self):
        self.scan([dict(POSTING, posting_id="")])
        job_id = self.connection.execute("SELECT job_id FROM jobs").fetchone()[0]
        apps = ApplicationRepository(self.database)
        app = apps.add(job_id, notes="Keep this")
        self.scan([POSTING])
        self.assertEqual(self.job()["job_id"], job_id)
        self.assertEqual(apps.get(app)["notes"], "Keep this")
        self.assertEqual(self.count("jobs"), 1)

    def test_configured_missing_threshold_is_frozen_across_resume(self):
        self.scan([POSTING])
        cycle = self.service.start_cycle([self.company], missing_threshold=1)
        run_cycle(self.database, cycle, fetcher=lambda _: Inventory("complete"))
        self.assertEqual(self.job()["lifecycle_status"], "closed")

    def test_second_coordinator_is_refused_and_lock_releases(self):
        with scan_lock(self.path):
            with self.assertRaises(ScanBusyError), scan_lock(self.path):
                self.fail("Second coordinator entered")
        with scan_lock(self.path):
            pass

    @unittest.skipIf(os.name == "nt", "Symlink creation needs separate Windows privileges")
    def test_catalog_symlink_uses_the_same_coordinator_lock(self):
        alias = self.path.parent / "alias.sqlite3"
        alias.symlink_to(self.path)
        with scan_lock(self.path):
            with self.assertRaises(ScanBusyError), scan_lock(alias):
                self.fail("Catalog alias bypassed the scan lock")

    def test_reserved_settings_are_not_silently_ignored(self):
        for changes in ({"workers": 2}, {"browser_enabled": True}, {"retry_attempts": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                scan_options(Settings(self.path.parent, self.path, **changes))
