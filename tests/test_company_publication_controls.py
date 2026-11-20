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

    def test_bootstrap_catchup_turns_mid_bootstrap_source_change_into_one_event(self):
        original = self.remote.read
        calls = {'companies': 0}
        def read(tab):
            rows = original(tab)
            if tab == 'Companies':
                calls['companies'] += 1
                if calls['companies'] == 1:
                    # The first snapshot is the historical watermark.  This
                    # edit arrives before the mandatory catch-up reread.
                    self.edit_company(**{'ATS / Source': 'Lever'})
            return rows
        with patch.object(self.remote, 'read', side_effect=read):
            result = self.sync.pull()
        self.assertEqual({'bootstrapped': True, 'seeded': 1}, result['company_event_baseline'])
        self.assertEqual(1, result['company_event_bootstrap_catchup']['changed_fields'])
        events = self.local.pending_company_events('intake')
        self.assertEqual(1, len(events))
        self.assertEqual('Lever', events[0]['fact']['ats_source'].title())

    def test_crash_after_frozen_watermark_merge_restarts_as_one_catchup_event(self):
        original_finish = self.local.finish_external_company_event_bootstrap
        with patch.object(self.local, 'finish_external_company_event_bootstrap',
                          side_effect=RuntimeError('simulated crash after import')):
            with self.assertRaisesRegex(RuntimeError, 'simulated crash'):
                self.sync.pull()
        self.assertIsNotNone(self.local.get_meta('company_event_external_bootstrap_pending'))
        self.assertIsNone(self.local.get_meta('company_event_external_baseline'))
        self.edit_company(**{'Official Careers URL': 'https://example.com/restarted'})
        with patch.object(self.local, 'finish_external_company_event_bootstrap', original_finish):
            result = self.sync.pull()
        self.assertEqual({'bootstrapped': True, 'seeded': 1}, result['company_event_baseline'])
        events = self.local.pending_company_events('intake')
        self.assertEqual(1, len(events))
        self.assertEqual('https://example.com/restarted', events[0]['fact']['official_careers_url'])

    def test_bootstrap_reordered_snapshot_does_not_enqueue_historical_companies(self):
        self.remote.commit([{'tab': 'Companies', 'identity': {'Company ID': 'C-2'},
                             'append_if_missing': True,
                             'values': {'Company': 'Beta', 'Company ID': 'C-2',
                                        'Company Status': 'Active',
                                        'Official Careers URL': 'https://example.com/beta',
                                        'ATS / Source': 'fixture'}}])
        self.local.import_rows('Companies', enumerate(self.remote.read('Companies'), 2))
        original = self.remote.read
        def reversed_companies(tab):
            rows = original(tab)
            return list(reversed(rows)) if tab == 'Companies' else rows
        with patch.object(self.remote, 'read', side_effect=reversed_companies):
            self.sync.pull()
        self.assertEqual([], self.local.pending_company_events('intake'))
        # Repeated/reordered reads remain a no-op; only a later source change
        # may create the newest per-company outbox fact.
        with patch.object(self.remote, 'read', side_effect=reversed_companies):
            self.sync.pull()
        self.assertEqual([], self.local.pending_company_events('intake'))

    def test_later_eligible_addition_and_withdrawal_are_exactly_once_events(self):
        self.sync.pull()
        self.remote.commit([{'tab': 'Companies', 'identity': {'Company ID': 'C-2'},
                             'append_if_missing': True,
                             'values': {'Company': 'Beta', 'Company ID': 'C-2',
                                        'Company Status': 'Active',
                                        'Official Careers URL': 'https://example.com/beta',
                                        'ATS / Source': 'fixture'}}])
        added = self.sync.pull()['company_event_reconciliation']['company_events']
        self.assertEqual(1, len(added))
        self.assertEqual(('C-2', 'company.eligible', 1),
                         (added[0]['company_id'], added[0]['kind'], added[0]['revision']))
        self.assertEqual([], self.sync.pull()['company_event_reconciliation']['company_events'])
        self.edit_company(**{'Official Careers URL': ''})
        withdrawn = self.sync.pull()['company_event_reconciliation']['company_events']
        self.assertEqual(1, len(withdrawn))
        self.assertEqual(('C-1', 'company.withdrawn'),
                         (withdrawn[0]['company_id'], withdrawn[0]['kind']))

    def test_idless_eligible_historical_row_holds_before_merge_then_seeds_when_fixed(self):
        remote = MemoryRepository({'Companies': [{
            'Company': 'Legacy No ID', 'Company ID': '', 'Company Status': 'Active',
            'Official Careers URL': 'https://example.com/legacy', 'ATS / Source': 'fixture'}]})
        remote.spreadsheet_id = 'fixture-idless'
        local = SQLiteRepository(Path(self.temp.name) / 'idless.sqlite3', 'fixture-idless', initialize=True)
        self.addCleanup(local.close)
        for tab in SCHEMAS:
            local.import_rows(tab, enumerate(remote.read(tab), 2))
        with local.transaction():
            local.set_meta('ready', 'yes')
        sync = SheetsSynchronizer(local, remote)
        with self.assertRaisesRegex(Exception, 'stable Company ID'):
            sync.pull()
        self.assertIsNone(local.get_meta('company_event_external_baseline'))
        self.assertIsNone(local.get_meta('company_event_external_bootstrap_pending'))
        self.assertEqual('', local.read('Companies')[0]['Company ID'])
        remote.commit([{'tab': 'Companies', 'identity': {'Company': 'Legacy No ID'},
                        'values': {'Company ID': 'C-LEGACY'}}])
        original_finish = local.finish_external_company_event_bootstrap
        with patch.object(local, 'finish_external_company_event_bootstrap',
                          side_effect=RuntimeError('crash after repaired merge')):
            with self.assertRaisesRegex(RuntimeError, 'crash after repaired merge'):
                sync.pull()
        self.assertIsNotNone(local.get_meta('company_event_external_bootstrap_pending'))
        self.assertIsNone(local.get_meta('company_event_external_baseline'))
        # A source change between the repaired merge and restart is catch-up
        # work, while the original repaired historical fact remains history.
        remote.commit([{'tab': 'Companies', 'identity': {'Company ID': 'C-LEGACY'},
                        'values': {'ATS / Source': 'Greenhouse'}}])
        with patch.object(local, 'finish_external_company_event_bootstrap', original_finish):
            first = sync.pull()
        self.assertEqual({'bootstrapped': True, 'seeded': 1}, first['company_event_baseline'])
        catchup = local.pending_company_events('intake')
        self.assertEqual(1, len(catchup))
        self.assertEqual('Greenhouse', catchup[0]['fact']['ats_source'].title())
        assigned = local.read('Companies')[0]['Company ID']
        self.assertEqual('C-LEGACY', assigned)
        # The next actual external source change is the one and only event.
        remote.commit([{'tab': 'Companies', 'identity': {'Company': 'Legacy No ID'},
                        'values': {'ATS / Source': 'Lever'}}])
        later = sync.pull()['company_event_reconciliation']['company_events']
        self.assertEqual(1, len(later))
        self.assertEqual((assigned, 'company.eligible'),
                         (later[0]['company_id'], later[0]['kind']))

    def test_idless_paused_historical_row_is_seeded_without_a_withdrawal_event(self):
        remote = MemoryRepository({'Companies': [{
            'Company': 'Paused Legacy', 'Company ID': '', 'Company Status': 'Paused',
            'Official Careers URL': 'https://example.com/paused', 'ATS / Source': 'fixture'}]})
        remote.spreadsheet_id = 'fixture-paused-idless'
        local = SQLiteRepository(Path(self.temp.name) / 'paused-idless.sqlite3',
                                 'fixture-paused-idless', initialize=True)
        self.addCleanup(local.close)
        for tab in SCHEMAS:
            local.import_rows(tab, enumerate(remote.read(tab), 2))
        with local.transaction():
            local.set_meta('ready', 'yes')
        sync = SheetsSynchronizer(local, remote)

        first = sync.pull()
        self.assertEqual({'bootstrapped': True, 'seeded': 1}, first['company_event_baseline'])
        self.assertEqual([], local.pending_company_events('intake'))
        assigned = local.read('Companies')[0]['Company ID']
        self.assertTrue(assigned.startswith('COMP-'))

        # A later eligibility change is real work.  The initial seed must not
        # weaken the existing withdrawal/transition semantics.
        remote.commit([{'tab': 'Companies', 'identity': {'Company': 'Paused Legacy'},
                        'values': {'Company Status': 'Active'}}])
        later = sync.pull()['company_event_reconciliation']['company_events']
        self.assertEqual(1, len(later))
        self.assertEqual((assigned, 'company.eligible'),
                         (later[0]['company_id'], later[0]['kind']))

    def test_idless_removed_or_incomplete_historical_rows_never_enqueue_initial_work(self):
        cases = (
            ('Removed Legacy', 'Removed', 'https://example.com/removed'),
            ('Incomplete Legacy', 'Active', ''),
        )
        for number, (name, status, careers_url) in enumerate(cases):
            with self.subTest(name=name):
                remote = MemoryRepository({'Companies': [{
                    'Company': name, 'Company ID': '', 'Company Status': status,
                    'Official Careers URL': careers_url, 'ATS / Source': 'fixture'}]})
                remote.spreadsheet_id = f'fixture-idless-{number}'
                local = SQLiteRepository(Path(self.temp.name) / f'idless-{number}.sqlite3',
                                         remote.spreadsheet_id, initialize=True)
                self.addCleanup(local.close)
                for tab in SCHEMAS:
                    local.import_rows(tab, enumerate(remote.read(tab), 2))
                with local.transaction():
                    local.set_meta('ready', 'yes')
                result = SheetsSynchronizer(local, remote).pull()
                self.assertEqual({'bootstrapped': True, 'seeded': 1},
                                 result['company_event_baseline'])
                self.assertEqual([], local.pending_company_events('intake'))
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
