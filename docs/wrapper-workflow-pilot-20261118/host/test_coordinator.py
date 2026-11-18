import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import coordinator as c
from coordinator_store import Store


def response(name, args):
    return {'message': {'role': 'assistant', 'content': '', 'tool_calls': [
        {'type': 'function', 'function': {'name': name, 'arguments': args}}]},
        'usage': {'done_reason': 'stop', 'prompt_eval_count': 500, 'eval_count': 60}}


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'
        for name in ('src', 'docs', 'tests'):
            (self.root / name).mkdir(parents=True)
        (self.root / 'src/a.py').write_text('value = 1\n')
        (self.root / 'tests/test_a.py').write_text('def test_a(): assert True\n')
        (self.root / 'docs/wrapper-development-test-protocol.md').write_text('# Required wrapper development and test protocol\nFollow the tests.\n')
        patcher = patch.object(c.code, 'ROOT', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.history = []
        self.answers = []
        def model(messages, schemas, limit):
            self.history.append(json.loads(json.dumps(messages)))
            return self.answers.pop(0)
        self.co = c.Coordinator(Path(self.tmp.name) / 'tasks', model,
                               lambda m, s: types.SimpleNamespace(available_generation_tokens=6000))
        # Existing assertions exercise persisted version-1 tasks across upgrades.
        # Version-2 host planning is covered by test_coordinator_workflow.
        self.co.workflow_version = 1
        test_patch = patch.object(c.code, 'run_tests', return_value={'exit_code': 0, 'timed_out': False, 'output': '1 passed'})
        test_patch.start()
        self.addCleanup(test_patch.stop)
        self.git_patch = patch.object(c.code, 'git', return_value='')
        self.git = self.git_patch.start()
        self.addCleanup(self.git_patch.stop)

    def task(self, objective='Read src/a.py and run tests/test_a.py', mode='review'):
        return self.co.command({'action': 'start', 'objective': objective, 'mode': mode})['id']

    def checkpoint(self, outcome='continue'):
        return response('worker_checkpoint', {'summary': 'Read src/a.py; saved evidence.',
            'next_action': 'Inspect remaining routing.', 'outcome': outcome})

    def test_fresh_sessions_retain_receipts_and_advance_to_real_verification(self):
        task = self.task()
        self.co.step(task)  # real dispatcher to test runner; no model needed
        self.answers = [response('code_read', {'path': 'src/a.py'}), self.checkpoint()]
        self.co.step(task)
        first_history = len(self.history)
        self.answers = [response('code_read', {'path': 'tests/test_a.py'}), self.checkpoint('phase_done')]
        self.co.step(task)
        fresh = self.history[first_history]
        self.assertEqual(len(fresh), 2)
        self.assertIn('saved evidence', fresh[1]['content'])
        self.assertIn('src/a.py', fresh[1]['content'])
        self.co.step(task)
        state = self.co.store.get(task)
        self.assertEqual(state['status'], 'REVIEW_COMPLETE_LIVE_NOT_VALIDATED')
        self.assertEqual(state['sessions'], 2)
        receipts = self.co.store.receipts(task)
        self.assertEqual(sum(r['name'] == 'code_test' for r in receipts), 2)
        self.assertTrue((self.co.store.base / task / 'HANDOFF.md').exists())

    def test_completion_claim_without_evidence_cannot_advance(self):
        task = self.task()
        self.co.step(task)
        self.answers = [self.checkpoint('phase_done')]
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['phase'], 'inspect')

    def test_review_worker_cannot_edit_and_truncated_calls_do_not_execute(self):
        task = self.task()
        self.co.step(task)
        self.answers = [response('code_create', {'path': 'src/b.py', 'content': 'bad'}), self.checkpoint()]
        self.co.step(task)
        self.assertFalse((self.root / 'src/b.py').exists())
        self.answers = [response('code_create', {'path': 'src/b.py', 'content': 'bad'})]
        self.answers[0]['usage']['done_reason'] = 'length'
        self.co.step(task)
        self.assertFalse((self.root / 'src/b.py').exists())

    def test_external_file_change_pauses_before_model_call(self):
        task = self.task()
        self.co.step(task)
        (self.root / 'src/a.py').write_text('external edit\n')
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_FILES_CHANGED')
        self.assertEqual(self.history, [])

    def test_crash_with_pending_edit_never_replays_automatically(self):
        task = self.task('Fix src/a.py and run tests/test_a.py', mode='develop')
        self.co.store.update(task, status='RUNNING')
        self.co.store.intent(task, 'implement', 'code_edit', {'path': 'src/a.py'})
        recovered = Store(self.co.store.base)
        recovered.recover()
        self.assertEqual(recovered.get(task)['status'], 'PAUSED_RECOVERY')
        with self.assertRaisesRegex(ValueError, 'no receipt'):
            self.co.command({'action': 'resume', 'id': task})

    def test_recovery_after_completed_read_continues_automatically(self):
        task = self.task()
        self.co.store.update(task, status='RUNNING')
        receipt = self.co.store.intent(task, 'inspect', 'code_read', {'path': 'src/a.py'})
        self.co.store.finish(receipt, {'ok': True, 'result': {}})
        self.co.store.recover()
        self.assertEqual(self.co.store.get(task)['status'], 'QUEUED')

    def test_pause_and_resume_keep_existing_receipts(self):
        task = self.task()
        self.co.step(task)
        self.co.command({'action': 'pause', 'id': task})
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED')
        self.co.command({'action': 'resume', 'id': task})
        self.assertEqual(self.co.store.get(task)['status'], 'QUEUED')
        self.assertEqual(len(self.co.store.receipts(task)), 1)

    def test_three_no_progress_sessions_stop(self):
        task = self.task()
        self.co.step(task)
        for _ in range(3):
            self.answers = [self.checkpoint()]
            self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_NO_PROGRESS')

    def test_repeated_bad_path_gets_valid_hint_and_stops(self):
        task = self.task()
        self.co.step(task)
        bad = response('code_read', {'path': '/etc/a.py'})
        self.answers = [bad, bad, bad]
        self.co.step(task)
        receipts = self.co.store.receipts(task)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_BLOCKED')
        self.assertIn('src/a.py', receipts[-1]['result']['valid_path_suggestions'])

    def test_context_pressure_offers_only_checkpoint(self):
        task = self.task()
        self.co.step(task)
        self.co.budget = lambda m, s: types.SimpleNamespace(available_generation_tokens=3000)
        offered = []
        def model(messages, schemas, limit):
            offered.extend(s['function']['name'] for s in schemas)
            return self.checkpoint()
        self.co.model = model
        self.co.step(task)
        self.assertEqual(offered, ['worker_checkpoint'])

    def test_failed_verification_cannot_be_marked_ready(self):
        task = self.task()
        self.co.store.update(task, phase='verify')
        with patch.object(c.code, 'run_tests', return_value={'exit_code': 1, 'output': 'FAILED'}):
            self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_TEST_FAILURE')

    def test_source_gate_and_development_authorization(self):
        task = self.task('Fix src/a.py using https://example.com and run tests/test_a.py', mode='develop')
        self.assertEqual(self.co.store.get(task)['mode'], 'develop')
        self.co.step(task)
        self.answers = [response('code_read', {'path': 'src/a.py'}), self.checkpoint('phase_done')]
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['phase'], 'inspect')

    def test_development_phase_can_edit_and_offline_success_stops_at_operator_gate(self):
        task = self.task('Fix src/a.py and run tests/test_a.py', mode='develop')
        self.co.step(task)
        self.answers = [response('code_read', {'path': 'src/a.py'}),
                        response('code_read', {'path': 'tests/test_a.py'}), self.checkpoint('phase_done')]
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['phase'], 'implement')
        digest = c.manifest()['src/a.py']
        self.answers = [response('code_read', {'path': 'src/a.py'}),
                        response('code_edit', {'path': 'src/a.py', 'sha256': digest, 'old': '1', 'new': '2'}),
                        response('code_diff', {}), self.checkpoint('phase_done')]
        # The implementation gate now requires a nonempty diff before verify.
        # `code.git` is mocked for this unit test, so make the mocked diff
        # reflect the guarded edit above.
        self.git.return_value = 'diff --git a/src/a.py b/src/a.py\n-value = 1\n+value = 2\n'
        self.co.step(task)
        self.co.step(task)
        self.assertEqual((self.root / 'src/a.py').read_text(), 'value = 2\n')
        self.assertEqual(self.co.store.get(task)['status'], 'AWAITING_LIVE_VALIDATION')
        tests = [r for r in self.co.store.receipts(task) if r['name'] == 'code_test']
        self.assertNotEqual(tests[0]['result']['source_manifest_sha256'], tests[1]['result']['source_manifest_sha256'])
        with self.assertRaisesRegex(ValueError, 'operator gate'):
            self.co.command({'action': 'resume', 'id': task})

    def test_pause_in_flight_is_preserved_on_restart(self):
        task = self.task()
        self.co.store.update(task, status='PAUSING', stop_requested=True)
        self.co.store.recover()
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED')

    def test_budget_does_not_reset_on_resume(self):
        task = self.task()
        self.co.store.update(task, status='PAUSED_BUDGET', calls=c.MAX_CALLS)
        with self.assertRaisesRegex(ValueError, 'budget exhausted'):
            self.co.command({'action': 'resume', 'id': task})


if __name__ == '__main__':
    unittest.main()
