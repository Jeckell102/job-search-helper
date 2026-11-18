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
        return self.co.command({'action': 'batch', 'items': [
            {'objective': f'Inspect company {n} src/a.py and tests/test_a.py', 'mode': 'develop'}
            for n in range(count)]})

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


if __name__ == '__main__':
    unittest.main()
