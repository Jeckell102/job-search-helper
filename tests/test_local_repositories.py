from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.database import Database
from job_search_helper.models import JobPosting, SourceScope, utc_now
from job_search_helper.repositories import ApplicationRepository, CatalogRepository, ConflictError


class LocalRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Database.initialize(Path(self.temporary.name) / "catalog.sqlite3")
        self.addCleanup(self.database.close)
        self.repo = CatalogRepository(self.database)
        self.apps = ApplicationRepository(self.database)
        self.company = self.repo.add_company("Acme", company_id="COMP-001")
        self.source = self.repo.add_source(self.company, "Greenhouse", "acme", "https://boards.greenhouse.io/acme")
        self.posting = JobPosting(posting_id="00123", requisition_id="REQ-9", title="Principal Engineer",
                                  description="Full evidence\n" * 6000, compensation="USD 90000 annual base",
                                  url="https://example.com/jobs/00123", is_listed=False)

    def create_job(self):
        return self.repo.create_job(self.company, self.posting, source_id=self.source)

    def test_company_rename_keeps_stable_job_identity_and_legacy_alias(self):
        job_id = self.create_job()
        self.repo.rename_company(self.company, "Renamed", expected_version=1)
        self.assertEqual(self.repo.get_job(job_id)["company_id"], self.company)
        alias = self.database.connection.execute("SELECT value FROM job_identity_aliases WHERE kind='legacy_key'").fetchone()[0]
        self.assertEqual(alias, "comp-001:greenhouse:00123")
        self.assertNotIn("00123", job_id)
        with self.assertRaises(ConflictError):
            self.repo.rename_company(self.company, "Stale rename", expected_version=1)

    def test_same_company_names_and_same_ids_on_different_boards_are_allowed(self):
        first = self.create_job()
        self.repo.add_company("Acme")
        second_source = self.repo.add_source(self.company, "Greenhouse", "new-board", "https://boards.greenhouse.io/new-board")
        second = self.repo.create_job(self.company, self.posting, source_id=second_source)
        self.assertNotEqual(first, second)
        self.assertEqual(self.database.connection.execute("SELECT count(*) FROM job_sources WHERE is_current=1 AND company_id=?", (self.company,)).fetchone()[0], 1)
        self.assertEqual(self.database.connection.execute("SELECT count(*) FROM job_identity_aliases WHERE kind='legacy_key'").fetchone()[0], 2)

    def test_duplicate_source_identity_rejected_without_partial_version(self):
        self.create_job()
        with self.assertRaises(sqlite3.IntegrityError):
            self.create_job()
        self.assertEqual(self.database.check()["counts"]["jobs"], 1)
        self.assertEqual(self.database.connection.execute("SELECT count(*) FROM job_versions").fetchone()[0], 1)

    def test_source_company_mismatch_rejected(self):
        other = self.repo.add_company("Other")
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.create_job(other, self.posting, source_id=self.source)
        self.assertEqual(self.database.check()["counts"]["jobs"], 0)

    def test_full_evidence_req_id_and_unlisted_posting_are_retained(self):
        job = self.repo.get_job(self.create_job())
        self.assertEqual(job["requisition_id"], "REQ-9")
        self.assertEqual(job["source_job_id"], "00123")
        self.assertEqual(job["description"], self.posting.description)
        self.assertEqual(job["title"], "Principal Engineer")
        self.assertEqual(job["compensation_text"], "USD 90000 annual base")
        self.assertEqual(self.database.connection.execute("SELECT is_listed FROM job_versions").fetchone()[0], 0)

    def test_same_evidence_reuses_version_but_url_change_is_preserved(self):
        job_id = self.create_job()
        current = self.repo.get_job(job_id)["current_version_id"]
        self.assertEqual(self.repo.store_version(job_id, self.posting, observed_at=utc_now()), current)
        version = self.repo.store_version(job_id, replace(self.posting, url="https://example.com/updated"), observed_at=utc_now())
        self.assertNotEqual(version, current)
        hashes = self.database.connection.execute("SELECT material_hash FROM job_versions").fetchall()
        self.assertEqual(hashes[0][0], hashes[1][0])
        self.assertEqual(self.repo.get_job(job_id)["current_version_id"], current)

    def test_current_version_cannot_belong_to_another_job(self):
        first = self.create_job()
        second = self.repo.create_job(self.company, replace(self.posting, posting_id="002"), source_id=self.source)
        version = self.repo.get_job(second)["current_version_id"]
        with self.assertRaises(sqlite3.IntegrityError), self.database.transaction():
            self.database.connection.execute("UPDATE jobs SET current_version_id=? WHERE job_id=?", (version, first))
        self.assertNotEqual(self.repo.get_job(first)["current_version_id"], version)

    def test_evidence_and_scope_are_immutable(self):
        self.create_job()
        scope = SourceScope(self.source, "https://boards.greenhouse.io/acme?team=1", "v1")
        first = self.repo.add_scope(scope)
        self.assertEqual(first, self.repo.add_scope(scope))
        self.assertNotEqual(first, self.repo.add_scope(replace(scope, adapter_version="v2")))
        for sql in ("UPDATE job_versions SET description='changed'", "DELETE FROM job_versions",
                    "UPDATE source_scopes SET adapter_version='changed'", "DELETE FROM source_scopes"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError), self.database.transaction():
                self.database.connection.execute(sql)

    def test_application_date_and_manual_job_lifecycle_remain_unknown(self):
        job_id = self.repo.create_job(self.company, self.posting)
        app = self.apps.get(self.apps.add(job_id))
        self.assertEqual(app["application_status"], "interested")
        self.assertIsNone(app["date_applied"])
        self.assertEqual(self.repo.get_job(job_id)["lifecycle_status"], "unknown")
        self.assertIsNone(self.repo.get_job(job_id)["first_seen_at"])

    def test_one_open_application_but_multiple_completed_attempts(self):
        job_id = self.create_job()
        first = self.apps.add(job_id)
        with self.assertRaises(ConflictError):
            self.apps.add(job_id)
        self.apps.update(first, expected_version=1, application_status="withdrawn")
        self.assertNotEqual(first, self.apps.add(job_id))

    def test_application_events_and_edits_are_atomic(self):
        job_id = self.create_job()
        identity = self.apps.add(job_id, notes="Saved", resume_used="systems")
        self.apps.update(identity, expected_version=1, application_status="applied", date_applied="2026-09-25", notes="Contacted")
        self.assertEqual(self.apps.get(identity)["resume_used"], "systems")
        before = self.apps.get(identity)
        with patch.object(self.apps, "_event", side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):
                self.apps.update(identity, expected_version=2, application_status="interviewing")
        self.assertEqual(self.apps.get(identity), before)
        self.assertEqual(self.database.connection.execute("SELECT count(*) FROM application_events").fetchone()[0], 2)
        with self.assertRaises(ConflictError):
            self.apps.update(identity, expected_version=1, notes="Stale")

    def test_invalid_application_status_dates_and_actor_fail_atomically(self):
        job_id = self.create_job()
        for changes in ({"status": "invalid"}, {"date_applied": "2026-02-30"}, {"date_applied": "20260925"}, {"actor": ""}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, sqlite3.IntegrityError)):
                self.apps.add(job_id, **changes)
        self.assertEqual(self.database.check()["counts"]["applications"], 0)

    def test_source_changes_do_not_overwrite_application_fields(self):
        job_id = self.create_job()
        identity = self.apps.add(job_id, status="applied", date_applied="2026-09-25", notes="Follow up", resume_used="v2")
        before = self.apps.get(identity)
        self.repo.store_version(job_id, replace(self.posting, description="New evidence"), observed_at=utc_now())
        with self.database.transaction():
            self.database.connection.execute("UPDATE jobs SET lifecycle_status='closed' WHERE job_id=?", (job_id,))
        self.assertEqual(self.apps.get(identity), before)

    def test_applications_cannot_be_cascade_deleted_and_events_are_immutable(self):
        job_id = self.create_job()
        self.apps.add(job_id)
        for sql in ("DELETE FROM jobs", "DELETE FROM companies", "DELETE FROM applications",
                    "DELETE FROM application_events", "UPDATE application_events SET note='rewrite'"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError), self.database.transaction():
                self.database.connection.execute(sql)

    def test_creation_failure_rolls_back_job_and_all_evidence(self):
        with patch.object(self.repo, "add_alias", side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):
                self.create_job()
        self.assertEqual(self.database.check()["counts"]["jobs"], 0)
        self.assertEqual(self.database.connection.execute("SELECT count(*) FROM job_versions").fetchone()[0], 0)
