import importlib.util
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from inference_control_store import InferenceControlStore


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.native = Mock(return_value=(
            {'role': 'assistant', 'content': 'ready', 'thinking': 'private', 'tool_calls': []},
            {'done_reason': 'stop', 'prompt_eval_count': 100, 'eval_count': 4}))
        self.room = Mock()
        profile = types.SimpleNamespace(context_tokens=12288, temperature=0.2)
        modules = {'context_budget': types.SimpleNamespace(estimate_context=Mock(), require_output_room=self.room),
            'profile_policy': types.SimpleNamespace(resolve_profile=lambda name: profile),
            'tool_runtime': types.SimpleNamespace(native_turn=self.native)}
        patcher = patch.dict('sys.modules', modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location('gateway_test', Path(__file__).with_name('wrapper_inference.py'))
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.data = {'messages': [{'role': 'user', 'content': 'Inspect'}], 'tools': [], 'max_tokens': 500}

    def test_inference_uses_shared_background_gate_and_omits_private_reasoning(self):
        result = self.module.infer(object(), self.data)
        self.assertFalse(self.native.call_args.kwargs['foreground'])
        self.assertNotIn('thinking', result['message'])
        self.assertEqual(result['context_tokens'], 12288)
        self.room.assert_called_once()

    def test_unsupported_tools_and_excess_output_rejected(self):
        for changes in ({'tools': [{'function': {'name': 'shell'}}]}, {'max_tokens': 9000}, {'max_tokens': True}):
            with self.assertRaises(ValueError):
                self.module.infer(object(), {**self.data, **changes})
        self.native.assert_not_called()

    def controlled(self):
        data = dict(self.data, request_id='a' * 32, owner_generation='c' * 64)
        data['request_fingerprint'] = self.module._digest({
            'messages': data['messages'], 'tools': data['tools'], 'max_tokens': data['max_tokens']})
        return data

    def test_controlled_turn_is_idempotent_and_keeps_only_a_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            control = InferenceControlStore(Path(temp) / 'control.sqlite3')
            result = self.module.infer(object(), self.controlled(), control)
            self.assertEqual(result['control']['status'], 'COMPLETED')
            self.assertNotIn('content', result['control'])
            duplicate = self.module.infer(object(), self.controlled(), control)
            self.assertNotIn('message', duplicate)
            self.assertEqual(duplicate['control']['status'], 'COMPLETED')
            self.assertEqual(self.native.call_count, 1)

    def test_controlled_turn_rejects_a_payload_fingerprint_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            control = InferenceControlStore(Path(temp) / 'control.sqlite3')
            data = self.controlled()
            data['request_fingerprint'] = 'd' * 64
            with self.assertRaisesRegex(ValueError, 'fingerprint'):
                self.module.infer(object(), data, control)
            self.native.assert_not_called()

    def test_controlled_native_error_is_terminal_and_releases_the_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            control = InferenceControlStore(Path(temp) / 'control.sqlite3')
            self.native.side_effect = RuntimeError('backend unavailable')
            with self.assertRaisesRegex(RuntimeError, 'backend unavailable'):
                self.module.infer(object(), self.controlled(), control)
            self.assertEqual(control.status('a' * 32)['status'], 'FAILED')
            self.assertTrue(control.begin('b' * 32, 'd' * 64, 'c' * 64)['start'])

    def test_controlled_cancellation_during_a_turn_is_terminal(self):
        with tempfile.TemporaryDirectory() as temp:
            control = InferenceControlStore(Path(temp) / 'control.sqlite3')
            data = self.controlled()
            def cancelled_turn(*args, **kwargs):
                control.cancel(data['request_id'], data['request_fingerprint'], data['owner_generation'])
                return ({'role': 'assistant', 'content': 'cancelled', 'tool_calls': []},
                        {'done_reason': 'stop', 'prompt_eval_count': 1, 'eval_count': 1})
            self.native.side_effect = cancelled_turn
            with self.assertRaisesRegex(ValueError, 'inference_cancelled'):
                self.module.infer(object(), data, control)
            self.assertEqual(control.status('a' * 32)['status'], 'CANCELLED')


if __name__ == '__main__':
    unittest.main()
