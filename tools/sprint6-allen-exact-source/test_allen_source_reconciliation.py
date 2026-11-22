"""Real local merge/events with an in-memory guarded workbook only."""
from pathlib import Path
import copy
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.allen_source_reconciliation import (
    AFTER, BEFORE, COMPANY_ID, COMPANY_NAME, RECORD_KEY,
    continue_allen_source_reconciliation, preflight_allen_source_reconciliation)
from job_search_helper.company_events import source_revision
from job_search_helper.repository import MemoryRepository, RepositoryError, SCHEMAS, UncertainWriteError
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sqlite_repository import SQLiteRepository


class Workbook(MemoryRepository):
    def __init__(self, data):
        super().__init__(data)
        self.spreadsheet_id = 'fixture-workbook'
        self.attempts = []
        self.lose_after = False
        self.lose_before = False

    def commit(self, operations):
        self.attempts.append(copy.deepcopy(operations))
        if self.lose_before:
            raise UncertainWriteError('fixture response loss with no visible commit')
        result = super().commit(operations)
        if self.lose_after:
            raise UncertainWriteError('fixture response loss after committed write')
        return result


class AllenSourceReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'jobs.sqlite3'
        allen = {'Company ID': COMPANY_ID, 'Company': COMPANY_NAME,
                 'Company Status': 'Active', 'Notes': 'Remote owner note',
                 'Priority': 'Medium', **BEFORE}
        other = {'Company ID': 'COMP-9999', 'Company': 'Unrelated',
                 'Company Status': 'Active', 'ATS / Source': 'Greenhouse',
                 'Official Careers URL': 'https://example.test/old'}
        self.remote = Workbook({'Companies': [allen, other], 'Job History': [{
            'Company': COMPANY_NAME, 'Job Key': 'old-job',
            'Official Job URL': 'https://example.test/old-job'}]})
        self.local = SQLiteRepository(self.path, 'fixture-workbook', initialize=True)
        self.addCleanup(lambda: self.local.close())
        for tab in SCHEMAS:
            self.local.import_rows(tab, enumerate(self.remote.read(tab), 2))
        with self.local.transaction():
            self.local.set_meta('ready', 'yes')
        self.local.bootstrap_company_event_reconciliation()
        self.intent = {'schema': 'allen-source-reconciliation-v1',
                       'spreadsheet_id': 'fixture-workbook', 'company_id': COMPANY_ID,
                       'company': COMPANY_NAME, 'company_status': 'Active',
                       'before': dict(BEFORE), 'after': dict(AFTER),
                       'expected_source_revision': source_revision(allen)}
        self.local.commit([
            {'tab': 'Companies', 'identity': {'Company ID': COMPANY_ID},
             'values': {'Notes': 'Remote owner note plus local note', 'Priority': 'High'}},
            {'tab': 'Job History', 'identity': {'Job Key': 'old-job'},
             'values': {'Last Checked': 'fixture-checked'}}])
        # Another real local revision must remain outside this event operation.
        self.local.commit([{'tab': 'Companies', 'identity': {'Company ID': 'COMP-9999'},
                            'values': {'Official Careers URL': 'https://example.test/new'}}])

    def restart(self):
        self.local.close()
        self.local = SQLiteRepository(self.path, 'fixture-workbook')

    def dirty(self):
        return self.local.db.execute('SELECT * FROM dirty ORDER BY tab,row_id,header').fetchall()

    def run_continuation(self):
        return continue_allen_source_reconciliation(self.local, self.remote, self.intent)

    def verify_complete_and_replay(self):
        before_db = list(self.local.db.iterdump())
        before_remote = {tab: self.remote.read(tab) for tab in SCHEMAS}
        before_local = self.local.read('Companies')
        dirty = self.dirty()
        check = preflight_allen_source_reconciliation(self.local, self.remote, self.intent)
        self.assertEqual((check['state'], check['would_write_remote']), ('READY', True))
        self.assertEqual(list(self.local.db.iterdump()), before_db)
        self.assertEqual(self.remote.attempts, [])
        result = self.run_continuation()
        self.assertEqual(result['state'], 'COMPLETE')
        event = result['company_event']
        self.assertEqual((event['company_id'], event['revision']), (COMPANY_ID, 2))
        self.assertEqual(len(self.remote.attempts), 1)
        operation = self.remote.attempts[0][0]
        self.assertEqual(operation['values'], AFTER)
        self.assertEqual(operation['identity'], {'Company ID': COMPANY_ID})
        self.assertFalse(operation['append_if_missing'])
        for tab in SCHEMAS:
            expected = copy.deepcopy(before_remote[tab])
            if tab == 'Companies':
                expected[0].update(AFTER)
            self.assertEqual(self.remote.read(tab), expected, tab)
        expected_local = copy.deepcopy(before_local)
        expected_local[0].update(AFTER)
        self.assertEqual(self.local.read('Companies'), expected_local)
        self.assertEqual(self.dirty(), dirty)
        self.assertEqual(self.local.pending_company_events('fixture'), [event])
        self.restart()
        replay = self.run_continuation()
        self.assertEqual(replay['company_event'], event)
        self.assertFalse(replay['remote_write_attempted'])
        self.assertEqual(len(self.remote.attempts), 1)
        self.assertEqual(self.dirty(), dirty)

    def test_correction_replay_writes_only_two_fields_once(self):
        self.verify_complete_and_replay()

    def test_committed_lost_response_replay_writes_only_two_fields_once(self):
        self.remote.lose_after = True
        self.verify_complete_and_replay()

    def test_uncertain_old_readback_never_reissues_claimed_write(self):
        self.remote.lose_before = True
        with self.assertRaises(UncertainWriteError):
            self.run_continuation()
        self.assertEqual(len(self.remote.attempts), 1)
        self.assertEqual(self.local.pending_company_events('fixture'), [])
        self.restart()
        self.assertEqual(preflight_allen_source_reconciliation(
            self.local, self.remote, self.intent)['state'], 'HELD_UNCERTAIN_WRITE')
        self.remote.lose_before = False
        with self.assertRaises(UncertainWriteError):
            self.run_continuation()
        self.assertEqual(len(self.remote.attempts), 1)
        self.assertEqual(self.local.pending_company_events('fixture'), [])

    def test_restart_after_merge_or_event_failure_uses_one_remote_write(self):
        with patch.object(self.local, 'reconcile_external_company_events',
                          side_effect=RuntimeError('fixture after committed merge')):
            with self.assertRaisesRegex(RuntimeError, 'after committed merge'):
                self.run_continuation()
        self.assertEqual(len(self.remote.attempts), 1)
        self.assertEqual(self.local.pending_company_events('fixture'), [])
        self.restart()
        result = self.run_continuation()
        self.assertEqual(result['state'], 'COMPLETE')
        self.assertEqual(len(self.remote.attempts), 1)
        self.assertEqual([row['company_id'] for row in self.local.pending_company_events('fixture')],
                         [COMPANY_ID])

    def test_dirty_source_holds_before_claim_or_write(self):
        self.local.commit([{'tab': 'Companies', 'identity': {'Company ID': COMPANY_ID},
                            'values': {'Official Careers URL': 'https://example.test/conflict'}}])
        before = list(self.local.db.iterdump())
        with self.assertRaises(RepositoryError):
            self.run_continuation()
        self.assertEqual(list(self.local.db.iterdump()), before)
        self.assertEqual(self.remote.attempts, [])
        self.assertIsNone(self.local.get_meta(RECORD_KEY))

    def test_readonly_preflight_preserves_retired_marker_and_continuation_refuses(self):
        # The outer caller verifies retirement/admission. This field is history,
        # not authority for this source-only helper to clear or resume a cycle.
        with self.local.transaction():
            rid, row = self.local.matches('Companies', {'Company ID': COMPANY_ID})[0]
            row['Active Cycle ID'] = 'CYC-B639C6D864EC'
            self.local._put('Companies', rid, row)
        self.local.close()
        self.local = SQLiteRepository(self.path, 'fixture-workbook', readonly=True)
        before = list(self.local.db.iterdump())
        writes = []
        self.local.db.set_authorizer(lambda action, arg1, arg2, dbname, trigger:
            (writes.append(action) or sqlite3.SQLITE_DENY) if action in {
                sqlite3.SQLITE_INSERT, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_UPDATE,
                sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE,
                sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_DROP_INDEX,
                sqlite3.SQLITE_TRANSACTION,
            } else sqlite3.SQLITE_OK)
        result = preflight_allen_source_reconciliation(self.local, self.remote, self.intent)
        self.assertEqual((result['state'], result['would_write_remote']), ('READY', True))
        self.assertEqual(writes, [])
        with self.assertRaisesRegex(RepositoryError, 'requires writable Jobs'):
            self.run_continuation()
        self.assertEqual(writes, [])
        self.local.close()
        self.local = SQLiteRepository(self.path, 'fixture-workbook', readonly=True)
        self.assertEqual(list(self.local.db.iterdump()), before)
        self.assertEqual(self.local.matches('Companies', {'Company ID': COMPANY_ID})[0][1][
            'Active Cycle ID'], 'CYC-B639C6D864EC')
        self.assertEqual(self.remote.attempts, [])


if __name__ == '__main__':
    unittest.main()
