"""Independent Group-5 QA for durable, non-replayable inference dispatch."""
import hashlib
import json
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import coding_tools as code
import coordinator as coordinator_module
import coordinator_inference
from coordinator_store import DEFAULT_CAMPAIGN_ID, Store


class InferenceReservationQATests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'
        for name in ('src', 'tests', 'docs'):
            (self.root / name).mkdir(parents=True)
        (self.root / 'src/a.py').write_text('VALUE = 1\n')
        (self.root / 'tests/test_a.py').write_text('def test_a():\n    assert True\n')
        (self.root / 'docs/wrapper-development-test-protocol.md').write_text(
            '# Required wrapper development and test protocol\nFollow the tests.\n')
        self.root_patch = patch.object(code, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.base = Path(self.tmp.name) / 'tasks'
        self.store = Store(self.base)

    def task(self, number=1, *, workflow_version=1):
        requirements = {
            'version': 1, 'required_files': ['tests/test_a.py', 'src/a.py'],
            'source_targets': [], 'read_hints': {},
        }
        return self.store.create(
            f'Inspect src/a.py and run tests/test_a.py for task {number}',
            ['tests/test_a.py'], 'review', max_sessions=10,
            authorization_version=1, evidence_requirements=requirements,
            workflow_version=workflow_version, integration=None)

    def running(self, number=1, *, workflow_version=1):
        state = self.task(number, workflow_version=workflow_version)
        fields = {'status': 'RUNNING', 'phase': 'inspect', 'stop_requested': False}
        if workflow_version == 2:
            fields['activated_at'] = coordinator_inference.time.time()
        return self.store.update(state['id'], **fields)

    def pilot_running(self, number=5001):
        integration = {
            'company_id': f'COMP-{number}', 'company': f'Pilot Company {number}',
            'configured_url': f'https://pilot.example/{number}/jobs',
            'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'],
            'work_order': f'W{number}', 'ats': 'pilot-ats',
        }
        requirements = {
            'version': 1, 'required_files': ['tests/test_a.py', 'src/a.py'],
            'source_targets': [{
                'url': integration['configured_url'],
                'allowed_urls': [integration['configured_url']],
                'identity_terms': [integration['company']],
            }], 'read_hints': {},
        }
        spec = dict(objective=f'Reviewed pilot company {number}',
                    tests=['tests/test_a.py'], mode='develop', max_sessions=10,
                    authorization_version=1, evidence_requirements=requirements,
                    workflow_version=2, integration=integration)
        task = self.store.enqueue_batch(
            f'pilot-reservation-{number}', [spec], held=True,
            campaign_id=f'campaign-{number}')[0][0]
        self.store.configure_queue(False)
        snapshot = self.store.activation_snapshot(task)
        self.store.commit_activation(
            task, {}, expected_state_digest=snapshot['state_digest'],
            expected_control_generation=snapshot['control_generation'], pilot=True)
        running = self.store.claim_pilot(task)
        self.assertIsNotNone(running)
        return running

    @staticmethod
    def response(name='worker_checkpoint', args=None, usage=None, request_id='provider-1'):
        if args is None:
            args = {'summary': 'saved', 'next_action': 'continue', 'outcome': 'continue'}
        return {
            'id': request_id,
            'message': {'role': 'assistant', 'content': '', 'tool_calls': [
                {'type': 'function', 'function': {'name': name, 'arguments': args}}
            ]},
            'usage': usage if usage is not None else {
                'done_reason': 'stop', 'prompt_eval_count': 100, 'eval_count': 50,
            },
        }

    def coordinator(self, model, budget=None):
        return coordinator_module.Coordinator(
            self.base, model=model,
            budget=budget or (lambda *_: types.SimpleNamespace(
                prompt_tokens=500, available_generation_tokens=6000)),
        )

    def start_and_reserve(self, state=None, *, prompt=500, output=1000):
        state = state or self.running()
        session = self.store.start_inference_session(state['id'])
        self.assertIsNotNone(session)
        receipt = self.store.reserve_inference(
            state['id'], phase=state['phase'],
            prompt_digest=hashlib.sha256(b'prompt').hexdigest(),
            tools_digest=hashlib.sha256(b'tools').hexdigest(),
            prompt_tokens=prompt, output_tokens=output,
            expected_control_generation=self.store.control_generation(),
            session_id=session['inference_session_id'])
        self.assertIsNotNone(receipt)
        return session, receipt

    def test_pause_committed_during_budget_prevents_reservation_and_callback(self):
        state = self.running()
        model_calls = []
        budget_calls = []

        def budget(*_args):
            budget_calls.append(1)
            if len(budget_calls) == 1:
                self.store.pause_task(state['id'])
            return types.SimpleNamespace(prompt_tokens=500, available_generation_tokens=6000)

        coordinator = self.coordinator(lambda *_: model_calls.append(1), budget)
        coordinator.session(state)
        self.assertGreaterEqual(len(budget_calls), 1)
        self.assertEqual(model_calls, [])
        self.assertEqual(self.store.inference_receipts(state['id']), [])
        final = self.store.get(state['id'])
        self.assertEqual((final['calls'], final['tokens']), (0, 0))

    def test_global_stop_during_prompt_preparation_prevents_dispatch(self):
        state = self.running()
        model_calls = []
        budget_calls = []

        def budget(*_args):
            budget_calls.append(1)
            if len(budget_calls) == 2:
                self.store.configure_queue(False)
            return types.SimpleNamespace(prompt_tokens=500, available_generation_tokens=6000)

        self.coordinator(lambda *_: model_calls.append(1), budget).session(state)
        self.assertEqual(model_calls, [])
        self.assertEqual(self.store.inference_receipts(state['id']), [])
        self.assertEqual(self.store.get(state['id'])['calls'], 0)

    def test_reservation_rechecks_deadline_budget_ownership_and_identity(self):
        cases = ('deadline', 'budget', 'ownership', 'identity')
        for index, case in enumerate(cases, 1):
            with self.subTest(case=case):
                for old in self.store.all():
                    if old['status'] == 'RUNNING':
                        self.store.pause_task(old['id'])
                        self.store.update(old['id'], status='PAUSED')
                self.store.configure_queue(True)
                state = (self.pilot_running(6000 + index) if case == 'identity'
                         else self.running(index, workflow_version=2))
                session = self.store.start_inference_session(state['id'])
                generation = self.store.control_generation()
                started = state.get('activated_at') or coordinator_inference.time.time()
                now = started + 1
                if case == 'budget':
                    self.store.update(state['id'], tokens=120000 - 200)
                elif case == 'ownership':
                    self.store.configure_queue(False)
                elif case == 'identity':
                    with self.store.connect() as db:
                        raw = json.loads(db.execute(
                            'SELECT state FROM tasks WHERE id=?', (state['id'],)).fetchone()[0])
                        raw['objective'] = 'raw identity mutation'
                        db.execute('UPDATE tasks SET state=? WHERE id=?',
                                   (json.dumps(raw), state['id']))
                try:
                    with patch.object(coordinator_inference.time, 'time',
                                      return_value=(state['activated_at'] + 3601
                                                    if case == 'deadline' else now)):
                        receipt = self.store.reserve_inference(
                            state['id'], phase=state['phase'], prompt_digest='a' * 64,
                            tools_digest='b' * 64, prompt_tokens=500, output_tokens=1000,
                            expected_control_generation=generation,
                            session_id=session['inference_session_id'])
                except ValueError:
                    receipt = None
                self.assertIsNone(receipt)
                self.assertEqual(self.store.inference_receipts(state['id']), [])
                self.assertEqual(self.store.get(state['id'])['calls'], 0)

    def test_two_store_instances_create_one_session_and_one_reservation(self):
        state = self.running()
        stores = [Store(self.base), Store(self.base)]
        barrier = threading.Barrier(2)

        def compete(index):
            barrier.wait()
            session = stores[index].start_inference_session(state['id'])
            if session is None:
                return None
            return stores[index].reserve_inference(
                state['id'], phase='inspect', prompt_digest='a' * 64,
                tools_digest='b' * 64, prompt_tokens=500, output_tokens=1000,
                expected_control_generation=stores[index].control_generation(),
                session_id=session['inference_session_id'])

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(compete, (0, 1)))
        self.assertEqual(sum(result is not None for result in results), 1)
        final = self.store.get(state['id'])
        self.assertEqual((final['sessions'], final['calls'], final['tokens']), (1, 1, 1500))
        self.assertEqual(len(self.store.inference_receipts(state['id'])), 1)

    def test_dispatch_wins_then_pause_drops_response_and_executes_no_tool(self):
        state = self.running()
        model_calls = []

        def model(*_args):
            model_calls.append(1)
            self.store.pause_task(state['id'])
            return self.response('code_read', {'path': 'src/a.py'})

        self.coordinator(model).session(state)
        self.assertEqual(model_calls, [1])
        inference = self.store.inference_receipts(state['id'])
        self.assertEqual(len(inference), 1)
        self.assertEqual(inference[0]['status'], 'RESPONSE_DROPPED')
        self.assertEqual(self.store.receipts(state['id']), [])
        self.assertEqual((self.store.get(state['id'])['calls'],
                          self.store.get(state['id'])['tokens']), (1, 150))

    def test_timeout_is_uncertain_reserved_and_restart_never_redispatches(self):
        state = self.running()
        calls = []

        def timeout(*_args):
            calls.append(1)
            raise TimeoutError('transport outcome unknown')

        with self.assertRaises(TimeoutError):
            self.coordinator(timeout).session(state)
        receipt = self.store.inference_receipts(state['id'])[0]
        final = self.store.get(state['id'])
        self.assertEqual(receipt['status'], 'UNCERTAIN')
        self.assertEqual(receipt['reserved_tokens'], 2500)
        self.assertEqual((final['calls'], final['tokens']), (1, 2500))
        self.assertEqual(final['status'], 'PAUSED_RECOVERY')

        restarted_calls = []
        restarted = self.coordinator(lambda *_: restarted_calls.append(1))
        restarted.store.recover()
        restarted.step(state['id'])
        self.assertEqual(restarted_calls, [])
        self.assertEqual(restarted.store.receipts(state['id']), [])
        self.assertEqual(len(restarted.store.inference_receipts(state['id'])), 1)
        self.assertEqual(restarted.store.inference_receipts(state['id'])[0]['status'], 'UNCERTAIN')

    def test_uncertain_dispatch_blocks_every_other_task_and_global_lane(self):
        first = self.running(31)
        second = self.task(32)
        _session, receipt = self.start_and_reserve(first)
        result = self.store.finalize_inference(
            receipt['request_id'], terminal_error='TimeoutError')
        self.assertEqual(result['receipt']['status'], 'UNCERTAIN')
        self.assertFalse(self.store.queue_enabled())
        self.assertFalse(self.store.campaign_enabled())
        self.assertIsNone(self.store.pilot_task())
        self.assertEqual(self.store.unresolved_inferences(), [result['receipt']])

        with self.assertRaisesRegex(ValueError, 'unresolved|reconcile'):
            self.store.configure_queue(True)
        # Even corrupt/legacy control state cannot bypass the global receipt
        # barrier in selectors, sessions, or tool intents.
        with self.store.connect() as db:
            db.execute("INSERT INTO settings VALUES ('queue_enabled','true') "
                       "ON CONFLICT(key) DO UPDATE SET value='true'")
        self.assertIsNone(self.store.claim_queued(second['id']))
        self.store.update(second['id'], status='RUNNING')
        self.assertIsNone(self.store.start_inference_session(second['id']))
        self.assertIsNone(self.store.active_intent(
            second['id'], 'inspect', 'code_read', {'path': 'src/a.py'}))
        self.assertEqual(self.store.inference_receipts(second['id']), [])
        self.assertEqual(self.store.receipts(second['id']), [])

    def test_usage_accounting_is_exactly_once_and_fail_closed(self):
        cases = [
            ('valid', {'prompt_eval_count': 100, 'eval_count': 50}, 150, 'COMPLETED', True),
            ('missing', None, 1500, 'RESPONSE_DROPPED', False),
            ('negative', {'prompt_eval_count': -1, 'eval_count': 20}, 1500, 'RESPONSE_DROPPED', False),
            ('zero', {'prompt_eval_count': 0, 'eval_count': 0}, 1500, 'RESPONSE_DROPPED', False),
            ('over', {'prompt_eval_count': 1200, 'eval_count': 800}, 2000, 'RESPONSE_DROPPED', False),
        ]
        for index, (label, usage, expected_tokens, status, tools) in enumerate(cases, 10):
            with self.subTest(label=label):
                state = self.running(index)
                _session, receipt = self.start_and_reserve(state)
                answer = self.response(usage=usage or {
                    'prompt_eval_count': 1, 'eval_count': 1})
                if usage is None:
                    answer.pop('usage')
                result = self.store.finalize_inference(receipt['request_id'], answer)
                self.assertEqual(result['receipt']['status'], status)
                self.assertEqual(result['tools_allowed'], tools)
                self.assertEqual(result['state']['tokens'], expected_tokens)
                self.assertEqual(result['state']['calls'], 1)
                duplicate = self.store.finalize_inference(
                    receipt['request_id'], self.response(usage={
                        'prompt_eval_count': 1, 'eval_count': 1}))
                self.assertFalse(duplicate['tools_allowed'])
                self.assertEqual(duplicate['state']['tokens'], expected_tokens)
                if not tools:
                    self.assertEqual(result['state']['status'], 'PAUSED_USAGE_ERROR')

    def test_pause_after_finalize_before_first_tool_still_executes_no_tool(self):
        state = self.running()
        coordinator = self.coordinator(
            lambda *_: self.response('code_read', {'path': 'src/a.py'}))
        original = coordinator.store.finalize_inference

        def finalize_then_pause(*args, **kwargs):
            result = original(*args, **kwargs)
            coordinator.store.pause_task(state['id'])
            return result

        with patch.object(coordinator.store, 'finalize_inference', side_effect=finalize_then_pause):
            coordinator.session(state)
        self.assertEqual(self.store.receipts(state['id']), [])
        self.assertEqual(self.store.inference_receipts(state['id'])[0]['status'], 'COMPLETED')
        self.assertTrue(self.store.get(state['id'])['stop_requested'])

    def test_control_loss_after_first_tool_prevents_every_later_tool_intent(self):
        state = self.running()
        answer = self.response('code_read', {'path': 'src/a.py'})
        answer['message']['tool_calls'].append({
            'type': 'function', 'function': {'name': 'code_diff', 'arguments': {}}})
        coordinator = self.coordinator(lambda *_: answer)
        original = coordinator.execute

        def execute_then_pause(current, name, args, names):
            result = original(current, name, args, names)
            if name == 'code_read':
                self.store.pause_task(state['id'])
            return result

        with patch.object(coordinator, 'execute', side_effect=execute_then_pause):
            coordinator.session(state)
        self.assertEqual([r['name'] for r in self.store.receipts(state['id'])], ['code_read'])
        self.assertNotIn('code_diff', [r['name'] for r in self.store.receipts(state['id'])])

    def test_deadline_after_dispatch_before_finalize_drops_tools(self):
        state = self.running(workflow_version=2)
        now = [state['activated_at'] + 1]
        coordinator = self.coordinator(
            lambda *_: self.response('code_read', {'path': 'src/a.py'}))
        original = coordinator.store.finalize_inference

        def expire_then_finalize(*args, **kwargs):
            now[0] = state['activated_at'] + 3601
            return original(*args, **kwargs)

        with patch.object(coordinator_inference.time, 'time', side_effect=lambda: now[0]), \
             patch.object(coordinator.store, 'finalize_inference', side_effect=expire_then_finalize):
            coordinator.session(state)
        self.assertEqual(self.store.inference_receipts(state['id'])[0]['status'], 'RESPONSE_DROPPED')
        self.assertEqual(self.store.receipts(state['id']), [])

    def test_pilot_stop_after_session_start_prevents_reservation(self):
        integration = {
            'company_id': 'COMP-5001', 'company': 'Pilot Company',
            'configured_url': 'https://pilot.example/jobs',
            'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'],
            'work_order': 'W5001', 'ats': 'pilot-ats',
        }
        requirements = {
            'version': 1, 'required_files': ['tests/test_a.py', 'src/a.py'],
            'source_targets': [{
                'url': integration['configured_url'],
                'allowed_urls': [integration['configured_url']],
                'identity_terms': [integration['company']],
            }], 'read_hints': {},
        }
        spec = dict(objective='Reviewed pilot company', tests=['tests/test_a.py'],
                    mode='develop', max_sessions=10, authorization_version=1,
                    evidence_requirements=requirements, workflow_version=2,
                    integration=integration)
        task = self.store.enqueue_batch(
            'pilot-reservation', [spec], held=True,
            campaign_id=DEFAULT_CAMPAIGN_ID)[0][0]
        self.store.configure_queue(False)
        snapshot = self.store.activation_snapshot(task)
        self.store.commit_activation(
            task, {}, expected_state_digest=snapshot['state_digest'],
            expected_control_generation=snapshot['control_generation'], pilot=True)
        running = self.store.claim_pilot(task)
        self.assertIsNotNone(running)
        session = self.store.start_inference_session(task)
        generation = self.store.control_generation()
        self.store.stop_pilot()
        receipt = self.store.reserve_inference(
            task, phase=running['phase'], prompt_digest='a' * 64,
            tools_digest='b' * 64, prompt_tokens=500, output_tokens=1000,
            expected_control_generation=generation,
            session_id=session['inference_session_id'])
        self.assertIsNone(receipt)
        self.assertEqual(self.store.inference_receipts(task), [])
        self.assertEqual(self.store.get(task)['calls'], 0)

    def test_receipt_digests_binding_and_counters_survive_restart_without_secrets(self):
        state = self.running()
        session, receipt = self.start_and_reserve(state)
        secret = 'PROMPT-SECRET-MUST-NOT-PERSIST'
        answer = self.response(request_id='provider-request-77')
        result = self.store.finalize_inference(receipt['request_id'], answer)
        restarted = Store(self.base)
        saved = restarted.inference_receipts(state['id'])[0]
        self.assertEqual(saved['request_id'], receipt['request_id'])
        self.assertEqual(saved['session_id'], session['inference_session_id'])
        self.assertEqual(saved['pre_counters'], {'sessions': 1, 'calls': 0, 'tokens': 0})
        self.assertEqual(saved['provider_request_id'], 'provider-request-77')
        self.assertEqual(saved['response_digest'], coordinator_inference.digest(answer))
        self.assertRegex(saved['prompt_digest'], r'^[0-9a-f]{64}$')
        self.assertRegex(saved['tools_digest'], r'^[0-9a-f]{64}$')
        self.assertNotIn(secret, json.dumps(saved))
        self.assertEqual((restarted.get(state['id'])['sessions'],
                          restarted.get(state['id'])['calls'],
                          restarted.get(state['id'])['tokens']), (1, 1, 150))
        self.assertTrue(result['tools_allowed'])
        restarted.export(state['id'])
        exported = json.loads((self.base / state['id'] / 'inference_receipts.json').read_text())
        self.assertEqual(exported, [saved])


if __name__ == '__main__':
    unittest.main()
