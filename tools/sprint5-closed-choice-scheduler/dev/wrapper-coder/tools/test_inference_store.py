"""Implementation unit checks for exactly-once durable inference accounting."""
import json
import unittest
import test_coordinator as fixture
from coordinator_inference import digest
from coordinator_store import Store


class InferenceStoreTests(unittest.TestCase):
    setUp = fixture.CoordinatorTests.setUp
    task = fixture.CoordinatorTests.task

    def reserve(self, *, phase=None, bind_control=False):
        task = self.task()
        if phase is not None:
            self.co.store.update(task, phase=phase)
        self.co.store.claim_queued(task)
        state = self.co.store.start_inference_session(task)
        receipt = self.co.store.reserve_inference(task, phase=state['phase'], prompt_digest='prompt',
            tools_digest='tools', prompt_tokens=500, output_tokens=2000,
            expected_control_generation=self.co.store.control_generation(), session_id=state['inference_session_id'])
        if bind_control:
            binding = {'request_id': receipt['request_id'], 'request_fingerprint': 'a' * 64,
                       'owner_generation': 'b' * 64}
            self.assertEqual(self.co.store.bind_inference_control(receipt['request_id'], binding)['control_binding'], binding)
        return task, receipt

    def test_opted_in_owned_recipe_choice_is_persisted_with_accounting_once(self):
        task, receipt = self.reserve(phase='inspect', bind_control=True)
        choice = {'summary': 'W1', 'next_action': 'listing_membership_change', 'outcome': 'phase_done'}
        answer = fixture.response('worker_checkpoint', choice)
        answer['message']['content'] = 'Private fixture text must not be persisted.'
        first = self.co.store.finalize_inference(receipt['request_id'], answer, record_owned_recipe_choice=True)
        self.assertTrue(first['tools_allowed'])
        reopened = Store(self.co.store.base)
        saved = reopened.inference_receipt(receipt['request_id'])
        self.assertEqual(saved['status'], 'COMPLETED')
        self.assertEqual(saved['accepted_recipe_choice'], choice)
        self.assertEqual(saved['response_digest'], digest(answer))
        self.assertNotIn(answer['message']['content'], json.dumps(saved))
        changed = fixture.response('worker_checkpoint', {**choice, 'next_action': 'hold'})
        duplicate = reopened.finalize_inference(receipt['request_id'], changed, record_owned_recipe_choice=True)
        self.assertFalse(duplicate['tools_allowed'])
        self.assertEqual(reopened.inference_receipt(receipt['request_id']), saved)
        self.assertEqual((reopened.get(task)['calls'], reopened.get(task)['tokens']), (1, 560))

    def test_default_negative_or_truncated_choice_does_not_enter_the_receipt(self):
        choice = {'summary': 'W1', 'next_action': 'listing_membership_change', 'outcome': 'phase_done'}
        for case in ('disabled', 'unbound', 'wrong_phase', 'fixed_delay', 'extra_argument', 'extra_call',
                     'truncated', 'cancelled', 'over_budget', 'changed_control'):
            with self.subTest(case=case):
                task, receipt = self.reserve(phase='baseline' if case == 'wrong_phase' else 'inspect',
                                             bind_control=case != 'unbound')
                args = dict(choice)
                if case == 'fixed_delay':
                    args['next_action'] = 'fixed_delay'
                if case == 'extra_argument':
                    args['note'] = 'An unreviewed argument'
                answer = fixture.response('worker_checkpoint', args)
                if case == 'extra_call':
                    answer['message']['tool_calls'] *= 2
                if case in {'truncated', 'cancelled'}:
                    answer['usage']['done_reason'] = 'length' if case == 'truncated' else 'cancelled'
                if case == 'over_budget':
                    answer['usage']['eval_count'] = receipt['reserved_tokens']
                if case == 'changed_control':
                    self.co.store.configure_queue(False)
                result = self.co.store.finalize_inference(receipt['request_id'], answer,
                                                         **({'record_owned_recipe_choice': True} if case != 'disabled' else {}))
                dropped = case in {'over_budget', 'changed_control'}
                self.assertEqual(result['tools_allowed'], not dropped)
                saved = self.co.store.inference_receipt(receipt['request_id'])
                self.assertEqual(saved['status'], 'RESPONSE_DROPPED' if dropped else 'COMPLETED')
                self.assertNotIn('accepted_recipe_choice', saved)
                self.co.store.stop_at_boundary(task, 'Next independent fixture case.')

    def test_finalize_once_adjusts_current_totals_not_old_snapshot(self):
        task, receipt = self.reserve()
        self.co.store.update(task, tokens=2600)
        answer = fixture.response('code_read', {'path': 'src/a.py'})
        first = self.co.store.finalize_inference(receipt['request_id'], answer)
        self.assertTrue(first['tools_allowed'])
        self.assertEqual(first['state']['tokens'], 660)
        second = Store(self.co.store.base).finalize_inference(receipt['request_id'], answer)
        self.assertFalse(second['tools_allowed'])
        self.assertEqual(second['state']['tokens'], 660)
        self.assertEqual(second['state']['calls'], 1)

    def test_crash_recovery_retains_full_charge_and_prevents_new_session(self):
        task, receipt = self.reserve()
        restarted = Store(self.co.store.base)
        restarted.recover()
        self.assertEqual(restarted.inference_receipts(task)[0]['status'], 'UNCERTAIN')
        self.assertEqual(restarted.get(task)['tokens'], 2500)
        self.assertEqual(restarted.get(task)['status'], 'PAUSED_RECOVERY')
        restarted.update(task, status='RUNNING')
        self.assertIsNone(restarted.start_inference_session(task))
        self.assertFalse(restarted.finalize_inference(receipt['request_id'], fixture.response('code_read', {}))['tools_allowed'])
        self.assertEqual(restarted.get(task)['tokens'], 2500)

    def test_malformed_tools_are_uncertain_without_consumption_refund(self):
        task, receipt = self.reserve()
        answer = fixture.response('code_read', {})
        answer['message']['tool_calls'] = [None]
        final = self.co.store.finalize_inference(receipt['request_id'], answer)
        self.assertFalse(final['tools_allowed'])
        self.assertEqual(final['receipt']['status'], 'UNCERTAIN')
        self.assertEqual(final['state']['tokens'], 2500)

    def test_restart_reconciles_retained_completion_without_replay_or_double_charge(self):
        task, receipt = self.reserve(phase='inspect')
        binding = {'request_id': receipt['request_id'], 'request_fingerprint': 'a' * 64,
                   'owner_generation': 'b' * 64}
        self.co.store.bind_inference_control(receipt['request_id'], binding)
        calls = []
        def status_query(saved):
            calls.append(saved['request_id'])
            self.assertEqual(saved['control_binding'], binding)
            return self.co.store.reconcile_remote_inference(saved['request_id'], {
                'request_id': saved['request_id'], 'status': 'COMPLETED',
                'created': 1.0, 'updated': 2.0, 'cancel_requested': False,
                'response_digest': 'c' * 64,
                'usage': {'prompt_eval_count': 12, 'eval_count': 8, 'done_reason': 'stop'}})
        restarted = Store(self.co.store.base)
        restarted.recover(status_query)
        settled = restarted.inference_receipts(task)[0]
        self.assertEqual(calls, [receipt['request_id']])
        self.assertEqual(settled['status'], 'RESPONSE_DROPPED')
        self.assertNotIn('accepted_recipe_choice', settled)
        self.assertEqual(restarted.get(task)['tokens'], 20)
        late = fixture.response('worker_checkpoint', {
            'summary': 'W1', 'next_action': 'listing_membership_change', 'outcome': 'phase_done',
        })
        self.assertFalse(restarted.finalize_inference(receipt['request_id'], late,
                                                      record_owned_recipe_choice=True)['tools_allowed'])
        self.assertEqual(restarted.inference_receipt(receipt['request_id']), settled)
        self.assertIsNone(restarted.start_inference_session(task))

    def test_restart_keeps_running_remote_receipt_as_a_lane_blocking_hold(self):
        task, receipt = self.reserve()
        binding = {'request_id': receipt['request_id'], 'request_fingerprint': 'a' * 64,
                   'owner_generation': 'b' * 64}
        self.co.store.bind_inference_control(receipt['request_id'], binding)
        calls = []
        def status_query(saved):
            calls.append(saved['request_id'])
            return self.co.store.reconcile_remote_inference(saved['request_id'], {
                'request_id': saved['request_id'], 'status': 'RUNNING'})
        restarted = Store(self.co.store.base)
        restarted.recover(status_query)
        self.assertEqual(calls, [receipt['request_id']])
        self.assertEqual(restarted.inference_receipts(task)[0]['status'], 'UNCERTAIN')
        self.assertIsNone(restarted.start_inference_session(task))
