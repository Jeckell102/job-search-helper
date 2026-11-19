import copy
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from job_search_helper.batching import PlanningRepository
from job_search_helper.engine import Engine, State, inventory_payload
from job_search_helper.inbox import InventoryInbox
from job_search_helper.publication_receipts import LOCAL_COMMITTED, receipt, record_fingerprints
from job_search_helper.repository import GoogleRepository, RepositoryError, SCHEMAS
from sheets_fixture import RangeSheets
from test_fetch_pool import company, inventory


class DurablePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = State(self.root / 'state.db')
        self.addCleanup(self.state.close)
        self.inbox = InventoryInbox(self.root / 'inbox.db', 'fixture')
        self.addCleanup(self.inbox.close)
        self.service = RangeSheets({'Companies': [company(i) for i in range(4)]})
        self.repo = GoogleRepository(self.service, 'fixture', min_request_interval=0)
        self.fetches = []
        def fetch(source, url, cid, name):
            self.fetches.append(cid)
            return inventory(cid, name, url)
        self.engine = Engine(self.repo, self.state, fetcher=fetch, batch_size=2, inbox=self.inbox,
                             error_log_path=self.root / 'errors.jsonl')
        capture = redirect_stdout(StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)
        self.cycle = self.engine.start_cycle([f'C-{i}' for i in range(4)])

    def company_receipt(self, company_id, inbox=None):
        inbox = inbox or self.inbox
        rows = inbox.connection.execute('SELECT binding FROM publication_receipts').fetchall()
        bindings = [json.loads(row[0]) for row in rows]
        binding = next(item for item in bindings if item['company_id'] == company_id)
        return receipt(inbox.connection, binding)

    def test_frozen_plan_and_local_receipt_commit_in_one_sqlite_transaction(self):
        payload = inventory_payload(inventory('C-0', 'Company 0', company(0)['Official Careers URL']), company(0))
        self.inbox.save(self.cycle, 'C-0', payload)
        plan = {'operations': [{'tab': 'Companies', 'identity': {'Company ID': 'C-0'},
                                'values': {'Scan State': 'In Progress'}}], 'final': {}}
        binding = {'request_id': self.cycle, 'company_id': 'C-0',
                   'source_revision': 'source-fixture', 'release_id': 'release-fixture'}
        details = {'binding': binding, 'records': record_fingerprints(plan['operations']),
                   'schedule': {'boundary': 'idle', 'enqueued_at': payload['fetched_at']}, 'timestamp': 't1'}
        self.inbox.save_plan(self.cycle, 'C-0', plan, receipt=details)
        self.assertIsNotNone(self.inbox.plan(self.cycle, 'C-0'))
        self.assertEqual(receipt(self.inbox.connection, binding)['state'], LOCAL_COMMITTED)

    def test_receipt_write_exception_rolls_back_the_frozen_plan_insert(self):
        payload = inventory_payload(inventory('C-0', 'Company 0', company(0)['Official Careers URL']), company(0))
        self.inbox.save(self.cycle, 'C-0', payload)
        plan = {'operations': [{'tab': 'Companies', 'identity': {'Company ID': 'C-0'},
                                'values': {'Scan State': 'In Progress'}}], 'final': {}}
        binding = {'request_id': self.cycle, 'company_id': 'C-0',
                   'source_revision': 'source-fixture', 'release_id': 'receipt-write-failure'}
        details = {'binding': binding, 'records': record_fingerprints(plan['operations']),
                   'schedule': {'boundary': 'idle', 'enqueued_at': payload['fetched_at']}, 'timestamp': 't1'}
        with patch('job_search_helper.inbox.publication_receipts.local_committed',
                   side_effect=OSError('injected receipt disk failure')):
            with self.assertRaisesRegex(OSError, 'receipt disk failure'):
                self.inbox.save_plan(self.cycle, 'C-0', plan, receipt=details)
        self.assertIsNone(self.inbox.plan(self.cycle, 'C-0'))
        self.assertIsNone(receipt(self.inbox.connection, binding))

    def test_receipt_uses_authoritative_cycle_source_revision_when_available(self):
        cycle = self.state.cycle(self.cycle)
        cycle['source_revision'] = 'immutable-company-source-rev-7'
        self.state.save_cycle(cycle)
        self.engine.resume_local(self.cycle, defer_sync=True)
        self.engine.resume_local(self.cycle, sync_only=True)
        saved = self.company_receipt('C-0')
        self.assertEqual(saved['binding']['source_revision'], 'immutable-company-source-rev-7')
        self.assertEqual(saved['binding']['source_revision_origin'], 'cycle')

    def test_deferred_sync_does_not_refetch_and_releases_acknowledged_data(self):
        self.engine.resume_parallel(self.cycle, fetch_workers=2, assignment_window=2, defer_sync=True)
        self.assertEqual(len(self.fetches), 4)
        self.assertEqual(self.repo.read('Job History'), [])
        self.assertEqual(self.inbox.cycles(), [self.cycle])
        self.engine.fetcher = lambda *args: self.fail('sync fetched a company')
        self.engine.resume_parallel(self.cycle, sync_only=True)
        self.assertEqual(len(self.repo.read('Job History')), 4)
        self.assertEqual(self.inbox.cycles(), [])

    def test_inventory_survives_close_reopen_before_control_checkpoint(self):
        payload = inventory_payload(inventory('C-0', 'Company 0', company(0)['Official Careers URL']), company(0))
        self.inbox.save(self.cycle, 'C-0', payload)
        # New process/connection sees it even though cycle still says queued.
        other = InventoryInbox(self.root / 'inbox.db', 'fixture')
        self.addCleanup(other.close)
        self.engine.inbox = other
        self.engine.fetcher = lambda *args: self.fail('durable company was refetched')
        self.engine.resume_parallel(self.cycle, sync_only=True)
        self.assertEqual(len(self.repo.read('Job History')), 1)
        self.assertEqual(other.cycles(), [])

    def test_destination_binding_and_original_inventory_immutable(self):
        self.inbox.save(self.cycle, 'C-0', {'jobs': [{'title': 'original'}]})
        self.inbox.save(self.cycle, 'C-0', {'jobs': [{'title': 'replacement'}]})
        self.assertEqual(self.inbox.get(self.cycle, 'C-0')[0]['jobs'][0]['title'], 'original')
        with self.assertRaises(ValueError):
            InventoryInbox(self.root / 'inbox.db', 'different-destination')

    def test_lost_write_response_keeps_inventory_and_retry_is_idempotent(self):
        self.engine.resume_parallel(self.cycle, defer_sync=True)
        original = self.repo.commit
        failed = [False]
        def commit(operations):
            if any(op['tab'] == 'Job History' for op in operations) and not failed[0]:
                failed[0] = True
                self.service.lose_response = True
            return original(operations)
        with patch.object(self.repo, 'commit', side_effect=commit):
            self.engine.resume_parallel(self.cycle, sync_only=True)
        self.assertIsNotNone(self.inbox.get(self.cycle, 'C-0'))
        self.engine.resume_parallel(self.cycle, sync_only=True, retry_blocked=True)
        rows = self.repo.read('Job History')
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({r['Job Key'] for r in rows}), 4)
        self.assertEqual(self.inbox.cycles(include_blocked=True), [])

    def test_workers_persist_results_and_take_assignments_during_write(self):
        saving = Event()
        returned = Event()
        def fetch(source, url, cid, name):
            if cid != 'C-0':
                self.assertTrue(saving.wait(5))
            return inventory(cid, name, url)
        self.engine.fetcher = fetch
        original = self.inbox.save
        def save(cycle, cid, payload):
            original(cycle, cid, payload)
            if cid == 'C-3':
                returned.set()
        original_stage = self.engine._stage_inventory
        def stage(*args, **kwargs):
            saving.set()
            self.assertTrue(returned.wait(5), 'writer blocked worker handoff')
            self.assertIsNotNone(self.inbox.get(self.cycle, 'C-3'))
            return original_stage(*args, **kwargs)
        with patch.object(self.inbox, 'save', side_effect=save), patch.object(self.engine, '_stage_inventory', side_effect=stage):
            self.engine.resume_parallel(self.cycle, fetch_workers=2, assignment_window=4)
        self.assertEqual(len(self.repo.read('Job History')), 4)

    def test_interrupt_after_remote_ack_before_checkpoint_replays_saved_payload(self):
        self.engine.resume_parallel(self.cycle, defer_sync=True)
        with patch.object(self.state, 'apply_buffer', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.engine.resume_parallel(self.cycle, sync_only=True)
        self.assertEqual(self.state.cycle(self.cycle)['companies']['C-0'].get('next_job_index', 0), 0)
        self.assertIsNotNone(self.inbox.get(self.cycle, 'C-0'))
        restarted = Engine(GoogleRepository(self.service, 'fixture', min_request_interval=0),
                           self.state, inbox=self.inbox, error_log_path=self.root / 'errors.jsonl')
        restarted.resume_parallel(self.cycle, sync_only=True)
        rows = restarted.repo.read('Job History')
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({r['Job Key'] for r in rows}), 4)
        self.assertEqual(self.inbox.cycles(), [])

    def test_file_backed_restart_reconciles_frozen_receipt_without_duplicate_rows(self):
        self.engine.resume_local(self.cycle, defer_sync=True)
        # This is intentionally a new SQLite connection, not an in-memory
        # fixture: the receipt must survive a process boundary with its plan.
        reopened = InventoryInbox(self.root / 'inbox.db', 'fixture')
        self.addCleanup(reopened.close)
        restarted = Engine(GoogleRepository(self.service, 'fixture', min_request_interval=0), self.state,
                           inbox=reopened, error_log_path=self.root / 'errors.jsonl')
        restarted.resume_local(self.cycle, sync_only=True)
        saved = self.company_receipt('C-0', reopened)
        self.assertEqual(saved['state'], 'SYNC_CONFIRMED')
        self.assertEqual(len(restarted.repo.read('Job History')), 4)
        self.assertEqual(len({row['Job Key'] for row in restarted.repo.read('Job History')}), 4)

    def test_duplicate_resume_keeps_one_confirmed_receipt_per_frozen_company(self):
        self.engine.resume_local(self.cycle, defer_sync=True)
        self.engine.resume_local(self.cycle, sync_only=True)
        self.engine.resume_local(self.cycle, sync_only=True, retry_blocked=True)
        rows = self.inbox.connection.execute(
            'SELECT company, count(*) FROM (SELECT json_extract(binding, "$.company_id") AS company '
            'FROM publication_receipts) GROUP BY company').fetchall()
        self.assertEqual(dict(rows), {f'C-{index}': 1 for index in range(4)})
        self.assertEqual(self.company_receipt('C-0')['state'], 'SYNC_CONFIRMED')

    def test_lost_acknowledgement_is_pending_across_restart_then_confirms_after_readback(self):
        self.engine.resume_local(self.cycle, defer_sync=True)
        original = self.repo.commit
        failed = [False]
        def commit(operations):
            if not failed[0] and any(op['tab'] == 'Job History' for op in operations):
                failed[0] = True
                self.service.lose_response = True
            return original(operations)
        with patch.object(self.repo, 'commit', side_effect=commit):
            self.engine.resume_local(self.cycle, sync_only=True)
        self.assertEqual(self.company_receipt('C-0')['state'], 'SYNC_PENDING')
        reopened = InventoryInbox(self.root / 'inbox.db', 'fixture')
        self.addCleanup(reopened.close)
        restarted = Engine(GoogleRepository(self.service, 'fixture', min_request_interval=0), self.state,
                           inbox=reopened, error_log_path=self.root / 'errors.jsonl')
        restarted.resume_local(self.cycle, sync_only=True, retry_blocked=True)
        self.assertEqual(self.company_receipt('C-0', reopened)['state'], 'SYNC_CONFIRMED')
        self.assertEqual(len(restarted.repo.read('Job History')), 4)

    def test_lost_acknowledgement_never_overwrites_a_manual_choice_during_recovery(self):
        self.engine.resume_local(self.cycle, defer_sync=True)
        original = self.repo.commit
        failed = [False]
        def commit(operations):
            if not failed[0] and any(op['tab'] == 'Job History' for op in operations):
                failed[0] = True
                self.service.lose_response = True
            return original(operations)
        with patch.object(self.repo, 'commit', side_effect=commit):
            self.engine.resume_local(self.cycle, sync_only=True)
        self.service.set_cell('Job History', 1, 'Added to Opportunities?', 'No')
        self.engine.resume_local(self.cycle, sync_only=True, retry_blocked=True)
        self.assertEqual(self.repo.read('Job History')[0]['Added to Opportunities?'], 'No')
        self.assertEqual(self.company_receipt('C-0')['state'], 'SYNC_PENDING')

    def test_fresh_pause_preserves_saved_inventory_for_explicit_retry(self):
        self.engine.resume_parallel(self.cycle, defer_sync=True)
        self.service.set_cell('Companies', 1, 'Company Status', 'Paused')
        self.engine.resume_parallel(self.cycle, sync_only=True)
        self.assertEqual(len(self.repo.read('Job History')), 3)
        self.assertTrue(self.inbox.get(self.cycle, 'C-0')[1])
        self.service.set_cell('Companies', 1, 'Company Status', 'Active')
        self.engine.resume_parallel(self.cycle, sync_only=True, retry_blocked=True)
        self.assertEqual(len(self.repo.read('Job History')), 4)

    def test_missing_durable_inventory_is_never_treated_as_empty_complete_scan(self):
        cycle = self.state.cycle(self.cycle)
        cycle['companies']['C-0'].update(stage='inventory', durable_inventory=True)
        self.state.save_cycle(cycle)
        self.engine.resume_parallel(self.cycle, sync_only=True)
        self.assertEqual(self.state.cycle(self.cycle)['companies']['C-0']['stage'], 'failed')
        self.assertIn('missing', (self.root / 'errors.jsonl').read_text())

    def test_company_error_status_failure_does_not_stop_other_companies(self):
        self.engine.resume_parallel(self.cycle, defer_sync=True)
        original = self.repo.commit
        def commit(operations):
            if any(op['tab'] == 'Job History' and op.get('values', {}).get('Company') == 'Company 0'
                   for op in operations):
                raise RepositoryError('Company-specific row problem')
            if any(op['tab'] == 'Companies' and op['identity'].get('Company ID') == 'C-0'
                   and op.get('values', {}).get('Blocked Reason') for op in operations):
                raise RepositoryError('Company status formula is protected')
            return original(operations)
        with patch.object(self.repo, 'commit', side_effect=commit):
            self.engine.resume_parallel(self.cycle, sync_only=True)
        self.assertEqual(len(self.repo.read('Job History')), 3)
        self.assertTrue(self.inbox.get(self.cycle, 'C-0')[1])
        self.assertIn('recording company error', (self.root / 'errors.jsonl').read_text())

    def test_runner_sync_uses_durable_data_and_reports_numeric_metrics(self):
        import json
        from job_search_helper import runner
        self.engine.resume_parallel(self.cycle, defer_sync=True)
        repo = GoogleRepository(self.service, 'fixture', min_request_interval=0)
        def make_engine(repo, state, **kwargs):
            return Engine(repo, state, fetcher=lambda *args: self.fail('sync fetched'), **kwargs)
        with patch.object(runner, '_load_environment'), patch.object(runner, 'load_title_blacklist'), \
             patch.object(runner, 'load_title_review_list'), patch.object(runner, 'state_path', return_value=Path(self.state.path)), \
             patch.object(runner, 'get_repository', return_value=repo), patch.object(runner, 'Engine', side_effect=make_engine):
            # The production command uses this fixed inbox filename.
            destination = __import__('sqlite3').connect(self.root / 'inventories.sqlite3')
            self.inbox.connection.backup(destination)
            destination.close()
            self.assertEqual(runner.run_start(sync_only=True, browser_fallback=False), 0)
        self.assertEqual(len(repo.read('Job History')), 4)
        metrics = json.loads((self.root / 'scraper-performance.json').read_text())
        self.assertTrue(all(isinstance(v, (int, float)) for v in metrics.values()))
        for key in ('read_requests', 'write_requests', 'read_response_bytes', 'write_payload_bytes',
                    'checkpoint_payload_bytes', 'checkpoint_seconds', 'staging_seconds'):
            self.assertGreater(metrics[key], 0)

    def test_sync_and_defer_options_are_forwarded(self):
        from job_search_helper import runner
        with patch.object(runner, 'run_start', return_value=0) as start:
            self.assertEqual(runner.main(['sync', '--batch-size', '25']), 0)
            self.assertTrue(start.call_args.kwargs['sync_only'])
            self.assertTrue(start.call_args.kwargs['retry_blocked'])
            self.assertEqual(start.call_args.kwargs['batch_size'], 25)
            self.assertEqual(runner.main(['sync', '--no-retry-blocked']), 0)
            self.assertFalse(start.call_args.kwargs['retry_blocked'])
            self.assertEqual(runner.main(['start', '--defer-sync']), 0)
            self.assertTrue(start.call_args.kwargs['defer_sync'])
            self.assertFalse(start.call_args.kwargs['sync_only'])

    def test_fetch_error_is_logged_and_other_companies_continue(self):
        def fetch(source, url, cid, name):
            if cid == 'C-0':
                raise OSError('fixture source failed')
            return inventory(cid, name, url)
        self.engine.fetcher = fetch
        self.engine.resume_parallel(self.cycle, fetch_workers=2)
        self.assertEqual(len(self.repo.read('Job History')), 3)
        self.assertIn('fetching inventory', (self.root / 'errors.jsonl').read_text())
        self.assertTrue(self.inbox.get(self.cycle, 'C-0')[1])


if __name__ == '__main__':
    unittest.main()
