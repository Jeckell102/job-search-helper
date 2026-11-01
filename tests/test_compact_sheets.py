import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_search_helper.repository import MemoryRepository, GoogleRepository, SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS, prune_local_only_delivery
from sheets_fixture import RangeSheets
from test_sqlite_migration import job, operation, upgrade_operation


class CompactSheetsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = SQLiteRepository(Path(self.tmp.name) / 'jobs.sqlite3', 'fixture', initialize=True)
        self.addCleanup(self.local.close)
        self.local.ensure_columns('Opportunities', ['Opportunity ID'])
        self.rows = {'Companies': [{'Company': 'Acme', 'Company ID': 'COMP-1', 'Company Status': 'Active'}],
            'Job History': [job(**{'Current Snapshot': 'large snapshot', 'Recheck Limit': 5})],
            'Job Evidence': [{'Job Key': 'job-1', 'Source Hash': 'source-1', 'Job Description': 'full evidence'}]}
        full = MemoryRepository(self.rows, schemas=self.local.schemas)
        for tab in SCHEMAS:
            self.local.import_rows(tab, enumerate(full.read(tab), 2))
        with self.local.transaction():
            self.local.set_meta('ready', 'yes')
            self.local.set_meta('sheets_profile', COMPACT_PROFILE)
        self.service = RangeSheets(self.rows, schemas=COMPACT_SCHEMAS)
        self.remote = GoogleRepository(self.service, 'fixture', schemas=COMPACT_SCHEMAS, min_request_interval=0)
        self.sync = SheetsSynchronizer(self.local, self.remote)

    def test_pull_does_not_blank_local_only_fields(self):
        self.sync.pull()
        row = self.local.read('Job History')[0]
        self.assertEqual(row['Current Snapshot'], 'large snapshot')
        self.assertEqual(row['Source Hash'], 'source-1')
        self.assertEqual(row['Recheck Limit'], 5)
        self.assertEqual(self.local.status()['conflicts'], 0)

    def test_compact_key_upgrade_keeps_same_sheet_row_and_user_choice(self):
        self.local.commit([upgrade_operation()])
        self.service.set_cell('Job History', 1, 'Added to Opportunities?', 'No')
        self.sync.pull()
        self.sync.publish_batch()
        self.sync.pull()
        rows = self.remote.read('Job History')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Job Key'], 'provider-1')
        self.assertEqual(rows[0]['Added to Opportunities?'], 'No')
        self.assertEqual(self.local.read('Job History')[0]['Current Snapshot'], 'large snapshot')
        self.assertEqual(self.local.status()['pending_cells'], 0)
        self.assertEqual(self.local.status()['conflicts'], 0)

    def test_only_visible_changes_are_published(self):
        self.local.commit([operation(**{'Current Snapshot': 'new snapshot', 'Last Checked': 'today', 'Source Hash': 'source-2'}),
            {'tab': 'Job Evidence', 'identity': {'Job Key': 'job-1', 'Source Hash': 'source-2'},
             'values': {'Job Description': 'new full text'}, 'append_if_missing': True}])
        self.assertEqual(self.local.status()['pending_cells'], 1)
        self.assertEqual(self.sync.publish_batch()['published_rows'], 1)
        self.assertEqual(self.remote.read('Job History')[0]['Last Checked'], 'today')
        self.assertNotIn('Current Snapshot', self.remote.read('Job History')[0])
        self.assertEqual(len(self.local.read('Job Evidence')), 2)
        self.assertEqual(self.local.status()['pending_cells'], 0)

    def test_old_queue_flags_pruned_without_erasing_records_or_visible_work(self):
        with self.local.transaction():
            for tab, h in [('Job History', 'Source Hash'), ('Job History', 'Current Snapshot'),
                           ('Job History', 'Last Checked'), ('Job Evidence', 'Job Description')]:
                rid = self.local.db.execute('SELECT MIN(row_id) FROM records WHERE tab=?', (tab,)).fetchone()[0]
                self.local.db.execute('INSERT OR IGNORE INTO dirty VALUES (?,?,?)', (tab, rid, h))
        self.assertEqual(prune_local_only_delivery(self.local), 3)
        self.assertEqual(self.local.status()['pending_cells'], 1)
        self.assertEqual(self.local.read('Job Evidence')[0]['Job Description'], 'full evidence')

    def test_new_job_insert_omits_large_fields_and_replay_is_idempotent(self):
        op = operation('job-2', **job('job-2', **{'Current Snapshot': 'private payload'}))
        op['append_if_missing'] = True
        self.local.commit([op])
        self.sync.publish_batch(); self.sync.publish_batch(); self.sync.pull()
        self.assertEqual(len(self.remote.read('Job History')), 2)
        self.assertEqual(self.local.status()['pending_cells'], 0)
        self.assertEqual(self.local.read('Job History')[1]['Current Snapshot'], 'private payload')

    def test_already_running_old_writer_cannot_reintroduce_removed_fields(self):
        def old_writer(local):
            with local.transaction():
                for tab, h in [('Job History', 'Current Snapshot'), ('Job Evidence', 'Job Description')]:
                    rid = local.db.execute('SELECT MIN(row_id) FROM records WHERE tab=?', (tab,)).fetchone()[0]
                    local.db.execute('INSERT OR IGNORE INTO dirty VALUES (?,?,?)', (tab, rid, h))
        with patch('job_search_helper.sheets_sync.prune_local_only_delivery', side_effect=old_writer):
            self.assertEqual(self.sync._operations(), [])

    def test_manual_yes_and_no_keep_working_without_remote_source_hash(self):
        self.service.set_cell('Job History', 1, 'Added to Opportunities?', 'Yes')
        self.sync.pull(); self.sync.publish_batch(); self.sync.publish_batch()
        self.assertEqual(len(self.remote.read('Opportunities')), 1)
        self.assertTrue(self.remote.read('Opportunities')[0]['Opportunity ID'])
        self.service.set_cell('Job History', 1, 'Added to Opportunities?', 'No')
        self.sync.pull(); self.sync.publish_batch()
        row = self.local.read('Job History')[0]
        self.assertEqual(row['Decision'], 'Reject')
        self.assertEqual(row['Added to Opportunities?'], 'No')
        self.assertEqual(self.local.status()['conflicts'], 0)

    def test_sheet_notes_and_company_additions_flow_back(self):
        self.service.set_cell('Job History', 1, 'Review Notes', 'My review')
        self.service.set_cell('Companies', 2, 'Company', 'New firm')
        self.service.set_cell('Companies', 2, 'Website', 'https://new.example')
        self.sync.pull(); self.sync.publish_batch()
        self.assertEqual(self.local.read('Job History')[0]['Review Notes'], 'My review')
        self.assertEqual(len(self.local.read('Companies')), 2)
        self.assertTrue(self.remote.read('Companies')[1]['Company ID'])

    def test_newer_local_visible_edit_survives_ack(self):
        self.local.commit([operation(**{'Last Checked': 'first'})])
        original = self.remote.commit
        def concurrent(ops):
            result = original(ops)
            self.local.commit([operation(**{'Last Checked': 'second'})])
            return result
        with patch.object(self.remote, 'commit', side_effect=concurrent):
            self.sync.publish_batch()
        self.assertEqual(self.local.status()['pending_cells'], 1)
        self.sync.publish_batch()
        self.assertEqual(self.remote.read('Job History')[0]['Last Checked'], 'second')

    def test_duplicate_applications_retain_independent_statuses(self):
        shared = {'Company': 'Acme', 'Job URL': 'https://jobs.example.com/job-1', 'Job Title': 'Engineer'}
        rows = [dict(shared, **{'Opportunity ID': 'OPP-a', 'Application Status': 'Applied', 'Notes': 'First'}),
                dict(shared, **{'Opportunity ID': 'OPP-b', 'Application Status': 'Not Interested', 'Notes': 'Second'})]
        full = MemoryRepository({'Opportunities': rows}, schemas=self.local.schemas)
        self.local.import_rows('Opportunities', enumerate(full.read('Opportunities'), 2))
        service = RangeSheets(dict(self.rows, Opportunities=rows), schemas=COMPACT_SCHEMAS)
        remote = GoogleRepository(service, 'fixture', schemas=COMPACT_SCHEMAS, min_request_interval=0)
        sync = SheetsSynchronizer(self.local, remote)
        service.set_cell('Opportunities', 1, 'Date Applied', '2026-10-12')
        sync.pull()
        self.local.commit([{'tab': 'Opportunities', 'identity': {'Company': 'Acme', 'Job URL': shared['Job URL']},
                           'values': {'Last Checked': 'today'}}])
        sync.publish_batch()
        actual = remote.read('Opportunities')
        self.assertEqual([r['Application Status'] for r in actual], ['Applied', 'Not Interested'])
        self.assertEqual(actual[0]['Date Applied'], '2026-10-12')
        self.assertEqual([r['Notes'] for r in actual], ['First', 'Second'])


if __name__ == '__main__':
    unittest.main()
