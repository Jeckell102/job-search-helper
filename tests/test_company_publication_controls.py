"""Offline guards for company edits made after a scraper's startup intake."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.repository import MemoryRepository, ReviewFieldsChangedError, SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.sheets_sync import SheetsSynchronizer


class CompanyPublicationControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.local = SQLiteRepository(Path(self.temp.name) / 'jobs.sqlite3', 'fixture', initialize=True)
        self.addCleanup(self.local.close)
        self.remote = MemoryRepository({'Companies': [{
            'Company': 'Acme', 'Company ID': 'C-1', 'Company Status': 'Active',
            'Official Careers URL': 'https://example.com/old-careers', 'ATS / Source': 'fixture'}],
            'Job History': [{'Company': 'Acme', 'Job Key': 'old-job',
                             'Official Job URL': 'https://example.com/jobs/1',
                             'Added to Opportunities?': 'Pending', 'Review Status': 'Needs Review'}]})
        self.remote.spreadsheet_id = 'fixture'
        for tab in SCHEMAS:
            self.local.import_rows(tab, enumerate(self.remote.read(tab), 2))
        with self.local.transaction():
            self.local.set_meta('ready', 'yes')
        self.sync = SheetsSynchronizer(self.local, self.remote)
        self.local.commit([{'tab': 'Job History', 'identity': {'Job Key': 'old-job'},
                            'values': {'Last Checked': 'today'}}])

    def edit_company(self, **values):
        self.remote.commit([{'tab': 'Companies', 'identity': {'Company ID': 'C-1'}, 'values': values}])

    def test_post_start_source_change_reconciles_to_one_outbox_event_only(self):
        # The first completed intake is only a watermark: it must not turn the
        # historical Company list into newly admitted scrape work.
        first = self.sync.pull()
        self.assertEqual(first['company_event_baseline'], {'bootstrapped': True, 'seeded': 1})
        self.assertEqual(self.local.pending_company_events('intake'), [])

        # This models a later, periodic Sheets intake during the same run.
        self.edit_company(**{'ATS / Source': 'Lever'})
        second = self.sync.pull()
        events = second['company_event_reconciliation']['company_events']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['kind'], 'company.eligible')
        self.assertEqual(events[0]['company_id'], 'C-1')
        self.assertEqual(self.local.pending_company_events('intake'), events)

        # An unchanged periodic pull is idempotent and cannot flood the
        # historical Company inventory into the outbox.
        third = self.sync.pull()
        self.assertEqual(third['company_event_reconciliation']['company_events'], [])
        self.assertEqual(self.local.pending_company_events('intake'), events)

    def test_failed_periodic_pull_preserves_event_baseline_and_outbox(self):
        self.sync.pull()
        baseline = self.local.db.execute(
            "SELECT value FROM meta WHERE key='company_event_external_baseline'").fetchone()[0]
        outbox = self.local.pending_company_events('intake')
        with patch.object(self.remote, 'read', side_effect=OSError('offline')):
            with self.assertRaisesRegex(OSError, 'offline'):
                self.sync.pull()
        self.assertEqual(self.local.db.execute(
            "SELECT value FROM meta WHERE key='company_event_external_baseline'").fetchone()[0], baseline)
        self.assertEqual(self.local.pending_company_events('intake'), outbox)

    def test_pause_after_startup_holds_delivery_and_unpause_resumes(self):
        self.edit_company(**{'Company Status': 'Paused'})
        with self.assertRaises(ReviewFieldsChangedError):
            self.sync.publish_batch()
        self.sync.pull()
        result = self.sync.publish_batch()
        self.assertEqual(result['published_rows'], 0)
        self.assertEqual(self.remote.read('Job History')[0]['Last Checked'], '')
        self.assertGreater(self.local.status()['pending_cells'], 0)
        self.edit_company(**{'Company Status': 'Active'})
        self.sync.pull()
        self.assertEqual(self.sync.publish_batch()['published_rows'], 1)
        self.assertEqual(self.remote.read('Job History')[0]['Last Checked'], 'today')

    def test_source_change_stays_held_after_fresh_pull_and_repeated_retry(self):
        self.edit_company(**{'Official Careers URL': 'https://example.com/new-careers'})
        with self.assertRaises(ReviewFieldsChangedError):
            self.sync.publish_batch()
        self.sync.pull()
        for _ in range(2):
            self.assertEqual(self.sync.publish_batch()['published_rows'], 0)
            self.sync.pull()
        self.assertEqual(self.remote.read('Job History')[0]['Last Checked'], '')
        self.assertEqual(self.local.db.execute(
            "SELECT count(*) FROM conflicts WHERE tab='Job History' AND header='__company_source__'").fetchone()[0], 1)
        self.assertGreater(self.local.status()['pending_cells'], 0)
        self.assertEqual(self.local.db.execute('SELECT count(*) FROM delivery_attempts').fetchone()[0], 0)

    def test_late_old_source_output_is_held_by_durable_company_fence(self):
        self.edit_company(**{'Official Careers URL': 'https://example.com/new-careers'})
        self.sync.pull()
        self.local.commit([{'tab': 'Job History', 'identity': {'Job Key': 'late-old-source'},
            'append_if_missing': True, 'values': {'Company': 'Acme',
            'Official Job URL': 'https://example.com/jobs/late', 'Last Checked': 'today'}}])
        self.assertEqual(self.sync.publish_batch()['published_rows'], 0)
        self.sync.pull()
        self.assertEqual(self.sync.publish_batch()['published_rows'], 0)
        self.assertEqual(len(self.remote.read('Job History')), 1)
        self.assertEqual(len(self.local.read('Job History')), 2)

    def test_external_claim_holds_without_discarding_pending_work(self):
        self.edit_company(**{'Claimed By': 'coordinator', 'Claim Token': 'fixture-claim'})
        with self.assertRaises(ReviewFieldsChangedError):
            self.sync.publish_batch()
        self.sync.pull()
        self.assertEqual(self.sync.publish_batch()['published_rows'], 0)
        self.assertEqual(self.remote.read('Job History')[0]['Last Checked'], '')
        self.assertGreater(self.local.status()['pending_cells'], 0)

    def test_company_removed_after_assignment_holds_its_pending_jobs(self):
        self.remote = MemoryRepository({'Job History': self.remote.read('Job History')})
        self.remote.spreadsheet_id = 'fixture'
        self.sync.remote = self.remote
        result = self.sync.publish_batch()
        self.assertEqual(result.get('held_missing_rows'), 1)
        self.assertEqual(self.sync.publish_batch()['published_rows'], 0)
        self.assertEqual(self.remote.read('Job History')[0]['Last Checked'], '')
        self.assertEqual(self.local.read('Companies')[0]['Company Status'], 'Paused')

    def test_rename_and_source_change_hold_old_name_rows_across_restart(self):
        self.edit_company(**{'Company': 'New Acme',
                             'Official Careers URL': 'https://example.com/new-careers'})
        self.sync.pull()
        self.assertEqual(self.local.db.execute(
            "SELECT count(*) FROM conflicts WHERE tab='Job History' AND header='__company_source__'").fetchone()[0], 1)
        self.local.close()
        self.local = SQLiteRepository(Path(self.temp.name) / 'jobs.sqlite3', 'fixture')
        self.addCleanup(self.local.close)
        self.sync = SheetsSynchronizer(self.local, self.remote)
        self.local.commit([{'tab': 'Job History', 'identity': {'Job Key': 'late-old-name'},
            'append_if_missing': True, 'values': {'Company': ' ACME ',
            'Official Job URL': 'https://example.com/jobs/late', 'Last Checked': 'today'}}])
        self.sync.pull()
        self.assertEqual(self.sync.publish_batch()['published_rows'], 0)
        self.assertEqual(self.remote.read('Job History')[0]['Last Checked'], '')
        self.assertEqual(len(self.remote.read('Job History')), 1)

    def test_renamed_company_pause_still_owns_old_name_jobs_and_can_resume(self):
        self.edit_company(**{'Company': 'New Acme', 'Company Status': 'Paused'})
        self.sync.pull()
        self.assertEqual(self.sync.publish_batch()['published_rows'], 0)
        self.assertEqual(self.remote.read('Job History')[0]['Last Checked'], '')
        self.edit_company(**{'Company Status': 'Active'})
        self.sync.pull()
        self.assertEqual(self.sync.publish_batch()['published_rows'], 1)
        self.assertEqual(self.remote.read('Job History')[0]['Last Checked'], 'today')

    def test_reused_company_name_is_ambiguous_with_historical_owner(self):
        self.edit_company(**{'Company': 'New Acme'})
        self.sync.pull()
        self.remote.commit([{'tab': 'Companies', 'identity': {'Company ID': 'C-2'},
            'append_if_missing': True, 'values': {'Company': 'Acme', 'Company Status': 'Active'}}])
        self.sync.pull()
        from job_search_helper.repository import RepositoryError
        with self.assertRaisesRegex(RepositoryError, 'ambiguous company owner'):
            self.sync.publish_batch()
        self.assertEqual(self.remote.read('Job History')[0]['Last Checked'], '')

    def test_source_change_after_multiple_renames_holds_original_dirty_rows(self):
        self.edit_company(**{'Company': 'Second Acme'})
        self.sync.pull()
        self.edit_company(**{'Company': 'Third Acme',
                             'Official Careers URL': 'https://example.com/new-careers'})
        self.sync.pull()
        self.assertEqual(self.local.db.execute(
            "SELECT count(*) FROM conflicts WHERE tab='Job History' AND header='__company_source__'").fetchone()[0], 1)
        self.assertEqual(self.sync.publish_batch()['published_rows'], 0)
