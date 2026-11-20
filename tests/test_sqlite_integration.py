"""Offline integration coverage: real repository adapter, scraper, and bootstrap."""
from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper import cli
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import GoogleRepository, RepositoryError
from job_search_helper.sqlite_bootstrap import bootstrap
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sync_cli import cycle
from sheets_fixture import RangeSheets
from test_fetch_pool import company, inventory
from test_sqlite_migration import job


class StorageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / 'jobs.sqlite3'
        self.service = RangeSheets({'Companies': [company(i) for i in range(3)]})
        self.remote = GoogleRepository(self.service, 'fixture', min_request_interval=0)

    def imported(self):
        bootstrap(self.remote, self.path, shadow=False, chunk_size=2)
        local = SQLiteRepository(self.path, 'fixture')
        self.addCleanup(local.close)
        return local

    def test_cell_aware_import_retains_link_target_numeric_date_formula_and_dropdown(self):
        self.service = RangeSheets({'Companies': [company(0)], 'Job History': [job()],
            'Opportunities': [{'Company': 'Acme', 'Job URL': 'https://jobs.example.com/job-1',
                               'Application Status': 'Applied', 'Date Applied': 46300.25}]})
        self.service.set_cell('Opportunities', 1, 'Date Applied', cell={'userEnteredValue': {'numberValue': 46300.25}, 'effectiveValue': {'numberValue': 46300.25}})
        self.service.set_cell('Opportunities', 1, 'Job URL', cell={
            'userEnteredValue': {'formulaValue': '=HYPERLINK("https://jobs.example.com/job-1","Posting")'},
            'effectiveValue': {'stringValue': 'Posting'}, 'hyperlink': 'https://jobs.example.com/job-1'})
        self.service.set_cell('Job History', 1, 'Review Notes', cell={
            'userEnteredValue': {'formulaValue': '=1+1'}, 'effectiveValue': {'numberValue': 2}})
        self.remote = GoogleRepository(self.service, 'fixture', min_request_interval=0)
        local = self.imported()
        row = local.read('Opportunities')[0]
        self.assertEqual(row['Job URL'], 'https://jobs.example.com/job-1')
        self.assertEqual(row['Date Applied'], 46300.25)
        self.assertEqual(row['Application Status'], 'Applied')
        with self.assertRaises(RepositoryError):
            local.commit([{'tab': 'Job History', 'identity': {'Job Key': 'job-1'}, 'values': {'Review Notes': 'overwrite'}}])
        self.assertEqual(len(self.service.batches), 0)

    def test_duplicate_identity_across_import_chunks_is_rejected(self):
        self.service = RangeSheets({'Companies': [company(0)], 'Job History': [job(), job()]})
        self.remote = GoogleRepository(self.service, 'fixture', min_request_interval=0)
        with self.assertRaises(RepositoryError):
            bootstrap(self.remote, self.path, shadow=False, chunk_size=1)
        with self.assertRaises(RepositoryError): SQLiteRepository(self.path, 'fixture')
        self.assertEqual(len(self.service.batches), 0)

    def test_separate_same_url_applications_survive_import_reordering_and_sync(self):
        rows = [
            {'Company': 'Acme', 'Job URL': 'https://jobs.example.com/job-1',
             'Job Title': 'Field Engineer', 'Location': 'San Diego, CA',
             'Work Arrangement': 'On-site', 'Application Status': 'Applied',
             'Date Applied': '2026-09-11', 'Notes': 'First application'},
            {'Company': 'Acme', 'Job URL': 'https://jobs.example.com/job-1',
             'Job Title': 'Field Engineer', 'Location': 'San Diego, California',
             'Work Arrangement': 'Onsite', 'Application Status': 'Not Interested',
             'Notes': 'Separate decision'},
        ]
        self.service = RangeSheets({'Companies': [company(0)],
            'Job History': [job(**{'Added to Opportunities?': 'Yes'})],
            'Opportunities': rows})
        self.remote = GoogleRepository(self.service, 'fixture', min_request_interval=0)
        local = self.imported()
        self.assertEqual(len(local.read('Opportunities')), 2)
        from job_search_helper.sqlite_repository import identity_for
        selected = local.read('Opportunities')[1]
        local.commit([{'tab': 'Opportunities', 'identity': identity_for('Opportunities', selected),
                       'values': {'Last Checked': 'today'}}])
        # Physical row order must not choose which user's application is updated.
        self.service = RangeSheets({'Companies': [company(0)],
            'Job History': [job(**{'Added to Opportunities?': 'Yes'})],
            'Opportunities': list(reversed(rows))})
        self.remote = GoogleRepository(self.service, 'fixture', min_request_interval=0)
        cycle(SheetsSynchronizer(local, self.remote))
        actual = self.remote.read('Opportunities')
        self.assertEqual(actual[0]['Last Checked'], 'today')
        self.assertEqual(actual[0]['Application Status'], 'Not Interested')
        self.assertEqual(actual[1]['Last Checked'], '')
        self.assertEqual(actual[1]['Application Status'], 'Applied')
        self.assertEqual(actual[1]['Date Applied'], '2026-09-11')
        self.assertEqual([r['Notes'] for r in actual], ['Separate decision', 'First application'])
        self.assertEqual(local.status()['pending_cells'], 0)

    def test_identical_opportunity_details_still_stop_instead_of_merging(self):
        row = {'Company': 'Acme', 'Job URL': 'https://jobs.example.com/job-1',
               'Job Title': 'Engineer', 'Location': 'Ohio'}
        self.service = RangeSheets({'Opportunities': [row, dict(row, **{'Application Status': 'Applied'})]})
        self.remote = GoogleRepository(self.service, 'fixture', min_request_interval=0)
        with self.assertRaises(RepositoryError):
            bootstrap(self.remote, self.path, shadow=True, chunk_size=1)
        self.assertEqual(len(self.service.batches), 0)

    def test_permanent_ids_keep_identical_applications_separate_during_source_refresh(self):
        from job_search_helper.repository import SCHEMAS
        import copy
        schemas = copy.deepcopy(SCHEMAS)
        schemas['Opportunities'].append('Opportunity ID')
        shared = {'Company': 'Acme', 'Job URL': 'https://jobs.example.com/job-1',
                  'Job Title': 'Field Engineer', 'Location': 'Ohio'}
        rows = [dict(shared, **{'Opportunity ID': 'OPP-a', 'Application Status': 'Applied',
                               'Date Applied': '2026-09-11', 'Notes': 'First'}),
                dict(shared, **{'Opportunity ID': 'OPP-b', 'Application Status': 'Not Interested',
                               'Notes': 'Second'})]
        self.service = RangeSheets({'Companies': [company(0)],
            'Job History': [job(**{'Added to Opportunities?': 'Yes'})],
            'Opportunities': rows}, schemas=schemas)
        self.remote = GoogleRepository(self.service, 'fixture', schemas=schemas, min_request_interval=0)
        local = self.imported()
        engine = Engine(local, None)
        self.assertIsNotNone(engine._opportunity({'url': shared['Job URL']}, {'Company': 'Acme'}))
        local.commit([{'tab': 'Opportunities',
            'identity': {'Company': 'Acme', 'Job URL': shared['Job URL']},
            'values': {'Location': 'Ohio, USA', 'Last Checked': 'today'},
            'append_notes': {'Notes': 'Source verified'}}])
        cycle(SheetsSynchronizer(local, self.remote))
        actual = self.remote.read('Opportunities')
        self.assertEqual([r['Opportunity ID'] for r in actual], ['OPP-a', 'OPP-b'])
        self.assertEqual([r['Application Status'] for r in actual], ['Applied', 'Not Interested'])
        self.assertEqual([r['Location'] for r in actual], ['Ohio, USA', 'Ohio, USA'])
        self.assertEqual(actual[0]['Date Applied'], '2026-09-11')
        self.assertTrue(actual[0]['Notes'].startswith('First'))
        self.assertTrue(actual[1]['Notes'].startswith('Second'))
        self.assertEqual(local.status()['pending_cells'], 0)
        self.assertEqual(len(actual), 2)
        from job_search_helper.batching import PlanningRepository
        planner = PlanningRepository(local)
        self.assertIsNotNone(Engine(planner, None)._opportunity(
            {'url': shared['Job URL']}, {'Company': 'Acme'}))
        planner.commit([{'tab': 'Opportunities',
            'identity': {'Company': 'Acme', 'Job URL': shared['Job URL']},
            'values': {'Last Checked': 'tomorrow'}}])
        self.assertEqual(len(planner.operations), 2)
        local.commit(planner.operations)
        planner.accept_commit()
        self.assertEqual([r['Last Checked'] for r in planner.read('Opportunities')], ['tomorrow', 'tomorrow'])
        planner.commit([{'tab': 'Opportunities',
            'identity': {'Company': 'Acme', 'Job URL': 'https://jobs.example.com/job-2'},
            'append_if_missing': True, 'values': {'Job Title': 'New Engineer'}}])
        local.commit(planner.operations)
        planner.accept_commit()
        self.assertEqual(len(planner.read('Opportunities')), 3)
        self.assertEqual(len({r['Opportunity ID'] for r in planner.read('Opportunities')}), 3)

    def test_shadow_import_cannot_be_opened_for_operational_use(self):
        result = bootstrap(self.remote, self.path, shadow=True)
        self.assertFalse(result['ready'])
        with self.assertRaises(RepositoryError): SQLiteRepository(self.path, 'fixture')
        self.assertEqual(len(self.service.batches), 0)

    def test_existing_import_destination_is_never_replaced(self):
        self.path.write_text('Do not replace me')
        with self.assertRaises(RepositoryError): bootstrap(self.remote, self.path)
        self.assertEqual(self.path.read_text(), 'Do not replace me')

    def test_sqlite_factory_does_not_authorize_or_construct_google_client(self):
        self.imported()
        with patch.dict(os.environ, {'JOB_STORAGE_BACKEND': 'sqlite', 'JOB_DB_FILE': str(self.path), 'SPREADSHEET_ID': 'fixture'}), \
             patch('job_search_helper.cli.authorize', side_effect=AssertionError('Google auth attempted')):
            repo = cli.get_repository(write=True, interactive=True, renew_both=True)
            try:
                self.assertTrue(repo.is_local)
                self.assertEqual(len(repo.read('Companies')), 3)
            finally: repo.close()

    def test_invalid_backend_does_not_silently_fall_back(self):
        with patch.dict(os.environ, {'JOB_STORAGE_BACKEND': 'sqllite'}):
            with self.assertRaises(ValueError): cli.get_repository()

    def test_successful_idle_sync_updates_health_and_clears_old_error(self):
        local = self.imported()
        with local.transaction(): local.set_meta('last_error', 'Old connection error')
        result = cycle(SheetsSynchronizer(local, self.remote))
        self.assertEqual(result['published_rows'], 0)
        self.assertTrue(result['last_sync'])
        self.assertEqual(result['last_error'], '')

    def test_local_review_and_scraper_locks_are_separate_from_google_writer(self):
        with patch.dict(os.environ, {'JOB_STORAGE_BACKEND': 'sqlite'}):
            self.assertEqual(cli.scraper_lock_name(), 'scraper.lock')
            self.assertEqual(cli.review_lock_name(), 'review-writeback.lock')
            with cli.writer_lock(self.root / 'writer.lock'):
                with cli.writer_lock(self.root / cli.scraper_lock_name()):
                    with cli.writer_lock(self.root / cli.review_lock_name()): pass
        with patch.dict(os.environ, {'JOB_STORAGE_BACKEND': 'sheets'}):
            self.assertEqual(cli.scraper_lock_name(), 'writer.lock')
            self.assertEqual(cli.review_lock_name(), 'writer.lock')

    def test_complete_local_scrape_uses_no_google_until_sync(self):
        local = self.imported()
        state = State(self.root / 'state.db'); self.addCleanup(state.close)
        inbox = InventoryInbox(self.root / 'inventories.sqlite3', 'fixture'); self.addCleanup(inbox.close)
        calls = []
        def fetch(source, url, cid, name):
            calls.append(cid)
            return inventory(cid, name, url)
        engine = Engine(local, state, fetcher=fetch, inbox=inbox, batch_size=100,
                        error_log_path=self.root / 'errors.jsonl')
        with redirect_stdout(StringIO()), patch.object(self.remote, 'commit', side_effect=AssertionError('Google write during scrape')):
            cid = engine.start_cycle()
            engine.resume_local(cid, fetch_workers=2, assignment_window=2)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(local.read('Job History')), 3)
        self.assertEqual(len(self.remote.read('Job History')), 0)
        self.assertEqual(state.cycle(cid)['status'], 'Complete')
        self.assertGreater(local.status()['pending_cells'], 0)
        sync = SheetsSynchronizer(local, self.remote)
        cycle(sync, max_batches=20)
        self.assertEqual(len(self.remote.read('Job History')), 3)
        self.assertEqual(local.status()['pending_cells'], 0)
        self.assertEqual(local.status()['conflicts'], 0)

    def test_saved_inventory_resume_does_not_refetch_after_backend_switch(self):
        local = self.imported()
        state = State(self.root / 'state.db'); self.addCleanup(state.close)
        inbox = InventoryInbox(self.root / 'inventories.sqlite3', 'fixture'); self.addCleanup(inbox.close)
        engine = Engine(local, state, fetcher=lambda source, url, cid, name: inventory(cid, name, url),
                        inbox=inbox, error_log_path=self.root / 'errors.jsonl')
        with redirect_stdout(StringIO()):
            cid = engine.start_cycle()
            engine.resume_local(cid, fetch_workers=2, defer_sync=True)
            engine.fetcher = lambda *args: self.fail('Saved inventory was refetched')
            engine.resume_local(cid, sync_only=True)
        self.assertEqual(len(local.read('Job History')), 3)
        self.assertEqual(inbox.cycles(), [])
        self.assertEqual(state.cycle(cid)['status'], 'Complete')

    def test_real_google_adapter_preserves_manual_status_after_local_update(self):
        self.service = RangeSheets({'Companies': [company(0)], 'Job History': [job()],
            'Opportunities': [{'Company': 'Acme', 'Job URL': 'https://jobs.example.com/job-1',
                               'Application Status': 'Applied', 'Date Applied': 46300.25}]})
        self.service.set_cell('Opportunities', 1, 'Date Applied', cell={'userEnteredValue': {'numberValue': 46300.25}, 'effectiveValue': {'numberValue': 46300.25}})
        self.remote = GoogleRepository(self.service, 'fixture', min_request_interval=0)
        local = self.imported()
        local.commit([{'tab': 'Opportunities', 'identity': {'Company': 'Acme', 'Job URL': 'https://jobs.example.com/job-1'},
                       'values': {'Last Checked': 'today'}}])
        self.service.set_cell('Opportunities', 1, 'Application Status', 'Interviewing')
        cycle(SheetsSynchronizer(local, self.remote))
        self.assertEqual(local.read('Opportunities')[0]['Application Status'], 'Interviewing')
        self.assertEqual(self.remote.read('Opportunities')[0]['Application Status'], 'Interviewing')
        self.assertEqual(self.remote.read('Opportunities')[0]['Date Applied'], 46300.25)
        self.assertEqual(local.status()['pending_cells'], 0)


if __name__ == '__main__': unittest.main()
