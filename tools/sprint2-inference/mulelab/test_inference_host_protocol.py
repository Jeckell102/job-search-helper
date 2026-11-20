import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import coordinator
from coordinator import inference_request_payload
from coordinator_inference import digest
import test_coordinator as fixture


def owned_receipt(request_id, status, *, usage=None, response_digest=None):
    return {'request_id': request_id, 'status': status, 'created': 100.0, 'updated': 101.0,
            'usage': usage, 'response_digest': response_digest, 'cancel_requested': False}


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

    def test_wire_response_must_bind_terminal_receipt_digest_and_usage(self):
        request_id = 'a' * 32
        binding = {'request_id': request_id, 'request_fingerprint': 'b' * 64,
                   'owner_generation': 'c' * 64}
        body = dict(fixture.response('code_read', {'path': 'src/a.py'}), context_tokens=12288)
        control = {'request_id': request_id, 'status': 'COMPLETED',
                   'response_digest': digest(body), 'usage': body['usage']}
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'bridge-token').write_text('synthetic-test-token')
            context = coordinator.INFERENCE_CONTROL.set(binding)
            self.addCleanup(coordinator.INFERENCE_CONTROL.reset, context)
            with patch.object(coordinator.code, 'BASE', base), patch.object(
                    coordinator.urllib.request, 'build_opener') as opener:
                for reply in (body, dict(body, control=dict(control, request_id='d' * 32)),
                              dict(body, control=dict(control, status='RUNNING')),
                              dict(body, control=dict(control, response_digest='e' * 64)),
                              dict(body, control=dict(control, usage=dict(body['usage'], eval_count=61))),
                              dict(body, usage=dict(body['usage'], eval_count=10000001), control=control)):
                    with self.subTest(reply=reply):
                        opener.return_value.open.return_value = io.BytesIO(json.dumps(reply).encode())
                        with self.assertRaises(ValueError):
                            coordinator.infer([], [], 256)
                opener.return_value.open.return_value = io.BytesIO(json.dumps(dict(body, control=control)).encode())
                self.assertEqual(coordinator.infer([], [], 256), body)

    def test_http_turn_requires_binding_before_transport(self):
        with patch.object(coordinator.urllib.request, 'build_opener') as opener:
            with self.assertRaisesRegex(ValueError, 'durable'):
                coordinator.infer([], [], 256)
            opener.assert_not_called()


class InferenceControlCleanupTests(fixture.CoordinatorTests):
    def reserve_bound_request(self):
        task = self.task()
        self.co.store.claim_queued(task)
        state = self.co.store.start_inference_session(task)
        receipt = self.co.store.reserve_inference(
            task, phase=state['phase'], prompt_digest='prompt', tools_digest='tools',
            prompt_tokens=1, output_tokens=256,
            expected_control_generation=self.co.store.control_generation(),
            session_id=state['inference_session_id'])
        binding = {'request_id': receipt['request_id'], 'request_fingerprint': 'a' * 64,
                   'owner_generation': 'b' * 64}
        self.co.store.bind_inference_control(receipt['request_id'], binding)
        return task, binding

    def recover_request(self, binding, operation):
        return self.co.command({'action': 'inference-recovery', 'request_id': binding['request_id'],
                                'operation': operation})

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
        task, binding = self.reserve_bound_request()
        saved = self.co.store.inference_receipts(task)[0]
        with patch.object(coordinator, 'inference_control_status',
                          return_value=owned_receipt('c' * 32, 'COMPLETED')) as status:
            self.assertIsNone(self.co.reconcile_inference(saved))
            status.assert_called_once_with(binding)
        self.assertEqual(self.co.store.inference_receipts(task)[0]['status'], 'DISPATCHING')

    def test_orphan_recovery_uses_only_the_persisted_binding_and_never_replays(self):
        task, binding = self.reserve_bound_request()
        request_id = binding['request_id']
        self.co.store.finalize_inference(request_id, terminal_error='Lost transport')
        with patch.object(coordinator, 'inference_control_status',
                          return_value=owned_receipt(request_id, 'UNCERTAIN')) as status, patch.object(
                coordinator, 'inference_control_orphan_recovery',
                side_effect=[owned_receipt(request_id, 'UNCERTAIN'), owned_receipt(request_id, 'FAILED')]) as recovery:
            observed = self.recover_request(binding, 'observe')
            self.assertTrue(observed['orphan_checked'])
            self.assertEqual(observed['remote_status'], 'UNCERTAIN')
            self.assertFalse(observed['settled'])
            settled = self.recover_request(binding, 'settle')
            self.assertTrue(settled['settled'])
            self.assertFalse(self.recover_request(binding, 'settle')['settled'])
            self.assertEqual(status.call_count, 2)
            self.assertEqual([call.args for call in recovery.call_args_list],
                             [(binding, 'observe'), (binding, 'settle')])
        self.assertEqual(self.co.store.inference_receipts(task)[0]['status'], 'FAILED')
        self.assertEqual(self.co.store.get(task)['tokens'], 257)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_RECOVERY')
        self.assertFalse(self.co.store.queue_enabled())

    def test_recovery_status_remains_held_until_owned_terminal_receipt(self):
        task, binding = self.reserve_bound_request()
        request_id = binding['request_id']
        usage = {'prompt_eval_count': 12, 'eval_count': 8, 'done_reason': 'stop'}
        ready = owned_receipt(request_id, 'COMPLETED', usage=usage, response_digest='a' * 64)
        with patch.object(coordinator, 'inference_control_status', side_effect=[
                None, owned_receipt(request_id, 'RUNNING'), dict(ready, owner_generation='private'), ready,
        ]) as status, patch.object(coordinator, 'inference_control_orphan_recovery') as orphan:
            self.assertFalse(self.recover_request(binding, 'observe')['settled'])
            self.assertEqual(self.recover_request(binding, 'settle')['remote_status'], 'RUNNING')
            self.assertFalse(self.recover_request(binding, 'status')['settled'])
            self.assertTrue(self.recover_request(binding, 'status')['settled'])
            self.assertEqual(self.recover_request(binding, 'status')['local_status'], 'RESPONSE_DROPPED')
            self.assertEqual(status.call_count, 4)
            orphan.assert_not_called()
        state = self.co.store.get(task)
        self.assertEqual((state['calls'], state['tokens'], state['status']), (1, 20, 'PAUSED_RECOVERY'))
        self.assertFalse(state['inference_session_open'])
        self.assertFalse(self.co.store.queue_enabled())

    def test_binding_eligibility_loss_does_not_dispatch(self):
        task = self.task()
        self.co.step(task)
        bind = self.co.store.bind_inference_control

        def pause_before_bind(*args):
            self.co.store.configure_queue(False)
            return bind(*args)

        with patch.object(self.co.store, 'bind_inference_control', side_effect=pause_before_bind):
            self.co.step(task)
        self.assertEqual(self.history, [])
        receipt = self.co.store.inference_receipts(task)[0]
        self.assertEqual(receipt['status'], 'UNCERTAIN')
        self.assertIsNone(receipt['control_binding'])
        with patch.object(coordinator, 'inference_control_status') as status:
            result = self.recover_request(receipt, 'status')
            self.assertFalse(result['binding_available'])
            self.assertFalse(result['settled'])
            status.assert_not_called()

    def test_control_only_turn_queries_owned_status_without_resubmitting_or_running_tools(self):
        task = self.task()
        self.co.step(task)
        base = Path(self.tmp.name)
        (base / 'bridge-token').write_text('synthetic-test-token')
        usage = {'prompt_eval_count': 12, 'eval_count': 8, 'done_reason': 'stop'}
        self.co.model = coordinator.infer
        calls = []

        def respond(request, **kwargs):
            calls.append(request)
            if request.get_method() == 'POST':
                payload = json.loads(request.data)
                return io.BytesIO(json.dumps({'control': {
                    'request_id': payload['request_id'], 'status': 'COMPLETED'
                }}).encode())
            request_id = request.full_url.rsplit('/', 1)[-1]
            return io.BytesIO(json.dumps(owned_receipt(
                request_id, 'COMPLETED', usage=usage, response_digest='a' * 64)).encode())

        with patch.object(coordinator.code, 'BASE', base), patch.object(
                coordinator.urllib.request, 'build_opener') as opener:
            opener.return_value.open.side_effect = respond
            self.co.step(task)
        self.assertEqual([call.get_method() for call in calls], ['POST', 'GET'])
        post = json.loads(calls[0].data)
        self.assertEqual(calls[1].get_header('X-wrapper-request-fingerprint'), post['request_fingerprint'])
        self.assertEqual(calls[1].get_header('X-wrapper-owner-generation'), post['owner_generation'])
        self.assertEqual(self.co.store.inference_receipts(task)[0]['status'], 'RESPONSE_DROPPED')
        self.assertEqual(self.co.store.get(task)['tokens'], 20)


if __name__ == '__main__':
    unittest.main()
