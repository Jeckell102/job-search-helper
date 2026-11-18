"""Persistent FIFO, isolated drafts, pause/restart, and submission acceptance."""
import json
import time
import unittest
from unittest.mock import patch
import coordinator as c
from coordinator_workspace import workspace
from test_coordinator_workflow import WorkflowTests


class QueueTests(WorkflowTests):
    def batch(self, count=2):
        result = self.co.command({'action': 'batch', 'items': [
            {'objective': f'Inspect company {n} src/a.py and tests/test_a.py', 'mode': 'develop',
             'integration': {'company_id': f'COMP-{n+1:04}', 'company': f'Company {n}',
                             'configured_url': f'https://example.com/company-{n}',
                             'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py']}}
            for n in range(count)]})
        # Queue tests explicitly choose the active state they need. Production
        # batch imports remain held until autopilot atomically selects one.
        return result

    def test_batch_preserves_validated_structured_company_identity(self):
        item = {'objective': 'Inspect company src/a.py and tests/test_a.py', 'mode': 'develop',
                'integration': {'company_id': 'COMP-0001', 'company': 'Example Company',
                                'configured_url': 'https://example.com/careers',
                                'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'],
                                'work_order': 'W03'}}
        task = self.co.command({'action': 'batch', 'items': [item]})['ids'][0]
        self.assertEqual(self.co.store.get(task)['integration']['company_id'], 'COMP-0001')

    def test_structured_identity_mismatch_fails_before_queue_write(self):
        item = {'objective': 'Inspect company src/a.py and tests/test_a.py', 'mode': 'develop',
                'integration': {'company_id': 'COMP-0001', 'company': 'Example Company',
                                'configured_url': 'https://example.com/careers',
                                'tests': ['tests/test_wrong.py'], 'source_targets': ['src/a.py']}}
        with self.assertRaisesRegex(ValueError, 'exactly match'):
            self.co.command({'action': 'batch', 'items': [item]})

    def test_batch_is_atomic_and_retry_keeps_original_ids_and_budgets(self):
        with self.assertRaises(ValueError):
            self.co.command({'action': 'batch', 'items': [
                {'objective': 'Inspect src/a.py tests/test_a.py'}, {'objective': 'invalid'}]})
        self.assertEqual(self.co.store.all(), [])
        first = self.batch()
        self.co.store.update(first['ids'][0], tokens=123)
        second = self.batch()
        self.assertTrue(second['reused'])
        self.assertEqual(first['ids'], second['ids'])
        self.assertEqual(self.co.store.get(first['ids'][0])['tokens'], 123)
        self.assertTrue(all(self.co.store.get(task)['status'] == 'PAUSED' for task in first['ids']))

    def test_first_pilot_start_creates_and_snapshots_isolated_workspace(self):
        task = self.batch(1)['ids'][0]
        self.co.store.update(task, status='PAUSED')
        self.co.command({'action': 'queue-pause'})
        self.co.command({'action': 'pilot-start', 'id': task})
        state = self.co.store.get(task)
        self.assertTrue((self.co.store.base / task / 'repo').is_dir())
        with workspace(self.co.store, state):
            self.assertEqual(state['manifest'], c.manifest())

    def test_initial_wait_does_not_expire_but_active_pause_does(self):
        task = self.task()
        self.co.store.update(task, created=time.time()-7200)
        self.co.step(task)
        activated = self.co.store.get(task)['activated_at']
        self.assertGreater(activated, time.time()-5)
        self.co.command({'action': 'pause', 'id': task})
        self.co.command({'action': 'resume', 'id': task})
        self.assertEqual(self.co.store.get(task)['activated_at'], activated)
        self.co.store.update(task, status='PAUSED', activated_at=time.time()-7200)
        with self.assertRaisesRegex(ValueError, 'budget exhausted'):
            self.co.command({'action': 'resume', 'id': task})

    def test_global_pause_survives_restart_and_never_resumes_blocked_tasks(self):
        a, b = self.batch()['ids']
        self.co.store.update(a, status='PAUSED_BLOCKED')
        self.co.command({'action': 'queue-pause'})
        other = c.Coordinator(self.co.store.base, self.co.model, self.co.budget)
        other.step(b)
        self.assertEqual(other.store.receipts(b), [])
        self.assertFalse(other.command({'action': 'queue'})['enabled'])
        other.command({'action': 'queue-resume'})
        self.assertEqual(other.store.get(a)['status'], 'PAUSED_BLOCKED')
        other.step(b)
        self.assertEqual(other.store.get(b)['phase'], 'inspect')

    def test_company_drafts_never_contaminate_each_other_or_base(self):
        a, b = self.batch()['ids']
        self.co.step(a)
        with workspace(self.co.store, self.co.store.get(a)):
            (c.code.root() / 'src/a.py').write_text('draft from first company\n')
        self.co.step(b)
        self.assertEqual((self.root / 'src/a.py').read_text(), 'value = 1\n')
        self.assertEqual((self.co.store.base / b / 'repo/src/a.py').read_text(), 'value = 1\n')
        self.assertIsNone(c.code.WORKSPACE.get())

    def test_scheduler_advances_after_blocked_company_in_fifo_order(self):
        a, b = self.batch()['ids']
        self.co.store.update(a, status='QUEUED')
        self.co.store.update(b, status='QUEUED')
        visited = []
        def step(task):
            visited.append(task)
            self.co.store.update(task, status='PAUSED_BLOCKED' if task == a else 'AWAITING_LIVE_VALIDATION')
            if task == b:
                self.co.stop.set()
        with patch.object(self.co, 'step', side_effect=step):
            self.co.run()
        self.assertEqual(visited, [a, b])

    def test_pause_during_final_test_prevents_following_diff(self):
        task = self.task()
        self.collect(task)
        self.answers = [self.checkpoint('phase_done')]
        self.co.step(task)
        def finish_test(paths):
            self.co.command({'action': 'queue-pause'})
            return {'exit_code': 0, 'timed_out': False, 'output': '1 passed'}
        with patch.object(c.code, 'run_tests', side_effect=finish_test):
            self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'QUEUED')
        self.assertEqual(self.co.store.receipts(task)[-1]['name'], 'code_test')

    def test_pilot_only_runs_selected_task_while_global_queue_is_paused(self):
        a, b = self.batch()['ids']
        self.co.command({'action': 'queue-pause'})
        self.co.store.update(a, status='PAUSED')
        self.co.store.update(b, status='PAUSED')
        result = self.co.command({'action': 'pilot-start', 'id': b})
        self.assertEqual(result['state']['status'], 'QUEUED')
        self.assertEqual(self.co.store.pilot_task(), b)
        self.co.step(b)
        self.assertEqual(self.co.store.get(b)['phase'], 'inspect')
        self.assertEqual(self.co.store.get(a)['status'], 'PAUSED')
        self.co.command({'action': 'pilot-stop'})
        self.assertIsNone(self.co.store.pilot_task())

    def test_autopilot_activates_exactly_one_untouched_company(self):
        a, b = self.batch()['ids']
        self.co.store.update(a, status='PAUSED', reason='Pause requested.')
        self.co.store.update(b, status='PAUSED', reason='Pause requested.')
        result = self.co.command({'action': 'autopilot-start'})
        self.assertTrue(result['autopilot'])
        first = self.co.store.activate_next_untouched()
        self.assertEqual(first['id'], a)
        self.assertEqual(self.co.store.get(a)['status'], 'QUEUED')
        self.assertEqual(self.co.store.get(b)['status'], 'PAUSED')
        self.assertIsNone(self.co.store.activate_next_untouched())

    def test_autopilot_advances_only_after_current_company_stops(self):
        a, b = self.batch()['ids']
        for task in (a, b):
            self.co.store.update(task, status='PAUSED', reason='Pause requested.')
        self.co.command({'action': 'autopilot-start'})
        self.assertEqual(self.co.store.activate_next_untouched()['id'], a)
        self.co.store.update(a, status='AWAITING_LIVE_VALIDATION')
        self.assertEqual(self.co.store.activate_next_untouched()['id'], b)

    def test_autopilot_never_retries_failures_or_previously_activated_tasks(self):
        a, b = self.batch()['ids']
        self.co.store.update(a, status='PAUSED_ERROR', activated_at=time.time())
        self.co.store.update(b, status='PAUSED', activated_at=time.time())
        self.co.command({'action': 'autopilot-start'})
        self.assertIsNone(self.co.store.activate_next_untouched())

    def test_autopilot_stop_survives_restart(self):
        self.co.command({'action': 'autopilot-start'})
        self.co.command({'action': 'autopilot-stop'})
        other = c.Coordinator(self.co.store.base, self.co.model, self.co.budget)
        self.assertFalse(other.store.autopilot_enabled())
        self.assertFalse(other.store.queue_enabled())

    def test_cross_process_claim_allows_only_one_scheduler(self):
        a, b = self.batch()['ids']
        self.co.store.update(a, status='QUEUED')
        self.co.store.update(b, status='QUEUED')
        other = c.Coordinator(self.co.store.base, self.co.model, self.co.budget)
        first = self.co.store.claim_queued()
        second = other.store.claim_queued()
        self.assertEqual(first['id'], a)
        self.assertIsNone(second)
        self.co.store.update(a, status='AWAITING_LIVE_VALIDATION')
        self.assertEqual(other.store.claim_queued()['id'], b)

    def test_same_queued_task_cannot_be_claimed_twice(self):
        task = self.batch(1)['ids'][0]
        self.co.store.update(task, status='QUEUED')
        other = c.Coordinator(self.co.store.base, self.co.model, self.co.budget)
        self.assertEqual(self.co.store.claim_queued()['id'], task)
        self.assertIsNone(other.store.claim_queued())

    def test_each_autopilot_company_gets_a_new_worker_identity(self):
        a, b = self.batch()['ids']
        for task in (a, b):
            self.co.store.update(task, status='PAUSED', reason='Pause requested.')
        first = self.co.store.activate_next_untouched()
        self.co.store.update(a, status='AWAITING_LIVE_VALIDATION')
        second = self.co.store.activate_next_untouched()
        self.assertNotEqual(first['integration_run_id'], second['integration_run_id'])
        self.assertEqual(second['calls'], 0)
        self.assertEqual(second['tokens'], 0)
        self.assertEqual(second['sessions'], 0)
        self.assertEqual(second['checkpoint'], {})

    def test_selected_company_is_not_reselected_after_pause_before_first_step(self):
        task = self.batch(1)['ids'][0]
        first = self.co.store.activate_next_untouched()
        self.co.store.update(task, status='PAUSED')
        self.assertIsNotNone(first.get('selected_at'))
        self.assertIsNone(self.co.store.activate_next_untouched())


if __name__ == '__main__':
    unittest.main()
