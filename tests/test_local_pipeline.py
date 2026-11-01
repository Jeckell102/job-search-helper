"""Acceptance tests for local planning and multi-company sync; no network."""
from contextlib import redirect_stdout
import copy
from io import StringIO
import json
from pathlib import Path
import re
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from job_search_helper.core import job_key
from job_search_helper.engine import Engine, State, inventory_payload
from job_search_helper.inbox import InventoryInbox
from job_search_helper.local_pipeline import LocalPipeline
from job_search_helper.repository import GoogleRepository, RepositoryError
from sheets_fixture import RangeSheets
from test_fetch_pool import company, inventory


class LocalPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = State(self.root / 'state.db')
        self.addCleanup(self.state.close)
        self.inbox = InventoryInbox(self.root / 'inbox.db', 'fixture')
        self.addCleanup(self.inbox.close)
        self.service = RangeSheets({'Companies': [company(i) for i in range(6)]})
        self.repo = GoogleRepository(self.service, 'fixture', min_request_interval=0)
        self.calls = []
        def fetch(source, url, cid, name):
            self.calls.append(cid)
            return inventory(cid, name, url)
        self.engine = Engine(self.repo, self.state, fetcher=fetch, batch_size=200, inbox=self.inbox,
                             error_log_path=self.root / 'errors.jsonl')
        capture = redirect_stdout(StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)
        self.cycle = self.engine.start_cycle([f'C-{i}' for i in range(6)])

    def defer(self):
        self.engine.resume_local(self.cycle, fetch_workers=2, assignment_window=2, defer_sync=True)
        self.engine.fetcher = lambda *args: self.fail('saved company was fetched again')

    def restart(self):
        other = InventoryInbox(self.root / 'inbox.db', 'fixture')
        self.addCleanup(other.close)
        state = State(self.root / 'state.db')
        self.addCleanup(state.close)
        repo = GoogleRepository(self.service, 'fixture', min_request_interval=0)
        return Engine(repo, state, inbox=other, batch_size=200,
                      fetcher=lambda *args: self.fail('sync fetched'), error_log_path=self.root / 'errors.jsonl')

    def assert_synced(self, engine=None, count=6):
        engine = engine or self.engine
        rows = engine.repo.read('Job History')
        self.assertEqual(len(rows), count)
        self.assertEqual(len({r['Job Key'] for r in rows}), count)
        self.assertEqual(engine.inbox.cycles(), [])

    def test_small_companies_share_atomic_write_and_counts_only_confirmed_rows(self):
        self.defer()
        before = len(self.service.batches)
        self.engine.resume_local(self.cycle, sync_only=True)
        self.assert_synced()
        # One consolidated changes write + cycle updates, not 6 independent job writes.
        self.assertLessEqual(len(self.service.batches) - before, 3)
        self.assertEqual(self.engine._dashboard.new_job_count, 6)
        self.assertEqual(self.engine._dashboard.local_job_count, 6)
        self.assertEqual(self.engine._dashboard.local_queue_count, 0)
        self.assertEqual(self.engine._dashboard.sync_plan_count, 0)
        self.assertEqual(self.state.cycle(self.cycle)['status'], 'Complete')

    def test_browser_pending_details_finish_with_exceptions_and_explicit_retry_skips_successes(self):
        from job_search_helper.ats import Inventory
        from job_search_helper.browser_progress import BrowserProgress
        from job_search_helper.browser_scraper import with_browser_fallback
        initial = inventory('C-0', 'Company 0', company(0)['Official Careers URL'])
        initial.status = 'partial'
        initial.browser_pending_urls = ['https://example.com/jobs/pending']
        self.engine.fetcher = lambda source, url, cid, name: initial if cid == 'C-0' else inventory(cid, name, url)
        self.engine.resume_local(self.cycle, fetch_workers=2)
        current = self.state.cycle(self.cycle)
        self.assertEqual(current['status'], 'Complete with exceptions')
        self.assertEqual(current['companies']['C-0']['stage'], 'partial')
        self.assertIsNone(self.inbox.get(self.cycle, 'C-0'))
        # Refetch is limited to the unfinished company; its durable browser
        # progress is supplied through the normal worker path.
        calls = []
        def browser(ats, url, cid, name, *, progress):
            calls.append(cid)
            self.assertIsInstance(progress, BrowserProgress)
            self.assertEqual(progress.scope[:2], (self.cycle, 'C-0'))
            return Inventory('partial', initial.jobs)
        self.engine.fetcher = with_browser_fallback(lambda *args: Inventory('partial'))
        with patch('job_search_helper.browser_scraper.fetch_browser_inventory', side_effect=browser):
            self.engine.resume_local(self.cycle, fetch_workers=2, retry_partial=True)
        self.assertEqual(calls, ['C-0'])
        self.assertEqual(self.state.cycle(self.cycle)['companies']['C-0']['stage'], 'partial')
        self.assertEqual(len(self.repo.read('Job History')), 6)

    def test_sync_uses_narrow_company_control_refreshes(self):
        self.defer()
        pipeline = LocalPipeline(self.engine, self.cycle)
        before = len(self.service.get_calls)
        pipeline.run(sync_only=True)
        ranges = [r for call in self.service.get_calls[before:] for r in call.get('ranges', [])]
        company_ranges = [r for r in ranges if r.startswith("'Companies'!")]
        self.assertTrue(company_ranges)
        self.assertFalse(any(re.search(r"!A1:[A-Z]+[2-9][0-9]*$", r) for r in company_ranges))

    def test_deferred_dashboard_shows_saved_local_queue(self):
        self.defer()
        self.assertEqual(self.engine._dashboard.local_queue_count, 6)
        self.assertEqual(self.engine._dashboard.sync_plan_count, 0)

    def test_workers_fetch_past_assignment_window_while_upload_is_blocked(self):
        uploading, all_returned = Event(), Event()
        original = self.repo.commit
        def fetch(source, url, cid, name):
            if cid != 'C-0':
                self.assertTrue(uploading.wait(5))
            return inventory(cid, name, url)
        save = self.inbox.save
        def persist(cycle, cid, payload):
            save(cycle, cid, payload)
            if cid == 'C-5':
                all_returned.set()
        def commit(operations):
            if any(op['tab'] == 'Job History' for op in operations):
                uploading.set()
                self.assertTrue(all_returned.wait(5), 'workers stalled behind Sheets')
            return original(operations)
        self.engine.fetcher = fetch
        self.engine.batch_size = 2
        with patch.object(self.inbox, 'save', side_effect=persist), patch.object(self.repo, 'commit', side_effect=commit):
            self.engine.resume_local(self.cycle, fetch_workers=2, assignment_window=1)
        self.assert_synced()

    def test_applied_write_lost_response_is_retained_and_explicit_replay_is_unique(self):
        self.defer()
        commit = self.repo.commit
        lost = False
        def write(operations):
            nonlocal lost
            if any(op['tab'] == 'Job History' for op in operations) and not lost:
                lost = True
                self.service.lose_response = True
            return commit(operations)
        with patch.object(self.repo, 'commit', side_effect=write):
            self.engine.resume_local(self.cycle, sync_only=True)
        self.assertEqual(self.engine._dashboard.new_job_count, 0)
        self.assertEqual(len(self.repo.read('Job History')), 6)
        for cid in self.inbox.pending(self.cycle, include_blocked=True):
            self.assertTrue(self.inbox.get(self.cycle, cid)[1])
            self.assertEqual(self.inbox.plan(self.cycle, cid)[1], 0)
        restarted = self.restart()
        restarted.resume_local(self.cycle, sync_only=True, retry_blocked=True)
        self.assert_synced(restarted)
        self.assertEqual(restarted._dashboard.new_job_count, 0)

    def test_interrupt_after_write_before_cursor_commit_survives_reopen(self):
        self.defer()
        with patch.object(self.inbox, 'advance', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.engine.resume_local(self.cycle, sync_only=True)
        restarted = self.restart()
        restarted.resume_local(self.cycle, sync_only=True)
        self.assert_synced(restarted)

    def test_interrupt_after_cursor_commit_before_company_checkpoint(self):
        self.defer()
        self.engine.checkpoint_hook = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.engine.resume_local(self.cycle, sync_only=True)
        restarted = self.restart()
        before = len(self.service.batches)
        restarted.resume_local(self.cycle, sync_only=True)
        self.assert_synced(restarted)
        self.assertEqual(len(self.service.batches) - before, 1)  # cycle status only

    def test_fresh_manual_no_and_formula_conflict_isolate_company(self):
        key = job_key('C-0', 'Greenhouse', '1', company(0)['Official Careers URL'] + '/jobs/1')
        self.service.set_cell('Job History', 1, 'Job Key', key)
        self.service.set_cell('Job History', 1, 'Company', 'Company 0')
        self.service.set_cell('Job History', 1, 'Official Job URL', company(0)['Official Careers URL'] + '/jobs/1')
        self.service.set_cell('Job History', 1, 'Added to Opportunities?', 'Pending')
        self.defer()
        original = LocalPipeline.flush
        def edited(pipeline):
            self.service.set_cell('Job History', 1, 'Added to Opportunities?', 'No')
            self.service.set_cell('Job History', 1, 'Review Notes', 'My exclusion')
            self.service.set_cell('Job History', 1, 'Job Title', cell={
                'userEnteredValue': {'formulaValue': '="My formula"'},
                'effectiveValue': {'stringValue': 'My formula'}})
            return original(pipeline)
        with patch.object(LocalPipeline, 'flush', edited):
            self.engine.resume_local(self.cycle, sync_only=True)
        rows = self.repo.read('Job History')
        manual = next(r for r in rows if r['Company'] == 'Company 0')
        self.assertEqual(manual['Added to Opportunities?'], 'No')
        self.assertEqual(manual['Review Notes'], 'My exclusion')
        self.assertEqual(manual['Job Title'], 'My formula')
        self.assertEqual(len(rows), 6)
        self.assertTrue(self.inbox.get(self.cycle, 'C-0')[1])
        self.assertEqual(self.engine._dashboard.new_job_count, 5)

    def test_pause_after_planning_and_between_uploads_preserves_inventory(self):
        self.defer()
        self.engine.batch_size = 2
        commit = self.repo.commit
        def pause(operations):
            result = commit(operations)
            if any(op['tab'] == 'Job History' for op in operations):
                self.service.set_cell('Companies', 6, 'Company Status', 'Paused')
            return result
        with patch.object(self.repo, 'commit', side_effect=pause):
            self.engine.resume_local(self.cycle, sync_only=True)
        self.assertTrue(self.inbox.get(self.cycle, 'C-5')[1])
        self.assertEqual(len(self.repo.read('Job History')), 5)

    def test_company_planning_failure_logs_and_continues(self):
        self.defer()
        stage = self.engine._stage_posting
        def broken(cycle, comp, posting):
            if comp['Company ID'] == 'C-0':
                raise ValueError('fixture invalid posting')
            return stage(cycle, comp, posting)
        with patch.object(self.engine, '_stage_posting', side_effect=broken):
            self.engine.resume_local(self.cycle, sync_only=True)
        self.assertEqual(len(self.repo.read('Job History')), 5)
        self.assertTrue(self.inbox.get(self.cycle, 'C-0')[1])
        self.assertIn('fixture invalid posting', (self.root / 'errors.jsonl').read_text())

    def test_large_payload_preflight_splits_without_weakening_api_backoff(self):
        self.defer()
        commit = self.repo.commit
        calls = []
        def limited(ops):
            if any(op['tab'] == 'Job History' for op in ops):
                calls.append(len(ops))
                if len(ops) > 1:
                    raise RepositoryError('Planned batch exceeds the safety threshold. No write attempted')
            return commit(ops)
        with patch.object(self.repo, 'commit', side_effect=limited):
            self.engine.resume_local(self.cycle, sync_only=True)
        self.assert_synced()
        self.assertIn(1, calls)

    def test_plan_saved_before_checkpoint_is_found_after_restart(self):
        self.defer()
        save = self.inbox.save_plan
        def interrupt(*args):
            save(*args)
            raise KeyboardInterrupt()
        with patch.object(self.inbox, 'save_plan', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.engine.resume_local(self.cycle, sync_only=True)
        self.assertEqual(self.repo.read('Job History'), [])
        restarted = self.restart()
        restarted.resume_local(self.cycle, sync_only=True)
        self.assert_synced(restarted)

    def test_defer_then_sync_never_fetches_and_default_backoff_unchanged(self):
        self.defer()
        self.assertEqual(len(self.calls), 6)
        self.assertEqual(self.repo.read('Job History'), [])
        self.engine.resume_local(self.cycle, sync_only=True)
        self.assert_synced()

    def test_blacklist_and_retained_blocked_source(self):
        def fetch(source, url, cid, name):
            if cid == 'C-0':
                return Inventory('failed', reason='source unavailable')
            inv = inventory(cid, name, url)
            if cid == 'C-1':
                inv.jobs[0]['title'] = 'Principal Software Engineer'
            return inv
        from job_search_helper.ats import Inventory
        self.engine.fetcher = fetch
        self.engine.resume_local(self.cycle)
        self.assertEqual(len(self.repo.read('Job History')), 4)
        self.assertTrue(self.inbox.get(self.cycle, 'C-0')[1])
        self.assertIn('source unavailable', (self.root / 'errors.jsonl').read_text())
        self.assertEqual(self.state.cycle(self.cycle)['status'], 'Complete with exceptions')

    def test_fresh_board_edit_or_external_claim_blocks_upload(self):
        self.defer()
        original = LocalPipeline.flush
        def edited(pipeline):
            self.service.set_cell('Companies', 1, 'Official Careers URL', 'https://different.test')
            self.service.set_cell('Companies', 2, 'Claim Token', 'owner')
            return original(pipeline)
        with patch.object(LocalPipeline, 'flush', edited):
            self.engine.resume_local(self.cycle, sync_only=True)
        self.assertEqual(len(self.repo.read('Job History')), 4)
        self.assertTrue(self.inbox.get(self.cycle, 'C-0')[1])
        self.assertTrue(self.inbox.get(self.cycle, 'C-1')[1])

    def test_explicit_retry_replans_conflict_without_overwriting_manual_no(self):
        key = job_key('C-0', 'Greenhouse', '1', company(0)['Official Careers URL'] + '/jobs/1')
        self.service.set_cell('Job History', 1, 'Job Key', key)
        self.service.set_cell('Job History', 1, 'Company', 'Company 0')
        self.service.set_cell('Job History', 1, 'Official Job URL', company(0)['Official Careers URL'] + '/jobs/1')
        self.service.set_cell('Job History', 1, 'Added to Opportunities?', 'Pending')
        self.defer()
        original = LocalPipeline.flush
        def edited(pipeline):
            self.service.set_cell('Job History', 1, 'Added to Opportunities?', 'No')
            self.service.set_cell('Job History', 1, 'Review Notes', 'Manual exclusion')
            return original(pipeline)
        with patch.object(LocalPipeline, 'flush', edited):
            self.engine.resume_local(self.cycle, sync_only=True)
        self.assertIsNone(self.inbox.plan(self.cycle, 'C-0'))
        restarted = self.restart()
        restarted.resume_local(self.cycle, sync_only=True, retry_blocked=True)
        self.assert_synced(restarted)
        row = next(r for r in restarted.repo.read('Job History') if r['Company'] == 'Company 0')
        self.assertEqual(row['Added to Opportunities?'], 'No')
        self.assertEqual(row['Review Notes'], 'Manual exclusion')

    def test_retry_blocked_saved_inventory_migrates_duplicate_legacy_keys_without_refetch(self):
        legacy_key = 'company0|url:https://boards.greenhouse.io/company0'
        for row, identifier in enumerate(('1', '2', '3'), 1):
            for header, value in {
                'Company': 'Company 0',
                'Job Title': f'Legacy job {identifier}',
                'Job Key': legacy_key,
                'Requisition ID': identifier,
                'Official Job URL': company(0)['Official Careers URL'] + f'/jobs/{identifier}',
            }.items():
                self.service.set_cell('Job History', row, header, value)

        self.defer()
        self.inbox.block(self.cycle, 'C-0')
        self.engine.resume_local(self.cycle, sync_only=True)
        self.assertTrue(self.inbox.get(self.cycle, 'C-0')[1])

        restarted = self.restart()
        migrated_operations = []
        commit = restarted.repo.commit
        def capture_migration(operations):
            migrated_operations.extend(copy.deepcopy([
                operation for operation in operations
                if operation['tab'] == 'Job History' and 'Job Key' in operation.get('expected', {})
            ]))
            return commit(operations)
        with patch.object(restarted.repo, 'commit', side_effect=capture_migration):
            restarted.resume_local(self.cycle, sync_only=True, retry_blocked=True)

        company_rows = [row for row in restarted.repo.read('Job History')
                        if row['Company'] == 'Company 0']
        migrated = next(row for row in company_rows if row['Requisition ID'] == '1')
        self.assertEqual(migrated['Job Key'], 'c-0:greenhouse:1')
        self.assertEqual(migrated['Prior Job Key'], legacy_key)
        self.assertEqual(len(company_rows), 3)
        self.assertNotIn('C-0', restarted.inbox.pending(self.cycle, include_blocked=True))
        self.assertEqual(self.calls.count('C-0'), 1)
        self.assertEqual(len(migrated_operations), 1)
        self.assertEqual(migrated_operations[0]['expected']['Job Key'], legacy_key)

    def test_absence_replay_increments_once_and_preserves_review_lock(self):
        from job_search_helper.core import pack_snapshot
        # No fetched job will match this old posting.
        for row in (1, 2):
            for header, value in {'Company': 'Company 0', 'Job Key': f'old-{row}',
                'Official Job URL': f'https://old.test/{row}', 'Consecutive Missing Scans': '0',
                'Current Snapshot': pack_snapshot({'v': 1, 'evaluations': [], 'inventory_source': company(0)['Official Careers URL']}),
                'Review Status': 'In Progress' if row == 2 else 'Reviewed'}.items():
                self.service.set_cell('Job History', row, header, value)
        self.defer()
        with patch.object(self.inbox, 'advance', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.engine.resume_local(self.cycle, sync_only=True)
        restarted = self.restart()
        restarted.resume_local(self.cycle, sync_only=True)
        rows = {r['Job Key']: r for r in restarted.repo.read('Job History')}
        self.assertEqual(str(rows['old-1']['Consecutive Missing Scans']), '1')
        self.assertEqual(str(rows['old-2']['Consecutive Missing Scans']), '0')
        self.assertEqual(rows['old-2']['Review Status'], 'In Progress')

    def test_durable_save_failure_stops_without_marking_company_complete(self):
        import sqlite3
        with patch.object(self.inbox, 'save', side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):
                self.engine.resume_local(self.cycle, assignment_window=1)
        self.assertEqual(self.repo.read('Job History'), [])
        self.assertTrue(all(item['stage'] == 'queued' for item in self.state.cycle(self.cycle)['companies'].values()))


    def test_sheet_queued_retries_locally_blocked_fetch_without_retry_flag(self):
        from job_search_helper.ats import Inventory

        attempts = []
        def fetch(source, url, cid, name):
            attempts.append(cid)
            if cid == 'C-0' and attempts.count('C-0') == 1:
                return Inventory('blocked', reason='one-time browser check')
            return inventory(cid, name, url)

        self.engine.fetcher = fetch
        self.engine.resume_local(self.cycle, fetch_workers=2, assignment_window=2)
        self.assertTrue(self.inbox.get(self.cycle, 'C-0')[1])
        self.assertEqual(attempts.count('C-0'), 1)

        self.service.set_cell('Companies', 1, 'Scan State', 'Queued')
        self.service.set_cell('Companies', 1, 'Automatic Retry?', '')
        restarted = self.restart()
        retry_attempts = []
        def retry_fetch(source, url, cid, name):
            retry_attempts.append(cid)
            return inventory(cid, name, url)
        restarted.fetcher = retry_fetch
        restarted.resume_local(self.cycle, fetch_workers=2, assignment_window=2)

        self.assertIn('C-0', retry_attempts)
        self.assertIsNone(restarted.inbox.get(self.cycle, 'C-0'))
        self.assertEqual(len(restarted.repo.read('Job History')), 6)

    def test_sheet_queued_unblocks_saved_write_payload_without_refetch(self):
        self.defer()
        self.inbox.block(self.cycle, 'C-0')
        cycle = self.state.cycle(self.cycle)
        cycle['companies']['C-0']['stage'] = 'failed'
        self.state.save_cycle(cycle)
        self.service.set_cell('Companies', 1, 'Scan State', 'Queued')
        restarted = self.restart()
        restarted.resume_local(self.cycle, sync_only=True)
        self.assertEqual(len(restarted.repo.read('Job History')), 6)
        self.assertIsNone(restarted.inbox.get(self.cycle, 'C-0'))

    def test_retry_discards_stale_textron_parent_board_payload_and_refetches(self):
        from job_search_helper.ats import Inventory

        careers = 'https://www.textronsystems.com/careers/apply-today'
        self.service.set_cell('Companies', 1, 'Official Careers URL', careers)
        self.service.set_cell('Companies', 1, 'ATS / Source', 'Taleo')
        stale = Inventory('partial', [inventory('C-0', 'Company 0', careers).jobs[0]],
                          'old shared-board partial',
                          'https://textron.taleo.net/careersection/textron/jobsearch.ftl', 'Taleo')
        self.inbox.save(self.cycle, 'C-0', inventory_payload(stale, {
            'Official Careers URL': careers,
        }))
        self.inbox.block(self.cycle, 'C-0')

        attempts = []
        def refetch(source, url, cid, name):
            attempts.append(cid)
            return inventory(cid, name, url)
        self.engine.fetcher = refetch
        self.engine.resume_local(self.cycle, retry_blocked=True, fetch_workers=2)

        self.assertIn('C-0', attempts)
        self.assertIsNone(self.inbox.get(self.cycle, 'C-0'))


    def test_full_description_is_written_to_evidence_tab_not_history(self):
        long_description = 'Integrate customer hardware and train operators. ' * 200
        def fetch(source, url, cid, name):
            inv = inventory(cid, name, url)
            inv.jobs[0]['description'] = long_description
            return inv
        self.engine.fetcher = fetch
        self.engine.resume_local(self.cycle, fetch_workers=2, assignment_window=2)

        history = self.repo.read('Job History')
        evidence = self.repo.read('Job Evidence')
        self.assertEqual(len(history), 6)
        self.assertEqual(len(evidence), 6)
        self.assertTrue(history[0]['Job Description'].startswith('See Job Evidence tab:'))
        self.assertNotIn('Integrate customer hardware', history[0]['Job Description'])
        self.assertEqual(evidence[0]['Job Key'], history[0]['Job Key'])
        self.assertEqual(evidence[0]['Source Hash'], history[0]['Source Hash'])
        self.assertIn('Integrate customer hardware', evidence[0]['Job Description'])

    def test_sync_interval_flushes_partial_batch_while_fetch_is_running(self):
        from job_search_helper.ats import Inventory
        upload_started = Event()
        commit = self.repo.commit
        def fetch(source, url, cid, name):
            if cid != 'C-0':
                self.assertTrue(upload_started.wait(5))
            return inventory(cid, name, url)
        def upload(ops):
            if any(op['tab'] == 'Job History' for op in ops):
                upload_started.set()
            return commit(ops)
        self.engine.fetcher = fetch
        with patch.object(self.repo, 'commit', side_effect=upload):
            self.engine.resume_local(self.cycle, sync_interval=1, fetch_workers=2)
        self.assert_synced()

    def test_manual_opportunity_rejection_preserves_cells_and_other_companies(self):
        key = job_key('C-0', 'Greenhouse', '1', company(0)['Official Careers URL'] + '/jobs/1')
        self.service.set_cell('Job History', 1, 'Job Key', key)
        self.service.set_cell('Job History', 1, 'Company', 'Company 0')
        self.service.set_cell('Job History', 1, 'Official Job URL', company(0)['Official Careers URL'] + '/jobs/1')
        self.service.set_cell('Job History', 1, 'Added to Opportunities?', 'Pending')
        self.defer()
        original = LocalPipeline.flush
        def invalid(pipeline):
            self.service.set_cell('Job History', 1, 'Added to Opportunities?', 'No')
            return original(pipeline)
        with patch.object(LocalPipeline, 'flush', invalid):
            self.engine.resume_local(self.cycle, sync_only=True)
        self.assertEqual(self.engine._dashboard.new_job_count, 5)
        self.assertTrue(self.inbox.get(self.cycle, 'C-0')[1])
        row = next(r for r in self.repo.read('Job History') if r['Company'] == 'Company 0')
        self.assertEqual(row['Added to Opportunities?'], 'No')

    def test_sync_interval_cli_and_validation(self):
        from job_search_helper import runner
        with patch.object(runner, 'run_start', return_value=0) as run:
            self.assertEqual(runner.main(['start', '--sync-interval', '120']), 0)
            self.assertEqual(run.call_args.kwargs['sync_interval'], 120)
        with self.assertRaises(ValueError):
            self.engine.resume_local(self.cycle, sync_interval=0)


if __name__ == '__main__':
    unittest.main()
