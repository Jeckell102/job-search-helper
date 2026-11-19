"""Implementation unit checks for exactly-once durable inference accounting."""
import unittest
import test_coordinator as fixture
from coordinator_store import Store


class InferenceStoreTests(unittest.TestCase):
    setUp = fixture.CoordinatorTests.setUp
    task = fixture.CoordinatorTests.task

    def reserve(self):
        task = self.task()
        self.co.store.claim_queued(task)
        state = self.co.store.start_inference_session(task)
        receipt = self.co.store.reserve_inference(task, phase=state['phase'], prompt_digest='prompt',
            tools_digest='tools', prompt_tokens=500, output_tokens=2000,
            expected_control_generation=self.co.store.control_generation(), session_id=state['inference_session_id'])
        return task, receipt

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
        task, receipt = self.reserve()
        binding = {'request_id': receipt['request_id'], 'request_fingerprint': 'a' * 64,
                   'owner_generation': 'b' * 64}
        self.co.store.bind_inference_control(receipt['request_id'], binding)
        calls = []
        def status_query(saved):
            calls.append(saved['request_id'])
            self.assertEqual(saved['control_binding'], binding)
            return self.co.store.reconcile_remote_inference(saved['request_id'], {
                'request_id': saved['request_id'], 'status': 'COMPLETED',
                'response_digest': 'c' * 64,
                'usage': {'prompt_eval_count': 12, 'eval_count': 8, 'done_reason': 'stop'}})
        restarted = Store(self.co.store.base)
        restarted.recover(status_query)
        settled = restarted.inference_receipts(task)[0]
        self.assertEqual(calls, [receipt['request_id']])
        self.assertEqual(settled['status'], 'RESPONSE_DROPPED')
        self.assertEqual(restarted.get(task)['tokens'], 20)
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
