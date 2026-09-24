"""Acceptance tests for local planning and multi-company sync; no network."""
from contextlib import redirect_stdout
import copy
from io import StringIO
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

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
        self.assertEqual(self.state.cycle(self.cycle)['status'], 'Complete')

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
        self.defer()
        original = LocalPipeline.flush
        def edited(pipeline):
            # Add a row under the planned key after the planning snapshot.
            plan = self.inbox.plan(self.cycle, 'C-0')[0]
            history_op = next(op for op in plan['operations'] if op['tab'] == 'Job History')
            self.service.set_cell('Job History', 1, 'Job Key', history_op['identity']['Job Key'])
            self.service.set_cell('Job History', 1, 'Company', 'Company 0')
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
        self.defer()
        original = LocalPipeline.flush
        def edited(pipeline):
            op = self.inbox.plan(self.cycle, 'C-0')[0]['operations'][0]
            self.service.set_cell('Job History', 1, 'Job Key', op['identity']['Job Key'])
            self.service.set_cell('Job History', 1, 'Company', 'Company 0')
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

    def test_formula_rejection_preserves_cells_and_other_companies(self):
        self.defer()
        original = LocalPipeline.flush
        def invalid(pipeline):
            op = self.inbox.plan(self.cycle, 'C-0')[0]['operations'][0]
            self.service.set_cell('Job History', 1, 'Job Key', op['identity']['Job Key'])
            self.service.set_cell('Job History', 1, 'Company', 'Company 0')
            self.service.set_cell('Job History', 1, 'Job Title', cell={
                'userEnteredValue': {'formulaValue': '=1'}, 'effectiveValue': {'numberValue': 1}})
            return original(pipeline)
        with patch.object(LocalPipeline, 'flush', invalid):
            self.engine.resume_local(self.cycle, sync_only=True)
        self.assertEqual(self.engine._dashboard.new_job_count, 5)
        self.assertTrue(self.inbox.get(self.cycle, 'C-0')[1])
        col = self.service.schemas['Job History'].index('Job Title')
        self.assertEqual(self.service.sheet('Job History')['data'][0]['rowData'][1]['values'][col]['userEnteredValue'], {'formulaValue': '=1'})

    def test_sync_interval_cli_and_validation(self):
        from job_search_helper import runner
        with patch.object(runner, 'run_start', return_value=0) as run:
            self.assertEqual(runner.main(['start', '--sync-interval', '120']), 0)
            self.assertEqual(run.call_args.kwargs['sync_interval'], 120)
        with self.assertRaises(ValueError):
            self.engine.resume_local(self.cycle, sync_interval=0)


if __name__ == '__main__':
    unittest.main()
