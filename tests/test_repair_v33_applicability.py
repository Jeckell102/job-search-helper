"""Legacy validation repair must reject unsupported modes before side effects."""
from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from job_search_helper import repair_v33_validation as repair_module
from job_search_helper.repository import GoogleRepository, MemoryRepository
from job_search_helper.sheet_profile import COMPACT_SCHEMAS


class LegacyValidationApplicabilityTests(unittest.TestCase):
    def test_sqlite_command_rejected_before_state_directory_lock_or_auth(self):
        with patch.object(repair_module, '_load_environment'), \
             patch('job_search_helper.cli.storage_backend', return_value='sqlite'), \
             patch.object(repair_module, 'state_path') as state, \
             patch.object(repair_module, 'writer_lock') as lock, \
             patch('job_search_helper.cli.get_remote_repository') as repository:
            with self.assertRaisesRegex(ValueError, 'legacy|full-schema|SQLite'):
                repair_module.main()
            state.assert_not_called()
            lock.assert_not_called()
            repository.assert_not_called()

    def test_compact_and_non_google_repositories_rejected_before_read_or_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / 'must-not-exist'
            compact = GoogleRepository(MagicMock(), 'fixture', schemas=COMPACT_SCHEMAS, min_request_interval=0)
            compact._load = MagicMock()
            memory = MemoryRepository()
            memory.spreadsheet_id = 'fixture'
            for repo in (compact, memory):
                with self.subTest(kind=type(repo).__name__):
                    with self.assertRaisesRegex(ValueError, 'legacy|full-schema|Google'):
                        repair_module.repair(repo, destination)
                    self.assertFalse(destination.exists())
            compact._load.assert_not_called()
            compact.service.spreadsheets.assert_not_called()

    def test_full_schema_default_uses_direct_google_repository_and_keeps_workflow(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / 'new-state' / 'state.db'
            with patch.object(repair_module, '_load_environment'), \
                 patch('job_search_helper.cli.storage_backend', return_value='sheets'), \
                 patch.object(repair_module, 'state_path', return_value=database), \
                 patch.object(repair_module, 'writer_lock', return_value=nullcontext()), \
                 patch('job_search_helper.cli.get_remote_repository') as remote, \
                 patch.object(repair_module, 'repair') as repair:
                self.assertEqual(repair_module.main(), 0)
                remote.assert_called_once_with(write=True, interactive=False, evidence_archives=False)
                repair.assert_called_once_with(remote.return_value, database.parent)
                self.assertTrue(database.parent.exists())
