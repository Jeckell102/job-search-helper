import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch


class RequiredProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tools = types.SimpleNamespace(
            execute=Mock(),
            scope=lambda messages: {'code_read'},
            schemas_for=lambda messages: [{'type': 'function'}],
        )
        self.native = Mock()
        stubs = {
            'coding_tools': self.tools,
            'context_budget': types.SimpleNamespace(estimate_context=Mock(), ensure_generation_room=Mock()),
            'profile_policy': types.SimpleNamespace(resolve_profile=lambda value: None),
            'tool_runtime': types.SimpleNamespace(native_turn=self.native),
            'engine': types.SimpleNamespace(Cancelled=RuntimeError, BackendError=RuntimeError),
        }
        self.patch = patch.dict('sys.modules', stubs)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        runtime_path = Path(__file__).with_name('coding_runtime.py')
        if not runtime_path.exists():
            runtime_path = Path(__file__).with_name('jetson-coding_runtime.py')
        spec = importlib.util.spec_from_file_location('protocol_runtime_under_test', runtime_path)
        self.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runtime)
        self.tools.execute.return_value = {'ok': True, 'result': {
            'path': self.runtime.PROTOCOL_PATH, 'sha256': 'a' * 64,
            'text': '1: # Required wrapper development and test protocol — version 1\n2: Required gates',
            'truncated': False,
        }}

    def test_loads_host_instructions_on_every_turn_without_mutating_history(self):
        messages = [{'role': 'system', 'content': 'original'}, {'role': 'user', 'content': 'Read only'}]
        for _ in range(2):
            history, trace = self.runtime.load_required_protocol(messages)
            self.assertIn('Required gates', history[0]['content'])
            self.assertEqual(trace[0]['name'], 'code_read')
        self.assertEqual(messages[0]['content'], 'original')
        self.assertEqual(self.tools.execute.call_count, 2)
        self.tools.execute.assert_called_with('code_read', {'path': self.runtime.PROTOCOL_PATH}, {'code_read'})

    def test_inserts_system_instruction_when_needed(self):
        history, _ = self.runtime.load_required_protocol([{'role': 'user', 'content': 'Inspect'}])
        self.assertEqual(history[0]['role'], 'system')
        self.assertEqual(history[1]['content'], 'Inspect')

    def test_missing_truncated_or_wrong_document_fails_closed(self):
        for result in [
            {'ok': False, 'error': 'offline'},
            {'ok': True, 'result': {'text': '# Required wrapper development and test protocol', 'truncated': True}},
            {'ok': True, 'result': {'text': 'unrelated document', 'truncated': False}},
        ]:
            self.tools.execute.return_value = result
            with self.assertRaises(ValueError):
                self.runtime.load_required_protocol([])

    def test_missing_protocol_prevents_inference_and_coding_actions(self):
        self.tools.execute.return_value = {'ok': False, 'error': 'offline'}
        events = list(self.runtime.stream(None, [{'role': 'user', 'content': 'Create a wrapper'}],
                                         100, None, lambda: False, 'Wrapper Coder', None))
        self.assertIn('No coding actions were started', events[0]['text'])
        self.assertTrue(events[-1]['done'])
        self.native.assert_not_called()
        self.assertEqual(self.tools.execute.call_count, 1)

    def test_tool_round_limit_returns_handoff_instead_of_backend_error(self):
        context = __import__('sys').modules['context_budget']
        self.runtime.resolve_profile = lambda value: types.SimpleNamespace(context_tokens=10000, temperature=0.2)
        context.estimate_context.return_value = types.SimpleNamespace(
            prompt_tokens=100,
            available_generation_tokens=1000,
        )
        self.native.return_value = (
            {'content': '', 'tool_calls': [{'function': {'name': 'code_read', 'arguments': {'path': 'src/a.py'}}}]},
            {'done_reason': 'tool_calls', 'prompt_eval_count': 10, 'eval_count': 5, 'eval_duration': 100},
        )
        engine = types.SimpleNamespace(stop=types.SimpleNamespace(is_set=lambda: False))
        events = list(self.runtime.stream(engine, [{'role': 'user', 'content': 'Inspect wrapper'}],
                                         100, None, lambda: False, 'Wrapper Coder', None))
        self.assertIn('Continue in a new request', events[-2]['text'])
        self.assertEqual(events[-1]['finish_reason'], 'length')
        self.assertEqual(self.native.call_count, self.runtime.MAX_TOOL_ROUNDS)


if __name__ == '__main__':
    unittest.main()
