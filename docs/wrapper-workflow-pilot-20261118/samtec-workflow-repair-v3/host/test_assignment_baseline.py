"""Whole-assignment pins cover opaque fixtures and first-use source changes."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import coding_tools as code
from coordinator import Coordinator
from coordinator_baseline import files, binding, verify
from coordinator_workspace import workspace

class AssignmentBaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'source'
        for name in ('src', 'tests', 'docs'):
            (self.root / name).mkdir(parents=True)
        (self.root / 'src/a.py').write_text('a=1\n')
        (self.root / 'tests/test_a.py').write_text('def test_a(): assert True\n')
        (self.root / 'tests/input.yaml').write_text('expected: 1\n')
        (self.root / 'pyproject.toml').write_text('[project]\nname="test"\n')
        p = patch.object(code, 'ROOT', self.root)
        p.start(); self.addCleanup(p.stop)
        self.co = Coordinator(Path(self.tmp.name) / 'tasks')

    def state(self):
        return self.co.store.create('Inspect src/a.py tests/test_a.py', ['tests/test_a.py'], 'review')

    def test_pin_covers_opaque_fixture_and_root_input(self):
        state = self.state()
        self.assertIn('tests/input.yaml', state['assignment_baseline']['manifest'])
        self.assertIn('pyproject.toml', state['assignment_baseline']['manifest'])
        (self.root / 'tests/input.yaml').write_text('expected: 2\n')
        with self.assertRaisesRegex(ValueError, 'baseline drift'):
            verify(state, self.root)
        with self.assertRaisesRegex(ValueError, 'baseline drift'):
            self.co.step(state['id'])
        self.assertEqual(self.co.store.receipts(state['id']), [])

    def test_missing_pin_and_unsafe_nested_directory_rejected(self):
        with self.assertRaisesRegex(ValueError, 'missing or invalid'):
            verify({}, self.root)
        (self.root / 'tests/link').symlink_to(self.root / 'src', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            files(self.root)

    def test_assignment_binding_cannot_be_overwritten(self):
        state = self.state()
        with self.assertRaises(ValueError):
            self.co.store.update(state['id'], assignment_baseline=binding({}))

    def test_direct_and_internal_scheduler_entrypoints_require_lock(self):
        with self.assertRaisesRegex(RuntimeError, 'own the lock'):
            self.co._run_loop()
        token = self.co._acquire_scheduler()
        try:
            other = Coordinator(self.co.store.base)
            with patch.object(other.store, 'recover') as recover:
                with self.assertRaises(RuntimeError):
                    other.run()
                recover.assert_not_called()
        finally:
            self.co._release_scheduler(token)
        self.co.stop.set()
        self.co.run()
        self.assertIsNone(self.co.scheduler_lock)
