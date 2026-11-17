import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

# The staged gateway shares the host permission module; deployment installs the
# same module beside wrapper_commands on Jetson.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import wrapper_commands as commands


class WrapperCommandTests(unittest.TestCase):
    def test_default_review_never_infers_authority_from_words(self):
        for objective in ('Fix src/a.py tests/test_a.py', 'Review a proposed fix tests/test_a.py',
                          'Do not modify files tests/test_a.py'):
            with self.subTest(objective=objective):
                self.assertEqual(commands.parse_command('/wrapper start ' + objective),
                                 {'action': 'start', 'objective': objective, 'mode': 'review'})

    def test_explicit_develop_flag_before_objective(self):
        self.assertEqual(commands.parse_command('/wrapper start --develop Fix src/a.py tests/test_a.py'),
                         {'action': 'start', 'objective': 'Fix src/a.py tests/test_a.py', 'mode': 'develop'})
        self.assertEqual(commands.parse_command('/wrapper start --review Read tests/test_a.py')['mode'], 'review')
        self.assertEqual(commands.parse_command('/wrapper start --develop\tFix tests/test_a.py')['mode'], 'develop')

    def test_contradictory_duplicate_unknown_and_misplaced_flags_rejected(self):
        for text in ('/wrapper start --review --develop Fix tests/test_a.py',
                     '/wrapper start --develop --develop Fix tests/test_a.py',
                     '/wrapper start --unsafe Fix tests/test_a.py',
                     '/wrapper start Fix tests/test_a.py --develop',
                     '/wrapper start --develop', '/wrapper list extra',
                     '/wrapper start --develop Do not modify any files; tests/test_a.py',
                     '/wrapper status WRAP-123 --develop', '/wrapper health extra'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                commands.parse_command(text)

    def test_non_commands_help_and_health(self):
        self.assertIsNone(commands.parse_command('Please fix src/a.py'))
        self.assertIsNone(commands.parse_command('/wrappers start test'))
        self.assertEqual(commands.parse_command('/wrapper'), {'action': 'help'})
        self.assertEqual(commands.parse_command('/wrapper help'), {'action': 'help'})
        self.assertEqual(commands.parse_command('/wrapper health'), {'action': 'health'})
        self.assertIn('--develop', commands.command('/wrapper help'))

    def test_bad_command_never_sends_request(self):
        with patch.object(commands.urllib.request, 'build_opener') as opener:
            result = commands.command('/wrapper start --develop --review Fix tests/test_a.py')
        opener.assert_not_called()
        self.assertIn('at most one mode flag', result)

    def test_mode_and_objective_forwarded_without_jetson_persistence(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'ok': True, 'text': 'Fixture task created.'}).encode()
        opener = Mock()
        opener.open.return_value = response
        with patch.object(commands.Path, 'read_text', return_value='{"token":"fixture-token"}'), \
             patch.object(commands.urllib.request, 'build_opener', return_value=opener):
            result = commands.command('/wrapper start --develop Fix src/a.py; tests/test_a.py')
        sent = json.loads(opener.open.call_args.args[0].data)
        self.assertEqual(sent['mode'], 'develop')
        self.assertIn('Fix src/a.py', sent['objective'])
        self.assertEqual(result, 'Fixture task created.')

    def test_no_write_conflict_never_sends_request(self):
        with patch.object(commands.urllib.request, 'build_opener') as opener:
            result = commands.command('/wrapper start --develop Do not modify any files; tests/test_a.py')
        opener.assert_not_called()
        self.assertIn('conflicts with a no-write instruction', result)


if __name__ == '__main__':
    unittest.main()
