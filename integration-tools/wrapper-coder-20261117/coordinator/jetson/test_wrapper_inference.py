import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch


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


if __name__ == '__main__':
    unittest.main()
