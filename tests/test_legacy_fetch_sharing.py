"""The legacy single-writer runner shares details without changing ownership."""
from collections import Counter
from contextlib import closing, redirect_stdout
from io import StringIO
import sqlite3
from threading import Barrier, Event, Lock, get_ident
import unittest
from unittest.mock import patch

from job_search_helper.cooperative_fetch import iter_details
from job_search_helper.dashboard import TerminalDashboard
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from test_fetch_pool import OwnedRepository, company, inventory


class LegacyFetchSharingTests(unittest.TestCase):
    def setUp(self):
        capture = redirect_stdout(StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def make(self, count, fetch, *, durable=False, all_companies=False):
        repo = OwnedRepository({'Companies': [company(i) for i in range(count)]})
        state = State()
        self.addCleanup(state.close)
        inbox = InventoryInbox(':memory:', 'fixture') if durable else None
        if inbox is not None:
            self.addCleanup(inbox.close)
        engine = Engine(repo, state, fetcher=fetch, inbox=inbox, error_log_path=None)
        cycle = engine.start_cycle(None if all_companies else [f'C-{i}' for i in range(count)])
        return repo, state, engine, cycle

    @staticmethod
    def detail(cid, name, url, number):
        row = inventory(cid, name, url).jobs[0]
        row.update(posting_id=str(number), url=f'{url}/jobs/{number}')
        return row

    def test_idle_workers_share_last_company_once_and_only_writer_touches_repository(self):
        barrier = Barrier(4, timeout=5)
        calls, threads, lock = Counter(), set(), Lock()

        def fetch(source, url, cid, name):
            def detail(number):
                with lock:
                    calls[number] += 1
                    threads.add(get_ident())
                if number < 4:
                    barrier.wait()
                return self.detail(cid, name, url, number)
            result = inventory(cid, name, url)
            with closing(iter_details(detail, range(12))) as details:
                result.jobs = list(details)
            return result

        repo, state, engine, cycle = self.make(1, fetch, durable=True)
        engine.resume_parallel(cycle, fetch_workers=4)
        self.assertEqual(calls, Counter(range(12)))
        self.assertEqual(len(threads), 4)
        self.assertEqual(len(repo.read('Job History')), 12)
        self.assertEqual(len({r['Job Key'] for r in repo.read('Job History')}), 12)
        self.assertEqual(state.cycle(cycle)['companies']['C-0']['stage'], 'complete')
        self.assertIsNone(engine.inbox.get(cycle, 'C-0'))

    def test_queued_companies_take_priority_over_helping(self):
        started, helper_checks, lock = set(), [], Lock()
        helper_arrived = Event()

        def fetch(source, url, cid, name):
            with lock:
                started.add(cid)
            if cid != 'C-0':
                return inventory(cid, name, url)
            owner = get_ident()

            def detail(number):
                if get_ident() != owner:
                    with lock:
                        helper_checks.append(len(started))
                    helper_arrived.set()
                elif number == 0:
                    self.assertTrue(helper_arrived.wait(5))
                return self.detail(cid, name, url, number)

            result = inventory(cid, name, url)
            with closing(iter_details(detail, range(10))) as details:
                result.jobs = list(details)
            return result

        repo, _, engine, cycle = self.make(6, fetch)
        engine.resume_parallel(cycle, fetch_workers=2, assignment_window=25)
        self.assertTrue(helper_checks)
        self.assertEqual(set(helper_checks), {6})
        self.assertEqual(len(repo.read('Job History')), 15)

    def test_newly_discovered_company_preempts_waiting_helpers(self):
        helper_started, release_helper, new_company_started = Event(), Event(), Event()

        def fetch(source, url, cid, name):
            if cid == 'C-2':
                new_company_started.set()
            if cid != 'C-0':
                return inventory(cid, name, url)

            def detail(number):
                if number == 0:
                    self.assertTrue(new_company_started.wait(5), 'helper blocked the new company')
                elif number == 1:
                    helper_started.set()
                    self.assertTrue(release_helper.wait(5))
                return self.detail(cid, name, url, number)

            result = inventory(cid, name, url)
            with closing(iter_details(detail, range(8))) as details:
                result.jobs = list(details)
            return result

        repo, state, engine, cycle = self.make(2, fetch, all_companies=True)
        stage = engine._stage_inventory
        added = False

        def discover(current, source, *args, **kwargs):
            nonlocal added
            if source['Company ID'] == 'C-1' and not added:
                self.assertTrue(helper_started.wait(5))
                added = True
                repo.commit([{'tab': 'Companies', 'identity': {'Company ID': 'C-2'},
                              'values': company(2), 'append_if_missing': True}])
                release_helper.set()
            return stage(current, source, *args, **kwargs)

        with patch.object(engine, '_stage_inventory', side_effect=discover):
            engine.resume_parallel(cycle, fetch_workers=2)
        self.assertTrue(added)
        self.assertTrue(new_company_started.is_set(), repo.read('Companies'))
        self.assertEqual(len(repo.read('Job History')), 10)
        self.assertTrue(all(row['stage'] == 'complete'
                            for row in state.cycle(cycle)['companies'].values()))

    def test_durable_save_failure_surfaces_without_success_checkpoint_or_hung_helpers(self):
        barrier = Barrier(3, timeout=5)

        def fetch(source, url, cid, name):
            def detail(number):
                barrier.wait()
                return self.detail(cid, name, url, number)
            result = inventory(cid, name, url)
            with closing(iter_details(detail, range(3))) as details:
                result.jobs = list(details)
            return result

        repo, state, engine, cycle = self.make(1, fetch, durable=True)
        with patch.object(engine.inbox, 'save', side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'disk full'):
                engine.resume_parallel(cycle, fetch_workers=3)
        self.assertEqual(repo.read('Job History'), [])
        self.assertEqual(state.cycle(cycle)['companies']['C-0']['stage'], 'queued')

    def test_helper_callback_failure_surfaces_and_finishes_claimed_detail(self):
        helper_called = Event()
        completed, lock = set(), Lock()

        def fetch(source, url, cid, name):
            def detail(number):
                if number == 0:
                    self.assertTrue(helper_called.wait(5))
                with lock:
                    completed.add(number)
                return self.detail(cid, name, url, number)
            result = inventory(cid, name, url)
            with closing(iter_details(detail, range(2))) as details:
                result.jobs = list(details)
            return result

        def fail_display(dashboard, slot, name):
            if name:
                helper_called.set()
                raise RuntimeError('display failed')

        _, _, engine, cycle = self.make(1, fetch)
        with patch.object(TerminalDashboard, 'worker_assisting', fail_display):
            with self.assertRaisesRegex(RuntimeError, 'display failed'):
                engine.resume_parallel(cycle, fetch_workers=2)
        self.assertEqual(completed, {0, 1})

    def test_worker_setup_failure_releases_remaining_company_count(self):
        _, state, engine, cycle = self.make(1, lambda *args: self.fail('fetch should not run'))
        with patch.object(TerminalDashboard, 'worker_fetching', side_effect=RuntimeError('display failed')):
            engine.resume_parallel(cycle, fetch_workers=3)
        self.assertEqual(state.cycle(cycle)['companies']['C-0']['stage'], 'failed')


if __name__ == '__main__':
    unittest.main()
