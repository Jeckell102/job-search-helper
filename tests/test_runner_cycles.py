from pathlib import Path
import tempfile
import unittest

from job_search_helper.engine import State
from job_search_helper.runner import active_inbox_cycles
from job_search_helper.runner import _print_run_status
from contextlib import redirect_stdout
from io import StringIO


class DummyInbox:
    def cycles(self, include_blocked=False):
        return ["CYC-DONE", "CYC-ACTIVE", "CYC-ORPHAN"]


class RunnerCycleSelectionTests(unittest.TestCase):
    def test_summary_separates_scrape_completion_from_global_review_backlog(self):
        output = StringIO()
        with redirect_stdout(output):
            _print_run_status({'cycle_id': 'CYC', 'status': 'In Progress', 'pending_reviews': 19672,
                'manual_review': 242, 'companies': {'C-1': {'stage': 'queued'}, 'C-2': {'stage': 'complete'}}})
        self.assertIn('cycle_status=In Progress', output.getvalue())
        self.assertIn('"queued": 1', output.getvalue())
        self.assertIn('Job History (all cycles)', output.getvalue())
        self.assertIn('unfinished scraping', output.getvalue())

    def test_start_ignores_blocked_inbox_work_from_completed_cycles(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = State(Path(temporary) / "state.db")
            self.addCleanup(state.close)
            state.save_cycle({
                "id": "CYC-DONE", "started_at": "2026-09-17T01:00:00+00:00",
                "status": "Complete with exceptions", "all": True, "companies": {},
            })
            state.save_cycle({
                "id": "CYC-ACTIVE", "started_at": "2026-09-17T02:00:00+00:00",
                "status": "In Progress", "all": True, "companies": {},
            })

            self.assertEqual(
                active_inbox_cycles(DummyInbox(), state),
                ["CYC-ACTIVE", "CYC-ORPHAN"],
            )




class FreshStartLifecycleTests(unittest.TestCase):
    def setUp(self):
        from job_search_helper.engine import Engine
        from job_search_helper.inbox import InventoryInbox
        from job_search_helper.repository import MemoryRepository
        from test_fetch_pool import company, inventory
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / 'state.db'
        self.state = State(self.database)
        self.addCleanup(self.state.close)
        self.repo = MemoryRepository({'Companies': [company(0), company(1)]})
        self.repo.spreadsheet_id = 'fixture'
        self.inbox = InventoryInbox(self.root / 'inventories.sqlite3', 'fixture')
        self.addCleanup(self.inbox.close)
        self.calls = []
        def fetch(source, url, cid, name):
            self.calls.append(cid)
            result = inventory(cid, name, url)
            if cid == 'C-1':
                result.status = 'partial'
                result.browser_discovery_incomplete = True
            return result
        self.engine = Engine(self.repo, self.state, inbox=self.inbox, fetcher=fetch,
                             error_log_path=self.root / 'errors.jsonl')
        self.output = StringIO()
        capture = redirect_stdout(self.output)
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def start(self, resume=False):
        from job_search_helper.runner import select_start_cycle
        cycle_id = select_start_cycle(self.engine, self.state, self.repo, self.database, resume=resume)
        result = self.engine.resume_local(cycle_id, fetch_workers=1, retry_partial=resume, retry_blocked=True)
        return cycle_id, result

    def test_repeated_start_rechecks_successes_and_partials_and_adds_new_company(self):
        from test_fetch_pool import company
        first, result = self.start()
        self.assertEqual(result['status'], 'Complete with exceptions')
        self.assertEqual(result['run_counts'], {'new_jobs': 2, 'successful': 1, 'partial': 1,
                                              'failed': 0, 'skipped': 0, 'pending': 0})
        before = self.state.cycle(first)
        self.repo.commit([{'tab': 'Companies', 'identity': {'Company ID': 'C-2'},
                           'values': company(2), 'append_if_missing': True}])
        second, result = self.start()
        self.assertNotEqual(first, second)
        self.assertEqual(self.calls, ['C-0', 'C-1', 'C-0', 'C-1', 'C-2'])
        self.assertEqual(self.state.cycle(first), before)
        self.assertEqual(result['run_counts'], {'new_jobs': 1, 'successful': 2, 'partial': 1,
                                              'failed': 0, 'skipped': 0, 'pending': 0})
        self.assertEqual(len(self.repo.read('Job History')), 3)
        rows = {row['Company ID']: row for row in self.repo.read('Companies')}
        self.assertTrue(rows['C-0']['Last Checked'])
        self.assertFalse(rows['C-1'].get('Last Checked'))
        self.assertEqual(rows['C-1']['Scan State'], 'Partial')

    def test_explicit_resume_retries_partial_without_repeating_complete(self):
        first, _ = self.start()
        self.calls.clear()
        second, result = self.start(resume=True)
        self.assertEqual(first, second)
        self.assertEqual(self.calls, ['C-1'])
        self.assertEqual(result['run_counts']['new_jobs'], 0)
        self.assertEqual(result['run_counts']['successful'], 0)
        self.assertEqual(result['run_counts']['partial'], 1)
        self.assertEqual(result['run_counts']['skipped'], 1)

    def test_fresh_start_supersedes_old_queue_without_deleting_its_payload_or_plan(self):
        from job_search_helper.engine import inventory_payload
        from test_fetch_pool import company, inventory
        old = self.engine.start_cycle()
        c = company(1)
        payload = inventory_payload(inventory('C-1', c['Company'], c['Official Careers URL']), c)
        self.inbox.save(old, 'C-1', payload)
        plan = {'operations': [{'tab': 'Companies', 'identity': {'Company ID': 'C-1'},
                                'values': {'Scan State': 'Complete'}}], 'final': {'stage': 'complete'}}
        self.inbox.save_plan(old, 'C-1', plan)
        before = self.state.cycle(old)
        new, result = self.start()
        self.assertNotEqual(old, new)
        self.assertIn(old, self.state.cycle(new)['supersedes'])
        self.assertEqual(self.state.cycle(old), before)
        self.assertEqual(self.inbox.get(old, 'C-1')[0], payload)
        self.assertEqual(self.inbox.plan(old, 'C-1'), (plan, 0))
        self.assertEqual(self.calls, ['C-0', 'C-1'])

    def test_resume_processes_durable_saved_inventory_without_fetching_it_again(self):
        from job_search_helper.engine import inventory_payload
        from test_fetch_pool import company, inventory
        old = self.engine.start_cycle()
        c = company(0)
        self.inbox.save(old, 'C-0', inventory_payload(inventory('C-0', c['Company'], c['Official Careers URL']), c))
        cycle, result = self.start(resume=True)
        self.assertEqual(cycle, old)
        self.assertEqual(self.calls, ['C-1'])
        self.assertEqual(result['run_counts']['successful'], 1)
        self.assertEqual(result['run_counts']['partial'], 1)
        self.assertEqual(result['status'], 'Complete with exceptions')

    def test_interruption_keeps_unattempted_companies_resumable(self):
        from unittest.mock import patch
        import sqlite3
        from job_search_helper.runner import select_start_cycle
        cycle = select_start_cycle(self.engine, self.state, self.repo, self.database)
        with patch.object(self.inbox, 'save', side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):
                self.engine.resume_local(cycle, fetch_workers=1)
        self.assertEqual(self.state.cycle(cycle)['status'], 'In Progress')
        self.assertFalse(self.state.cycle(cycle).get('completed_at'))
        self.calls.clear()
        resumed, result = self.start(resume=True)
        self.assertEqual(resumed, cycle)
        self.assertEqual(self.calls, ['C-0', 'C-1'])

    def test_cli_default_and_resume_are_distinct_and_sync_rejects_resume(self):
        from unittest.mock import patch
        from contextlib import redirect_stderr
        from job_search_helper import runner
        with patch.object(runner, 'run_start', return_value=0) as run:
            self.assertEqual(runner.main(['start', '--fetch-workers', '15']), 0)
            self.assertFalse(run.call_args.kwargs['resume'])
            self.assertEqual(runner.main(['start', '--resume', '--fetch-workers', '15']), 0)
            self.assertTrue(run.call_args.kwargs['resume'])
            run.reset_mock()
            with redirect_stderr(StringIO()):
                self.assertEqual(runner.main(['sync', '--resume']), 2)
            run.assert_not_called()

    def test_summary_reports_run_counts_and_leaves_zero_skipped_blank(self):
        from job_search_helper.runner import _print_run_summary
        _, result = self.start()
        self.output.truncate(0); self.output.seek(0)
        _print_run_summary(result['run_counts'])
        text = self.output.getvalue()
        self.assertIn('New jobs downloaded (new Job History rows): 2', text)
        self.assertIn('Companies successfully scanned: 1', text)
        self.assertIn('Companies partially scanned: 1', text)
        self.assertIn('Companies skipped: \n', text)
        self.assertNotIn('Companies blocked or failed:', text)

    def test_actual_runner_finishes_with_summary_and_next_start_scans_again(self):
        from unittest.mock import patch
        from job_search_helper import runner
        from job_search_helper.engine import Engine
        def make_engine(repo, state, **kwargs):
            return Engine(repo, state, fetcher=self.engine.fetcher, error_log_path=self.root / 'errors.jsonl', **kwargs)
        with patch.object(runner, '_load_environment'), \
             patch.object(runner, 'load_title_blacklist'), patch.object(runner, 'load_title_review_list'), \
             patch.object(runner, 'state_path', return_value=self.database), \
             patch.object(runner, 'get_repository', return_value=self.repo), \
             patch.object(runner, 'Engine', side_effect=make_engine), \
             patch.object(runner, '_refresh_review_queue'):
            self.assertEqual(runner.run_start(fetch_workers=1, browser_fallback=False), 0)
            self.assertTrue(self.output.getvalue().endswith('Companies skipped: \n'))
            self.output.truncate(0); self.output.seek(0)
            self.assertEqual(runner.run_start(fetch_workers=1, browser_fallback=False), 0)
        self.assertEqual(self.calls, ['C-0', 'C-1', 'C-0', 'C-1'])
        self.assertIn('New jobs downloaded (new Job History rows): 0', self.output.getvalue())
        self.assertTrue(self.output.getvalue().endswith('Companies skipped: \n'))

    def test_resume_never_falls_back_to_older_unfinished_scan(self):
        from job_search_helper.runner import resolve_cycle
        for cid, date, status in [('OLD', '2026-10-13T00:00:00+00:00', 'In Progress'),
                                  ('NEW', '2026-10-29T00:00:00+00:00', 'Complete')]:
            self.state.save_cycle({'id': cid, 'started_at': date, 'status': status, 'all': True, 'companies': {}})
        with self.assertRaisesRegex(ValueError, 'latest scan is already complete'):
            resolve_cycle(self.engine, self.state, self.repo)
        self.assertEqual(len(self.state.cycles()), 2)

    def test_resume_recovers_latest_remote_scope_and_newest_remote_supersession(self):
        from job_search_helper.runner import resolve_cycle
        from job_search_helper.engine import State, Engine
        old = self.engine.start_cycle()
        new, _ = self.start()
        empty = State()
        self.addCleanup(empty.close)
        engine = Engine(self.repo, empty)
        selected, _ = resolve_cycle(engine, empty, self.repo)
        self.assertEqual(selected, new)
        self.assertIn(old, empty.cycle(new)['supersedes'])
        self.assertEqual(set(empty.cycle(new)['companies']), {'C-0', 'C-1'})

    def test_resume_without_saved_scan_or_with_pending_fresh_request_fails_without_changes(self):
        from job_search_helper.runner import select_start_cycle
        with self.assertRaisesRegex(ValueError, 'No saved scan'):
            select_start_cycle(self.engine, self.state, self.repo, self.database, resume=True)
        request = self.root / 'next-scan.json'
        request.write_text('{"mode":"fresh-full-scan","request_id":"pending"}')
        with self.assertRaisesRegex(ValueError, 'fresh next-scan.json request is pending'):
            select_start_cycle(self.engine, self.state, self.repo, self.database, resume=True)
        self.assertTrue(request.exists())
        self.assertEqual(self.state.cycles(), [])

    def test_blocked_failures_remain_separate_from_partial_and_skipped_counts(self):
        from job_search_helper.ats import Inventory
        from job_search_helper.runner import _print_run_summary
        self.engine.fetcher = lambda *args: Inventory('blocked', reason='Access denied')
        _, result = self.start()
        self.assertEqual(result['status'], 'Complete with exceptions')
        self.assertEqual(result['run_counts'], {'new_jobs': 0, 'successful': 0, 'partial': 0,
                                              'skipped': 0, 'failed': 2, 'pending': 0})
        _print_run_summary(result['run_counts'])
        self.assertIn('Companies blocked or failed: 2', self.output.getvalue())
        self.assertFalse(any(row.get('Last Checked') for row in self.repo.read('Companies')))


if __name__ == '__main__':
    unittest.main()
