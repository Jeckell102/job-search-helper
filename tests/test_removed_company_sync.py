"""A company removed during a scrape must not block unrelated publication."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.repository import MemoryRepository, MissingIdentityError, RepositoryError, SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.sheets_sync import SheetsSynchronizer


class RemovedCompanyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.local = SQLiteRepository(Path(self.temp.name) / 'jobs.sqlite3', 'fixture', initialize=True)
        self.addCleanup(self.local.close)
        self.remote = MemoryRepository({'Companies': [
            {'Company': 'Removed', 'Company ID': 'COMP-removed', 'Company Status': 'Active'},
            {'Company': 'Retained', 'Company ID': 'COMP-retained', 'Company Status': 'Active'}]})
        self.remote.spreadsheet_id = 'fixture'
        for tab in SCHEMAS:
            self.local.import_rows(tab, enumerate(self.remote.read(tab), 2))
        with self.local.transaction():
            self.local.set_meta('ready', 'yes')
        self.local.commit([{'tab': 'Companies', 'identity': {'Company ID': key},
                            'values': {'Last Checked': '2026-11-02'}} for key in ('COMP-removed', 'COMP-retained')])
        self.sync = SheetsSynchronizer(self.local, self.remote)

    def remove_company(self):
        self.remote = MemoryRepository({'Companies': [self.remote.read('Companies')[1]]})
        self.remote.spreadsheet_id = 'fixture'
        self.sync.remote = self.remote

    def test_missing_company_is_preserved_paused_and_other_company_can_publish(self):
        self.remove_company()
        first = self.sync.publish_batch()
        self.assertEqual(first, {'published_rows': 0, 'held_missing_rows': 1})
        self.assertEqual(self.remote.read('Companies')[0]['Last Checked'], '')
        self.assertEqual(self.local.read('Companies')[0]['Company Status'], 'Paused')
        self.assertEqual(len(self.local.read('Companies')), 2)
        self.assertEqual(self.local.db.execute('SELECT count(*) FROM delivery_attempts').fetchone()[0], 0)
        second = self.sync.publish_batch()
        self.assertEqual(second['published_rows'], 1)
        self.assertEqual(self.remote.read('Companies')[0]['Last Checked'], '2026-11-02')
        self.assertEqual(len(self.remote.read('Companies')), 1)

    def test_duplicate_or_uncertain_write_is_never_treated_as_a_deletion(self):
        for error in (RepositoryError('duplicate identity'), OSError('lost response')):
            with self.subTest(error=error), patch.object(self.remote, 'commit', side_effect=error):
                with self.assertRaises(type(error)):
                    self.sync.publish_batch()
            self.assertEqual(self.local.read('Companies')[0]['Company Status'], 'Active')
            self.assertEqual(self.local.db.execute('SELECT count(*) FROM conflicts').fetchone()[0], 0)

    def test_scoped_publication_keeps_exact_missing_identity_failure(self):
        self.remove_company()
        rid = self.local.matches('Companies', {'Company ID': 'COMP-removed'})[0][0]
        with self.assertRaises(MissingIdentityError):
            self.sync.publish_batch(row_scope={('Companies', rid): {'Last Checked'}})
        self.assertEqual(self.local.read('Companies')[0]['Company Status'], 'Active')


if __name__ == '__main__':
    unittest.main()
