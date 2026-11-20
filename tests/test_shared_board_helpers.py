"""Shared HTTP detail fetching preserves inventory and request guarantees."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import copy
import json
from pathlib import Path
from threading import Barrier, Event, Lock, get_ident
import time
import unittest
from unittest.mock import patch

from job_search_helper import shared_boards as boards
from job_search_helper.ats import FetchError
from job_search_helper.cooperative_fetch import CooperativeFetchWork


@contextmanager
def helpers(count=4):
    work = CooperativeFetchWork(1, max_pending=2 * count)
    stop = Event()
    with ThreadPoolExecutor(max_workers=count - 1) as pool:
        futures = [pool.submit(work.help_until_finished, stop) for _ in range(count - 1)]
        try:
            with work.bind_worker('Example'):
                yield work
        finally:
            work.company_done()
            for future in futures:
                future.result(timeout=5)


class Response:
    def __init__(self, status=200, body=b'{}', headers=None):
        self.status, self.body, self.headers = status, body, headers or {}

    def read(self, limit):
        return self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class SharedBoardHelperTests(unittest.TestCase):
    def setUp(self):
        self.board = boards.board_link('https://careers.smartrecruiters.com/Example')

    def scan(self, transport, entries, posting, listings=None, max_jobs=10000):
        with patch.object(boards, 'listing', side_effect=listings or [entries, entries]), \
                patch.object(boards, 'posting', side_effect=posting):
            return boards._fetch(self.board, transport, 'C-1', 'Example', self.board.url,
                                 max_jobs=max_jobs)

    def test_idle_helpers_fetch_each_detail_once_and_keep_listing_order(self):
        entries = [{'id': str(i)} for i in range(12)]
        barrier, lock, counts, threads = Barrier(4), Lock(), Counter(), set()

        def posting(board, transport, entry, *args):
            with lock:
                counts[entry['id']] += 1
                threads.add(get_ident())
            if int(entry['id']) < 4:
                barrier.wait(timeout=5)
            return {'posting_id': entry['id']}

        with helpers():
            result = self.scan(boards.Transport(self.board), entries, posting)
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(counts, Counter({str(i): 1 for i in range(12)}))
        self.assertEqual([job['posting_id'] for job in result.jobs], [str(i) for i in range(12)])
        self.assertEqual(len(threads), 4)

    def test_native_smartrecruiters_fetch_validates_details_and_final_listing(self):
        fixtures = Path(__file__).parent / 'fixtures' / 'shared_boards'
        entry = json.loads((fixtures / 'smartrecruiters-feed.json').read_text())['content'][0]
        detail = json.loads((fixtures / 'smartrecruiters-detail.json').read_text())
        entries, details = [], {}
        for number in range(6):
            ident = str(744000153853000 + number)
            listed, full = copy.deepcopy(entry), copy.deepcopy(detail)
            listed['id'] = full['id'] = ident
            listed['company']['identifier'] = full['company']['identifier'] = 'Example'
            full['postingUrl'] = f'https://jobs.smartrecruiters.com/Example/{ident}-systems-designer'
            entries.append(listed)
            details[ident] = full
        feed = {'offset': 0, 'limit': 100, 'totalFound': len(entries), 'content': entries}
        calls, lock, barrier = Counter(), Lock(), Barrier(4)

        class Opener:
            def open(client, request, timeout):
                url = request.full_url
                with lock:
                    calls[url] += 1
                if '?' in url:
                    body = feed
                else:
                    ident = url.rsplit('/', 1)[-1]
                    if int(ident) < 744000153853004:
                        barrier.wait(timeout=5)
                    body = details[ident]
                return Response(body=json.dumps(body).encode())

        with helpers(), patch.object(boards, 'build_opener', side_effect=lambda *args: Opener()):
            transport = boards.Transport(self.board)
            transport._limits.for_url('https://api.smartrecruiters.com').interval = 0
            result = boards.fetch_shared('SmartRecruiters', self.board.url, 'C-1', 'Example', transport)
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual([row['posting_id'] for row in result.jobs], list(details))
        self.assertTrue(all(len(row['description']) > 100 for row in result.jobs))
        self.assertEqual(sum(count for url, count in calls.items() if '?' in url), 2)
        self.assertEqual(sum(count for url, count in calls.items() if '?' not in url), 6)

    def test_custom_transport_stays_on_owner_thread(self):
        owner = get_ident()
        threads = []

        def posting(board, transport, entry, *args):
            threads.append(get_ident())
            return {'posting_id': entry['id']}

        with helpers():
            result = self.scan(object(), [{'id': str(i)} for i in range(6)], posting)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(threads, [owner] * 6)

    def test_failure_remains_partial_and_does_not_drop_other_valid_details(self):
        entries = [{'id': str(i)} for i in range(6)]

        def posting(board, transport, entry, *args):
            if entry['id'] == '2':
                raise FetchError('partial', 'Invalid detail identity')
            return {'posting_id': entry['id']}

        with helpers():
            result = self.scan(boards.Transport(self.board), entries, posting)
        self.assertEqual(result.status, 'partial', result.reason)
        self.assertIn('1 postings failed validation', result.reason)
        self.assertEqual([row['posting_id'] for row in result.jobs], ['0', '1', '3', '4', '5'])

    def test_blocked_detail_does_not_recheck_or_report_complete(self):
        entries = [{'id': str(i)} for i in range(30)]
        calls = Counter()

        def posting(board, transport, entry, *args):
            calls[entry['id']] += 1
            if entry['id'] == '0':
                raise FetchError('blocked', 'Access denied')
            return {'posting_id': entry['id']}

        with helpers(), patch.object(boards, 'listing', return_value=entries) as listing, \
                patch.object(boards, 'posting', side_effect=posting):
            result = boards._fetch(self.board, boards.Transport(self.board), 'C-1', 'Example', self.board.url)
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(listing.call_count, 1)
        self.assertLess(len(calls), len(entries))
        self.assertTrue(all(count == 1 for count in calls.values()))

    def test_reconciliation_refetches_only_edited_and_new_details(self):
        initial = [{'id': '1', 'version': 1}, {'id': '2', 'version': 1}, {'id': '3', 'version': 1}]
        final = [{'id': '1', 'version': 1}, {'id': '2', 'version': 2}, {'id': '4', 'version': 1}]
        calls = Counter()

        def posting(board, transport, entry, *args):
            calls[(entry['id'], entry['version'])] += 1
            return dict(entry)

        with helpers():
            result = self.scan(boards.Transport(self.board), initial, posting,
                               listings=[initial, final, final])
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(result.jobs, final)
        self.assertEqual(calls, Counter({('1', 1): 1, ('2', 1): 1, ('3', 1): 1,
                                         ('2', 2): 1, ('4', 1): 1}))

    def test_success_cap_does_not_schedule_extra_requests(self):
        entries = [{'id': str(i)} for i in range(20)]
        calls = Counter()

        def posting(board, transport, entry, *args):
            calls[entry['id']] += 1
            if entry['id'] == '1':
                raise FetchError('partial', 'Missing description')
            return {'posting_id': entry['id']}

        with helpers():
            result = self.scan(boards.Transport(self.board), entries, posting, max_jobs=3)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(result.jobs), 3)
        self.assertEqual(calls, Counter({'0': 1, '1': 1, '2': 1, '3': 1}))

    def test_duplicate_listing_fails_before_any_details(self):
        entries = [{'id': '1'}, {'id': '1'}]
        with helpers(), patch.object(boards, 'posting') as posting:
            result = self.scan(boards.Transport(self.board), entries, posting)
        self.assertEqual(result.status, 'partial')
        posting.assert_not_called()

    def test_host_limit_is_shared_between_companies_and_openers_are_thread_local(self):
        work = CooperativeFetchWork()
        with work.bind_worker():
            first = boards.Transport(self.board)
            second = boards.Transport(boards.board_link('https://careers.smartrecruiters.com/Other'))
        self.assertIs(first._limits, second._limits)
        first_url = 'https://api.smartrecruiters.com/v1/companies/Example/postings/1'
        second_url = 'https://api.smartrecruiters.com/v1/companies/Other/postings/2'
        limit = first._limits.for_url(first_url)
        self.assertIs(limit, second._limits.for_url(second_url))
        limit.interval = 0.01
        lock, starts, clients = Lock(), [], set()
        activity = {'current': 0, 'maximum': 0}

        class Opener:
            def __init__(client):
                client.owner = get_ident()

            def open(client, request, timeout):
                self.assertEqual(get_ident(), client.owner)
                with lock:
                    clients.add(client.owner)
                    starts.append(time.monotonic())
                    activity['current'] += 1
                    activity['maximum'] = max(activity['maximum'], activity['current'])
                time.sleep(0.06)
                with lock:
                    activity['current'] -= 1
                return Response()

        with patch.object(boards, 'build_opener', side_effect=lambda *args: Opener()), \
                ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit((first if i % 2 else second).get,
                                   first_url if i % 2 else second_url) for i in range(8)]
            for future in futures:
                self.assertEqual(future.result(timeout=5).status, 200)
        self.assertGreater(activity['maximum'], 1)
        self.assertLessEqual(activity['maximum'], 4)
        self.assertEqual(len(clients), 8)
        self.assertTrue(all(b - a >= 0.009 for a, b in zip(starts, starts[1:])), starts)

    def test_retry_after_pauses_shared_host_for_full_delay(self):
        now, starts = [0.0], []
        responses = iter([Response(429, headers={'Retry-After': '12'}), Response(), Response()])

        class Opener:
            def open(self, request, timeout):
                starts.append(now[0])
                return next(responses)

        def sleep(seconds):
            now[0] += seconds

        with patch.object(boards.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(boards.time, 'sleep', side_effect=sleep), \
                patch.object(boards, 'build_opener', return_value=Opener()):
            work = CooperativeFetchWork()
            with work.bind_worker():
                first, second = boards.Transport(self.board), boards.Transport(self.board)
            url = 'https://api.smartrecruiters.com/v1/companies/Example/postings/1'
            self.assertEqual(first.get(url).status, 200)
            self.assertEqual(second.get(url).status, 200)
        self.assertEqual(starts, [0.0, 12.0, 12.4])

    def test_long_retry_after_stays_partial_without_waiting_or_retrying_early(self):
        with patch.object(boards.time, 'sleep') as sleep, \
                patch.object(boards, 'build_opener') as factory:
            factory.return_value.open.return_value = Response(429, headers={'Retry-After': '3600'})
            work = CooperativeFetchWork()
            with work.bind_worker():
                first, second = boards.Transport(self.board), boards.Transport(self.board)
            url = 'https://api.smartrecruiters.com/v1/companies/Example/postings/1'
            for transport in (first, second):
                with self.assertRaises(FetchError) as error:
                    transport.get(url)
                self.assertEqual(error.exception.status, 'partial')
                self.assertIn('retry later', error.exception.reason)
            self.assertEqual(factory.return_value.open.call_count, 1)
            sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
