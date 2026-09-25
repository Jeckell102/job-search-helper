import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper import database as module
from job_search_helper.database import Database, DatabaseError
from job_search_helper.repositories import CatalogRepository


class LocalDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "data/catalog.sqlite3"
        self.database = Database.initialize(self.path)
        self.addCleanup(self.database.close)

    def test_new_database_has_four_logical_entities_and_private_file(self):
        check = self.database.check()
        self.assertEqual(check["counts"], {"companies": 0, "jobs": 0, "applications": 0, "scan_cycles": 0})
        self.assertEqual(check["schema_version"], module.SCHEMA_VERSION)
        self.assertEqual(check["journal_mode"], "delete")
        self.assertEqual(self.database.connection.execute("PRAGMA synchronous").fetchone()[0], 2)
        if os.name == "posix":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_initialization_repeated_does_not_replace_records_or_identity(self):
        CatalogRepository(self.database).add_company("Acme", company_id="COMP-001")
        before = self.path.read_bytes()
        with Database.initialize(self.path) as again:
            self.assertEqual(again.database_id, self.database.database_id)
            self.assertEqual(again.check()["counts"]["companies"], 1)
        self.assertEqual(before, self.path.read_bytes())

    def test_foreign_keys_enabled_on_every_connection(self):
        for readonly in (False, True):
            with Database(self.path, readonly=readonly) as database:
                self.assertEqual(database.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError), self.database.transaction():
            self.database.connection.execute(
                "INSERT INTO job_sources VALUES ('source', 'missing', 'lever', 'board', 'https://example.com', 1, 'now')"
            )

    def test_unknown_and_legacy_databases_are_not_adopted(self):
        path = self.root / "legacy.db"
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE cycles(id TEXT, data TEXT)")
        connection.commit()
        connection.close()
        before = path.read_bytes()
        for operation in (Database.initialize, Database.migrate, Database):
            with self.subTest(operation=operation), self.assertRaises(DatabaseError):
                operation(path)
            self.assertEqual(before, path.read_bytes())

    def test_newer_schema_is_refused_without_mutation(self):
        self.database.connection.execute("PRAGMA user_version = 999")
        before = self.path.read_bytes()
        for operation in (Database, Database.initialize, Database.migrate):
            with self.assertRaisesRegex(DatabaseError, "newer"):
                operation(self.path)
            self.assertEqual(before, self.path.read_bytes())

    def test_changed_migration_checksum_is_refused(self):
        self.database.connection.execute("UPDATE schema_migrations SET checksum = 'tampered'")
        with self.assertRaisesRegex(DatabaseError, "checksum"):
            Database(self.path)

    def test_inconsistent_migration_history_is_refused(self):
        self.database.connection.execute("DELETE FROM schema_migrations")
        with self.assertRaisesRegex(DatabaseError, "history"):
            Database(self.path)

    def test_schema_upgrade_is_atomic_and_records_checksum(self):
        original = module._migration
        current = module.SCHEMA_VERSION
        sql = "CREATE TABLE upgrade_probe(value TEXT);\n"
        checksum = hashlib.sha256(sql.encode()).hexdigest()
        with patch.object(module, "MIGRATIONS", (*module.MIGRATIONS, "next_probe.sql")), \
                patch.object(module, "SCHEMA_VERSION", current + 1), \
                patch.object(module, "_migration", side_effect=lambda n: original(n) if n <= current else (sql, checksum)):
            with self.assertRaisesRegex(DatabaseError, "upgrade"):
                Database(self.path)
            with Database.migrate(self.path) as upgraded:
                self.assertEqual(upgraded.connection.execute("PRAGMA user_version").fetchone()[0], current + 1)
                self.assertEqual(upgraded.connection.execute("SELECT checksum FROM schema_migrations WHERE version=?", (current + 1,)).fetchone()[0], checksum)

    def test_failed_migration_rolls_back_schema_and_version(self):
        original = module._migration
        current = module.SCHEMA_VERSION
        sql = "CREATE TABLE failed_probe(value TEXT);\nINVALID SQL;\n"
        with patch.object(module, "MIGRATIONS", (*module.MIGRATIONS, "next_failure.sql")), \
                patch.object(module, "SCHEMA_VERSION", current + 1), \
                patch.object(module, "_migration", side_effect=lambda n: original(n) if n <= current else (sql, "test")):
            with self.assertRaises(sqlite3.Error):
                Database.migrate(self.path)
        self.assertEqual(self.database.connection.execute("PRAGMA user_version").fetchone()[0], current)
        self.assertIsNone(self.database.connection.execute("SELECT name FROM sqlite_master WHERE name='failed_probe'").fetchone())
        self.assertTrue(self.database.check()["ok"])

    def test_failed_initialization_does_not_leave_a_half_catalog(self):
        target = self.root / "failure.sqlite3"
        with patch.object(module, "_execute_migration", side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):
                Database.initialize(target)
        self.assertFalse(target.exists())

    def test_real_foundation_upgrade_preserves_existing_evidence(self):
        path = self.root / "foundation.sqlite3"
        with patch.object(module, "MIGRATIONS", module.MIGRATIONS[:1]), patch.object(module, "SCHEMA_VERSION", 1):
            with Database.initialize(path) as old:
                repo = CatalogRepository(old)
                repo.add_company("Existing", company_id="old-company")
                with old.transaction():
                    old.connection.execute(
                        "INSERT INTO jobs(job_id, company_id, origin, created_at, updated_at) "
                        "VALUES ('old-job', 'old-company', 'manual', '2026-09-24T10:00:00Z', '2026-09-24T10:00:00Z')")
                    old.connection.execute(
                        "INSERT INTO job_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        ("old-version", "old-job", "Original title", "", "", "", "Evidence " * 10000, "", "", 1,
                         "September 24, 2026", "", "2026-09-24T10:00:00Z", "material", "legacy-v1", "evidence", "adapter-v1", "{}"))
                    old.connection.execute("UPDATE jobs SET current_version_id='old-version' WHERE job_id='old-job'")
                identity = old.database_id
        with self.assertRaisesRegex(DatabaseError, "upgrade"):
            Database(path)
        with Database.migrate(path) as upgraded:
            self.assertEqual(upgraded.database_id, identity)
            job = CatalogRepository(upgraded).get_job("old-job")
            self.assertEqual(job["description"], "Evidence " * 10000)
            self.assertEqual(job["source_created_raw"], "September 24, 2026")
            self.assertIsNone(job["source_created_at"])
            self.assertEqual(job["latest_observation_sequence"], 0)
            self.assertTrue(upgraded.check()["ok"])

    def test_outer_transaction_rolls_back_nested_repository_writes(self):
        with self.assertRaises(KeyboardInterrupt), self.database.transaction():
            CatalogRepository(self.database).add_company("Uncommitted")
            raise KeyboardInterrupt()
        self.assertEqual(self.database.check()["counts"]["companies"], 0)
        self.assertFalse(self.database.connection.in_transaction)

    def test_inner_failure_preserves_outer_transaction(self):
        repo = CatalogRepository(self.database)
        with self.database.transaction():
            repo.add_company("First", company_id="one")
            with self.assertRaises(sqlite3.IntegrityError):
                repo.add_company("Duplicate", company_id="one")
            repo.add_company("Second", company_id="two")
        self.assertEqual(self.database.check()["counts"]["companies"], 2)

    def test_read_only_checks_do_not_change_database_bytes(self):
        before = self.path.read_bytes()
        with Database(self.path, readonly=True) as reader:
            reader.check()
            with self.assertRaises(sqlite3.OperationalError):
                reader.connection.execute("DELETE FROM companies")
        self.assertEqual(before, self.path.read_bytes())

    def test_missing_read_only_database_is_not_created(self):
        missing = self.root / "missing.sqlite3"
        with self.assertRaises(sqlite3.OperationalError):
            Database(missing, readonly=True)
        self.assertFalse(missing.exists())

    def test_second_writer_is_bounded_and_does_not_commit(self):
        with Database(self.path) as second, self.database.transaction():
            second.connection.execute("PRAGMA busy_timeout=10")
            with self.assertRaises(sqlite3.OperationalError):
                CatalogRepository(second).add_company("Conflicting writer")
        self.assertEqual(self.database.check()["counts"]["companies"], 0)

    def test_backup_restores_committed_records_and_identity(self):
        CatalogRepository(self.database).add_company("Acme", company_id="001")
        target = self.database.backup(self.root / "backups/snapshot.sqlite3")
        with Database(target) as restored:
            self.assertTrue(restored.check()["ok"])
            self.assertEqual(restored.database_id, self.database.database_id)
            self.assertEqual(restored.connection.execute("SELECT company_id FROM companies").fetchone()[0], "001")
            CatalogRepository(restored).add_company("Restored workspace")
        self.assertEqual(self.database.check()["counts"]["companies"], 1)
        self.assertEqual(list(target.parent.glob(".jsh-backup-*")), [])

    def test_backup_never_overwrites_existing_destination(self):
        target = self.root / "existing.sqlite3"
        target.write_bytes(b"preserve me")
        with self.assertRaises(FileExistsError):
            self.database.backup(target)
        self.assertEqual(target.read_bytes(), b"preserve me")

    def test_failed_backup_verification_does_not_publish(self):
        target = self.root / "bad.sqlite3"
        with patch.object(Database, "check", side_effect=DatabaseError("injected corruption")):
            with self.assertRaises(DatabaseError):
                self.database.backup(target)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob(".jsh-backup-*")), [])

    def test_backup_refuses_open_transaction(self):
        with self.database.transaction(), self.assertRaises(DatabaseError):
            self.database.backup(self.root / "blocked.sqlite3")

    def test_crash_before_commit_recovers_without_partial_records(self):
        script = """
import os, sys
from job_search_helper.database import Database
from job_search_helper.repositories import CatalogRepository
with Database(sys.argv[1]) as database, database.transaction():
    CatalogRepository(database).add_company('Not committed')
    os._exit(0)
"""
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                           PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        completed = subprocess.run([sys.executable, "-c", script, str(self.path)], env=environment,
                                   cwd=self.root, capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.database.check()["counts"]["companies"], 0)
