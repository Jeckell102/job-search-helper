"""Acceptance tests for automatic retries with real durable staging."""
from collections import Counter
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from job_search_helper.ats import Inventory
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import MemoryRepository
from job_search_helper.runner import _run_scan_with_retries
from test_fetch_pool import company, inventory


class PartialInventoryRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.state = State(root / 'state.db')
        self.addCleanup(self.state.close)
        self.inbox = InventoryInbox(root / 'inbox.db', 'fixture')
        self.addCleanup(self.inbox.close)
        self.repo = MemoryRepository({'Companies': [company(i) for i in range(3)]})
        self.repo.spreadsheet_id = 'fixture'
        self.calls = Counter()
        self.recover = True
        def fetch(source, url, cid, name):
            self.calls[cid] += 1
            result = inventory(cid, name, url)
            if cid == 'C-1':
                result.status = 'partial'
                result.reason = 'Listing count disagreed'
                if self.calls[cid] > 1 and self.recover:
                    result.status = 'complete'
                    more = dict(result.jobs[0], posting_id='late-job', url=url + '/late-job')
                    result.jobs.append(more)
            if cid == 'C-2':
                return Inventory('blocked', reason='403; manual verification needed')
            return result
        self.engine = Engine(self.repo, self.state, inbox=self.inbox, fetcher=fetch,
                             error_log_path=root / 'errors.jsonl')
        self.output = StringIO()
        capture = redirect_stdout(self.output)
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)
        self.cycle = self.engine.start_cycle()

    def run_scan(self, **kwargs):
        return _run_scan_with_retries(self.engine, self.cycle, fetch_workers=1, **kwargs)

    def test_retry_recovers_missing_job_without_refetching_successes_or_blocked_companies(self):
        result = self.run_scan()
        self.assertEqual(self.calls, {'C-0': 1, 'C-1': 2, 'C-2': 1})
        rows = self.repo.read('Job History')
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({row['Job Key'] for row in rows}), 3)
        self.assertEqual(result['run_counts'], {'new_jobs': 3, 'successful': 2, 'partial': 0,
                                              'skipped': 0, 'failed': 1, 'pending': 0})
        self.assertEqual(result['status'], 'Complete with exceptions')
        self.assertIn('Retrying 1 incomplete', self.output.getvalue())
        self.assertEqual(self.engine.performance['locally_processed_jobs'], 4)

    def test_persistent_gap_stays_partial_after_bounded_retry(self):
        self.recover = False
        result = self.run_scan()
        self.assertEqual(self.calls['C-1'], 2)
        self.assertEqual(result['run_counts']['new_jobs'], 2)
        self.assertEqual(result['run_counts']['partial'], 1)
        row = next(r for r in self.repo.read('Companies') if r['Company ID'] == 'C-1')
        self.assertEqual(row['Scan State'], 'Partial')
        self.assertFalse(row.get('Last Checked'))

    def test_retry_can_be_disabled(self):
        result = self.run_scan(partial_retries=0)
        self.assertEqual(self.calls['C-1'], 1)
        self.assertEqual(result['run_counts']['partial'], 1)

    def test_two_retry_limit_is_enforced(self):
        self.recover = False
        self.run_scan(partial_retries=2)
        self.assertEqual(self.calls['C-1'], 3)
        self.assertEqual(self.calls['C-0'], 1)

    def test_invalid_retry_limit_is_rejected_before_opening_storage(self):
        from job_search_helper.runner import run_start
        for value in (-1, 3, True, 1.5):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Partial retries'):
                run_start(partial_retries=value)

    def test_deferred_fetch_does_not_refetch_unprocessed_durable_results(self):
        result = self.run_scan(defer_sync=True)
        self.assertEqual(self.calls, {'C-0': 1, 'C-1': 1, 'C-2': 1})
        self.assertEqual(result['run_counts']['pending'], 3)
        self.assertEqual(self.repo.read('Job History'), [])
        self.engine.fetcher = lambda *args: self.fail('sync must never fetch')
        synced = self.run_scan(sync_only=True)
        self.assertEqual(synced['run_counts']['partial'], 1)
        self.assertEqual(len(self.repo.read('Job History')), 2)

    def test_scoped_retry_does_not_replay_other_durable_work(self):
        self.engine.resume_local(self.cycle, fetch_workers=1, defer_sync=True)
        self.engine.fetcher = lambda *args: self.fail('saved inventory should be staged')
        self.engine.resume_local(self.cycle, sync_only=True, retry_company_ids={'C-1'})
        self.assertEqual(len(self.repo.read('Job History')), 1)
        self.assertIsNotNone(self.inbox.get(self.cycle, 'C-0'))
        self.assertIsNotNone(self.inbox.get(self.cycle, 'C-2'))

    def test_retries_preserve_no_choices_and_do_not_infer_closure_from_partial_inventory(self):
        # Establish a complete inventory containing two C-1 jobs first.
        self.calls['C-1'] = 1
        self.engine.resume_local(self.cycle, fetch_workers=1)
        jobs = [row for row in self.repo.read('Job History') if row['Company'] == company(1)['Company']]
        self.assertEqual(len(jobs), 2)
        first = next(row for row in jobs if not row['Official Job URL'].endswith('/late-job'))
        self.repo.commit([{'tab': 'Job History', 'identity': {'Job Key': first['Job Key']},
                           'values': {'Added to Opportunities?': 'No', 'Review Notes': 'User decision'}}])
        self.recover = False
        self.calls.clear()
        self.cycle = self.engine.start_cycle()
        result = self.run_scan()
        jobs = [row for row in self.repo.read('Job History') if row['Company'] == company(1)['Company']]
        self.assertEqual(len(jobs), 2)
        first = next(row for row in jobs if row['Job Key'] == first['Job Key'])
        self.assertEqual(first['Added to Opportunities?'], 'No')
        self.assertIn('User decision', first['Review Notes'])
        older = next(row for row in jobs if row['Official Job URL'].endswith('/late-job'))
        self.assertNotEqual(older['Job Status'], 'Closed')
        self.assertEqual(str(older.get('Consecutive Missing Scans') or 0), '0')
        self.assertEqual(result['run_counts']['new_jobs'], 0)
