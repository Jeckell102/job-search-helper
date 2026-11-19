"""Independent Group-7 QA for scheduler ownership and assignment baselines."""
import json
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import coding_tools as code
import coordinator as coordinator_module
import coordinator_workspace
from backfill_campaign_metadata import backfill_campaign_identity
from coordinator_acceptance import files as acceptance_files
from coordinator_baseline import binding, files as baseline_files
from coordinator_store import Store, campaign_manifest_digest
from coordinator_workspace import workspace


CAMPAIGN = 'qa-ownership-baseline'


class OwnershipBaselineQATests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'
        self.original = {
            'src/company.py': b'def value():\n    return 1\n',
            'tests/test_company.py': b'from src.company import value\n\ndef test_value():\n    assert value() == 1\n',
            'tests/fixture.json': b'{"expected": 1}\n',
            'docs/wrapper-development-test-protocol.md': b'# Required wrapper development and test protocol\n\nreviewed\n',
            'docs/provider-data.bin': b'provider fixture\x00\x01',
            'pyproject.toml': b'[tool.pytest.ini_options]\naddopts = "-q"\n',
            'title-blacklist.txt': b'intern\n',
            'title-review-list.txt': b'engineer\n',
        }
        self.restore_root()
        self.root_patch = patch.object(code, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.base = Path(self.tmp.name) / 'tasks'
        self.store = Store(self.base)

    def restore_root(self):
        for name, content in self.original.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    @staticmethod
    def integration(number=1):
        return {
            'company_id': f'COMP-{number:04}',
            'company': f'Canonical Company {number}',
            'configured_url': f'https://canonical.example/company-{number}',
            'tests': ['tests/test_company.py'],
            'source_targets': ['src/company.py'],
            'work_order': f'W{number:03}',
            'ats': 'canonical-ats',
        }

    @classmethod
    def spec(cls, number=1):
        integration = cls.integration(number)
        return {
            'objective': f'Implement reviewed company {number}',
            'tests': list(integration['tests']),
            'mode': 'develop', 'max_sessions': 10,
            'authorization_version': 1, 'workflow_version': 2,
            'integration': integration,
            'evidence_requirements': {
                'version': 1,
                'required_files': integration['tests'] + integration['source_targets'],
                'source_targets': [{
                    'url': integration['configured_url'],
                    'allowed_urls': [integration['configured_url']],
                    'identity_terms': [integration['company']],
                }],
                'read_hints': {},
            },
        }

    def imported(self, number=1, *, store=None, campaign=CAMPAIGN):
        store = store or self.store
        task_id = store.enqueue_batch(
            f'ownership-batch-{number}', [self.spec(number)], held=True,
            campaign_id=campaign)[0][0]
        return store.get(task_id)

    def coordinator(self, base=None):
        return coordinator_module.Coordinator(
            base or self.base, model=lambda *_: None,
            budget=lambda *_: types.SimpleNamespace(
                prompt_tokens=100, available_generation_tokens=1000))

    def test_same_process_owner_blocks_direct_run_before_state_change_and_releases(self):
        self.store.configure_queue(False)
        task = self.store.create(**self.spec(900))
        before = self.store.get(task['id'])
        entered, release = threading.Event(), threading.Event()
        owner = self.coordinator()

        def blocked_recovery(*_):
            entered.set()
            release.wait(5)

        owner.store.recover = blocked_recovery
        owner.start()
        self.assertTrue(entered.wait(2))
        with self.assertRaisesRegex(RuntimeError, 'ownership was not acquired'):
            owner._owned_run(owner.scheduler_token)
        contender = self.coordinator()
        contender.stop.set()
        with self.assertRaisesRegex(RuntimeError, 'owns the scheduler'):
            contender.run()
        self.assertEqual(self.store.get(task['id']), before)
        self.assertIsNone(contender.scheduler_lock)

        owner.stop.set()
        owner.wake.set()
        release.set()
        owner.thread.join(5)
        self.assertFalse(owner.thread.is_alive())
        self.assertIsNone(owner.scheduler_lock)

        restarted = self.coordinator()
        restarted.stop.set()
        restarted.run()
        self.assertIsNone(restarted.scheduler_lock)

    def test_cross_process_public_owner_blocks_then_process_exit_allows_restart(self):
        child_base = Path(self.tmp.name) / 'cross-process'
        script = (
            'import time\n'
            'from coordinator import Coordinator\n'
            f'c=Coordinator({str(child_base)!r}, model=lambda *_: None, budget=lambda *_: None)\n'
            'c.start()\n'
            'print("LOCKED", flush=True)\n'
            'time.sleep(30)\n'
        )
        child = subprocess.Popen(
            [sys.executable, '-c', script], cwd=Path(__file__).parent,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        self.assertEqual(child.stdout.readline().strip(), 'LOCKED')

        contender = self.coordinator(child_base)
        contender.stop.set()
        with self.assertRaisesRegex(RuntimeError, 'owns the scheduler'):
            contender.run()
        child.terminate()
        child.wait(5)
        child.stdout.close()
        child.stderr.close()
        restarted = self.coordinator(child_base)
        restarted.stop.set()
        restarted.run()
        self.assertIsNone(restarted.scheduler_lock)

    def test_normal_exception_and_thread_start_failure_release_lock(self):
        normal = self.coordinator(Path(self.tmp.name) / 'normal')
        normal.stop.set()
        normal.run()
        self.assertIsNone(normal.scheduler_lock)

        exceptional = self.coordinator(Path(self.tmp.name) / 'exception')
        with patch.object(exceptional, '_run_loop', side_effect=KeyboardInterrupt('stop')):
            with self.assertRaises(KeyboardInterrupt):
                exceptional.run()
        self.assertIsNone(exceptional.scheduler_lock)
        retry = self.coordinator(Path(self.tmp.name) / 'exception')
        retry.stop.set()
        retry.run()

        failed_start = self.coordinator(Path(self.tmp.name) / 'failed-start')
        with patch.object(threading.Thread, 'start', side_effect=RuntimeError('thread failed')):
            with self.assertRaisesRegex(RuntimeError, 'thread failed'):
                failed_start.start()
        self.assertIsNone(failed_start.scheduler_lock)
        after_failure = self.coordinator(Path(self.tmp.name) / 'failed-start')
        after_failure.stop.set()
        after_failure.run()

    def test_private_loop_cannot_run_without_thread_bound_lock(self):
        coordinator = self.coordinator()
        before = self.store.all()
        with self.assertRaisesRegex(RuntimeError, 'requires this thread to own'):
            coordinator._run_loop()
        self.assertEqual(self.store.all(), before)

    def test_direct_creation_and_campaign_import_pin_the_complete_source(self):
        expected = baseline_files(self.root)
        self.assertEqual(set(expected), set(self.original))
        direct = self.store.create(**self.spec(1))
        imported = self.imported(2)
        self.assertEqual(direct['assignment_baseline'], binding(expected))
        self.assertEqual(imported['assignment_baseline'], binding(expected))
        self.assertNotEqual(direct['assignment_baseline'], {'manifest': {}})

    def test_direct_pins_checkout_while_import_pins_distinct_frozen_queue_base(self):
        frozen = Path(self.tmp.name) / 'queue-base'
        for name, content in self.original.items():
            path = frozen / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (frozen / 'src/company.py').write_text('def value():\n    return 2\n')
        store = Store(Path(self.tmp.name) / 'distinct-source')
        with patch.object(coordinator_workspace, 'batch_source', return_value=frozen):
            direct = store.create(**self.spec(10))
            imported = self.imported(11, store=store, campaign=CAMPAIGN + '-distinct')
            self.assertEqual(direct['assignment_baseline'], binding(baseline_files(self.root)))
            self.assertEqual(imported['assignment_baseline'], binding(baseline_files(frozen)))
            self.assertNotEqual(direct['assignment_baseline'], imported['assignment_baseline'])
            with workspace(store, imported, create=True):
                target = store.base / imported['id'] / 'repo'
                self.assertEqual((target / 'src/company.py').read_text(),
                                 'def value():\n    return 2\n')
                tracked = subprocess.run(
                    ['git', 'ls-files'], cwd=target, check=True,
                    text=True, stdout=subprocess.PIPE).stdout.splitlines()
                self.assertEqual(set(tracked), set(self.original))

    def test_each_source_test_doc_and_root_input_drift_blocks_first_copy(self):
        paths = (
            'src/company.py', 'tests/test_company.py', 'tests/fixture.json',
            'docs/wrapper-development-test-protocol.md', 'docs/provider-data.bin',
            'pyproject.toml', 'title-blacklist.txt', 'title-review-list.txt',
        )
        for index, name in enumerate(paths, 1):
            with self.subTest(path=name):
                self.restore_root()
                store = Store(Path(self.tmp.name) / f'drift-{index}')
                state = self.imported(100 + index, store=store,
                                      campaign=f'{CAMPAIGN}-{index}')
                path = self.root / name
                path.write_bytes(path.read_bytes() + b'changed')
                with self.assertRaisesRegex(ValueError, 'baseline drift'):
                    with workspace(store, state, create=True):
                        pass
                self.assertFalse((store.base / state['id'] / 'repo').exists())
                self.assertEqual(store.receipts(state['id']), [])
                self.assertEqual(store.inference_receipts(state['id']), [])

    def test_missing_pin_and_unpublished_wrong_target_fail_closed(self):
        missing = self.imported(250)
        with self.store.connect() as db:
            state = json.loads(db.execute(
                'SELECT state FROM tasks WHERE id=?', (missing['id'],)).fetchone()[0])
            state.pop('assignment_baseline')
            db.execute('UPDATE tasks SET state=? WHERE id=?',
                       (json.dumps(state), missing['id']))
        with self.assertRaisesRegex(ValueError, 'missing or invalid'):
            with workspace(self.store, self.store.get(missing['id']), create=True):
                pass
        self.assertFalse((self.store.base / missing['id'] / 'repo').exists())

        valid = self.imported(251)
        target = self.store.base / valid['id'] / 'repo'
        target.mkdir(parents=True)
        (target / 'src').mkdir()
        (target / 'src/company.py').write_text('unreviewed staged copy\n')
        with self.assertRaisesRegex(ValueError, 'baseline drift'):
            with workspace(self.store, valid, create=True):
                pass
        self.assertEqual((target / 'src/company.py').read_text(),
                         'unreviewed staged copy\n')

    def test_ordinary_resume_cannot_approve_direct_or_imported_baseline_drift(self):
        direct = self.store.create(**self.spec(300))
        self.store.configure_queue(False)
        direct = self.store.pause_task(direct['id'], 'Operator paused before first activation.')
        (self.root / 'docs/provider-data.bin').write_bytes(b'drifted direct input')
        with self.assertRaisesRegex(ValueError, 'baseline drift'):
            self.coordinator().command({'action': 'resume', 'id': direct['id']})
        self.assertEqual(self.store.get(direct['id'])['status'], 'PAUSED')

        self.restore_root()
        imported = self.imported(301)
        (self.root / 'title-review-list.txt').write_text('changed review list\n')
        with self.assertRaisesRegex(ValueError, 'baseline drift'):
            self.coordinator().command({'action': 'resume', 'id': imported['id']})
        final = self.store.get(imported['id'])
        self.assertEqual(final['campaign_disposition'], 'HELD_FOR_CAMPAIGN')
        self.assertEqual(final['status'], 'PAUSED')
        self.assertFalse((self.store.base / imported['id'] / 'repo').exists())

    def test_private_initial_step_cannot_bless_drift_or_invoke_model(self):
        state = self.store.create(**self.spec(350))
        calls = []
        coordinator = coordinator_module.Coordinator(
            self.base, model=lambda *_: calls.append(1),
            budget=lambda *_: types.SimpleNamespace(
                prompt_tokens=100, available_generation_tokens=1000))
        (self.root / 'tests/fixture.json').write_text('{"expected": 999}\n')
        with self.assertRaisesRegex(ValueError, 'baseline drift'):
            coordinator._step(state['id'])
        final = self.store.get(state['id'])
        self.assertIsNone(final['activated_at'])
        self.assertEqual(final['manifest'], {})
        self.assertEqual(self.store.receipts(state['id']), [])
        self.assertEqual(calls, [])

    def test_source_change_during_copy_rejects_staged_workspace(self):
        state = self.imported(400)
        source_path = self.root / 'src/company.py'
        original_read = Path.read_bytes
        reads = 0

        def racing_read(path):
            nonlocal reads
            if path == source_path:
                reads += 1
                if reads == 2:
                    path.write_text('def value():\n    return 999\n')
            return original_read(path)

        with patch.object(Path, 'read_bytes', racing_read):
            with self.assertRaisesRegex(ValueError, 'baseline drift|changed while copying'):
                with workspace(self.store, state, create=True):
                    pass
        self.assertGreaterEqual(reads, 2)
        self.assertFalse((self.store.base / state['id'] / 'repo').exists())

    def test_published_workspace_tracks_every_root_input_in_git(self):
        state = self.imported(500)
        with workspace(self.store, state, create=True):
            target = self.store.base / state['id'] / 'repo'
            result = subprocess.run(
                ['git', 'ls-files'], cwd=target, check=True,
                text=True, stdout=subprocess.PIPE)
        tracked = set(result.stdout.splitlines())
        self.assertEqual(tracked, set(self.original))
        self.assertEqual(baseline_files(target), state['assignment_baseline']['manifest'])

    def test_retry_preserves_reviewed_assignment_and_acceptance_baselines(self):
        original = self.imported(600)
        self.store.configure_campaign(True, CAMPAIGN)
        self.store.activate_next_campaign(CAMPAIGN)
        self.store.update(original['id'], status='PAUSED_ERROR', reason='reviewed retry')
        self.store.reconcile_campaign(CAMPAIGN)
        self.assertFalse(self.store.queue_enabled())
        original = self.store.get(original['id'])
        reviewed_assignment = original['assignment_baseline']
        reviewed_acceptance = original['acceptance_baseline_manifest']

        (self.root / 'src/company.py').write_text('def value():\n    return 999\n')
        retry = self.store.retry_campaign_task(original['id'])
        self.assertEqual(retry['assignment_baseline'], reviewed_assignment)
        self.assertEqual(retry['acceptance_baseline_manifest'], reviewed_acceptance)
        with self.assertRaisesRegex(ValueError, 'baseline drift'):
            with workspace(self.store, retry, create=True):
                pass
        self.assertFalse((self.store.base / retry['id'] / 'repo').exists())

    def test_reviewed_102_member_assignment_backfill_is_exact_and_idempotent(self):
        store = Store(Path(self.tmp.name) / 'legacy-102')
        store.configure_queue(False)
        items, ids = [], []
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for number in range(1, 103):
                spec = self.spec(number)
                state = store.new_state(**spec)
                state.update(
                    isolated_workspace=True, status='PAUSED', stop_requested=False,
                    reason='Held for one-company campaign selection.',
                    campaign_id=CAMPAIGN,
                    campaign_company_id=spec['integration']['company_id'],
                    campaign_disposition='HELD_FOR_CAMPAIGN')
                state['campaign_manifest_digest'] = campaign_manifest_digest(state)
                state.pop('assignment_baseline', None)
                db.execute('INSERT INTO tasks VALUES (?,?)',
                           (state['id'], json.dumps(state)))
                ids.append(state['id'])
                items.append({'objective': spec['objective'],
                              'integration': spec['integration']})
            db.execute('INSERT INTO batches VALUES (?,?)',
                       ('reviewed-original-102', json.dumps(ids)))

        expected_assignment = baseline_files(self.root)
        expected_acceptance = acceptance_files(self.root)
        dry = backfill_campaign_identity(
            store, items, baseline_root=self.root,
            expected_baseline_manifest=expected_acceptance,
            expected_assignment_manifest=expected_assignment)
        self.assertEqual(len(dry['matched']), 102)
        self.assertEqual(len(dry['changed']), 102)
        self.assertFalse(any('assignment_baseline' in store.get(task) for task in ids))

        applied = backfill_campaign_identity(
            store, items, apply=True, baseline_root=self.root,
            expected_baseline_manifest=expected_acceptance,
            expected_assignment_manifest=expected_assignment)
        self.assertEqual(len(applied['changed']), 102)
        expected_binding = binding(expected_assignment)
        self.assertTrue(all(store.get(task)['assignment_baseline'] == expected_binding
                            for task in ids))
        rerun = backfill_campaign_identity(
            store, items, apply=True, baseline_root=self.root,
            expected_baseline_manifest=expected_acceptance,
            expected_assignment_manifest=expected_assignment)
        self.assertEqual(rerun['changed'], [])
        self.assertEqual(len(rerun['matched']), 102)
        before = store.get(ids[0])
        (self.root / 'pyproject.toml').write_text('[tool.pytest.ini_options]\naddopts = "-x"\n')
        with self.assertRaisesRegex(ValueError, 'whole baseline differs'):
            backfill_campaign_identity(
                store, items, apply=True, baseline_root=self.root,
                expected_baseline_manifest=expected_acceptance,
                expected_assignment_manifest=expected_assignment)
        self.assertEqual(store.get(ids[0]), before)


if __name__ == '__main__':
    unittest.main()
