"""Recover manual Sheet edits without weakening commit-time guards."""
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from job_search_helper.repository import MemoryRepository, SCHEMAS, ReviewFieldsChangedError
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.run_sync import RunSheetsSync
from test_sqlite_migration import job, operation
from test_run_scoped_sync import FakeSync


class StaleSheetChoicesTests(unittest.TestCase):
    def setUp(self):
        capture=redirect_stdout(StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__,None,None,None)

    def session(self, sync):
        @contextmanager
        def factory():
            yield sync
        return RunSheetsSync(factory, log=lambda message: None)

    def test_prewrite_conflict_refreshes_controls_then_retries(self):
        sync = FakeSync(pending=1)
        original = sync.publish_batch
        def publish():
            if sync.events.count('pull') < 2:
                raise ReviewFieldsChangedError('Job History', {'Job Key': 'job-1'})
            return original()
        with patch.object(sync, 'publish_batch', side_effect=publish):
            with self.session(sync):
                self.assertEqual(sync.local.pending, 0)
        # Startup and conflict replan each pull once; final reconciliation
        # always reads Company controls once more before the run terminates.
        self.assertEqual(sync.events.count('pull'), 3)

    def test_repeated_startup_conflicts_defer_delivery_then_final_pulls_and_drains(self):
        sync = FakeSync(pending=1)
        sync.publish_error = ReviewFieldsChangedError('Job History', {'Job Key': 'job-1'})
        session = self.session(sync)
        with session:
            self.assertIsNone(session.startup_error)
            self.assertEqual(sync.events.count('pull'), 2)
            self.assertEqual(sync.events.count('publish'), 2)
            self.assertEqual(sync.local.pending, 1)
            self.assertEqual(session.report['startup']['stop_reason'], 'review_fields_changed')
            self.assertIn('ReviewFieldsChangedError', sync.local.meta['last_error'])
            sync.publish_error = None
        self.assertEqual(sync.events.count('pull'), 3)
        self.assertEqual(sync.local.pending, 0)
        self.assertEqual(sync.local.meta['last_error'], '')
        self.assertFalse(session.thread.is_alive())

    def test_continuing_conflicts_still_report_incomplete_final_delivery(self):
        sync = FakeSync(pending=1)
        sync.publish_error = ReviewFieldsChangedError('Job History', {'Job Key': 'job-1'})
        session = self.session(sync)
        with self.assertRaisesRegex(RuntimeError, 'Final Sheets sync incomplete'):
            with session:
                self.assertEqual(sync.events.count('publish'), 2)
        self.assertIsNone(session.startup_error)
        self.assertIsInstance(session.final_error, ReviewFieldsChangedError)
        self.assertEqual(sync.local.pending, 1)
        self.assertFalse(session.thread.is_alive())

    def test_partial_startup_progress_survives_conflict_and_background_retry_repulls(self):
        sync = FakeSync(pending=3)
        published = sync.publish_batch
        calls = []
        def publish():
            calls.append(True)
            if len(calls) in (2, 3):
                raise ReviewFieldsChangedError('Job History', {'Job Key': 'job-1'})
            return published()
        @contextmanager
        def factory():
            yield sync
        logs = []
        recovered = threading.Event()
        session = RunSheetsSync(factory, interval=.2, log=logs.append)
        original = session._publish
        def track(source, phase, *, final=False):
            result = original(source, phase, final=final)
            if phase == 'periodic':
                recovered.set()
            return result
        with patch.object(sync, 'publish_batch', side_effect=publish), \
             patch.object(session, '_publish', side_effect=track):
            with session:
                self.assertEqual(session.report['startup']['published_rows'], 1)
                self.assertEqual(session.report['startup']['batches'], 1)
                self.assertEqual(session.report['startup']['pending_cells'], 2)
                self.assertTrue(recovered.wait(2), logs)
                self.assertEqual(sync.events.count('pull'), 3)
                self.assertEqual(sync.local.pending, 0)
        self.assertEqual(session.totals['sheets_published_row_updates'], 3)
        self.assertTrue(any('Sheets startup deferred' in message for message in logs))

    def test_uncertain_write_does_not_trigger_automatic_replanning(self):
        sync = FakeSync(pending=1)
        sync.publish_error = OSError('Response lost after submitting write')
        with self.assertRaisesRegex(RuntimeError, 'startup sync failed'):
            with self.session(sync):
                pass
        self.assertEqual(sync.events.count('pull'), 1)
        self.assertEqual(sync.local.pending, 1)

    def test_real_guard_imports_manual_no_and_notes_before_publishing_source_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'jobs.sqlite3'
            remote = MemoryRepository({'Job History': [job()]})
            remote.spreadsheet_id = 'fixture'
            local = SQLiteRepository(path, 'fixture', initialize=True)
            for tab in SCHEMAS:
                local.import_rows(tab, enumerate(remote.read(tab), 2))
            with local.transaction():
                local.set_meta('ready', 'yes')
            local.commit([operation(**{'Last Checked': '2026-11-02'})])
            local.close()
            @contextmanager
            def factory():
                connection = SQLiteRepository(path, 'fixture')
                try:
                    yield SheetsSynchronizer(connection, remote)
                finally:
                    connection.close()
            original = remote.commit
            changed = []
            def edit_before_commit(ops):
                if not changed:
                    original([operation(**{'Added to Opportunities?': 'No', 'Review Notes': 'My choice'})])
                    changed.append(True)
                return original(ops)
            with patch.object(remote, 'commit', side_effect=edit_before_commit):
                with RunSheetsSync(factory, log=lambda message: None):
                    row = remote.read('Job History')[0]
                    self.assertEqual(row['Added to Opportunities?'], 'No')
                    self.assertEqual(row['Review Notes'], 'My choice')
                    self.assertEqual(row['Last Checked'], '2026-11-02')
                    self.assertEqual(row['Review Status'], 'Reviewed')
            self.assertEqual(len(remote.read('Job History')), 1)

    def test_two_real_prewrite_conflicts_allow_scraping_and_preserve_latest_choice(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'jobs.sqlite3'
            remote = MemoryRepository({'Job History': [job()]})
            remote.spreadsheet_id = 'fixture'
            local = SQLiteRepository(path, 'fixture', initialize=True)
            for tab in SCHEMAS:
                local.import_rows(tab, enumerate(remote.read(tab), 2))
            with local.transaction():
                local.set_meta('ready', 'yes')
            local.commit([operation(**{'Last Checked': '2026-11-05'})])
            local.close()
            @contextmanager
            def factory():
                connection = SQLiteRepository(path, 'fixture')
                try:
                    yield SheetsSynchronizer(connection, remote)
                finally:
                    connection.close()
            original = remote.commit
            choices = iter(('No', 'Yes'))
            def edit_before_commit(ops):
                choice = next(choices, None)
                if choice:
                    original([operation(**{'Added to Opportunities?': choice,
                                           'Review Notes': 'Latest choice: ' + choice})])
                return original(ops)
            with patch.object(remote, 'commit', side_effect=edit_before_commit):
                session = RunSheetsSync(factory, log=lambda message: None)
                with session:
                    self.assertIsNone(session.startup_error)
                    self.assertEqual(session.report['startup']['stop_reason'], 'review_fields_changed')
                    row = remote.read('Job History')[0]
                    self.assertEqual(row['Last Checked'], '')
                    self.assertEqual(row['Added to Opportunities?'], 'Yes')
                    # The scraper body can now run while delivery is deferred.
                row = remote.read('Job History')[0]
                self.assertEqual(row['Last Checked'], '2026-11-05')
                self.assertEqual(row['Added to Opportunities?'], 'Yes')
                self.assertEqual(row['Review Notes'], 'Latest choice: Yes')
                self.assertEqual(row['Decision'], 'Accept')
                self.assertEqual(session.report['final']['pending_cells'], 0)

    def test_cached_location_rescreen_preserves_first_seen(self):
        from job_search_helper.engine import Engine, State
        from job_search_helper.inbox import InventoryInbox
        from test_fetch_pool import company, inventory
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local = SQLiteRepository(root / 'jobs.sqlite3', 'fixture', initialize=True)
            self.addCleanup(local.close)
            initial = MemoryRepository({'Companies': [company(0)]})
            for tab in SCHEMAS:
                local.import_rows(tab, enumerate(initial.read(tab), 2))
            with local.transaction():local.set_meta('ready', 'yes')
            state=State(root/'state.db'); self.addCleanup(state.close)
            inbox=InventoryInbox(root/'inbox.db','fixture');self.addCleanup(inbox.close)
            result=inventory('C-0', company(0)['Company'], company(0)['Official Careers URL'])
            engine=Engine(local,state,inbox=inbox,fetcher=lambda *args:result,error_log_path=root/'errors.jsonl')
            engine._stage_posting({'id':'OLD'},company(0),result.jobs[0])
            row=local.read('Job History')[0]
            local.commit([{'tab':'Job History','identity':{'Job Key':row['Job Key']},'values':{'First Seen':'2026-01-01'}}])
            result.jobs[0]['location']='Bucharest, Romania'
            engine.resume_local(engine.start_cycle(),fetch_workers=1)
            row=local.read('Job History')[0]
            self.assertEqual(row['Added to Opportunities?'],'No')
            self.assertEqual(row['First Seen'],'2026-01-01')

    def test_manual_choice_matching_rejected_plan_is_still_protected(self):
        with tempfile.TemporaryDirectory() as temporary:
            local=SQLiteRepository(Path(temporary)/'jobs.sqlite3','fixture',initialize=True)
            self.addCleanup(local.close)
            remote=MemoryRepository({'Job History':[job()]});remote.spreadsheet_id='fixture'
            for tab in SCHEMAS:
                local.import_rows(tab,enumerate(remote.read(tab),2))
            with local.transaction():local.set_meta('ready','yes')
            local.commit([operation(**{'Added to Opportunities?':'No','Last Checked':'today'})])
            remote.commit([operation(**{'Added to Opportunities?':'No','Review Notes':'User selected No'})])
            sync=SheetsSynchronizer(local,remote)
            with self.assertRaises(ReviewFieldsChangedError):sync.publish_batch()
            self.assertEqual(local.db.execute('SELECT count(*) FROM delivery_attempts').fetchone()[0],0)
            sync.pull();sync.publish_batch()
            rid,row=local.matches('Job History',{'Job Key':'job-1'})[0]
            choice=local.db.execute("SELECT value FROM manual_choices WHERE tab='Job History' AND row_id=?",(rid,)).fetchone()
            self.assertEqual(choice[0],'No')
            self.assertEqual(row['Decision'],'Reject')
            self.assertEqual(remote.read('Job History')[0]['Review Notes'],'User selected No')

    def test_sheet_yes_overrides_queued_automatic_no(self):
        with tempfile.TemporaryDirectory() as temporary:
            local=SQLiteRepository(Path(temporary)/'jobs.sqlite3','fixture',initialize=True)
            self.addCleanup(local.close)
            remote=MemoryRepository({'Job History':[job()]});remote.spreadsheet_id='fixture'
            for tab in SCHEMAS:
                local.import_rows(tab,enumerate(remote.read(tab),2))
            with local.transaction():local.set_meta('ready','yes')
            local.commit([operation(**{'Added to Opportunities?':'No','Review Status':'Reviewed','Decision':'Reject'})])
            remote.commit([operation(**{'Added to Opportunities?':'Yes'})])
            sync=SheetsSynchronizer(local,remote)
            with self.assertRaises(ReviewFieldsChangedError):sync.publish_batch()
            sync.pull();sync.publish_batch()
            self.assertEqual(local.read('Job History')[0]['Added to Opportunities?'],'Yes')
            self.assertEqual(local.read('Job History')[0]['Decision'],'Accept')
            self.assertEqual(remote.read('Job History')[0]['Added to Opportunities?'],'Yes')
