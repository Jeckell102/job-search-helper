import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import coding_tools as host


def load_jetson_tools():
    path = Path(__file__).resolve().parents[1] / 'jetson/coding_tools.py'
    if not path.is_file():
        path = Path(__file__).with_name('jetson-coding_tools.py')
    spec = importlib.util.spec_from_file_location('jetson_forwarding_tools', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScopeParityTests(unittest.TestCase):
    def test_host_and_jetson_enforce_same_no_write_scope(self):
        jetson = load_jetson_tools()
        for wording in ('do not modify any files', "don't change anything", "don’t edit code",
                        'do not write files', 'read-only', 'review only',
                        'never update code', 'do not make any changes',
                        'without modifying files', 'no file changes', 'leave files unchanged'):
            messages = [{'role': 'user', 'content': 'Review the fix; ' + wording + '. Run tests/test_a.py.'}]
            with self.subTest(wording=wording):
                self.assertEqual(host.scope(messages), jetson.scope(messages))
                self.assertFalse({'code_edit', 'code_create', 'code_commit'} & jetson.scope(messages))

    def test_jetson_denies_mutation_before_forwarding(self):
        jetson = load_jetson_tools()
        names = jetson.scope([{'role': 'user', 'content': 'Review src/a.py; do not modify any files.'}])
        with patch('urllib.request.build_opener') as opener:
            result = jetson.execute('code_edit', {'path': 'src/a.py', 'old': '1', 'new': '2', 'sha256': 'fixture'}, names)
        self.assertFalse(result['ok'])
        opener.assert_not_called()

    def test_explicit_manual_requests_match(self):
        jetson = load_jetson_tools()
        for objective in ('Fix and test src/a.py.', 'Please implement the wrapper.',
                          'Review and then fix src/a.py.', 'Please commit the changes.'):
            messages = [{'role': 'user', 'content': objective}]
            self.assertEqual(host.scope(messages), jetson.scope(messages))


if __name__ == '__main__':
    unittest.main()
