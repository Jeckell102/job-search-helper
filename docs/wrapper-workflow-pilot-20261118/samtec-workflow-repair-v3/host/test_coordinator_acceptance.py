"""Frozen assertions run against the edited source, independently of editable tests."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import coding_tools as code
import coordinator_acceptance as acceptance
from coordinator_store import Store, task_state_digest


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'
        for name in ('src', 'tests', 'docs'):
            (self.root / name).mkdir(parents=True)
        (self.root / 'src/company.py').write_text('value = 1\n')
        (self.root / 'tests/test_company.py').write_text('from company import value\ndef test_company():\n    assert value == 2\n')
        (self.root / 'tests/fixture.json').write_text('{"expected":2}')
        (self.root / 'pyproject.toml').write_text('[tool.pytest.ini_options]\n')
        context = patch.object(code, 'ROOT', self.root)
        context.start()
        self.addCleanup(context.stop)
        self.store = Store(Path(self.tmp.name) / 'tasks')
        self.state = self.store.create('Inspect src/company.py and tests/test_company.py', ['tests/test_company.py'], 'develop', authorization_version=1)
        self.store.configure_queue(False)

    def runner(self, paths):
        command = [sys.executable, '-B', '-c', 'import runpy; m=runpy.run_path("tests/test_company.py"); m["test_company"]()']
        value = subprocess.run(command, cwd=code.root(), env={**os.environ, 'PYTHONPATH': str(code.root() / 'src')}, capture_output=True)
        return {'exit_code': value.returncode, 'timed_out': False, 'output': value.stderr.decode()}

    def test_direct_and_imported_tasks_pin_their_actual_distinct_baselines(self):
        base = Path(self.tmp.name) / 'installed'
        shared, frozen = base / 'repo', base / 'queue-base'
        for root, assertion in ((shared, '1 == 1'), (frozen, '2 == 2')):
            (root / 'tests').mkdir(parents=True)
            (root / 'tests/test_company.py').write_text('def test_company(): assert ' + assertion + '\n')
        with patch.object(code, 'BASE', base), patch.object(code, 'ROOT', shared):
            direct = self.store.create('Inspect src/company.py and tests/test_company.py',
                ['tests/test_company.py'], 'develop', authorization_version=1)
            spec = dict(objective='Inspect src/company.py and tests/test_company.py',
                tests=['tests/test_company.py'], mode='develop', max_sessions=10,
                authorization_version=1, evidence_requirements={}, workflow_version=2,
                integration=dict(company_id='COMP-0001', company='Company',
                    configured_url='https://example.com/company',
                    tests=['tests/test_company.py'], source_targets=['src/company.py']))
            imported = self.store.enqueue_batch('different-baselines', [spec], held=True)[0][0]
            self.assertEqual(direct['acceptance_baseline_manifest'], acceptance.files(shared))
            self.assertEqual(self.store.get(imported)['acceptance_baseline_manifest'], acceptance.files(frozen))
            self.assertNotEqual(direct['acceptance_baseline_manifest'], self.store.get(imported)['acceptance_baseline_manifest'])
            acceptance.ensure_bundle(self.store, direct, shared)

    def test_weakened_editable_test_cannot_hide_bad_source(self):
        state = acceptance.ensure_bundle(self.store, self.state, self.root)
        (self.root / 'tests/test_company.py').write_text('def test_company(): pass\n')
        with patch.object(code, 'run_tests', side_effect=self.runner):
            self.assertNotEqual(acceptance.verify_bundle(self.store, state, self.root)['exit_code'], 0)
            (self.root / 'src/company.py').write_text('value = 2\n')
            result = acceptance.verify_bundle(self.store, state, self.root)
            self.assertEqual(result['exit_code'], 0)
            self.assertTrue(result['independent_acceptance'])
            self.assertEqual(result['edit_scope_digest'], state['edit_scope']['digest'])
            self.assertEqual(result['edit_scope_version'], state['edit_scope']['version'])
            self.assertEqual(result['edited_source_origin'], str(self.root / 'src'))

    def test_source_change_after_acceptance_prevents_offline_promotion(self):
        import coordinator
        co = coordinator.Coordinator(self.store.base, model=lambda *args: self.fail('No inference expected'))
        self.store.configure_queue(True)
        self.store.update(self.state['id'], phase='verify', status='RUNNING')
        original = acceptance.verify_bundle
        def changed_after_proof(*args):
            result = original(*args)
            (self.root / 'src/company.py').write_text('value = 999\n')
            return result
        with patch.object(code, 'run_tests', return_value={'exit_code': 0, 'timed_out': False}), patch.object(code, 'git', return_value=''), patch.object(acceptance, 'verify_bundle', side_effect=changed_after_proof):
            co.step(self.state['id'])
        current = self.store.get(self.state['id'])
        self.assertEqual(current['status'], 'PAUSED_FILES_CHANGED')
        self.assertIn('changed', current['reason'])

    def test_unreceipted_test_change_before_first_capture_rejected(self):
        (self.root / 'tests/test_company.py').write_text('def test_company(): assert True\n')
        with self.assertRaisesRegex(ValueError, 'changed since assignment'):
            acceptance.ensure_bundle(self.store, self.state, self.root)

    def test_fixture_and_config_tampering_fail_before_runner(self):
        state = acceptance.ensure_bundle(self.store, self.state, self.root)
        target = acceptance.bundle_path(self.store, state) / 'tests/fixture.json'
        target.write_text('{}')
        with patch.object(code, 'run_tests') as runner, self.assertRaises(ValueError):
            acceptance.verify_bundle(self.store, state, self.root)
        runner.assert_not_called()

    def test_exact_scope_prevents_unassigned_write(self):
        token = code.EDIT_SCOPE.set(self.state['edit_scope'])
        try:
            denied = code.execute('code_create', {'path': 'src/other.py', 'content': 'bad'}, {'code_create'})
            self.assertFalse(denied['ok'])
            self.assertFalse((self.root / 'src/other.py').exists())
            source = self.root / 'src/company.py'
            allowed = code.execute('code_edit', {'path': 'src/company.py', 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'old': '1', 'new': '2'}, {'code_edit'})
            self.assertTrue(allowed['ok'])
        finally:
            code.EDIT_SCOPE.reset(token)

    def test_expansion_audits_and_invalidates_evidence_without_resetting_budget(self):
        task = self.state['id']
        self.store.update(task, status='PAUSED', calls=3)
        state = self.store.get(task)
        expanded = self.store.expand_edit_scope(task, ['docs/report.md'], 'Reviewed handoff destination', expected_state_digest=task_state_digest(state), expected_scope_digest=state['edit_scope']['digest'])
        self.assertEqual(expanded['calls'], 3)
        self.assertEqual(expanded['edit_scope']['version'], 2)
        self.assertEqual(expanded['edit_scope']['history'][0]['added'], ['docs/report.md'])
        self.assertGreater(expanded['evidence_epoch'], 0)
        with self.assertRaises(ValueError):
            self.store.expand_edit_scope(task, ['src/extra.py'], 'Stale approval', expected_state_digest=task_state_digest(state), expected_scope_digest=state['edit_scope']['digest'])


if __name__ == '__main__':
    unittest.main()
