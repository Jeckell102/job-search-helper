import unittest
from unittest.mock import patch

import coordinator
from coordinator import inference_request_payload
import test_coordinator as fixture


class InferenceHostProtocolTests(unittest.TestCase):
    def test_legacy_payload_remains_exact_until_control_is_bound(self):
        self.assertEqual(inference_request_payload([], [], 256), {
            'messages': [], 'tools': [], 'max_tokens': 256})

    def test_bound_payload_carries_only_durable_control_identifiers(self):
        payload = inference_request_payload([{'role': 'user', 'content': 'private'}], [], 256, {
            'request_id': 'a' * 32, 'request_fingerprint': 'b' * 64,
            'owner_generation': 'c' * 64})
        self.assertEqual(payload['request_id'], 'a' * 32)
        self.assertEqual(payload['request_fingerprint'], 'b' * 64)
        self.assertEqual(payload['owner_generation'], 'c' * 64)

    def test_control_binding_rejects_malformed_or_extra_data(self):
        for control in ({'request_id': 'short', 'request_fingerprint': 'b' * 64, 'owner_generation': 'c' * 64},
                        {'request_id': 'a' * 32, 'request_fingerprint': 'b' * 64,
                         'owner_generation': 'c' * 64, 'prompt': 'private'}):
            with self.subTest(control=control):
                with self.assertRaisesRegex(ValueError, 'control'):
                    inference_request_payload([], [], 256, control)


class InferenceControlCleanupTests(fixture.CoordinatorTests):
    def test_throwing_model_clears_request_binding_after_durable_reservation(self):
        task = self.task()
        self.co.step(task)  # baseline; no inference yet
        self.co.model = lambda *args: (_ for _ in ()).throw(RuntimeError('transport lost'))
        with self.assertRaisesRegex(RuntimeError, 'transport lost'):
            self.co.step(task)
        self.assertIsNone(coordinator.INFERENCE_CONTROL.get())
        receipt = self.co.store.inference_receipts(task)[0]
        self.assertEqual(receipt['status'], 'UNCERTAIN')

    def test_host_reconciliation_uses_exact_persisted_binding_and_rejects_wrong_request(self):
        task = self.task()
        self.co.store.claim_queued(task)
        state = self.co.store.start_inference_session(task)
        receipt = self.co.store.reserve_inference(task, phase=state['phase'], prompt_digest='prompt',
            tools_digest='tools', prompt_tokens=1, output_tokens=256,
            expected_control_generation=self.co.store.control_generation(), session_id=state['inference_session_id'])
        binding = {'request_id': receipt['request_id'], 'request_fingerprint': 'a' * 64,
                   'owner_generation': 'b' * 64}
        self.co.store.bind_inference_control(receipt['request_id'], binding)
        saved = self.co.store.inference_receipts(task)[0]
        with patch.object(coordinator, 'inference_control_status', return_value={
                'request_id': 'c' * 32, 'status': 'COMPLETED'}) as status:
            self.assertIsNone(self.co.reconcile_inference(saved))
            status.assert_called_once_with(binding)
        self.assertEqual(self.co.store.inference_receipts(task)[0]['status'], 'DISPATCHING')

    def test_orphan_recovery_uses_only_the_persisted_binding_and_never_replays(self):
        task = self.task()
        self.co.store.claim_queued(task)
        state = self.co.store.start_inference_session(task)
        receipt = self.co.store.reserve_inference(task, phase=state['phase'], prompt_digest='prompt',
            tools_digest='tools', prompt_tokens=1, output_tokens=256,
            expected_control_generation=self.co.store.control_generation(), session_id=state['inference_session_id'])
        binding = {'request_id': receipt['request_id'], 'request_fingerprint': 'a' * 64,
                   'owner_generation': 'b' * 64}
        self.co.store.bind_inference_control(receipt['request_id'], binding)
        saved = self.co.store.inference_receipts(task)[0]
        with patch.object(coordinator, 'inference_control_orphan_recovery', return_value={
                'request_id': receipt['request_id'], 'status': 'FAILED'}) as recovery:
            self.co.reconcile_orphan_inference(saved, 'settle')
            recovery.assert_called_once_with(binding, 'settle')
        self.assertEqual(self.co.store.inference_receipts(task)[0]['status'], 'FAILED')


if __name__ == '__main__':
    unittest.main()
