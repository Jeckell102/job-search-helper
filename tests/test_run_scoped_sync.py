"""Run-owned Sheets lifecycle; fixtures only, no Google calls or live state."""
from contextlib import contextmanager, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from job_search_helper.run_sync import RunSheetsSync, publish_pending, run_scoped_sync, sync_connection
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.repository import MemoryRepository, SCHEMAS
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper import cli, runner


class FakeLocal:
    def __init__(self):
        self.pending = 0
        self.db = self
        self.meta = {}

    def execute(self, query):
        return self

    def fetchone(self):
        return (self.pending,)

    @contextmanager
    def transaction(self):
        yield

    def set_meta(self, key, value):
        self.meta[key] = value


class FakeSync:
    def __init__(self, pending=0):
        self.local = FakeLocal()
        self.local.pending = pending
        self.events = []
        self.published = threading.Event()
        self.pull_error = None
        self.publish_error = None
        self.zero_progress = False
        self.batch_size = 1

    def pull(self):
        self.events.append('pull')
        if self.pull_error:
            raise self.pull_error
        return {'changed': 0}

    def publish_batch(self):
        self.events.append('publish')
        if self.publish_error:
            raise self.publish_error
        count = 0 if self.zero_progress else min(self.batch_size, self.local.pending)
        self.local.pending -= count
        self.published.set()
        return {'published_rows':count}


class RunScopedSyncTests(unittest.TestCase):
    def session(self, sync, **kwargs):
        @contextmanager
        def factory():
            sync.events.append('open')
            try:
                yield sync
            finally:
                sync.events.append('close')
        kwargs.setdefault('log', lambda message:None)
        return RunSheetsSync(factory, **kwargs)

    def test_pending_backlog_restarts_immediately_without_60_second_pause(self):
        sync = FakeSync(pending=3)
        session = self.session(sync, interval=60)
        drained = threading.Event()
        def bounded_pass(source, phase, *, final=False):
            result = source.publish_batch()
            session.report[phase] = {'published_rows': result['published_rows'],
                                     'pending_cells': source.local.pending}
            if not source.local.pending:
                drained.set()
        with patch.object(session, '_publish', side_effect=bounded_pass):
            with session:
                self.assertTrue(drained.wait(2), 'Backlog slept for the configured interval')
                self.assertEqual(sync.events.count('pull'), 1)
        self.assertEqual(sync.local.pending, 0)

    def test_idle_poll_publishes_new_changes_before_the_60_second_interval(self):
        sync = FakeSync()
        session = self.session(sync, interval=60)
        with session:
            sync.local.pending = 1
            self.assertTrue(sync.published.wait(4), 'New changes waited for the 60-second interval')
            self.assertEqual(sync.events.count('pull'), 1)
        self.assertEqual(sync.local.pending, 0)

    def test_startup_pull_and_drain_precede_body_then_final_drain_and_stop(self):
        sync = FakeSync(pending=2)
        session = self.session(sync)
        with session:
            self.assertEqual(sync.events, ['open','pull','publish','publish'])
            sync.events.append('scrape')
            sync.local.pending = 3
        self.assertEqual(sync.events, ['open','pull','publish','publish','scrape',
                                      'publish','publish','publish','close'])
        self.assertFalse(session.thread.is_alive())
        self.assertEqual(sync.local.pending,0)

    def test_periodic_ticks_publish_only_without_repull(self):
        sync = FakeSync()
        session = self.session(sync,interval=.02)
        with session:
            sync.local.pending = 1
            self.assertTrue(sync.published.wait(2))
        self.assertEqual(sync.events.count('pull'),1)
        self.assertEqual(sync.events.count('publish'),1)
        self.assertFalse(session.thread.is_alive())

    def test_run_totals_include_all_periodic_updates_and_final_drain(self):
        sync = FakeSync(pending=2)
        session = self.session(sync)
        session._publish(sync, 'startup')
        for count in (3, 4):
            sync.local.pending = count
            session._publish(sync, 'periodic')
        sync.local.pending = 1
        session._publish(sync, 'final', final=True)
        self.assertEqual(session.report['periodic']['published_rows'], 4)
        self.assertEqual(session.totals['sheets_published_row_updates'], 10)
        self.assertEqual(session.totals['sheets_publish_batches'], 10)
        self.assertEqual(session.totals['sheets_pending_cells'], 0)

    def test_totals_retain_acknowledged_batches_before_a_later_failure(self):
        sync = FakeSync(pending=2)
        session = self.session(sync)
        original = sync.publish_batch
        def publish():
            if sync.local.pending == 1:
                raise OSError('second batch failed')
            return original()
        with patch.object(sync, 'publish_batch', side_effect=publish), self.assertRaises(OSError):
            session._publish(sync, 'periodic')
        self.assertEqual(session.totals['sheets_published_row_updates'], 1)
        self.assertEqual(session.totals['sheets_pending_cells'], 1)

    def test_startup_budget_allows_scraping_with_1051_pending_then_final_drains(self):
        sync = FakeSync(pending=1551)
        sync.batch_size = 500
        now = [0.0]
        publish = sync.publish_batch

        def slow_batch():
            result = publish()
            now[0] += 61
            return result

        logs = []
        session = self.session(sync, log=logs.append)
        with patch('job_search_helper.run_sync.time.monotonic', side_effect=lambda:now[0]), \
             patch.object(sync, 'publish_batch', side_effect=slow_batch):
            with session:
                self.assertLessEqual(sync.local.pending, 1051)
                self.assertEqual(session.report['startup']['published_rows'], 500)
                self.assertEqual(session.report['startup']['stop_reason'], 'time_budget')
                self.assertIsNone(session.startup_error)
                self.assertTrue(any('starting scraping with the backlog saved locally' in m for m in logs))
                self.assertTrue(any('batch 1 complete' in m for m in logs))
            self.assertEqual(sync.local.pending, 0)
            self.assertEqual(session.report['final']['stop_reason'], 'drained')
            self.assertFalse(session.thread.is_alive())

    def test_startup_remainder_retries_on_periodic_tick_without_another_pull(self):
        sync = FakeSync(pending=2)
        now = [0.0]
        publish = sync.publish_batch
        allow_retry = threading.Event()
        calls = [0]

        def slow_first_batch():
            calls[0] += 1
            if calls[0] > 1:
                allow_retry.wait(2)
            result = publish()
            now[0] = 1.0
            return result

        session = self.session(sync, interval=.02)
        with patch('job_search_helper.run_sync.time.monotonic', side_effect=lambda:now[0]), \
             patch.object(sync, 'publish_batch', side_effect=slow_first_batch):
            with session:
                self.assertEqual(session.report['startup']['pending_cells'], 1)
                sync.published.clear()
                allow_retry.set()
                self.assertTrue(sync.published.wait(2))
            self.assertEqual(session.report['periodic']['pending_cells'], 0)
        self.assertEqual(sync.events.count('pull'), 1)
        self.assertFalse(session.thread.is_alive())

    def test_startup_held_work_stays_saved_and_does_not_prevent_scraping(self):
        sync = FakeSync(pending=2)
        sync.zero_progress = True
        session = self.session(sync)
        with session:
            self.assertEqual(sync.local.pending, 2)
            self.assertEqual(session.report['startup']['stop_reason'], 'no_progress')
            sync.zero_progress = False
        self.assertEqual(sync.local.pending, 0)

    def test_real_startup_publish_failure_still_blocks_without_losing_pending_work(self):
        sync = FakeSync(pending=2)
        sync.publish_error = OSError('offline')
        session = self.session(sync)
        with self.assertRaisesRegex(RuntimeError, 'startup sync failed'):
            with session:
                self.fail('A real delivery error is not budget exhaustion')
        self.assertEqual(sync.local.pending, 2)
        self.assertIn('offline', sync.local.meta['last_error'])
        self.assertFalse(session.thread.is_alive())

    def test_no_pending_work_makes_no_publish_requests(self):
        sync = FakeSync()
        with self.session(sync):
            pass
        self.assertEqual(sync.events,['open','pull','close'])

    def test_keyboard_interrupt_still_performs_final_drain(self):
        sync = FakeSync()
        session = self.session(sync)
        with self.assertRaises(KeyboardInterrupt):
            with session:
                sync.local.pending = 2
                raise KeyboardInterrupt()
        self.assertEqual(sync.local.pending,0)
        self.assertFalse(session.thread.is_alive())
        self.assertEqual(sync.events[-1],'close')

    def test_startup_failure_prevents_body_and_closes_worker(self):
        sync = FakeSync()
        sync.pull_error = OSError('offline')
        session = self.session(sync)
        with self.assertRaisesRegex(RuntimeError,'startup sync failed'):
            with session:
                self.fail('Scraping must not start after failed intake')
        self.assertFalse(session.thread.is_alive())
        self.assertIn('offline',sync.local.meta['last_error'])
        self.assertEqual(sync.events,['open','pull','close'])

    def test_untyped_factory_failure_is_not_mistaken_for_writer_contention(self):
        @contextmanager
        def factory():
            raise RuntimeError('Another local helper holds the writer lock')
            yield
        session = RunSheetsSync(factory,log=lambda message:None)
        with self.assertRaisesRegex(RuntimeError,'writer lock'):
            with session:
                self.fail('must not enter')
        self.assertFalse(session.thread.is_alive())

    def test_final_failure_is_reported_and_pending_work_retained(self):
        sync = FakeSync()
        session = self.session(sync)
        with self.assertRaisesRegex(RuntimeError,'Final Sheets sync incomplete'):
            with session:
                sync.local.pending = 2
                sync.publish_error = OSError('offline')
        self.assertEqual(sync.local.pending,2)
        self.assertFalse(session.thread.is_alive())
        self.assertIn('offline',sync.local.meta['last_error'])

    def test_final_failure_never_hides_original_scraper_error(self):
        sync = FakeSync()
        session = self.session(sync)
        with self.assertRaisesRegex(ValueError,'scraper failure'):
            with session:
                sync.local.pending = 1
                sync.publish_error = OSError('offline')
                raise ValueError('scraper failure')
        self.assertIsNotNone(session.final_error)
        self.assertFalse(session.thread.is_alive())

    def test_zero_progress_is_bounded_and_not_claimed_as_final_success(self):
        sync = FakeSync()
        session = self.session(sync)
        with self.assertRaisesRegex(RuntimeError,'1 cell'):
            with session:
                sync.local.pending = 1
                sync.zero_progress = True
        self.assertEqual(sync.events.count('publish'),1)
        self.assertEqual(sync.local.pending,1)

    def test_periodic_failure_is_retried_on_exit_without_losing_data(self):
        sync = FakeSync()
        session = self.session(sync)
        sync.local.pending = 2
        sync.publish_error = OSError('temporary')
        with self.assertRaises(OSError):
            session._publish(sync,'periodic')
        self.assertEqual(sync.local.pending,2)
        sync.publish_error = None
        result = session._publish(sync,'final',final=True)
        self.assertEqual(result['pending_cells'],0)

    def test_bounded_periodic_drain_and_stop_signal_preserve_remainder(self):
        sync = FakeSync(pending=3)
        result = publish_pending(sync,max_batches=2)
        self.assertEqual(result['published_rows'],2)
        self.assertEqual(result['pending_cells'],1)
        self.assertEqual(result['stop_reason'],'batch_budget')
        stop = threading.Event(); stop.set()
        result = publish_pending(sync,stop=stop)
        self.assertEqual(result['batches'],0)
        self.assertEqual(sync.local.pending,1)
        self.assertEqual(result['stop_reason'],'stopped')

    def test_zero_time_budget_makes_no_delivery_attempt_and_keeps_pending_cells(self):
        sync = FakeSync(pending=2)
        result = publish_pending(sync,max_seconds=0)
        self.assertEqual(result['stop_reason'],'time_budget')
        self.assertEqual(result['batches'],0)
        self.assertEqual(sync.local.pending,2)

    def test_last_batch_that_clears_queue_is_drained_even_at_batch_limit(self):
        sync = FakeSync(pending=1)
        result = publish_pending(sync,max_batches=1)
        self.assertEqual(result['stop_reason'],'drained')
        self.assertEqual(result['pending_cells'],0)

    def test_final_drain_finishes_beyond_the_old_time_budget(self):
        sync = FakeSync(pending=2)
        session = self.session(sync)
        now = [0.0]
        publish = sync.publish_batch

        def slow_batch():
            result = publish()
            now[0] += 301
            return result

        with patch('job_search_helper.run_sync.time.monotonic', side_effect=lambda:now[0]), \
             patch.object(sync,'publish_batch',side_effect=slow_batch):
            session._publish(sync,'final',final=True)
        self.assertEqual(sync.local.pending,0)
        self.assertEqual(session.report['final']['stop_reason'],'drained')
        self.assertEqual(session.report['final']['batches'],2)
        self.assertEqual(session.report['final']['elapsed_seconds'],602)

    def test_final_drain_has_no_arbitrary_batch_count_limit(self):
        sync = FakeSync(pending=1001)
        session = self.session(sync)
        session._publish(sync, 'final', final=True)
        self.assertEqual(sync.local.pending, 0)
        self.assertEqual(session.report['final']['batches'], 1001)
        self.assertEqual(session.report['final']['stop_reason'], 'drained')


class SyncWriterContentionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.lock = self.root / 'writer.lock'
        self.logs = []

    def session(self, sync, *, interval=.02):
        @contextmanager
        def factory():
            sync.events.append('open')
            try:
                yield sync
            finally:
                sync.events.append('close')
        return RunSheetsSync(factory, interval=interval, log=self.logs.append,
            lock_factory=lambda: cli.writer_lock(self.lock),
            pending_count=lambda: sync.local.pending)

    def test_busy_reviewer_never_blocks_start_scraping_or_exit(self):
        sync = FakeSync(pending=2)
        session = self.session(sync)
        with cli.writer_lock(self.lock):
            with session:
                self.assertEqual(sync.events, [])
                self.assertIsNone(session.startup_error)
                sync.local.pending += 3  # New work saves while reviewer owns Sheets.
            self.assertIsNone(session.final_error)
            self.assertFalse(session.thread.is_alive())
            self.assertEqual(sync.events, [])
            self.assertEqual(sync.local.pending, 5)
            self.assertEqual(session.report['final']['stop_reason'], 'writer_busy')
            self.assertEqual(session.totals['sheets_pending_cells'], 5)
            with self.assertRaises(cli.WriterLockBusy):
                with cli.writer_lock(self.lock):
                    self.fail('Scraper released the reviewer lock')
        self.assertTrue(any('Scraping starts now' in line for line in self.logs))

    def test_interrupt_while_reviewer_is_busy_still_stops_promptly(self):
        sync = FakeSync(pending=2)
        session = self.session(sync)
        with cli.writer_lock(self.lock), self.assertRaises(KeyboardInterrupt):
            with session:
                raise KeyboardInterrupt()
        self.assertFalse(session.thread.is_alive())
        self.assertEqual(sync.local.pending, 2)
        self.assertIsNone(session.final_error)

    def test_deferred_intake_and_saved_work_sync_when_reviewer_releases_lock(self):
        sync = FakeSync(pending=2)
        session = self.session(sync)
        owner = cli.writer_lock(self.lock)
        owner.__enter__()
        released = False
        try:
            with session:
                sync.local.pending += 1
                self.assertEqual(sync.events, [])
                owner.__exit__(None, None, None)
                released = True
                self.assertTrue(sync.published.wait(2), self.logs)
            self.assertEqual(sync.events.count('pull'), 1)
            self.assertEqual(sync.local.pending, 0)
            self.assertEqual(sync.events[0:2], ['open', 'pull'])
            self.assertFalse(session.thread.is_alive())
        finally:
            if not released:
                owner.__exit__(None, None, None)

    def test_idle_worker_releases_lock_and_periodic_contention_only_defers_upload(self):
        sync = FakeSync()
        session = self.session(sync)
        deferred = threading.Event()
        def log(message):
            self.logs.append(message)
            if 'Sheets update deferred' in message:
                deferred.set()
        session.log = log
        with session:
            # A reviewer can publish between scraper updates.
            with cli.writer_lock(self.lock):
                sync.local.pending = 3
                self.assertTrue(deferred.wait(2), self.logs)
                self.assertFalse(sync.published.is_set())
                self.assertEqual(sync.local.pending, 3)
            self.assertTrue(sync.published.wait(2), self.logs)
        self.assertEqual(sync.local.pending, 0)
        self.assertEqual(sync.events.count('pull'), 1)

    def test_actual_publication_remains_exclusive(self):
        sync = FakeSync()
        entered, release = threading.Event(), threading.Event()
        publish = sync.publish_batch
        def slow_publish():
            entered.set()
            if not release.wait(2):
                raise RuntimeError('Test did not release publication')
            return publish()
        session = self.session(sync)
        with patch.object(sync, 'publish_batch', side_effect=slow_publish), session:
            sync.local.pending = 1
            try:
                self.assertTrue(entered.wait(2), self.logs)
                with self.assertRaises(cli.WriterLockBusy):
                    with cli.writer_lock(self.lock):
                        self.fail('Overlapping remote writers')
            finally:
                release.set()
            self.assertTrue(sync.published.wait(2))
        with cli.writer_lock(self.lock):
            pass

    def imported(self):
        remote = MemoryRepository({'Companies': [{'Company ID': 'C-1', 'Company': 'Acme',
            'Company Status': 'Active', 'Official Careers URL': 'https://example.com/jobs'}]})
        remote.spreadsheet_id = 'fixture'
        local = SQLiteRepository(self.root / 'jobs.sqlite3', 'fixture', initialize=True)
        self.addCleanup(local.close)
        for tab in SCHEMAS:
            local.import_rows(tab, enumerate(remote.read(tab), 2))
        with local.transaction():
            local.set_meta('ready', 'yes')
        return local, remote

    def test_production_wiring_saves_to_sqlite_without_authentication_while_busy(self):
        local, remote = self.imported()
        session = run_scoped_sync(local, self.root / 'state.db', interval=.02)
        session.log = self.logs.append
        with cli.writer_lock(self.lock), \
             patch.object(cli, 'get_remote_repository') as authenticate:
            with session:
                local.commit([{'tab': 'Companies', 'identity': {'Company ID': 'C-1'},
                               'values': {'Last Checked': '2026-10-22'}}])
                self.assertEqual(local.read('Companies')[0]['Last Checked'], '2026-10-22')
            authenticate.assert_not_called()
        self.assertIsNone(session.startup_error)
        self.assertIsNone(session.final_error)
        self.assertEqual(session.totals['sheets_pending_cells'], 1)
        self.assertEqual(local.db.execute('SELECT count(*) FROM dirty').fetchone()[0], 1)
        self.assertFalse(session.thread.is_alive())

    def test_production_deferred_intake_imports_fresh_controls_before_publishing(self):
        local, remote = self.imported()
        session = run_scoped_sync(local, self.root / 'state.db', interval=.02)
        session.log = self.logs.append
        owner = cli.writer_lock(self.lock)
        owner.__enter__()
        released = False
        try:
            with patch.object(cli, 'get_remote_repository', return_value=remote) as authenticate:
                with session:
                    authenticate.assert_not_called()
                    local.commit([{'tab': 'Companies', 'identity': {'Company ID': 'C-1'},
                                   'values': {'Last Checked': '2026-10-22'}}])
                    remote.commit([{'tab': 'Companies', 'identity': {'Company ID': 'C-1'},
                                    'values': {'Company Status': 'Paused'}}])
                    owner.__exit__(None, None, None)
                    released = True
                # Final sync also catches a run that finishes before the retry tick.
                authenticate.assert_called_once()
            self.assertEqual(local.read('Companies')[0]['Company Status'], 'Paused')
            self.assertEqual(remote.read('Companies')[0]['Last Checked'], '2026-10-22')
            self.assertEqual(local.db.execute('SELECT count(*) FROM dirty').fetchone()[0], 0)
            self.assertIsNone(session.final_error)
        finally:
            if not released:
                owner.__exit__(None, None, None)


class RealSQLiteSyncLifecycleTests(unittest.TestCase):
    def test_worker_owns_connection_pulls_controls_and_publishes_final_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'jobs.sqlite3'
            remote = MemoryRepository({'Companies':[{'Company ID':'C-1','Company':'Acme',
                'Company Status':'Active','Official Careers URL':'https://example.com/jobs'}]})
            remote.spreadsheet_id = 'fixture'
            local = SQLiteRepository(path,'fixture',initialize=True)
            for tab in SCHEMAS:
                local.import_rows(tab,enumerate(remote.read(tab),2))
            with local.transaction(): local.set_meta('ready','yes')
            local.close()
            connections = []
            @contextmanager
            def factory():
                conn = SQLiteRepository(path,'fixture')
                connections.append((threading.get_ident(),conn))
                try:
                    yield SheetsSynchronizer(conn,remote)
                finally:
                    conn.close()
            with RunSheetsSync(factory,log=lambda message:None) as session:
                main = SQLiteRepository(path,'fixture')
                self.assertEqual(main.read('Companies')[0]['Company'],'Acme')
                main.commit([{'tab':'Companies','identity':{'Company ID':'C-1'},
                              'values':{'Last Checked':'2026-10-13'}}])
                main.close()
            self.assertEqual(remote.read('Companies')[0]['Last Checked'],'2026-10-13')
            self.assertNotEqual(connections[0][0],threading.get_ident())
            self.assertFalse(session.thread.is_alive())
            check = sqlite3.connect(path)
            self.assertEqual(check.execute('SELECT count(*) FROM dirty').fetchone()[0],0)
            check.close()


class RunnerSyncWiringTests(unittest.TestCase):
    def run_empty(self, *, local=True, defer=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        repo = MagicMock(spreadsheet_id='fixture',metrics={})
        repo.is_local = local
        engine = MagicMock(performance={})
        engine.sync_manual_opportunities.return_value = {'added':0,'skipped':0}
        with patch.object(runner,'_load_environment'), patch.object(runner,'state_path',return_value=Path(directory.name)/'state.db'), \
             patch.object(runner,'get_repository',return_value=repo),patch.object(runner,'Engine',return_value=engine), \
             patch.object(runner,'_refresh_review_queue'), patch('job_search_helper.run_sync.run_scoped_sync') as sync, \
             redirect_stdout(StringIO()):
            totals = {'sheets_published_row_updates': 0, 'sheets_pending_cells': 9}
            sync.return_value.__enter__.return_value.totals = totals
            def finish(*args):
                totals.update(sheets_published_row_updates=7, sheets_pending_cells=0)
                return False
            sync.return_value.__exit__.side_effect = finish
            result = runner.run_start(sync_only=True,browser_fallback=False,defer_sync=defer)
            self.metrics = json.loads((Path(directory.name)/'scraper-performance.json').read_text())
        return result,sync

    def test_sqlite_sync_is_entered_and_exited_even_when_no_inventories(self):
        result,sync = self.run_empty()
        self.assertEqual(result,0)
        sync.assert_called_once()
        sync.return_value.__enter__.assert_called_once()
        sync.return_value.__exit__.assert_called_once()
        self.assertEqual(self.metrics['sheets_published_row_updates'], 7)
        self.assertEqual(self.metrics['sheets_pending_cells'], 0)

    def test_deferred_sqlite_run_never_constructs_sync(self):
        result,sync = self.run_empty(defer=True)
        self.assertEqual(result,0)
        sync.assert_not_called()

    def test_direct_sheets_backend_keeps_existing_path(self):
        result,sync = self.run_empty(local=False)
        self.assertEqual(result,0)
        sync.assert_not_called()


if __name__ == '__main__':
    unittest.main()
