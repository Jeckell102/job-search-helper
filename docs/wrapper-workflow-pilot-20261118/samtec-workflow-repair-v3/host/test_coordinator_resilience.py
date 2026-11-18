"""Isolated fault-injection tests: no live service, model, network or production writes."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import threading
import time
import types
import unittest
from unittest.mock import patch

import coordinator as c
import test_coordinator as fixture


class ResilienceTests(unittest.TestCase):
    setUp = fixture.CoordinatorTests.setUp
    task = fixture.CoordinatorTests.task
    checkpoint = fixture.CoordinatorTests.checkpoint

    def start(self):
        self.co.start()
        def stop():
            self.co.stop.set()
            self.co.wake.set()
            self.co.thread.join(2)
        self.addCleanup(stop)

    def until(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            self.co.wake.set()
            time.sleep(.01)
        self.assertTrue(predicate())

    def test_repeated_snapshot_failures_degrade_health_without_replaying_actions(self):
        task = self.task()
        self.answers = [self.checkpoint('blocked')]
        with patch.object(self.co.store, 'export', side_effect=OSError('snapshot disk unavailable')):
            self.start()
            self.until(lambda: self.co.health()['snapshot_errors'].get(task, {}).get('attempts', 0) >= 3)
            self.until(lambda: self.co.store.get(task)['status'] == 'PAUSED_BLOCKED')
            health = self.co.command({'action': 'health'})
            self.assertTrue(health['worker_alive'])
            self.assertEqual(health['status'], 'degraded')
            self.assertEqual(self.co.store.get(task)['calls'], 1)
            self.assertEqual(len(self.co.store.receipts(task)), 1)
        self.co.export(task)
        self.assertEqual(self.co.health()['snapshot_errors'], {})
        checkpoint = json.loads((self.co.store.base / task / 'checkpoint.json').read_text())
        self.assertEqual(checkpoint['status'], 'PAUSED_BLOCKED')

    def test_persistent_database_failure_is_visible_and_stops_for_supervisor(self):
        self.task()
        uncaught = []
        with patch.object(self.co.store, 'all', side_effect=sqlite3.OperationalError('database unavailable')):
            with patch.object(c, 'CONTROL_RETRY_SECONDS', .001), patch.object(threading, 'excepthook', side_effect=uncaught.append):
                self.start()
                self.co.thread.join(2)
        self.assertFalse(self.co.thread.is_alive())
        self.assertEqual(uncaught, [])
        self.assertEqual(self.co.health()['status'], 'failed')
        self.assertEqual(self.co.health()['control_failures'], c.CONTROL_RETRIES)
        self.assertIn('OperationalError', self.co.health()['fatal_error'])

    def test_database_failure_inside_error_handler_is_also_contained(self):
        self.task()
        with patch.object(self.co, 'step', side_effect=RuntimeError('tool error')):
            with patch.object(self.co.store, 'get', side_effect=sqlite3.OperationalError('recovery DB failed')):
                with patch.object(c, 'CONTROL_RETRY_SECONDS', .001):
                    self.start()
                    self.co.thread.join(2)
        self.assertFalse(self.co.thread.is_alive())
        self.assertEqual(self.co.health()['control_failures'], c.CONTROL_RETRIES)

    def test_transient_database_failure_reconciles_before_continuing(self):
        task = self.task()
        original = self.co.store.all
        attempts = []
        def flaky_all():
            attempts.append(1)
            if len(attempts) == 1:
                raise sqlite3.OperationalError('temporary database failure')
            return original()
        self.answers = [self.checkpoint('blocked')]
        with patch.object(self.co.store, 'all', side_effect=flaky_all), patch.object(c, 'CONTROL_RETRY_SECONDS', .001):
            self.start()
            self.until(lambda: self.co.store.get(task)['status'] == 'PAUSED_BLOCKED')
        self.assertTrue(self.co.thread.is_alive())
        self.assertEqual(self.co.store.get(task)['calls'], 1)
        self.assertEqual(self.co.health()['control_failures'], 0)

    def test_database_failure_after_edit_never_replays_uncertain_mutation(self):
        task = self.task('Fix src/a.py and run tests/test_a.py', mode='develop')
        self.co.store.update(task, phase='implement', manifest=c.manifest())
        self.answers = [fixture.response('code_edit', {'path': 'src/a.py', 'sha256': c.manifest()['src/a.py'],
                                                    'old': '1', 'new': '2'})]
        with patch.object(self.co.store, 'finish', side_effect=sqlite3.OperationalError('receipt disk unavailable')):
            with patch.object(c, 'CONTROL_RETRY_SECONDS', .001):
                self.start()
                self.until(lambda: self.co.store.get(task)['status'] == 'PAUSED_RECOVERY')
        self.assertEqual((self.root / 'src/a.py').read_text(), 'value = 2\n')
        self.assertEqual(len(self.history), 1)
        self.assertEqual(len(self.co.store.receipts(task)), 1)
        self.assertIsNone(self.co.store.receipts(task)[0]['result'])
        with self.assertRaisesRegex(ValueError, 'no receipt'):
            self.co.command({'action': 'resume', 'id': task})

    def test_supervisor_exits_process_when_scheduler_is_dead(self):
        spec = importlib.util.spec_from_file_location('isolated_host_server', Path(c.__file__).with_name('host_server.py'))
        module = importlib.util.module_from_spec(spec)
        # Importing the bridge normally reads its token; the test supplies a harmless fixture.
        with patch.object(Path, 'read_text', return_value='isolated-test-token'):
            spec.loader.exec_module(module)
        exits = []
        coordinator = types.SimpleNamespace(thread=types.SimpleNamespace(is_alive=lambda: False))
        module.supervise(coordinator, exit_process=exits.append)
        self.assertEqual(exits, [75])

    def test_token_reservation_caps_generation_to_remaining_allowance(self):
        task = self.task()
        self.co.step(task)
        self.co.store.update(task, tokens=c.MAX_TOKENS - 800)
        self.co.budget = lambda m, s: types.SimpleNamespace(prompt_tokens=500, available_generation_tokens=6000)
        observed = []
        def model(messages, schemas, limit):
            observed.append((limit, self.co.store.get(task)['tokens']))
            return self.checkpoint()
        self.co.model = model
        self.co.step(task)
        self.assertEqual(observed, [(300, c.MAX_TOKENS)])
        self.assertEqual(self.co.store.get(task)['tokens'], c.MAX_TOKENS - 240)

    def test_failed_call_keeps_full_reserved_tokens(self):
        task = self.task()
        self.co.step(task)
        self.co.budget = lambda m, s: types.SimpleNamespace(prompt_tokens=500, available_generation_tokens=6000)
        self.co.model = lambda *args: (_ for _ in ()).throw(TimeoutError('uncertain inference'))
        with self.assertRaises(TimeoutError):
            self.co.step(task)
        state = self.co.store.get(task)
        self.assertEqual((state['calls'], state['tokens']), (1, 2500))

    def test_missing_negative_boolean_and_zero_usage_retain_reservation_and_block_tools(self):
        invalid = [None, {}, {'prompt_eval_count': -1, 'eval_count': 60},
                   {'prompt_eval_count': True, 'eval_count': 60},
                   {'prompt_eval_count': '500', 'eval_count': 60},
                   {'prompt_eval_count': 0, 'eval_count': 0}]
        for usage in invalid:
            with self.subTest(usage=usage):
                task = self.task()
                self.co.step(task)
                self.co.budget = lambda m, s: types.SimpleNamespace(prompt_tokens=500, available_generation_tokens=6000)
                answer = fixture.response('code_read', {'path': 'src/a.py'})
                answer['usage'] = usage
                self.co.model = lambda *args: answer
                self.co.step(task)
                state = self.co.store.get(task)
                self.assertEqual(state['tokens'], 2500)
                self.assertEqual(state['status'], 'PAUSED_USAGE_ERROR')
                self.assertEqual(len(self.co.store.receipts(task)), 1)  # Baseline only.

    def test_over_reservation_usage_pauses_and_preserves_observed_usage(self):
        task = self.task()
        self.co.step(task)
        self.co.budget = lambda m, s: types.SimpleNamespace(prompt_tokens=500, available_generation_tokens=6000)
        answer = fixture.response('code_read', {'path': 'src/a.py'})
        answer['usage']['eval_count'] = 3000
        self.co.model = lambda *args: answer
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['tokens'], 3500)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_USAGE_ERROR')
        self.assertEqual(len(self.co.store.receipts(task)), 1)

    def test_expired_queued_task_runs_no_baseline_and_cannot_resume(self):
        task = self.task()
        created = self.co.store.get(task)['created']
        with patch.object(c.time, 'time', return_value=created + c.MAX_SECONDS):
            self.co.step(task)
            self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_BUDGET')
            self.assertEqual(self.co.store.receipts(task), [])
            with self.assertRaisesRegex(ValueError, 'budget exhausted'):
                self.co.command({'action': 'resume', 'id': task})

    def test_deadline_expiring_during_model_prevents_returned_tool_action(self):
        task = self.task()
        self.co.step(task)
        created = self.co.store.get(task)['created']
        now = [created + 1]
        def model(*args):
            now[0] = created + c.MAX_SECONDS
            return fixture.response('code_read', {'path': 'src/a.py'})
        self.co.model = model
        with patch.object(c.time, 'time', side_effect=lambda: now[0]):
            self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_BUDGET')
        self.assertEqual(len(self.co.store.receipts(task)), 1)

    def test_deadline_expiring_during_tool_prevents_next_tool_in_batch(self):
        task = self.task()
        self.co.step(task)
        created = self.co.store.get(task)['created']
        now = [created + 1]
        answer = fixture.response('code_read', {'path': 'src/a.py'})
        answer['message']['tool_calls'].append({'type': 'function', 'function': {'name': 'code_diff', 'arguments': {}}})
        self.answers = [answer]
        original = c.code.execute
        def execute(name, args, names):
            result = original(name, args, names)
            if name == 'code_read' and args['path'] == 'src/a.py':
                now[0] = created + c.MAX_SECONDS
            return result
        with patch.object(c.time, 'time', side_effect=lambda: now[0]), patch.object(c.code, 'execute', side_effect=execute):
            self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_BUDGET')
        self.assertEqual([r['name'] for r in self.co.store.receipts(task)], ['code_test', 'code_read'])


if __name__ == '__main__':
    unittest.main()
