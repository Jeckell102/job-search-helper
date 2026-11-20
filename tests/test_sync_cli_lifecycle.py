"""Publisher lifecycle tests use only temporary SQLite databases and file locks."""
from contextlib import ExitStack
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper import sync_cli
from job_search_helper.cli import writer_lock, WriterLockBusy
from job_search_helper.sqlite_repository import SQLiteRepository


class SyncCliLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.lock = self.directory / 'writer.lock'
        self.local = SQLiteRepository(self.directory / 'jobs.sqlite3', 'fixture', initialize=True)
        self.addCleanup(self.local.close)
        self.messages = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, replacement in [('_load_environment', lambda: None),
                ('SQLiteRepository', lambda *a, **k: self.local),
                ('state_path', lambda: self.directory / 'state.db'),
                ('job_database_path', lambda: self.local.path),
                ('storage_backend', lambda: 'sqlite'),
                ('print_status', self.messages.append)]:
            self.stack.enter_context(patch.object(sync_cli, name, replacement))
        self.stack.enter_context(patch.dict('os.environ', {'SPREADSHEET_ID': 'fixture'}))
        self.remote_factory = self.stack.enter_context(patch.object(sync_cli, 'get_remote_repository'))
        self.sync_factory = self.stack.enter_context(patch.object(sync_cli, 'SheetsSynchronizer'))
        self.run_cycle = self.stack.enter_context(patch.object(sync_cli, 'cycle'))
        self.run_cycle.return_value = {'published_rows': 0}

    def assert_locked(self):
        with self.assertRaises(WriterLockBusy):
            with writer_lock(self.lock):
                pass

    def assert_closed(self):
        with self.assertRaises(sqlite3.ProgrammingError):
            self.local.db.execute('SELECT 1')

    def test_watch_initializes_and_runs_under_lock_but_releases_before_sleep(self):
        def remote(**kwargs):
            self.assert_locked()
            return object()
        def cycle(*args, **kwargs):
            self.assert_locked()
            return {'published_rows': 0}
        def sleep(delay):
            with writer_lock(self.lock):
                pass  # A reviewer can acquire the real lock between cycles.
            raise KeyboardInterrupt
        self.remote_factory.side_effect = remote
        self.run_cycle.side_effect = cycle
        with patch.object(sync_cli.time, 'sleep', side_effect=sleep):
            self.assertEqual(sync_cli.main(['watch', '--interval', '5']), 130)
        self.assert_closed()

    def test_busy_watch_retries_without_initializing_remote_until_lock_is_free(self):
        holder = writer_lock(self.lock)
        holder.__enter__()
        held = True
        sleeps = []
        def sleep(delay):
            nonlocal held
            sleeps.append(delay)
            if held:
                self.assertLessEqual(delay, 30)
                self.remote_factory.assert_not_called()
                self.run_cycle.assert_not_called()
                holder.__exit__(None, None, None)
                held = False
            else:
                raise KeyboardInterrupt
        try:
            with patch.object(sync_cli.time, 'sleep', side_effect=sleep):
                self.assertEqual(sync_cli.main(['watch', '--interval', '3600']), 130)
        finally:
            if held: holder.__exit__(None, None, None)
        self.assertEqual(self.run_cycle.call_count, 1)
        self.assertEqual(len(sleeps), 2)
        self.assertTrue(any(item.get('state') == 'SYNC_DEFERRED_WRITER_BUSY' for item in self.messages))
        self.assert_closed()

    def test_watch_releases_lock_after_error_and_retries(self):
        self.run_cycle.side_effect = [RuntimeError('fixture failure'), {'published_rows': 1}]
        sleeps = []
        def sleep(delay):
            with writer_lock(self.lock): pass
            sleeps.append(delay)
            self.assertGreaterEqual(delay, 1)
            self.assertLessEqual(delay, 300)
            if len(sleeps) == 2: raise KeyboardInterrupt
        with patch.object(sync_cli.time, 'sleep', side_effect=sleep):
            self.assertEqual(sync_cli.main(['watch', '--interval', '5']), 130)
        self.assertEqual(self.run_cycle.call_count, 2)
        self.remote_factory.assert_called_once()
        self.assertTrue(any(item.get('state') == 'SYNC_ERROR_LOCAL_WORK_RETAINED' for item in self.messages))
        self.assert_closed()

    def test_watch_retries_initialization_failure_under_lock(self):
        attempts = []
        def remote(**kwargs):
            self.assert_locked()
            attempts.append(True)
            if len(attempts) == 1:
                raise RuntimeError('fixture initialization failure')
            return object()
        sleeps = []
        def sleep(delay):
            with writer_lock(self.lock): pass
            sleeps.append(delay)
            if len(sleeps) == 2: raise KeyboardInterrupt
        self.remote_factory.side_effect = remote
        with patch.object(sync_cli.time, 'sleep', side_effect=sleep):
            self.assertEqual(sync_cli.main(['watch', '--interval', '5']), 130)
        self.assertEqual(len(attempts), 2)
        self.run_cycle.assert_called_once()
        self.assert_closed()

    def test_once_success_and_failure_do_not_sleep_and_close_local(self):
        with patch.object(sync_cli.time, 'sleep') as sleep:
            self.assertEqual(sync_cli.main(['once']), 0)
            sleep.assert_not_called()
        self.assert_closed()

    def test_once_error_returns_nonzero_without_sleep(self):
        self.run_cycle.side_effect = RuntimeError('fixture failure')
        with patch.object(sync_cli.time, 'sleep') as sleep:
            self.assertEqual(sync_cli.main(['once']), 1)
            sleep.assert_not_called()
        self.assert_closed()

    def test_once_busy_fails_without_remote_initialization_or_wait(self):
        with writer_lock(self.lock), patch.object(sync_cli.time, 'sleep') as sleep:
            self.assertEqual(sync_cli.main(['once']), 1)
            self.remote_factory.assert_not_called()
            sleep.assert_not_called()
        self.assert_closed()

    def test_interrupt_during_cycle_releases_lock_and_closes_local(self):
        self.run_cycle.side_effect = KeyboardInterrupt
        self.assertEqual(sync_cli.main(['watch', '--interval', '5']), 130)
        with writer_lock(self.lock): pass
        self.assert_closed()
