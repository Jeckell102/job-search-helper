"""Deterministic scheduling/lifecycle tests; no network or timing benchmarks."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout
from io import StringIO
from threading import Barrier, Event, Lock, get_ident
import unittest
from unittest.mock import patch

from job_search_helper.cooperative_fetch import (
    CooperativeFetchWork, get_shared_resource, iter_details,
)
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from test_fetch_pool import OwnedRepository, company, inventory


class CooperativeFetchTests(unittest.TestCase):
    def test_unbound_calls_are_sequential_and_ordered(self):
        owner = get_ident()
        seen = []
        def fetch(value):
            seen.append(get_ident())
            return value * 2
        self.assertEqual(list(iter_details(fetch, range(8))), list(range(0, 16, 2)))
        self.assertEqual(seen, [owner] * 8)

    def test_idle_helper_executes_each_detail_once_and_preserves_order(self):
        work = CooperativeFetchWork(1, max_pending=2)
        stop = Event()
        paired = Barrier(2, timeout=5)
        calls, threads, labels = Counter(), set(), []
        lock = Lock()
        def fetch(value):
            with lock:
                calls[value] += 1
                threads.add(get_ident())
            if value < 2:
                paired.wait()
            return value
        def owner():
            try:
                with work.bind_worker('Large Company'):
                    return list(iter_details(fetch, range(10)))
            finally:
                work.company_done()
        with ThreadPoolExecutor(max_workers=2) as executor:
            helper = executor.submit(work.help_until_finished, stop, labels.append)
            result = executor.submit(owner)
            self.assertEqual(result.result(timeout=5), list(range(10)))
            helper.result(timeout=5)
        self.assertEqual(calls, Counter(range(10)))
        self.assertEqual(len(threads), 2)
        self.assertTrue(labels)
        self.assertEqual(set(labels), {'Large Company'})
        self.assertFalse(work.help_one())

    def test_all_workers_can_own_companies_without_spare_helpers(self):
        work = CooperativeFetchWork(2, max_pending=4)
        started = Barrier(2, timeout=5)
        def owner(name):
            try:
                with work.bind_worker(name):
                    started.wait()
                    return list(iter_details(lambda x: (name, x), range(20)))
            finally:
                work.company_done()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(owner, name) for name in ('A', 'B')]
            for name, future in zip(('A', 'B'), futures):
                self.assertEqual(future.result(timeout=5), [(name, x) for x in range(20)])

    def test_detail_window_is_lazy_and_early_close_cancels_queued_work(self):
        work = CooperativeFetchWork(1, max_pending=3)
        supplied, executed = [], []
        def source():
            for value in range(1000):
                supplied.append(value)
                yield value
        def fetch(value):
            executed.append(value)
            return value
        with work.bind_worker():
            with closing(iter_details(fetch, source())) as results:
                self.assertEqual(next(results), 0)
                self.assertEqual(supplied, [0, 1, 2])
        self.assertEqual(executed, [0])
        self.assertFalse(work.help_one())

    def test_close_waits_for_started_request_and_cancels_unstarted_requests(self):
        work = CooperativeFetchWork(1, max_pending=3)
        first_started, second_started = Event(), Event()
        release, closing_started, closed = Event(), Event(), Event()
        self.addCleanup(release.set)
        calls = []
        def fetch(value):
            calls.append(value)
            if value == 0:
                first_started.set()
                self.assertTrue(second_started.wait(5))
            elif value == 1:
                second_started.set()
                self.assertTrue(release.wait(5))
            return value
        def helper():
            self.assertTrue(first_started.wait(5))
            self.assertTrue(work.help_one(timeout=5))
        def close(results):
            closing_started.set()
            results.close()
            closed.set()
        with ThreadPoolExecutor(max_workers=2) as executor:
            assisting = executor.submit(helper)
            with work.bind_worker():
                results = iter_details(fetch, range(3))
                self.assertEqual(next(results), 0)
                draining = executor.submit(close, results)
                self.assertTrue(closing_started.wait(5))
                self.assertFalse(closed.is_set())
                release.set()
                draining.result(timeout=5)
                assisting.result(timeout=5)
        self.assertEqual(calls, [0, 1])
        self.assertFalse(work.help_one())

    def test_task_exception_does_not_leave_queued_work(self):
        work = CooperativeFetchWork(1, max_pending=3)
        calls = []
        def fetch(value):
            calls.append(value)
            raise ValueError('failed detail')
        with work.bind_worker(), self.assertRaisesRegex(ValueError, 'failed detail'):
            list(iter_details(fetch, range(100)))
        self.assertEqual(calls, [0])
        self.assertFalse(work.help_one())

    def test_source_exception_cancels_already_enqueued_details(self):
        work = CooperativeFetchWork(1, max_pending=3)
        calls = []
        def source():
            yield 0
            raise ValueError('bad listing iterator')
        with work.bind_worker(), self.assertRaisesRegex(ValueError, 'bad listing iterator'):
            list(iter_details(calls.append, source()))
        self.assertEqual(calls, [])
        self.assertFalse(work.help_one())

    def test_helper_callback_failure_does_not_strand_claimed_future(self):
        work = CooperativeFetchWork(1, max_pending=2)
        callback_entered = Event()
        def source():
            yield 0
            self.assertTrue(callback_entered.wait(5))
            yield 1
        def callback(name):
            callback_entered.set()
            raise ValueError('dashboard failed')
        with ThreadPoolExecutor(max_workers=1) as executor:
            helper = executor.submit(work.help_one, 5, callback)
            with work.bind_worker():
                self.assertEqual(list(iter_details(lambda x: x, source())), [0, 1])
            with self.assertRaisesRegex(ValueError, 'dashboard failed'):
                helper.result(timeout=5)

    def test_resource_is_shared_within_run_and_binding_is_restored(self):
        work = CooperativeFetchWork(0)
        calls = []
        def resource():
            calls.append(1)
            return object()
        def owner():
            with work.bind_worker():
                return get_shared_resource('host', resource)
        with ThreadPoolExecutor(max_workers=3) as executor:
            resources = list(executor.map(lambda _: owner(), range(20)))
        self.assertTrue(all(value is resources[0] for value in resources))
        self.assertEqual(calls, [1])
        self.assertIsNot(get_shared_resource('host', resource), resources[0])

    def test_empty_run_and_stopped_helper_exit_without_work(self):
        work = CooperativeFetchWork(0)
        work.help_until_finished(Event())
        work.company_added(1)
        stop = Event()
        stop.set()
        work.help_until_finished(stop)
        work.company_done()
        with self.assertRaises(RuntimeError):
            work.company_done()


class LocalCooperativeFetchTests(unittest.TestCase):
    def setUp(self):
        capture = redirect_stdout(StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def make(self, fetch, count=3):
        repo = OwnedRepository({'Companies': [company(i) for i in range(count)]})
        state = State()
        inbox = InventoryInbox(':memory:', 'fixture')
        self.addCleanup(state.close)
        self.addCleanup(inbox.close)
        engine = Engine(repo, state, fetcher=fetch, inbox=inbox, error_log_path=None)
        cycle = engine.start_cycle([f'C-{i}' for i in range(count)])
        return engine, cycle

    def test_idle_worker_prioritizes_remaining_company_then_helps_and_saves_once(self):
        last_company_started, detail_started, helper_started = Event(), Event(), Event()
        owner_thread = None
        assisted, detail_calls, company_calls = [], Counter(), []
        lock = Lock()
        def fetch(source, url, cid, name):
            nonlocal owner_thread
            company_calls.append(cid)
            result = inventory(cid, name, url)
            if cid != 'C-0':
                self.assertTrue(detail_started.wait(5))
                if cid == 'C-2':
                    last_company_started.set()
                return result
            owner_thread = get_ident()
            def detail(value):
                with lock:
                    detail_calls[value] += 1
                if get_ident() == owner_thread:
                    detail_started.set()
                    self.assertTrue(last_company_started.wait(5))
                    self.assertTrue(helper_started.wait(5))
                else:
                    self.assertTrue(last_company_started.is_set())
                    assisted.append(value)
                    helper_started.set()
                return {**result.jobs[0], 'posting_id': str(value)}
            with closing(iter_details(detail, range(30))) as rows:
                result.jobs = list(rows)
            return result
        engine, cycle = self.make(fetch)
        with patch.object(engine.inbox, 'save', wraps=engine.inbox.save) as save:
            engine.resume_local(cycle, fetch_workers=2, assignment_window=1, defer_sync=True)
        self.assertEqual(Counter(company_calls), Counter(['C-0', 'C-1', 'C-2']))
        self.assertEqual(detail_calls, Counter(range(30)))
        self.assertTrue(assisted)
        self.assertEqual(save.call_count, 3)
        self.assertEqual(len(engine.inbox.get(cycle, 'C-0')[0]['jobs']), 30)
        self.assertTrue(all(row['task'] != 'Helping' for row in engine._dashboard.worker_state.values()))

    def test_durability_error_stops_helpers_and_propagates(self):
        def fetch(source, url, cid, name):
            with closing(iter_details(lambda x: x, range(8))) as rows:
                list(rows)
            return inventory(cid, name, url)
        engine, cycle = self.make(fetch, count=1)
        with patch.object(engine.inbox, 'save', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                engine.resume_local(cycle, fetch_workers=3, defer_sync=True)


if __name__ == '__main__':
    unittest.main()
