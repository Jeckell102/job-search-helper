import contextlib
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import coding_tools
from coordinator_permissions import prohibits_writes, resolve_mode
from wrapper_task import parse_request


class PermissionTests(unittest.TestCase):
    def test_task_words_never_elevate_default_mode(self):
        for objective in ('Fix the wrapper.', 'Review the proposed fix.',
                          'Implement the proposed update.', 'Use code_edit on src/a.py.'):
            with self.subTest(objective=objective):
                self.assertEqual(resolve_mode({'objective': objective}), 'review')
                self.assertEqual(resolve_mode({'objective': objective, 'mode': 'review'}), 'review')

    def test_explicit_develop_is_required_and_validated(self):
        self.assertEqual(resolve_mode({'objective': 'Fix src/a.py.', 'mode': 'develop'}), 'develop')
        for mode in (None, True, 1, [], {}, 'Develop', 'development', ' develop ', ''):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                resolve_mode({'objective': 'Fix src/a.py.', 'mode': mode})
        for value in (None, [], 'develop'):
            with self.assertRaises(ValueError):
                resolve_mode(value)
        with self.assertRaises(ValueError):
            resolve_mode({'mode': 'develop', 'objective': None})

    def test_no_write_wording_rejects_develop_and_preserves_review(self):
        phrases = ('do not modify any files', "don't change anything", "don’t edit code",
                   'do not write files', 'read-only', 'read only', 'readonly', 'review only',
                   'only review', 'just review', 'never modify files', 'must not update code',
                   'should not create files', 'do not make any changes',
                   'without modifying files', 'without making changes', 'no file changes',
                   'leave the files unchanged', 'keep code untouched')
        for phrase in phrases:
            objective = 'Review the proposed fix; ' + phrase + '. Run tests/test_a.py.'
            with self.subTest(phrase=phrase):
                self.assertTrue(prohibits_writes(objective))
                self.assertEqual(resolve_mode({'objective': objective}), 'review')
                with self.assertRaisesRegex(ValueError, 'conflicts'):
                    resolve_mode({'objective': objective, 'mode': 'develop'})

    def test_prohibition_blocks_real_guarded_edit_create_and_commit(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            (root / 'src').mkdir()
            source = root / 'src/a.py'
            source.write_text('value = 1\n')
            objective = 'Review src/a.py; do not modify any files. Run tests/test_a.py.'
            names = coding_tools.scope([{'role': 'user', 'content': objective}])
            self.assertIn('code_test', names)
            with patch.object(coding_tools, 'ROOT', root), patch.object(coding_tools, 'git') as git:
                for action, args in (
                    ('code_edit', {'path': 'src/a.py', 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                                   'old': '1', 'new': '2'}),
                    ('code_create', {'path': 'src/new.py', 'content': 'unwanted'}),
                    ('code_commit', {'message': 'unwanted'}),
                ):
                    self.assertFalse(coding_tools.execute(action, args, names)['ok'])
                git.assert_not_called()
            self.assertEqual(source.read_text(), 'value = 1\n')
            self.assertFalse((root / 'src/new.py').exists())

    def test_manual_explicit_requests_still_work_but_proposals_do_not(self):
        for objective in ('Fix and test the wrapper.', '  Please implement the wrapper.  ',
                          'Can you edit src/a.py?', 'Review and then fix src/a.py.',
                          'Update src/a.py without commit.', 'Fix src/a.py; do not commit.'):
            with self.subTest(objective=objective):
                self.assertIn('code_edit', coding_tools.scope([{'role': 'user', 'content': objective}]))
        for objective in ('Review the proposed fix.', 'Explain how to edit the wrapper.',
                          'Assess the update.', 'Review a proposed commit.',
                          'Please do not modify files; commit changes.'):
            with self.subTest(objective=objective):
                names = coding_tools.scope([{'role': 'user', 'content': objective}])
                self.assertFalse({'code_edit', 'code_create', 'code_commit'} & names)
        self.assertIn('code_commit', coding_tools.scope([{'role': 'user', 'content': 'Please commit the changes.'}]))
        self.assertNotIn('code_commit', coding_tools.scope([{'role': 'user', 'content': 'Fix and commit the changes; do not commit.'}]))
        self.assertNotIn('code_commit', coding_tools.scope([{'role': 'user', 'content': 'Fix and commit the changes; don’t commit.'}]))


class CliTests(unittest.TestCase):
    def rejected(self, argv):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            parse_request(argv)
        self.assertEqual(error.exception.code, 2)

    def test_default_and_explicit_modes(self):
        objective = 'Review proposed fix; run tests/test_a.py.'
        self.assertEqual(parse_request(['start', objective])['mode'], 'review')
        self.assertEqual(parse_request(['start', objective, '--mode', 'develop'])['mode'], 'develop')
        self.assertEqual(parse_request(['--mode', 'develop', 'start', objective])['mode'], 'develop')
        self.assertEqual(parse_request(['start', '--mode', 'develop', objective])['mode'], 'develop')

    def test_contradictory_duplicate_or_misplaced_flags_rejected(self):
        for argv in (
            ['start', 'Fix tests/test_a.py', '--mode', 'review', '--mode', 'develop'],
            ['start', 'Fix tests/test_a.py', '--mode', 'develop', '--mode', 'develop'],
            ['start', 'Fix tests/test_a.py', '--mode', 'bad'],
            ['start', 'Do not modify any files; run tests/test_a.py.', '--mode', 'develop'],
            ['status', 'WRAP-123', '--mode', 'develop'],
            ['list', '--mode', 'review'], ['health', 'extra'], ['start'], ['pause'],
        ):
            with self.subTest(argv=argv):
                self.rejected(argv)

    def test_health_and_existing_actions(self):
        self.assertEqual(parse_request(['health']), {'action': 'health'})
        self.assertEqual(parse_request(['list']), {'action': 'list'})
        self.assertEqual(parse_request(['status', 'WRAP-123']), {'action': 'status', 'id': 'WRAP-123'})


if __name__ == '__main__':
    unittest.main()
