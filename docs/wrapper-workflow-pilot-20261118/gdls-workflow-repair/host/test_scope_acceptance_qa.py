"""Independent Group-4 QA for exact write scopes and frozen acceptance."""
import os
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import coding_tools as code
import coordinator as coordinator_module
import coordinator_acceptance as acceptance
from coordinator_store import (
    DEFAULT_CAMPAIGN_ID,
    SELECTED,
    Store,
    task_state_digest,
)


class ScopeAcceptanceQATests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'
        for name in ('src', 'tests', 'docs'):
            (self.root / name).mkdir(parents=True)
        (self.root / 'src/company.py').write_text('def value():\n    return 1\n')
        (self.root / 'src/unassigned.py').write_text('UNASSIGNED = True\n')
        (self.root / 'tests/test_company.py').write_text(
            'from src.company import value\n\n'
            'def test_value():\n    assert value() == 1\n')
        (self.root / 'tests/test_unassigned.py').write_text(
            'def test_unassigned():\n    assert True\n')
        (self.root / 'tests/fixture.json').write_text('{"expected": 1}\n')
        (self.root / 'docs/unassigned.md').write_text('operator document\n')
        (self.root / 'pyproject.toml').write_text('[tool.pytest.ini_options]\n')
        self.root_patch = patch.object(code, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.base = Path(self.tmp.name) / 'tasks'
        self.store = Store(self.base)

    @staticmethod
    def integration(number=1, *, source_targets=None):
        return {
            'company_id': f'COMP-{number:04}',
            'company': f'Canonical Company {number}',
            'configured_url': f'https://canonical.example/company-{number}',
            'tests': ['tests/test_company.py'],
            'source_targets': source_targets or ['src/company.py'],
            'work_order': f'W{number:03}',
            'ats': 'canonical-ats',
        }

    @classmethod
    def spec(cls, number=1, *, source_targets=None):
        integration = cls.integration(number, source_targets=source_targets)
        url = integration['configured_url']
        return {
            'objective': f'Implement reviewed company {number}',
            'tests': list(integration['tests']),
            'mode': 'develop',
            'max_sessions': 10,
            'authorization_version': 1,
            'workflow_version': 2,
            'integration': integration,
            'evidence_requirements': {
                'version': 1,
                'required_files': integration['tests'] + integration['source_targets'],
                'source_targets': [{
                    'url': url,
                    'allowed_urls': [url],
                    'identity_terms': [integration['company']],
                }],
                'read_hints': {},
            },
        }

    def task(self, number=1, *, source_targets=None):
        return self.store.create(**self.spec(number, source_targets=source_targets))

    def paused_task(self, number=1):
        state = self.task(number)
        self.store.configure_queue(False)
        return self.store.update(state['id'], status='PAUSED', stop_requested=True)

    def expand(self, state, paths, reason='Reviewed auxiliary edit'):
        return self.store.expand_edit_scope(
            state['id'], paths, reason,
            expected_state_digest=task_state_digest(state),
            expected_scope_digest=state['edit_scope']['digest'])

    def coordinator(self):
        return coordinator_module.Coordinator(
            self.base,
            model=lambda *_: None,
            budget=lambda *_: types.SimpleNamespace(available_generation_tokens=6000),
        )

    def test_host_tool_boundary_allows_only_exact_assigned_paths(self):
        state = self.task(source_targets=['src/company.py', 'src/new_company.py'])
        token = code.EDIT_SCOPE.set(state['edit_scope'])
        try:
            original = (self.root / 'src/company.py').read_bytes()
            assigned = code.execute('code_edit', {
                'path': 'src/company.py',
                'sha256': __import__('hashlib').sha256(original).hexdigest(),
                'old': 'return 1', 'new': 'return 2',
            }, {'code_edit'})
            created = code.execute('code_create', {
                'path': 'src/new_company.py', 'content': 'NEW = True\n',
            }, {'code_create'})
            self.assertTrue(assigned['ok'])
            self.assertTrue(created['ok'])

            before = {
                name: (self.root / name).read_bytes()
                for name in ('src/unassigned.py', 'tests/test_unassigned.py', 'docs/unassigned.md')
            }
            attempts = (
                ('code_edit', {'path': 'src/unassigned.py', 'sha256': '0' * 64,
                               'old': 'True', 'new': 'False'}),
                ('code_edit', {'path': 'tests/test_unassigned.py', 'sha256': '0' * 64,
                               'old': 'True', 'new': 'False'}),
                ('code_edit', {'path': 'docs/unassigned.md', 'sha256': '0' * 64,
                               'old': 'operator', 'new': 'worker'}),
                ('code_create', {'path': 'src/extra.py', 'content': 'bad\n'}),
                ('code_edit', {'path': 'src/../src/company.py', 'sha256': '0' * 64,
                               'old': '2', 'new': '3'}),
            )
            for name, args in attempts:
                with self.subTest(path=args['path']):
                    result = code.execute(name, args, {name})
                    self.assertFalse(result['ok'])
                    self.assertIn('approved edit scope', result['error'])
            self.assertEqual(before, {
                name: (self.root / name).read_bytes() for name in before
            })
            self.assertFalse((self.root / 'src/extra.py').exists())
        finally:
            code.EDIT_SCOPE.reset(token)

    def test_missing_edit_authority_fails_closed_without_filesystem_change(self):
        self.assertIsNone(code.EDIT_SCOPE.get())
        before = (self.root / 'src/company.py').read_bytes()
        result = code.execute('code_edit', {
            'path': 'src/company.py',
            'sha256': __import__('hashlib').sha256(before).hexdigest(),
            'old': 'return 1', 'new': 'return 999',
        }, {'code_edit'})
        self.assertFalse(result['ok'])
        self.assertRegex(result['error'], 'authority|scope')
        self.assertEqual((self.root / 'src/company.py').read_bytes(), before)

    def test_coordinator_binds_scope_and_worker_request_does_not_expand_it(self):
        state = self.task()
        coordinator = self.coordinator()
        current = coordinator_module.manifest()
        state = self.store.update(
            state['id'], manifest=current, status='RUNNING',
            checkpoint={'summary': 'Worker requests src/unassigned.py',
                        'next_action': 'operator scope review', 'outcome': 'blocked'})
        before_scope = state['edit_scope']
        before_file = (self.root / 'src/unassigned.py').read_bytes()
        result = coordinator.execute(state, 'code_edit', {
            'path': 'src/unassigned.py',
            'sha256': __import__('hashlib').sha256(before_file).hexdigest(),
            'old': 'True', 'new': 'False',
        }, {'code_edit'})
        self.assertFalse(result['ok'])
        self.assertEqual(self.store.get(state['id'])['edit_scope'], before_scope)
        self.assertEqual((self.root / 'src/unassigned.py').read_bytes(), before_file)
        self.assertIsNone(code.EDIT_SCOPE.get())

    def test_reviewed_expansion_is_cas_guarded_audited_and_durable(self):
        state = self.paused_task()
        expanded = self.expand(state, ['src/auxiliary.py'], 'Reviewed provider helper')
        self.assertEqual(expanded['edit_scope']['version'], 2)
        self.assertEqual(
            expanded['edit_scope']['paths'],
            ['src/auxiliary.py', 'src/company.py', 'tests/test_company.py'])
        self.assertEqual(expanded['edit_scope']['history'][-1]['added'], ['src/auxiliary.py'])
        self.assertEqual(expanded['edit_scope']['history'][-1]['reason'], 'Reviewed provider helper')
        self.assertEqual(expanded['phase'], 'baseline')
        self.assertIsNone(expanded['baseline_passed'])
        self.assertEqual(Store(self.base).get(state['id'])['edit_scope'], expanded['edit_scope'])

        for paths, reason in ((['src/auxiliary.py'], 'again'),
                              (['src/dup.py', 'src/dup.py'], 'duplicate'),
                              (['src/../src/escape.py'], 'traversal')):
            with self.subTest(paths=paths):
                with self.assertRaises(ValueError):
                    self.expand(expanded, paths, reason)

        with self.assertRaisesRegex(ValueError, 'changed'):
            self.expand(state, ['src/stale.py'], 'stale state')

    def test_expansion_rejects_unsafe_files_active_claims_and_unfinished_receipts(self):
        state = self.paused_task()
        (self.root / 'src/link.py').symlink_to(self.root / 'src/company.py')
        os.link(self.root / 'src/company.py', self.root / 'src/hard.py')
        for path in ('src/link.py', 'src/hard.py'):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    self.expand(state, [path])
        self.assertEqual(self.store.get(state['id'])['edit_scope'], state['edit_scope'])

        for status in ('RUNNING', 'QUEUED', 'PAUSING'):
            with self.subTest(status=status):
                current = self.store.update(state['id'], status=status)
                with self.assertRaisesRegex(ValueError, 'paused safe boundary'):
                    self.expand(current, [f'src/{status.lower()}.py'])
        current = self.store.update(state['id'], status='PAUSED')
        self.store.intent(state['id'], 'implement', 'code_read', {'path': 'src/company.py'})
        with self.assertRaisesRegex(ValueError, 'unfinished'):
            self.expand(current, ['src/pending.py'])

    def test_selected_campaign_claim_must_be_released_before_expansion(self):
        ids, _ = self.store.enqueue_batch(
            'selected-scope', [self.spec(2)], held=True,
            campaign_id=DEFAULT_CAMPAIGN_ID)
        self.store.configure_queue(False)
        self.store.configure_campaign(True, DEFAULT_CAMPAIGN_ID)
        selected = self.store.activate_next_campaign(DEFAULT_CAMPAIGN_ID)
        self.assertEqual(selected['id'], ids[0])
        self.assertEqual(selected['campaign_disposition'], SELECTED)
        self.store.configure_campaign(False, DEFAULT_CAMPAIGN_ID)
        selected = self.store.update(ids[0], status='PAUSED')
        with self.assertRaisesRegex(ValueError, 'claim|selected|safe boundary'):
            self.expand(selected, ['src/claimed.py'])

    def test_concurrent_scope_expansion_commits_exactly_one_review(self):
        state = self.paused_task()
        stores = [Store(self.base), Store(self.base)]
        barrier = threading.Barrier(2)

        def expand(index):
            barrier.wait()
            try:
                return stores[index].expand_edit_scope(
                    state['id'], [f'src/race_{index}.py'], f'review {index}',
                    expected_state_digest=task_state_digest(state),
                    expected_scope_digest=state['edit_scope']['digest'])
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(expand, (0, 1)))
        committed = [result for result in results if result]
        self.assertEqual(len(committed), 1)
        final = self.store.get(state['id'])
        self.assertEqual(final['edit_scope']['version'], 2)
        self.assertEqual(len(final['edit_scope']['history']), 1)

    def test_weakened_current_test_cannot_replace_frozen_original_assertion(self):
        state = self.task()
        state = acceptance.ensure_bundle(self.store, state, self.root)
        (self.root / 'tests/test_company.py').write_text('def test_value():\n    pass\n')
        (self.root / 'src/company.py').write_text('def value():\n    return 2\n')
        state = self.store.update(
            state['id'], phase='verify', status='QUEUED',
            manifest=coordinator_module.manifest())

        roots = []
        def fake_run(paths):
            current_root = code.root()
            roots.append(current_root)
            test = (current_root / 'tests/test_company.py').read_text()
            source = (current_root / 'src/company.py').read_text()
            failed = 'assert value() == 1' in test and 'return 2' in source
            return {'exit_code': 1 if failed else 0, 'timed_out': False,
                    'output': 'FAILED frozen assertion' if failed else 'passed'}

        coordinator = self.coordinator()
        with patch.object(code, 'run_tests', side_effect=fake_run), \
             patch.object(code, 'git', return_value='diff --git a/src/company.py b/src/company.py\n'):
            coordinator.step(state['id'])
        final = self.store.get(state['id'])
        self.assertEqual(final['status'], 'PAUSED_TEST_FAILURE')
        receipts = self.store.receipts(state['id'])
        current = next(r for r in receipts if r['name'] == 'code_test')
        frozen = next(r for r in receipts if r['name'] == 'acceptance_test')
        self.assertEqual(current['result']['result']['exit_code'], 0)
        self.assertEqual(frozen['result']['result']['exit_code'], 1)
        self.assertTrue(frozen['result']['result']['independent_acceptance'])
        self.assertEqual(frozen['result']['result']['edited_source_origin'], str(self.root / 'src'))
        self.assertEqual(frozen['result']['result']['command'],
                         ['coding_tools.run_tests', 'tests/test_company.py'])
        self.assertEqual(frozen['result']['result']['bundle_digest_before'],
                         frozen['result']['result']['bundle_digest_after'])
        self.assertEqual(frozen['result']['result']['edit_scope_digest'],
                         state['edit_scope']['digest'])
        self.assertEqual(frozen['result']['result']['edit_scope_version'],
                         state['edit_scope']['version'])
        self.assertEqual(frozen['result']['result']['source_manifest_digest'],
                         acceptance.digest(frozen['result']['result']['source_manifest']))
        self.assertEqual(len(roots), 2)
        self.assertEqual(roots[0], self.root)
        self.assertNotEqual(roots[1], self.root)

    def test_correct_source_requires_both_current_and_frozen_tests(self):
        state = self.task()
        state = acceptance.ensure_bundle(self.store, state, self.root)
        state = self.store.update(
            state['id'], phase='verify', status='QUEUED',
            manifest=coordinator_module.manifest())
        coordinator = self.coordinator()
        with patch.object(code, 'run_tests', return_value={
                'exit_code': 0, 'timed_out': False, 'output': 'passed'}), \
             patch.object(code, 'git', return_value='diff --git a/src/company.py b/src/company.py\n'):
            coordinator.step(state['id'])
        final = self.store.get(state['id'])
        self.assertEqual(final['status'], 'AWAITING_LIVE_VALIDATION')
        self.assertEqual(
            [r['name'] for r in self.store.receipts(state['id'])],
            ['code_test', 'acceptance_test', 'code_diff'])

    def test_source_change_after_acceptance_cannot_enter_offline_ready_gate(self):
        state = self.task()
        state = acceptance.ensure_bundle(self.store, state, self.root)
        state = self.store.update(
            state['id'], phase='verify', status='QUEUED',
            manifest=coordinator_module.manifest())
        coordinator = self.coordinator()

        def mutate_during_diff(*_args):
            (self.root / 'src/company.py').write_text(
                'def value():\n    return 777\n')
            return 'diff --git a/src/company.py b/src/company.py\n'

        with patch.object(code, 'run_tests', return_value={
                'exit_code': 0, 'timed_out': False, 'output': 'passed'}), \
             patch.object(code, 'git', side_effect=mutate_during_diff):
            coordinator.step(state['id'])
        final = self.store.get(state['id'])
        self.assertNotEqual(final['status'], 'AWAITING_LIVE_VALIDATION')
        self.assertTrue(final['status'].startswith('PAUSED'))
        receipts = self.store.receipts(state['id'])
        acceptance_receipt = next(r for r in receipts if r['name'] == 'acceptance_test')
        self.assertEqual(acceptance_receipt['result']['result']['source_manifest_digest'],
                         acceptance.digest(acceptance_receipt['result']['result']['source_manifest']))
        diff_receipt = next(r for r in receipts if r['name'] == 'code_diff')
        self.assertFalse(diff_receipt['result']['source_unchanged_during_diff'])

    def test_missing_assertion_and_changed_pre_capture_inputs_fail_closed(self):
        (self.root / 'tests/test_company.py').write_text('def test_value():\n    pass\n')
        no_assertion = self.task(3)
        coordinator = self.coordinator()
        with patch.object(code, 'run_tests') as run:
            coordinator.step(no_assertion['id'])
        final = self.store.get(no_assertion['id'])
        self.assertEqual(final['status'], 'PAUSED_BLOCKED')
        self.assertIn('lacks an original independent acceptance assertion', final['reason'])
        run.assert_not_called()

        (self.root / 'tests/test_company.py').write_text(
            'from src.company import value\n\ndef test_value():\n    assert value() == 1\n')
        drift = self.task(4)
        (self.root / 'tests/fixture.json').write_text('{"expected": 2}\n')
        with self.assertRaisesRegex(ValueError, 'changed since assignment'):
            acceptance.ensure_bundle(self.store, drift, self.root)

    def test_tampered_bundle_test_fixture_or_config_stops_before_execution(self):
        state = self.task()
        state = acceptance.ensure_bundle(self.store, state, self.root)
        bundle_root = acceptance.bundle_path(self.store, state)
        originals = {
            name: (bundle_root / name).read_bytes()
            for name in ('tests/test_company.py', 'tests/fixture.json', 'pyproject.toml')
        }
        for name, original in originals.items():
            with self.subTest(name=name):
                path = bundle_root / name
                path.write_bytes(original + b'\n# tampered\n')
                with patch.object(code, 'run_tests') as run:
                    with self.assertRaisesRegex(ValueError, 'hash changed'):
                        acceptance.verify_bundle(self.store, state, self.root)
                run.assert_not_called()
                path.write_bytes(original)

        token = code.EDIT_SCOPE.set(state['edit_scope'])
        try:
            frozen = bundle_root / 'tests/test_company.py'
            result = code.execute('code_edit', {
                'path': frozen.as_posix(),
                'sha256': '0' * 64, 'old': 'assert', 'new': 'pass',
            }, {'code_edit'})
            self.assertFalse(result['ok'])
            self.assertEqual(frozen.read_bytes(), originals['tests/test_company.py'])
        finally:
            code.EDIT_SCOPE.reset(token)

    def test_source_change_during_frozen_run_fails_closed(self):
        state = self.task()
        state = acceptance.ensure_bundle(self.store, state, self.root)

        def mutate_source(_paths):
            (self.root / 'src/company.py').write_text(
                'def value():\n    return 999\n')
            return {'exit_code': 0, 'timed_out': False, 'output': 'passed'}

        with patch.object(code, 'run_tests', side_effect=mutate_source):
            with self.assertRaisesRegex(ValueError, 'changed during verification'):
                acceptance.verify_bundle(self.store, state, self.root)


if __name__ == '__main__':
    unittest.main()
